import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import require_roles
from app.db.session import get_db
from app.models.user import ROLE_ADMIN, ROLE_TRANSPORT_STAFF, ROLE_WARD_NURSE
from app.schemas.transaction import BorrowRequest, ReturnRequest, TransactionOut
from app.services import borrow_service

router = APIRouter(tags=["borrow"])

BORROW_ROLES = (ROLE_ADMIN, ROLE_WARD_NURSE, ROLE_TRANSPORT_STAFF)


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
        borrower_name=payload.borrower_name,
        ward_id=payload.ward_id,
        department_id=payload.department_id,
        phone_number=payload.phone_number,
        pickup_location_id=payload.pickup_location_id,
        dropoff_location_id=payload.dropoff_location_id,
        quantity=payload.quantity,
        due_at=payload.due_at,
        notes=payload.notes,
        ip_address=ip,
        user_agent=ua,
    )
    return tx


@router.get("/borrow/active", response_model=list[TransactionOut])
async def list_active_borrows(db: AsyncSession = Depends(get_db), _user=Depends(require_roles(*BORROW_ROLES, "biomedical_engineer", "viewer"))):
    from app.crud import transaction as transaction_crud

    return await transaction_crud.list_active(db)


@router.post("/return/{transaction_id}", response_model=TransactionOut)
async def create_return(
    transaction_id: uuid.UUID,
    payload: ReturnRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_roles(*BORROW_ROLES, "biomedical_engineer")),
):
    ip, ua = _client_meta(request)
    tx = await borrow_service.return_equipment(
        db,
        transaction_id=transaction_id,
        condition=payload.condition,
        notes=payload.notes,
        received_by_user_id=user.id,
        ip_address=ip,
        user_agent=ua,
    )
    return tx
