import logging
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.audit import redact_sensitive
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.user import ALL_ROLES, ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, Role, User
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio

# The seeded_users fixture (tests/conftest.py) derives each user's
# employee_code from its role name (f"{role_name.upper()}001") -- Roadmap
# PR10 renamed the "admin" role to "administrator", so the seeded
# administrator's employee_code is now ADMINISTRATOR001, not ADMIN001.
ADMIN_EMPLOYEE_CODE = f"{ROLE_ADMINISTRATOR.upper()}001"


async def _raw_client():
    """Same app/dependency_overrides as `client`, but with raise_app_exceptions=False.

    Starlette's ServerErrorMiddleware re-raises after sending a 500 response;
    httpx's default ASGITransport re-raises that into the caller. See the
    identical helper in test_exception_handling.py (PR2) for the full
    explanation — needed here for the same reason: inspecting the response an
    injected, unhandled exception already produced, rather than failing the
    test on the exception itself.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def _rows(db_session, *, action=None, entity_type=None, entity_id=None):
    stmt = select(AuditLog)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type is not None:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    result = await db_session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# redact_sensitive() unit tests
# ---------------------------------------------------------------------------


async def test_redact_sensitive_masks_known_keys():
    data = {
        "password": "hunter2",
        "password_hash": "$2b$...",
        "hashed_password": "$2b$...",
        "current_password": "hunter2",
        "new_password": "hunter3",
        "refresh_token": "abc.def.ghi",
        "access_token": "abc.def.ghi",
        "jwt": "abc.def.ghi",
        "authorization": "Bearer abc.def.ghi",
        "cookie": "session=abc123",
        "secret": "s3cr3t",
        "client_secret": "s3cr3t",
        "api_key": "k-123",
        "private_key": "-----BEGIN PRIVATE KEY-----",
        "full_name": "Jane Doe",
    }
    redacted = redact_sensitive(data)
    for key in data:
        if key == "full_name":
            continue
        assert redacted[key] == "***REDACTED***", f"expected {key!r} to be redacted"
    assert redacted["full_name"] == "Jane Doe"


async def test_redact_sensitive_handles_nested_and_missing_data():
    assert redact_sensitive(None) is None
    nested = {"user": {"password": "hunter2", "name": "Jane"}, "items": ["a", {"jwt": "x"}]}
    redacted = redact_sensitive(nested)
    assert redacted["user"]["password"] == "***REDACTED***"
    assert redacted["user"]["name"] == "Jane"
    assert redacted["items"][0] == "a"
    assert redacted["items"][1]["jwt"] == "***REDACTED***"


# ---------------------------------------------------------------------------
# Authentication events
# ---------------------------------------------------------------------------


async def test_login_success_creates_audit_row(client, seeded_users, db_session):
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-Correlation-ID": "corr-login-success"},
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"},
    )
    assert resp.status_code == 200
    assert resp.headers["x-correlation-id"] == "corr-login-success"
    assert "x-request-id" in resp.headers

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == seeded_users[ROLE_ADMINISTRATOR].id
    assert row.correlation_id == "corr-login-success"
    assert row.request_id is not None


async def test_oversized_inbound_request_id_is_rejected_not_persisted_raw(client, seeded_users, db_session):
    # audit_logs.request_id/correlation_id are String(64) on PostgreSQL — an
    # inbound header longer than that must never reach the INSERT as-is.
    oversized = "x" * 500
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": oversized, "X-Correlation-ID": oversized},
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-request-id"] != oversized
    assert len(resp.headers["x-request-id"]) <= 64

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].request_id != oversized
    assert rows[0].request_id is not None and len(rows[0].request_id) <= 64
    assert rows[0].correlation_id != oversized


async def test_unsafe_characters_in_inbound_request_id_are_rejected(client, seeded_users, db_session):
    unsafe = "abc\t\r\n<script>oops"
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": unsafe},
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-request-id"] != unsafe

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].request_id != unsafe


async def test_user_agent_is_bounded_and_sanitized(client, seeded_users, db_session):
    oversized_ua = "X" * 1000
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"User-Agent": oversized_ua},
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"},
    )
    assert resp.status_code == 200, resp.text

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].user_agent is not None
    assert len(rows[0].user_agent) <= 255


async def test_user_agent_control_characters_are_stripped(client, seeded_users, db_session):
    unsafe_ua = "Mozilla/5.0\r\nX-Injected: evil\x00control"
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"User-Agent": unsafe_ua},
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"},
    )
    assert resp.status_code == 200, resp.text

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert len(rows) == 1
    assert "\r" not in rows[0].user_agent
    assert "\n" not in rows[0].user_agent
    assert "\x00" not in rows[0].user_agent


async def test_trailing_newline_inbound_request_id_is_rejected(client, seeded_users, db_session):
    # Regression for match() vs fullmatch(): `$` (without re.MULTILINE)
    # matches either end-of-string or just before a trailing "\n", so a
    # pattern anchored with `^...$` and checked via .match() would wrongly
    # accept "validvalue\n" and let the newline reach the database.
    # fullmatch() must reject this.
    trailing_newline = "a" * 30 + "\n"
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": trailing_newline},
        json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["x-request-id"] != trailing_newline
    assert "\n" not in resp.headers["x-request-id"]

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].request_id != trailing_newline
    assert "\n" not in rows[0].request_id


async def test_login_failure_wrong_password_known_account_has_null_actor(client, seeded_users, db_session):
    resp = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "wrong-password"}
    )
    assert resp.status_code == 401

    rows = await _rows(db_session, action="login_failure", entity_type="auth")
    assert len(rows) == 1
    # Per ADR-0001: the actor is never the authentication target, even for
    # a known account — only the *subject* (entity_id) may reference it.
    assert rows[0].user_id is None
    assert rows[0].entity_id == seeded_users[ROLE_ADMINISTRATOR].id
    # No form of the submitted identifier is persisted — not raw, not
    # hashed, not in any other representation.
    assert rows[0].after_data is None
    assert rows[0].before_data is None


async def test_login_failure_unknown_identifier_has_null_actor_and_null_entity(client, seeded_users, db_session):
    resp = await client.post(
        "/api/v1/auth/login", json={"identifier": "NOBODY001", "password": "wrong-password"}
    )
    assert resp.status_code == 401

    rows = await _rows(db_session, action="login_failure", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].entity_id is None
    assert rows[0].after_data is None
    assert rows[0].before_data is None
    # The unknown identifier must not appear anywhere in the persisted row,
    # in any representation (raw, hashed, or otherwise).
    row_repr = f"{rows[0].after_data}{rows[0].before_data}{rows[0].user_id}{rows[0].entity_id}"
    assert "NOBODY001" not in row_repr


async def test_login_succeeds_even_if_audit_write_fails(client, seeded_users, db_session, monkeypatch):
    """Authentication events are best-effort (see record_best_effort_audit_event) —
    a broken audit subsystem must never lock a legitimate user out."""

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr("app.core.audit.audit_crud.create", _boom)

    resp = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert rows == [], "the failed audit write should have rolled back to its savepoint, not persisted"


# ---------------------------------------------------------------------------
# PR7-M1: best-effort protection must cover the *whole* auth persistence
# boundary, not just the audit write's own SAVEPOINT — a failure in the
# commit that follows it (outside that SAVEPOINT) must not turn a decided
# authentication outcome into an unrelated 500 either. See
# commit_best_effort() in app/core/audit.py.
#
# These tests need a real transaction boundary where a SAVEPOINT (from
# record_best_effort_audit_event's begin_nested()) is released and then the
# *outer* transaction is rolled back — pysqlite's default legacy transaction
# handling does not correctly support that combination (a released
# SAVEPOINT's row can survive a later db.rollback()), which is exactly the
# documented reason SQLAlchemy ships a dedicated recipe for it. Rather than
# apply that recipe to the shared `db_engine` fixture (used by ~150 other
# tests, including ones that deliberately exercise the still-open, PR
# #10-owned MissingGreenlet defect in a way that turns out to interact badly
# with stricter transaction semantics — out of scope here), it is scoped to
# a dedicated engine/client used only by this section.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sp_engine():
    from sqlalchemy import event

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # See https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#serializable-isolation-savepoints-transactional-ddl
    @event.listens_for(engine.sync_engine, "connect")
    def _do_connect(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _do_begin(conn):
        conn.exec_driver_sql("BEGIN")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def sp_seeded_users(sp_engine):
    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as session:
        roles = {}
        for name in ALL_ROLES:
            role = Role(name=name, permissions={})
            session.add(role)
            roles[name] = role
        await session.flush()

        users = {}
        for role_name in ALL_ROLES:
            user = User(
                employee_code=f"{role_name.upper()}001",
                full_name=f"Test {role_name}",
                email=f"{role_name}@mep-hospital-test.dev",
                password_hash=hash_password("Password@123"),
                role_id=roles[role_name].id,
            )
            session.add(user)
            users[role_name] = user
        await session.commit()
        return users


@pytest_asyncio.fixture
async def sp_client(sp_engine):
    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db():
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _boom_commit(monkeypatch):
    async def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(AsyncSession, "commit", _boom)


async def _rows_fresh(sp_engine, *, action=None, entity_type=None, entity_id=None):
    """Same query as _rows(), but through a brand-new session/connection.

    These commit-time-failure tests exercise a real rollback (via
    commit_best_effort's `await db.rollback()`) on the *request's own*
    session, which is a different AsyncSession object than any other
    fixture-held session even though both share the same underlying
    StaticPool SQLite connection. Verifying through a fresh session — the
    same pattern PR2's test_exception_handling.py uses for post-rollback
    assertions — avoids relying on some other session's own transactional/
    visibility state, which is unrelated to the request's rollback and not a
    reliable way to observe it.
    """
    session_maker = async_sessionmaker(sp_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as fresh_session:
        return await _rows(fresh_session, action=action, entity_type=entity_type, entity_id=entity_id)


async def test_login_failure_response_survives_commit_time_failure(
    sp_client, sp_seeded_users, sp_engine, monkeypatch
):
    _boom_commit(monkeypatch)

    resp = await sp_client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "wrong-password"}
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == "INVALID_CREDENTIALS"

    monkeypatch.undo()
    rows = await _rows_fresh(sp_engine, action="login_failure", entity_type="auth")
    assert rows == [], "a failed commit must leave no partial audit row behind"


async def test_login_success_response_survives_commit_time_failure(
    sp_client, sp_seeded_users, sp_engine, monkeypatch
):
    _boom_commit(monkeypatch)

    resp = await sp_client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()

    monkeypatch.undo()
    rows = await _rows_fresh(sp_engine, action="login_success", entity_type="auth")
    assert rows == [], "a failed commit must leave no partial audit row behind"


async def test_refresh_response_survives_commit_time_failure(sp_client, sp_seeded_users, sp_engine, monkeypatch):
    login_resp = await sp_client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert login_resp.status_code == 200

    _boom_commit(monkeypatch)

    resp = await sp_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()

    monkeypatch.undo()
    rows = await _rows_fresh(sp_engine, action="token_refresh", entity_type="auth")
    assert rows == [], "a failed commit must leave no partial audit row behind"

    # Session recovery: an ordinary follow-up request through the same
    # dependency-injected session machinery still works.
    follow_up = await sp_client.get("/api/v1/audit-logs", headers=await _auth_headers(sp_client, ROLE_ADMINISTRATOR))
    assert follow_up.status_code == 200


async def test_logout_response_survives_commit_time_failure(sp_client, sp_seeded_users, sp_engine, monkeypatch):
    headers = await _auth_headers(sp_client, ROLE_ADMINISTRATOR)

    _boom_commit(monkeypatch)

    resp = await sp_client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200, resp.text

    monkeypatch.undo()
    rows = await _rows_fresh(sp_engine, action="logout", entity_type="auth")
    assert rows == [], "a failed commit must leave no partial audit row behind"


# ---------------------------------------------------------------------------
# CR7-M2: the cleanup rollback inside commit_best_effort() must itself be
# best-effort — if *both* the commit and the rollback that cleans up after it
# fail (e.g. the connection is genuinely gone), the already-decided
# authentication outcome must still survive, and both failures must be
# logged as warnings (never re-raised, never silently dropped).
# ---------------------------------------------------------------------------


def _boom_commit_and_rollback(monkeypatch):
    async def _boom_commit_impl(self, *args, **kwargs):
        raise RuntimeError("simulated commit failure")

    async def _boom_rollback_impl(self, *args, **kwargs):
        raise RuntimeError("simulated rollback failure")

    monkeypatch.setattr(AsyncSession, "commit", _boom_commit_impl)
    monkeypatch.setattr(AsyncSession, "rollback", _boom_rollback_impl)


def _assert_commit_and_rollback_warnings_logged(caplog):
    messages = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    assert any("Failed to commit authentication audit transaction" in m for m in messages), (
        "expected a warning log for the commit failure"
    )
    assert any("Failed to roll back authentication audit transaction" in m for m in messages), (
        "expected a warning log for the rollback-cleanup failure"
    )
    # Never log credentials/tokens/identifiers — only the fixed message text
    # and (via exc_info, not the formatted message) the simulated
    # RuntimeError itself.
    for m in messages:
        assert "Password@123" not in m
        assert "wrong-password" not in m


async def test_login_failure_response_survives_commit_and_rollback_failure(
    sp_client, sp_seeded_users, sp_engine, monkeypatch, caplog
):
    _boom_commit_and_rollback(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="app.core.audit"):
        resp = await sp_client.post(
            "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "wrong-password"}
        )
    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == "INVALID_CREDENTIALS"
    _assert_commit_and_rollback_warnings_logged(caplog)

    monkeypatch.undo()
    # A fresh request (its own fresh session, per sp_client's dependency
    # override) still works normally — the failure did not wedge the app.
    follow_up = await sp_client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert follow_up.status_code == 200, follow_up.text


async def test_login_success_response_survives_commit_and_rollback_failure(
    sp_client, sp_seeded_users, sp_engine, monkeypatch, caplog
):
    _boom_commit_and_rollback(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="app.core.audit"):
        resp = await sp_client.post(
            "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
        )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()
    _assert_commit_and_rollback_warnings_logged(caplog)

    monkeypatch.undo()
    follow_up = await sp_client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert follow_up.status_code == 200, follow_up.text


async def test_refresh_response_survives_commit_and_rollback_failure(
    sp_client, sp_seeded_users, sp_engine, monkeypatch, caplog
):
    login_resp = await sp_client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert login_resp.status_code == 200

    _boom_commit_and_rollback(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="app.core.audit"):
        resp = await sp_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()
    _assert_commit_and_rollback_warnings_logged(caplog)

    monkeypatch.undo()
    # Session recovery: an ordinary follow-up request through a fresh
    # session still works.
    follow_up = await sp_client.get("/api/v1/audit-logs", headers=await _auth_headers(sp_client, ROLE_ADMINISTRATOR))
    assert follow_up.status_code == 200


async def test_logout_response_survives_commit_and_rollback_failure(
    sp_client, sp_seeded_users, sp_engine, monkeypatch, caplog
):
    headers = await _auth_headers(sp_client, ROLE_ADMINISTRATOR)

    _boom_commit_and_rollback(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="app.core.audit"):
        resp = await sp_client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200, resp.text
    _assert_commit_and_rollback_warnings_logged(caplog)

    monkeypatch.undo()
    follow_up = await sp_client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert follow_up.status_code == 200, follow_up.text


async def test_logout_creates_audit_row(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200

    rows = await _rows(db_session, action="logout", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].user_id == seeded_users[ROLE_ADMINISTRATOR].id


async def test_refresh_creates_audit_row(client, seeded_users, db_session):
    login_resp = await client.post(
        "/api/v1/auth/login", json={"identifier": ADMIN_EMPLOYEE_CODE, "password": "Password@123"}
    )
    assert login_resp.status_code == 200

    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200

    rows = await _rows(db_session, action="token_refresh", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].user_id == seeded_users[ROLE_ADMINISTRATOR].id


# ---------------------------------------------------------------------------
# Master data: users (including password reset/change masking)
# ---------------------------------------------------------------------------


async def test_create_user_masks_password_in_audit(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "employee_code": "NEWUSER01",
            "full_name": "New Person",
            "email": "new.person@mep-hospital-test.dev",
            "password": "SuperSecret@123",
            "role_name": ROLE_READ_ONLY,
        },
    )
    assert resp.status_code == 201, resp.text
    new_user_id = resp.json()["id"]

    rows = await _rows(db_session, action="create", entity_type="user")
    assert len(rows) == 1
    row = rows[0]
    assert str(row.entity_id) == new_user_id
    assert row.user_id == seeded_users[ROLE_ADMINISTRATOR].id
    assert row.after_data["password"] == "***REDACTED***"
    assert "SuperSecret@123" not in str(row.after_data)
    assert row.after_data["employee_code"] == "NEWUSER01"


async def test_update_user_password_change_masks_password_and_records_before_after(
    client, seeded_users, db_session
):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    target_id = str(seeded_users[ROLE_READ_ONLY].id)

    resp = await client.patch(
        f"/api/v1/users/{target_id}",
        headers=headers,
        json={"password": "BrandNewPassword@123", "is_active": False},
    )
    assert resp.status_code == 200, resp.text

    rows = await _rows(db_session, action="update", entity_type="user")
    assert len(rows) == 1
    row = rows[0]
    assert str(row.entity_id) == target_id
    assert row.user_id == seeded_users[ROLE_ADMINISTRATOR].id
    assert row.after_data["password"] == "***REDACTED***"
    assert "BrandNewPassword@123" not in str(row.after_data)
    assert row.before_data["password_hash"] == "***REDACTED***"
    assert row.before_data["is_active"] is True
    assert row.after_data["is_active"] is False


async def test_update_user_role_change_records_before_and_after_role_name(client, seeded_users, db_session):
    """Roadmap PR10: a role reassignment is audited like any other user
    update -- before_data/after_data must capture the actual role name
    change (read_only -> equipment_pool_staff here), not just that some
    update happened."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    target_id = str(seeded_users[ROLE_READ_ONLY].id)

    resp = await client.patch(
        f"/api/v1/users/{target_id}",
        headers=headers,
        json={"role_name": ROLE_EQUIPMENT_POOL_STAFF},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == ROLE_EQUIPMENT_POOL_STAFF

    rows = await _rows(db_session, action="update", entity_type="user")
    assert len(rows) == 1
    row = rows[0]
    assert str(row.entity_id) == target_id
    assert row.user_id == seeded_users[ROLE_ADMINISTRATOR].id
    assert row.before_data["role_name"] == ROLE_READ_ONLY
    assert row.after_data["role_name"] == ROLE_EQUIPMENT_POOL_STAFF


async def test_user_role_update_rolls_back_when_audit_write_fails(client, seeded_users, db_session, monkeypatch):
    """Roadmap PR10: a role change must be atomic with its audit row, same
    as user creation (test_user_create_rolls_back_when_audit_write_fails
    above) -- if the audit write fails, the role_id UPDATE must not persist
    either."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    target = seeded_users[ROLE_READ_ONLY]
    target_id = str(target.id)
    original_role_id = target.role_id

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr("app.core.audit.audit_crud.create", _boom)

    async with await _raw_client() as raw_client:
        resp = await raw_client.patch(
            f"/api/v1/users/{target_id}",
            headers=headers,
            json={"role_name": ROLE_EQUIPMENT_POOL_STAFF},
        )
    assert resp.status_code == 500

    await db_session.refresh(target, attribute_names=["role_id"])
    assert target.role_id == original_role_id, "a failed audit write must roll back the role change too"


# ---------------------------------------------------------------------------
# Master data: department / ward / location / category
# ---------------------------------------------------------------------------


async def test_create_department_creates_audit_row(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/departments", headers=headers, json={"code": "SURG", "name": "Surgery"}
    )
    assert resp.status_code == 201, resp.text
    dept_id = resp.json()["id"]

    rows = await _rows(db_session, action="create", entity_type="department")
    assert len(rows) == 1
    assert str(rows[0].entity_id) == dept_id
    assert rows[0].after_data == {"code": "SURG", "name": "Surgery"}


async def test_create_ward_location_category_create_audit_rows(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)

    dept_resp = await client.post(
        "/api/v1/departments", headers=headers, json={"code": "ICU", "name": "Intensive Care"}
    )
    assert dept_resp.status_code == 201
    department_id = dept_resp.json()["id"]

    ward_resp = await client.post(
        "/api/v1/wards",
        headers=headers,
        json={"code": "ICU-A", "name": "ICU Ward A", "department_id": department_id},
    )
    assert ward_resp.status_code == 201

    location_resp = await client.post(
        "/api/v1/locations", headers=headers, json={"name": "Central Store", "type": "storage"}
    )
    assert location_resp.status_code == 201

    category_resp = await client.post(
        "/api/v1/categories",
        headers=headers,
        json={"name": "Infusion Pumps", "default_pm_interval_days": 90, "default_cal_interval_days": 180},
    )
    assert category_resp.status_code == 201

    for entity_type, resp in (
        ("ward", ward_resp),
        ("location", location_resp),
        ("category", category_resp),
    ):
        rows = await _rows(db_session, action="create", entity_type=entity_type)
        assert len(rows) == 1, f"expected exactly one create audit row for {entity_type}"
        assert str(rows[0].entity_id) == resp.json()["id"]


# ---------------------------------------------------------------------------
# Equipment (already audited pre-PR3; verifying the refactor onto the shared
# record_audit_event() helper preserved behavior and added request/correlation ids)
# ---------------------------------------------------------------------------


async def test_equipment_create_audit_row_has_request_and_correlation_ids(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AUDIT-EQ-0001", "equipment_name": "Syringe Pump"},
    )
    assert resp.status_code == 201, resp.text
    equipment_id = resp.json()["id"]

    rows = await _rows(db_session, action="create", entity_type="equipment")
    assert len(rows) == 1
    row = rows[0]
    assert str(row.entity_id) == equipment_id
    assert row.request_id is not None
    assert row.correlation_id is not None


async def test_equipment_create_with_due_dates_is_json_safe(client, seeded_users, db_session):
    # payload.model_dump() (used for the ORM write) keeps native Python
    # `date` objects for pm_due_date/cal_due_date; passing that dict
    # straight through as the audit row's after_data used to crash the
    # JSON/JSONB column's serializer (TypeError: Object of type date is not
    # JSON serializable) — after the equipment row had already committed.
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={
            "asset_number": "AUDIT-EQ-DATES-0001",
            "equipment_name": "Ventilator",
            "pm_due_date": "2026-08-01",
            "cal_due_date": "2026-09-15",
        },
    )
    assert resp.status_code == 201, resp.text
    equipment_id = resp.json()["id"]
    assert resp.json()["pm_due_date"] == "2026-08-01"
    assert resp.json()["cal_due_date"] == "2026-09-15"

    from app.models.equipment import Equipment

    result = await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    assert result.scalar_one().asset_number == "AUDIT-EQ-DATES-0001"

    rows = await _rows(
        db_session, action="create", entity_type="equipment", entity_id=uuid.UUID(equipment_id)
    )
    assert len(rows) == 1, "exactly one audit row must exist"
    row = rows[0]
    # Stable, JSON-safe (ISO-format string) date values in the persisted row.
    assert row.after_data["pm_due_date"] == "2026-08-01"
    assert row.after_data["cal_due_date"] == "2026-09-15"


async def test_equipment_create_with_only_one_due_date_is_json_safe(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={
            "asset_number": "AUDIT-EQ-DATES-0002",
            "equipment_name": "Infusion Pump",
            "pm_due_date": "2027-01-01",
        },
    )
    assert resp.status_code == 201, resp.text
    equipment_id = resp.json()["id"]

    rows = await _rows(
        db_session, action="create", entity_type="equipment", entity_id=uuid.UUID(equipment_id)
    )
    assert len(rows) == 1
    assert rows[0].after_data["pm_due_date"] == "2027-01-01"
    assert rows[0].after_data["cal_due_date"] is None


async def test_equipment_update_audit_row_has_before_and_after(client, seeded_users, db_session):
    # PATCH /api/v1/equipment/{id}'s MissingGreenlet defect (see PR #7's
    # description, "Equipment MissingGreenlet fix") is now fixed at the base
    # (Equipment.__mapper_args__ = {"eager_defaults": True}, merged via PR
    # #10) — the endpoint is expected to return 200 like any other endpoint,
    # via the ordinary `client` fixture.
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AUDIT-EQ-UPD-0001", "equipment_name": "Old Name"},
    )
    assert create_resp.status_code == 201
    equipment_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/equipment/{equipment_id}",
        headers=headers,
        json={"equipment_name": "New Name"},
    )
    assert update_resp.status_code == 200, update_resp.text

    rows = await _rows(
        db_session, action="update", entity_type="equipment", entity_id=uuid.UUID(equipment_id)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == seeded_users[ROLE_ADMINISTRATOR].id
    assert row.before_data["equipment_name"] == "Old Name"
    assert row.after_data["equipment_name"] == "New Name"

    from app.models.equipment import Equipment

    result = await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    assert result.scalar_one().equipment_name == "New Name"


async def test_equipment_status_change_audit_row_has_correct_action_and_actor(client, seeded_users, db_session):
    # Same now-fixed defect as the update test above — see that test's
    # comment. This endpoint is expected to return 200.
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AUDIT-EQ-STATUS-0001", "equipment_name": "Wheelchair"},
    )
    assert create_resp.status_code == 201
    equipment_id = create_resp.json()["id"]

    status_resp = await client.post(
        f"/api/v1/equipment/{equipment_id}/status",
        headers=headers,
        json={"status": "unavailable_defective", "reason": "Needs a new wheel"},
    )
    assert status_resp.status_code == 200, status_resp.text

    rows = await _rows(
        db_session, action="status_change", entity_type="equipment", entity_id=uuid.UUID(equipment_id)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == seeded_users[ROLE_ADMINISTRATOR].id
    assert row.after_data == {"status": "unavailable_defective", "reason": "Needs a new wheel"}


async def test_no_duplicate_audit_rows_for_single_action(client, seeded_users, db_session):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AUDIT-EQ-0002", "equipment_name": "Vital Signs Monitor"},
    )
    assert resp.status_code == 201
    equipment_id = resp.json()["id"]

    rows = await _rows(
        db_session, action="create", entity_type="equipment", entity_id=uuid.UUID(equipment_id)
    )
    assert len(rows) == 1, "a single create request must produce exactly one audit row"


async def test_equipment_delete_audit_row_has_before_snapshot_and_null_after(
    client, seeded_users, db_session
):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "AUDIT-EQ-DEL-0001", "equipment_name": "Portable Ultrasound"},
    )
    assert create_resp.status_code == 201
    equipment_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/equipment/{equipment_id}", headers=headers)
    assert del_resp.status_code == 204

    rows = await _rows(
        db_session, action="delete", entity_type="equipment", entity_id=uuid.UUID(equipment_id)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.before_data is not None
    assert row.before_data["asset_number"] == "AUDIT-EQ-DEL-0001"
    assert row.after_data is None


# ---------------------------------------------------------------------------
# Atomicity: audit write failure rolls back the business operation
# ---------------------------------------------------------------------------


async def test_equipment_create_rolls_back_when_audit_write_fails(
    client, seeded_users, db_session, monkeypatch
):
    from app.models.equipment import Equipment

    # Log in (itself an audited action) before the audit write starts
    # failing, otherwise there would be no way to obtain valid credentials.
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr("app.core.audit.audit_crud.create", _boom)

    async with await _raw_client() as raw_client:
        resp = await raw_client.post(
            "/api/v1/equipment",
            headers=headers,
            json={"asset_number": "AUDITFAIL-0001", "equipment_name": "Should Not Persist"},
        )
    assert resp.status_code == 500

    result = await db_session.execute(select(Equipment).where(Equipment.asset_number == "AUDITFAIL-0001"))
    assert result.scalars().all() == [], "equipment must not persist when its audit write fails"

    rows = await _rows(db_session, entity_type="equipment")
    assert all(row.action != "create" or "AUDITFAIL" not in str(row.after_data) for row in rows)


async def test_user_create_rolls_back_when_audit_write_fails(client, seeded_users, db_session, monkeypatch):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr("app.core.audit.audit_crud.create", _boom)

    async with await _raw_client() as raw_client:
        resp = await raw_client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "employee_code": "AUDITFAILUSER",
                "full_name": "Should Not Persist",
                "email": "auditfail@mep-hospital-test.dev",
                "password": "Whatever@123",
                "role_name": ROLE_READ_ONLY,
            },
        )
    assert resp.status_code == 500

    from app.models.user import User

    result = await db_session.execute(select(User).where(User.employee_code == "AUDITFAILUSER"))
    assert result.scalars().all() == [], "user must not persist when its audit write fails"


# ---------------------------------------------------------------------------
# Admin-only read API regression
# ---------------------------------------------------------------------------


async def test_audit_log_listing_requires_admin(client, seeded_users):
    headers = await _auth_headers(client, ROLE_READ_ONLY)
    resp = await client.get("/api/v1/audit-logs", headers=headers)
    assert resp.status_code == 403


async def test_audit_log_listing_returns_request_and_correlation_ids(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    create_resp = await client.post(
        "/api/v1/departments", headers=admin_headers, json={"code": "LAB", "name": "Laboratory"}
    )
    assert create_resp.status_code == 201

    resp = await client.get(
        "/api/v1/audit-logs", headers=admin_headers, params={"entity_type": "department"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert "request_id" in body[0]
    assert "correlation_id" in body[0]


async def test_audit_log_listing_limit_is_bounded(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/audit-logs", headers=headers, params={"limit": 100000})
    assert resp.status_code == 422, "an unbounded limit must be rejected, not silently accepted"


async def test_audit_log_listing_limit_must_be_at_least_one(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    for bad_limit in (0, -1):
        resp = await client.get("/api/v1/audit-logs", headers=headers, params={"limit": bad_limit})
        assert resp.status_code == 422, f"limit={bad_limit} must be rejected, not treated as 'no results'"


async def test_audit_log_listing_ordering_is_deterministic(client, seeded_users):
    """Same query, called twice with no state change in between, must
    return rows in the same order — proves the tiebreaker (id) makes
    ordering stable even when multiple rows share a created_at value."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    for i in range(4):
        resp = await client.post(
            "/api/v1/departments", headers=headers, json={"code": f"ORD{i}", "name": f"Order Dept {i}"}
        )
        assert resp.status_code == 201

    first = await client.get(
        "/api/v1/audit-logs", headers=headers, params={"entity_type": "department", "limit": 50}
    )
    second = await client.get(
        "/api/v1/audit-logs", headers=headers, params={"entity_type": "department", "limit": 50}
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert [row["id"] for row in first.json()] == [row["id"] for row in second.json()]


async def test_audit_log_listing_supports_offset_pagination(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    for i in range(3):
        resp = await client.post(
            "/api/v1/departments", headers=headers, json={"code": f"PG{i}", "name": f"Page Dept {i}"}
        )
        assert resp.status_code == 201

    page_1 = await client.get(
        "/api/v1/audit-logs",
        headers=headers,
        params={"entity_type": "department", "limit": 2, "offset": 0},
    )
    page_2 = await client.get(
        "/api/v1/audit-logs",
        headers=headers,
        params={"entity_type": "department", "limit": 2, "offset": 2},
    )
    assert page_1.status_code == 200
    assert page_2.status_code == 200
    ids_page_1 = {row["id"] for row in page_1.json()}
    ids_page_2 = {row["id"] for row in page_2.json()}
    assert ids_page_1.isdisjoint(ids_page_2), "paginated pages must not overlap"
