"""Roadmap PR29 PostgreSQL proof (runs in the postgres CI job): migration 0033
on both the fresh-install and historical-upgrade paths."""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.test_postgres_integration import (  # noqa: F401
    _drop_scratch_database,
    _recreate_scratch_database,
    _run_alembic,
    _scratch_dsn,
)

pytestmark = pytest.mark.postgres

_COLS = text(
    "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
    "WHERE table_schema='public' AND table_name='borrow_transactions' "
    "AND column_name IN ('hn_ciphertext','hn_recorded') ORDER BY column_name"
)


async def test_migration_0033_fresh_and_historical_paths_converge():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")
    try:
        _run_alembic("upgrade", "head")
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                fresh = [tuple(r) for r in (await conn.execute(_COLS)).all()]
            assert [r[0] for r in fresh] == ["hn_ciphertext", "hn_recorded"]
            assert fresh[1][1:3] == ("boolean", "NO") and "false" in fresh[1][3]
            assert fresh[0][1:] == ("text", "YES", None)

            _run_alembic("downgrade", "0032_report_ward_rows")
            async with engine.connect() as conn:
                assert (await conn.execute(_COLS)).all() == []
            _run_alembic("upgrade", "head")
            async with engine.connect() as conn:
                assert [tuple(r) for r in (await conn.execute(_COLS)).all()] == fresh
            # Idempotent re-run (IF NOT EXISTS).
            _run_alembic("downgrade", "0032_report_ward_rows")
            _run_alembic("upgrade", "head")
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()
