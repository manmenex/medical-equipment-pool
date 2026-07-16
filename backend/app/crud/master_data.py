from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.master_data import Department, EquipmentCategory, Location, Ward


async def list_departments(db: AsyncSession) -> list[Department]:
    return list((await db.execute(select(Department).order_by(Department.name))).scalars().all())


async def create_department(db: AsyncSession, *, code: str, name: str) -> Department:
    obj = Department(code=code, name=name)
    db.add(obj)
    await db.flush()
    return obj


async def list_wards(db: AsyncSession) -> list[Ward]:
    return list((await db.execute(select(Ward).order_by(Ward.name))).scalars().all())


async def create_ward(db: AsyncSession, *, code: str, name: str, department_id: str | None) -> Ward:
    obj = Ward(code=code, name=name, department_id=department_id)
    db.add(obj)
    await db.flush()
    return obj


async def list_locations(db: AsyncSession) -> list[Location]:
    return list((await db.execute(select(Location).order_by(Location.name))).scalars().all())


async def create_location(db: AsyncSession, *, name: str, type_: str | None) -> Location:
    obj = Location(name=name, type=type_)
    db.add(obj)
    await db.flush()
    return obj


async def list_categories(db: AsyncSession) -> list[EquipmentCategory]:
    return list((await db.execute(select(EquipmentCategory).order_by(EquipmentCategory.name))).scalars().all())


async def create_category(
    db: AsyncSession, *, name: str, default_pm_interval_days: int | None, default_cal_interval_days: int | None
) -> EquipmentCategory:
    obj = EquipmentCategory(
        name=name,
        default_pm_interval_days=default_pm_interval_days,
        default_cal_interval_days=default_cal_interval_days,
    )
    db.add(obj)
    await db.flush()
    return obj
