import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import (
    EQUIPMENT_POOL_OPERATION_ROLES,
    WARD_CORRECTION_ROLES,
    get_current_user,
    require_roles,
)
from app.core.exceptions import InvalidInputError, TransactionNotFoundError
from app.core.reporting_time import Shift
from app.crud import transaction as transaction_crud
from app.db.session import get_db
from app.models.transaction import DispatchType, RoutineRound
from app.schemas.batch import BatchResponse, DispatchBatchRequest, ReceiptBatchRequest
from app.schemas.checklist import ContactName, CuffCounts
from app.schemas.common import Page
from app.schemas.hn import HnInput
from app.schemas.transaction import TransactionOut, WardCorrectionRequest
from app.services import batch_service, borrow_service, cuff_service, hn_service
from app.utils.parsing import parse_uuid

router = APIRouter(prefix="/transactions", tags=["transactions"])


class CuffReceiveRequest(BaseModel):
    """Roadmap PR28 (D11): cuffs handed back after the device was received."""

    cuffs: CuffCounts
    ward_contact_name: ContactName = None

    model_config = {"extra": "forbid"}


class CuffReceiveOut(BaseModel):
    transaction_id: str
    transaction_no: str
    cuffs_issued: CuffCounts
    cuffs_returned: CuffCounts
    cuffs_outstanding: CuffCounts


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    return (request.client.host if request.client else None), request.headers.get("user-agent")


@router.get("", response_model=Page[TransactionOut])
async def list_transactions(
    ward_id: str | None = None,
    equipment_id: str | None = None,
    status: str | None = None,
    dispatch_type: DispatchType | None = None,
    routine_round: RoutineRound | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    shift: Shift | None = None,
    event: Literal["dispatch", "receipt"] = "dispatch",
    limit: int = Query(default=25, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    # Review fix: a reversed date range (from_date after to_date) can never
    # match anything and is almost always a client mistake -- reject it
    # explicitly with a 400 here, at the API boundary, before it reaches
    # transaction_crud.search()'s business logic, rather than silently
    # returning an empty page that looks identical to "no matches."
    if from_date is not None and to_date is not None and from_date > to_date:
        raise InvalidInputError("'from_date' must not be after 'to_date'")

    # Roadmap PR16 Slice 3 (docs/archive/design/PR16_REPORTING_FOUNDATION_PLAN.md
    # §8): a separate, new check -- business_date_from/_to are compared
    # against the derived business_date value, not the raw
    # borrowed_at/returned_at timestamp from_date/to_date already validate
    # above, so this is not a duplicate of that check.
    if business_date_from is not None and business_date_to is not None and business_date_from > business_date_to:
        raise InvalidInputError("'business_date_from' must not be after 'business_date_to'")

    rows, next_cursor, total = await transaction_crud.search(
        db,
        ward_id=parse_uuid(ward_id, "ward_id"),
        equipment_id=parse_uuid(equipment_id, "equipment_id"),
        status=status,
        dispatch_type=dispatch_type,
        routine_round=routine_round,
        from_date=from_date,
        to_date=to_date,
        business_date_from=business_date_from,
        business_date_to=business_date_to,
        shift=shift,
        event=event,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=rows, next_cursor=next_cursor, total=total)


@router.post("/dispatch-batch", response_model=BatchResponse)
async def dispatch_batch(
    payload: DispatchBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    """Roadmap PR27 (D3): ward-first multi-equipment dispatch. Always 200 with a
    per-item result; each item is its own transaction (see batch_service)."""
    ip, ua = _client_meta(request)
    return await batch_service.dispatch_batch(db, payload, user_id=user.id, ip_address=ip, user_agent=ua)


@router.post("/receipt-batch", response_model=BatchResponse)
async def receipt_batch(
    payload: ReceiptBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    """Roadmap PR27 (D3): ward-first multi-equipment receipt (usable/defective
    per item). Always 200 with a per-item result."""
    ip, ua = _client_meta(request)
    return await batch_service.receipt_batch(db, payload, user_id=user.id, ip_address=ip, user_agent=ua)


@router.get("/{transaction_id}", response_model=TransactionOut)
async def get_transaction(
    transaction_id: uuid.UUID, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)
):
    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")
    return tx


class HnRevealOut(BaseModel):
    hn: str


@router.post("/{transaction_id}/reveal-hn", response_model=HnRevealOut)
async def reveal_hn(
    transaction_id: uuid.UUID,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    """Roadmap PR29 (D1/D13): the ONLY place an HN leaves the server. Equipment
    Pool staff and administrators; every successful reveal writes an audit row
    (actor, transaction id, time -- never the value) in the same commit."""
    hn = await hn_service.reveal_hn(db, transaction_id=transaction_id, actor_user_id=user.id, request=request)
    response.headers["Cache-Control"] = "no-store"
    return HnRevealOut(hn=hn)


class HnAddRequest(BaseModel):
    """Roadmap PR34 (D15). The value is never echoed in a validation error
    (the app's 422 handler drops ``input``) and is excluded from repr."""

    hn: HnInput = Field(repr=False)

    model_config = {"extra": "forbid"}

    @field_validator("hn")
    @classmethod
    def _required(cls, v):
        if v is None:
            raise ValueError("HN is required")
        return v


@router.post("/{transaction_id}/hn", response_model=TransactionOut)
async def add_hn(
    transaction_id: uuid.UUID,
    payload: HnAddRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    """Roadmap PR34 (D15): add an HN to an OPEN dispatch that has none
    (Standby becomes in use). 409 when the dispatch is not open or already has
    an HN. Online only. Audited without the value; response carries has_hn only."""
    response.headers["Cache-Control"] = "no-store"
    return await hn_service.add_hn(
        db, transaction_id=transaction_id, hn=payload.hn, actor_user_id=user.id, request=request
    )


@router.post("/{transaction_id}/receive-cuffs", response_model=CuffReceiveOut)
async def receive_cuffs(
    transaction_id: uuid.UUID,
    payload: CuffReceiveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    """Roadmap PR28 (D11): receive outstanding cuffs of an already-received (or
    re-dispatch-closed) transaction. Never exceeds outstanding; audited."""
    ip, ua = _client_meta(request)
    return await cuff_service.receive_cuffs(
        db,
        transaction_id=transaction_id,
        counts=payload.cuffs,
        ward_contact_name=payload.ward_contact_name,
        actor_user_id=user.id,
        ip_address=ip,
        user_agent=ua,
    )


@router.post("/{transaction_id}/correct-ward", response_model=TransactionOut)
async def correct_transaction_ward(
    transaction_id: uuid.UUID,
    payload: WardCorrectionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*WARD_CORRECTION_ROLES)),
):
    """Roadmap PR9A: audited correction of a transaction's recorded
    destination ward -- a narrow, purpose-built action (see
    app.services.borrow_service.correct_ward's docstring), never a generic
    transaction PATCH. Thin by design: all business orchestration (ward
    validation, same-ward rejection, the conditional-update concurrency
    guard, and the atomic audit write) lives in the service layer.
    """
    return await borrow_service.correct_ward(
        db,
        transaction_id=transaction_id,
        new_ward_id=payload.ward_id,
        reason=payload.reason,
        actor_user_id=user.id,
        request=request,
    )
