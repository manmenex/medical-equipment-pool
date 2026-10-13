"""Login lockout: 5 consecutive failures, 10 minutes, per account.

Owner decision. These tests assert the *behaviour* an operator would
observe, not the counter: that the sixth attempt is refused even with the
RIGHT password, that the lock lifts on its own, and that a success resets
the count -- because a counter that increments correctly while the gate
never closes would satisfy any test written against the number alone.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.audit import AUDIT_ACTION_ACCOUNT_LOCKED
from app.models.audit import AuditLog
from app.models.user import ROLE_ADMINISTRATOR, User
from app.services.auth_service import (
    LOCKOUT_DURATION,
    MAXIMUM_FAILED_LOGIN_ATTEMPTS,
)
from tests.conftest import login

pytestmark = pytest.mark.asyncio

ADMIN_EMPLOYEE_CODE = f"{ROLE_ADMINISTRATOR.upper()}001"
CORRECT = "Password@123"
WRONG = "definitely-not-the-password"


async def _attempt(client, password, *, identifier=ADMIN_EMPLOYEE_CODE):
    return await client.post(
        "/api/v1/auth/login", json={"identifier": identifier, "password": password}
    )


async def _fail_to_the_threshold(client):
    """Exactly enough wrong attempts to reach the lock, no more."""
    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS):
        resp = await _attempt(client, WRONG)
        assert resp.status_code == 401, resp.text


async def test_attempts_below_the_threshold_do_not_lock(client, seeded_users):
    """The boundary from below: one short of the limit must still work.

    An off-by-one here would lock users a whole attempt early, which in a
    ward is the difference between "I mistyped it" and "I am locked out".
    """
    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS - 1):
        assert (await _attempt(client, WRONG)).status_code == 401

    ok = await _attempt(client, CORRECT)
    assert ok.status_code == 200


async def test_the_threshold_locks_the_account_even_for_the_right_password(
    client, seeded_users
):
    """The whole point of the control, and the thing a counter test misses.

    After the fifth failure the CORRECT password must be refused too --
    otherwise the counter is being maintained while the gate stays open.
    """
    await _fail_to_the_threshold(client)

    resp = await _attempt(client, CORRECT)
    assert resp.status_code == 423
    assert resp.json()["code"] == "ACCOUNT_LOCKED"


async def test_the_lock_message_says_how_long_to_wait(client, seeded_users):
    """A locked user with no end time keeps retrying, which is both a
    support call and more load."""
    await _fail_to_the_threshold(client)
    resp = await _attempt(client, CORRECT)
    assert "10 minute" in resp.json()["detail"]


async def test_attempts_against_a_locked_account_do_not_extend_the_lock(
    client, seeded_users, db_session
):
    """Otherwise an attacker who keeps trying holds the real user out
    indefinitely instead of for ten minutes, and the account never
    recovers while the attack continues."""
    await _fail_to_the_threshold(client)

    user = (
        await db_session.execute(
            select(User).where(User.employee_code == ADMIN_EMPLOYEE_CODE)
        )
    ).scalar_one()
    await db_session.refresh(user)
    first_deadline = user.locked_until
    assert first_deadline is not None

    for _ in range(3):
        assert (await _attempt(client, WRONG)).status_code == 423

    await db_session.refresh(user)
    assert user.locked_until == first_deadline


async def test_the_lock_lifts_by_itself_without_anything_running(
    client, seeded_users, db_session
):
    """A lock expires by being in the past -- no job, no cron, no cleanup.

    Simulated by moving the stored deadline into the past rather than
    waiting ten minutes, which is the one thing a test cannot do honestly.
    """
    await _fail_to_the_threshold(client)
    assert (await _attempt(client, CORRECT)).status_code == 423

    user = (
        await db_session.execute(
            select(User).where(User.employee_code == ADMIN_EMPLOYEE_CODE)
        )
    ).scalar_one()
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    assert (await _attempt(client, CORRECT)).status_code == 200


async def test_a_successful_login_resets_the_counter(client, seeded_users):
    """Four failures then a success must not leave one failure away from a
    lock -- the next typo would be the fifth and the user would be locked
    out having signed in successfully in between."""
    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS - 1):
        assert (await _attempt(client, WRONG)).status_code == 401
    assert (await _attempt(client, CORRECT)).status_code == 200

    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS - 1):
        assert (await _attempt(client, WRONG)).status_code == 401
    assert (await _attempt(client, CORRECT)).status_code == 200


async def test_the_lock_is_per_account(client, seeded_users):
    """The Owner chose per-account. Locking one must not touch another."""
    await _fail_to_the_threshold(client)
    assert (await _attempt(client, CORRECT)).status_code == 423

    other = await _attempt(
        client, CORRECT, identifier="EQUIPMENT_POOL_STAFF001"
    )
    assert other.status_code == 200


async def test_an_unknown_identifier_locks_nothing(client, seeded_users):
    """There is no account to count against, and inventing somewhere to
    count it would mean persisting the submitted identifier -- exactly what
    ADR-0001 forbids. The real account must be unaffected."""
    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS * 2):
        resp = await _attempt(client, WRONG, identifier="NO-SUCH-ACCOUNT-9999")
        assert resp.status_code == 401
        assert resp.json()["code"] == "INVALID_CREDENTIALS"

    assert (await _attempt(client, CORRECT)).status_code == 200


async def test_locking_an_account_is_audited_as_its_own_event(
    client, seeded_users, db_session
):
    """An administrator fielding "I am locked out" needs to find the lock,
    not reconstruct it by counting failure rows."""
    await _fail_to_the_threshold(client)

    rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == AUDIT_ACTION_ACCOUNT_LOCKED)
        )
    ).scalars().all()
    assert len(rows) == 1
    # No actor: a failed attempt has no authenticated actor (ADR-0001), and
    # the locked account is the subject rather than the agent.
    assert rows[0].user_id is None
    assert rows[0].entity_id is not None


async def test_the_lock_is_recorded_for_about_the_configured_duration(
    client, seeded_users, db_session
):
    """Bound to LOCKOUT_DURATION, not to a hard-coded ten minutes, so the
    test follows the constant if the Owner changes it."""
    before = datetime.now(timezone.utc)
    await _fail_to_the_threshold(client)

    user = (
        await db_session.execute(
            select(User).where(User.employee_code == ADMIN_EMPLOYEE_CODE)
        )
    ).scalar_one()
    await db_session.refresh(user)
    stored = user.locked_until
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)

    assert before + LOCKOUT_DURATION - timedelta(seconds=30) <= stored
    assert stored <= datetime.now(timezone.utc) + LOCKOUT_DURATION


# ---------------------------------------------------------------------------
# The change-password path verifies the same secret, so it shares the counter.
# ---------------------------------------------------------------------------


async def test_a_wrong_current_password_counts_towards_the_lock(client, seeded_users):
    """Otherwise a stolen access token is an unlimited oracle for the
    current password here, while /auth/login is locked -- the control would
    be real on one door and decorative on the other."""
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    headers = {"Authorization": f"Bearer {token}"}

    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS):
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": WRONG, "new_password": "Harbour7Lantern9"},
        )
        assert resp.status_code == 401

    # The lock is now in force on BOTH doors.
    assert (await _attempt(client, CORRECT)).status_code == 423
    locked = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": CORRECT, "new_password": "Harbour7Lantern9"},
    )
    assert locked.status_code == 423
    assert locked.json()["code"] == "ACCOUNT_LOCKED"


async def test_a_successful_change_clears_the_counter(client, seeded_users):
    """They proved they know the current password to get here, so the
    accumulated failures were their own typing."""
    token = await login(client, ADMIN_EMPLOYEE_CODE)
    headers = {"Authorization": f"Bearer {token}"}

    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS - 1):
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers=headers,
            json={"current_password": WRONG, "new_password": "Harbour7Lantern9"},
        )
        assert resp.status_code == 401

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": CORRECT, "new_password": "Harbour7Lantern9"},
    )
    assert changed.status_code == 200

    # Four more failures must not lock: the counter restarted at zero.
    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS - 1):
        assert (await _attempt(client, WRONG)).status_code == 401
    assert (await _attempt(client, "Harbour7Lantern9")).status_code == 200


# ---------------------------------------------------------------------------
# Administrator reset (Owner decision: free of the password policy).
# ---------------------------------------------------------------------------


async def test_an_administrator_setting_a_password_clears_the_lock(
    client, seeded_users
):
    """The Administrator is already resetting the credential; leaving the
    account locked for another ten minutes would just produce a second
    support call for the same incident."""
    admin_token = await login(client, ADMIN_EMPLOYEE_CODE)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    listed = await client.get("/api/v1/users", headers=admin_headers)
    target = next(
        u for u in listed.json() if u["employee_code"] != ADMIN_EMPLOYEE_CODE
    )

    for _ in range(MAXIMUM_FAILED_LOGIN_ATTEMPTS):
        resp = await _attempt(client, WRONG, identifier=target["employee_code"])
        assert resp.status_code == 401
    assert (
        await _attempt(client, CORRECT, identifier=target["employee_code"])
    ).status_code == 423

    reset = await client.patch(
        f"/api/v1/users/{target['id']}",
        headers=admin_headers,
        json={"password": "TemporaryReset2026"},
    )
    assert reset.status_code == 200

    unlocked = await _attempt(
        client, "TemporaryReset2026", identifier=target["employee_code"]
    )
    assert unlocked.status_code == 200


async def test_an_administrator_may_set_a_password_the_policy_would_refuse(
    client, seeded_users
):
    """Owner decision: this path is free of the self-service policy.

    "ab" is below the minimum, has no digit, and has too few distinct
    characters -- every structural rule the policy applies. It is accepted
    here, and the account is then required to replace it.
    """
    admin_token = await login(client, ADMIN_EMPLOYEE_CODE)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    listed = await client.get("/api/v1/users", headers=admin_headers)
    target = next(
        u for u in listed.json() if u["employee_code"] != ADMIN_EMPLOYEE_CODE
    )

    resp = await client.patch(
        f"/api/v1/users/{target['id']}", headers=admin_headers, json={"password": "ab"}
    )
    assert resp.status_code == 200

    # It works, and it is temporary.
    signed_in = await _attempt(client, "ab", identifier=target["employee_code"])
    assert signed_in.status_code == 200

    target_headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
    profile = await client.get("/api/v1/auth/me", headers=target_headers)
    assert profile.json()["must_change_password"] is True


async def test_an_administrator_password_over_the_hashing_limit_is_refused_not_crashed(
    client, seeded_users
):
    """The one check that still applies on this path, and it is not policy.

    bcrypt.hashpw raises above 72 bytes, so without the guard an
    Administrator typing a long password gets an unhandled HTTP 500.
    """
    admin_token = await login(client, ADMIN_EMPLOYEE_CODE)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    listed = await client.get("/api/v1/users", headers=admin_headers)
    target = next(
        u for u in listed.json() if u["employee_code"] != ADMIN_EMPLOYEE_CODE
    )

    resp = await client.patch(
        f"/api/v1/users/{target['id']}",
        headers=admin_headers,
        json={"password": "a" * 73},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_INPUT"
