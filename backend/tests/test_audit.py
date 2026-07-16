import uuid

import pytest
from sqlalchemy import select

from app.core.audit import redact_sensitive
from app.models.audit import AuditLog
from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _auth_headers(client, role="admin"):
    identifier = f"{role.upper()}001"
    token = await login(client, identifier)
    return {"Authorization": f"Bearer {token}"}


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
        json={"identifier": "ADMIN001", "password": "Password@123"},
    )
    assert resp.status_code == 200
    assert resp.headers["x-correlation-id"] == "corr-login-success"
    assert "x-request-id" in resp.headers

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == seeded_users["admin"].id
    assert row.correlation_id == "corr-login-success"
    assert row.request_id is not None


async def test_oversized_inbound_request_id_is_rejected_not_persisted_raw(client, seeded_users, db_session):
    # audit_logs.request_id/correlation_id are String(64) on PostgreSQL — an
    # inbound header longer than that must never reach the INSERT as-is.
    oversized = "x" * 500
    resp = await client.post(
        "/api/v1/auth/login",
        headers={"X-Request-ID": oversized, "X-Correlation-ID": oversized},
        json={"identifier": "ADMIN001", "password": "Password@123"},
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
        json={"identifier": "ADMIN001", "password": "Password@123"},
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
        json={"identifier": "ADMIN001", "password": "Password@123"},
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
        json={"identifier": "ADMIN001", "password": "Password@123"},
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
        json={"identifier": "ADMIN001", "password": "Password@123"},
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
        "/api/v1/auth/login", json={"identifier": "ADMIN001", "password": "wrong-password"}
    )
    assert resp.status_code == 401

    rows = await _rows(db_session, action="login_failure", entity_type="auth")
    assert len(rows) == 1
    # Per ADR-0001: the actor is never the authentication target, even for
    # a known account — only the *subject* (entity_id) may reference it.
    assert rows[0].user_id is None
    assert rows[0].entity_id == seeded_users["admin"].id
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
        "/api/v1/auth/login", json={"identifier": "ADMIN001", "password": "Password@123"}
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()

    rows = await _rows(db_session, action="login_success", entity_type="auth")
    assert rows == [], "the failed audit write should have rolled back to its savepoint, not persisted"


async def test_logout_creates_audit_row(client, seeded_users, db_session):
    headers = await _auth_headers(client, "admin")
    resp = await client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200

    rows = await _rows(db_session, action="logout", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].user_id == seeded_users["admin"].id


async def test_refresh_creates_audit_row(client, seeded_users, db_session):
    login_resp = await client.post(
        "/api/v1/auth/login", json={"identifier": "ADMIN001", "password": "Password@123"}
    )
    assert login_resp.status_code == 200

    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200

    rows = await _rows(db_session, action="token_refresh", entity_type="auth")
    assert len(rows) == 1
    assert rows[0].user_id == seeded_users["admin"].id


# ---------------------------------------------------------------------------
# Master data: users (including password reset/change masking)
# ---------------------------------------------------------------------------


async def test_create_user_masks_password_in_audit(client, seeded_users, db_session):
    headers = await _auth_headers(client, "admin")
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "employee_code": "NEWUSER01",
            "full_name": "New Person",
            "email": "new.person@mep-hospital-test.dev",
            "password": "SuperSecret@123",
            "role_name": "viewer",
        },
    )
    assert resp.status_code == 201, resp.text
    new_user_id = resp.json()["id"]

    rows = await _rows(db_session, action="create", entity_type="user")
    assert len(rows) == 1
    row = rows[0]
    assert str(row.entity_id) == new_user_id
    assert row.user_id == seeded_users["admin"].id
    assert row.after_data["password"] == "***REDACTED***"
    assert "SuperSecret@123" not in str(row.after_data)
    assert row.after_data["employee_code"] == "NEWUSER01"


async def test_update_user_password_change_masks_password_and_records_before_after(
    client, seeded_users, db_session
):
    headers = await _auth_headers(client, "admin")
    target_id = str(seeded_users["viewer"].id)

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
    assert row.user_id == seeded_users["admin"].id
    assert row.after_data["password"] == "***REDACTED***"
    assert "BrandNewPassword@123" not in str(row.after_data)
    assert row.before_data["password_hash"] == "***REDACTED***"
    assert row.before_data["is_active"] is True
    assert row.after_data["is_active"] is False


# ---------------------------------------------------------------------------
# Master data: department / ward / location / category
# ---------------------------------------------------------------------------


async def test_create_department_creates_audit_row(client, seeded_users, db_session):
    headers = await _auth_headers(client, "admin")
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
    headers = await _auth_headers(client, "admin")

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
    headers = await _auth_headers(client, "admin")
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


async def test_equipment_update_audit_row_has_before_and_after(client, seeded_users, db_session):
    # PATCH /api/v1/equipment/{id} previously returned a spurious 500 after
    # the update had already committed (MissingGreenlet — see
    # Equipment.__mapper_args__["eager_defaults"] in app/models/equipment.py
    # and its dedicated fix/regression tests in test_equipment.py). Now that
    # it's fixed, this must be a strict 200, not a tolerated 500.
    headers = await _auth_headers(client, "admin")
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
    assert update_resp.json()["equipment_name"] == "New Name"

    rows = await _rows(
        db_session, action="update", entity_type="equipment", entity_id=uuid.UUID(equipment_id)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == seeded_users["admin"].id
    assert row.before_data["equipment_name"] == "Old Name"
    assert row.after_data["equipment_name"] == "New Name"

    from app.models.equipment import Equipment

    result = await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))
    assert result.scalar_one().equipment_name == "New Name"


async def test_equipment_status_change_audit_row_has_correct_action_and_actor(client, seeded_users, db_session):
    # Same MissingGreenlet fix as the update test above — must be a strict
    # 200 now, not a tolerated 500.
    headers = await _auth_headers(client, "admin")
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
        json={"status": "repair", "reason": "Needs a new wheel"},
    )
    assert status_resp.status_code == 200, status_resp.text
    assert status_resp.json()["status"] == "repair"

    rows = await _rows(
        db_session, action="status_change", entity_type="equipment", entity_id=uuid.UUID(equipment_id)
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == seeded_users["admin"].id
    assert row.after_data == {"status": "repair", "reason": "Needs a new wheel"}


async def test_no_duplicate_audit_rows_for_single_action(client, seeded_users, db_session):
    headers = await _auth_headers(client, "admin")
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
    headers = await _auth_headers(client, "admin")
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
    headers = await _auth_headers(client, "admin")

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
    headers = await _auth_headers(client, "admin")

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
                "role_name": "viewer",
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
    headers = await _auth_headers(client, "viewer")
    resp = await client.get("/api/v1/audit-logs", headers=headers)
    assert resp.status_code == 403


async def test_audit_log_listing_returns_request_and_correlation_ids(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
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
    headers = await _auth_headers(client, "admin")
    resp = await client.get("/api/v1/audit-logs", headers=headers, params={"limit": 100000})
    assert resp.status_code == 422, "an unbounded limit must be rejected, not silently accepted"


async def test_audit_log_listing_limit_must_be_at_least_one(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    for bad_limit in (0, -1):
        resp = await client.get("/api/v1/audit-logs", headers=headers, params={"limit": bad_limit})
        assert resp.status_code == 422, f"limit={bad_limit} must be rejected, not treated as 'no results'"


async def test_audit_log_listing_ordering_is_deterministic(client, seeded_users):
    """Same query, called twice with no state change in between, must
    return rows in the same order — proves the tiebreaker (id) makes
    ordering stable even when multiple rows share a created_at value."""
    headers = await _auth_headers(client, "admin")
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
    headers = await _auth_headers(client, "admin")
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
