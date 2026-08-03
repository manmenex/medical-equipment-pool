"""Roadmap PR19A -- Legacy Import Foundation.

See docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md for the full design
and docs/audits/04-consolidated-implementation-plan.md Part D ("PR19 --
Legacy Import Foundation") for the authoritative scope boundary.

Architecture (design's own diagram):

    Import File -> Parser Adapter -> Validation -> Business Mapping
        -> Dry Run -> Import Execution -> Summary

This module implements every stage of that pipeline as dataset-agnostic
orchestration over a pluggable `ImportAdapter` (design: "Parser adapters
must be replaceable"). It deliberately ships **zero concrete adapters** --
`registry` (the module-level `ImportAdapterRegistry`) is empty. Equipment
Master import (Roadmap PR20), Receive history import, and Issue history
import (Roadmap PR21) will each register their own `ImportAdapter`
subclass in a future slice; this module must never import
`app.models.equipment` or `app.models.transaction`, and does not.

Because no adapter is registered, `ImportAdapter`'s `plan_dry_run`/
`execute` hooks -- the only two hooks capable of writing real data -- can
never be reached with a real dataset in this slice; every call against a
real dataset_type fails fast with `ImportAdapterNotRegisteredError` before
any state changes. The pipeline mechanics themselves (state machine,
structural validation, duplicate detection, business-rule hook,
transaction/rollback safety, audit integration) are fully implemented and
exercised by this module's own test suite using an in-memory test-double
adapter -- not a CSV/Excel parser, which remains explicitly out of scope.

Transaction strategy (design §4/"no partial silent import"): each phase
(validate / dry-run / execute) is a two-step commit. Step 1 durably
records that the phase started (`ImportSession.status` transitions to its
*_RUNNING/*_VALIDATING state, one `ImportJob` row is created) and commits
immediately -- this is what makes a session's last-known phase inspectable
even if the process is interrupted mid-phase (design §7: "resumable import
sessions -- foundation only"). Step 2 performs the actual work inside a
fresh, still-open transaction: on success, it commits together with the
job's SUCCEEDED status and the session's new terminal-for-this-phase
status; on any exception, everything step 2 attempted is rolled back, and
a *separate* follow-up transaction records the job as FAILED and the
session's failure state -- so a crash during row-error insertion, business
mapping, or (in a future slice) the real write phase can never leave a
partially-applied batch, only a durably-recorded, honestly-reported
failure.
"""

import abc
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AUDIT_ACTION_IMPORT, AUDIT_ENTITY_IMPORT_SESSION, record_audit_event
from app.core.exceptions import (
    ImportAdapterNotImplementedError,
    ImportAdapterNotRegisteredError,
    ImportExecutionFailedError,
    ImportSessionStateError,
    InvalidInputError,
)
from app.crud import import_session as import_session_crud
from app.models.import_session import (
    CANCELLABLE_SESSION_STATUSES,
    ImportErrorSeverity,
    ImportJob,
    ImportJobStatus,
    ImportJobType,
    ImportRowError,
    ImportSession,
    ImportSessionStatus,
)

# Foundation-level bound on parsed row count, shared by every future
# adapter's structural pass -- mirrors Roadmap PR12's MAX_IMPORT_ROWS
# precedent (app.services.import_service). A concrete adapter may declare
# a *lower* dataset-specific bound; this is the ceiling no dataset type may
# exceed.
MAX_IMPORT_ROWS = 5000


@dataclass(frozen=True)
class RawImportRecord:
    """One not-yet-validated row an adapter's `parse()` produced.
    `fields` is a flat string-to-string mapping -- typed coercion into a
    canonical business payload is a concrete adapter's own responsibility
    inside its `execute`/`plan_dry_run`, not this dataclass's job."""

    row_number: int
    fields: dict[str, str]


@dataclass
class FieldError:
    """One validation failure, not yet attributed to a session -- that
    happens when it is persisted as an `app.models.import_session.
    ImportRowError` row (see `_persist_row_errors`)."""

    row_number: int | None
    field: str | None
    error_code: str
    message: str
    severity: ImportErrorSeverity = ImportErrorSeverity.ERROR


@dataclass
class DryRunPlan:
    """What execution would do, computed with zero writes (design
    architecture diagram, dry-run stage). Every field is adapter-reported;
    `run_execute` never trusts this plan for anything beyond display -- it
    always re-derives its own `ExecutionOutcome` independently."""

    would_create: int = 0
    would_update: int = 0
    would_skip: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class ExecutionOutcome:
    created: int = 0
    updated: int = 0
    skipped: int = 0


class ImportAdapter(abc.ABC):
    """One pluggable dataset-type adapter (design: "Parser adapters must
    be replaceable"). No concrete subclass ships in this Roadmap PR19A
    slice -- see module docstring.

    Every hook below except `parse` and `validate_business_rules` has a
    foundation-level default that raises `ImportAdapterNotImplementedError`
    on purpose: a dataset type with no adapter override for `plan_dry_run`/
    `execute` can never write anything anywhere, which is exactly the
    invariant this slice's "Do NOT implement Equipment/Receive/Issue
    import" boundary requires -- the pipeline is real and exercised, but no
    real data movement is possible until a future slice deliberately
    implements a concrete adapter.
    """

    #: Registry key -- must match `ImportSession.dataset_type` exactly.
    dataset_type: str
    #: Declared field schema for structural validation (design, "Validation
    #: pipeline"). A field present in this tuple but missing/blank on a
    #: record is a per-row structural failure.
    required_fields: tuple[str, ...] = ()
    #: Optional per-field maximum length, checked the same way.
    field_max_lengths: dict[str, int] = {}
    #: Fields whose combined value must be unique within one parsed batch
    #: (design, "duplicate detection"). Empty means this dataset type has
    #: no in-batch duplicate concept.
    duplicate_key_fields: tuple[str, ...] = ()

    @abc.abstractmethod
    def parse(self, raw_input: object) -> list[RawImportRecord]:
        """Turn adapter-specific raw input into `RawImportRecord`s. The one
        stage every real subclass MUST implement -- there is no meaningful
        foundation-level default for "read this format". Synchronous by
        design: a real adapter parsing a large file should run this via
        `asyncio.to_thread` at its own call site, mirroring Roadmap PR12's
        `_parse_workbook_sync` precedent; this foundation does not assume
        that for every future format."""

    async def validate_business_rules(self, db: AsyncSession, record: RawImportRecord) -> list[FieldError]:
        """Business-rule hook (e.g. cross-referencing existing equipment/
        ward rows) -- design, "Validation pipeline". Default: no additional
        errors. A dataset type with nothing beyond structural/duplicate
        checks may leave this unoverridden."""
        return []

    async def plan_dry_run(self, db: AsyncSession, session: "ImportSession") -> DryRunPlan:
        """Compute, with zero writes, what `execute` would do for this
        session. Receives the `ImportSession` itself (its counts, id,
        dataset_type) rather than a list of records: this foundation slice
        does not persist parsed/validated row content between phases (only
        `ImportRowError`s), so a concrete adapter that needs to plan
        against real row data is responsible for its own strategy for
        making that data available again at dry-run/execute time -- e.g.
        re-parsing a durably-referenced source, or its own adapter-owned
        cache. That decision belongs to the concrete adapter design (a
        future slice), not this foundation."""
        raise ImportAdapterNotImplementedError(
            f"No dry-run planning is implemented for dataset type '{self.dataset_type}' in this "
            "Roadmap PR19A foundation slice. A concrete adapter for this dataset type has not "
            "been registered yet."
        )

    async def execute(self, db: AsyncSession, session: "ImportSession") -> ExecutionOutcome:
        """Perform the real write phase for this session, inside the
        caller's already-open transaction (see `run_execute`) -- any
        exception raised here rolls back everything this call attempted.
        Same "receives the session, not a record list" rationale as
        `plan_dry_run` above."""
        raise ImportAdapterNotImplementedError(
            f"No import execution is implemented for dataset type '{self.dataset_type}' in this "
            "Roadmap PR19A foundation slice. A concrete adapter for this dataset type has not "
            "been registered yet."
        )


class ImportAdapterRegistry:
    """Design: "Parser adapters must be replaceable." A single process-wide
    mapping from `dataset_type` to the `ImportAdapter` instance that
    handles it. Empty by default -- see module docstring."""

    def __init__(self) -> None:
        self._adapters: dict[str, ImportAdapter] = {}

    def register(self, adapter: ImportAdapter) -> None:
        self._adapters[adapter.dataset_type] = adapter

    def unregister(self, dataset_type: str) -> None:
        self._adapters.pop(dataset_type, None)

    def get(self, dataset_type: str) -> ImportAdapter | None:
        return self._adapters.get(dataset_type)

    def known_dataset_types(self) -> list[str]:
        return sorted(self._adapters)


#: The single process-wide registry every service/API call site uses.
#: Empty by default (see module docstring) -- tests register a stub
#: adapter around themselves and unregister it afterward; production code
#: registers nothing until a future Roadmap slice adds a real adapter.
registry = ImportAdapterRegistry()


def _require_adapter(dataset_type: str) -> ImportAdapter:
    adapter = registry.get(dataset_type)
    if adapter is None:
        raise ImportAdapterNotRegisteredError(
            f"No import adapter is registered for dataset type '{dataset_type}'. This dataset "
            "type is not yet supported by the Legacy Import Foundation."
        )
    return adapter


def _require_status(session: ImportSession, *allowed: ImportSessionStatus) -> None:
    if session.status not in allowed:
        raise ImportSessionStateError(
            f"Import session {session.id} is in state '{session.status.value}'; this operation "
            f"requires one of: {', '.join(s.value for s in allowed)}."
        )


# ---------------------------------------------------------------------------
# Validation pipeline stages (design architecture diagram: "Validation").
# Deterministic order (design, "deterministic validation order"): structural
# -> duplicate detection -> business rules, always in that sequence, always
# in original parse order within each stage.
# ---------------------------------------------------------------------------


def _validate_structural(
    records: list[RawImportRecord], adapter: ImportAdapter
) -> tuple[list[RawImportRecord], list[FieldError]]:
    valid: list[RawImportRecord] = []
    errors: list[FieldError] = []
    for record in records:
        record_errors: list[FieldError] = []
        for required_field in adapter.required_fields:
            if not record.fields.get(required_field):
                record_errors.append(
                    FieldError(
                        record.row_number,
                        required_field,
                        "MISSING_REQUIRED_FIELD",
                        f"Missing required field '{required_field}'.",
                    )
                )
        for field_name, max_length in adapter.field_max_lengths.items():
            value = record.fields.get(field_name)
            if value is not None and len(value) > max_length:
                record_errors.append(
                    FieldError(
                        record.row_number,
                        field_name,
                        "FIELD_TOO_LONG",
                        f"Field '{field_name}' exceeds the maximum length of {max_length} characters.",
                    )
                )
        if record_errors:
            errors.extend(record_errors)
        else:
            valid.append(record)
    return valid, errors


def _detect_duplicates(
    records: list[RawImportRecord], adapter: ImportAdapter
) -> tuple[list[RawImportRecord], list[FieldError]]:
    if not adapter.duplicate_key_fields:
        return records, []

    seen: dict[tuple[str, ...], list[int]] = {}
    for record in records:
        key = tuple(record.fields.get(f, "") for f in adapter.duplicate_key_fields)
        seen.setdefault(key, []).append(record.row_number)
    # Every occurrence of a duplicated key fails -- mirrors Roadmap PR12's
    # "flag all duplicates within a file" precedent
    # (app.services.import_service._find_in_file_duplicates); none is
    # silently kept as "the real one".
    duplicated_rows = {row for rows in seen.values() if len(rows) > 1 for row in rows}

    key_label = ", ".join(adapter.duplicate_key_fields)
    valid = [r for r in records if r.row_number not in duplicated_rows]
    errors = [
        FieldError(
            r.row_number,
            None,
            "DUPLICATE_WITHIN_BATCH",
            f"Duplicate value for ({key_label}) within the uploaded batch.",
        )
        for r in records
        if r.row_number in duplicated_rows
    ]
    return valid, errors


async def _run_business_validation(
    db: AsyncSession, records: list[RawImportRecord], adapter: ImportAdapter
) -> tuple[list[RawImportRecord], list[FieldError]]:
    valid: list[RawImportRecord] = []
    errors: list[FieldError] = []
    for record in records:
        record_errors = await adapter.validate_business_rules(db, record)
        if record_errors:
            errors.extend(record_errors)
        else:
            valid.append(record)
    return valid, errors


def _persist_row_errors(errors: list[FieldError]) -> list[ImportRowError]:
    return [
        ImportRowError(
            row_number=e.row_number,
            field=e.field,
            error_code=e.error_code,
            message=e.message,
            severity=e.severity,
        )
        for e in errors
    ]


# ---------------------------------------------------------------------------
# Phase orchestration (design §4/"no partial silent import" + §7/"resumable
# import sessions -- foundation only"). See module docstring for the exact
# two-step commit shape this implements.
# ---------------------------------------------------------------------------


async def _run_phase(
    db: AsyncSession,
    session: ImportSession,
    *,
    job_type: ImportJobType,
    running_status: ImportSessionStatus,
    failure_status: ImportSessionStatus,
    work: Callable[[ImportJob], Awaitable[None]],
) -> ImportJob:
    """`work` is responsible for setting `session.status` (and any other
    session fields) to reflect its own definition of success before
    returning; it must not catch and swallow its own exceptions -- any
    exception it raises is what drives the failure path below."""
    session.status = running_status
    job = await import_session_crud.create_job(db, session_id=session.id, job_type=job_type)
    # Durably records "this phase started" before doing any real work, so
    # the session's last-known phase is inspectable even if `work` never
    # returns (design §7).
    await db.commit()

    try:
        await work(job)
    except Exception as exc:
        await db.rollback()
        await db.refresh(session)
        await db.refresh(job)
        await import_session_crud.finish_job(db, job, status=ImportJobStatus.FAILED, error_message=str(exc)[:2000])
        session.status = failure_status
        session.failure_reason = str(exc)[:2000]
        await db.commit()
        raise
    else:
        await import_session_crud.finish_job(db, job, status=ImportJobStatus.SUCCEEDED, error_message=None)
        await db.commit()
    return job


async def get_or_create_session(
    db: AsyncSession,
    *,
    dataset_type: str,
    created_by_user_id: uuid.UUID,
    idempotency_key: str | None,
    source_checksum: str | None,
    source_filename: str | None,
    notes: str | None,
) -> tuple[ImportSession, bool]:
    """Design, "idempotent imports": a repeated request with the same
    `(dataset_type, idempotency_key)` pair returns the existing session
    unchanged rather than creating a duplicate. Returns `(session,
    created)` so the caller can distinguish "created" from "returned
    existing" (e.g. to choose a 201 vs 200 response)."""
    if idempotency_key is not None:
        existing = await import_session_crud.get_by_idempotency_key(
            db, dataset_type=dataset_type, idempotency_key=idempotency_key
        )
        if existing is not None:
            return existing, False

    session = await import_session_crud.create_session(
        db,
        dataset_type=dataset_type,
        created_by_user_id=created_by_user_id,
        idempotency_key=idempotency_key,
        source_checksum=source_checksum,
        source_filename=source_filename,
        notes=notes,
    )
    await db.commit()
    return session, True


async def run_validation(db: AsyncSession, session: ImportSession, raw_input: object) -> ImportSession:
    """Design architecture diagram, "Validation" stage. Re-runnable: a
    session in VALIDATED or VALIDATION_FAILED may be validated again
    (e.g. against a corrected source), which simply re-derives its counts
    and error rows from scratch -- previous `ImportRowError` rows for this
    session are not accumulated across runs, only the latest pass's rows
    are ever persisted at once (see `import_session_crud.
    bulk_add_row_errors`; nothing deletes prior rows in this slice since a
    session's row_errors are, in this foundation, effectively write-once
    per lifetime -- re-validation is expected to be rare enough operator
    behavior that this is a documented, not a silent, limitation)."""
    _require_status(
        session,
        ImportSessionStatus.CREATED,
        ImportSessionStatus.VALIDATED,
        ImportSessionStatus.VALIDATION_FAILED,
    )
    adapter = _require_adapter(session.dataset_type)

    async def work(job: ImportJob) -> None:
        records = adapter.parse(raw_input)
        if len(records) > MAX_IMPORT_ROWS:
            raise InvalidInputError(
                f"The import batch contains more than {MAX_IMPORT_ROWS} rows, exceeding the "
                "maximum a single import session may process."
            )

        structurally_valid, structural_errors = _validate_structural(records, adapter)
        deduplicated, duplicate_errors = _detect_duplicates(structurally_valid, adapter)
        business_valid, business_errors = await _run_business_validation(db, deduplicated, adapter)

        all_errors = structural_errors + duplicate_errors + business_errors
        await import_session_crud.bulk_add_row_errors(
            db, session_id=session.id, errors=_persist_row_errors(all_errors)
        )

        session.total_rows = len(records)
        session.valid_rows = len(business_valid)
        session.invalid_rows = len({e.row_number for e in all_errors if e.row_number is not None})
        session.validated_at = datetime.now(timezone.utc)
        session.status = (
            ImportSessionStatus.VALIDATED if not all_errors else ImportSessionStatus.VALIDATION_FAILED
        )

    await _run_phase(
        db,
        session,
        job_type=ImportJobType.VALIDATE,
        running_status=ImportSessionStatus.VALIDATING,
        failure_status=ImportSessionStatus.VALIDATION_FAILED,
        work=work,
    )
    return session


async def run_dry_run(db: AsyncSession, session: ImportSession) -> ImportSession:
    """Design architecture diagram, "Dry Run" stage. Requires a session
    that has already passed validation -- a session with any recorded
    validation error can never reach dry run, matching "no partial silent
    import" applied to the session state machine itself."""
    _require_status(
        session,
        ImportSessionStatus.VALIDATED,
        ImportSessionStatus.DRY_RUN_COMPLETED,
        ImportSessionStatus.DRY_RUN_FAILED,
    )
    adapter = _require_adapter(session.dataset_type)

    async def work(job: ImportJob) -> None:
        await adapter.plan_dry_run(db, session)
        session.dry_run_completed_at = datetime.now(timezone.utc)
        session.status = ImportSessionStatus.DRY_RUN_COMPLETED

    await _run_phase(
        db,
        session,
        job_type=ImportJobType.DRY_RUN,
        running_status=ImportSessionStatus.DRY_RUN_RUNNING,
        failure_status=ImportSessionStatus.DRY_RUN_FAILED,
        work=work,
    )
    return session


async def run_execute(
    db: AsyncSession,
    session: ImportSession,
    *,
    actor_user_id: uuid.UUID,
    request: object | None = None,
) -> ImportSession:
    """Design architecture diagram, "Import Execution" stage. Requires a
    session whose dry run has already completed successfully -- execution
    can never be reached from any other state, so it is structurally
    impossible to execute a session that was never validated or
    dry-run-planned. `adapter.execute()` runs inside the same open
    transaction `_run_phase` manages; any exception it raises rolls back
    everything it attempted (design §4, "rollback on failure" / "no
    partial silent import"). Exactly one audit_logs entry is written, only
    on success, mirroring Roadmap PR12's "one entry per import commit
    batch" precedent."""
    _require_status(session, ImportSessionStatus.DRY_RUN_COMPLETED)
    adapter = _require_adapter(session.dataset_type)

    async def work(job: ImportJob) -> None:
        try:
            outcome = await adapter.execute(db, session)
        except ImportAdapterNotImplementedError:
            # Safe, expected, and clear on its own -- see ImportAdapter's
            # docstring. No concrete adapter can reach this in production
            # in this slice.
            raise
        except Exception as exc:
            # Mirrors Roadmap PR12's ImportCommitFailedError precedent: an
            # adapter's own internal failure is never leaked to the client
            # verbatim, only a generic, safe message -- the real exception
            # is still recorded server-side via ImportJob.error_message
            # (set by _run_phase's failure branch from this exception's
            # str(), not from the original).
            raise ImportExecutionFailedError(
                "Import execution failed unexpectedly. The entire batch was rolled back; no rows "
                "were imported."
            ) from exc

        session.imported_rows = outcome.created + outcome.updated
        session.executed_at = datetime.now(timezone.utc)
        session.status = ImportSessionStatus.COMPLETED
        await record_audit_event(
            db,
            actor_user_id=actor_user_id,
            action=AUDIT_ACTION_IMPORT,
            entity_type=AUDIT_ENTITY_IMPORT_SESSION,
            entity_id=session.id,
            after={
                "dataset_type": session.dataset_type,
                "created": outcome.created,
                "updated": outcome.updated,
                "skipped": outcome.skipped,
            },
            request=request,
        )

    await _run_phase(
        db,
        session,
        job_type=ImportJobType.EXECUTE,
        running_status=ImportSessionStatus.EXECUTING,
        failure_status=ImportSessionStatus.FAILED,
        work=work,
    )
    return session


async def cancel_session(db: AsyncSession, session: ImportSession) -> ImportSession:
    """Design §4: an operator may abandon a session any time before
    execution starts. Once EXECUTING has begun, cancellation is no longer
    offered (see `CANCELLABLE_SESSION_STATUSES`) -- the write phase always
    resolves to COMPLETED or FAILED on its own."""
    if session.status not in CANCELLABLE_SESSION_STATUSES:
        raise ImportSessionStateError(
            f"Import session {session.id} cannot be cancelled from state '{session.status.value}'."
        )
    session.status = ImportSessionStatus.CANCELLED
    await db.commit()
    return session
