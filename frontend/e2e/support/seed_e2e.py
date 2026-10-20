"""Synthetic fixtures for the PR25E E1 browser drills. No hospital data.

Run with the backend directory as cwd and DATABASE_URL pointing at a
throwaway SQLite file:

    DATABASE_URL=sqlite+aiosqlite:///./e2e.db python ../frontend/e2e/support/seed_e2e.py

Creates the schema (Base.metadata.create_all: the Alembic chain targets
PostgreSQL and does not apply to SQLite, so it is covered by the backend CI
`alembic upgrade head` step instead), the three roles, four users (one per drill persona),
two wards, one department with a fallback phone and 40 equipment rows
(BCM9001 .. BCM9040) so every drill scenario uses equipment of its own.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.models.equipment import Equipment, EquipmentStatus  # noqa: E402
from app.models.master_data import Department, EquipmentCategory, Ward  # noqa: E402
from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, Role, User  # noqa: E402

PASSWORD = "Drill@12345"  # synthetic, local-only database
USERS = [
    ("E2EADMIN", "Drill Reviewer", "e2e-admin@example.test", ROLE_ADMINISTRATOR),
    ("E2EPOOLA", "Drill Pool A", "e2e-pool-a@example.test", ROLE_EQUIPMENT_POOL_STAFF),
    ("E2EPOOLB", "Drill Pool B", "e2e-pool-b@example.test", ROLE_EQUIPMENT_POOL_STAFF),
    ("E2EPOOLC", "Drill Pool C", "e2e-pool-c@example.test", ROLE_EQUIPMENT_POOL_STAFF),
]
EQUIPMENT_COUNT = 40


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        roles = {}
        for name in ALL_ROLES:
            role = Role(name=name, permissions={})
            db.add(role)
            roles[name] = role
        await db.flush()
        pw = hash_password(PASSWORD)
        for code, full_name, email, role_name in USERS:
            db.add(User(employee_code=code, full_name=full_name, email=email, password_hash=pw, role_id=roles[role_name].id))
        dept = Department(code="E2E", name="Drill Department", phone="0000")
        db.add(dept)
        await db.flush()
        db.add(Ward(code="DW1", name="Drill Ward 1", department_id=dept.id, phone="1111"))
        db.add(Ward(code="DW2", name="Drill Ward 2", department_id=dept.id))
        cat = EquipmentCategory(name="Drill Pump", default_pm_interval_days=90, default_cal_interval_days=365)
        db.add(cat)
        await db.flush()
        for i in range(1, EQUIPMENT_COUNT + 1):
            db.add(
                Equipment(
                    asset_number=f"E2E-AST-{i:03d}",
                    equipment_name=f"Drill Pump {i:03d}",
                    bcm_code=f"BCM9{i:03d}",
                    category_id=cat.id,
                    department_owner_id=dept.id,
                    status=EquipmentStatus.AVAILABLE_AT_POOL,
                )
            )
        await db.commit()
    await engine.dispose()
    print("seeded")


asyncio.run(main())
