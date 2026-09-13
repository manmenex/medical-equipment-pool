import pytest

from app.models.user import ROLE_ADMINISTRATOR
from app.services.auth_service import MAXIMUM_PASSWORD_BYTES, MINIMUM_PASSWORD_LENGTH
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

# Long enough to slice any boundary case out of, and pure ASCII so that one
# character is exactly one byte. The length tests slice this rather than
# writing a literal of a counted length -- a hand-counted 72-character string
# is one typo away from silently testing the wrong side of the boundary,
# which is precisely what happened while writing these.
_ASCII_FILLER = "Correct-Horse-Battery-Staple-Cupboard-Lantern-Kettle-Window-Harbour-Ferryboat-Anchor"
assert len(_ASCII_FILLER) == len(_ASCII_FILLER.encode("utf-8"))


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


async def test_change_password_rejects_a_password_one_character_below_the_minimum(
    client, seeded_users
):
    """Bound to the constant, not to a hard-coded short string.

    The minimum has already moved once (12 -> 6, an Owner decision). A test
    written against a literal like "short" keeps passing when the minimum
    drops below it, while quietly no longer testing the boundary at all.
    """
    too_short = "a1B2c3D4e5F6g7"[: MINIMUM_PASSWORD_LENGTH - 1]
    assert len(too_short) == MINIMUM_PASSWORD_LENGTH - 1

    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": too_short},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "WEAK_PASSWORD"


async def test_change_password_accepts_a_password_exactly_at_the_minimum(
    client, seeded_users
):
    """The other half of the boundary: the minimum must be attainable.

    Without this, an off-by-one that rejects exactly-minimum passwords would
    pass every other test in this file while telling users the rule is one
    character laxer than it is.
    """
    exactly_minimum = "a1B2c3D4e5F6g7"[:MINIMUM_PASSWORD_LENGTH]
    assert len(exactly_minimum) == MINIMUM_PASSWORD_LENGTH

    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": exactly_minimum},
    )
    assert resp.status_code == 200

    # Behaviour, not status code: the accepted password actually logs in.
    ok = await client.post(
        "/api/v1/auth/login",
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": exactly_minimum},
    )
    assert ok.status_code == 200


async def test_a_long_passphrase_at_the_hashing_limit_is_accepted(client, seeded_users):
    """No policy cap below bcrypt's own: 72 bytes must be usable in full."""
    # Sliced from the constant rather than hand-counted: ASCII, so one
    # character is one byte, and the test cannot drift off the boundary.
    passphrase = _ASCII_FILLER[:MAXIMUM_PASSWORD_BYTES]
    assert len(passphrase.encode("utf-8")) == MAXIMUM_PASSWORD_BYTES

    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": passphrase},
    )
    assert resp.status_code == 200

    ok = await client.post(
        "/api/v1/auth/login",
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": passphrase},
    )
    assert ok.status_code == 200


async def test_a_password_over_the_hashing_limit_is_refused_not_crashed(
    client, seeded_users
):
    """bcrypt raises above 72 bytes. Without the guard this is an HTTP 500.

    The regression to prevent is not "long passwords are allowed" -- it is
    "the server crashes instead of telling the user what is wrong".
    """
    passphrase = _ASCII_FILLER[: MAXIMUM_PASSWORD_BYTES + 1]
    assert len(passphrase.encode("utf-8")) == MAXIMUM_PASSWORD_BYTES + 1

    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": passphrase},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "WEAK_PASSWORD"

    # And the account is untouched -- a refused change must change nothing.
    ok = await client.post(
        "/api/v1/auth/login",
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"},
    )
    assert ok.status_code == 200


async def test_the_byte_limit_is_counted_in_bytes_not_characters(client, seeded_users):
    """The limit that actually bites this application.

    The UI is Thai and Thai characters are 3 bytes each in UTF-8, so 25 Thai
    characters -- about a sentence -- is already 75 bytes. A character-based
    check would let this through and crash inside bcrypt.
    """
    thai = "ก" * 25
    assert len(thai) == 25
    assert len(thai.encode("utf-8")) == 75

    token = await login(client, ADMIN_EMPLOYEE_CODE)
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "Password@123", "new_password": thai},
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


async def test_fresh_install_and_upgrade_agree_on_the_column_default():
    """The two installation paths must produce the same physical column.

    A brand-new database gets `users.must_change_password` from
    `Base.metadata.create_all()` (migration 0001_initial); a database that
    predates this slice gets it from 0023's `ADD COLUMN`. SQLAlchemy's
    `default=` is Python-side only and emits no DDL, so a model without
    `server_default=` yields a fresh-install column with no catalog default
    while the upgrade path has `DEFAULT FALSE` -- and then
    `ADD COLUMN IF NOT EXISTS` silently does nothing on the fresh install,
    leaving the divergence in place. 0023's convergence check aborts the
    migration on exactly that, which is how this was found; this test fails
    in milliseconds instead of at `alembic upgrade head`.
    """
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from app.models.user import User

    column = User.__table__.c.must_change_password
    assert column.server_default is not None, (
        "users.must_change_password has no server_default, so Base.metadata.create_all() "
        "would build a fresh install without the catalog default that migration 0023 gives "
        "an upgraded database."
    )

    fresh_install_ddl = str(CreateTable(User.__table__).compile(dialect=postgresql.dialect()))
    emitted = next(
        line.strip()
        for line in fresh_install_ddl.splitlines()
        if line.strip().startswith("must_change_password")
    )
    assert "DEFAULT false" in emitted, emitted
    assert "NOT NULL" in emitted, emitted

    # The other half of the pair: the upgrade path's own DDL. Read from the
    # migration module rather than restated here, so the two cannot drift.
    import importlib.util
    from pathlib import Path

    migration_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0023_user_must_change_password.py"
    spec = importlib.util.spec_from_file_location("_mep_migration_0023", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    add_column = " ".join(module._ADD_COLUMN.split()).upper()
    assert "DEFAULT FALSE" in add_column, module._ADD_COLUMN
    assert "NOT NULL" in add_column, module._ADD_COLUMN
