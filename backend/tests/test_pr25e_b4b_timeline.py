"""Roadmap PR25E slice B4b: per-equipment timeline, Apply sequence, collision
stats and CSV (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 9.7, 16.1;
Owner decisions D7 and D8). No auto-sequencing exists or is tested for."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.equipment import Equipment, EquipmentStatus
from app.models.export import ExportEvent
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.test_pr25e_b2_sync_ops import _equipment, _send, _user, _ward, dispatch_op, receipt_op

pytestmark = pytest.mark.asyncio
S = "/api/v1/sync"


@pytest.fixture
async def ctx(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    return {
        "admin": admin, "staff": staff, "ro": ro,
        "staff_id": await _user(client, staff), "admin_id": await _user(client, admin),
        "ward": await _ward(client, admin), "eq": await _equipment(client, admin),
    }


async def _count(db, model, *where):
    q = select(func.count()).select_from(model)
    for w in where:
        q = q.where(w)
    return (await db.execute(q)).scalar_one()


async def _set(db, op_id, **values):
    await db.execute(update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(op_id)).values(**values))
    await db.commit()


async def _scenario(client, ctx, db):
    """tx1 dispatched then received (committed); op2 (dispatch) conflicted;
    op3 (receipt of op2) pending past its window. Applying [op2, op3] holds."""
    op1 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    assert (await _send(client, ctx["staff"], op1))[0]["result"] == "applied"
    op2 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    assert (await _send(client, ctx["staff"], op2))[0]["code"] == "EQUIPMENT_NOT_AVAILABLE"
    op3 = receipt_op(ctx["staff_id"], op2["op_id"], seq=1)
    assert (await _send(client, ctx["staff"], op3))[0]["result"] == "retry_later"
    await _set(db, op3["op_id"], first_seen_at=datetime.now(timezone.utc) - timedelta(hours=49))
    r1 = receipt_op(ctx["staff_id"], op1["op_id"], seq=2, device_id=op1["device_id"])
    assert (await _send(client, ctx["staff"], r1))[0]["result"] == "applied"
    now = datetime.now(timezone.utc)
    await _set(db, op2["op_id"], occurred_at=now - timedelta(minutes=30))
    await _set(db, op3["op_id"], occurred_at=now - timedelta(minutes=20))
    return op1, op2, op3


def _tl(eq):
    return f"{S}/equipment/{eq}/timeline"


def _seq(eq):
    return f"{S}/equipment/{eq}/apply-sequence"


async def test_timeline_merges_and_orders(client, ctx, db_session):
    op1, op2, op3 = await _scenario(client, ctx, db_session)
    r = await client.get(_tl(ctx["eq"]), headers=ctx["staff"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["equipment"]["id"] == ctx["eq"] and "asset_number" not in r.text and "AST-B2" not in r.text
    ev = body["events"]
    assert [e["source"] for e in ev].count("transaction") == 2 and [e["source"] for e in ev].count("op") == 2
    ops = [e for e in ev if e["source"] == "op"]
    assert [e["op_id"] for e in ops] == [op2["op_id"], op3["op_id"]]
    assert all(e["selectable"] for e in ops) and not any(e["selectable"] for e in ev if e["source"] == "transaction")
    assert ops[0]["result_code"] == "EQUIPMENT_NOT_AVAILABLE"
    assert ops[1]["kind"] == "receipt" and ops[1]["status"] == "pending"
    times = [e["at"] for e in ev]
    assert times == sorted(times)
    assert ops[0]["band_s"] == 30 and ops[0]["order_uncertain"] is False
    assert "payload" not in r.text


async def test_timeline_rbac_and_admin_only_rows(client, ctx, db_session):
    _, op2, _ = await _scenario(client, ctx, db_session)
    assert (await client.get(_tl(ctx["eq"]), headers=ctx["ro"])).status_code == 403
    assert (await client.get(_tl(ctx["eq"]))).status_code == 401
    assert (await client.get(_tl(uuid.uuid4()), headers=ctx["staff"])).status_code == 404
    await _set(db_session, op2["op_id"], result_code="FORBIDDEN")
    staff_ops = [e for e in (await client.get(_tl(ctx["eq"]), headers=ctx["staff"])).json()["events"] if e["source"] == "op"]
    assert op2["op_id"] not in [e["op_id"] for e in staff_ops]
    admin_ops = [e for e in (await client.get(_tl(ctx["eq"]), headers=ctx["admin"])).json()["events"] if e["source"] == "op"]
    assert op2["op_id"] in [e["op_id"] for e in admin_ops]


async def test_device_seq_overrides_time_and_overlap_flag(client, ctx, db_session):
    op1 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    await _send(client, ctx["staff"], op1)
    dev = str(uuid.uuid4())
    a = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1, device_id=dev)
    b = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=2, device_id=dev)
    other = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    await _send(client, ctx["staff"], a, b, other)
    now = datetime.now(timezone.utc)
    # a (seq 1) claims a LATER time than b (seq 2): seq wins within the device.
    await _set(db_session, a["op_id"], occurred_at=now - timedelta(minutes=5))
    await _set(db_session, b["op_id"], occurred_at=now - timedelta(minutes=50))
    await _set(db_session, other["op_id"], occurred_at=now - timedelta(minutes=49, seconds=40))
    ev = [e for e in (await client.get(_tl(ctx["eq"]), headers=ctx["staff"])).json()["events"] if e["source"] == "op"]
    ids = [e["op_id"] for e in ev]
    assert ids.index(a["op_id"]) < ids.index(b["op_id"])
    flags = {e["op_id"]: e["order_uncertain"] for e in ev}
    assert flags[other["op_id"]] is True and flags[a["op_id"]] is False


async def test_apply_sequence_success(client, ctx, db_session):
    op1, op2, op3 = await _scenario(client, ctx, db_session)
    exports = await _count(db_session, ExportEvent)
    d = await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [op2["op_id"], op3["op_id"]], "dry_run": True})
    assert d.status_code == 200 and d.json()["failed"] is None and len(d.json()["steps"]) == 2
    assert await _count(db_session, ExportEvent) == exports  # dry run writes nothing
    r = await client.post(_seq(ctx["eq"]), headers=ctx["admin"], json={"op_ids": [op2["op_id"], op3["op_id"]]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["failed"] is None and [s["op_id"] for s in out["steps"]] == [op2["op_id"], op3["op_id"]]
    assert all(s["ok"] and s["new_op_id"] for s in out["steps"])
    assert out["steps"][0]["transaction_id"] == op2["op_id"]  # dispatch tx id = original op_id
    assert await _count(db_session, ExportEvent) == exports + 2  # exactly one per applied op
    tx = await db_session.get(BorrowTransaction, uuid.UUID(op2["op_id"]))
    await db_session.refresh(tx)
    assert tx.status.value == "closed" and str(tx.borrower_user_id) == ctx["staff_id"]
    assert str(tx.received_by_user_id) == ctx["staff_id"]
    eq = await db_session.get(Equipment, uuid.UUID(ctx["eq"]))
    await db_session.refresh(eq)
    assert eq.status == EquipmentStatus.AVAILABLE_AT_POOL
    logs = (await db_session.execute(select(AuditLog).where(AuditLog.action == "sync_conflict_resolved"))).scalars().all()
    assert len(logs) == 2 and {str(x.user_id) for x in logs} == {ctx["admin_id"]}
    assert {x.after_data["original_user_id"] for x in logs} == {ctx["staff_id"]}
    for oid in (op2["op_id"], op3["op_id"]):
        row = await db_session.get(ClientOperation, uuid.UUID(oid))
        await db_session.refresh(row)
        assert row.status == "resolved" and row.resolution == "applied_as" and str(row.resolved_by) == ctx["admin_id"]
    # double submit: nothing more is applied
    again = await client.post(_seq(ctx["eq"]), headers=ctx["admin"], json={"op_ids": [op2["op_id"], op3["op_id"]]})
    assert again.status_code == 409 and again.json()["code"] == "SYNC_OP_NOT_RESOLVABLE"
    assert await _count(db_session, ExportEvent) == exports + 2
    assert await _count(db_session, BorrowTransaction) == 2


async def test_apply_sequence_stops_at_first_failure(client, ctx, db_session):
    """op1 frees the equipment; [opA, opB] are both dispatches: A applies, B
    cannot (equipment issued again). A stays applied, B stays in review."""
    op1 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    await _send(client, ctx["staff"], op1)
    a = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    b = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    c = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    await _send(client, ctx["staff"], a, b, c)
    await _send(client, ctx["staff"], receipt_op(ctx["staff_id"], op1["op_id"], seq=2, device_id=op1["device_id"]))
    exports = await _count(db_session, ExportEvent)
    dry = (await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [a["op_id"], b["op_id"], c["op_id"]], "dry_run": True})).json()
    assert dry["failed"]["op_id"] == b["op_id"] and dry["failed"]["code"] == "EQUIPMENT_NOT_AVAILABLE"
    assert dry["remaining"] == [c["op_id"]] and len(dry["steps"]) == 1
    r = await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [a["op_id"], b["op_id"], c["op_id"]]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert [s["op_id"] for s in out["steps"]] == [a["op_id"]]
    assert out["failed"]["op_id"] == b["op_id"] and out["failed"]["code"] == "SYNC_APPLY_FAILED"
    assert out["remaining"] == [c["op_id"]]
    assert await _count(db_session, ExportEvent) == exports + 1
    stat = {}
    for n, o in (("a", a), ("b", b), ("c", c)):
        row = await db_session.get(ClientOperation, uuid.UUID(o["op_id"]))
        await db_session.refresh(row)
        stat[n] = row.status
    assert stat == {"a": "resolved", "b": "conflict", "c": "conflict"}


async def test_apply_sequence_first_step_failure_is_409(client, ctx, db_session):
    op1 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    await _send(client, ctx["staff"], op1)
    a = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    await _send(client, ctx["staff"], a)
    exports = await _count(db_session, ExportEvent)
    r = await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [a["op_id"]]})
    assert r.status_code == 409 and r.json()["code"] == "SYNC_APPLY_FAILED"
    assert await _count(db_session, ExportEvent) == exports and await _count(db_session, BorrowTransaction) == 1


async def test_apply_sequence_validation_and_rbac(client, ctx, db_session):
    op1, op2, op3 = await _scenario(client, ctx, db_session)
    eq2 = await _equipment(client, ctx["admin"], n=2)
    ids = [op2["op_id"], op3["op_id"]]
    assert (await client.post(_seq(ctx["eq"]), headers=ctx["ro"], json={"op_ids": ids})).status_code == 403
    assert (await client.post(_seq(ctx["eq"]), json={"op_ids": ids})).status_code == 401
    assert (await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": []})).status_code == 422
    assert (await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": ids, "x": 1})).status_code == 422
    assert (await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [ids[0], ids[0]]})).status_code == 400
    assert (await client.post(_seq(eq2), headers=ctx["staff"], json={"op_ids": ids})).status_code == 400  # wrong equipment
    assert (await client.post(_seq(str(uuid.uuid4())), headers=ctx["staff"], json={"op_ids": ids})).status_code == 404
    assert (await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [str(uuid.uuid4())]})).status_code == 404
    assert (await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [op1["op_id"]]})).status_code == 409  # applied
    # admin-only class: staff cannot include it, and nothing at all is applied
    await _set(db_session, op3["op_id"], result_code="FORBIDDEN")
    exports = await _count(db_session, ExportEvent)
    r = await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": ids})
    assert r.status_code == 403 and r.json()["code"] == "SYNC_REVIEW_ADMIN_ONLY"
    assert await _count(db_session, ExportEvent) == exports
    assert (await client.post(_seq(ctx["eq"]), headers=ctx["admin"], json={"op_ids": ids})).status_code == 200


async def test_stats_and_csv(client, ctx, db_session):
    op1, op2, op3 = await _scenario(client, ctx, db_session)
    assert (await client.post(_seq(ctx["eq"]), headers=ctx["admin"], json={"op_ids": [op2["op_id"], op3["op_id"]]})).status_code == 200
    st = await client.get(f"{S}/collisions/stats", headers=ctx["admin"])
    assert st.status_code == 200, st.text
    body = st.json()
    assert body["total_conflicts"] == 2 and body["by_status"] == {"resolved": 2}
    assert body["by_result_code"]["EQUIPMENT_NOT_AVAILABLE"] == 1
    g = body["groups"]
    assert g["equipment_with_multiple_conflicts"] == 1 and g["cross_device"] == 1
    assert g["by_outcome"]["same"] == 1 and g["agreement_rate"] == 1.0
    assert g["would_have_auto_sequenced"]["conditions_met"] == 1
    assert g["would_have_auto_sequenced"]["resolved_same_order"] == 1
    assert "payload" not in st.text
    # admin only; bad ranges rejected
    assert (await client.get(f"{S}/collisions/stats", headers=ctx["staff"])).status_code == 403
    assert (await client.get(f"{S}/collisions/stats", headers=ctx["ro"])).status_code == 403
    bad = await client.get(f"{S}/collisions/stats", headers=ctx["admin"], params={"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"})
    assert bad.status_code == 400
    far = await client.get(f"{S}/collisions/stats", headers=ctx["admin"], params={"from": "2020-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"})
    assert far.status_code == 400
    empty = (await client.get(f"{S}/collisions/stats", headers=ctx["admin"], params={"from": "2020-01-01T00:00:00Z", "to": "2020-02-01T00:00:00Z"})).json()
    assert empty["total_conflicts"] == 0 and empty["groups"]["agreement_rate"] is None

    csv_r = await client.get(f"{S}/collisions/export", headers=ctx["admin"])
    assert csv_r.status_code == 200 and csv_r.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_r.headers["content-disposition"]
    lines = csv_r.text.lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("op_id,op_type,status,result_code,resolution,bcm_code,ward,operator")
    assert len(lines) == 3
    for forbidden in ("payload", "notes", "asset_number", "AST-B2", "@"):
        assert forbidden not in csv_r.text
    assert (await client.get(f"{S}/collisions/export", headers=ctx["staff"])).status_code == 403


async def test_csv_neutralises_formula_cells(client, ctx, db_session):
    from app.services.sync_timeline_service import _cell

    assert _cell("=1+1") == "'=1+1" and _cell("@x") == "'@x" and _cell(None) == "" and _cell("ok") == "ok"
    for raw in (" =1+1", "\t+cmd", "  -2", "\n@x"):
        assert _cell(raw).startswith("'"), raw
    assert _cell("a=b") == "a=b"


async def test_sequence_with_op_too_old_uses_confirmed_time(client, ctx, db_session):
    op1, op2, op3 = await _scenario(client, ctx, db_session)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    await _set(db_session, op2["op_id"], result_code="OP_TOO_OLD", occurred_at=old)
    r = await client.post(_seq(ctx["eq"]), headers=ctx["admin"], json={"op_ids": [op2["op_id"], op3["op_id"]]})
    assert r.status_code == 200 and r.json()["failed"] is None, r.text
    tx = await db_session.get(BorrowTransaction, uuid.UUID(op2["op_id"]))
    first = await db_session.get(BorrowTransaction, uuid.UUID(op1["op_id"]))
    await db_session.refresh(tx)
    await db_session.refresh(first)

    def u(d):
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d

    # relational guard: not earlier than the equipment's latest receipt
    assert u(tx.borrowed_at) >= u(first.returned_at)
    assert u(tx.returned_at) >= u(tx.borrowed_at)


async def test_sequence_rejects_device_seq_inversion_and_deleted_equipment(client, ctx, db_session):
    op1 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    await _send(client, ctx["staff"], op1)
    dev = str(uuid.uuid4())
    a = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1, device_id=dev)
    b = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=2, device_id=dev)
    await _send(client, ctx["staff"], a, b)
    r = await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [b["op_id"], a["op_id"]]})
    assert r.status_code == 400
    assert (await client.get(_tl(ctx["eq"]), headers=ctx["staff"])).json()["truncated"] is False
    await db_session.execute(
        update(Equipment).where(Equipment.id == uuid.UUID(ctx["eq"])).values(deleted_at=datetime.now(timezone.utc))
    )
    await db_session.commit()
    r = await client.post(_seq(ctx["eq"]), headers=ctx["staff"], json={"op_ids": [a["op_id"], b["op_id"]]})
    assert r.status_code == 404
