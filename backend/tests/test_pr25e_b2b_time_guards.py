"""Roadmap PR25E slice B2b: business-time guards for POST /sync/operations
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md section 11, test item 8)."""
import uuid
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.reporting_time import Shift, business_date_and_shift
from app.models.client_operation import ClientOperation
from app.models.export import ExportEvent
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF
from app.schemas.sync import SyncOperation
from app.services import sync_service
from app.services.sync_service import compute_business_time
from tests.conftest import auth_headers as _auth_headers
from tests.test_pr25e_b2_sync_ops import _equipment, _send, _user, _ward, dispatch_op, receipt_op

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture
async def ctx(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    return {
        "admin": admin,
        "staff": staff,
        "staff_id": await _user(client, staff),
        "ward": await _ward(client, admin, "W-B2B"),
        "eq": await _equipment(client, admin, 7),
    }


def _op(ctx, local: datetime, offset=0, **kw) -> dict:
    op = dispatch_op(ctx["staff_id"], ctx["eq"], ctx["ward"], **kw)
    op["occurred_at_local"] = iso(local)
    op["clock_offset_ms"] = offset
    return op


async def _ledger(db_session, op_id):
    return (await db_session.execute(select(ClientOperation).where(ClientOperation.op_id == uuid.UUID(op_id)))).scalar_one()


async def _tx(db_session, op_id):
    await db_session.rollback()
    row = (
        await db_session.execute(
            select(BorrowTransaction.borrowed_at, BorrowTransaction.returned_at).where(
                BorrowTransaction.id == uuid.UUID(op_id)
            )
        )
    ).one()
    return SimpleNamespace(borrowed_at=row.borrowed_at, returned_at=row.returned_at)


# ---- pure boundary / offset behaviour (fixed received_at) ----

async def _compute(db_session, local, offset=0, ctx_ids=None):
    op = SyncOperation.model_validate(
        {
            "op_id": str(uuid.uuid4()), "device_id": str(uuid.uuid4()), "device_seq": 1,
            "user_id": str(uuid.uuid4()), "op_type": "dispatch",
            "occurred_at_local": iso(local), "clock_offset_ms": offset,
            "dispatch": {"equipment_id": str(uuid.uuid4()), "ward_id": str(uuid.uuid4()), "dispatch_type": "on_demand"},
        }
    )
    return await compute_business_time(db_session, op, NOW)


async def test_in_window_time_is_kept_and_unflagged(db_session):
    t = NOW - timedelta(hours=3)
    assert await _compute(db_session, t) == (t, None)


async def test_offset_is_added(db_session):
    local = NOW - timedelta(hours=3)
    t, flag = await _compute(db_session, local, offset=90_000)
    assert t == local + timedelta(seconds=90) and flag is None
    t, _ = await _compute(db_session, local, offset=-90_000)
    assert t == local - timedelta(seconds=90)


async def test_offset_pushes_into_future_clamp(db_session):
    # device clock 1h slow; offset +1h puts the op after now+2min
    t, flag = await _compute(db_session, NOW - timedelta(minutes=10), offset=3_600_000)
    assert (t, flag) == (NOW, "clamped_future")


async def test_future_boundary_exactly_two_minutes_not_clamped(db_session):
    edge = NOW + timedelta(minutes=2)
    assert await _compute(db_session, edge) == (edge, None)
    t, flag = await _compute(db_session, edge + timedelta(milliseconds=1))
    assert (t, flag) == (NOW, "clamped_future")


async def test_old_boundary_exactly_seven_days_not_clamped(db_session):
    edge = NOW - timedelta(days=7)
    assert await _compute(db_session, edge) == (edge, None)
    t, flag = await _compute(db_session, edge - timedelta(milliseconds=1))
    assert (t, flag) == (NOW, "clamped_old")


# ---- end to end through the endpoint ----

async def test_future_clamped_end_to_end(client, ctx, db_session):
    before = datetime.now(timezone.utc)
    op = _op(ctx, before + timedelta(hours=5))
    [res] = await _send(client, ctx["staff"], op)
    assert res["result"] == "applied"
    tx = await _tx(db_session, op["op_id"])
    row = await _ledger(db_session, op["op_id"])
    assert row.time_flag == "clamped_future" and row.occurred_at == tx.borrowed_at
    assert before <= tx.borrowed_at <= datetime.now(timezone.utc)


async def test_old_clamped_end_to_end(client, ctx, db_session):
    op = _op(ctx, datetime.now(timezone.utc) - timedelta(days=8))
    await _send(client, ctx["staff"], op)
    tx = await _tx(db_session, op["op_id"])
    row = await _ledger(db_session, op["op_id"])
    assert row.time_flag == "clamped_old"
    assert datetime.now(timezone.utc) - tx.borrowed_at < timedelta(minutes=1)


async def test_backdated_within_window_uses_business_time_and_pr16_shift(client, ctx, db_session):
    # 22:00 Bangkok (15:00 UTC) yesterday = Night shift of yesterday's business date.
    now = datetime.now(timezone.utc)
    local = (now - timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
    op = _op(ctx, local)
    await _send(client, ctx["staff"], op)
    tx = await _tx(db_session, op["op_id"])
    row = await _ledger(db_session, op["op_id"])
    assert tx.borrowed_at == local and row.occurred_at == local and row.time_flag is None
    bd, shift = business_date_and_shift(tx.borrowed_at)
    assert shift == Shift.NIGHT and bd == (local + timedelta(hours=7)).date()
    assert row.received_at is not None and row.received_at > local


async def test_receipt_before_dispatch_clamped(client, ctx, db_session):
    d = _op(ctx, datetime.now(timezone.utc) - timedelta(hours=1))
    await _send(client, ctx["staff"], d)
    r = receipt_op(ctx["staff_id"], d["op_id"])
    r["occurred_at_local"] = iso(datetime.now(timezone.utc) - timedelta(hours=3))
    r["clock_offset_ms"] = 0
    [res] = await _send(client, ctx["staff"], r)
    assert res["result"] == "applied"
    tx = await _tx(db_session, d["op_id"])
    row = await _ledger(db_session, r["op_id"])
    assert row.time_flag == "before_dispatch"
    assert tx.returned_at == tx.borrowed_at == row.occurred_at


async def test_receipt_after_dispatch_keeps_time(client, ctx, db_session):
    now = datetime.now(timezone.utc)
    d = _op(ctx, now - timedelta(hours=3))
    await _send(client, ctx["staff"], d)
    r = receipt_op(ctx["staff_id"], d["op_id"])
    r["occurred_at_local"] = iso(now - timedelta(hours=2))
    r["clock_offset_ms"] = 0
    await _send(client, ctx["staff"], r)
    tx = await _tx(db_session, d["op_id"])
    assert tx.returned_at == now - timedelta(hours=2)
    assert (await _ledger(db_session, r["op_id"])).time_flag is None


async def test_dispatch_before_last_receipt_clamped_no_overlap(client, ctx, db_session):
    now = datetime.now(timezone.utc)
    d1 = _op(ctx, now - timedelta(hours=5))
    await _send(client, ctx["staff"], d1)
    r1 = receipt_op(ctx["staff_id"], d1["op_id"])
    r1["occurred_at_local"] = iso(now - timedelta(hours=2))
    r1["clock_offset_ms"] = 0
    await _send(client, ctx["staff"], r1)
    # Backdated dispatch overlapping the previous usage interval.
    d2 = _op(ctx, now - timedelta(hours=4), seq=3)
    [res] = await _send(client, ctx["staff"], d2)
    assert res["result"] == "applied"
    t1 = await _tx(db_session, d1["op_id"])
    t2 = await _tx(db_session, d2["op_id"])
    row = await _ledger(db_session, d2["op_id"])
    assert row.time_flag == "before_last_receipt"
    assert t2.borrowed_at == t1.returned_at == row.occurred_at
    # equal-to-last-receipt is not an overlap and not flagged
    r2 = receipt_op(ctx["staff_id"], d2["op_id"], seq=4)
    r2["occurred_at_local"] = iso(now - timedelta(hours=1))
    r2["clock_offset_ms"] = 0
    await _send(client, ctx["staff"], r2)
    d3 = _op(ctx, now - timedelta(hours=1), seq=5)
    await _send(client, ctx["staff"], d3)
    assert (await _ledger(db_session, d3["op_id"])).time_flag is None


async def test_flagged_op_never_blocks_and_offset_applied_end_to_end(client, ctx, db_session):
    local = datetime.now(timezone.utc) - timedelta(hours=6)
    op = _op(ctx, local, offset=30 * 60 * 1000)
    [res] = await _send(client, ctx["staff"], op)
    assert res["result"] == "applied"
    tx = await _tx(db_session, op["op_id"])
    assert tx.borrowed_at == local + timedelta(minutes=30)


async def test_online_endpoints_keep_server_time(client, ctx, db_session):
    before = datetime.now(timezone.utc)
    r = await client.post(
        "/api/v1/borrow", headers=ctx["staff"],
        json={"equipment_id": ctx["eq"], "ward_id": ctx["ward"], "dispatch_type": "on_demand"},
    )
    assert r.status_code in (200, 201), r.text
    tx_id = r.json()["id"]
    tx = await _tx(db_session, tx_id)
    assert before - timedelta(seconds=1) <= tx.borrowed_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    rr = await client.post(f"/api/v1/return/{tx_id}", headers=ctx["staff"], json={"receipt_outcome": "usable"})
    assert rr.status_code == 200, rr.text
    tx = await _tx(db_session, tx_id)
    assert before - timedelta(seconds=1) <= tx.returned_at <= datetime.now(timezone.utc) + timedelta(seconds=1)


async def test_export_event_time_is_business_time_seq_by_commit(client, ctx, db_session):
    now = datetime.now(timezone.utc)
    key_resp = await client.post("/api/v1/export-keys", headers=ctx["admin"], json={"name": "k"})
    key = {"X-API-Key": key_resp.json()["key"]}
    eq2 = await _equipment(client, ctx["admin"], 8)
    newer = _op(ctx, now - timedelta(hours=1))
    older = dispatch_op(ctx["staff_id"], eq2, ctx["ward"], seq=2)
    older["occurred_at_local"] = iso(now - timedelta(days=3))
    older["clock_offset_ms"] = 0
    await _send(client, ctx["staff"], newer)
    await _send(client, ctx["staff"], older)  # committed later, older business time
    ev = (await client.get("/api/v1/export/events", headers=key)).json()["events"]
    assert [e["transaction_id"] for e in ev] == [newer["op_id"], older["op_id"]]
    assert ev[0]["seq"] < ev[1]["seq"]
    t_old = datetime.fromisoformat(ev[1]["event_time"].replace("Z", "+00:00"))
    assert t_old.replace(tzinfo=t_old.tzinfo or timezone.utc) == now - timedelta(days=3) or abs(
        t_old.replace(tzinfo=t_old.tzinfo or timezone.utc) - (now - timedelta(days=3))
    ) < timedelta(seconds=1)
    assert ev[1]["event_time"] < ev[0]["event_time"]
