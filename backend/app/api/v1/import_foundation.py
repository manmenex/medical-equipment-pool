"""Roadmap PR19A (Legacy Import Foundation): the import-session lifecycle
API skeleton. See app.services.import_foundation for the full design.

Administrator-only, matching Roadmap PR12's precedent for import endpoints
(design: "Import endpoints must require elevated permissions. No
unrestricted upload endpoints."). No parser is implemented in this slice --
`POST /import-sessions/{id}/validate` accepts no request body and always
fails with `IMPORT_ADAPTER_NOT_REGISTERED` (422) for every dataset_type,
since `app.services.import_foundation.registry` ships empty. This is the
honest, structural proof that the API contract, permission gate, and
session state machine are wired end-to-end without pretending a real
import can succeed yet.
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, require_roles
from app.core.exceptions import ImportSessionNotFoundError
from app.crud import import_session as import_session_crud
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.import_foundation import (
    ImportJobOut,
    ImportRowErrorOut,
    ImportSessionCreate,
    ImportSessionOut,
    ImportSessionStatusOut,
    ImportSessionSummaryOut,
)
from app.services import import_foundation as import_foundation_service

router = APIRouter(prefix="/import-sessions", tags=["import-foundation"])


async def _get_session_or_404(db: AsyncSession, session_id: uuid.UUID):
    session = await import_session_crud.get_by_id(db, session_id)
    if session is None:
        raise ImportSessionNotFoundError(f"Import session {session_id} was not found.")
    return session


@router.post("", response_model=ImportSessionOut)
async def create_import_session(
    payload: ImportSessionCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Design, "create import session". Idempotent: a repeated call with
    the same `(dataset_type, idempotency_key)` returns the existing
    session unchanged rather than creating a duplicate."""
    session, _created = await import_foundation_service.get_or_create_session(
        db,
        dataset_type=payload.dataset_type,
        created_by_user_id=user.id,
        idempotency_key=payload.idempotency_key,
        source_checksum=payload.source_checksum,
        source_filename=payload.source_filename,
        notes=payload.notes,
    )
    return ImportSessionOut.model_validate(session)


@router.get("", response_model=Page[ImportSessionOut])
async def list_import_sessions(
    dataset_type: str | None = None,
    limit: int = Query(default=25, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    rows, next_cursor = await import_session_crud.list_sessions(
        db, limit=limit, cursor=cursor, dataset_type=dataset_type
    )
    total = await import_session_crud.count_sessions(db, dataset_type=dataset_type)
    items = [ImportSessionOut.model_validate(row) for row in rows]
    return Page(items=items, next_cursor=next_cursor, total=total)


@router.get("/{session_id}", response_model=ImportSessionSummaryOut)
async def get_import_session_summary(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Design, "import summary" -- the "Import result summary model"."""
    session = await _get_session_or_404(db, session_id)
    error_count = await import_session_crud.count_row_errors(db, session_id=session.id)
    return ImportSessionSummaryOut(
        session=ImportSessionOut.model_validate(session),
        jobs=[ImportJobOut.model_validate(job) for job in session.jobs],
        error_count=error_count,
    )


@router.get("/{session_id}/status", response_model=ImportSessionStatusOut)
async def get_import_session_status(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Design, "import status" -- lightweight, poll-friendly."""
    session = await _get_session_or_404(db, session_id)
    return ImportSessionStatusOut.model_validate(session)


@router.get("/{session_id}/errors", response_model=Page[ImportRowErrorOut])
async def list_import_session_errors(
    session_id: uuid.UUID,
    limit: int = Query(default=25, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    await _get_session_or_404(db, session_id)
    rows, next_cursor = await import_session_crud.list_row_errors(
        db, session_id=session_id, limit=limit, cursor=cursor
    )
    total = await import_session_crud.count_row_errors(db, session_id=session_id)
    items = [ImportRowErrorOut.model_validate(row) for row in rows]
    return Page(items=items, next_cursor=next_cursor, total=total)


@router.post("/{session_id}/validate", response_model=ImportSessionOut)
async def validate_import_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Design, "validate import". No request body: no parser is
    implemented in this slice, so there is no raw input for this endpoint
    to accept yet -- see module docstring."""
    session = await _get_session_or_404(db, session_id)
    session = await import_foundation_service.run_validation(db, session, raw_input=None)
    return ImportSessionOut.model_validate(session)


@router.post("/{session_id}/dry-run", response_model=ImportSessionOut)
async def dry_run_import_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Design, "dry run"."""
    session = await _get_session_or_404(db, session_id)
    session = await import_foundation_service.run_dry_run(db, session)
    return ImportSessionOut.model_validate(session)


@router.post("/{session_id}/execute", response_model=ImportSessionOut)
async def execute_import_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Design, "execute import"."""
    session = await _get_session_or_404(db, session_id)
    session = await import_foundation_service.run_execute(
        db, session, actor_user_id=user.id, request=request
    )
    return ImportSessionOut.model_validate(session)


@router.post("/{session_id}/cancel", response_model=ImportSessionOut)
async def cancel_import_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    session = await _get_session_or_404(db, session_id)
    session = await import_foundation_service.cancel_session(db, session)
    return ImportSessionOut.model_validate(session)
