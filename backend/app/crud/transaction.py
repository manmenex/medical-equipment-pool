import uuid
from datetime import datetime

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.transaction import TX_STATUS_BORROWED, BorrowTransaction
from app.utils.pagination import decode_cursor, encode_cursor


async def generate_transaction_no(db: AsyncSession) -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"TX-{today}-"
    count_stmt = select(func.count()).select_from(BorrowTransaction).where(
        BorrowTransaction.transaction_no.like(f"{prefix}%")
    )
    count = (await db.execute(count_stmt)).scalar_one()
    return f"{prefix}{count + 1:04d}"


async def get_active_borrow_for_equipment(db: AsyncSession, equipment_id: uuid.UUID) -> BorrowTransaction | None:
    result = await db.execute(
        select(BorrowTransaction).where(
            BorrowTransaction.equipment_id == equipment_id,
            BorrowTransaction.status == TX_STATUS_BORROWED,
        )
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, transaction_id: uuid.UUID) -> BorrowTransaction | None:
    result = await db.execute(
        select(BorrowTransaction)
        .options(selectinload(BorrowTransaction.equipment))
        .where(BorrowTransaction.id == transaction_id)
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, *, data: dict) -> BorrowTransaction:
    tx = BorrowTransaction(**data)
    db.add(tx)
    await db.flush()
    await db.refresh(tx, attribute_names=["equipment"])
    return tx


async def list_active(db: AsyncSession) -> list[BorrowTransaction]:
    result = await db.execute(
        select(BorrowTransaction)
        .options(selectinload(BorrowTransaction.equipment))
        .where(BorrowTransaction.status == TX_STATUS_BORROWED)
        .order_by(BorrowTransaction.borrowed_at.desc())
    )
    return list(result.scalars().all())


async def search(
    db: AsyncSession,
    *,
    ward_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[BorrowTransaction], str | None, int]:
    filters = []
    if ward_id is not None:
        filters.append(BorrowTransaction.ward_id == ward_id)
    if equipment_id is not None:
        filters.append(BorrowTransaction.equipment_id == equipment_id)
    if status is not None:
        filters.append(BorrowTransaction.status == status)

    count_stmt = select(func.count()).select_from(BorrowTransaction).where(and_(*filters)) if filters else select(
        func.count()
    ).select_from(BorrowTransaction)
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(BorrowTransaction).options(selectinload(BorrowTransaction.equipment))
    if filters:
        stmt = stmt.where(and_(*filters))
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                BorrowTransaction.created_at < cursor_dt,
                and_(BorrowTransaction.created_at == cursor_dt, cast(BorrowTransaction.id, String) < cursor_id),
            )
        )
    stmt = stmt.order_by(BorrowTransaction.created_at.desc(), BorrowTransaction.id.desc()).limit(limit + 1)

    rows = list((await db.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
        rows = rows[:limit]
    return rows, next_cursor, total
