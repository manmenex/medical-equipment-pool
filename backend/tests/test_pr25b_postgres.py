"""PostgreSQL proof that the export cursor cannot skip a committed event.

SQLite cannot demonstrate row-lock serialization, so this runs against a real
PostgreSQL (mirrors test_pr24b_postgres.py). Run only these:
    POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://... pytest -q -m postgres tests/test_pr25b_postgres.py
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.equipment import Equipment
from app.models.export import EVENT_TYPE_DISPATCH, ExportEvent
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction
from app.services import export_service

pytestmark = pytest.mark.postgres

URL = os.environ.get(
    "POSTGRES_TEST_DATABASE_URL",
    "postgresql+asyncpg://mep_test:mep_test_password@localhost:5432/mep_test_db",
)


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine(URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL not reachable at {URL}: {exc}")
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


async def _tx(maker, n):
    async with maker() as s:
        ward = Ward(code=f"W{n}", name=f"Ward {n}")
        eq = Equipment(asset_number=f"A{n}", equipment_name="Pump")
        s.add_all([ward, eq])
        await s.flush()
        tx = BorrowTransaction(transaction_no=f"T{n}", equipment_id=eq.id, ward_id=ward.id)
        s.add(tx)
        await s.commit()
        return tx.id


async def _visible(maker, after=0):
    async with maker() as s:
        return list((await s.execute(select(ExportEvent.seq).where(ExportEvent.seq > after).order_by(ExportEvent.seq))).scalars())


async def test_late_committer_cannot_be_overtaken(maker):
    """A takes the lower seq and stalls before commit; B starts afterwards.
    B must not be able to take a seq (let alone commit) until A is done, so
    the consumer can never see B's event without A's."""
    t1, t2 = await _tx(maker, 1), await _tx(maker, 2)
    now = datetime.now(timezone.utc)

    a = maker()
    await export_service.record_event(a, transaction_id=t1, event_type=EVENT_TYPE_DISPATCH, event_at=now)

    async def writer_b():
        async with maker() as b:
            ev = await export_service.record_event(b, transaction_id=t2, event_type=EVENT_TYPE_DISPATCH, event_at=now)
            await b.commit()
            return ev.seq

    task_b = asyncio.create_task(writer_b())
    await asyncio.sleep(0.5)
    assert not task_b.done(), "B must block on the counter row while A holds it"
    assert await _visible(maker) == []  # nothing committed: a poller sees nothing

    await a.commit()
    await a.close()
    assert await asyncio.wait_for(task_b, 5) == 2
    assert await _visible(maker) == [1, 2]


async def test_rollback_leaves_no_gap(maker):
    t1, t2 = await _tx(maker, 1), await _tx(maker, 2)
    now = datetime.now(timezone.utc)
    async with maker() as a:
        await export_service.record_event(a, transaction_id=t1, event_type=EVENT_TYPE_DISPATCH, event_at=now)
        await a.rollback()
    async with maker() as b:
        ev = await export_service.record_event(b, transaction_id=t2, event_type=EVENT_TYPE_DISPATCH, event_at=now)
        await b.commit()
    assert ev.seq == 1 and await _visible(maker) == [1]


async def test_concurrent_writers_poller_always_sees_a_prefix(maker):
    txs = [await _tx(maker, n) for n in range(10, 22)]
    now = datetime.now(timezone.utc)
    stop = asyncio.Event()
    observed: list[list[int]] = []

    async def poller():
        while not stop.is_set():
            observed.append(await _visible(maker))
            await asyncio.sleep(0)

    async def writer(tx_id, delay):
        async with maker() as s:
            await export_service.record_event(s, transaction_id=tx_id, event_type=EVENT_TYPE_DISPATCH, event_at=now)
            await asyncio.sleep(delay)  # hold the lock a while before committing
            await s.commit()

    p = asyncio.create_task(poller())
    await asyncio.gather(*(writer(t, 0.02 * (i % 3)) for i, t in enumerate(txs)))
    stop.set()
    await p
    assert observed
    for seqs in observed:
        assert seqs == list(range(1, len(seqs) + 1)), seqs  # always a gap-free prefix
    assert await _visible(maker) == list(range(1, 13))


async def test_backfill_sql_numbers_history_chronologically(maker):
    """Run the migration's own backfill statements against real rows."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0025_export_events.py"
    spec = importlib.util.spec_from_file_location("_mep_migration_0025", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    t1, t2 = await _tx(maker, 1), await _tx(maker, 2)
    async with maker() as s:
        await s.execute(
            text("UPDATE borrow_transactions SET status='closed', returned_at=now(), condition_on_return='usable' WHERE id=:i"),
            {"i": t1},
        )
        await s.execute(text(mod._BACKFILL))
        await s.execute(text(mod._SET_COUNTER))
        await s.commit()
    async with maker() as s:
        rows = (await s.execute(select(ExportEvent).order_by(ExportEvent.seq))).scalars().all()
        assert [r.seq for r in rows] == [1, 2, 3]
        assert [r.event_type for r in rows].count("receipt") == 1
        assert len({r.event_id for r in rows}) == 3
        assert rows[-1].event_type == "receipt"  # latest event time last
        # live events continue after the backfill
        ev = await export_service.record_event(s, transaction_id=t2, event_type="receipt", event_at=datetime.now(timezone.utc))
        assert ev.seq == 4
