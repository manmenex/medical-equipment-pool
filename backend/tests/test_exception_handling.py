import logging

import pytest
from sqlalchemy import select

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio


def _assert_safe_envelope(body: dict, expected_status: int):
    assert set(body.keys()) == {"detail", "code", "status"}
    assert body["status"] == expected_status
    assert isinstance(body["detail"], str)
    assert isinstance(body["code"], str)
    assert body["code"] == body["code"].upper()
    forbidden_substrings = [
        "Traceback",
        "sqlite3",
        "asyncpg",
        "psycopg",
        "UNIQUE constraint",
        "IntegrityError",
        "File \"",
        "  File ",
        ".py\", line",
    ]
    for needle in forbidden_substrings:
        assert needle not in body["detail"], f"leaked internal detail: {needle!r} in {body['detail']!r}"


# ---------------------------------------------------------------------------
# Duplicate resources
# ---------------------------------------------------------------------------


async def test_duplicate_department_code_returns_409(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    payload = {"code": "CARD", "name": "Cardiology"}
    first = await client.post("/api/v1/departments", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/departments", headers=headers, json={"code": "CARD", "name": "Cardiology Duplicate"}
    )
    assert second.status_code == 409
    body = second.json()
    _assert_safe_envelope(body, 409)
    assert body["code"] == "DUPLICATE"


async def test_duplicate_ward_code_returns_409(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    dept = await client.post("/api/v1/departments", headers=headers, json={"code": "SURG", "name": "Surgery"})
    assert dept.status_code == 201, dept.text

    payload = {"code": "W-100", "name": "Ward 100", "department_id": dept.json()["id"]}
    first = await client.post("/api/v1/wards", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/wards", headers=headers, json=payload)
    assert second.status_code == 409
    _assert_safe_envelope(second.json(), 409)


async def test_ward_with_nonexistent_department_returns_400_not_500(client, seeded_users):
    """Corrected in the PR2 review round: a bad department_id is now caught
    by a pre-flush existence check (app.core.references), which works
    identically regardless of whether the underlying database enforces FK
    constraints — this is what makes the case deterministically testable
    under the SQLite test database, which does not enforce FKs itself."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    fake_department_id = "00000000-0000-0000-0000-000000000000"
    resp = await client.post(
        "/api/v1/wards",
        headers=headers,
        json={"code": "W-999", "name": "Ghost Ward", "department_id": fake_department_id},
    )
    assert resp.status_code == 400
    body = resp.json()
    _assert_safe_envelope(body, 400)
    assert body["code"] == "INVALID_INPUT"


async def test_duplicate_category_name_returns_409(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    payload = {"name": "Infusion Pumps"}
    first = await client.post("/api/v1/categories", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/categories", headers=headers, json=payload)
    assert second.status_code == 409
    _assert_safe_envelope(second.json(), 409)


async def test_duplicate_user_employee_code_returns_409(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    payload = {
        "employee_code": f"{ROLE_ADMINISTRATOR.upper()}001",  # already used by the seeded admin user
        "full_name": "Someone Else",
        "email": "someone-else@mep-hospital-test.dev",
        "password": "Password@123",
        "role_name": ROLE_READ_ONLY,
    }
    resp = await client.post("/api/v1/users", headers=headers, json=payload)
    assert resp.status_code == 409
    body = resp.json()
    _assert_safe_envelope(body, 409)
    assert body["code"] == "DUPLICATE"


async def test_duplicate_equipment_asset_number_returns_409(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    payload = {"asset_number": "DUP-0001", "equipment_name": "Syringe Pump"}
    first = await client.post("/api/v1/equipment", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    second = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": "DUP-0001", "equipment_name": "Different Name"}
    )
    assert second.status_code == 409
    body = second.json()
    _assert_safe_envelope(body, 409)
    assert body["code"] == "DUPLICATE"


async def test_location_create_has_no_duplicate_protection_known_limitation(client, seeded_users):
    """Location has no unique constraint in the current schema, so creating the
    same location twice succeeds both times — documented as a known PR2
    limitation, not a bug: enforcing uniqueness here would require a schema
    migration, which is out of scope for this PR."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    payload = {"name": "Central Store", "type": "storage"}
    first = await client.post("/api/v1/locations", headers=headers, json=payload)
    second = await client.post("/api/v1/locations", headers=headers, json=payload)
    assert first.status_code == 201
    assert second.status_code == 201


# ---------------------------------------------------------------------------
# Invalid input
# ---------------------------------------------------------------------------


async def test_malformed_department_id_query_param_returns_400(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/equipment", headers=headers, params={"department_id": "not-a-uuid"})
    assert resp.status_code == 400
    body = resp.json()
    _assert_safe_envelope(body, 400)
    assert body["code"] == "INVALID_INPUT"


async def test_malformed_transaction_ward_id_query_param_returns_400(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/transactions", headers=headers, params={"ward_id": "garbage"})
    assert resp.status_code == 400
    _assert_safe_envelope(resp.json(), 400)


async def test_unknown_role_on_create_user_returns_422(client, seeded_users):
    """Roadmap PR10: role_name is now a closed Literal (RoleName) at the
    schema layer, so an unrecognized role is rejected by Pydantic/FastAPI
    request validation (422 VALIDATION_ERROR) before the handler body --
    and its runtime get_role_by_name lookup -- ever runs. This is a
    behavior change from the pre-PR10 400 INVALID_INPUT (the runtime
    lookup is retained as a defensive fallback, but is no longer reachable
    via this endpoint for an unrecognized role_name)."""
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "employee_code": "NEWUSR001",
            "full_name": "New User",
            "email": "new-user@mep-hospital-test.dev",
            "password": "Password@123",
            "role_name": "not_a_real_role",
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"


async def test_update_nonexistent_user_returns_404(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000", headers=headers, json={"full_name": "Nobody"}
    )
    assert resp.status_code == 404
    body = resp.json()
    _assert_safe_envelope(body, 404)
    assert body["code"] == "RESOURCE_NOT_FOUND"


async def test_unknown_receipt_outcome_returns_422_not_500(client, seeded_users):
    """Roadmap PR8B: receipt_outcome is a typed ReceiptOutcome enum, so an
    unrecognized value is caught by Pydantic/FastAPI request validation
    (422 VALIDATION_ERROR) before app.services.borrow_service ever runs --
    not the pre-PR8B 400 INVALID_INPUT a free-form condition string needed
    a runtime dict-lookup miss to detect, and never a 500."""
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)

    eq_resp = await client.post(
        "/api/v1/equipment", headers=admin_headers, json={"asset_number": "COND-0001", "equipment_name": "Monitor"}
    )
    assert eq_resp.status_code == 201
    equipment = eq_resp.json()

    ward_id = await _create_ward(client, admin_headers, code="W-COND-0001")
    borrow_resp = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_id": equipment["id"], "ward_id": ward_id, "dispatch_type": "on_demand"},
    )
    assert borrow_resp.status_code == 201
    tx = borrow_resp.json()

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"receipt_outcome": "not-a-real-outcome"}
    )
    assert return_resp.status_code == 422
    body = return_resp.json()
    # A 422 body includes an additional `errors` array beyond the base
    # {detail, code, status} envelope (docs/api/ERROR_CODES.md) --
    # _assert_safe_envelope's exact-key-set check does not apply here.
    assert body["status"] == 422
    assert body["code"] == "VALIDATION_ERROR"
    assert isinstance(body["detail"], str)
    assert "Traceback" not in body["detail"]


async def test_malformed_equipment_id_in_borrow_returns_400_not_500(client, seeded_users):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    nurse_headers = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin_headers, code="W-MALFORMED-0001")
    resp = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_id": "not-a-uuid", "ward_id": ward_id, "dispatch_type": "on_demand"},
    )
    assert resp.status_code == 400
    _assert_safe_envelope(resp.json(), 400)


# ---------------------------------------------------------------------------
# Transaction / rollback safety
# ---------------------------------------------------------------------------


async def test_rollback_after_duplicate_department_leaves_session_usable(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    payload = {"code": "ROLLBACK1", "name": "First"}
    first = await client.post("/api/v1/departments", headers=headers, json=payload)
    assert first.status_code == 201

    duplicate = await client.post("/api/v1/departments", headers=headers, json=payload)
    assert duplicate.status_code == 409

    # The session used to serve the failed request must not be left broken —
    # an unrelated, well-formed request right after it must succeed normally.
    retry = await client.post("/api/v1/departments", headers=headers, json={"code": "ROLLBACK2", "name": "Second"})
    assert retry.status_code == 201, retry.text

    listing = await client.get("/api/v1/departments", headers=headers)
    assert listing.status_code == 200
    codes = {d["code"] for d in listing.json()}
    assert {"ROLLBACK1", "ROLLBACK2"} <= codes


async def test_no_partial_row_remains_after_duplicate_equipment_failure(client, seeded_users, db_session):
    from app.models.equipment import Equipment

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    payload = {"asset_number": "NOPARTIAL-0001", "equipment_name": "Ultrasound"}
    first = await client.post("/api/v1/equipment", headers=headers, json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/equipment", headers=headers, json=payload)
    assert second.status_code == 409

    result = await db_session.execute(select(Equipment).where(Equipment.asset_number == "NOPARTIAL-0001"))
    rows = result.scalars().all()
    assert len(rows) == 1, "duplicate-create attempt must not leave a second/partial row behind"


async def test_no_audit_log_entry_created_for_failed_duplicate_equipment(client, seeded_users, db_session):
    from app.models.audit import AuditLog

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    payload = {"asset_number": "NOAUDIT-0001", "equipment_name": "X-Ray"}
    first = await client.post("/api/v1/equipment", headers=headers, json=payload)
    assert first.status_code == 201

    before = await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "equipment"))
    count_before = len(before.scalars().all())

    second = await client.post("/api/v1/equipment", headers=headers, json=payload)
    assert second.status_code == 409

    after = await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "equipment"))
    count_after = len(after.scalars().all())
    assert count_after == count_before, "a failed create must not produce an audit entry for it"


async def test_existing_successful_paths_still_work_after_exception_handling_changes(client, seeded_users):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": "OK-0001", "equipment_name": "Working Pump"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "available_at_pool"
    assert "qr_code_value" not in body


# ---------------------------------------------------------------------------
# Unexpected (non-domain) errors
# ---------------------------------------------------------------------------


async def _raw_client():
    """A second client for the same app, sharing whatever dependency_overrides
    the `client` fixture already installed, but with raise_app_exceptions=False.

    Starlette's ServerErrorMiddleware always re-raises after sending a 500
    response (so real ASGI servers can log it) — httpx's ASGITransport
    re-raises that into the caller by default, which would make these tests
    fail on the exception itself instead of letting us inspect the response
    it already sent. Production servers (uvicorn etc.) don't have this
    behavior; it's a test-transport-only quirk.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_unexpected_exception_returns_safe_generic_envelope_not_traceback(client, seeded_users, monkeypatch):
    from app.api.v1 import equipment as equipment_module

    async def boom(*_args, **_kwargs):
        raise RuntimeError("super secret internal detail that must never reach the client")

    monkeypatch.setattr(equipment_module.equipment_crud, "search", boom)

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    async with await _raw_client() as raw_client:
        resp = await raw_client.get("/api/v1/equipment", headers=headers)

    assert resp.status_code == 500
    body = resp.json()
    _assert_safe_envelope(body, 500)
    assert body["code"] == "INTERNAL_ERROR"
    assert "super secret internal detail" not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text


async def test_unexpected_exception_is_logged_server_side(client, seeded_users, monkeypatch, caplog):
    from app.api.v1 import equipment as equipment_module

    async def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(equipment_module.equipment_crud, "search", boom)

    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    with caplog.at_level(logging.ERROR, logger="app.main"):
        async with await _raw_client() as raw_client:
            resp = await raw_client.get("/api/v1/equipment", headers=headers)

    assert resp.status_code == 500
    assert any("Unhandled exception" in r.message for r in caplog.records)


async def test_handled_domain_error_does_not_log_a_full_traceback(client, seeded_users, caplog):
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    with caplog.at_level(logging.INFO, logger="app.main"):
        resp = await client.get("/api/v1/equipment", headers=headers, params={"department_id": "bad-uuid"})

    assert resp.status_code == 400
    info_records = [r for r in caplog.records if r.name == "app.main"]
    assert info_records, "expected a handled-error log record"
    for record in info_records:
        assert record.exc_info is None, "handled application errors must not log a stack trace"


# ---------------------------------------------------------------------------
# Audit-write failure atomicity (PR2 review round)
# ---------------------------------------------------------------------------


async def test_audit_write_failure_after_flush_leaves_no_equipment_or_audit_row(
    client, seeded_users, db_engine, monkeypatch
):
    """Simulates the audit-log INSERT itself failing *after* the business row
    (equipment) has already been flushed within the same request/session, via
    the real POST /api/v1/equipment endpoint (not a standalone helper) — the
    actual API/service transaction boundary. Since db.commit() is only ever
    called once, after both writes succeed, an audit-log failure here must
    roll back the equipment row too.

    Verifies, in order: the client gets a safe generic envelope with no
    trace of the injected exception; the request's own session was rolled
    back and/or disposed (not merely inferred — the AsyncSession methods
    that do this are tracked directly); a fresh session opened afterward
    sees neither the equipment row nor an audit row; and a completely
    ordinary follow-up request still succeeds through a fresh session,
    proving the failure didn't leave the database or connection unusable."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.crud import audit as audit_crud_module
    from app.models.audit import AuditLog
    from app.models.equipment import Equipment

    injected_marker = "simulated audit-log write failure — must never reach the client"

    # Log in (itself an audited action as of PR3) before the audit write
    # starts failing, otherwise there would be no way to obtain credentials.
    headers = await _auth_headers(client, ROLE_ADMINISTRATOR)

    async def failing_audit_create(*_args, **_kwargs):
        raise RuntimeError(injected_marker)

    # record_audit_event() (app.core.audit) is now the single call site every
    # endpoint goes through, but it still bottoms out in this one crud
    # function — patching it here exercises the real, current code path.
    monkeypatch.setattr(audit_crud_module, "create", failing_audit_create)

    # Track every AsyncSession close()/rollback() call for the duration of
    # this test, so "the request's session was rolled back or safely
    # disposed" is a direct observation, not an inference from side effects.
    closed_sessions: list[AsyncSession] = []
    rolled_back_sessions: list[AsyncSession] = []
    original_close = AsyncSession.close
    original_rollback = AsyncSession.rollback

    async def tracking_close(self):
        closed_sessions.append(self)
        await original_close(self)

    async def tracking_rollback(self):
        rolled_back_sessions.append(self)
        await original_rollback(self)

    monkeypatch.setattr(AsyncSession, "close", tracking_close)
    monkeypatch.setattr(AsyncSession, "rollback", tracking_rollback)

    async with await _raw_client() as raw_client:
        resp = await raw_client.post(
            "/api/v1/equipment",
            headers=headers,
            json={"asset_number": "ATOMIC-0001", "equipment_name": "Syringe Pump"},
        )

    # 1. Safe error envelope — no raw exception text or stack trace.
    assert resp.status_code == 500
    body = resp.json()
    _assert_safe_envelope(body, 500)
    assert body["code"] == "INTERNAL_ERROR"
    assert injected_marker not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text
    assert "audit_crud" not in resp.text

    # 2. The request's session was rolled back or safely disposed — not
    # just assumed from the context-manager contract, but observed.
    assert closed_sessions or rolled_back_sessions, (
        "expected the request's session to be closed and/or rolled back after the failure"
    )

    # 3. No business row and no audit row from the failed request, seen
    # from a completely fresh session/connection.
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as fresh_session:
        equipment_rows = (
            await fresh_session.execute(select(Equipment).where(Equipment.asset_number == "ATOMIC-0001"))
        ).scalars().all()
        audit_rows = (
            await fresh_session.execute(select(AuditLog).where(AuditLog.entity_type == "equipment"))
        ).scalars().all()

    assert equipment_rows == [], "equipment row must not survive an audit-write failure in the same request"
    assert audit_rows == [], "no partial/successful audit row should exist either"

    # 4. A subsequent, ordinary request (audit-log creation no longer
    # failing) succeeds through a fresh session — the earlier failure left
    # nothing broken behind it.
    monkeypatch.undo()
    retry = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "ATOMIC-0002", "equipment_name": "Syringe Pump Retry"},
    )
    assert retry.status_code == 201, retry.text
