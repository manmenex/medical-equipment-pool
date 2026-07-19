from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import cache_get, cache_set
from app.models.equipment import Equipment, EquipmentStatus
from app.models.transaction import BorrowTransaction


async def get_summary(db: AsyncSession) -> dict:
    cached = await cache_get("dashboard:summary")
    if cached:
        return cached

    stmt = (
        select(Equipment.status, func.count())
        .where(Equipment.deleted_at.is_(None))
        .group_by(Equipment.status)
    )
    rows = (await db.execute(stmt)).all()
    counts = {status.value: 0 for status in EquipmentStatus}
    total = 0
    for status_value, count in rows:
        key = status_value.value if hasattr(status_value, "value") else status_value
        counts[key] = count
        total += count

    today = date.today()
    pm_due_soon = (
        await db.execute(
            select(func.count()).select_from(Equipment).where(
                Equipment.deleted_at.is_(None),
                Equipment.pm_due_date.is_not(None),
                Equipment.pm_due_date <= today + timedelta(days=settings.PM_DUE_SOON_DAYS),
                Equipment.pm_due_date >= today,
            )
        )
    ).scalar_one()
    cal_due_soon = (
        await db.execute(
            select(func.count()).select_from(Equipment).where(
                Equipment.deleted_at.is_(None),
                Equipment.cal_due_date.is_not(None),
                Equipment.cal_due_date <= today + timedelta(days=settings.CAL_DUE_SOON_DAYS),
                Equipment.cal_due_date >= today,
            )
        )
    ).scalar_one()

    result = {
        "total": total,
        "available_at_pool": counts.get("available_at_pool", 0),
        "issued_to_ward": counts.get("issued_to_ward", 0),
        "unavailable_defective": counts.get("unavailable_defective", 0),
        "decommissioned": counts.get("decommissioned", 0),
        "pm_due_soon": pm_due_soon,
        "cal_due_soon": cal_due_soon,
    }
    await cache_set("dashboard:summary", result, ttl_seconds=15)
    return result


async def get_borrow_trend(db: AsyncSession, days: int = 30) -> list[dict]:
    cache_key = f"dashboard:trend:{days}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    since = date.today() - timedelta(days=days)
    stmt = (
        select(func.date(BorrowTransaction.borrowed_at), func.count())
        .where(func.date(BorrowTransaction.borrowed_at) >= since)
        .group_by(func.date(BorrowTransaction.borrowed_at))
        .order_by(func.date(BorrowTransaction.borrowed_at))
    )
    rows = (await db.execute(stmt)).all()
    result = [{"date": str(d), "count": c} for d, c in rows]
    await cache_set(cache_key, result, ttl_seconds=60)
    return result


async def get_top_borrowed(db: AsyncSession, limit: int = 10) -> list[dict]:
    cache_key = f"dashboard:top:{limit}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    stmt = (
        select(
            Equipment.id,
            Equipment.asset_number,
            Equipment.equipment_name,
            func.count(BorrowTransaction.id).label("borrow_count"),
        )
        .join(BorrowTransaction, BorrowTransaction.equipment_id == Equipment.id)
        .group_by(Equipment.id, Equipment.asset_number, Equipment.equipment_name)
        .order_by(func.count(BorrowTransaction.id).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    result = [
        {
            "equipment_id": str(eid),
            "asset_number": asset_number,
            "equipment_name": name,
            "borrow_count": count,
        }
        for eid, asset_number, name, count in rows
    ]
    await cache_set(cache_key, result, ttl_seconds=60)
    return result
