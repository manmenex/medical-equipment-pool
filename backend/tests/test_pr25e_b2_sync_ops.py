"""Roadmap PR25E slice B2: POST /api/v1/sync/operations (SQLite; PostgreSQL
concurrency evidence lives in test_pr25e_b2_postgres.py)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crud import client_operation as client_op_crud
from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.equipment import Equipment, EquipmentStatus
from app.models.export import ExportEvent
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, User
from app.schemas.sync import SyncOperation
from app.services import borrow_service, sync_service
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio

URL = "/api/v1/sync/operations"


async def _user(client, headers) -> str:
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return me.json()["id"]


async def _equipment(client, admin, n=1):
    r = await client.post("/api/v1/equipment", headers=admin, json={"asset_number": f"AST-B2-{n}", "equipment_name": "Pump"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _ward(client, admin, code="W-B2"):
    r = await client.post("/api/v1/wards", headers=admin, json={"code": code, "name": code})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def dispatch_op(user_id, equipment_id, ward_id, *, seq=1, op_id=None, device_id=None, **extra):
    return {
        "op_id": op_id or str(uuid.uuid4()),
        "device_id": device_id or str(uuid.uuid4()),
        "device_seq": seq,
        "user_id": user_id,
        "op_type": "dispatch",
        "occurred_at_local": "2026-10-13T08:00:00Z",
        "clock_offset_ms": 0,
        "dispatch": {"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand", **extra},
    }


def receipt_op(user_id, tx_id, *, seq=2, op_id=None, device_id=None, outcome="usable"):
    return {
        "op_id": op_id or str(uuid.uuid4()),
        "device_id": device_id or str(uuid.uuid4()),
        "device_seq": seq,
        "user_id": user_id,
        "op_type": "receipt",
        "occurred_at_local": "2026-10-13T09:00:00Z",
        "receipt": {"transaction_id": str(tx_id), "receipt_outcome": outcome},
    }


async def _send(client, headers, *ops, expect=200):
    r = await client.post(URL, headers=headers, json={"operations": list(ops)})
    assert r.status_code == expect, r.text
    return r.json()["results"] if expect == 200 else r.json()


@pytest.fixture
async def ctx(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    return {
        "admin": admin,
        "staff": staff,
        "staff_id": await _user(client, staff),
        "admin_id": await _user(client, admin),
        "ward": await _ward(client, admin),
        "eq": await _equipment(client, admin),
    }


async def _count(db, model, *where):
    q = select(func.count()).select_from(model)
    for w in where:
        q = q.where(w)
    return (await db.execute(q)).scalar_one()


async def test_dispatch_applied_ledger_audit_export(client, ctx, db_session):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    [res] = await _send(client, ctx["staff"], op)
    assert res["result"] == "applied" and res["transaction_id"] == op["op_id"]

    tx = (await db_session.execute(select(BorrowTransaction))).scalar_one()
    assert str(tx.id) == op["op_id"] and str(tx.borrower_user_id) == ctx["staff_id"]
    row = (await db_session.execute(select(ClientOperation))).scalar_one()
    assert row.status == "applied" and str(row.submitted_by_user_id) == ctx["staff_id"]
    assert row.transaction_id == tx.id and row.payload["op_type"] == "dispatch"
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.action == "borrow"))).scalar_one()
    assert str(audit.user_id) == ctx["staff_id"]
    assert audit.after_data["op_id"] == op["op_id"] and audit.after_data["device_seq"] == 1
    assert await _count(db_session, ExportEvent) == 1


async def test_sequential_duplicate_dispatch(client, ctx, db_session):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], op)
    [res] = await _send(client, ctx["staff"], op)
    assert res["result"] == "duplicate" and res["transaction_id"] == op["op_id"]
    assert await _count(db_session, BorrowTransaction) == 1
    assert await _count(db_session, AuditLog, AuditLog.action == "borrow") == 1
    assert await _count(db_session, ExportEvent) == 1
    assert await _count(db_session, ClientOperation) == 1


async def test_user_mismatch_reveals_nothing(client, ctx, db_session):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], op)
    # Another pool user replays the op_id (naming the original user or themselves).
    for env_user in (ctx["staff_id"], ctx["admin_id"]):
        replay = {**op, "user_id": env_user}
        [res] = await _send(client, ctx["admin"], replay)
        assert res["result"] == "rejected" and res["code"] == "OP_USER_MISMATCH"
        assert res["transaction_id"] is None and op["op_id"] not in res["message"]
    # Even a changed payload from the wrong user must not leak OP_ID_REUSED.
    other = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], op_id=op["op_id"], notes="x")
    [res] = await _send(client, ctx["admin"], other)
    assert res["code"] == "OP_USER_MISMATCH"
    assert await _count(db_session, ClientOperation) == 1


async def test_envelope_user_not_token_user_rejected_without_ledger(client, ctx, db_session):
    op = dispatch_op(ctx["admin_id"], ctx["eq"], ctx["ward"])
    [res] = await _send(client, ctx["staff"], op)
    assert res["code"] == "OP_USER_MISMATCH"
    assert await _count(db_session, ClientOperation) == 0 and await _count(db_session, BorrowTransaction) == 0


async def test_op_id_reused_with_different_payload(client, ctx, db_session):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    await _send(client, ctx["staff"], op)
    changed = {**op, "dispatch": {**op["dispatch"], "notes": "different"}}
    [res] = await _send(client, ctx["staff"], changed)
    assert res["result"] == "rejected" and res["code"] == "OP_ID_REUSED"
    assert await _count(db_session, ClientOperation) == 1


async def test_device_seq_reused_by_other_op(client, ctx, db_session):
    dev = str(uuid.uuid4())
    await _send(client, ctx["staff"], dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=7, device_id=dev))
    eq2 = await _equipment(client, ctx["admin"], 2)
    [res] = await _send(client, ctx["staff"], dispatch_op(ctx["staff_id"], eq2, ctx["ward"], seq=7, device_id=dev))
    assert res["result"] == "rejected" and res["code"] == "DEVICE_SEQ_REUSED"
    assert await _count(db_session, BorrowTransaction) == 1


async def test_receipt_applied_duplicate_and_second_receipt_conflict(client, ctx, db_session):
    d = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    r1 = receipt_op(ctx["staff_id"], d["op_id"])
    r2 = receipt_op(ctx["staff_id"], d["op_id"], outcome="defective")
    res = await _send(client, ctx["staff"], d, r1)
    assert [x["result"] for x in res] == ["applied", "applied"]
    assert (await _send(client, ctx["staff"], r1))[0]["result"] == "duplicate"
    [c] = await _send(client, ctx["staff"], r2)
    assert c["result"] == "conflict" and c["code"] == "TRANSACTION_ALREADY_RETURNED"
    # Re-send of the conflicting op returns the stored result, no re-run.
    [c2] = await _send(client, ctx["staff"], r2)
    assert c2["result"] == "conflict" and c2["code"] == "TRANSACTION_ALREADY_RETURNED"
    crow = await client_op_crud.get(db_session, uuid.UUID(r2["op_id"]))
    assert crow.status == "conflict" and crow.payload["receipt"]["receipt_outcome"] == "defective"
    eq = await db_session.get(Equipment, uuid.UUID(ctx["eq"]))
    await db_session.refresh(eq)
    assert eq.status == EquipmentStatus.AVAILABLE_AT_POOL  # first (usable) receipt stands
    assert await _count(db_session, ExportEvent) == 2


async def test_dispatch_conflict_row_and_no_export(client, ctx, db_session):
    await _send(client, ctx["staff"], dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"]))
    loser = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=2)
    [res] = await _send(client, ctx["staff"], loser)
    assert res["result"] == "conflict" and res["code"] == "EQUIPMENT_NOT_AVAILABLE"
    row = await client_op_crud.get(db_session, uuid.UUID(loser["op_id"]))
    assert row.status == "conflict" and row.payload["dispatch"]["equipment_id"] == ctx["eq"]
    assert await _count(db_session, BorrowTransaction) == 1
    assert await _count(db_session, ExportEvent) == 1
    assert await _count(db_session, AuditLog, AuditLog.action == "borrow") == 1


@pytest.mark.parametrize(
    "mutate,code",
    [
        (lambda o, c: o["dispatch"].update(equipment_id=str(uuid.uuid4())), "EQUIPMENT_NOT_FOUND"),
        (lambda o, c: o["dispatch"].update(ward_id=str(uuid.uuid4())), "INVALID_INPUT"),
    ],
)
async def test_dispatch_conflict_matrix(client, ctx, db_session, mutate, code):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    mutate(op, ctx)
    [res] = await _send(client, ctx["staff"], op)
    assert res["result"] == "conflict" and res["code"] == code
    assert await _count(db_session, BorrowTransaction) == 0 and await _count(db_session, ExportEvent) == 0


async def test_retry_later_then_pending_applied_exactly_once(client, ctx, db_session):
    d_op = str(uuid.uuid4())
    r = receipt_op(ctx["staff_id"], d_op)
    [res] = await _send(client, ctx["staff"], r)
    assert res["result"] == "retry_later" and res["code"] == "DEPENDENCY_MISSING"
    row = await client_op_crud.get(db_session, uuid.UUID(r["op_id"]))
    assert row.status == "pending" and row.attempt_count == 1
    first_seen = row.first_seen_at
    [res] = await _send(client, ctx["staff"], r)  # still not duplicate
    assert res["result"] == "retry_later"
    await db_session.refresh(row)
    assert row.attempt_count == 2 and row.first_seen_at == first_seen
    assert await _count(db_session, ExportEvent) == 0

    # The dispatch replays (same id the receipt targets), then the receipt applies.
    d = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], op_id=d_op)
    assert (await _send(client, ctx["staff"], d))[0]["result"] == "applied"
    [res] = await _send(client, ctx["staff"], r)
    assert res["result"] == "applied" and res["transaction_id"] == d_op
    assert await _count(db_session, ClientOperation, ClientOperation.op_id == uuid.UUID(r["op_id"])) == 1
    await db_session.refresh(row)
    assert row.status == "applied" and row.attempt_count == 3 and row.first_seen_at == first_seen
    assert await _count(db_session, ExportEvent) == 2
    assert (await _send(client, ctx["staff"], r))[0]["result"] == "duplicate"
    assert await _count(db_session, ExportEvent) == 2


async def test_pending_past_48h_becomes_conflict(client, ctx, db_session):
    r = receipt_op(ctx["staff_id"], str(uuid.uuid4()))
    await _send(client, ctx["staff"], r)
    await db_session.execute(
        update(ClientOperation).values(first_seen_at=datetime.now(timezone.utc) - timedelta(hours=49))
    )
    await db_session.commit()
    [res] = await _send(client, ctx["staff"], r)
    assert res["result"] == "conflict" and res["code"] == "TRANSACTION_NOT_FOUND"
    row = await client_op_crud.get(db_session, uuid.UUID(r["op_id"]))
    await db_session.refresh(row)
    assert row.status == "conflict" and row.attempt_count == 2
    assert (await _send(client, ctx["staff"], r))[0]["result"] == "conflict"
    assert await _count(db_session, ExportEvent) == 0


async def test_batch_processed_in_device_seq_order(client, ctx, db_session):
    dev = str(uuid.uuid4())
    d = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1, device_id=dev)
    r = receipt_op(ctx["staff_id"], d["op_id"], seq=2, device_id=dev)
    res = await _send(client, ctx["staff"], r, d)  # submitted out of order
    assert [x["op_id"] for x in res] == [d["op_id"], r["op_id"]]
    assert [x["result"] for x in res] == ["applied", "applied"]


async def test_envelope_is_strict_and_bounded(client, ctx):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    for bad in (
        {**op, "equipment_status": "available_at_pool"},
        {**op, "status": "closed"},
        {**op, "dispatch": {**op["dispatch"], "quantity": 2}},
        {**op, "op_type": "receipt"},
        {**op, "op_id": str(uuid.uuid1())},
    ):
        r = await client.post(URL, headers=ctx["staff"], json={"operations": [bad]})
        assert r.status_code == 422, bad
    r = await client.post(URL, headers=ctx["staff"], json={"operations": [], "x": 1})
    assert r.status_code == 422
    many = [dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=i) for i in range(26)]
    assert (await client.post(URL, headers=ctx["staff"], json={"operations": many})).status_code == 422
    huge = {**op, "dispatch": {**op["dispatch"], "notes": "x" * 9000}}
    assert (await client.post(URL, headers=ctx["staff"], json={"operations": [huge]})).status_code == 422


async def test_rbac(client, ctx):
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"])
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    assert (await client.post(URL, headers=ro, json={"operations": [op]})).status_code == 403
    assert (await client.post(URL, json={"operations": [op]})).status_code == 401
    admin_op = dispatch_op(ctx["admin_id"], ctx["eq"], ctx["ward"])
    assert (await _send(client, ctx["admin"], admin_op))[0]["result"] == "applied"


# ---- service-level: atomicity, write order, actor split --------------------


async def _seed(db: AsyncSession):
    ward = Ward(code="WS", name="WS")
    eq = Equipment(asset_number="AST-SVC", equipment_name="Pump")
    db.add_all([ward, eq])
    await db.commit()
    return ward, eq


def _sync_op(user: User, ward, eq) -> SyncOperation:
    return SyncOperation.model_validate(dispatch_op(str(user.id), str(eq.id), str(ward.id)))


async def test_failure_after_ledger_write_rolls_everything_back(db_engine, seeded_users, monkeypatch):
    maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as db:
        ward, eq = await _seed(db)
    user = seeded_users[ROLE_EQUIPMENT_POOL_STAFF]

    async def boom(*a, **k):
        raise RuntimeError("injected after ledger write")

    monkeypatch.setattr(borrow_service.export_service, "record_event", boom)
    async with maker() as db:
        with pytest.raises(RuntimeError):
            await sync_service.process_operation(db, _sync_op(user, ward, eq), user)
    async with maker() as db:
        for model in (ClientOperation, BorrowTransaction, ExportEvent, AuditLog):
            assert await _count(db, model) == 0, model
        assert (await db.get(Equipment, eq.id)).status == EquipmentStatus.AVAILABLE_AT_POOL


async def test_ledger_written_before_record_event(db_engine, seeded_users, monkeypatch):
    maker = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as db:
        ward, eq = await _seed(db)
    user = seeded_users[ROLE_EQUIPMENT_POOL_STAFF]
    order: list[str] = []
    real_applied = client_op_crud.write_applied
    real_event = borrow_service.export_service.record_event

    async def applied(*a, **k):
        order.append("ledger")
        return await real_applied(*a, **k)

    async def event(*a, **k):
        order.append("export")
        return await real_event(*a, **k)

    monkeypatch.setattr(client_op_crud, "write_applied", applied)
    monkeypatch.setattr(borrow_service.export_service, "record_event", event)
    async with maker() as db:
        res = await sync_service.process_operation(db, _sync_op(user, ward, eq), user)
    assert res.result == "applied" and order == ["ledger", "export"]


async def test_actor_defaults_to_operator_and_can_differ(db_session, seeded_users):
    ward, eq = await _seed(db_session)
    staff, admin = seeded_users[ROLE_EQUIPMENT_POOL_STAFF], seeded_users[ROLE_ADMINISTRATOR]
    common = dict(
        ward_id=str(ward.id), dispatch_type=__import__("app.models.transaction", fromlist=["DispatchType"]).DispatchType.ON_DEMAND,
        routine_round=None, department_id=None, phone_number=None, pickup_location_id=None,
        dropoff_location_id=None, notes=None, ip_address=None, user_agent=None,
    )
    tx = await borrow_service.borrow(db_session, equipment_id=str(eq.id), borrower_user_id=staff.id, **common)
    audit = (await db_session.execute(select(AuditLog).where(AuditLog.entity_id == tx.id))).scalar_one()
    assert audit.user_id == staff.id and "op_id" not in audit.after_data
    await borrow_service.return_equipment(
        db_session, transaction_id=tx.id, receipt_outcome=__import__("app.models.transaction", fromlist=["ReceiptOutcome"]).ReceiptOutcome.USABLE,
        notes=None, received_by_user_id=staff.id, actor_user_id=admin.id, ip_address=None, user_agent=None,
    )
    ret = (await db_session.execute(select(AuditLog).where(AuditLog.action == "return"))).scalar_one()
    assert ret.user_id == admin.id
    await db_session.refresh(tx)
    assert tx.received_by_user_id == staff.id


async def test_s6_envelope_version_compat(client, ctx, db_session):
    """S6: a missing envelope_version (queued before S6) is version 1 and
    accepted; explicit 1 is accepted; 0 is CLIENT_TOO_OLD (426); a future
    version is ENVELOPE_VERSION_UNSUPPORTED (400). Rejections write nothing."""
    ledger_before = await _count(db_session, ClientOperation)
    old = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], seq=1)
    assert "envelope_version" not in old
    assert (await _send(client, ctx["staff"], old))[0]["result"] == "applied"

    eq2 = await _equipment(client, ctx["admin"], n=2)
    v1 = dispatch_op(ctx["staff_id"], eq2, ctx["ward"], seq=1, device_id=old["device_id"])
    v1["device_seq"] = 2
    v1["envelope_version"] = 1
    assert (await _send(client, ctx["staff"], v1))[0]["result"] == "applied"

    count_after_ok = await _count(db_session, ClientOperation)
    assert count_after_ok == ledger_before + 2

    eq3 = await _equipment(client, ctx["admin"], n=3)
    too_old = dispatch_op(ctx["staff_id"], eq3, ctx["ward"], seq=1)
    too_old["envelope_version"] = 0
    body = await _send(client, ctx["staff"], too_old, expect=426)
    assert body["code"] == "CLIENT_TOO_OLD"

    future = dispatch_op(ctx["staff_id"], eq3, ctx["ward"], seq=1)
    future["envelope_version"] = 2
    body = await _send(client, ctx["staff"], future, expect=400)
    assert body["code"] == "ENVELOPE_VERSION_UNSUPPORTED"

    # One bad op rejects the whole request: the good op in the batch is not applied.
    good = dispatch_op(ctx["staff_id"], eq3, ctx["ward"], seq=1)
    await _send(client, ctx["staff"], good, future, expect=400)
    assert await _count(db_session, ClientOperation) == count_after_ok
