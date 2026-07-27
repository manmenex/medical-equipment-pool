"""Roadmap PR12 (Inventory Import): upload -> preview -> commit endpoints.

Administrator-only (docs/audits/04-consolidated-implementation-plan.md
Part D "PR12": "New Administrator-only import UI"). See
app.services.import_service for the full design.
"""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, require_roles
from app.core.redis import cache_delete_prefix
from app.db.session import get_db
from app.schemas.import_schemas import ImportCommitResponse, ImportPreviewResponse
from app.services.import_service import process_import

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/preview", response_model=ImportPreviewResponse)
async def preview_import(
    file: UploadFile = File(...),
    # Roadmap PR12 is update-only (see app.services.import_service's
    # module docstring). Defaults to True so an omitted field behaves
    # correctly; an explicit `false` is rejected by process_import with a
    # clear error rather than silently accepted.
    update_existing: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Parses and validates the uploaded file against current database
    state. Zero database writes occur, including audit writes -- see
    app.services.import_service.process_import's `commit=False` path.
    """
    result = await process_import(db, file=file, update_existing=update_existing, commit=False)
    return ImportPreviewResponse.model_validate(result)


@router.post("/commit", response_model=ImportCommitResponse)
async def commit_import(
    request: Request,
    file: UploadFile = File(...),
    # Roadmap PR12 is update-only (see app.services.import_service's
    # module docstring). Defaults to True so an omitted field behaves
    # correctly; an explicit `false` is rejected by process_import with a
    # clear error rather than silently accepted.
    update_existing: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Re-parses and re-validates the uploaded file from scratch -- never
    trusts a prior preview result supplied by the frontend (a stale or
    tampered client-side preview payload cannot influence what gets
    written). Valid rows commit in one transaction; an unexpected
    system/database failure rolls back the entire batch. Exactly one
    audit_logs entry is written for the batch itself.
    """
    result = await process_import(
        db,
        file=file,
        update_existing=update_existing,
        commit=True,
        actor_user_id=user.id,
        request=request,
    )
    await cache_delete_prefix("equipment:search:")
    await cache_delete_prefix("dashboard:")
    return ImportCommitResponse.model_validate(result)
