"""Validate-phase orchestration for the legacy-import pipeline.

Roadmap PR19A2 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §9,
§10, §11, §12, §13). Implements the complete, generic lease-acquisition /
heartbeat-renewal / completion-fencing / failure-fencing mechanism (§9)
for the first time, wired into `VALIDATING` -- what makes `validate` safe
to merge and deploy on its own (§25).

The renewal-loop/bound-failure-message/fence-lost-audit mechanics
(§9.2/§9.4.2/§19) live in `app.services.import_lease`, shared unchanged
with dry-run and execute (§25: "PR19A3 adds no new lease, heartbeat,
fencing, or recovery code" -- the converse also holds, PR19A2 does not
keep a private copy either). This module retains only what is genuinely
`validate`-specific: parsing, business-rule evaluation, and row-finding
persistence.
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime, timezone
from typing import NoReturn

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AUDIT_ACTION_IMPORT_RECOVERY, AUDIT_ENTITY_IMPORT_SESSION, record_audit_event
from app.core.config import settings
from app.core.exceptions import (
    ImportAdapterNotRegisteredError,
    ImportAttemptInProgressError,
    ImportRecoveryRequiredError,
    ImportSessionInvalidStateError,
    ImportSourceNotRegisteredError,
)
from app.crud import import_job as import_job_crud
from app.crud import import_session as import_session_crud
from app.crud import import_source_blob as import_source_blob_crud
from app.models.import_session import ImportRowError, ImportSession
from app.services import import_lease
from app.services.import_adapter import MAX_IMPORT_ROWS, get_adapter
from app.services.import_source_reader import ImportSourceReader, SourceDescriptor

logger = logging.getLogger(__name__)


class _RowLimitExceededError(Exception):
    """Internal marker -- follows the same TX1/TX2 failure path (§9.4.2)
    as any other domain exception raised while parsing/validating; never
    surfaced to the client as a distinct error code."""


class _FenceLostDuringSuccessError(Exception):
    """Internal marker: the success-path fencing UPDATE(s) affected zero
    rows (§9.4.1 step 6). Caught by the same generic failure handler as a
    genuine domain exception -- both follow the identical TX1-rollback/TX2
    path (§9.4.2)."""


async def _raise_for_non_admittable_session(db: AsyncSession, session_id: uuid.UUID) -> NoReturn:
    """Re-fetches the session and classifies exactly why validate cannot
    proceed from its current state -- used both for the up-front check and
    after a lost admission race (§7: "the caller lost a race... must
    re-fetch and respond ... never proceed as if it had won")."""
    session = await import_session_crud.get_by_id(db, session_id)
    if session is None:
        raise ImportSessionInvalidStateError(f"Import session '{session_id}' no longer exists.")
    if session.status == "validating":
        running_job = await import_job_crud.get_running_job(db, session_id=session_id, job_type="validate")
        if running_job is not None and running_job.lease_expires_at is not None:
            if running_job.lease_expires_at < datetime.now(timezone.utc):
                raise ImportRecoveryRequiredError(
                    "A prior validation attempt's lease has expired. Call /recover before retrying."
                )
        raise ImportAttemptInProgressError("A validation attempt is already running for this session.")
    raise ImportSessionInvalidStateError(
        f"Session status '{session.status}' does not allow validate. "
        "Allowed source states: created, validated, validation_failed."
    )


async def run_validation(
    db: AsyncSession, *, session: ImportSession, actor_id: uuid.UUID | None, request: Request | None
) -> ImportSession:
    """§21 endpoint #8. Accepts a `SOURCE_REGISTERED` (or already-frozen,
    for re-validate) source, atomically freezes it as part of admission
    (§6), then runs the fully fenced validate phase (§9.4).

    Every primitive needed anywhere in this function -- including in the
    TX2 failure-publication path below -- is captured into a local
    variable as soon as it becomes available, before any statement that
    could roll back or expire `db`'s objects. `db.rollback()` (called
    unconditionally on the TX1-failure path, and internally by
    `admit_validate_job` when its CAS loses a race) expires every ORM
    object attached to the session -- `expire_on_commit=False` only
    protects against `commit()`, not `rollback()`. A bare attribute access
    on an expired ORM instance afterward (e.g. `session.id`, `job_row.id`,
    `session_row.version`) would trigger an implicit lazy-reload outside
    any awaited context, raising `MissingGreenlet`. Using the captured
    primitives instead of touching `session`/`session_row`/`job_row` again
    avoids this entirely, including when real database work (e.g. an
    adapter's `preload_business_context`) has made the transaction active
    before a later failure."""
    session_id = session.id
    dataset_type = session.dataset_type
    expected_version = session.version

    if session.status == "validating" or session.status not in ("created", "validated", "validation_failed"):
        await _raise_for_non_admittable_session(db, session_id)

    source = await import_session_crud.get_source(db, session_id=session_id)
    if source is None:
        raise ImportSourceNotRegisteredError(
            "No source has been registered for this session. Call POST /{id}/source first."
        )

    adapter = get_adapter(dataset_type)
    if adapter is None:
        raise ImportAdapterNotRegisteredError(f"No import adapter is registered for dataset_type '{dataset_type}'.")

    lease_owner = uuid.uuid4()
    lease_generation = 1
    _source_existed, session_row, job_row = await import_job_crud.admit_validate_job(
        db,
        session_id=session_id,
        expected_version=expected_version,
        lease_owner=lease_owner,
        lease_duration_seconds=settings.IMPORT_JOB_LEASE_DURATION_SECONDS,
    )
    if session_row is None or job_row is None:
        await _raise_for_non_admittable_session(db, session_id)

    # §9.4.2: captured immediately, before any statement that could roll
    # back or expire `job_row`/`session_row` -- see docstring above. Both
    # TX1's own completion writes and TX2's later failure-publication use
    # these primitives exclusively, never the ORM instances themselves.
    job_id = job_row.id
    admitted_session_version = session_row.version

    renewal_task = asyncio.create_task(
        import_lease.renew_lease_loop(
            job_id=job_id,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            lease_duration_seconds=settings.IMPORT_JOB_LEASE_DURATION_SECONDS,
            heartbeat_interval_seconds=settings.IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS,
        )
    )

    domain_exc: Exception | None = None
    final_session: ImportSession | None = None
    try:
        # Roadmap PR20A (design §6.5): the framework, never the adapter,
        # is the only caller of `ImportSourceReader.open_verified`. A
        # source registered only via the existing PR19A metadata-only
        # `POST /{id}/source` path has no `import_source_blobs` row, so
        # this blob-existence check (never a hardcoded dataset_type
        # comparison) leaves `parse()` receiving `None` exactly as PR19A
        # shipped it, for every dataset_type that doesn't use PR20A's
        # byte-storage upload endpoint.
        raw_input: object = None
        if await import_source_blob_crud.exists_for_source(db, import_source_id=source.id):
            descriptor = SourceDescriptor(
                import_source_id=source.id,
                import_session_id=session_id,
                dataset_type=dataset_type,
                expected_checksum=source.checksum,
                expected_byte_size=source.byte_size,
                content_type=source.content_type,
                original_filename=source.filename,
                registration_status=source.status,
            )
            raw_input = await ImportSourceReader().open_verified(db, descriptor)
        raw_records = await asyncio.to_thread(adapter.parse, raw_input)
        if len(raw_records) > MAX_IMPORT_ROWS:
            raise _RowLimitExceededError(f"Source has more than {MAX_IMPORT_ROWS} rows.")

        context = await adapter.preload_business_context(db, raw_records)

        findings: list[ImportRowError] = []
        error_row_numbers: set[int] = set()
        warning_row_numbers: set[int] = set()
        for record in raw_records:
            for field_error in adapter.validate_business_rules(record, context):
                findings.append(
                    ImportRowError(
                        import_job_id=job_id,
                        row_number=record.row_number,
                        field=field_error.field,
                        error_code=field_error.error_code,
                        message=field_error.message,
                        severity=field_error.severity,
                    )
                )
                # §12: independent distinct-row projections -- one row may
                # legitimately appear in both sets.
                if field_error.severity == "error":
                    error_row_numbers.add(record.row_number)
                elif field_error.severity == "warning":
                    warning_row_numbers.add(record.row_number)
        db.add_all(findings)

        total_rows = len(raw_records)
        invalid_rows = len(error_row_numbers)
        warning_rows = len(warning_row_numbers)
        valid_rows = total_rows - invalid_rows
        # §13: VALIDATED iff blocking_errors (severity=error) is empty --
        # warnings never block.
        new_status = "validated" if invalid_rows == 0 else "validation_failed"

        final_session = await import_job_crud.fenced_success(
            db,
            job_id=job_id,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            session_id=session_id,
            expected_version=admitted_session_version,
            new_session_status=new_status,
            total_rows=total_rows,
            valid_rows=valid_rows,
            invalid_rows=invalid_rows,
            warning_rows=warning_rows,
        )
        if final_session is None:
            raise _FenceLostDuringSuccessError()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 -- §9.4.2 treats every exception identically
        domain_exc = exc
        final_session = None
        if not isinstance(exc, (_RowLimitExceededError, _FenceLostDuringSuccessError)):
            logger.exception("Validation attempt %s crashed", job_id)
    finally:
        renewal_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewal_task

    if domain_exc is None and final_session is not None:
        return final_session

    # §9.4.2: TX1 rolled back; a brand-new, clean transaction (TX2)
    # attempts best-effort fenced failure publication.
    await db.rollback()
    bounded_message = import_lease.bound_failure_message(
        None if isinstance(domain_exc, _FenceLostDuringSuccessError) else domain_exc, phase_label="Validation"
    )
    try:
        async with import_lease.AsyncSessionLocal() as tx2:
            failed_session = await import_job_crud.fenced_failure(
                tx2,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                session_id=session_id,
                expected_version=admitted_session_version,
                failure_status="validation_failed",
                bounded_error_message=bounded_message,
            )
            if failed_session is None:
                # §9.4.2 step 5: fenced out on our own failure publication too.
                await tx2.rollback()
                await import_lease.write_fence_lost_audit(actor_id=actor_id, session_id=session_id, request=request)
                raise ImportRecoveryRequiredError(
                    "This validation attempt was superseded by a recovery claim or a later attempt."
                )
            await tx2.commit()
            return failed_session
    except ImportRecoveryRequiredError:
        raise
    except Exception:
        # §9.4.2 step 7: TX2 itself failed on infrastructure grounds --
        # never IMPORT_RECOVERY_REQUIRED, never an unfenced write. The job
        # and session are left exactly as they were ('running'/'validating');
        # the lease expires naturally and recovery owns the next attempt.
        logger.exception(
            "TX2 (best-effort fenced failure publication) for validation attempt %s failed on infrastructure "
            "grounds; job left running, lease will expire naturally",
            job_id,
        )
        raise


async def recover_session(
    db: AsyncSession, *, session: ImportSession, actor_id: uuid.UUID | None, request: Request | None
) -> ImportSession:
    """§21 endpoint #7 / §9.3. Generic across `job_type` via
    `import_job_crud.PHASE_STATUS_MAP` -- PR19A2 populates exactly one
    entry (`validate`); PR19A3 adds `dry_run`/`execute` unchanged."""
    claimed_job = await import_job_crud.claim_stale_job(db, session_id=session.id)
    if claimed_job is None:
        await db.rollback()
        raise ImportSessionInvalidStateError(
            "Nothing to recover: no stale-running job (an expired, still-'running' lease) exists for this session."
        )
    phase = import_job_crud.PHASE_STATUS_MAP.get(claimed_job.job_type)
    if phase is None:
        await db.rollback()
        raise ImportSessionInvalidStateError(f"No recovery mapping is defined for job_type '{claimed_job.job_type}'.")

    session_row = await import_job_crud.transition_session_for_recovery(
        db, session_id=session.id, running_status=phase["running_status"], failure_status=phase["failure_status"]
    )
    if session_row is None:
        await db.rollback()
        raise ImportSessionInvalidStateError("Nothing to recover: the session already moved on for another reason.")

    # Roadmap PR20E (design §14.4c): reconciles the case §14.4b's
    # exception-based hook cannot cover -- a hard worker crash during
    # execute() that never raised anything at all. Only `execute`-phase
    # recovery needs this; `dry_run`/`validate` recovery never calls it
    # (§14.3's own same-TX1 atomicity already leaves no partial artifact
    # for those phases to reconcile). If this raises, the exception
    # propagates uncaught -- the caller's entire transaction (including
    # the claim/transition above) rolls back, exactly like every other
    # failure path in this function.
    if claimed_job.job_type == "execute":
        adapter = get_adapter(session.dataset_type)
        if adapter is not None:
            await adapter.on_execution_recovery(db, session.id)

    await record_audit_event(
        db,
        actor_user_id=actor_id,
        action=AUDIT_ACTION_IMPORT_RECOVERY,
        entity_type=AUDIT_ENTITY_IMPORT_SESSION,
        entity_id=session.id,
        request=request,
    )
    await db.commit()
    return session_row
