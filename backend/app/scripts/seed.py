"""Seed demo/reference data, and optionally bulk synthetic volume for load testing.

Usage:
    python -m app.scripts.seed
    python -m app.scripts.seed --equipment 500000 --transactions 2000000
"""
import argparse
import asyncio
import random
import uuid

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.equipment import Equipment, EquipmentStatus
from app.models.master_data import Department, EquipmentCategory, Location, Ward
from app.models.transaction import BorrowTransaction
from app.models.user import ALL_ROLES, Role, User
from app.services.qr_service import build_qr_value

DEPARTMENTS = [("MED", "อายุรกรรม"), ("SURG", "ศัลยกรรม"), ("ICU", "ผู้ป่วยวิกฤต"), ("ER", "อุบัติเหตุฉุกเฉิน")]
CATEGORIES = [
    ("Infusion Pump", 90, 365),
    ("ECG Monitor", 90, 365),
    ("Ventilator", 30, 180),
    ("Defibrillator", 30, 180),
    ("Patient Monitor", 90, 365),
]
LOCATIONS = [("Ward 5A", "ward"), ("Ward 5B", "ward"), ("ICU-1", "icu"), ("Central Store", "store")]


async def seed_reference_data(db) -> dict:
    roles = {}
    for role_name in ALL_ROLES:
        role = Role(name=role_name, permissions={})
        db.add(role)
        roles[role_name] = role
    await db.flush()

    admin = User(
        employee_code="ADMIN001",
        full_name="System Administrator",
        email="admin@hospital.local",
        password_hash=hash_password("Admin@12345"),
        role_id=roles["admin"].id,
    )
    db.add(admin)

    departments = []
    for code, name in DEPARTMENTS:
        dep = Department(code=code, name=name)
        db.add(dep)
        departments.append(dep)
    await db.flush()

    wards = []
    for i, (loc_name, loc_type) in enumerate(LOCATIONS):
        if loc_type == "ward":
            ward = Ward(code=f"W{i}", name=loc_name, department_id=departments[0].id)
            db.add(ward)
            wards.append(ward)

    categories = []
    for name, pm_days, cal_days in CATEGORIES:
        cat = EquipmentCategory(name=name, default_pm_interval_days=pm_days, default_cal_interval_days=cal_days)
        db.add(cat)
        categories.append(cat)

    locations = []
    for name, type_ in LOCATIONS:
        loc = Location(name=name, type=type_)
        db.add(loc)
        locations.append(loc)

    await db.flush()
    return {"departments": departments, "categories": categories, "locations": locations, "wards": wards}


async def seed_sample_equipment(db, refs: dict, count: int = 50) -> None:
    for i in range(count):
        category = random.choice(refs["categories"])
        asset_number = f"AST-{i + 1:05d}"
        eq = Equipment(
            asset_number=asset_number,
            serial_number=f"SN-{uuid.uuid4().hex[:10]}",
            equipment_name=category.name,
            category_id=category.id,
            brand=random.choice(["GE", "Philips", "Mindray", "Drager"]),
            model=f"Model-{random.randint(100, 999)}",
            department_owner_id=random.choice(refs["departments"]).id,
            current_location_id=random.choice(refs["locations"]).id,
            status=EquipmentStatus.AVAILABLE,
            qr_code_value=build_qr_value(asset_number),
        )
        db.add(eq)
    await db.flush()


async def seed_bulk(db, refs: dict, equipment_count: int, transaction_count: int) -> None:
    print(f"Bulk seeding {equipment_count} equipment rows...")
    batch = []
    equipment_ids = []
    for i in range(equipment_count):
        category = random.choice(refs["categories"])
        asset_number = f"BULK-{i + 1:07d}"
        eq_id = uuid.uuid4()
        equipment_ids.append(eq_id)
        batch.append(
            Equipment(
                id=eq_id,
                asset_number=asset_number,
                serial_number=f"SN-{uuid.uuid4().hex[:12]}",
                equipment_name=f"{category.name} #{i}",
                category_id=category.id,
                department_owner_id=random.choice(refs["departments"]).id,
                current_location_id=random.choice(refs["locations"]).id,
                status=EquipmentStatus.AVAILABLE,
                qr_code_value=build_qr_value(asset_number),
            )
        )
        if len(batch) >= 5000:
            db.add_all(batch)
            await db.flush()
            db.expunge_all()
            batch = []
            print(f"  {i + 1}/{equipment_count}")
    if batch:
        db.add_all(batch)
        await db.flush()

    print(f"Bulk seeding {transaction_count} historical (returned) transactions...")
    batch_tx = []
    for i in range(transaction_count):
        eq_id = random.choice(equipment_ids)
        batch_tx.append(
            BorrowTransaction(
                transaction_no=f"TXBULK-{i + 1:08d}",
                equipment_id=eq_id,
                borrower_name=f"Borrower {i % 500}",
                status="returned",
                condition_on_return="available",
            )
        )
        if len(batch_tx) >= 5000:
            db.add_all(batch_tx)
            await db.flush()
            db.expunge_all()
            batch_tx = []
            print(f"  {i + 1}/{transaction_count}")
    if batch_tx:
        db.add_all(batch_tx)
        await db.flush()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--equipment", type=int, default=0, help="extra bulk equipment rows for load testing")
    parser.add_argument("--transactions", type=int, default=0, help="extra bulk transaction rows for load testing")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        refs = await seed_reference_data(db)
        await seed_sample_equipment(db, refs, count=50)
        if args.equipment:
            await seed_bulk(db, refs, args.equipment, args.transactions)
        await db.commit()
    print("Seed complete. Admin login: ADMIN001 / Admin@12345")


if __name__ == "__main__":
    asyncio.run(main())
