"""Forced first-login password change: coverage for gates not exercised in test_auth.py
(dashboard SSE auth, require_roles routes, and the status-change route)."""
import uuid

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import dashboard as dashboard_module
from app.core.exceptions import PasswordChangeRequiredError
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF
from tests.conftest import login

pytestmark = pytest.mark.asyncio

TEMP_PASSWORD = "TemporaryReset2026"


async def _flag_user_via_admin_reset(client, role_name):
    """Flag the seeded user of `role_name` through a real administrator password reset."""
    admin_token = await login(client, f"{ROLE_ADMINISTRATOR.upper()}001")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    listed = await client.get("/api/v1/users", headers=admin_headers)
    code = f"{role_name.upper()}001"
    target = next(u for u in listed.json() if u["employee_code"] == code)
    reset = await client.patch(f"/api/v1/users/{target['id']}", headers=admin_headers, json={"password": TEMP_PASSWORD})
    assert reset.status_code == 200, reset.text
    token = await login(client, code, password=TEMP_PASSWORD)
    return token, {"Authorization": f"Bearer {token}"}


async def test_dashboard_stream_auth_rejects_flagged_user(client, db_engine, seeded_users, monkeypatch):
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(dashboard_module, "AsyncSessionLocal", session_maker)
    token, _ = await _flag_user_via_admin_reset(client, ROLE_EQUIPMENT_POOL_STAFF)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # Call the dependency directly so no open stream is created.
    with pytest.raises(PasswordChangeRequiredError) as exc_info:
        await dashboard_module.get_current_user_for_stream(credentials)
    assert exc_info.value.code == "PASSWORD_CHANGE_REQUIRED"


async def test_dashboard_stream_auth_accepts_unflagged_user(client, db_engine, seeded_users, monkeypatch):
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(dashboard_module, "AsyncSessionLocal", session_maker)
    token = await login(client, f"{ROLE_EQUIPMENT_POOL_STAFF.upper()}001")
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    user = await dashboard_module.get_current_user_for_stream(credentials)
    assert user.id == seeded_users[ROLE_EQUIPMENT_POOL_STAFF].id


async def test_flagged_administrator_is_refused_on_require_roles_route(client, seeded_users):
    # GET /users is gated by require_roles(ROLE_ADMINISTRATOR); the role is allowed,
    # so the 403 can only come from the forced-change check.
    _, headers = await _flag_user_via_admin_reset(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_flagged_staff_is_refused_on_equipment_status_change(client, seeded_users):
    # Equipment Pool Staff is allowed by require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)
    # and get_current_role_name; the 403 must be the forced-change check.
    _, headers = await _flag_user_via_admin_reset(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await client.post(
        f"/api/v1/equipment/{uuid.uuid4()}/status",
        headers=headers,
        json={"status": "UNAVAILABLE_DEFECTIVE", "reason": "test"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
