import pytest

from app.models.user import ROLE_ADMINISTRATOR
from tests.conftest import login

pytestmark = pytest.mark.asyncio

# The seeded_users fixture (tests/conftest.py) derives each user's
# employee_code from its role name (f"{role_name.upper()}001") -- Roadmap
# PR10 renamed the "admin" role to "administrator", so the seeded
# administrator's employee_code is now ADMINISTRATOR001, not ADMIN001.
ADMIN_EMPLOYEE_CODE = f"{ROLE_ADMINISTRATOR.upper()}001"


async def test_login_success(client, seeded_users):
    resp = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client, seeded_users):
    resp = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


async def test_me_requires_auth(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_returns_profile(client, seeded_users):
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["employee_code"] == ADMIN_EMPLOYEE_CODE
    assert data["role"] == ROLE_ADMINISTRATOR
