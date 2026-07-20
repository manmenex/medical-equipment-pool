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
        json={"equipment_id": equipment["id"], "borrower_name": "Nurse Somying"},
    )
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx = borrow_resp.json()
    assert tx["equipment"]["status"] == "issued_to_ward"

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp.json()["status"] == "issued_to_ward"

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"condition": "available"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["status"] == "closed"

    check_resp2 = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp2.json()["status"] == "available_at_pool"


async def test_cannot_borrow_unavailable_equipment(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    nurse_headers = await _auth_headers(client, "ward_nurse")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-1002")

    first = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_id": equipment["id"], "borrower_name": "Nurse A"},
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/borrow",
        headers=nurse_headers,
        json={"equipment_id": equipment["id"], "borrower_name": "Nurse B"},
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

    equipment = Equipment(asset_number="AST-1003", equipment_name="Ventilator")
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
        json={"equipment_id": equipment["id"], "borrower_name": "Someone"},
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
        json={"equipment_id": equipment["id"], "borrower_name": "Nurse Pad"},
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
        json={"equipment_id": equipment["id"], "borrower_name": "Nurse Audit"},
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


# ---------------------------------------------------------------------------
# Roadmap PR7 (knowledge/adr/ADR-005-transaction-model.md): the transaction
# domain model's two-state OPEN/CLOSED lifecycle -- repository (app.crud.
# transaction), service (app.services.borrow_service), and migration
# 0007_transaction_lifecycle.py's PostgreSQL evidence lives in
# tests/test_postgres_integration.py. These exercise the lifecycle via the
# SQLite-backed suite.
# ---------------------------------------------------------------------------


async def test_new_dispatch_opens_a_transaction_with_status_open(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7-0001")

    resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={"equipment_id": equipment["id"], "borrower_name": "Nurse Open"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "open"


async def test_receipt_closes_the_transaction_and_records_outcome(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7-0002")

    borrow_resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={"equipment_id": equipment["id"], "borrower_name": "Nurse Close"},
    )
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx_id = borrow_resp.json()["id"]

    return_resp = await client.post(
        f"/api/v1/return/{tx_id}", headers=admin_headers, json={"condition": "available", "notes": "all good"}
    )
    assert return_resp.status_code == 200, return_resp.text
    tx = return_resp.json()
    assert tx["status"] == "closed"


async def test_closing_an_already_closed_transaction_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7-0003")

    borrow_resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={"equipment_id": equipment["id"], "borrower_name": "Nurse Twice"},
    )
    tx_id = borrow_resp.json()["id"]

    first = await client.post(f"/api/v1/return/{tx_id}", headers=admin_headers, json={"condition": "available"})
    assert first.status_code == 200, first.text

    second = await client.post(f"/api/v1/return/{tx_id}", headers=admin_headers, json={"condition": "available"})
    assert second.status_code == 409
    assert second.json()["code"] == "TRANSACTION_ALREADY_RETURNED"


async def test_repository_close_sets_closed_status_and_receipt_fields(db_session):
    """Repository-level (app.crud.transaction) proof, independent of the
    HTTP layer: close() is the only path that may set
    TransactionStatus.CLOSED, and it records returned_at/condition_on_return/
    received_by_user_id/notes together."""
    from app.crud import transaction as transaction_crud
    from app.models.equipment import Equipment
    from app.models.transaction import BorrowTransaction, TransactionStatus

    equipment = Equipment(asset_number="AST-PR7-0004", equipment_name="Pump")
    db_session.add(equipment)
    await db_session.flush()

    tx = BorrowTransaction(transaction_no="TX-PR7-0004", equipment_id=equipment.id, borrower_name="Nurse Repo")
    db_session.add(tx)
    await db_session.flush()
    assert tx.status == TransactionStatus.OPEN, "create() must rely on the OPEN column default"

    receiver_id = uuid.uuid4()
    await transaction_crud.close(
        db_session, tx, received_by_user_id=receiver_id, condition_on_return="available", notes="checked in"
    )

    assert tx.status == TransactionStatus.CLOSED
    assert tx.returned_at is not None
    assert tx.condition_on_return == "available"
    assert tx.received_by_user_id == receiver_id
    assert "checked in" in tx.notes


async def test_repository_get_open_transaction_for_equipment(db_session):
    from app.crud import transaction as transaction_crud
    from app.models.equipment import Equipment
    from app.models.transaction import BorrowTransaction, TransactionStatus

    equipment = Equipment(asset_number="AST-PR7-0005", equipment_name="Pump")
    db_session.add(equipment)
    await db_session.flush()

    assert await transaction_crud.get_open_transaction_for_equipment(db_session, equipment.id) is None

    tx = BorrowTransaction(transaction_no="TX-PR7-0005", equipment_id=equipment.id, borrower_name="Nurse Lookup")
    db_session.add(tx)
    await db_session.flush()

    found = await transaction_crud.get_open_transaction_for_equipment(db_session, equipment.id)
    assert found is not None
    assert found.id == tx.id

    await transaction_crud.close(db_session, tx, received_by_user_id=None, condition_on_return="available", notes=None)
    await db_session.flush()

    assert await transaction_crud.get_open_transaction_for_equipment(db_session, equipment.id) is None


async def test_scheduler_overdue_check_notifies_but_does_not_write_a_third_status(db_session, monkeypatch):
    """Roadmap PR7: the lifecycle has exactly two states. An overdue
    transaction must remain OPEN -- app.worker.scheduler.check_overdue_returns
    must notify engineers without writing a status value outside
    {open, closed}."""
    from datetime import datetime, timedelta

    from app.models.equipment import Equipment
    from app.models.transaction import BorrowTransaction, TransactionStatus
    from app.worker import scheduler

    equipment = Equipment(asset_number="AST-PR7-0006", equipment_name="Pump")
    db_session.add(equipment)
    await db_session.flush()

    tx = BorrowTransaction(
        transaction_no="TX-PR7-0006",
        equipment_id=equipment.id,
        borrower_name="Nurse Overdue",
        due_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.add(tx)
    await db_session.commit()

    class _SessionCtx:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: _SessionCtx())

    async def _fake_notify(db, title, body, notif_type):
        assert notif_type == "overdue"

    monkeypatch.setattr(scheduler, "_notify_engineers", _fake_notify)

    await scheduler.check_overdue_returns()

    await db_session.refresh(tx)
    assert tx.status == TransactionStatus.OPEN, "overdue transactions remain OPEN -- 'overdue' is not a status"
