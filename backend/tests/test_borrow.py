import uuid

import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _auth_headers(client, role="admin"):
    identifier = f"{role.upper()}001"
    token = await login(client, identifier)
    return {"Authorization": f"Bearer {token}"}


async def _create_equipment(client, headers, asset_number="AST-1001", name="Infusion Pump"):
    resp = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": asset_number, "equipment_name": name}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_borrow_then_return_flow(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    nurse_headers = await _auth_headers(client, "ward_nurse")

    equipment = await _create_equipment(client, admin_headers)

    borrow_resp = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Nurse Somying"},
    )
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx = borrow_resp.json()
    assert tx["equipment"]["status"] == "borrowed"

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp.json()["status"] == "borrowed"

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"condition": "available"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["status"] == "returned"

    check_resp2 = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp2.json()["status"] == "available"


async def test_cannot_borrow_unavailable_equipment(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    nurse_headers = await _auth_headers(client, "ward_nurse")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-1002")

    first = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Nurse A"},
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Nurse B"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "EQUIPMENT_NOT_AVAILABLE"


async def test_unique_active_borrow_db_constraint(db_session):
    """The DB-level partial unique index (idx_tx_one_active_borrow) is the real guard
    against a double-borrow race — two concurrent requests both passing the
    Available check would otherwise both insert a 'borrowed' row. This exercises
    that constraint directly at the model layer, independent of HTTP concurrency
    (which SQLite's single test connection can't safely simulate)."""
    from sqlalchemy.exc import IntegrityError

    from app.models.equipment import Equipment
    from app.models.transaction import BorrowTransaction
    from app.services.qr_service import build_qr_value

    equipment = Equipment(
        asset_number="AST-1003", equipment_name="Ventilator", qr_code_value=build_qr_value("AST-1003")
    )
    db_session.add(equipment)
    await db_session.flush()

    db_session.add(
        BorrowTransaction(transaction_no="TX-TEST-0001", equipment_id=equipment.id, borrower_name="Nurse A")
    )
    await db_session.flush()

    db_session.add(
        BorrowTransaction(transaction_no="TX-TEST-0002", equipment_id=equipment.id, borrower_name="Nurse B")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_viewer_cannot_borrow(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    viewer_headers = await _auth_headers(client, "viewer")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-1004")

    resp = await client.post(
        "/api/v1/borrow",
        headers=viewer_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Someone"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PR4: transaction-number generation (docs/kickoffs/PR4-architecture-kickoff.md,
# squash commit 91b23b62d864edadb430d1f4335c6b77e59222f0). These exercise the
# API contract and audit behavior via the ordinary SQLite-backed `client`
# fixture, which drives generate_transaction_no()'s SQLite-only compatibility
# fallback (Owner Decision 1) — NOT the real PostgreSQL sequence. They prove
# the response/audit *shape* is unchanged and format-compliant; they are not,
# and must never be read as, evidence of PostgreSQL concurrency-safety — that
# is proven only in tests/test_postgres_integration.py.
# ---------------------------------------------------------------------------


async def test_transaction_no_is_padded_to_at_least_eight_digits(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR4-0001")

    resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Nurse Pad"},
    )
    assert resp.status_code == 201, resp.text
    tx = resp.json()

    # Existing response shape unchanged: transaction_no is still a plain
    # string field at the same position, in the same TX-{date}-{suffix}
    # textual shape existing clients already parse/display.
    transaction_no = tx["transaction_no"]
    prefix, date_part, suffix = transaction_no.split("-")
    assert prefix == "TX"
    assert len(date_part) == 8 and date_part.isdigit()
    assert suffix.isdigit()
    assert len(suffix) >= 8, f"suffix {suffix!r} is narrower than the 8-digit minimum (Owner Decision 2)"


async def test_borrow_creates_exactly_one_audit_row_matching_transaction_no(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.audit import AuditLog

    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR4-0002")

    resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={"equipment_qr": equipment["qr_code_value"], "borrower_name": "Nurse Audit"},
    )
    assert resp.status_code == 201, resp.text
    tx = resp.json()

    rows = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "borrow",
                AuditLog.entity_type == "borrow_transaction",
                AuditLog.entity_id == uuid.UUID(tx["id"]),
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].after_data["transaction_no"] == tx["transaction_no"]


# ---------------------------------------------------------------------------
# PR4-D1 (independent review, PR #13): generate_transaction_no() must select
# its implementation only among the two explicitly supported dialects —
# PostgreSQL (real sequence) and SQLite (the isolated, non-concurrency-safe
# compatibility fallback below) — and fail closed, not silently reuse the
# SQLite fallback, for anything else.
# ---------------------------------------------------------------------------


async def test_generate_transaction_no_uses_sqlite_fallback_for_sqlite_dialect(db_session):
    from app.crud import transaction as transaction_crud

    assert db_session.get_bind().dialect.name == "sqlite"

    value = await transaction_crud.generate_transaction_no(db_session)
    prefix, date_part, suffix = value.split("-")
    assert prefix == "TX"
    assert len(date_part) == 8 and date_part.isdigit()
    assert suffix.isdigit() and len(suffix) >= 8


async def test_generate_transaction_no_fails_closed_for_unsupported_dialect(db_session, monkeypatch):
    from app.crud import transaction as transaction_crud

    class _FakeDialect:
        name = "mysql"

    class _FakeBind:
        dialect = _FakeDialect()

    # Any dialect other than postgresql/sqlite must never reach either
    # generator implementation -- it must raise before either branch runs.
    monkeypatch.setattr(db_session, "get_bind", lambda *args, **kwargs: _FakeBind())

    with pytest.raises(transaction_crud.UnsupportedDatabaseDialectError):
        await transaction_crud.generate_transaction_no(db_session)
