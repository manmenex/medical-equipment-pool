import uuid

import pytest

from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward
from tests.conftest import on_demand_borrow_payload as _on_demand_borrow_payload

pytestmark = pytest.mark.asyncio


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
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-FLOW")

    borrow_resp = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx = borrow_resp.json()
    assert tx["equipment"]["status"] == "issued_to_ward"

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp.json()["status"] == "issued_to_ward"

    return_resp = await client.post(
        f"/api/v1/return/{tx['id']}", headers=nurse_headers, json={"receipt_outcome": "usable"}
    )
    assert return_resp.status_code == 200, return_resp.text
    assert return_resp.json()["status"] == "closed"

    check_resp2 = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp2.json()["status"] == "available_at_pool"


async def test_cannot_borrow_unavailable_equipment(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    nurse_headers = await _auth_headers(client, "ward_nurse")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-1002")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-UNAVAIL")

    first = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/borrow", headers=nurse_headers, json=payload)
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
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-VIEWER")

    resp = await client.post("/api/v1/borrow", headers=viewer_headers, json=payload)
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
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR4-0001")

    resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
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
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR4-0002")

    resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
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
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR7-0001")

    resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "open"


async def test_receipt_closes_the_transaction_and_records_outcome(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7-0002")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR7-0002")

    borrow_resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx_id = borrow_resp.json()["id"]

    return_resp = await client.post(
        f"/api/v1/return/{tx_id}", headers=admin_headers, json={"receipt_outcome": "usable", "notes": "all good"}
    )
    assert return_resp.status_code == 200, return_resp.text
    tx = return_resp.json()
    assert tx["status"] == "closed"


async def test_closing_an_already_closed_transaction_is_rejected(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7-0003")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR7-0003")

    borrow_resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    tx_id = borrow_resp.json()["id"]

    first = await client.post(f"/api/v1/return/{tx_id}", headers=admin_headers, json={"receipt_outcome": "usable"})
    assert first.status_code == 200, first.text

    second = await client.post(f"/api/v1/return/{tx_id}", headers=admin_headers, json={"receipt_outcome": "usable"})
    assert second.status_code == 409
    assert second.json()["code"] == "TRANSACTION_ALREADY_RETURNED"


async def test_repository_close_sets_closed_status_and_receipt_fields(db_session):
    """Repository-level (app.crud.transaction) proof, independent of the
    HTTP layer: close() is the only path that may set
    TransactionStatus.CLOSED, and it records returned_at/condition_on_return/
    received_by_user_id/notes together.

    Roadmap PR8A: close() now performs a conditional
    ``UPDATE ... WHERE status='open'`` and reports whether *this* call won
    (rowcount == 1) rather than mutating the ORM object in place -- so the
    persisted receipt fields are observable only after a refresh."""
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
    won = await transaction_crud.close(
        db_session, tx, received_by_user_id=receiver_id, receipt_outcome="usable", notes="checked in"
    )
    assert won is True, "closing an OPEN transaction must report the win (rowcount == 1)"

    await db_session.refresh(
        tx, attribute_names=["status", "returned_at", "condition_on_return", "received_by_user_id", "notes"]
    )
    assert tx.status == TransactionStatus.CLOSED
    assert tx.returned_at is not None
    assert tx.condition_on_return == "usable"
    assert tx.received_by_user_id == receiver_id
    assert "checked in" in tx.notes


async def test_repository_close_second_call_on_closed_row_reports_loss_and_preserves_winner(db_session):
    """Roadmap PR8A: close() is the atomic receipt guard. Once a row is no
    longer OPEN, a subsequent close() must match zero rows, report the loss
    (return False), and leave the first receipt's fields untouched. This
    proves the rowcount-decided winner/loser logic deterministically on
    SQLite (a second call standing in for the losing concurrent request);
    real concurrent-request behavior against PostgreSQL is proven in
    tests/test_postgres_integration.py."""
    from app.crud import transaction as transaction_crud
    from app.models.equipment import Equipment
    from app.models.transaction import BorrowTransaction, TransactionStatus

    equipment = Equipment(asset_number="AST-PR8A-0001", equipment_name="Pump")
    db_session.add(equipment)
    await db_session.flush()

    tx = BorrowTransaction(transaction_no="TX-PR8A-0001", equipment_id=equipment.id, borrower_name="Nurse Guard")
    db_session.add(tx)
    await db_session.flush()

    first_receiver = uuid.uuid4()
    won_first = await transaction_crud.close(
        db_session, tx, received_by_user_id=first_receiver, receipt_outcome="usable", notes="first"
    )
    assert won_first is True

    # Stand-in for the losing concurrent request: the row is already CLOSED,
    # so this conditional close matches zero rows. It must report the loss and
    # must NOT overwrite the winner's outcome / receiver / notes.
    second_receiver = uuid.uuid4()
    won_second = await transaction_crud.close(
        db_session, tx, received_by_user_id=second_receiver, receipt_outcome="defective", notes="second"
    )
    assert won_second is False, "a close() against an already-closed row must report rowcount == 0"

    await db_session.refresh(
        tx, attribute_names=["status", "condition_on_return", "received_by_user_id", "notes"]
    )
    assert tx.status == TransactionStatus.CLOSED
    assert tx.condition_on_return == "usable", "the loser must not overwrite the winner's outcome"
    assert tx.received_by_user_id == first_receiver, "the loser must not overwrite the winner's receiver"
    assert "second" not in (tx.notes or ""), "the loser's notes must not be persisted"


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

    await transaction_crud.close(db_session, tx, received_by_user_id=None, receipt_outcome="usable", notes=None)
    await db_session.flush()

    assert await transaction_crud.get_open_transaction_for_equipment(db_session, equipment.id) is None


async def test_check_overdue_returns_no_longer_exists(db_session):
    """Codex PR7a review round 1 (BLOCKER): the hourly overdue-returns job
    re-selected the same OPEN transactions every run with no de-duplication,
    creating a fresh notification for the same transaction every hour
    indefinitely. The approved MVP business model has no due-date/overdue
    *workflow* at all -- fixed by removing the job (and the function),
    not by patching it with deduplication. This asserts there is no code
    path left that could reintroduce it by accident."""
    from app.worker import scheduler

    assert not hasattr(scheduler, "check_overdue_returns")


async def test_scheduler_never_registers_the_disabled_overdue_job():
    """The active scheduler must only ever run app.worker.scheduler's
    PM/CAL-due check -- no job with the old "overdue_check" id, and no
    other job that could generate an overdue notification, is registered.
    Repeated start_scheduler()/stop_scheduler() cycles (e.g. app restarts)
    can therefore never produce a duplicate -- or any -- overdue
    notification, because there is no longer a job that runs the disabled
    workflow at all."""
    from app.worker import scheduler

    for _ in range(3):
        scheduler.start_scheduler()
        assert scheduler._scheduler is not None
        job_ids = {job.id for job in scheduler._scheduler.get_jobs()}
        assert job_ids == {"pm_cal_due_check"}
        assert "overdue_check" not in job_ids
        scheduler.stop_scheduler()
        assert scheduler._scheduler is None


async def test_repeated_scheduler_restarts_create_zero_overdue_notifications(db_session):
    """End-to-end proof for the Codex BLOCKER: even with an OPEN,
    long-overdue transaction sitting in the database, repeatedly starting
    and stopping the scheduler (simulating repeated app restarts, the
    trigger for the original bug) creates zero notifications of any kind,
    because the scheduler no longer runs anything that reads
    BorrowTransaction.due_at or writes an "overdue" notification."""
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from app.models.equipment import Equipment
    from app.models.notification import Notification
    from app.models.transaction import BorrowTransaction
    from app.worker import scheduler

    equipment = Equipment(asset_number="AST-PR7A-0007", equipment_name="Pump")
    db_session.add(equipment)
    await db_session.flush()

    db_session.add(
        BorrowTransaction(
            transaction_no="TX-PR7A-0007",
            equipment_id=equipment.id,
            borrower_name="Nurse Overdue",
            due_at=datetime.utcnow() - timedelta(days=30),
        )
    )
    await db_session.commit()

    for _ in range(3):
        scheduler.start_scheduler()
        scheduler.stop_scheduler()

    result = await db_session.execute(select(Notification).where(Notification.type == "overdue"))
    assert result.scalars().all() == []


# ---------------------------------------------------------------------------
# Roadmap PR7b (docs/audits/04-consolidated-implementation-plan.md Part D
# PR7 entry; docs/ROADMAP.md "PR7 (7b slice)"): dispatch_type, routine_round,
# ward_id-required-for-new-dispatches, and removing borrower_name/due_at/
# quantity from the active write path. Schema-level (BorrowRequest) tests
# first, then service/API-level tests.
# ---------------------------------------------------------------------------


async def test_borrow_request_routine_round_dispatch_with_valid_round_succeeds():
    from app.schemas.transaction import BorrowRequest

    req = BorrowRequest(
        equipment_id=str(uuid.uuid4()),
        ward_id=str(uuid.uuid4()),
        dispatch_type="routine_round",
        routine_round="06:00",
    )
    assert req.dispatch_type.value == "routine_round"
    assert req.routine_round.value == "06:00"


async def test_borrow_request_routine_round_dispatch_without_round_is_rejected():
    from pydantic import ValidationError

    from app.schemas.transaction import BorrowRequest

    with pytest.raises(ValidationError):
        BorrowRequest(equipment_id=str(uuid.uuid4()), ward_id=str(uuid.uuid4()), dispatch_type="routine_round")


async def test_borrow_request_on_demand_dispatch_with_no_round_succeeds():
    from app.schemas.transaction import BorrowRequest

    req = BorrowRequest(equipment_id=str(uuid.uuid4()), ward_id=str(uuid.uuid4()), dispatch_type="on_demand")
    assert req.routine_round is None


async def test_borrow_request_on_demand_dispatch_with_a_round_is_rejected():
    from pydantic import ValidationError

    from app.schemas.transaction import BorrowRequest

    with pytest.raises(ValidationError):
        BorrowRequest(
            equipment_id=str(uuid.uuid4()),
            ward_id=str(uuid.uuid4()),
            dispatch_type="on_demand",
            routine_round="06:00",
        )


async def test_borrow_request_missing_ward_id_is_rejected():
    from pydantic import ValidationError

    from app.schemas.transaction import BorrowRequest

    with pytest.raises(ValidationError):
        BorrowRequest(equipment_id=str(uuid.uuid4()), dispatch_type="on_demand")


async def test_borrow_request_missing_dispatch_type_is_rejected():
    from pydantic import ValidationError

    from app.schemas.transaction import BorrowRequest

    with pytest.raises(ValidationError):
        BorrowRequest(equipment_id=str(uuid.uuid4()), ward_id=str(uuid.uuid4()))


async def test_borrow_request_has_no_borrower_name_field():
    from pydantic import ValidationError

    from app.schemas.transaction import BorrowRequest

    assert "borrower_name" not in BorrowRequest.model_fields
    # Codex PR20 review round 1, MAJOR 1: the default Pydantic/FastAPI
    # behavior used elsewhere in this codebase (silently ignore
    # unrecognized fields) let a caller still send borrower_name with no
    # error at all, which is not "removed from the contract" -- it's
    # silently accepted and discarded. BorrowRequest (only) now sets
    # extra="forbid", so a legacy caller still sending borrower_name gets a
    # hard 422, exactly like a missing required field.
    with pytest.raises(ValidationError):
        BorrowRequest(
            equipment_id=str(uuid.uuid4()), ward_id=str(uuid.uuid4()), dispatch_type="on_demand", borrower_name="Nurse"
        )


async def test_borrow_request_has_no_due_at_field():
    from pydantic import ValidationError

    from app.schemas.transaction import BorrowRequest

    assert "due_at" not in BorrowRequest.model_fields
    with pytest.raises(ValidationError):
        BorrowRequest(
            equipment_id=str(uuid.uuid4()),
            ward_id=str(uuid.uuid4()),
            dispatch_type="on_demand",
            due_at="2026-01-01T00:00:00",
        )


async def test_borrow_request_has_no_quantity_field():
    from pydantic import ValidationError

    from app.schemas.transaction import BorrowRequest

    assert "quantity" not in BorrowRequest.model_fields
    with pytest.raises(ValidationError):
        BorrowRequest(equipment_id=str(uuid.uuid4()), ward_id=str(uuid.uuid4()), dispatch_type="on_demand", quantity=2)


@pytest.mark.parametrize(
    ("extra_field", "extra_value"),
    [
        ("borrower_name", "Nurse Test"),
        ("due_at", "2026-01-01T00:00:00"),
        ("quantity", 2),
    ],
)
async def test_removed_field_in_borrow_request_is_rejected_with_no_side_effects(
    client, seeded_users, db_session, extra_field, extra_value
):
    """Codex PR20 review round 1, MAJOR 1: API-level proof, not just a
    schema-level unit test -- POSTing a removed field must fail the
    request entirely (422, before the handler body ever runs), so it can
    never create a transaction, change equipment status, or write an audit
    record, exactly as if the field genuinely does not exist."""
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.transaction import BorrowTransaction

    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number=f"AST-PR20-{extra_field}")
    ward_id = await _create_ward(client, admin_headers, code=f"W-PR20-{extra_field}")

    resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={
            "equipment_id": equipment["id"],
            "ward_id": ward_id,
            "dispatch_type": "on_demand",
            extra_field: extra_value,
        },
    )
    assert resp.status_code == 422, resp.text

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp.json()["status"] == "available_at_pool", "equipment status must be unchanged"

    tx_rows = (
        await db_session.execute(
            select(BorrowTransaction).where(BorrowTransaction.equipment_id == uuid.UUID(equipment["id"]))
        )
    ).scalars().all()
    assert tx_rows == [], "no transaction may be created when the request is rejected"

    audit_rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "borrow", AuditLog.entity_type == "borrow_transaction")
        )
    ).scalars().all()
    assert audit_rows == [], "no audit record may be created when the request is rejected"


async def test_routine_round_dispatch_creates_exactly_one_open_transaction(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.transaction import BorrowTransaction

    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7B-0001")
    ward_id = await _create_ward(client, admin_headers, code="W-PR7B-0001")

    resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={
            "equipment_id": equipment["id"],
            "ward_id": ward_id,
            "dispatch_type": "routine_round",
            "routine_round": "11:00",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "open"

    rows = (
        await db_session.execute(
            select(BorrowTransaction).where(BorrowTransaction.equipment_id == uuid.UUID(equipment["id"]))
        )
    ).scalars().all()
    assert len(rows) == 1, "one dispatch request must create exactly one equipment transaction"


async def test_on_demand_dispatch_creates_exactly_one_open_transaction(client, seeded_users, db_session):
    from sqlalchemy import select

    from app.models.transaction import BorrowTransaction

    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7B-0002")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR7B-0002")

    resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "open"

    rows = (
        await db_session.execute(
            select(BorrowTransaction).where(BorrowTransaction.equipment_id == uuid.UUID(equipment["id"]))
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_routine_round_dispatch_transitions_equipment_to_issued_to_ward(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7B-0003")
    ward_id = await _create_ward(client, admin_headers, code="W-PR7B-0003")

    resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={
            "equipment_id": equipment["id"],
            "ward_id": ward_id,
            "dispatch_type": "routine_round",
            "routine_round": "15:00",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["equipment"]["status"] == "issued_to_ward"


async def test_dispatch_without_ward_id_is_rejected_by_the_api(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7B-0004")

    resp = await client.post(
        "/api/v1/borrow", headers=admin_headers, json={"equipment_id": equipment["id"], "dispatch_type": "on_demand"}
    )
    assert resp.status_code == 422, resp.text


async def test_dispatch_without_dispatch_type_is_rejected_by_the_api(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7B-0005")
    ward_id = await _create_ward(client, admin_headers, code="W-PR7B-0005")

    resp = await client.post(
        "/api/v1/borrow", headers=admin_headers, json={"equipment_id": equipment["id"], "ward_id": ward_id}
    )
    assert resp.status_code == 422, resp.text


async def test_dispatch_type_and_routine_round_are_persisted_as_approved_lowercase_values(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR7B-0006")
    ward_id = await _create_ward(client, admin_headers, code="W-PR7B-0006")

    resp = await client.post(
        "/api/v1/borrow",
        headers=admin_headers,
        json={
            "equipment_id": equipment["id"],
            "ward_id": ward_id,
            "dispatch_type": "routine_round",
            "routine_round": "21:00",
        },
    )
    assert resp.status_code == 201, resp.text
    tx = resp.json()
    assert tx["dispatch_type"] == "routine_round"
    assert tx["routine_round"] == "21:00"


async def test_historical_transaction_fields_remain_readable_after_pr7b(db_session):
    """A row created before Roadmap PR7b (no ward_id/dispatch_type/
    routine_round, but a borrower_name) must still serialize cleanly through
    the current TransactionOut contract -- historical data is read-only,
    never erased just because it is no longer an active write field."""
    from app.models.equipment import Equipment
    from app.models.transaction import BorrowTransaction
    from app.schemas.transaction import TransactionOut

    equipment = Equipment(asset_number="AST-PR7B-0007", equipment_name="Legacy Pump")
    db_session.add(equipment)
    await db_session.flush()

    tx = BorrowTransaction(
        transaction_no="TX-PR7B-0007",
        equipment_id=equipment.id,
        borrower_name="Pre-PR7b Nurse",
        quantity=2,
    )
    tx.equipment = equipment
    db_session.add(tx)
    await db_session.flush()

    out = TransactionOut.model_validate(tx, from_attributes=True)
    assert out.borrower_name == "Pre-PR7b Nurse"
    assert out.quantity == 2
    assert out.dispatch_type is None
    assert out.routine_round is None
    assert out.ward_id is None


# ---------------------------------------------------------------------------
# Roadmap PR8B (knowledge/adr/ADR-006-receipt-outcome-contract.md): the
# frozen receipt_outcome contract (usable/defective), replacing the
# pre-PR8B four-value condition string. Usable-receipt, repeat-receipt, and
# basic response-shape coverage already exists above
# (test_borrow_then_return_flow, test_receipt_closes_the_transaction_and_
# records_outcome, test_closing_an_already_closed_transaction_is_rejected);
# defective-outcome coverage is in tests/test_equipment.py; concurrent-
# receipt coverage is in tests/test_postgres_integration.py (SQLite cannot
# safely simulate real concurrency). These cover what those do not yet:
# invalid-outcome/retired-field validation, the defensive invalid-
# transition guard, audit/history row creation, full response consistency,
# and the missing-transaction/missing-equipment error paths.
# ---------------------------------------------------------------------------


async def test_receipt_with_invalid_outcome_is_rejected_with_validation_error(client, seeded_users):
    """receipt_outcome is a typed ReceiptOutcome enum -- an unrecognized
    value is caught by Pydantic/FastAPI request validation (422) before
    app.services.borrow_service ever runs, not the pre-PR8B 400
    INVALID_INPUT a free-form condition string needed a runtime
    dict-lookup miss to detect."""
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR8B-0001")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR8B-0001")

    borrow_resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx_id = borrow_resp.json()["id"]

    return_resp = await client.post(
        f"/api/v1/return/{tx_id}", headers=admin_headers, json={"receipt_outcome": "not-a-real-outcome"}
    )
    assert return_resp.status_code == 422, return_resp.text
    assert return_resp.json()["code"] == "VALIDATION_ERROR"

    # Zero side effects: equipment must still read ISSUED_TO_WARD.
    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp.json()["status"] == "issued_to_ward"


async def test_receipt_rejects_the_retired_condition_field(client, seeded_users):
    """No compatibility layer: ReturnRequest now sets extra: 'forbid'
    (mirroring BorrowRequest's Roadmap PR7b precedent), so a caller still
    sending the pre-PR8B `condition` field gets a hard 422, never a
    silently-ignored field or a silently-accepted receipt."""
    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR8B-0002")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR8B-0002")

    borrow_resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx_id = borrow_resp.json()["id"]

    return_resp = await client.post(f"/api/v1/return/{tx_id}", headers=admin_headers, json={"condition": "available"})
    assert return_resp.status_code == 422, return_resp.text
    assert return_resp.json()["code"] == "VALIDATION_ERROR"

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp.json()["status"] == "issued_to_ward", "a rejected request must produce zero side effects"


async def test_receipt_on_missing_transaction_returns_404(client, seeded_users):
    admin_headers = await _auth_headers(client, "admin")
    missing_id = uuid.uuid4()

    return_resp = await client.post(
        f"/api/v1/return/{missing_id}", headers=admin_headers, json={"receipt_outcome": "usable"}
    )
    assert return_resp.status_code == 404, return_resp.text
    assert return_resp.json()["code"] == "TRANSACTION_NOT_FOUND"


async def test_receipt_on_transaction_with_missing_equipment_returns_404(db_session):
    """Defensive case (app.services.borrow_service.return_equipment):
    equipment_crud.get_by_id filters out soft-deleted rows. No ordinary API
    path can reach this -- there is no client-facing action that both
    keeps a transaction OPEN and soft-deletes its equipment -- so the
    repository layer is exercised directly, standing in for the defensive
    EquipmentNotFoundError branch."""
    from app.core.exceptions import EquipmentNotFoundError
    from app.crud import equipment as equipment_crud
    from app.models.equipment import Equipment
    from app.models.transaction import BorrowTransaction, ReceiptOutcome
    from app.services import borrow_service

    equipment = Equipment(asset_number="AST-PR8B-0003", equipment_name="Pump")
    db_session.add(equipment)
    await db_session.flush()

    tx = BorrowTransaction(transaction_no="TX-PR8B-0003", equipment_id=equipment.id, borrower_name="Nurse Gone")
    db_session.add(tx)
    await db_session.flush()

    await equipment_crud.soft_delete(db_session, equipment)
    await db_session.flush()

    with pytest.raises(EquipmentNotFoundError):
        await borrow_service.return_equipment(
            db_session,
            transaction_id=tx.id,
            receipt_outcome=ReceiptOutcome.USABLE,
            notes=None,
            received_by_user_id=None,
            ip_address=None,
            user_agent=None,
        )


async def test_receipt_rejects_invalid_equipment_transition(db_session):
    """Defensive case: DISPATCH_RECEIPT_TRANSITIONS only allows
    ISSUED_TO_WARD -> {AVAILABLE_AT_POOL, UNAVAILABLE_DEFECTIVE}. Ordinary
    API use can never reach return_equipment() with equipment in any other
    status while its transaction is still OPEN -- MANUAL_LIFECYCLE_
    TRANSITIONS never touches ISSUED_TO_WARD as a source or target
    (app.models.equipment) -- so this exercises app.crud.equipment.
    change_status_for_dispatch_receipt's guard directly, standing in for a
    corrupted/out-of-band equipment status."""
    from app.core.exceptions import InvalidStatusTransitionError
    from app.models.equipment import Equipment, EquipmentStatus
    from app.models.transaction import BorrowTransaction, ReceiptOutcome
    from app.services import borrow_service

    equipment = Equipment(
        asset_number="AST-PR8B-0004", equipment_name="Pump", status=EquipmentStatus.DECOMMISSIONED
    )
    db_session.add(equipment)
    await db_session.flush()

    tx = BorrowTransaction(transaction_no="TX-PR8B-0004", equipment_id=equipment.id, borrower_name="Nurse Corrupt")
    db_session.add(tx)
    await db_session.flush()

    with pytest.raises(InvalidStatusTransitionError):
        await borrow_service.return_equipment(
            db_session,
            transaction_id=tx.id,
            receipt_outcome=ReceiptOutcome.USABLE,
            notes=None,
            received_by_user_id=None,
            ip_address=None,
            user_agent=None,
        )


async def test_receipt_creates_audit_and_history_rows_with_consistent_response(client, seeded_users, db_session):
    """A single successful receipt must (1) close the transaction, (2)
    transition equipment status, (3) write exactly one
    EquipmentStatusHistory row, (4) write exactly one audit row recording
    receipt_outcome, and (5) return a response whose fields are all
    mutually consistent with the persisted state, not just individually
    correct in isolation."""
    from sqlalchemy import select

    from app.models.audit import AuditLog
    from app.models.equipment import EquipmentStatusHistory

    admin_headers = await _auth_headers(client, "admin")
    equipment = await _create_equipment(client, admin_headers, asset_number="AST-PR8B-0005")
    payload = await _on_demand_borrow_payload(client, admin_headers, equipment["id"], ward_code="W-PR8B-0005")

    borrow_resp = await client.post("/api/v1/borrow", headers=admin_headers, json=payload)
    assert borrow_resp.status_code == 201, borrow_resp.text
    tx_id = borrow_resp.json()["id"]

    return_resp = await client.post(
        f"/api/v1/return/{tx_id}",
        headers=admin_headers,
        json={"receipt_outcome": "defective", "notes": "cracked housing"},
    )
    assert return_resp.status_code == 200, return_resp.text
    body = return_resp.json()

    # Response consistency: every field describing the outcome agrees.
    assert body["status"] == "closed"
    assert body["receipt_outcome"] == "defective"
    assert body["equipment"]["status"] == "unavailable_defective"
    assert body["returned_at"] is not None
    assert body["notes"] is not None and "cracked housing" in body["notes"]

    check_resp = await client.get(f"/api/v1/equipment/{equipment['id']}", headers=admin_headers)
    assert check_resp.json()["status"] == "unavailable_defective", "response must match persisted equipment state"

    history_rows = (
        (
            await db_session.execute(
                select(EquipmentStatusHistory).where(
                    EquipmentStatusHistory.equipment_id == uuid.UUID(equipment["id"])
                )
            )
        )
        .scalars()
        .all()
    )
    receipt_history = [h for h in history_rows if h.to_status == "unavailable_defective"]
    assert len(receipt_history) == 1
    assert receipt_history[0].from_status == "issued_to_ward"

    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "return",
                    AuditLog.entity_type == "borrow_transaction",
                    AuditLog.entity_id == uuid.UUID(tx_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].after_data == {"receipt_outcome": "defective"}
