"""Roadmap PR19A (Legacy Import Foundation) persistence helpers.

Pure data-access -- state-machine enforcement and business orchestration
live in `app.services.import_foundation`, never here, mirroring this
codebase's existing crud/service split (e.g. `app.crud.transaction` vs.
`app.services.borrow_service`).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.import_session import (
    ImportJob,
    ImportJobStatus,
    ImportJobType,
    ImportRowError,
    ImportSession,
    ImportSessionStatus,
)
from app.utils.pagination import decode_alpha_cursor, decode_cursor, encode_alpha_cursor, encode_cursor

DEFAULT_LIST_LIMIT = 25
MAX_LIST_LIMIT = 200


async def create_session(
    db: AsyncSession,
    *,
    dataset_type: str,
    created_by_user_id: uuid.UUID,
    idempotency_key: str | None,
    source_checksum: str | None,
    source_filename: str | None,
    notes: str | None,
) -> ImportSession:
    session = ImportSession(
        dataset_type=dataset_type,
        status=ImportSessionStatus.CREATED,
        created_by_user_id=created_by_user_id,
        idempotency_key=idempotency_key,
        source_checksum=source_checksum,
        source_filename=source_filename,
        notes=notes,
    )
    db.add(session)
    await db.flush()
    return session


async def get_by_idempotency_key(db: AsyncSession, *, dataset_type: str, idempotency_key: str) -> ImportSession | None:
    result = await db.execute(
        select(ImportSession).where(
            ImportSession.dataset_type == dataset_type,
            ImportSession.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, session_id: uuid.UUID) -> ImportSession | None:
    """Eager-loads `.jobs` (`selectinload`, a second bounded query -- a
    session has at most three jobs, one per phase) so
    `ImportSessionSummaryOut` can serialize it without an async-unsafe
    lazy load outside this function's own awaited call (see
    `app.models.import_session.ImportSession`'s `__mapper_args__` for the
    equivalent column-default fix this addresses for relationships)."""
    result = await db.execute(
        select(ImportSession).options(selectinload(ImportSession.jobs)).where(ImportSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def list_sessions(
    db: AsyncSession, *, limit: int, cursor: str | None, dataset_type: str | None
) -> tuple[list[ImportSession], str | None]:
    """Cursor-paginated, newest first -- same `(created_at DESC, id DESC)`
    keyset technique every other list endpoint in this codebase uses (see
    `app.utils.pagination`), applied to import sessions."""
    bounded_limit = max(1, min(limit, MAX_LIST_LIMIT))
    query = select(ImportSession)
    if dataset_type is not None:
        query = query.where(ImportSession.dataset_type == dataset_type)
    if cursor is not None:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        query = query.where(
            (ImportSession.created_at < cursor_created_at)
            | ((ImportSession.created_at == cursor_created_at) & (ImportSession.id < uuid.UUID(cursor_id)))
        )
    query = query.order_by(ImportSession.created_at.desc(), ImportSession.id.desc()).limit(bounded_limit + 1)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    next_cursor: str | None = None
    if len(rows) > bounded_limit:
        rows = rows[:bounded_limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
    return rows, next_cursor


async def create_job(db: AsyncSession, *, session_id: uuid.UUID, job_type: ImportJobType) -> ImportJob:
    job = ImportJob(
        import_session_id=session_id,
        job_type=job_type,
        status=ImportJobStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    return job


async def finish_job(db: AsyncSession, job: ImportJob, *, status: ImportJobStatus, error_message: str | None) -> None:
    job.status = status
    job.finished_at = datetime.now(timezone.utc)
    job.error_message = error_message
    await db.flush()


async def bulk_add_row_errors(db: AsyncSession, *, session_id: uuid.UUID, errors: list[ImportRowError]) -> None:
    for error in errors:
        error.import_session_id = session_id
        db.add(error)
    if errors:
        await db.flush()


async def list_row_errors(
    db: AsyncSession, *, session_id: uuid.UUID, limit: int, cursor: str | None
) -> tuple[list[ImportRowError], str | None]:
    """Cursor-paginated by `(row_number, id)` ascending -- report order
    matters here (a human reviewing failures wants row 1 before row 5,000),
    unlike the newest-first convention `list_sessions` above uses.

    `row_number` is nullable (a session-level error has none); every
    comparison below runs against `COALESCE(row_number, -1)` instead of the
    raw column so a session-level error always sorts first and NULL never
    needs its own SQL three-valued-logic branch."""
    bounded_limit = max(1, min(limit, MAX_LIST_LIMIT))
    ordering_key = func.coalesce(ImportRowError.row_number, -1)
    query = select(ImportRowError).where(ImportRowError.import_session_id == session_id)
    if cursor is not None:
        cursor_row_number, cursor_id = decode_row_error_cursor(cursor)
        query = query.where(
            (ordering_key > cursor_row_number)
            | ((ordering_key == cursor_row_number) & (ImportRowError.id > uuid.UUID(cursor_id)))
        )
    query = query.order_by(ordering_key.asc(), ImportRowError.id.asc()).limit(bounded_limit + 1)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    next_cursor: str | None = None
    if len(rows) > bounded_limit:
        rows = rows[:bounded_limit]
        last = rows[-1]
        next_cursor = encode_row_error_cursor(last.row_number, str(last.id))
    return rows, next_cursor


async def count_sessions(db: AsyncSession, *, dataset_type: str | None) -> int:
    query = select(func.count()).select_from(ImportSession)
    if dataset_type is not None:
        query = query.where(ImportSession.dataset_type == dataset_type)
    result = await db.execute(query)
    return int(result.scalar_one())


async def count_row_errors(db: AsyncSession, *, session_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count()).select_from(ImportRowError).where(ImportRowError.import_session_id == session_id)
    )
    return int(result.scalar_one())


def encode_row_error_cursor(row_number: int | None, id_: str) -> str:
    return encode_alpha_cursor(str(row_number if row_number is not None else -1), id_)


def decode_row_error_cursor(cursor: str) -> tuple[int, str]:
    raw_row_number, id_ = decode_alpha_cursor(cursor)
    return int(raw_row_number), id_
