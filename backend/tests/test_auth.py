import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def test_login_success(client, seeded_users):
    resp = await client.post(
        "/api/v1/auth/login", json={"identifier": "ADMIN001", "password": "Password@123"}
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client, seeded_users):
    resp = await client.post(
        "/api/v1/auth/login", json={"identifier": "ADMIN001", "password": "wrong"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


async def test_me_requires_auth(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_returns_profile(client, seeded_users):
    token = await login(client, "ADMIN001")
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["employee_code"] == "ADMIN001"
    assert data["role"] == "admin"
