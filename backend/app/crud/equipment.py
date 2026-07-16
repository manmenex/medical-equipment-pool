import uuid
from datetime import datetime

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment, EquipmentStatus, EquipmentStatusHistory
from app.utils.pagination import decode_cursor, encode_cursor


async def get_by_id(db: AsyncSession, equipment_id: uuid.UUID) -> Equipment | None:
    result = await db.execute(
        select(Equipment).where(Equipment.id == equipment_id, Equipment.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_by_qr(db: AsyncSession, qr_value: str) -> Equipment | None:
    result = await db.execute(
        select(Equipment).where(Equipment.qr_code_value == qr_value, Equipment.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_by_asset_number(db: AsyncSession, asset_number: str) -> Equipment | None:
    result = await db.execute(
        select(Equipment).where(Equipment.asset_number == asset_number, Equipment.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def search(
    db: AsyncSession,
    *,
    q: str | None = None,
    status: EquipmentStatus | None = None,
    department_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[Equipment], str | None, int]:
    base_filters = [Equipment.deleted_at.is_(None)]
    if status is not None:
        base_filters.append(Equipment.status == status)
    if department_id is not None:
        base_filters.append(Equipment.department_owner_id == department_id)
    if category_id is not None:
        base_filters.append(Equipment.category_id == category_id)
    if q:
        like = f"%{q}%"
        base_filters.append(
            or_(
                Equipment.equipment_name.ilike(like),
                Equipment.asset_number.ilike(like),
                Equipment.serial_number.ilike(like),
                Equipment.qr_code_value.ilike(like),
            )
        )

    count_stmt = select(func.count()).select_from(Equipment).where(and_(*base_filters))
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(Equipment).where(and_(*base_filters))
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Equipment.created_at < cursor_dt,
                and_(Equipment.created_at == cursor_dt, cast(Equipment.id, String) < cursor_id),
            )
        )
    stmt = stmt.order_by(Equipment.created_at.desc(), Equipment.id.desc()).limit(limit + 1)

    rows = list((await db.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
        rows = rows[:limit]

    return rows, next_cursor, total


async def create(db: AsyncSession, *, data: dict) -> Equipment:
    equipment = Equipment(**data)
    db.add(equipment)
    await db.flush()
    return equipment


async def update(db: AsyncSession, equipment: Equipment, *, data: dict) -> Equipment:
    for key, value in data.items():
        if value is not None:
            setattr(equipment, key, value)
    await db.flush()
    return equipment


async def soft_delete(db: AsyncSession, equipment: Equipment) -> None:
    equipment.deleted_at = datetime.utcnow()
    await db.flush()


async def change_status(
    db: AsyncSession,
    equipment: Equipment,
    *,
    new_status: EquipmentStatus,
    changed_by_user_id: uuid.UUID | None,
    reason: str | None = None,
) -> EquipmentStatusHistory:
    history = EquipmentStatusHistory(
        equipment_id=equipment.id,
        from_status=equipment.status.value if equipment.status else None,
        to_status=new_status.value,
        changed_by_user_id=changed_by_user_id,
        reason=reason,
    )
    equipment.status = new_status
    db.add(history)
    await db.flush()
    return history


async def get_history(db: AsyncSession, equipment_id: uuid.UUID) -> list[EquipmentStatusHistory]:
    result = await db.execute(
        select(EquipmentStatusHistory)
        .where(EquipmentStatusHistory.equipment_id == equipment_id)
        .order_by(EquipmentStatusHistory.changed_at.desc())
    )
    return list(result.scalars().all())
