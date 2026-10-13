"""Roadmap PR25E slice B2 -- ``POST /api/v1/sync/operations``
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 6.1; docs/api/sync.md)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    ADMINISTRATOR_ONLY_ROLES,
    EQUIPMENT_POOL_OPERATION_ROLES,
    VIEW_AND_REPORT_ROLES,
    require_roles,
)
from app.core.exceptions import InvalidInputError
from app.db.session import get_db
from app.schemas.sync import SyncBatchRequest, SyncBatchResponse
from app.schemas.sync_read import (
    SyncSnapshotPage,
    SyncStatsResponse,
    SyncStatusResponse,
    SyncVerifyRequest,
    SyncVerifyResponse,
)
from app.services import sync_service, sync_snapshot_service, sync_verify_service

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


@router.post("/verify", response_model=SyncVerifyResponse)
async def verify_operations(
    payload: SyncVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    unknown = await sync_verify_service.verify(db, user.id, payload.op_ids, ip_address=ip, user_agent=ua)
    return SyncVerifyResponse(checked=len(set(payload.op_ids)), unknown_op_ids=unknown)


@router.get("/snapshot", response_model=SyncSnapshotPage)
async def get_snapshot(
    request: Request,
    section: str = Query(..., description="equipment | wards | departments | locations | open_transactions"),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=sync_snapshot_service.DEFAULT_LIMIT, ge=1, le=sync_snapshot_service.MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    page = await sync_snapshot_service.get_page(db, section, cursor, limit)
    headers = {"ETag": page["etag"], "Cache-Control": "private, no-cache"}
    candidates = {t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")}
    if page["etag"] in candidates:
        return Response(status_code=304, headers=headers)
    return JSONResponse(jsonable_encoder(SyncSnapshotPage(**page)), headers=headers)


@router.get("/status", response_model=SyncStatusResponse)
async def get_status(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    return await sync_verify_service.status(db)


@router.get("/stats", response_model=SyncStatsResponse)
async def get_stats(
    range_from: datetime | None = Query(default=None, alias="from"),
    range_to: datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    def _aware(v: datetime) -> datetime:
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v.astimezone(timezone.utc)

    end = _aware(range_to) if range_to else datetime.now(timezone.utc)
    start = _aware(range_from) if range_from else end - timedelta(days=30)
    if start >= end:
        raise InvalidInputError("'from' must be earlier than 'to'.")
    if end - start > timedelta(days=sync_verify_service.MAX_STATS_RANGE_DAYS):
        raise InvalidInputError(f"Range may not exceed {sync_verify_service.MAX_STATS_RANGE_DAYS} days.")
    body = await sync_verify_service.stats(db, start, end)
    return SyncStatsResponse(range_from=start, range_to=end, **body)
