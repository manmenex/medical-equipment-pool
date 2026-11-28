"""Host-only password reset CLI (app.scripts.reset_password)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import verify_password
from app.models.audit import AuditLog
from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, Role, User
from app.scripts import bootstrap_admin, reset_password


@pytest.fixture
def session_maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(autouse=True)
def patched_session_local(monkeypatch, session_maker):
    monkeypatch.setattr(bootstrap_admin, "AsyncSessionLocal", session_maker)
    monkeypatch.setattr(reset_password, "AsyncSessionLocal", session_maker)


@pytest.fixture
async def locked_admin(db_session, session_maker):
    for name in ALL_ROLES:
        db_session.add(Role(name=name, permissions={}))
    await db_session.commit()
    user, old_password = await bootstrap_admin.bootstrap_admin(
        employee_code="ADMIN001", email="admin@hospital.local", full_name="System Administrator"
    )
    async with session_maker() as db:
        u = await db.get(User, user.id)
        u.must_change_password = False
        u.failed_login_attempts = 5
        u.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
        await db.commit()
    return user, old_password


async def test_reset_sets_new_password_requires_change_and_unlocks(locked_admin, session_maker):
    user, old_password = locked_admin
    _, new_password = await reset_password.reset_password(employee_code="ADMIN001")

    assert new_password and new_password != old_password
    async with session_maker() as db:
        u = await db.get(User, user.id)
        assert verify_password(new_password, u.password_hash)
        assert not verify_password(old_password, u.password_hash)
        assert u.password_hash != new_password
        assert u.must_change_password is True
        assert u.failed_login_attempts == 0
        assert u.locked_until is None
        role = await db.get(Role, u.role_id)
        assert role.name == ROLE_ADMINISTRATOR


async def test_reset_is_audited_without_actor_or_secret(locked_admin, session_maker):
    user, _ = locked_admin
    _, new_password = await reset_password.reset_password(employee_code="ADMIN001")
    async with session_maker() as db:
        rows = (
            await db.execute(select(AuditLog).where(AuditLog.action == "PASSWORD_RESET_HOST"))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].entity_id == user.id
    assert new_password not in str(rows[0].after_data)


async def test_reset_unknown_user_changes_nothing(locked_admin, session_maker):
    with pytest.raises(reset_password.ResetRefused):
        await reset_password.reset_password(employee_code="NOPE999")
    async with session_maker() as db:
        rows = (
            await db.execute(select(AuditLog).where(AuditLog.action == "PASSWORD_RESET_HOST"))
        ).scalars().all()
    assert rows == []
