"""Roadmap PR25E slice B2c: adoption (Owner decision D4) and ``stale_context``
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 8.3, 9.8)."""
import pytest
from sqlalchemy import func, select

from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.equipment import EquipmentStatusHistory
from app.models.export import ExportEvent
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers
from tests.test_pr25e_b2_sync_ops import _send, _user, ctx, dispatch_op, receipt_op  # noqa: F401

pytestmark = pytest.mark.asyncio


def adopt(op):
    return {**op, "adopt": True, "original_user_id": op["user_id"]}


async def test_adoption_records_original_operator_and_adopter_actor(client, ctx, db_session):
    op = adopt(dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"]))
    [res] = await _send(client, ctx["admin"], op)
    assert res["result"] == "applied" and res["transaction_id"] == op["op_id"]

    tx = (await db_session.execute(select(BorrowTransaction))).scalar_one()
    assert str(tx.borrower_user_id) == ctx["staff_id"]  # recorded operator
    row = (await db_session.execute(select(ClientOperation))).scalar_one()
    assert str(row.user_id) == ctx["staff_id"]
    assert str(row.submitted_by_user_id) == ctx["admin_id"] and row.adopted_at is not None

    borrow = (await db_session.execute(select(AuditLog).where(AuditLog.action == "borrow"))).scalar_one()
    assert str(borrow.user_id) == ctx["admin_id"]
    assert borrow.after_data["adopted"] is True
    assert borrow.after_data["original_user_id"] == ctx["staff_id"]
    assert borrow.after_data["submitted_by_user_id"] == ctx["admin_id"]
    adopt_audit = (await db_session.execute(select(AuditLog).where(AuditLog.action == "sync_adopt"))).scalar_one()
    assert str(adopt_audit.user_id) == ctx["admin_id"]
    assert adopt_audit.after_data["original_user_ids"] == [ctx["staff_id"]]
    assert adopt_audit.after_data["op_ids"] == [op["op_id"]]
    hist = (await db_session.execute(select(EquipmentStatusHistory))).scalars().all()
    assert hist and all(str(h.changed_by_user_id) == ctx["admin_id"] for h in hist)
    assert (await db_session.execute(select(func.count()).select_from(ExportEvent))).scalar_one() == 1


async def test_adopted_receipt_keeps_original_receiver(client, ctx, db_session):
    d = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], d)
    r = adopt(receipt_op(ctx["staff_id"], d["op_id"], device_id=d["device_id"]))
    [res] = await _send(client, ctx["admin"], r)
    assert res["result"] == "applied"
    tx = (await db_session.execute(select(BorrowTransaction))).scalar_one()
    assert str(tx.received_by_user_id) == ctx["staff_id"]
    ret = (await db_session.execute(select(AuditLog).where(AuditLog.action == "return"))).scalar_one()
    assert str(ret.user_id) == ctx["admin_id"]


async def test_adoption_replay_is_duplicate_and_writes_nothing_more(client, ctx, db_session):
    op = adopt(dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"]))
    await _send(client, ctx["admin"], op)
    [res] = await _send(client, ctx["admin"], op)
    assert res["result"] == "duplicate"
    # The original operator's own plain retry is also a duplicate.
    plain = {k: v for k, v in op.items() if k not in ("adopt", "original_user_id")}
    [res] = await _send(client, ctx["staff"], plain)
    assert res["result"] == "duplicate"
    for model, where in ((AuditLog, AuditLog.action == "sync_adopt"), (AuditLog, AuditLog.action == "borrow"), (ExportEvent, True)):
        n = (await db_session.execute(select(func.count()).select_from(model).where(where))).scalar_one()
        assert n == 1


async def test_mismatch_without_adoption_still_rejected(client, ctx, db_session):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    [res] = await _send(client, ctx["admin"], op)
    assert res["code"] == "OP_USER_MISMATCH"
    assert (await db_session.execute(select(func.count()).select_from(ClientOperation))).scalar_one() == 0


async def test_non_staff_adopter_rejected(client, ctx, seeded_users):
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    op = adopt(dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"]))
    r = await client.post("/api/v1/sync/operations", headers=ro, json={"operations": [op]})
    assert r.status_code == 403


async def test_adopting_non_pool_or_unknown_or_self_rejected(client, ctx, seeded_users, db_session):
    ro_id = str(seeded_users[ROLE_READ_ONLY].id)
    unknown = "00000000-0000-4000-8000-000000000001"
    cases = [ro_id, unknown, ctx["admin_id"]]  # read-only, unknown, self
    for i, uid in enumerate(cases):
        [res] = await _send(client, ctx["admin"], adopt(dispatch_op(uid, ctx["eq"], ctx["ward"], seq=i + 1)))
        assert res["result"] == "rejected" and res["code"] == "OP_USER_MISMATCH"
    assert (await db_session.execute(select(func.count()).select_from(ClientOperation))).scalar_one() == 0


async def test_adoption_cannot_hijack_other_users_ledger_row(client, ctx, seeded_users):
    # Row owned by staff; admin "adopts" it claiming a different original.
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], op)
    claim = adopt({**op, "user_id": ctx["admin_id"]})
    [res] = await _send(client, ctx["admin"], claim)
    assert res["code"] == "OP_USER_MISMATCH"  # self-adoption refused, reveals nothing
    third = str(seeded_users[ROLE_READ_ONLY].id)
    [res] = await _send(client, ctx["admin"], adopt({**op, "user_id": third}))
    assert res["code"] == "OP_USER_MISMATCH" and res["transaction_id"] is None


async def test_envelope_adopt_fields_validated(client, ctx):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    for bad in (
        {**op, "adopt": True},  # missing original_user_id
        {**op, "original_user_id": ctx["staff_id"]},  # original without adopt
        {**op, "adopt": True, "original_user_id": ctx["admin_id"]},  # differs from user_id
        {**op, "unknown_field": 1},
    ):
        await _send(client, ctx["admin"], bad, expect=422)


async def test_stale_context_server_decides(client, ctx, db_session):
    fresh = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    fresh["snapshot_age_s"] = 4 * 3600
    stale = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=2)
    stale["snapshot_age_s"] = 4 * 3600 + 1
    [r1, r2] = await _send(client, ctx["staff"], fresh, stale)
    assert r1["result"] == "applied"
    assert r2["result"] == "conflict"  # equipment already out; flag persists on conflict rows too
    rows = {str(r.op_id): r for r in (await db_session.execute(select(ClientOperation))).scalars()}
    assert rows[fresh["op_id"]].stale_context is False
    assert rows[stale["op_id"]].stale_context is True


async def test_stale_context_applied_op_is_flagged_not_blocked(client, ctx, db_session):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    op["snapshot_age_s"] = 10 * 3600
    [res] = await _send(client, ctx["staff"], op)
    assert res["result"] == "applied"
    row = (await db_session.execute(select(ClientOperation))).scalar_one()
    assert row.stale_context is True
