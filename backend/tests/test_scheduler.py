from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.equipment import Equipment
from app.models.notification import Notification
from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, Role, User
from app.worker import scheduler as scheduler_module

pytestmark = pytest.mark.asyncio


async def _make_equipment(db_session, *, asset_number: str, pm_due_date=None, cal_due_date=None) -> Equipment:
    equipment = Equipment(
        asset_number=asset_number,
        equipment_name=f"Equipment {asset_number}",
        pm_due_date=pm_due_date,
        cal_due_date=cal_due_date,
    )
    db_session.add(equipment)
    await db_session.flush()
    return equipment


async def _make_user(db_session, roles: dict, *, role_name: str, code: str, is_active: bool = True) -> User:
    user = User(
        employee_code=code,
        full_name=f"User {code}",
        email=f"{code.lower()}@mep-hospital-test.dev",
        password_hash="x",
        role_id=roles[role_name].id,
        is_active=is_active,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def session_maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
def _patch_scheduler_session(monkeypatch, session_maker):
    monkeypatch.setattr(scheduler_module, "AsyncSessionLocal", session_maker)


@pytest.fixture
async def roles(db_session):
    roles = {}
    for name in ALL_ROLES:
        role = Role(name=name, permissions={})
        db_session.add(role)
        roles[name] = role
    await db_session.flush()
    await db_session.commit()
    return roles


async def test_zero_due_rows_performs_zero_recipient_queries(monkeypatch, db_session, roles):
    await _make_user(db_session, roles, role_name=ROLE_ADMINISTRATOR, code="ADMIN001")
    await db_session.commit()

    calls = []
    original = scheduler_module._get_recipient_ids

    async def _tracking(db):
        calls.append(1)
        return await original(db)

    monkeypatch.setattr(scheduler_module, "_get_recipient_ids", _tracking)

    await scheduler_module.check_pm_cal_due()

    assert calls == [], "no PM/CAL due rows must mean zero recipient queries"


async def test_any_due_rows_performs_exactly_one_recipient_query(monkeypatch, db_session, roles):
    await _make_user(db_session, roles, role_name=ROLE_ADMINISTRATOR, code="ADMIN001")
    await _make_equipment(
        db_session,
        asset_number="SCHED-0001",
        pm_due_date=date.today() + timedelta(days=1),
    )
    await db_session.commit()

    calls = []
    original = scheduler_module._get_recipient_ids

    async def _tracking(db):
        calls.append(1)
        return await original(db)

    monkeypatch.setattr(scheduler_module, "_get_recipient_ids", _tracking)

    await scheduler_module.check_pm_cal_due()

    assert len(calls) == 1, "any due rows must trigger exactly one recipient query, reused for every notification"


async def test_notification_count_equals_due_rows_times_active_recipients(db_session, roles):
    await _make_user(db_session, roles, role_name=ROLE_ADMINISTRATOR, code="ADMIN001")
    await _make_user(db_session, roles, role_name=ROLE_EQUIPMENT_POOL_STAFF, code="STAFF001")
    await _make_equipment(db_session, asset_number="SCHED-0002", pm_due_date=date.today())
    await _make_equipment(db_session, asset_number="SCHED-0003", cal_due_date=date.today())
    await db_session.commit()

    await scheduler_module.check_pm_cal_due()

    count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar_one()
    # 2 due rows (1 PM + 1 CAL) x 2 active recipients (admin + equipment_pool_staff)
    assert count == 4


async def test_inactive_users_receive_no_notifications(db_session, roles):
    await _make_user(db_session, roles, role_name=ROLE_ADMINISTRATOR, code="ADMIN001", is_active=False)
    await _make_equipment(db_session, asset_number="SCHED-0004", pm_due_date=date.today())
    await db_session.commit()

    await scheduler_module.check_pm_cal_due()

    count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count == 0


async def test_unrelated_roles_receive_no_notifications(db_session, roles):
    await _make_user(db_session, roles, role_name=ROLE_READ_ONLY, code="VIEWER001")
    await _make_equipment(db_session, asset_number="SCHED-0005", pm_due_date=date.today())
    await db_session.commit()

    await scheduler_module.check_pm_cal_due()

    count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count == 0


async def test_pm_and_cal_notification_content_unchanged(db_session, roles):
    admin = await _make_user(db_session, roles, role_name=ROLE_ADMINISTRATOR, code="ADMIN001")
    pm_equipment = await _make_equipment(db_session, asset_number="SCHED-0006", pm_due_date=date.today())
    cal_equipment = await _make_equipment(db_session, asset_number="SCHED-0007", cal_due_date=date.today())
    await db_session.commit()

    await scheduler_module.check_pm_cal_due()

    notifications = (
        await db_session.execute(select(Notification).where(Notification.user_id == admin.id))
    ).scalars().all()
    by_type = {n.type: n for n in notifications}

    assert by_type["pm"].title == f"PM ใกล้ครบกำหนด: {pm_equipment.equipment_name}"
    assert by_type["pm"].body == f"เครื่อง {pm_equipment.asset_number} มีกำหนด PM วันที่ {pm_equipment.pm_due_date}"
    assert by_type["calibration"].title == f"Calibration ใกล้ครบกำหนด: {cal_equipment.equipment_name}"
    assert (
        by_type["calibration"].body
        == f"เครื่อง {cal_equipment.asset_number} มีกำหนด Calibration วันที่ {cal_equipment.cal_due_date}"
    )


async def test_equipment_outside_due_horizon_produces_no_notification(db_session, roles):
    await _make_user(db_session, roles, role_name=ROLE_ADMINISTRATOR, code="ADMIN001")
    far_future = date.today() + timedelta(days=settings.PM_DUE_SOON_DAYS + 30)
    await _make_equipment(db_session, asset_number="SCHED-0008", pm_due_date=far_future)
    await db_session.commit()

    await scheduler_module.check_pm_cal_due()

    count = (await db_session.execute(select(func.count()).select_from(Notification))).scalar_one()
    assert count == 0
