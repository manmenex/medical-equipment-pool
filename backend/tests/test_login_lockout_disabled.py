"""Login lockout switch (Owner decision 2026-11-01: OFF by default)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.audit import AUDIT_ACTION_ACCOUNT_LOCKED, AUDIT_ACTION_LOGIN_FAILURE
from app.core.config import Settings, settings
from app.models.audit import AuditLog
from app.models.user import ROLE_ADMINISTRATOR, User
from tests.conftest import login

pytestmark = pytest.mark.asyncio

CODE = f"{ROLE_ADMINISTRATOR.upper()}001"
CORRECT = "Password@123"
WRONG = "definitely-not-the-password"


async def _attempt(client, password):
    return await client.post(
        "/api/v1/auth/login", json={"identifier": CODE, "password": password}
    )


async def _user(db):
    db.expire_all()
    return (await db.execute(select(User).where(User.employee_code == CODE))).scalar_one()


async def test_defaults_are_off_5_10():
    s = Settings(_env_file=None)
    assert s.LOGIN_LOCKOUT_ENABLED is False
    assert s.LOGIN_LOCKOUT_MAX_ATTEMPTS == 5
    assert s.LOGIN_LOCKOUT_MINUTES == 10


@pytest.fixture
def _disabled(monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_ENABLED", False)


async def test_disabled_many_failures_never_lock_and_are_counted_and_audited(
    client, seeded_users, db_session, _disabled
):
    for _ in range(12):
        assert (await _attempt(client, WRONG)).status_code == 401
    user = await _user(db_session)
    assert user.locked_until is None
    assert user.failed_login_attempts == 12
    rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == AUDIT_ACTION_LOGIN_FAILURE)
        )
    ).scalars().all()
    assert len(rows) == 12
    locked = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == AUDIT_ACTION_ACCOUNT_LOCKED)
        )
    ).scalars().all()
    assert locked == []

    assert (await _attempt(client, CORRECT)).status_code == 200
    assert (await _user(db_session)).failed_login_attempts == 0


async def test_disabled_ignores_existing_locked_until(
    client, seeded_users, db_session, _disabled
):
    user = await _user(db_session)
    user.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
    await db_session.commit()
    assert (await _attempt(client, CORRECT)).status_code == 200


async def test_disabled_change_password_never_locks(
    client, seeded_users, db_session, _disabled
):
    token = await login(client, CODE)
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(8):
        r = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": WRONG, "new_password": "Harbour7Lantern9"},
        )
        assert r.status_code == 401
    assert (await _user(db_session)).locked_until is None
    ok = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": CORRECT, "new_password": "Harbour7Lantern9"},
    )
    assert ok.status_code == 200


async def test_disabled_change_password_ignores_existing_lock(
    client, seeded_users, db_session, _disabled
):
    token = await login(client, CODE)
    user = await _user(db_session)
    user.locked_until = datetime.now(timezone.utc) + timedelta(hours=1)
    await db_session.commit()
    ok = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": CORRECT, "new_password": "Harbour7Lantern9"},
    )
    assert ok.status_code == 200


async def test_enabled_uses_configured_attempts_and_minutes(
    client, seeded_users, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_ENABLED", True)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_MINUTES", 30)
    for _ in range(3):
        assert (await _attempt(client, WRONG)).status_code == 401  # 3rd trips the lock
    resp = await _attempt(client, CORRECT)
    assert resp.status_code == 423
    detail = resp.json()["detail"]
    assert "3 failed" in detail
    assert "30 minute" in detail
    assert "UTC" in detail
    details = resp.json()["details"]
    assert details["max_attempts"] == 3
    assert details["lockout_minutes"] == 30
    assert details["locked_until"].endswith("+00:00")
    stored = (await _user(db_session)).locked_until
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    delta = stored - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < delta <= timedelta(minutes=30)
