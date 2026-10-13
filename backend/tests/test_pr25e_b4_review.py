"""Roadmap PR25E slice B4: conflict review list/detail, dismiss, apply-now
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 9.6, 9.8, 17 item 9)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.equipment import Equipment, EquipmentStatus, EquipmentStatusHistory
from app.models.export import ExportEvent
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.test_pr25e_b2_sync_ops import _equipment, _send, _user, _ward, dispatch_op, receipt_op

pytestmark = pytest.mark.asyncio
C = "/api/v1/sync/conflicts"


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


async def _conflict(client, ctx, seq=2):
    """op1 dispatches the equipment; op2 conflicts. Returns (op1, op2)."""
    op1 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    assert (await _send(client, ctx["staff"], op1))[0]["result"] == "applied"
    op2 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=seq)
    assert (await _send(client, ctx["staff"], op2))[0]["code"] == "EQUIPMENT_NOT_AVAILABLE"
    return op1, op2


async def _free_equipment(client, ctx, op1):
    r = receipt_op(ctx["staff_id"], op1["op_id"], seq=9)
    assert (await _send(client, ctx["staff"], r))[0]["result"] == "applied"


async def test_list_detail_and_information_boundary(client, ctx):
    op1, op2 = await _conflict(client, ctx)
    r = await client.get(C, headers=ctx["staff"])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["op_id"] == op2["op_id"]
    it = body["items"][0]
    assert it["result_code"] == "EQUIPMENT_NOT_AVAILABLE" and it["operator"]["id"] == ctx["staff_id"]
    assert it["equipment"]["status"] == "issued_to_ward" and it["ward_name"] == "W-B2"
    assert "payload" not in it
    text = r.text + (await client.get(f"{C}/{op2['op_id']}", headers=ctx["staff"])).text
    for forbidden in ("AST-B2-1", "item_no", "asset_number", "email", "payload_hash"):
        assert forbidden not in text
    d = (await client.get(f"{C}/{op2['op_id']}", headers=ctx["admin"])).json()
    assert d["apply_now_possible"] is False and d["apply_now_blocker"] == "EQUIPMENT_NOT_AVAILABLE"
    assert d["payload_summary"]["dispatch_type"] == "on_demand"


async def test_filters_pagination_and_stale_first(client, ctx, db_session):
    eq2 = await _equipment(client, ctx["admin"], n=2)
    await _send(client, ctx["staff"], dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1))
    ops = [dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=s) for s in (2, 3, 4)]
    for o in ops:
        await _send(client, ctx["staff"], o)
    # newest op is stale -> must sort first although received last
    await db_session.execute(
        update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(ops[2]["op_id"])).values(stale_context=True)
    )
    await db_session.commit()
    items = (await client.get(C, headers=ctx["staff"])).json()["items"]
    assert [i["op_id"] for i in items][0] == ops[2]["op_id"] and items[0]["stale_context"]
    p1 = (await client.get(C, headers=ctx["staff"], params={"limit": 2})).json()
    p2 = (await client.get(C, headers=ctx["staff"], params={"limit": 2, "offset": 2})).json()
    assert p1["total"] == 3 and len(p1["items"]) == 2 and len(p2["items"]) == 1
    assert {i["op_id"] for i in p1["items"] + p2["items"]} == {o["op_id"] for o in ops}
    f = (await client.get(C, headers=ctx["staff"], params={"stale_context": "true"})).json()
    assert f["total"] == 1
    assert (await client.get(C, headers=ctx["staff"], params={"result_code": "NOPE"})).json()["total"] == 0
    assert (await client.get(C, headers=ctx["staff"], params={"op_type": "receipt"})).json()["total"] == 0
    assert (await client.get(C, headers=ctx["staff"], params={"status": "bogus"})).status_code == 400
    assert (await client.get(C, headers=ctx["staff"], params={"limit": 101})).status_code == 422
    # expired pending rows are listed, fresh ones are not
    fresh = receipt_op(ctx["staff_id"], str(uuid.uuid4()), seq=20)
    old = receipt_op(ctx["staff_id"], str(uuid.uuid4()), seq=21)
    await _send(client, ctx["staff"], fresh, old)
    await db_session.execute(
        update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(old["op_id"]))
        .values(first_seen_at=datetime.now(timezone.utc) - timedelta(hours=49))
    )
    await db_session.commit()
    ids = {i["op_id"] for i in (await client.get(C, headers=ctx["staff"])).json()["items"]}
    assert old["op_id"] in ids and fresh["op_id"] not in ids
    assert (await client.get(f"{C}/{fresh['op_id']}", headers=ctx["staff"])).status_code == 404


async def test_rbac_and_admin_only_class(client, ctx, db_session):
    _, op2 = await _conflict(client, ctx)
    assert (await client.get(C, headers=ctx["ro"])).status_code == 403
    assert (await client.get(C)).status_code == 401
    oid = op2["op_id"]
    assert (await client.post(f"{C}/{oid}/dismiss", headers=ctx["ro"], json={"reason": "not_real"})).status_code == 403
    assert (await client.post(f"{C}/{oid}/apply-now", headers=ctx["ro"])).status_code == 403
    await db_session.execute(update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(oid)).values(result_code="FORBIDDEN"))
    await db_session.commit()
    assert (await client.get(C, headers=ctx["staff"])).json()["total"] == 0
    assert (await client.get(C, headers=ctx["admin"])).json()["total"] == 1
    for call in (
        client.get(f"{C}/{oid}", headers=ctx["staff"]),
        client.post(f"{C}/{oid}/dismiss", headers=ctx["staff"], json={"reason": "not_real"}),
        client.post(f"{C}/{oid}/apply-now", headers=ctx["staff"]),
    ):
        r = await call
        assert r.status_code == 403 and r.json()["code"] == "SYNC_REVIEW_ADMIN_ONLY"
    r = await client.post(f"{C}/{oid}/dismiss", headers=ctx["admin"], json={"reason": "not_real"})
    assert r.status_code == 200


async def test_dismiss_requires_reason_and_audits(client, ctx, db_session):
    _, op2 = await _conflict(client, ctx)
    oid = op2["op_id"]
    url = f"{C}/{oid}/dismiss"
    assert (await client.post(url, headers=ctx["staff"], json={})).status_code == 422
    assert (await client.post(url, headers=ctx["staff"], json={"reason": "whatever"})).status_code == 422
    exports = await _count(db_session, ExportEvent)
    r = await client.post(url, headers=ctx["admin"], json={"reason": "already_recorded", "note": "same item"})
    assert r.status_code == 200 and r.json()["resolution"] == "dismissed"
    row = (await db_session.execute(select(ClientOperation).where(ClientOperation.op_id == uuid.UUID(oid)))).scalar_one()
    await db_session.refresh(row)
    assert row.status == "resolved" and str(row.resolved_by) == ctx["admin_id"] and row.resolution_note == "already_recorded: same item"
    log = (await db_session.execute(select(AuditLog).where(AuditLog.action == "sync_conflict_resolved"))).scalar_one()
    assert str(log.user_id) == ctx["admin_id"] and log.after_data["original_user_id"] == ctx["staff_id"]
    assert log.after_data["original_op_id"] == oid and log.before_data["status"] == "conflict"
    assert await _count(db_session, ExportEvent) == exports
    assert await _count(db_session, BorrowTransaction) == 1
    # not resolvable twice; resend of the original is a silent duplicate
    assert (await client.post(url, headers=ctx["staff"], json={"reason": "not_real"})).json()["code"] == "SYNC_OP_NOT_RESOLVABLE"
    assert (await client.post(f"{C}/{oid}/apply-now", headers=ctx["staff"])).status_code == 409
    assert (await _send(client, ctx["staff"], op2))[0]["result"] == "duplicate"
    assert (await client.get(C, headers=ctx["staff"])).json()["total"] == 0
    assert (await client.get(C, headers=ctx["staff"], params={"status": "resolved"})).json()["items"][0]["dismiss_reason"] == "already_recorded"


async def test_cannot_resolve_applied_or_unknown(client, ctx):
    op1, _ = await _conflict(client, ctx)
    for path in ("dismiss", "apply-now"):
        r = await client.post(f"{C}/{op1['op_id']}/{path}", headers=ctx["admin"], json={"reason": "not_real"} if path == "dismiss" else None)
        assert r.status_code == 409 and r.json()["code"] == "SYNC_OP_NOT_RESOLVABLE"
    assert (await client.get(f"{C}/{op1['op_id']}", headers=ctx["admin"])).status_code == 404
    assert (await client.post(f"{C}/{uuid.uuid4()}/apply-now", headers=ctx["admin"])).status_code == 404


async def test_apply_now_success(client, ctx, db_session):
    op1, op2 = await _conflict(client, ctx)
    await _free_equipment(client, ctx, op1)
    exports = await _count(db_session, ExportEvent)
    d = (await client.get(f"{C}/{op2['op_id']}", headers=ctx["admin"])).json()
    assert d["apply_now_possible"] is True
    r = await client.post(f"{C}/{op2['op_id']}/apply-now", headers=ctx["admin"])
    assert r.status_code == 200, r.text
    out = r.json()
    new_id = uuid.UUID(out["new_op_id"])
    assert new_id != uuid.UUID(op2["op_id"]) and out["resolution"] == "applied_as"
    assert await _count(db_session, ExportEvent) == exports + 1
    tx = (await db_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == new_id))).scalar_one()
    assert str(tx.borrower_user_id) == ctx["staff_id"]  # recorded operator = original
    eq = await db_session.get(Equipment, uuid.UUID(ctx["eq"]))
    await db_session.refresh(eq)
    assert eq.status == EquipmentStatus.ISSUED_TO_WARD
    borrow_log = (await db_session.execute(select(AuditLog).where(AuditLog.action == "borrow", AuditLog.entity_id == new_id))).scalar_one()
    assert str(borrow_log.user_id) == ctx["admin_id"]
    assert borrow_log.after_data["original_user_id"] == ctx["staff_id"] and borrow_log.after_data["resolves_op_id"] == op2["op_id"]
    hist = (await db_session.execute(
        select(EquipmentStatusHistory).where(EquipmentStatusHistory.equipment_id == eq.id).order_by(EquipmentStatusHistory.changed_at.desc())
    )).scalars().first()
    assert str(hist.changed_by_user_id) == ctx["admin_id"]
    res = (await db_session.execute(select(AuditLog).where(AuditLog.action == "sync_conflict_resolved"))).scalar_one()
    assert str(res.user_id) == ctx["admin_id"] and res.after_data["new_op_id"] == str(new_id)
    orig = (await db_session.execute(select(ClientOperation).where(ClientOperation.op_id == uuid.UUID(op2["op_id"])))).scalar_one()
    await db_session.refresh(orig)
    assert orig.status == "resolved" and orig.resolution == "applied_as" and orig.resolution_note == str(new_id)
    assert str(orig.resolved_by) == ctx["admin_id"] and orig.user_id == uuid.UUID(ctx["staff_id"])
    new_row = (await db_session.execute(select(ClientOperation).where(ClientOperation.op_id == new_id))).scalar_one()
    assert new_row.status == "applied" and str(new_row.submitted_by_user_id) == ctx["admin_id"]
    # second apply cannot double-apply
    assert (await client.post(f"{C}/{op2['op_id']}/apply-now", headers=ctx["admin"])).status_code == 409
    assert await _count(db_session, ExportEvent) == exports + 1


async def test_apply_now_still_conflicting_stays_conflict(client, ctx, db_session):
    _, op2 = await _conflict(client, ctx)
    exports, txs = await _count(db_session, ExportEvent), await _count(db_session, BorrowTransaction)
    r = await client.post(f"{C}/{op2['op_id']}/apply-now", headers=ctx["staff"])
    assert r.status_code == 409 and r.json()["code"] == "SYNC_APPLY_FAILED"
    row = (await db_session.execute(select(ClientOperation).where(ClientOperation.op_id == uuid.UUID(op2["op_id"])))).scalar_one()
    await db_session.refresh(row)
    assert row.status == "conflict" and row.resolved_by is None and row.resolution_note == "apply_failed:EQUIPMENT_NOT_AVAILABLE"
    assert await _count(db_session, ExportEvent) == exports and await _count(db_session, BorrowTransaction) == txs
    assert await _count(db_session, AuditLog, AuditLog.action == "sync_conflict_resolved") == 0
    # the reason is refreshed when the cause changes (ward vanished from payload)
    await db_session.execute(update(Equipment).values(status=EquipmentStatus.AVAILABLE_AT_POOL))
    await db_session.execute(update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(op2["op_id"])).values(
        payload={"op_type": "dispatch", "dispatch": {**row.payload["dispatch"], "ward_id": str(uuid.uuid4())}}))
    await db_session.commit()
    r = await client.post(f"{C}/{op2['op_id']}/apply-now", headers=ctx["staff"])
    assert r.status_code == 409
    await db_session.refresh(row)
    assert row.status == "conflict" and row.result_code == "INVALID_INPUT"


async def test_apply_now_receipt(client, ctx, db_session):
    op1 = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    await _send(client, ctx["staff"], op1)
    # expired pending receipt becomes reviewable, then applies against the now-known tx
    rc = receipt_op(ctx["staff_id"], str(uuid.uuid4()), seq=2)
    await _send(client, ctx["staff"], rc)
    await db_session.execute(update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(rc["op_id"]))
        .values(first_seen_at=datetime.now(timezone.utc) - timedelta(hours=49)))
    await db_session.commit()
    await db_session.execute(update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(rc["op_id"])).values(
        payload={"op_type": "receipt", "receipt": {"transaction_id": op1["op_id"], "receipt_outcome": "defective", "notes": None}}))
    await db_session.commit()
    r = await client.post(f"{C}/{rc['op_id']}/apply-now", headers=ctx["admin"])
    assert r.status_code == 200, r.text
    tx = await db_session.get(BorrowTransaction, uuid.UUID(op1["op_id"]))
    await db_session.refresh(tx)
    assert tx.status.value == "closed" and str(tx.received_by_user_id) == ctx["staff_id"]
    eq = await db_session.get(Equipment, uuid.UUID(ctx["eq"]))
    await db_session.refresh(eq)
    assert eq.status == EquipmentStatus.UNAVAILABLE_DEFECTIVE


async def test_op_too_old_uses_stored_occurred_at(client, ctx, db_session):
    op1, op2 = await _conflict(client, ctx)
    await _free_equipment(client, ctx, op1)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    await db_session.execute(update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(op2["op_id"]))
        .values(result_code="OP_TOO_OLD", occurred_at=old))
    await db_session.commit()
    # relational guard: the latest receipt of this equipment is newer -> clamped up to it
    r = await client.post(f"{C}/{op2['op_id']}/apply-now", headers=ctx["admin"])
    assert r.status_code == 200, r.text
    tx = await db_session.get(BorrowTransaction, uuid.UUID(r.json()["new_op_id"]))
    last = (await db_session.execute(select(func.max(BorrowTransaction.returned_at)))).scalar_one()
    assert tx.borrowed_at.replace(tzinfo=timezone.utc) >= old and tx.borrowed_at.replace(tzinfo=timezone.utc) >= last.replace(tzinfo=timezone.utc)


async def test_op_too_old_unclamped_when_no_guard(client, ctx, db_session):
    eq = ctx["eq"]
    bad = dispatch_op(ctx["staff_id"], str(uuid.uuid4()), ctx["ward"], seq=1)
    await _send(client, ctx["staff"], bad)  # EQUIPMENT_NOT_FOUND conflict
    old = datetime.now(timezone.utc) - timedelta(days=10)
    body = {"op_type": "dispatch", "dispatch": {**bad["dispatch"], "equipment_id": eq}}
    await db_session.execute(update(ClientOperation).where(ClientOperation.op_id == uuid.UUID(bad["op_id"]))
        .values(result_code="OP_TOO_OLD", occurred_at=old, payload=body))
    await db_session.commit()
    d = (await client.get(f"{C}/{bad['op_id']}", headers=ctx["admin"])).json()
    assert d["occurred_at"] is not None and d["result_code"] == "OP_TOO_OLD"
    r = await client.post(f"{C}/{bad['op_id']}/apply-now", headers=ctx["admin"])
    assert r.status_code == 200, r.text
    tx = await db_session.get(BorrowTransaction, uuid.UUID(r.json()["new_op_id"]))
    assert abs(tx.borrowed_at.replace(tzinfo=timezone.utc) - old) < timedelta(seconds=1)
