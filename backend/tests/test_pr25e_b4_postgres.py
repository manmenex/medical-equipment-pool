"""Roadmap PR25E slice B4: PostgreSQL evidence that two resolvers racing on
one review item produce exactly one winner (design section 9.6).

    POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://... pytest -q -m postgres tests/test_pr25e_b4_postgres.py
"""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import SyncApplyFailedError, SyncOpNotResolvableError
from app.models.audit import AuditLog
from app.models.client_operation import ClientOperation
from app.models.export import ExportEvent
from app.models.transaction import BorrowTransaction
from app.services import sync_review_service
from tests.test_pr25e_b2_postgres import _U, _dispatch, _receipt, maker, world  # noqa: F401
from tests.test_postgres_integration import pg_engine, pg_seeded_users, pg_session, pg_transaction_seq  # noqa: F401
from app.services import sync_service

pytestmark = pytest.mark.postgres


async def _count(maker, model, *where):
    async with maker() as db:
        q = select(func.count()).select_from(model)
        for w in where:
            q = q.where(w)
        return (await db.execute(q)).scalar_one()


async def _setup_conflict(maker, world):
    """op1 dispatches, op2 conflicts, then op1 is received so op2 is applicable."""
    op1, op2 = _dispatch(world, seq=1), _dispatch(world, seq=2)
    async with maker() as db:
        assert (await sync_service.process_operation(db, op1, _U(world["user"]))).result == "applied"
    async with maker() as db:
        assert (await sync_service.process_operation(db, op2, _U(world["user"]))).result == "conflict"
    async with maker() as db:
        r = _receipt(world, op1.op_id, seq=3)
        assert (await sync_service.process_operation(db, r, _U(world["user"]))).result == "applied"
    return op2


async def _apply(maker, op_id, resolver):
    async with maker() as db:
        try:
            return await sync_review_service.apply_now(db, op_id, resolver, is_admin=True)
        except (SyncOpNotResolvableError, SyncApplyFailedError) as exc:
            return exc


async def _dismiss(maker, op_id, resolver):
    async with maker() as db:
        try:
            return await sync_review_service.dismiss(db, op_id, resolver, is_admin=True, reason="not_real", note=None)
        except SyncOpNotResolvableError as exc:
            return exc


@pytest.mark.parametrize("round_", range(4))
async def test_two_apply_now_one_winner(maker, world, round_):
    op2 = await _setup_conflict(maker, world)
    exports = await _count(maker, ExportEvent)
    res = await asyncio.gather(*[_apply(maker, op2.op_id, world["user"]) for _ in range(3)])
    wins = [r for r in res if isinstance(r, dict)]
    assert len(wins) == 1, res
    assert all(isinstance(r, Exception) for r in res if r not in wins)
    assert await _count(maker, ExportEvent) == exports + 1
    assert await _count(maker, BorrowTransaction) == 2  # op1 + the applied op2
    assert await _count(maker, AuditLog, AuditLog.action == "sync_conflict_resolved") == 1
    assert await _count(maker, ClientOperation, ClientOperation.status == "resolved") == 1
    assert await _count(maker, ClientOperation, ClientOperation.result_code == "RESOLVER_APPLIED") == 1


@pytest.mark.parametrize("round_", range(4))
async def test_dismiss_vs_apply_now_one_winner(maker, world, round_):
    op2 = await _setup_conflict(maker, world)
    res = await asyncio.gather(_apply(maker, op2.op_id, world["user"]), _dismiss(maker, op2.op_id, world["user"]))
    wins = [r for r in res if isinstance(r, dict)]
    assert len(wins) == 1, res
    assert await _count(maker, AuditLog, AuditLog.action == "sync_conflict_resolved") == 1
    applied = wins[0]["resolution"] == "applied_as"
    assert await _count(maker, BorrowTransaction) == (2 if applied else 1)
    assert await _count(maker, ClientOperation, ClientOperation.status == "resolved") == 1
