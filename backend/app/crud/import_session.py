import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ImportSessionInvalidStateError, ImportSourceMismatchError
from app.models.import_session import ImportJob, ImportRowError, ImportSession, ImportSource

# Roadmap PR19A1 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §6, §7,
# §15.1, §15.2, §20). Every state-changing operation here is a single,
# atomic conditional UPDATE -- never a load-then-mutate-then-commit
# sequence (§7) -- and every source-registration write is a single,
# self-contained statement with no preceding SELECT (§15.2), closing the
# TOCTOU race between a pre-freeze correction and a concurrent freeze.

_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
_CANCELLABLE_STATUSES = ("created", "validated", "validation_failed", "dry_run_completed", "dry_run_failed")

# §15.2: this foundation has no options fields yet -- the options
# fingerprint is a fixed hash of the empty object, computed once.
_EMPTY_OPTIONS_FINGERPRINT = hashlib.sha256(json.dumps({}, sort_keys=True).encode()).hexdigest()


def _source_fingerprint(*, checksum: str, byte_size: int, dataset_type: str, filename: str | None, source_version: str | None) -> str:
    """§15.2's identity fingerprint: SHA-256 of the canonical JSON of every
    identity-bearing field, including the owning session's dataset_type."""
    canonical = json.dumps(
        {
            "checksum": checksum,
            "byte_size": byte_size,
            "dataset_type": dataset_type,
            "filename": (filename or "").strip().lower(),
            "source_version": source_version,
            "options_fingerprint": _EMPTY_OPTIONS_FINGERPRINT,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


async def get_by_id(db: AsyncSession, session_id: uuid.UUID) -> ImportSession | None:
    return (await db.execute(select(ImportSession).where(ImportSession.id == session_id))).scalar_one_or_none()


async def get_source(db: AsyncSession, *, session_id: uuid.UUID) -> ImportSource | None:
    """Roadmap PR19A2 (design §6): `validate`'s admission gate needs to
    know whether a source row exists at all -- in either `registered` or
    `frozen` state -- before attempting any CAS transition."""
    return (
        await db.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))
    ).scalar_one_or_none()


async def get_session_jobs_and_finding_count(
    db: AsyncSession, *, session_id: uuid.UUID
) -> tuple[list[ImportJob], int]:
    """§21 endpoint #3's "session + jobs + finding count +
    validation_attempt_id". No endpoint in this foundation ever creates an
    `ImportJob` or `ImportRowError` row, so this always returns `([], 0)`
    today -- the query itself is the real, generic implementation PR19A2/
    PR19A3 populate data for, not a placeholder that changes shape later."""
    jobs = list(
        (
            await db.execute(
                select(ImportJob).where(ImportJob.import_session_id == session_id).order_by(ImportJob.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    finding_count = (
        await db.execute(
            select(func.count())
            .select_from(ImportRowError)
            .join(ImportJob, ImportRowError.import_job_id == ImportJob.id)
            .where(ImportJob.import_session_id == session_id)
        )
    ).scalar_one()
    return jobs, finding_count


async def get_or_create_session(
    db: AsyncSession, *, dataset_type: str, idempotency_key: str | None, notes: str | None, created_by_user_id: uuid.UUID
) -> tuple[ImportSession, bool]:
    """§15.1/§7: session creation carries no identity/checksum field at all
    -- `(dataset_type, idempotency_key)` alone is the idempotency key.

    - No `idempotency_key` -> always a new session (no accidental dedup).
    - Key present, no existing row -> create.
    - Key present, existing row -> return it, unconditionally an idempotent
      replay (no other field could ever disagree).

    Race-safe via INSERT-then-catch-IntegrityError-then-requery (§7's
    "session creation's own race-safety"), never SELECT-then-INSERT.

    Returns (session, created).
    """
    session = ImportSession(
        dataset_type=dataset_type,
        idempotency_key=idempotency_key,
        notes=notes,
        created_by_user_id=created_by_user_id,
        status="created",
        version=0,
    )
    db.add(session)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        if idempotency_key is None:
            # No idempotency key was supplied, so the only unique
            # constraint that could have fired requires one -- this must
            # be a different, unrelated integrity failure; re-raise.
            raise
        existing = (
            await db.execute(
                select(ImportSession).where(
                    ImportSession.dataset_type == dataset_type, ImportSession.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return existing, False
    return session, True


async def list_sessions(
    db: AsyncSession, *, dataset_type: str | None, limit: int, cursor_dt: datetime | None, cursor_id: uuid.UUID | None
) -> tuple[list[ImportSession], int]:
    """§20/§21 endpoint #2 -- cursor-paginated, side-effect free. Caller
    (the API layer) has already decoded/validated the cursor via
    `app.utils.pagination.decode_cursor` and parsed `cursor_id` as a UUID,
    raising `InvalidInputError` before this function is ever called (§20's
    "fail-fast, no query executed first")."""
    filters = []
    if dataset_type is not None:
        filters.append(ImportSession.dataset_type == dataset_type)

    stmt = select(ImportSession).where(*filters) if filters else select(ImportSession)
    if cursor_dt is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(
                ImportSession.created_at < cursor_dt,
                and_(ImportSession.created_at == cursor_dt, ImportSession.id < cursor_id),
            )
        )
    stmt = stmt.order_by(ImportSession.created_at.desc(), ImportSession.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    count_stmt = select(func.count()).select_from(ImportSession)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = (await db.execute(count_stmt)).scalar_one()

    return rows, total


async def cancel_session(db: AsyncSession, *, session_id: uuid.UUID, expected_version: int) -> ImportSession:
    """§7's atomic conditional UPDATE, applied to the cancel transition.
    Endpoint #6 (§21) -- cancellable only from a non-running,
    non-terminal state."""
    result = await db.execute(
        update(ImportSession)
        .where(
            ImportSession.id == session_id,
            ImportSession.status.in_(_CANCELLABLE_STATUSES),
            ImportSession.version == expected_version,
        )
        .values(status="cancelled", version=ImportSession.version + 1, terminal_at=datetime.now(timezone.utc))
        .returning(ImportSession)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ImportSessionInvalidStateError(
            "Session cannot be cancelled from its current state, or was modified concurrently -- re-fetch and retry."
        )
    await db.commit()
    return row


async def register_or_correct_source(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    dataset_type: str,
    checksum: str,
    byte_size: int,
    content_type: str | None,
    filename: str | None,
    source_version: str | None,
) -> tuple[ImportSource, bool]:
    """§15.2 -- the sole identity/checksum contract. A plain INSERT first
    (never a SELECT first); on a UNIQUE(import_session_id) violation, the
    correction is a single atomic CAS `UPDATE ... WHERE status =
    'registered'`, never a `SELECT` followed by a separate branch-and-
    `UPDATE`. Returns (source, created).
    """
    fingerprint = _source_fingerprint(
        checksum=checksum, byte_size=byte_size, dataset_type=dataset_type, filename=filename, source_version=source_version
    )
    source = ImportSource(
        import_session_id=session_id,
        status="registered",
        checksum=checksum,
        byte_size=byte_size,
        content_type=content_type,
        filename=filename,
        source_version=source_version,
        options_fingerprint=_EMPTY_OPTIONS_FINGERPRINT,
        source_fingerprint=fingerprint,
        created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
    else:
        await db.commit()
        return source, True

    # §15.2's atomic correction -- one CAS UPDATE, no prior SELECT. This
    # statement's WHERE clause is evaluated atomically by PostgreSQL as
    # part of the UPDATE itself; there is no window for a concurrent
    # freeze (§6) to land in between a "check" and an "act".
    result = await db.execute(
        update(ImportSource)
        .where(ImportSource.import_session_id == session_id, ImportSource.status == "registered")
        .values(
            checksum=checksum,
            byte_size=byte_size,
            content_type=content_type,
            filename=filename,
            source_version=source_version,
            options_fingerprint=_EMPTY_OPTIONS_FINGERPRINT,
            source_fingerprint=fingerprint,
        )
        .returning(ImportSource)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        await db.commit()
        return row, False

    # The CAS UPDATE affected zero rows -- the source is 'frozen' (the
    # only other possible state, since the INSERT failure already proved a
    # row exists). Frozen is terminal and never reversed, so a plain
    # SELECT now carries no race.
    await db.rollback()
    existing = (
        await db.execute(select(ImportSource).where(ImportSource.import_session_id == session_id))
    ).scalar_one_or_none()
    if existing is None:
        # Should be unreachable (the INSERT failure proved a row exists),
        # but never silently proceed on an assumption that turned out false.
        raise ImportSourceMismatchError("Source registration state could not be determined; retry.")
    if existing.source_fingerprint == fingerprint:
        return existing, False
    raise ImportSourceMismatchError(
        "This session's source is already frozen with a different identity fingerprint. The row is never mutated once frozen."
    )


async def freeze_source_and_transition_to_validating(
    db: AsyncSession, *, session_id: uuid.UUID, expected_version: int
) -> tuple[bool, ImportSession | None]:
    """§6's freeze-and-transition, one transaction, two statements. Not
    called by any endpoint in PR19A1 (no `/validate` endpoint ships with
    this slice) -- authored here as the reusable primitive PR19A2's
    `validate` admission calls (§25: "source registration and the freeze
    mechanism ... invoked by validate in PR19A2 but authored here").

    Returns (source_row_existed, session_row_or_None). `session_row is
    None` means the session's own CAS did not match (wrong state or stale
    version) -- the caller must re-fetch and decide how to respond; this
    function performs no source-existence check of its own (that is
    `/validate`'s job, via `IMPORT_SOURCE_NOT_REGISTERED`, §6/§23 -- out of
    scope for this foundation slice).
    """
    freeze_result = await db.execute(
        update(ImportSource)
        .where(ImportSource.import_session_id == session_id, ImportSource.status == "registered")
        .values(status="frozen", frozen_at=datetime.now(timezone.utc))
        .returning(ImportSource.id)
    )
    source_existed = freeze_result.first() is not None

    session_result = await db.execute(
        update(ImportSession)
        .where(
            ImportSession.id == session_id,
            ImportSession.status.in_(("created", "validated", "validation_failed")),
            ImportSession.version == expected_version,
        )
        .values(status="validating", version=ImportSession.version + 1)
        .returning(ImportSession)
    )
    session_row = session_result.scalar_one_or_none()
    if session_row is None:
        await db.rollback()
        return source_existed, None
    await db.commit()
    return source_existed, session_row
