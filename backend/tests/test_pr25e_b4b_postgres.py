"""Roadmap PR25E slice B4b: PostgreSQL evidence that two resolvers submitting
the SAME Apply sequence concurrently apply each op exactly once.

    POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://... pytest -q -m postgres tests/test_pr25e_b4b_postgres.py
"""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.core.exceptions import DomainError
from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.export import ExportEvent
from app.models.transaction import BorrowTransaction
from app.services import sync_service, sync_timeline_service
from tests.test_pr25e_b2_postgres import _U, _dispatch, _receipt, maker, world  # noqa: F401
from tests.test_postgres_integration import pg_engine, pg_seeded_users, pg_session, pg_transaction_seq  # noqa: F401

pytestmark = pytest.mark.postgres


async def _count(maker, model, *where):
    async with maker() as db:
        q = select(func.count()).select_from(model)
        for w in where:
            q = q.where(w)
        return (await db.execute(q)).scalar_one()


async def _setup(maker, world):
    """op1 dispatches; op2 (dispatch) conflicts; op1 is received; the
    sequence [op2, receipt-of-op2] is then lifecycle-valid."""
    op1, op2 = _dispatch(world, seq=1), _dispatch(world, seq=2)
    async with maker() as db:
        assert (await sync_service.process_operation(db, op1, _U(world["user"]))).result == "applied"
    async with maker() as db:
        assert (await sync_service.process_operation(db, op2, _U(world["user"]))).result == "conflict"
    async with maker() as db:
        assert (await sync_service.process_operation(db, _receipt(world, op1.op_id, seq=3), _U(world["user"]))).result == "applied"
    # a receipt for op2's future transaction, reviewable (expired pending)
    op3 = _receipt(world, op2.op_id, seq=4)
    async with maker() as db:
        assert (await sync_service.process_operation(db, op3, _U(world["user"]))).result == "retry_later"
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update

    async with maker() as db:
        await db.execute(
            update(ClientOperation).where(ClientOperation.op_id == op3.op_id)
            .values(first_seen_at=datetime.now(timezone.utc) - timedelta(hours=49))
        )
        await db.commit()
    return op2, op3


async def _run(maker, world, eq_id, ids):
    async with maker() as db:
        try:
            return await sync_timeline_service.apply_sequence(db, eq_id, ids, world["user"], is_admin=True)
        except DomainError as exc:
            return exc


@pytest.mark.parametrize("round_", range(4))
async def test_concurrent_identical_sequences_apply_once(maker, world, round_):
    op2, op3 = await _setup(maker, world)
    async with maker() as db:
        eq_id = (await db.execute(select(BorrowTransaction.equipment_id).limit(1))).scalar_one()
    exports = await _count(maker, ExportEvent)
    res = await asyncio.gather(*[_run(maker, world, eq_id, [op2.op_id, op3.op_id]) for _ in range(3)])
    wins = [r for r in res if isinstance(r, dict) and len(r["steps"]) >= 1]
    # Each op is applied by exactly one request, however the steps interleave.
    applied = [s["op_id"] for r in wins for s in r["steps"]]
    assert sorted(applied, key=str) == sorted([op2.op_id, op3.op_id], key=str), res
    assert await _count(maker, ExportEvent) == exports + 2
    assert await _count(maker, BorrowTransaction) == 2
    assert await _count(maker, AuditLog, AuditLog.action == "sync_conflict_resolved") == 2
    assert await _count(maker, ClientOperation, ClientOperation.resolution == "applied_as") == 2
