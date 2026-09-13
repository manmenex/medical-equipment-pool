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


# ---------------------------------------------------------------------------
# Self-service password change + forced change on first login.
#
# Before this existed, no user could change their own password at all: the
# only route was an Administrator calling PATCH /users/{id}, which asked for
# no current password and enforced no rules. The Administrator bootstrap's
# one-time password could therefore stay in use indefinitely.
# ---------------------------------------------------------------------------

NEW_PASSWORD = "Correct-Horse-Battery-9"


async def test_change_password_requires_auth(client, seeded_users):
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Password@123", "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 401


async def test_change_password_succeeds_and_the_new_password_works(client, seeded_users):
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 200

    # The real proof is not the 200 -- it is that the new password logs in
    # and the old one no longer does.
    ok = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": NEW_PASSWORD}
    )
    assert ok.status_code == 200
    stale = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert stale.status_code == 401


async def test_change_password_requires_the_current_password(client, seeded_users):
    """A token left on an unattended workstation must not be enough to take
    an account over permanently."""
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "not-the-current-password", "new_password": NEW_PASSWORD},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"

    # And nothing changed: the original password still works.
    ok = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert ok.status_code == 200


async def test_change_password_rejects_a_short_password(client, seeded_users):
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": "short"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "WEAK_PASSWORD"


async def test_change_password_rejects_surrounding_whitespace(client, seeded_users):
    """An account whose password depends on an invisible character is one
    nobody can support over the phone."""
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": f" {NEW_PASSWORD} "},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "WEAK_PASSWORD"


async def test_change_password_rejects_reusing_the_current_password(client, seeded_users):
    """Otherwise "change your password" can be satisfied by retyping it."""
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": "Password@123"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SAME_PASSWORD"


async def test_change_password_endpoint_cannot_target_another_account(client, seeded_users):
    """There is no user_id parameter, so a supplied one must be ignored
    rather than honoured."""
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "Password@123",
            "new_password": NEW_PASSWORD,
            "user_id": "00000000-0000-0000-0000-000000000000",
            "employee_code": "SOMEONE-ELSE",
        },
    )
    assert resp.status_code == 200
    # The caller's own password changed; nobody else's could have.
    ok = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": NEW_PASSWORD}
    )
    assert ok.status_code == 200


async def test_profile_exposes_must_change_password(client, seeded_users):
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    # Seeded users chose their own passwords, so the flag is False -- an
    # existing deployment must not have every account locked out on deploy.
    assert resp.json()["must_change_password"] is False


async def test_administrator_set_password_is_temporary_and_clears_on_change(client, seeded_users):
    """The whole point of the flag: two people now know that password."""
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    headers = {"Authorization": f"Bearer {token}"}

    listed = await client.get("/api/v1/users", headers=headers)
    assert listed.status_code == 200
    target = next(u for u in listed.json() if u["employee_code"] != ADMIN_EMPLOYEE_CODE)

    reset = await client.patch(
        f"/api/v1/users/{target['id']}",
        headers=headers,
        json={"password": "Temporary-Reset-2026"},
    )
    assert reset.status_code == 200

    # That user logs in with the temporary password and is told to replace it.
    target_token = await login(client, target["employee_code"], password="Temporary-Reset-2026")
    profile = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {target_token}"}
    )
    assert profile.status_code == 200
    assert profile.json()["must_change_password"] is True

    # Changing it clears the flag -- and this is the only thing that does.
    changed = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {target_token}"},
        json={"current_password": "Temporary-Reset-2026", "new_password": NEW_PASSWORD},
    )
    assert changed.status_code == 200

    after_token = await login(client, target["employee_code"], password=NEW_PASSWORD)
    after = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {after_token}"}
    )
    assert after.json()["must_change_password"] is False


async def test_failed_change_does_not_clear_the_forced_flag(client, seeded_users):
    """A wrong current password must not be a way out of the requirement."""
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    headers = {"Authorization": f"Bearer {token}"}
    listed = await client.get("/api/v1/users", headers=headers)
    target = next(u for u in listed.json() if u["employee_code"] != ADMIN_EMPLOYEE_CODE)
    await client.patch(
        f"/api/v1/users/{target['id']}", headers=headers, json={"password": "Temporary-Reset-2026"}
    )

    target_token = await login(client, target["employee_code"], password="Temporary-Reset-2026")
    target_headers = {"Authorization": f"Bearer {target_token}"}

    for payload in (
        {"current_password": "wrong-current", "new_password": NEW_PASSWORD},
        {"current_password": "Temporary-Reset-2026", "new_password": "tiny"},
        {"current_password": "Temporary-Reset-2026", "new_password": "Temporary-Reset-2026"},
    ):
        resp = await client.post(
            "/api/v1/auth/change-password", headers=target_headers, json=payload
        )
        assert resp.status_code in (400, 401)

    profile = await client.get("/api/v1/auth/me", headers=target_headers)
    assert profile.json()["must_change_password"] is True
