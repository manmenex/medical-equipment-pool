import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_session import ImportJob, ImportRowError, ImportSession, ImportSource

# Roadmap PR19A2 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §9,
# §12). Every completion write here is a single, atomic conditional
# UPDATE fenced on lease_owner + lease_generation (+ session.version for
# the session-level statement) -- never a load-then-mutate-then-commit
# sequence. Functions that participate in a caller-owned transaction
# boundary (the fenced_* functions) never call db.commit()/db.rollback()
# themselves; the caller (app.services.import_validation_service) decides
# the boundary.

# §25: "generic across job_type... only a small per-job_type mapping to
# session-status values". PR19A2 adds exactly one entry (validate);
# PR19A3 extends this same mapping for dry_run/execute -- the /recover
# endpoint and completion-fencing mechanism themselves are unchanged.
PHASE_STATUS_MAP: dict[str, dict[str, str]] = {
    "validate": {"running_status": "validating", "failure_status": "validation_failed"},
    "dry_run": {"running_status": "dry_run_running", "failure_status": "dry_run_failed"},
    "execute": {"running_status": "executing", "failure_status": "failed"},
}

_ALLOWED_VALIDATE_ADMISSION_STATUSES = ("created", "validated", "validation_failed")


async def _claim_session_and_insert_job(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    job_type: str,
    allowed_from_statuses: tuple[str, ...],
    running_status: str,
    expected_version: int,
    lease_owner: uuid.UUID,
    lease_duration_seconds: int,
    now: datetime,
) -> tuple[ImportSession | None, ImportJob | None]:
    """§9.1/§25's single, shared session-CAS + lease-acquisition primitive.
    Every phase (`validate`, `dry_run`, `execute`) admits through this one
    implementation -- there is exactly one algorithm for "atomically move
    the session into its RUNNING status and open a leased job row",
    parameterized only by the per-phase policy values callers already
    have (allowed source statuses, the RUNNING status, the job_type).
    Never commits or rolls back -- the caller owns the transaction
    boundary (validate's admission additionally freezes the source in the
    same transaction; a later phase has nothing left to freeze, §6).
    Returns `(session_row_or_None, job_row_or_None)`; `None` means the CAS
    did not match (wrong state or stale version) -- the caller must
    re-fetch and decide how to respond (§23), never proceed as if it had
    won."""
    session_result = await db.execute(
        update(ImportSession)
        .where(
            ImportSession.id == session_id,
            ImportSession.status.in_(allowed_from_statuses),
            ImportSession.version == expected_version,
        )
        .values(status=running_status, version=ImportSession.version + 1)
        .returning(ImportSession)
    )
    session_row = session_result.scalar_one_or_none()
    if session_row is None:
        return None, None

    attempt_number_subq = select(func.coalesce(func.max(ImportJob.attempt_number), 0) + 1).where(
        ImportJob.import_session_id == session_id, ImportJob.job_type == job_type
    )
    attempt_number = (await db.execute(attempt_number_subq)).scalar_one()

    job = ImportJob(
        import_session_id=session_id,
        job_type=job_type,
        status="running",
        attempt_number=attempt_number,
        lease_owner=lease_owner,
        lease_generation=1,
        lease_expires_at=now + timedelta(seconds=lease_duration_seconds),
        heartbeat_at=now,
        started_at=now,
    )
    db.add(job)
    await db.flush()
    return session_row, job


async def admit_validate_job(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    expected_version: int,
    lease_owner: uuid.UUID,
    lease_duration_seconds: int,
) -> tuple[bool, ImportSession | None, ImportJob | None]:
    """§6's freeze-and-transition plus §9.1's lease acquisition (via
    `_claim_session_and_insert_job`), fused into one transaction -- design
    §9.1 requires the job INSERT to share the same transaction as the
    session's own CAS, which PR19A1's
    `freeze_source_and_transition_to_validating` (which commits on its
    own) cannot compose with a third statement. This function performs
    the freeze, then the shared CAS + job-insert primitive, then commits
    once, all three together.

    Returns (source_row_existed, session_row_or_None, job_row_or_None).
    `session_row is None` means the session's own CAS did not match (wrong
    state or stale version, or the source did not exist at all) -- the
    caller must re-fetch and decide how to respond (§23's error codes),
    never proceed as if it had won.
    """
    now = datetime.now(timezone.utc)

    freeze_result = await db.execute(
        update(ImportSource)
        .where(ImportSource.import_session_id == session_id, ImportSource.status == "registered")
        .values(status="frozen", frozen_at=now)
        .returning(ImportSource.id)
    )
    source_existed = freeze_result.first() is not None

    session_row, job = await _claim_session_and_insert_job(
        db,
        session_id=session_id,
        job_type="validate",
        allowed_from_statuses=_ALLOWED_VALIDATE_ADMISSION_STATUSES,
        running_status="validating",
        expected_version=expected_version,
        lease_owner=lease_owner,
        lease_duration_seconds=lease_duration_seconds,
        now=now,
    )
    if session_row is None:
        await db.rollback()
        return source_existed, None, None

    await db.commit()
    return source_existed, session_row, job


async def admit_phase_job(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    job_type: str,
    allowed_from_statuses: tuple[str, ...],
    running_status: str,
    expected_version: int,
    lease_owner: uuid.UUID,
    lease_duration_seconds: int,
) -> tuple[ImportSession | None, ImportJob | None]:
    """Roadmap PR19A3 (design §9.1, §25): dry-run/execute admission,
    through the same `_claim_session_and_insert_job` primitive
    `admit_validate_job` uses above -- without validate's own
    source-freeze step (the source is already frozen by the time a
    session can ever reach `validated`, §6 -- there is nothing left to
    freeze for a later phase). Returns `(session_row_or_None,
    job_row_or_None)`; `None` means the CAS did not match (wrong state or
    stale version) -- the caller must re-fetch and decide how to respond
    (§23), never proceed as if it had won."""
    session_row, job = await _claim_session_and_insert_job(
        db,
        session_id=session_id,
        job_type=job_type,
        allowed_from_statuses=allowed_from_statuses,
        running_status=running_status,
        expected_version=expected_version,
        lease_owner=lease_owner,
        lease_duration_seconds=lease_duration_seconds,
        now=datetime.now(timezone.utc),
    )
    if session_row is None:
        await db.rollback()
        return None, None

    await db.commit()
    return session_row, job


async def get_running_job(db: AsyncSession, *, session_id: uuid.UUID, job_type: str) -> ImportJob | None:
    return (
        await db.execute(
            select(ImportJob).where(
                ImportJob.import_session_id == session_id, ImportJob.job_type == job_type, ImportJob.status == "running"
            )
        )
    ).scalar_one_or_none()


async def renew_lease(
    db: AsyncSession, *, job_id: uuid.UUID, lease_owner: uuid.UUID, lease_generation: int, lease_duration_seconds: int
) -> bool:
    """§9.2's renewal UPDATE. Commits on its own -- the renewal loop's
    session is never shared with the main work's transaction. Returns
    whether the lease was actually renewed (a clean 0-row result means the
    lease is definitely lost; the caller stops renewing immediately, no
    retry -- see the renewal loop's own docstring for why this differs
    from a raised exception)."""
    result = await db.execute(
        update(ImportJob)
        .where(
            ImportJob.id == job_id,
            ImportJob.lease_owner == lease_owner,
            ImportJob.lease_generation == lease_generation,
            ImportJob.status == "running",
        )
        .values(
            lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=lease_duration_seconds),
            heartbeat_at=datetime.now(timezone.utc),
        )
        .returning(ImportJob.id)
    )
    renewed = result.first() is not None
    await db.commit()
    return renewed


async def _fence_job_terminal(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    lease_owner: uuid.UUID,
    lease_generation: int,
    new_status: str,
    error_message: str | None,
) -> bool:
    """§9.4.1/§9.4.2's single, shared job-fencing predicate: the exact
    same `WHERE id/lease_owner/lease_generation/status='running'` CAS,
    whether the outcome being published is success or failure, for every
    phase. Returns whether the fenced row was found -- a `False` result
    (zero rows matched) is the unambiguous "this worker was fenced out"
    signal every caller must interpret identically (§9.4.1 step 6 /
    §9.4.2 step 5)."""
    job_result = await db.execute(
        update(ImportJob)
        .where(
            ImportJob.id == job_id,
            ImportJob.lease_owner == lease_owner,
            ImportJob.lease_generation == lease_generation,
            ImportJob.status == "running",
        )
        .values(status=new_status, finished_at=datetime.now(timezone.utc), error_message=error_message)
        .returning(ImportJob.id)
    )
    return job_result.first() is not None


async def _fence_session_terminal(
    db: AsyncSession, *, session_id: uuid.UUID, running_status: str, expected_version: int, values: dict
) -> ImportSession | None:
    """§9.4.1/§9.4.2's single, shared session-fencing predicate: the exact
    same `WHERE id/status=running_status/version=expected_version` CAS for
    every phase's terminal publication, success or failure. `values` is
    the only thing that varies per call -- per-phase result columns, or
    the shared status/version/updated_at/failure_reason base every caller
    already supplies."""
    session_result = await db.execute(
        update(ImportSession)
        .where(ImportSession.id == session_id, ImportSession.status == running_status, ImportSession.version == expected_version)
        .values(**values)
        .returning(ImportSession)
    )
    return session_result.scalar_one_or_none()


async def fenced_phase_success(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    lease_owner: uuid.UUID,
    lease_generation: int,
    session_id: uuid.UUID,
    expected_version: int,
    running_status: str,
    new_session_status: str,
    extra_session_values: dict | Callable[[datetime], dict] | None = None,
) -> ImportSession | None:
    """§9.4.1/§25's single, shared fenced-success primitive -- validate,
    dry-run, and execute all publish success through this one
    implementation of the job/session fencing mechanics
    (`_fence_job_terminal`/`_fence_session_terminal`), parameterized by
    `running_status` (each phase has its own `*_RUNNING` value) and
    `extra_session_values` (each phase persists different completion
    columns: validate's `current_validation_job_id`/row-count columns;
    dry-run's `dry_run_completed_at`; execute's
    `executed_at`/`imported_rows`/`terminal_at`). No commit (the caller's
    TX1 owns the boundary). Returns `None` if either fencing UPDATE
    affected zero rows -- the caller must roll back the entire
    transaction and follow the failure path (§9.4.2), never commit a
    partial result.

    Chronology (PR19A3 review round 2): `job.finished_at` (inside
    `_fence_job_terminal`) is always established *before* this function's
    own `now`, which in turn is always established *before* the session's
    own completion timestamp -- `job fence -> job completion timestamp ->
    session completion timestamp`, never the reverse. `extra_session_values`
    accepts either a plain dict (for values with no ordering constraint,
    e.g. row counts) or a `Callable[[datetime], dict]` that receives this
    exact `now` -- the only way a caller can set an operation-specific
    completion timestamp (`validated_at`, `dry_run_completed_at`,
    `executed_at`/`terminal_at`) is by deriving it from the value handed
    to it here, never by computing its own `datetime.now()` before calling
    this function (which would race ahead of the job fence's own
    timestamp -- exactly the bug this fixes)."""
    if not await _fence_job_terminal(
        db, job_id=job_id, lease_owner=lease_owner, lease_generation=lease_generation, new_status="succeeded", error_message=None
    ):
        return None

    now = datetime.now(timezone.utc)
    values: dict = {
        "status": new_session_status,
        "version": ImportSession.version + 1,
        "updated_at": now,
    }
    if callable(extra_session_values):
        values.update(extra_session_values(now))
    elif extra_session_values:
        values.update(extra_session_values)
    return await _fence_session_terminal(
        db, session_id=session_id, running_status=running_status, expected_version=expected_version, values=values
    )


async def fenced_phase_failure(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    lease_owner: uuid.UUID,
    lease_generation: int,
    session_id: uuid.UUID,
    expected_version: int,
    running_status: str,
    failure_status: str,
    bounded_error_message: str,
    extra_session_values: dict | Callable[[datetime], dict] | None = None,
) -> ImportSession | None:
    """§9.4.2/§25's single, shared fenced-failure primitive -- the
    failure-path counterpart to `fenced_phase_success` above, through the
    same shared `_fence_job_terminal`/`_fence_session_terminal`
    mechanics. `extra_session_values` lets execute set `terminal_at`
    (FAILED is terminal, §5) while dry-run leaves it untouched
    (DRY_RUN_FAILED is not terminal). No commit (the caller's TX2 owns
    the boundary). Returns `None` if either fencing UPDATE affected zero
    rows -- this worker has also been fenced out on its own failure
    publication (§9.4.2 step 5); the caller must roll back TX2 and write
    a fence-lost audit entry in a separate TX3, never overwrite whatever
    the new owner already wrote.

    Same chronology guarantee as `fenced_phase_success` above: the
    `Callable[[datetime], dict]` form of `extra_session_values` receives
    `now`, established only after `_fence_job_terminal` succeeds, so
    `job.finished_at <= session`'s own failure-completion timestamp
    (e.g. execute's `terminal_at`) always holds -- never computed by the
    caller ahead of the fence."""
    if not await _fence_job_terminal(
        db,
        job_id=job_id,
        lease_owner=lease_owner,
        lease_generation=lease_generation,
        new_status="failed",
        error_message=bounded_error_message,
    ):
        return None

    now = datetime.now(timezone.utc)
    values: dict = {
        "status": failure_status,
        "version": ImportSession.version + 1,
        "updated_at": now,
        "failure_reason": bounded_error_message,
    }
    if callable(extra_session_values):
        values.update(extra_session_values(now))
    elif extra_session_values:
        values.update(extra_session_values)
    return await _fence_session_terminal(
        db, session_id=session_id, running_status=running_status, expected_version=expected_version, values=values
    )


async def fenced_success(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    lease_owner: uuid.UUID,
    lease_generation: int,
    session_id: uuid.UUID,
    expected_version: int,
    new_session_status: str,
    total_rows: int,
    valid_rows: int,
    invalid_rows: int,
    warning_rows: int,
) -> ImportSession | None:
    """§9.4.1's fenced success publication for `validate` -- a thin,
    validate-specific wrapper over the shared `fenced_phase_success`
    primitive above (§25: validate, dry-run, and execute share one
    fencing implementation; only the per-phase result columns differ).
    §12: `current_validation_job_id` is promoted unconditionally whenever
    the job reaches `succeeded`, regardless of whether `new_session_status`
    is `validated` or `validation_failed` -- a completed pass that finds
    blocking errors is still a legitimate "current" result.

    PR19A3 review round 2: `validated_at` is derived from the `now`
    `fenced_phase_success` hands back via its callback -- established
    only *after* the job fence succeeds -- never computed here ahead of
    time. This restores PR19A2's original observable chronology
    (`job.finished_at <= session.validated_at == session.updated_at`),
    which a prior refactor round accidentally inverted by capturing this
    wrapper's own `now` before calling into the shared primitive. No
    commit (the caller's TX1 owns the boundary)."""
    return await fenced_phase_success(
        db,
        job_id=job_id,
        lease_owner=lease_owner,
        lease_generation=lease_generation,
        session_id=session_id,
        expected_version=expected_version,
        running_status="validating",
        new_session_status=new_session_status,
        extra_session_values=lambda now: {
            "validated_at": now,
            "current_validation_job_id": job_id,
            "total_rows": total_rows,
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "warning_rows": warning_rows,
        },
    )


async def fenced_failure(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    lease_owner: uuid.UUID,
    lease_generation: int,
    session_id: uuid.UUID,
    expected_version: int,
    failure_status: str,
    bounded_error_message: str,
) -> ImportSession | None:
    """§9.4.2 steps 3-4's best-effort fenced failure publication for
    `validate` -- a thin, validate-specific wrapper over the shared
    `fenced_phase_failure` primitive above (§25). No commit (the caller's
    TX2 owns the boundary). Returns `None` if either fencing UPDATE
    affected zero rows -- this worker has also been fenced out on its own
    failure publication (§9.4.2 step 5); the caller must roll back TX2
    and write a fence-lost audit entry in a separate TX3, never overwrite
    whatever the new owner already wrote."""
    return await fenced_phase_failure(
        db,
        job_id=job_id,
        lease_owner=lease_owner,
        lease_generation=lease_generation,
        session_id=session_id,
        expected_version=expected_version,
        running_status="validating",
        failure_status=failure_status,
        bounded_error_message=bounded_error_message,
    )


async def claim_stale_job(db: AsyncSession, *, session_id: uuid.UUID) -> ImportJob | None:
    """§9.3 step 1 -- atomically claims *a* stale-running job for this
    session (job_type-generic: whichever job_type this session currently
    has running). Does not commit; the caller performs the session
    transition in the same transaction before committing."""
    result = await db.execute(
        update(ImportJob)
        .where(
            ImportJob.import_session_id == session_id,
            ImportJob.status == "running",
            ImportJob.lease_expires_at < datetime.now(timezone.utc),
        )
        .values(
            status="abandoned",
            finished_at=datetime.now(timezone.utc),
            error_message="stale: lease expired, process interruption presumed",
        )
        .returning(ImportJob)
    )
    return result.scalar_one_or_none()


async def transition_session_for_recovery(
    db: AsyncSession, *, session_id: uuid.UUID, running_status: str, failure_status: str
) -> ImportSession | None:
    """§9.3 step 2 -- the owning session's transition, in the same
    transaction as `claim_stale_job`. Does not commit."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(ImportSession)
        .where(ImportSession.id == session_id, ImportSession.status == running_status)
        .values(
            status=failure_status,
            version=ImportSession.version + 1,
            failure_reason="recovered: prior attempt abandoned after lease expiry",
            terminal_at=now if failure_status in ("completed", "failed", "cancelled") else ImportSession.terminal_at,
            updated_at=now,
        )
        .returning(ImportSession)
    )
    return result.scalar_one_or_none()


MAX_ROW_NUMBER_SORT_VALUE = 2**31 - 1


def _finding_sort_value(row_number_column):
    # ImportRowError.row_number is nullable (§4.4) -- NULLs sort last, tied
    # rows broken by id (see list_findings' cursor comparison below).
    return func.coalesce(row_number_column, MAX_ROW_NUMBER_SORT_VALUE)


async def list_findings(
    db: AsyncSession, *, job_id: uuid.UUID, limit: int, cursor_n: int | None, cursor_id: uuid.UUID | None
) -> tuple[list[ImportRowError], int]:
    """§12's "current vs. historical" contract: the caller resolves
    `attempt_id`/`current_validation_job_id` to a concrete `job_id` before
    calling this -- this function only ever lists one job's findings."""
    sort_value = _finding_sort_value(ImportRowError.row_number)
    stmt = select(ImportRowError).where(ImportRowError.import_job_id == job_id)
    if cursor_n is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(sort_value > cursor_n, and_(sort_value == cursor_n, ImportRowError.id > cursor_id))
        )
    stmt = stmt.order_by(sort_value.asc(), ImportRowError.id.asc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    total = (
        await db.execute(select(func.count()).select_from(ImportRowError).where(ImportRowError.import_job_id == job_id))
    ).scalar_one()
    return rows, total
