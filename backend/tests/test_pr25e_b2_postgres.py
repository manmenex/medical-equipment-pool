"""Roadmap PR25E slice B2: PostgreSQL concurrency evidence for
``sync_service.process_operation`` (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md
sections 6.3, 17 items 1, 11g, 11i). SQLite cannot show row-lock behaviour.

    POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://... pytest -q -m postgres tests/test_pr25e_b2_postgres.py
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.crud import client_operation as client_op_crud
from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.equipment import Equipment, EquipmentStatus
from app.models.export import ExportEvent
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_EQUIPMENT_POOL_STAFF
from app.schemas.sync import SyncOperation
from app.services import sync_service

from tests.test_postgres_integration import (  # noqa: F401
    pg_engine,
    pg_seeded_users,
    pg_session,
    pg_transaction_seq,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def maker(pg_engine):
    return async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture
async def world(maker, pg_seeded_users, pg_transaction_seq):
    async with maker() as db:
        ward = Ward(code="WP", name="WP")
        eq = Equipment(asset_number="AST-PG", equipment_name="Pump")
        db.add_all([ward, eq])
        await db.commit()
        return {"ward": str(ward.id), "eq": str(eq.id), "user": pg_seeded_users[ROLE_EQUIPMENT_POOL_STAFF].id}


def _recent(**delta):
    """ISO-8601 UTC timestamp relative to now, so ops stay inside the 7-day
    OP_TOO_OLD window however old the test run is (never hard-code dates)."""
    return (datetime.now(timezone.utc) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dispatch(world, *, op_id=None, seq=1, device=None, eq=None):
    return SyncOperation.model_validate(
        {
            "op_id": str(op_id or uuid.uuid4()),
            "device_id": str(device or uuid.uuid4()),
            "device_seq": seq,
            "user_id": str(world["user"]),
            "op_type": "dispatch",
            "occurred_at_local": _recent(hours=2),
            "dispatch": {"equipment_id": eq or world["eq"], "ward_id": world["ward"], "dispatch_type": "on_demand"},
        }
    )


def _receipt(world, tx_id, *, op_id=None, seq=2, device=None, outcome="usable"):
    return SyncOperation.model_validate(
        {
            "op_id": str(op_id or uuid.uuid4()),
            "device_id": str(device or uuid.uuid4()),
            "device_seq": seq,
            "user_id": str(world["user"]),
            "op_type": "receipt",
            "occurred_at_local": _recent(hours=1),
            "receipt": {"transaction_id": str(tx_id), "receipt_outcome": outcome},
        }
    )


class _U:
    def __init__(self, id):
        self.id = id


async def _run(maker, world, op):
    async with maker() as db:
        return await sync_service.process_operation(db, op, _U(world["user"]))


async def _count(maker, model, *where):
    async with maker() as db:
        q = select(func.count()).select_from(model)
        for w in where:
            q = q.where(w)
        return (await db.execute(q)).scalar_one()


async def _assert_one_applied_dispatch(maker, op):
    assert await _count(maker, BorrowTransaction) == 1
    assert await _count(maker, ClientOperation) == 1
    assert await _count(maker, AuditLog, AuditLog.action == "borrow") == 1
    assert await _count(maker, ExportEvent) == 1


@pytest.mark.parametrize("round_", range(5))
async def test_concurrent_identical_dispatch(maker, world, round_):
    op = _dispatch(world)
    results = await asyncio.gather(*[_run(maker, world, op) for _ in range(4)])
    kinds = sorted(r.result for r in results)
    assert kinds == ["applied", "duplicate", "duplicate", "duplicate"], results
    assert all(r.transaction_id == op.op_id for r in results)
    await _assert_one_applied_dispatch(maker, op)
    assert await _count(maker, ClientOperation, ClientOperation.status == "conflict") == 0


async def test_loser_with_stale_read_gets_duplicate_not_conflict(maker, world, monkeypatch):
    """Loser read the ledger (empty) BEFORE the winner committed, then fails
    before flush with EQUIPMENT_NOT_AVAILABLE: step 4 must re-read the ledger."""
    op = _dispatch(world)
    a_done = asyncio.Event()
    real_get = client_op_crud.get
    seen = {"b": False}

    async def get(db, op_id):
        row = await real_get(db, op_id)
        if getattr(db, "_is_b", False) and not seen["b"]:
            seen["b"] = True
            await a_done.wait()
        return row

    monkeypatch.setattr(client_op_crud, "get", get)

    async def loser():
        async with maker() as db:
            db._is_b = True
            return await sync_service.process_operation(db, op, _U(world["user"]))

    task = asyncio.create_task(loser())
    await asyncio.sleep(0.3)
    winner = await _run(maker, world, op)
    a_done.set()
    loser_res = await task
    assert winner.result == "applied" and loser_res.result == "duplicate"
    await _assert_one_applied_dispatch(maker, op)


async def test_different_ops_same_equipment_one_wins(maker, world):
    ops = [_dispatch(world, seq=i) for i in (1, 2)]
    results = await asyncio.gather(*[_run(maker, world, o) for o in ops])
    assert sorted(r.result for r in results) == ["applied", "conflict"]
    loser = next(r for r in results if r.result == "conflict")
    assert loser.code == "EQUIPMENT_NOT_AVAILABLE"
    assert await _count(maker, BorrowTransaction) == 1 and await _count(maker, ExportEvent) == 1
    async with maker() as db:
        row = await client_op_crud.get(db, loser.op_id)
        assert row.status == "conflict" and row.transaction_id is None


async def test_concurrent_receipts_different_ops_one_wins(maker, world):
    d = _dispatch(world)
    assert (await _run(maker, world, d)).result == "applied"
    rs = [_receipt(world, d.op_id, seq=i) for i in (2, 3)]
    results = await asyncio.gather(*[_run(maker, world, r) for r in rs])
    assert sorted(r.result for r in results) == ["applied", "conflict"]
    assert next(r for r in results if r.result == "conflict").code in ("RECEIPT_RACE_LOST", "TRANSACTION_ALREADY_RETURNED")
    assert await _count(maker, ExportEvent) == 2
    assert await _count(maker, AuditLog, AuditLog.action == "return") == 1


async def test_concurrent_retries_of_pending_apply_exactly_once(maker, world):
    d = _dispatch(world)
    r = _receipt(world, d.op_id)
    assert (await _run(maker, world, r)).result == "retry_later"
    assert (await _run(maker, world, d)).result == "applied"
    results = await asyncio.gather(*[_run(maker, world, r) for _ in range(4)])
    assert sorted(x.result for x in results) == ["applied", "duplicate", "duplicate", "duplicate"], results
    assert await _count(maker, ClientOperation, ClientOperation.op_id == r.op_id) == 1
    async with maker() as db:
        row = await client_op_crud.get(db, r.op_id)
        assert row.status == "applied"
    assert await _count(maker, ExportEvent) == 2
    assert await _count(maker, AuditLog, AuditLog.action == "return") == 1
    async with maker() as db:
        eq = await db.get(Equipment, uuid.UUID(world["eq"]))
        assert eq.status == EquipmentStatus.AVAILABLE_AT_POOL


async def test_conditional_pending_update_loses_when_row_already_moved(maker, world):
    """write_applied(pending=True) on a row that is no longer pending affects
    zero rows -> rolls back and raises (the section 6.3 step 2 guard)."""
    d = _dispatch(world)
    r = _receipt(world, d.op_id)
    await _run(maker, world, r)
    await _run(maker, world, d)
    await _run(maker, world, r)  # now applied
    ctx = client_op_crud.ClientOpContext(
        op_id=r.op_id, device_id=r.device_id, device_seq=r.device_seq, user_id=world["user"],
        submitted_by_user_id=world["user"], op_type="receipt", payload_hash="x" * 64, payload={}, pending=True,
    )
    async with maker() as db:
        with pytest.raises(client_op_crud.ClientOpAlreadyProcessedError):
            await client_op_crud.write_applied(db, ctx, transaction_id=d.op_id, occurred_at=None)
