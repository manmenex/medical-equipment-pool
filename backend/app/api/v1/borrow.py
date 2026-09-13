import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import EQUIPMENT_POOL_OPERATION_ROLES, get_current_user, require_roles
from app.db.session import get_db
from app.schemas.transaction import BorrowRequest, ReturnRequest, TransactionOut
from app.services import borrow_service

router = APIRouter(tags=["borrow"])

# Roadmap PR10: dispatch and receipt are Equipment Pool operations --
# Administrator and Equipment Pool Staff, never Read Only. Replaces the
# pre-PR10 admin/ward_nurse/transport_staff gate (plus the inline
# biomedical_engineer/viewer literals list_active_borrows and create_return
# used to carry) -- none of those three legacy roles has a confirmed
# equivalent in the new model, so this is a deliberate narrowing to the
# confirmed matrix, not an oversight.
BORROW_ROLES = EQUIPMENT_POOL_OPERATION_ROLES


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua


@router.post("/borrow", response_model=TransactionOut, status_code=201)
async def create_borrow(
    payload: BorrowRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*BORROW_ROLES)),
):
    ip, ua = _client_meta(request)
    tx = await borrow_service.borrow(
        db,
        equipment_id=payload.equipment_id,
        borrower_user_id=user.id,
        ward_id=payload.ward_id,
        dispatch_type=payload.dispatch_type,
        routine_round=payload.routine_round,
        department_id=payload.department_id,
        phone_number=payload.phone_number,
        pickup_location_id=payload.pickup_location_id,
        dropoff_location_id=payload.dropoff_location_id,
        notes=payload.notes,
        ip_address=ip,
        user_agent=ua,
    )
    return tx


@router.get("/borrow/active", response_model=list[TransactionOut])
async def list_active_borrows(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    # Roadmap PR10: a view/list surface -- every authenticated role
    # (including Read Only) may view active transactions, mirroring
    # GET /transactions's own no-role-restriction gate.
    from app.crud import transaction as transaction_crud

    return await transaction_crud.list_active(db)


@router.post("/return/{transaction_id}", response_model=TransactionOut)
async def create_return(
    transaction_id: uuid.UUID,
    payload: ReturnRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*BORROW_ROLES)),
):
    ip, ua = _client_meta(request)
    tx = await borrow_service.return_equipment(
        db,
        transaction_id=transaction_id,
        receipt_outcome=payload.receipt_outcome,
        notes=payload.notes,
        received_by_user_id=user.id,
        ip_address=ip,
        user_agent=ua,
    )
    return tx
