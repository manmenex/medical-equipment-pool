import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.crud import transaction as transaction_crud
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.transaction import TransactionOut

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=Page[TransactionOut])
async def list_transactions(
    ward_id: str | None = None,
    equipment_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=25, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    rows, next_cursor, total = await transaction_crud.search(
        db,
        ward_id=uuid.UUID(ward_id) if ward_id else None,
        equipment_id=uuid.UUID(equipment_id) if equipment_id else None,
        status=status,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=rows, next_cursor=next_cursor, total=total)


@router.get("/{transaction_id}", response_model=TransactionOut)
async def get_transaction(
    transaction_id: uuid.UUID, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)
):
    from app.core.exceptions import TransactionNotFoundError

    tx = await transaction_crud.get_by_id(db, transaction_id)
    if tx is None:
        raise TransactionNotFoundError("Transaction not found")
    return tx
