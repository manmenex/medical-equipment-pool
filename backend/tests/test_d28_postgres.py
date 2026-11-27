"""Owner Governance 2026-11-27 (D28) PostgreSQL proofs (postgres CI job):
migration 0039 round trip (columns, widened status CHECK, fail-closed
downgrade while a voided row exists) and the partial unique index ignoring
voided rows."""
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

_NEW_COLUMNS = {
    "prior_equipment_status",
    "closed_by_redispatch_transaction_id",
    "receipt_saved_at",
    "voided_at",
    "voided_by_user_id",
    "void_reason",
    "corrected_by_transaction_id",
}
_COLS = text(
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_schema='public' AND table_name='borrow_transactions'"
)
_CHECK = text(
    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_borrow_transactions_status_open_closed'"
)


async def _insert_tx(conn, equipment_id, n, status):
    await conn.execute(
        text(
            "INSERT INTO borrow_transactions (id, transaction_no, equipment_id, quantity, borrowed_at, status, "
            "dispatched_while_defective, has_hn) VALUES (:id, :no, :eq, 1, now(), :st, false, false)"
        ),
        {"id": uuid.uuid4(), "no": f"TX-D28-{n}", "eq": equipment_id, "st": status},
    )


async def test_migration_0039_round_trip_and_status_check():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")
    try:
        _run_alembic("upgrade", "head")
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                assert _NEW_COLUMNS <= {r[0] for r in (await conn.execute(_COLS)).all()}
                assert "voided" in (await conn.execute(_CHECK)).scalar()

            # 'voided' is accepted; any other value is still rejected; a voided row
            # does not occupy the one-open-transaction-per-device slot.
            async with engine.begin() as conn:
                eq = uuid.uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO equipment (id, equipment_name, status, version, equipment_source, metadata) "
                        "VALUES (:id, 'Pump', 'available_at_pool', 1, 'pool', '{}')"
                    ),
                    {"id": eq},
                )
                await _insert_tx(conn, eq, 1, "voided")
                await _insert_tx(conn, eq, 2, "voided")
                await _insert_tx(conn, eq, 3, "open")
            async with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    await _insert_tx(conn, eq, 4, "bogus")
            async with engine.begin() as conn:
                with pytest.raises(IntegrityError):
                    await _insert_tx(conn, eq, 5, "open")  # second open row still refused

            # Fail closed: the old CHECK cannot hold a voided row.
            with pytest.raises(Exception):
                _run_alembic("downgrade", "0038_export_hn_scope")
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM borrow_transactions WHERE status = 'voided'"))
            _run_alembic("downgrade", "0038_export_hn_scope")
            async with engine.connect() as conn:
                assert not _NEW_COLUMNS & {r[0] for r in (await conn.execute(_COLS)).all()}
                assert "voided" not in (await conn.execute(_CHECK)).scalar()
            _run_alembic("upgrade", "head")
            async with engine.connect() as conn:
                assert _NEW_COLUMNS <= {r[0] for r in (await conn.execute(_COLS)).all()}
                assert "voided" in (await conn.execute(_CHECK)).scalar()
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()
