"""Roadmap PR31 (Owner Governance 2026-11-25, D8): dispatch is not blocked by
equipment status. Re-dispatch atomically closes the previous open transaction
("closed by re-dispatch, receipt not recorded"), defective equipment may be
dispatched (flagged), decommissioned equipment stays blocked, and an
acknowledgement is required for the first two (409 DISPATCH_STATUS_WARNING)."""
import csv
import io
import uuid

import pytest
from sqlalchemy import func, select

from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus, EquipmentStatusHistory
from app.models.export import ExportEvent
from app.models.transaction import CLOSE_REASON_REDISPATCH, BorrowTransaction, TransactionStatus
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio


async def _equipment(client, admin, n):
    resp = await client.post(
        "/api/v1/equipment", headers=admin, json={"asset_number": f"AST-PR31-{n}", "equipment_name": "Pump"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_status(client, admin, equipment_id, status):
    resp = await client.post(f"/api/v1/equipment/{equipment_id}/status", headers=admin, json={"status": status})
    assert resp.status_code == 200, resp.text


def _payload(equipment_id, ward_id, **extra):
    return {"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand", **extra}


@pytest.fixture
async def ctx(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_a = await _create_ward(client, admin, "W-31A", "Ward Alpha")
    ward_b = await _create_ward(client, admin, "W-31B", "Ward Beta")
    return {"admin": admin, "staff": staff, "ward_a": ward_a, "ward_b": ward_b}


async def _tx(db_session, tx_id):
    db_session.expire_all()
    return (await db_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)))).scalar_one()


async def _eq_status(db_session, equipment_id):
    db_session.expire_all()
    row = (await db_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(equipment_id)))).scalar_one()
    return row.status


async def test_redispatch_without_acknowledgement_returns_409_with_details(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "a1")
    first = await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))
    assert first.status_code == 201

    resp = await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_b"]))
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "DISPATCH_STATUS_WARNING"
    d = body["details"]
    assert d["warning"] == "already_dispatched"
    assert d["current_ward_name"] == "Ward Alpha"
    assert d["current_ward_id"] == ctx["ward_a"]
    assert d["open_transaction_id"] == first.json()["id"]
    assert d["dispatched_at"]

    # Zero side effects.
    tx = await _tx(db_session, first.json()["id"])
    assert tx.status == TransactionStatus.OPEN and tx.close_reason is None
    n = (await db_session.execute(select(func.count()).select_from(BorrowTransaction))).scalar_one()
    assert n == 1


async def test_redispatch_with_acknowledgement_closes_previous_and_opens_new_atomically(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "a2")
    first = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()

    resp = await client.post(
        "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_b"], acknowledge_status_warning=True)
    )
    assert resp.status_code == 201, resp.text
    new = resp.json()
    assert new["status"] == "open"
    assert new["ward_id"] == ctx["ward_b"]
    assert new["close_reason"] is None and new["dispatched_while_defective"] is False
    assert new["equipment"]["status"] == "issued_to_ward"

    prev = await _tx(db_session, first["id"])
    assert prev.status == TransactionStatus.CLOSED
    assert prev.close_reason == CLOSE_REASON_REDISPATCH
    # No fabricated receipt.
    assert prev.returned_at is None
    assert prev.condition_on_return is None
    assert prev.received_by_user_id is None
    assert prev.receipt_outcome is None

    assert await _eq_status(db_session, eq) == EquipmentStatus.ISSUED_TO_WARD

    # Exactly one open transaction for the equipment.
    open_n = (
        await db_session.execute(
            select(func.count()).select_from(BorrowTransaction).where(
                BorrowTransaction.equipment_id == uuid.UUID(eq), BorrowTransaction.status == TransactionStatus.OPEN
            )
        )
    ).scalar_one()
    assert open_n == 1

    # Audit: one close row for the previous tx, one borrow row for the new tx.
    close_rows = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "redispatch_close"))
    ).scalars().all()
    assert len(close_rows) == 1
    assert str(close_rows[0].entity_id) == first["id"]
    assert close_rows[0].after_data["close_reason"] == CLOSE_REASON_REDISPATCH
    assert close_rows[0].after_data["closed_by_transaction_id"] == new["id"]
    borrow_rows = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "borrow", AuditLog.entity_id == uuid.UUID(new["id"]))
        )
    ).scalars().all()
    assert len(borrow_rows) == 1
    assert borrow_rows[0].after_data["redispatch_closed_transaction_id"] == first["id"]

    # Status history records the re-dispatch; no receipt export event for the closed tx.
    hist = (
        await db_session.execute(
            select(EquipmentStatusHistory).where(EquipmentStatusHistory.reason == "Re-dispatched")
        )
    ).scalars().all()
    assert len(hist) == 1 and hist[0].from_status == hist[0].to_status == "issued_to_ward"
    events = (
        await db_session.execute(select(ExportEvent).where(ExportEvent.transaction_id == uuid.UUID(first["id"])))
    ).scalars().all()
    assert [e.event_type for e in events] == ["dispatch"]


async def test_receipt_of_the_new_transaction_after_redispatch_is_normal(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "a3")
    first = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()
    new = (
        await client.post(
            "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_b"], acknowledge_status_warning=True)
        )
    ).json()

    # The closed-by-redispatch transaction can no longer be received.
    old = await client.post(f"/api/v1/return/{first['id']}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
    assert old.status_code == 409 and old.json()["code"] == "TRANSACTION_CLOSED_BY_REDISPATCH"

    ok = await client.post(f"/api/v1/return/{new['id']}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
    assert ok.status_code == 200
    assert await _eq_status(db_session, eq) == EquipmentStatus.AVAILABLE_AT_POOL


async def test_defective_dispatch_requires_acknowledgement_then_flags_transaction(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "d1")
    await _set_status(client, ctx["admin"], eq, "unavailable_defective")

    warn = await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))
    assert warn.status_code == 409
    assert warn.json()["code"] == "DISPATCH_STATUS_WARNING"
    assert warn.json()["details"]["warning"] == "defective"
    assert await _eq_status(db_session, eq) == EquipmentStatus.UNAVAILABLE_DEFECTIVE

    ok = await client.post(
        "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"], acknowledge_status_warning=True)
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["dispatched_while_defective"] is True
    assert ok.json()["close_reason"] is None
    assert await _eq_status(db_session, eq) == EquipmentStatus.ISSUED_TO_WARD

    row = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == "borrow", AuditLog.entity_id == uuid.UUID(ok.json()["id"]))
        )
    ).scalar_one()
    assert row.after_data["dispatched_while_defective"] is True
    assert row.after_data["previous_equipment_status"] == "unavailable_defective"


async def test_normal_dispatch_is_unflagged_and_ack_flag_is_harmless(client, ctx):
    eq = await _equipment(client, ctx["admin"], "n1")
    resp = await client.post(
        "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"], acknowledge_status_warning=True)
    )
    assert resp.status_code == 201
    assert resp.json()["dispatched_while_defective"] is False


async def test_decommissioned_is_rejected_even_with_acknowledgement(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "x1")
    await _set_status(client, ctx["admin"], eq, "unavailable_defective")
    await _set_status(client, ctx["admin"], eq, "decommissioned")

    for extra in ({}, {"acknowledge_status_warning": True}):
        resp = await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"], **extra))
        assert resp.status_code == 409
        assert resp.json()["code"] == "EQUIPMENT_NOT_AVAILABLE"
    assert await _eq_status(db_session, eq) == EquipmentStatus.DECOMMISSIONED
    n = (await db_session.execute(select(func.count()).select_from(BorrowTransaction))).scalar_one()
    assert n == 0


async def test_unknown_field_is_still_rejected(client, ctx):
    eq = await _equipment(client, ctx["admin"], "u1")
    resp = await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"], bogus=1))
    assert resp.status_code == 422


async def test_lost_close_race_rolls_back_with_zero_side_effects(client, ctx, db_session, monkeypatch):
    from app.crud import transaction as transaction_crud

    eq = await _equipment(client, ctx["admin"], "r1")
    first = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()

    async def _lost(db, tx):
        return False

    monkeypatch.setattr(transaction_crud, "close_for_redispatch", _lost)
    resp = await client.post(
        "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_b"], acknowledge_status_warning=True)
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "EQUIPMENT_NOT_AVAILABLE"
    assert (await _tx(db_session, first["id"])).status == TransactionStatus.OPEN
    n = (await db_session.execute(select(func.count()).select_from(BorrowTransaction))).scalar_one()
    assert n == 1
    assert (
        await db_session.execute(select(func.count()).select_from(AuditLog).where(AuditLog.action == "redispatch_close"))
    ).scalar_one() == 0


async def test_repeated_redispatch_chain_keeps_exactly_one_open_transaction(client, ctx, db_session):
    # Sequential chain on SQLite (its single shared connection cannot race);
    # true two-connection concurrency is proved in test_pr31_postgres.py.
    eq = await _equipment(client, ctx["admin"], "c1")
    await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))
    for ward in (ctx["ward_b"], ctx["ward_a"], ctx["ward_b"]):
        r = await client.post(
            "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ward, acknowledge_status_warning=True)
        )
        assert r.status_code == 201

    db_session.expire_all()
    rows = (await db_session.execute(select(BorrowTransaction))).scalars().all()
    assert len(rows) == 4
    assert len([r for r in rows if r.status == TransactionStatus.OPEN]) == 1
    assert len([r for r in rows if r.close_reason == CLOSE_REASON_REDISPATCH]) == 3
    assert all(r.returned_at is None for r in rows)
    assert await _eq_status(db_session, eq) == EquipmentStatus.ISSUED_TO_WARD


async def test_dispatch_check_endpoint(client, ctx):
    eq = await _equipment(client, ctx["admin"], "k1")
    ok = (await client.get(f"/api/v1/equipment/{eq}/dispatch-check", headers=ctx["staff"])).json()
    assert ok["warning"] is None and ok["dispatchable"] is True and ok["requires_acknowledgement"] is False

    tx = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()
    d = (await client.get(f"/api/v1/equipment/{eq}/dispatch-check", headers=ctx["staff"])).json()
    assert d["warning"] == "already_dispatched" and d["requires_acknowledgement"] is True
    assert d["current_ward_name"] == "Ward Alpha" and d["open_transaction_id"] == tx["id"] and d["dispatched_at"]

    await client.post(f"/api/v1/return/{tx['id']}", headers=ctx["staff"], json={"receipt_outcome": "defective"})
    d = (await client.get(f"/api/v1/equipment/{eq}/dispatch-check", headers=ctx["staff"])).json()
    assert d["warning"] == "defective" and d["dispatchable"] is True and d["requires_acknowledgement"] is True

    await _set_status(client, ctx["admin"], eq, "decommissioned")
    d = (await client.get(f"/api/v1/equipment/{eq}/dispatch-check", headers=ctx["staff"])).json()
    assert d["warning"] == "decommissioned" and d["dispatchable"] is False and d["requires_acknowledgement"] is False

    missing = await client.get(f"/api/v1/equipment/{uuid.uuid4()}/dispatch-check", headers=ctx["staff"])
    assert missing.status_code == 404


async def test_dispatch_check_requires_authentication(client, seeded_users):
    resp = await client.get(f"/api/v1/equipment/{uuid.uuid4()}/dispatch-check")
    assert resp.status_code == 401


async def test_reports_exports_and_active_list_handle_closed_by_redispatch(client, ctx):
    eq = await _equipment(client, ctx["admin"], "p1")
    first = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()
    new = (
        await client.post(
            "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_b"], acknowledge_status_warning=True)
        )
    ).json()

    # Receive report: neither the closed-by-redispatch row nor the still-open one appears.
    rec = await client.get("/api/v1/reports/receive", headers=ctx["admin"])
    assert rec.status_code == 200 and rec.json()["items"] == []

    # Issue report: both dispatches appear; the superseded one has no receipt.
    iss = await client.get("/api/v1/reports/issue", headers=ctx["admin"])
    assert iss.status_code == 200
    by_id = {i["id"]: i for i in iss.json()["items"]}
    assert set(by_id) == {first["id"], new["id"]}
    assert by_id[first["id"]]["status"] == "closed"
    assert by_id[first["id"]]["receipt_outcome"] is None
    assert by_id[first["id"]]["returned_at"] is None
    assert by_id[first["id"]]["receipt_business_date"] is None

    # Active list holds only the new open transaction.
    active = (await client.get("/api/v1/borrow/active", headers=ctx["admin"])).json()
    assert [t["id"] for t in active] == [new["id"]]

    # CSV export serializes the closed row with an empty return time/outcome.
    csv_resp = await client.get("/api/v1/reports/export", headers=ctx["admin"], params={"format": "csv"})
    assert csv_resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_resp.text.lstrip("\ufeff"))))
    closed = [r for r in rows if r["สถานะ"] == "รับคืนแล้ว"]
    assert len(closed) == 1 and closed[0]["วันที่รับคืน"] == "" and closed[0]["สภาพตอนคืน"] == ""

    # Read-only export API: dispatch events only, no receipt event for the superseded tx.
    key = (await client.post("/api/v1/export-keys", headers=ctx["admin"], json={"name": "k"})).json()["key"]
    ev = (await client.get("/api/v1/export/events", headers={"X-API-Key": key})).json()
    kinds = sorted((e["transaction_id"] == first["id"], e["event_type"]) for e in ev["events"])
    assert kinds == [(False, "dispatch"), (True, "dispatch")]


async def test_offline_dispatch_of_dispatched_equipment_without_ack_goes_to_conflict(client, ctx, db_session):
    from tests.test_pr25e_b2_sync_ops import URL, dispatch_op

    me = (await client.get("/api/v1/auth/me", headers=ctx["staff"])).json()["id"]
    eq = await _equipment(client, ctx["admin"], "s1")
    first = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()

    op = dispatch_op(me, eq, ctx["ward_b"])
    resp = await client.post(URL, headers=ctx["staff"], json={"operations": [op]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["result"] == "conflict"
    assert (await _tx(db_session, first["id"])).status == TransactionStatus.OPEN

    op2 = dispatch_op(me, eq, ctx["ward_b"], seq=2, acknowledge_status_warning=True)
    resp2 = await client.post(URL, headers=ctx["staff"], json={"operations": [op2]})
    assert resp2.json()["results"][0]["result"] == "applied", resp2.text
    assert (await _tx(db_session, first["id"])).close_reason == CLOSE_REASON_REDISPATCH


# --- review follow-ups -------------------------------------------------------


async def test_monitor_events_show_close_reason_for_redispatch_closed_transaction(client, ctx):
    eq = await _equipment(client, ctx["admin"], "mon1")
    first = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()
    new = (
        await client.post(
            "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_b"], acknowledge_status_warning=True)
        )
    ).json()

    disp = await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "dispatch"})
    assert disp.status_code == 200, disp.text
    by_id = {e["id"]: e for e in disp.json()["items"]}
    assert by_id[first["id"]]["close_reason"] == CLOSE_REASON_REDISPATCH
    assert by_id[new["id"]]["close_reason"] is None

    # No receipt was recorded for the superseded transaction: not a receipt event.
    rec = await client.get("/api/v1/monitor/events", headers=ctx["staff"], params={"kind": "receipt"})
    assert rec.status_code == 200 and rec.json()["items"] == []


async def test_decommission_racing_a_defective_dispatch_can_never_leave_decommissioned_issued(
    client, ctx, db_session, monkeypatch
):
    """The equipment status write is conditional on the status the dispatch
    validated; a manual decommission committed between the dispatch's read and
    its write wins and the dispatch rolls back completely."""
    from sqlalchemy import update

    from app.services import borrow_service

    eq = await _equipment(client, ctx["admin"], "race1")
    await _set_status(client, ctx["admin"], eq, "unavailable_defective")

    real_assess = borrow_service.assess_dispatch

    async def assess_then_decommission(db, equipment):
        assessment = await real_assess(db, equipment)
        # "Another session" commits the manual decommission after our read.
        await db.execute(
            update(Equipment)
            .where(Equipment.id == equipment.id)
            .values(status=EquipmentStatus.DECOMMISSIONED)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        return assessment

    monkeypatch.setattr(borrow_service, "assess_dispatch", assess_then_decommission)
    resp = await client.post(
        "/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"], acknowledge_status_warning=True)
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "EQUIPMENT_STATUS_CHANGED"
    assert await _eq_status(db_session, eq) == EquipmentStatus.DECOMMISSIONED
    n = (await db_session.execute(select(func.count()).select_from(BorrowTransaction))).scalar_one()
    assert n == 0


async def test_stale_expected_open_transaction_id_is_refused_and_matching_one_accepted(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], "st1")
    first = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()

    stale = await client.post(
        "/api/v1/borrow",
        headers=ctx["staff"],
        json=_payload(eq, ctx["ward_b"], acknowledge_status_warning=True, expected_open_transaction_id=str(uuid.uuid4())),
    )
    assert stale.status_code == 409 and stale.json()["code"] == "DISPATCH_WARNING_STALE"
    assert (await _tx(db_session, first["id"])).status == TransactionStatus.OPEN

    ok = await client.post(
        "/api/v1/borrow",
        headers=ctx["staff"],
        json=_payload(eq, ctx["ward_b"], acknowledge_status_warning=True, expected_open_transaction_id=first["id"]),
    )
    assert ok.status_code == 201, ok.text

    # The warned transaction was meanwhile received: an id no longer matches anything open.
    await client.post(f"/api/v1/return/{ok.json()['id']}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
    gone = await client.post(
        "/api/v1/borrow",
        headers=ctx["staff"],
        json=_payload(eq, ctx["ward_a"], acknowledge_status_warning=True, expected_open_transaction_id=ok.json()["id"]),
    )
    assert gone.status_code == 409 and gone.json()["code"] == "DISPATCH_WARNING_STALE"


async def test_redispatch_business_time_is_clamped_to_the_closed_transactions_dispatch_time(client, ctx, db_session):
    from datetime import datetime, timedelta, timezone

    from app.services import borrow_service

    eq = await _equipment(client, ctx["admin"], "cl1")
    first = (await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))).json()
    older = datetime.now(timezone.utc) - timedelta(days=2)
    tx = await borrow_service.borrow(
        db_session,
        equipment_id=eq,
        borrower_user_id=None,
        ward_id=ctx["ward_b"],
        dispatch_type=None,
        routine_round=None,
        department_id=None,
        phone_number=None,
        pickup_location_id=None,
        dropoff_location_id=None,
        notes=None,
        ip_address=None,
        user_agent=None,
        borrowed_at=older,
        acknowledge_status_warning=True,
    )
    new_id = str(tx.id)
    prev_at = (await _tx(db_session, first["id"])).borrowed_at
    new_at = (await _tx(db_session, new_id)).borrowed_at
    assert new_at >= prev_at


async def test_review_precondition_predicts_the_dispatch_warning(client, ctx, db_session):
    from tests.test_pr25e_b2_sync_ops import URL, dispatch_op

    me = (await client.get("/api/v1/auth/me", headers=ctx["staff"])).json()["id"]
    eq = await _equipment(client, ctx["admin"], "pr1")
    await client.post("/api/v1/borrow", headers=ctx["staff"], json=_payload(eq, ctx["ward_a"]))
    op = dispatch_op(me, eq, ctx["ward_b"])
    res = await client.post(URL, headers=ctx["staff"], json={"operations": [op]})
    assert res.json()["results"][0]["result"] == "conflict"

    detail = (await client.get(f"/api/v1/sync/conflicts/{op['op_id']}", headers=ctx["admin"])).json()
    assert detail["apply_now_possible"] is False and detail["apply_now_blocker"] == "DISPATCH_STATUS_WARNING"
