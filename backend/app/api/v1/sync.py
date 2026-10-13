"""Roadmap PR25E slice B2 -- ``POST /api/v1/sync/operations``
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 6.1; docs/api/sync.md)."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import EQUIPMENT_POOL_OPERATION_ROLES, require_roles
from app.db.session import get_db
from app.schemas.sync import SyncBatchRequest, SyncBatchResponse
from app.services import sync_service

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/operations", response_model=SyncBatchResponse)
async def submit_operations(
    payload: SyncBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    results = await sync_service.process_batch(db, payload.operations, user, ip_address=ip, user_agent=ua)
    return SyncBatchResponse(results=results)
