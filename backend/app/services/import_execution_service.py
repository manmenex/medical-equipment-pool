"""Dry-run and execute phase orchestration for the legacy-import pipeline.

Roadmap PR19A3 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §16,
§17, §9.4.3). Adds no new lease, heartbeat, fencing, or recovery
mechanism of its own (§25) -- it composes onto the generic primitives
PR19A2 already shipped and PR19A3 extends additively:
`app.crud.import_job.PHASE_STATUS_MAP` (now including `dry_run`/
`execute`), `admit_phase_job`/`fenced_phase_success`/`fenced_phase_failure`
(the same fencing shape as validate's own, parameterized), and
`app.services.import_lease`'s shared renewal-loop/fence-lost-audit
helpers. `app.services.import_validation_service` (PR19A2) is not
imported or modified by this module.
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime, timezone
from typing import NoReturn

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AUDIT_ACTION_IMPORT, AUDIT_ENTITY_IMPORT_SESSION, record_audit_event
from app.core.config import settings
from app.core.exceptions import (
    ImportAdapterNotImplementedError,
    ImportAdapterNotRegisteredError,
    ImportAttemptInProgressError,
    ImportExecutionFailedError,
    ImportRecoveryRequiredError,
    ImportSessionInvalidStateError,
    ImportSourceNotRegisteredError,
)
from app.crud import import_job as import_job_crud
from app.crud import import_session as import_session_crud
from app.crud import import_source_blob as import_source_blob_crud
from app.db.session import AsyncSessionLocal
from app.models.import_session import ImportSession
from app.services import import_lease
from app.services.import_adapter import ImportAdapter, get_adapter
from app.services.import_adapter_context import AdapterInvocationContext, adapter_invocation_context
from app.services.import_source_reader import ImportSourceReader, SourceDescriptor

logger = logging.getLogger(__name__)

_DRY_RUN_ALLOWED_FROM_STATUSES = ("validated", "dry_run_completed", "dry_run_failed")
_EXECUTE_ALLOWED_FROM_STATUSES = ("dry_run_completed",)


class _FenceLostDuringSuccessError(Exception):
    """Internal marker: the success-path fencing UPDATE(s) affected zero
    rows (§9.4.1 step 6). Caught by the same generic failure handler as a
    genuine domain exception -- both follow the identical TX1-rollback/TX2
    path (§9.4.2). Mirrors `import_validation_service`'s own private
    marker of the same name -- deliberately not imported from there (see
    module docstring: PR19A2's module is left untouched)."""


async def _raise_for_non_admittable_dry_run(db: AsyncSession, session_id: uuid.UUID) -> NoReturn:
    """Re-fetches the session and classifies exactly why dry-run cannot
    proceed from its current state (§7's "the caller lost a race... must
    re-fetch and respond ... never proceed as if it had won"), mirroring
    `import_validation_service._raise_for_non_admittable_session`'s shape
    for the `dry_run` phase."""
    session = await import_session_crud.get_by_id(db, session_id)
    if session is None:
        raise ImportSessionInvalidStateError(f"Import session '{session_id}' no longer exists.")
    if session.status == "dry_run_running":
        running_job = await import_job_crud.get_running_job(db, session_id=session_id, job_type="dry_run")
        if running_job is not None and running_job.lease_expires_at is not None:
            if running_job.lease_expires_at < datetime.now(timezone.utc):
                raise ImportRecoveryRequiredError(
                    "A prior dry-run attempt's lease has expired. Call /recover before retrying."
                )
        raise ImportAttemptInProgressError("A dry-run attempt is already running for this session.")
    raise ImportSessionInvalidStateError(
        f"Session status '{session.status}' does not allow dry-run. "
        f"Allowed source states: {', '.join(_DRY_RUN_ALLOWED_FROM_STATUSES)}."
    )


async def _resolve_non_admittable_execute(db: AsyncSession, session_id: uuid.UUID) -> ImportSession:
    """Re-fetches and classifies why `execute` could not be admitted.
    Unlike validate/dry-run, a lost admission race here may legitimately
    mean a concurrent execute already completed (§17: COMPLETED is always
    an idempotent 200 replay, never an error) -- so this returns the
    session rather than always raising."""
    fresh = await import_session_crud.get_by_id(db, session_id)
    if fresh is None:
        raise ImportSessionInvalidStateError(f"Import session '{session_id}' no longer exists.")
    if fresh.status == "completed":
        return fresh
    if fresh.status == "executing":
        running_job = await import_job_crud.get_running_job(db, session_id=session_id, job_type="execute")
        if running_job is not None and running_job.lease_expires_at is not None:
            if running_job.lease_expires_at < datetime.now(timezone.utc):
                raise ImportRecoveryRequiredError(
                    "A prior execute attempt's lease has expired. Call /recover before retrying."
                )
        raise ImportAttemptInProgressError("An execute attempt is already running for this session.")
    raise ImportSessionInvalidStateError(
        f"Session status '{fresh.status}' does not allow execute. "
        "Requires a fresh dry-run first (status 'dry_run_completed')."
    )


async def run_dry_run(
    db: AsyncSession, *, session: ImportSession, actor_id: uuid.UUID | None, request: Request | None
) -> ImportSession:
    """§21 endpoint #10 / §16. Runs `adapter.plan_dry_run()` inside a
    genuinely read-only, separate session/transaction -- any write
    attempt is rejected by the database itself, not merely discarded
    after the fact -- then persists pass/fail through the same fenced
    completion contract (§9.4.1/§9.4.2) validate already established
    (§9.4.3: "dry-run participates fully in the fencing contract; it
    simply never has domain writes to discard").

    Every primitive needed anywhere in this function is captured into a
    local variable as soon as it becomes available, before any statement
    that could roll back or expire `db`'s objects -- see
    `import_validation_service.run_validation`'s docstring for the
    `MissingGreenlet` hazard this avoids."""
    session_id = session.id
    dataset_type = session.dataset_type
    expected_version = session.version

    if session.status not in _DRY_RUN_ALLOWED_FROM_STATUSES:
        await _raise_for_non_admittable_dry_run(db, session_id)

    adapter = get_adapter(dataset_type)
    if adapter is None:
        raise ImportAdapterNotRegisteredError(f"No import adapter is registered for dataset_type '{dataset_type}'.")
    if type(adapter).plan_dry_run is ImportAdapter.plan_dry_run:
        raise ImportAdapterNotImplementedError(f"Adapter for dataset_type '{dataset_type}' does not implement dry-run.")

    lease_owner = uuid.uuid4()
    lease_generation = 1
    session_row, job_row = await import_job_crud.admit_phase_job(
        db,
        session_id=session_id,
        job_type="dry_run",
        allowed_from_statuses=_DRY_RUN_ALLOWED_FROM_STATUSES,
        running_status="dry_run_running",
        expected_version=expected_version,
        lease_owner=lease_owner,
        lease_duration_seconds=settings.IMPORT_JOB_LEASE_DURATION_SECONDS,
    )
    if session_row is None or job_row is None:
        await _raise_for_non_admittable_dry_run(db, session_id)

    job_id = job_row.id
    admitted_session_version = session_row.version
    # Roadmap PR20A (design §6.4): captured immediately, as a bare
    # primitive, following this function's own established discipline --
    # `session_row` must not be touched again after any statement that
    # could roll back/expire it.
    accepted_validation_job_id = session_row.current_validation_job_id

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
        # Roadmap PR20A (design §6.4/§6.5): resolved inside the fenced
        # attempt, exactly like `import_validation_service.run_validation`'s
        # identical `open_verified` call -- a missing source/blob or a
        # checksum/length mismatch here is a structural failure that must
        # route through the existing TX1/TX2 crash path (§6.5's failure-
        # classification table), never a bare pre-admission rejection that
        # would leave this already-admitted job stuck `running` with no
        # fenced failure ever published. A source row is guaranteed to
        # exist in the normal case -- dry-run is only reachable from
        # `validated`/`dry_run_completed`/`dry_run_failed`, and validate's
        # own admission already requires a registered source -- but this
        # is still verified, not assumed.
        source = await import_session_crud.get_source(db, session_id=session_id)
        if source is None:
            raise ImportSourceNotRegisteredError(
                f"Import session '{session_id}' has no registered source despite being admitted for dry-run."
            )
        verified_source_content = None
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
            verified_source_content = await ImportSourceReader().open_verified(db, descriptor)
        invocation_context = AdapterInvocationContext(
            import_session_id=session_id,
            import_source_id=source.id,
            dataset_type=dataset_type,
            source_checksum=source.checksum,
            source_fingerprint=source.source_fingerprint,
            ruleset_version=adapter.ruleset_version,
            verified_source_content=verified_source_content,
            dry_run_job_id=job_id,
            accepted_validation_job_id=accepted_validation_job_id,
        )

        async with AsyncSessionLocal() as ro_db:
            # §16: PostgreSQL's `SET TRANSACTION READ ONLY` is the primary,
            # safety-critical enforcement mechanism, and design §16
            # explicitly requires "PostgreSQL tests (PR19A3)" to prove it
            # -- this is intentionally not replicated on SQLite. SQLite's
            # nearest equivalent, `PRAGMA query_only`, is a *connection*-
            # level setting, not transaction-level; this test suite's
            # SQLite engines use `StaticPool` (one shared connection for
            # every session in the engine, tests/conftest.py), so setting
            # it here would leak into unrelated sessions/tests with no
            # reliable point to safely reset it. SQLite is dev/test-only
            # in this repository (never production, see
            # `app.crud.transaction`'s identical documented posture), so
            # this omission carries no production risk.
            if ro_db.get_bind().dialect.name == "postgresql":
                await ro_db.execute(text("SET TRANSACTION READ ONLY"))
            # §16: computed entirely within the read-only transaction,
            # then discarded -- only pass/fail feeds the session's own
            # completion columns below (§16's "Result persistence").
            # Roadmap PR20A (design §6.4): the contextvar is set/reset
            # around exactly this call, nothing else.
            with adapter_invocation_context(invocation_context):
                await adapter.plan_dry_run(ro_db)

        final_session = await import_job_crud.fenced_phase_success(
            db,
            job_id=job_id,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            session_id=session_id,
            expected_version=admitted_session_version,
            running_status="dry_run_running",
            new_session_status="dry_run_completed",
            extra_session_values=lambda now: {"dry_run_completed_at": now},
        )
        if final_session is None:
            raise _FenceLostDuringSuccessError()
        await db.commit()
    except Exception as exc:  # noqa: BLE001 -- §9.4.2 treats every exception identically
        domain_exc = exc
        final_session = None
        if not isinstance(exc, _FenceLostDuringSuccessError):
            # §16: a caught write-attempt exception is additionally
            # tagged as a distinct, security-relevant log marker -- never
            # a distinct HTTP error code, only an operator-searchable log
            # line (§16's own security/observability requirement).
            if "read-only" in str(exc).lower() or "readonly" in str(exc).lower():
                logger.warning("import.dry_run.write_attempt_detected session_id=%s job_id=%s", session_id, job_id)
            logger.exception("Dry-run attempt %s crashed", job_id)
    finally:
        renewal_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewal_task

    if domain_exc is None and final_session is not None:
        return final_session

    # §9.4.2: TX1 rolled back (or, for dry-run, never had domain writes to
    # begin with -- this still resets `db`'s own transaction, e.g. after a
    # lost fenced_phase_success); a brand-new, clean transaction (TX2)
    # attempts best-effort fenced failure publication.
    await db.rollback()
    bounded_message = import_lease.bound_failure_message(
        None if isinstance(domain_exc, _FenceLostDuringSuccessError) else domain_exc, phase_label="Dry-run"
    )
    try:
        async with AsyncSessionLocal() as tx2:
            failed_session = await import_job_crud.fenced_phase_failure(
                tx2,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                session_id=session_id,
                expected_version=admitted_session_version,
                running_status="dry_run_running",
                failure_status="dry_run_failed",
                bounded_error_message=bounded_message,
            )
            if failed_session is None:
                await tx2.rollback()
                await import_lease.write_fence_lost_audit(actor_id=actor_id, session_id=session_id, request=request)
                raise ImportRecoveryRequiredError(
                    "This dry-run attempt was superseded by a recovery claim or a later attempt."
                )
            await tx2.commit()
            return failed_session
    except ImportRecoveryRequiredError:
        raise
    except Exception:
        logger.exception(
            "TX2 (best-effort fenced failure publication) for dry-run attempt %s failed on infrastructure "
            "grounds; job left running, lease will expire naturally",
            job_id,
        )
        raise


async def run_execute(
    db: AsyncSession, *, session: ImportSession, actor_id: uuid.UUID | None, request: Request | None
) -> ImportSession:
    """§21 endpoint #11 / §17. Single-winner execution claim (`DRY_RUN_
    COMPLETED -> EXECUTING`, the same §7 atomic conditional UPDATE every
    other phase transition uses) plus completion fencing (§9.4), composed
    unchanged from PR19A2's mechanism. Execute idempotency is
    state-based, not a request-payload/fingerprint comparison (design
    §17: "a repeat call, not a request-payload comparison -- contrast
    §15"): `COMPLETED` always replays the existing session, `EXECUTING`
    is `409 IMPORT_ATTEMPT_IN_PROGRESS`, `FAILED` or any other state is
    `409 IMPORT_SESSION_INVALID_STATE` (a fresh dry-run is required
    first). There is no compound idempotency-key/fingerprint contract for
    execute in the merged design -- §15's fingerprint mechanism is scoped
    to source registration only."""
    session_id = session.id
    dataset_type = session.dataset_type
    expected_version = session.version
    current_status = session.status

    if current_status == "completed":
        return session
    if current_status == "executing":
        return await _resolve_non_admittable_execute(db, session_id)
    if current_status != "dry_run_completed":
        raise ImportSessionInvalidStateError(
            f"Session status '{current_status}' does not allow execute. "
            "Requires a fresh dry-run first (status 'dry_run_completed')."
        )

    adapter = get_adapter(dataset_type)
    if adapter is None:
        raise ImportAdapterNotRegisteredError(f"No import adapter is registered for dataset_type '{dataset_type}'.")
    if type(adapter).execute is ImportAdapter.execute:
        raise ImportAdapterNotImplementedError(f"Adapter for dataset_type '{dataset_type}' does not implement execute.")

    lease_owner = uuid.uuid4()
    lease_generation = 1
    session_row, job_row = await import_job_crud.admit_phase_job(
        db,
        session_id=session_id,
        job_type="execute",
        allowed_from_statuses=_EXECUTE_ALLOWED_FROM_STATUSES,
        running_status="executing",
        expected_version=expected_version,
        lease_owner=lease_owner,
        lease_duration_seconds=settings.IMPORT_JOB_LEASE_DURATION_SECONDS,
    )
    if session_row is None or job_row is None:
        return await _resolve_non_admittable_execute(db, session_id)

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
        # Roadmap PR20A (design §6.4): identity-only context for `execute`
        # -- `verified_source_content`/`dry_run_job_id`/
        # `accepted_validation_job_id` are always `None` here, since
        # `execute()` never re-reads or re-parses the source and resolves
        # its own confirmed plan internally (design §14.4, a later slice).
        # `import_session_id` is retained only for audit-logging purposes;
        # neither `plan_dry_run` nor `execute` writes to
        # `import_sessions`/`import_jobs` itself.
        source = await import_session_crud.get_source(db, session_id=session_id)
        if source is None:
            raise ImportSourceNotRegisteredError(
                f"Import session '{session_id}' has no registered source despite being admitted for execute."
            )
        invocation_context = AdapterInvocationContext(
            import_session_id=session_id,
            import_source_id=source.id,
            dataset_type=dataset_type,
            source_checksum=source.checksum,
            source_fingerprint=source.source_fingerprint,
            ruleset_version=adapter.ruleset_version,
            verified_source_content=None,
            dry_run_job_id=None,
            accepted_validation_job_id=None,
        )

        # §17/§9.4.1 step 3: unlike dry-run, execute must actually write --
        # the normal read-write session, inside this same TX1.
        with adapter_invocation_context(invocation_context):
            imported_rows = await adapter.execute(db)
        final_session = await import_job_crud.fenced_phase_success(
            db,
            job_id=job_id,
            lease_owner=lease_owner,
            lease_generation=lease_generation,
            session_id=session_id,
            expected_version=admitted_session_version,
            running_status="executing",
            new_session_status="completed",
            extra_session_values=lambda now: {"executed_at": now, "imported_rows": imported_rows, "terminal_at": now},
        )
        if final_session is None:
            raise _FenceLostDuringSuccessError()
        # §9.4.1 step 5 / §19: one AUDIT_ACTION_IMPORT entry, same TX1,
        # fresh success only -- never for an idempotent replay or a
        # cleanly-recorded failure.
        await record_audit_event(
            db,
            actor_user_id=actor_id,
            action=AUDIT_ACTION_IMPORT,
            entity_type=AUDIT_ENTITY_IMPORT_SESSION,
            entity_id=session_id,
            request=request,
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 -- §9.4.2 treats every exception identically
        domain_exc = exc
        final_session = None
        if not isinstance(exc, _FenceLostDuringSuccessError):
            logger.exception("Execute attempt %s crashed", job_id)
    finally:
        renewal_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await renewal_task

    if domain_exc is None and final_session is not None:
        return final_session

    await db.rollback()
    bounded_message = import_lease.bound_failure_message(
        None if isinstance(domain_exc, _FenceLostDuringSuccessError) else domain_exc, phase_label="Execution"
    )
    try:
        async with AsyncSessionLocal() as tx2:
            failed_session = await import_job_crud.fenced_phase_failure(
                tx2,
                job_id=job_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                session_id=session_id,
                expected_version=admitted_session_version,
                running_status="executing",
                failure_status="failed",
                bounded_error_message=bounded_message,
                # §5: FAILED is terminal, unlike DRY_RUN_FAILED/
                # VALIDATION_FAILED.
                extra_session_values=lambda now: {"terminal_at": now},
            )
            if failed_session is None:
                await tx2.rollback()
                await import_lease.write_fence_lost_audit(actor_id=actor_id, session_id=session_id, request=request)
                raise ImportRecoveryRequiredError(
                    "This execute attempt was superseded by a recovery claim or a later attempt."
                )
            await tx2.commit()
    except ImportRecoveryRequiredError:
        raise
    except Exception:
        logger.exception(
            "TX2 (best-effort fenced failure publication) for execute attempt %s failed on infrastructure "
            "grounds; job left running, lease will expire naturally",
            job_id,
        )
        raise
    else:
        # §21 endpoint #11 / §23: execute's own cleanly-recorded failure is
        # the one phase treated as a genuine server error, unlike
        # validate/dry-run's 200 for the same class of outcome.
        raise ImportExecutionFailedError(bounded_message)
