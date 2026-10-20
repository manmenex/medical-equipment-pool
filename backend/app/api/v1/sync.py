"""Roadmap PR25E slice B2 -- ``POST /api/v1/sync/operations``
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 6.1; docs/api/sync.md)."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
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
from app.core.security import decode_token
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
from app.schemas.sync_review import (
    ApplyNowRequest,
    DismissRequest,
    ReviewDetail,
    ReviewList,
    ResolveResponse,
)
from app.services import sync_review_service, sync_service, sync_snapshot_service, sync_verify_service

router = APIRouter(prefix="/sync", tags=["sync"])


def _token_auth_time(request: Request) -> datetime | None:
    """``auth_time`` (password-login time) of the bearer token. The auth dependency has already verified
    it; a missing/invalid claim yields None (adoption then fails closed)."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        at = decode_token(token.strip()).get("auth_time")
        return datetime.fromtimestamp(float(at), tz=timezone.utc)
    except (jwt.PyJWTError, TypeError, ValueError):
        return None


@router.post("/operations", response_model=SyncBatchResponse)
async def submit_operations(
    payload: SyncBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    results = await sync_service.process_batch(
        db, payload.operations, user, ip_address=ip, user_agent=ua, auth_time=_token_auth_time(request)
    )
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


# ---- Slice B4: conflict review (roles: staff + administrator; the FORBIDDEN
# class is administrator-only, enforced in the service) ----

def _client(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None), request.headers.get("user-agent")


@router.get("/conflicts", response_model=ReviewList)
async def list_conflicts(
    status: str = Query(default="unresolved", description="unresolved | conflict | pending | resolved"),
    result_code: str | None = Query(default=None, max_length=64),
    op_type: str | None = Query(default=None),
    operator_id: uuid.UUID | None = None,
    stale_context: bool | None = None,
    device_id: uuid.UUID | None = None,
    received_from: datetime | None = None,
    received_to: datetime | None = None,
    limit: int = Query(default=sync_review_service.DEFAULT_LIMIT, ge=1, le=sync_review_service.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    is_admin = await sync_review_service.is_administrator(db, user.id)
    return await sync_review_service.list_items(
        db, is_admin=is_admin, status=status, result_code=result_code, op_type=op_type,
        operator_id=operator_id, stale_context=stale_context, device_id=device_id,
        received_from=received_from, received_to=received_to, limit=limit, offset=offset,
    )


@router.get("/conflicts/{op_id}", response_model=ReviewDetail)
async def get_conflict(
    op_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    is_admin = await sync_review_service.is_administrator(db, user.id)
    return await sync_review_service.get_detail(db, op_id, is_admin=is_admin)


@router.post("/conflicts/{op_id}/dismiss", response_model=ResolveResponse)
async def dismiss_conflict(
    op_id: uuid.UUID,
    payload: DismissRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    ip, ua = _client(request)
    uid = user.id
    is_admin = await sync_review_service.is_administrator(db, uid)
    return await sync_review_service.dismiss(
        db, op_id, uid, is_admin=is_admin, reason=payload.reason, note=payload.note, ip_address=ip, user_agent=ua
    )


@router.post("/conflicts/{op_id}/apply-now", response_model=ResolveResponse)
async def apply_conflict_now(
    op_id: uuid.UUID,
    request: Request,
    payload: ApplyNowRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    ip, ua = _client(request)
    uid = user.id
    is_admin = await sync_review_service.is_administrator(db, uid)
    return await sync_review_service.apply_now(db, op_id, uid, is_admin=is_admin, ip_address=ip, user_agent=ua)
