import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import WARD_CORRECTION_ROLES, get_current_user, require_roles
from app.core.exceptions import InvalidInputError, TransactionNotFoundError
from app.core.reporting_time import Shift
from app.crud import transaction as transaction_crud
from app.db.session import get_db
from app.models.transaction import DispatchType, RoutineRound
from app.schemas.common import Page
from app.schemas.transaction import TransactionOut, WardCorrectionRequest
from app.services import borrow_service
from app.utils.parsing import parse_uuid

router = APIRouter(prefix="/transactions", tags=["transactions"])


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

    # Roadmap PR16 Slice 3 (docs/design/PR16_REPORTING_FOUNDATION_PLAN.md
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


@router.get("/{transaction_id}", response_model=TransactionOut)
async def get_transaction(
    transaction_id: uuid.UUID, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)
):
    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")
    return tx


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
