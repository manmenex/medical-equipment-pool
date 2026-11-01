"""Roadmap PR25B -- Administrator management of export API keys. Human JWT
(administrator only); the machine key itself can reach none of this."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_roles
from app.core.audit import AUDIT_ACTION_CREATE, AUDIT_ACTION_UPDATE, record_audit_event
from app.core.exceptions import ResourceNotFoundError
from app.db.session import get_db
from app.models.export import ExportApiKey
from app.models.user import ROLE_ADMINISTRATOR
from app.schemas.export import ExportKeyCreate, ExportKeyCreated, ExportKeyOut
from app.services import export_service

router = APIRouter(prefix="/export-keys", tags=["export-keys"])
AUDIT_ENTITY_EXPORT_API_KEY = "export_api_key"


def _out(row: ExportApiKey) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "key_prefix": row.key_prefix,
        "created_at": row.created_at,
        "revoked_at": row.revoked_at,
        "last_used_at": row.last_used_at,
    }


@router.get("", response_model=list[ExportKeyOut])
async def list_keys(db: AsyncSession = Depends(get_db), _user=Depends(require_roles(ROLE_ADMINISTRATOR))):
    return [_out(r) for r in await export_service.list_keys(db)]


@router.post("", response_model=ExportKeyCreated, status_code=201)
async def create_key(
    payload: ExportKeyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(ROLE_ADMINISTRATOR)),
):
    row, key = await export_service.create_key(db, name=payload.name, created_by=actor.id)
    await record_audit_event(
        db,
        actor_user_id=actor.id,
        action=AUDIT_ACTION_CREATE,
        entity_type=AUDIT_ENTITY_EXPORT_API_KEY,
        entity_id=row.id,
        after={"name": row.name, "key_prefix": row.key_prefix},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return {**_out(row), "key": key}


@router.post("/{key_id}/revoke", response_model=ExportKeyOut)
async def revoke_key(
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(ROLE_ADMINISTRATOR)),
):
    row = (await db.execute(select(ExportApiKey).where(ExportApiKey.id == key_id))).scalar_one_or_none()
    if row is None:
        raise ResourceNotFoundError("Export API key not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        row.revoked_by_user_id = actor.id
        await record_audit_event(
            db,
            actor_user_id=actor.id,
            action=AUDIT_ACTION_UPDATE,
            entity_type=AUDIT_ENTITY_EXPORT_API_KEY,
            entity_id=row.id,
            before={"revoked": False},
            after={"revoked": True},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
    return _out(row)
