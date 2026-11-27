"""Owner Governance 2026-11-27 (D28) PostgreSQL proof (postgres CI job):
migration 0040 lets a transaction have repeated (transaction, event_type)
export rows, allows one correction per original, and round-trips."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_postgres_integration import (  # noqa: F401
    _drop_scratch_database,
    _recreate_scratch_database,
    _run_alembic,
    _scratch_dsn,
)

pytestmark = pytest.mark.postgres

_NEW = {"correction", "corrects_event_id", "withdrawn", "generation"}
_COLS = text(
    "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='export_events'"
)
_UQ = text("SELECT count(*) FROM pg_constraint WHERE conname='uq_export_events_transaction_type'")
_INS = text(
    "INSERT INTO export_events (seq, event_id, event_type, transaction_id, event_at, correction, corrects_event_id, generation) "
    "VALUES (:s, :e, :t, :tx, now(), :c, :co, :g)"
)


async def test_migration_0040_export_corrections_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")
    try:
        _run_alembic("upgrade", "head")
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.begin() as conn:
                assert _NEW <= {r[0] for r in (await conn.execute(_COLS)).all()}
                assert (await conn.execute(_UQ)).scalar() == 0
                eq, tx, orig = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, equipment_name, status, version, equipment_source, metadata) "
                        "VALUES (:id, 'Pump', 'available_at_pool', 1, 'pool', '{}')"
                    ),
                    {"id": eq},
                )
                await conn.execute(
                    text(
                        "INSERT INTO borrow_transactions (id, transaction_no, equipment_id, quantity, borrowed_at, "
                        "status, dispatched_while_defective, has_hn) "
                        "VALUES (:id, 'TX-D28-X', :eq, 1, now(), 'open', false, false)"
                    ),
                    {"id": tx, "eq": eq},
                )
                await conn.execute(_INS, {"s": 1, "e": orig, "t": "receipt", "tx": tx, "c": False, "co": None, "g": 0})
                await conn.execute(_INS, {"s": 2, "e": uuid.uuid4(), "t": "receipt", "tx": tx, "c": False, "co": None, "g": 1})
                await conn.execute(_INS, {"s": 3, "e": uuid.uuid4(), "t": "dispatch", "tx": tx, "c": True, "co": orig, "g": 0})
            async with engine.begin() as conn:
                with pytest.raises(IntegrityError):  # a second correction of the same original
                    await conn.execute(
                        _INS, {"s": 4, "e": uuid.uuid4(), "t": "dispatch", "tx": tx, "c": True, "co": orig, "g": 0}
                    )
            _run_alembic("downgrade", "0039_transaction_corrections")
            async with engine.connect() as conn:
                assert not _NEW & {r[0] for r in (await conn.execute(_COLS)).all()}
                assert (await conn.execute(_UQ)).scalar() == 1
                assert (await conn.execute(text("SELECT count(*) FROM export_events"))).scalar() == 1
            _run_alembic("upgrade", "head")
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()
