import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_roles
from app.crud import audit as audit_crud
from app.db.session import get_db
from app.models.user import ROLE_ADMIN

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditLogOut(BaseModel):
    id: str
    user_id: str | None
    action: str
    entity_type: str
    entity_id: str | None
    request_id: str | None
    correlation_id: str | None
    ip_address: str | None
    created_at: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AuditLogOut])
async def list_audit_logs(
    entity_type: str | None = None,
    user_id: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(ROLE_ADMIN)),
):
    logs = await audit_crud.list_logs(
        db,
        entity_type=entity_type,
        user_id=uuid.UUID(user_id) if user_id else None,
        limit=limit,
    )
    return [
        AuditLogOut(
            id=str(log.id),
            user_id=str(log.user_id) if log.user_id else None,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=str(log.entity_id) if log.entity_id else None,
            request_id=log.request_id,
            correlation_id=log.correlation_id,
            ip_address=log.ip_address,
            created_at=log.created_at.isoformat(),
        )
        for log in logs
    ]
