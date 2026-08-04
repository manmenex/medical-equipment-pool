import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, require_roles
from app.core.exceptions import ImportSessionNotFoundError, InvalidInputError
from app.crud import import_session as import_crud
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.import_session import (
    ImportSessionCreate,
    ImportSessionOut,
    ImportSessionStatusOut,
    ImportSourceIn,
    ImportSourceOut,
)
from app.utils.pagination import decode_cursor, encode_cursor

# Roadmap PR19A1 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §21).
# Endpoints #1-#6 only: create, list, summary, status, source
# register/correct, cancel. No parser, validation, dry-run, execute,
# recover, or retention-cleanup endpoint ships with this slice (§25) --
# those, and the lease/heartbeat/recovery/completion-fencing mechanism
# they depend on, are PR19A2/PR19A3's deliverables.

router = APIRouter(prefix="/import-sessions", tags=["import-sessions"])


async def _get_or_404(db: AsyncSession, session_id: uuid.UUID):
    session = await import_crud.get_by_id(db, session_id)
    if session is None:
        raise ImportSessionNotFoundError(f"Import session '{session_id}' not found.")
    return session


@router.post("", response_model=ImportSessionOut)
async def create_session(
    payload: ImportSessionCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session, created = await import_crud.get_or_create_session(
        db,
        dataset_type=payload.dataset_type,
        idempotency_key=payload.idempotency_key,
        notes=payload.notes,
        created_by_user_id=actor.id,
    )
    if created:
        await db.commit()
    # §15.1: 201 for a genuinely new session, 200 for an idempotent replay.
    response.status_code = 201 if created else 200
    return session


@router.get("", response_model=Page[ImportSessionOut])
async def list_sessions(
    dataset_type: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    cursor_dt = None
    cursor_uuid = None
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        try:
            cursor_uuid = uuid.UUID(cursor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidInputError("Invalid or malformed pagination cursor.") from exc

    rows, total = await import_crud.list_sessions(
        db, dataset_type=dataset_type, limit=limit, cursor_dt=cursor_dt, cursor_id=cursor_uuid
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
    return Page(items=rows, next_cursor=next_cursor, total=total)


@router.get("/{session_id}", response_model=ImportSessionOut)
async def get_session_summary(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    return await _get_or_404(db, session_id)


@router.get("/{session_id}/status", response_model=ImportSessionStatusOut)
async def get_session_status(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    return await _get_or_404(db, session_id)


@router.post("/{session_id}/source", response_model=ImportSourceOut)
async def register_source(
    session_id: uuid.UUID,
    payload: ImportSourceIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    source, created = await import_crud.register_or_correct_source(
        db,
        session_id=session.id,
        dataset_type=session.dataset_type,
        checksum=payload.checksum,
        byte_size=payload.byte_size,
        content_type=payload.content_type,
        filename=payload.filename,
        source_version=payload.source_version,
    )
    # §15.2/§21 endpoint #5: 201 for the session's first registration, 200
    # for an idempotent no-op or a pre-freeze correction.
    response.status_code = 201 if created else 200
    return source


@router.post("/{session_id}/cancel", response_model=ImportSessionOut)
async def cancel_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_or_404(db, session_id)
    return await import_crud.cancel_session(db, session_id=session.id, expected_version=session.version)
