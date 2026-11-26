"""Roadmap PR33 PostgreSQL proof (runs in the postgres CI job): migration 0034
-- new equipment columns, the relaxed BCM canonical CHECK for demo/loan rows
only, global bcm_code uniqueness, and the fail-closed downgrade."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
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
    "WHERE table_schema='public' AND table_name='equipment' AND column_name IN "
    "('equipment_source','owner_company','due_back_date','has_charger','has_clamp',"
    "'returned_to_owner_at','returned_to_owner_by_user_id') ORDER BY column_name"
)

_INSERT = text(
    "INSERT INTO equipment (id, equipment_name, bcm_code, equipment_source, status, version, metadata, "
    "created_at, updated_at) "
    "VALUES (:id, 'Pump', :bcm, :src, 'available_at_pool', 1, '{}'::jsonb, now(), now())"
)


async def test_migration_0034_columns_constraints_and_downgrade():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")
    try:
        _run_alembic("upgrade", "head")
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                cols = {r[0]: tuple(r[1:]) for r in (await conn.execute(_COLS)).all()}
            assert set(cols) == {
                "equipment_source", "owner_company", "due_back_date", "has_charger", "has_clamp",
                "returned_to_owner_at", "returned_to_owner_by_user_id",
            }
            assert cols["equipment_source"][1] == "NO" and "pool" in cols["equipment_source"][2]
            assert cols["has_charger"][1:] == ("NO", "true") and cols["has_clamp"][1:] == ("NO", "true")

            # Pool rows keep the canonical BCM rule; demo/loan rows may hold a serial.
            async with engine.begin() as conn:
                await conn.execute(_INSERT, {"id": str(uuid.uuid4()), "bcm": "BCM0001", "src": "pool"})
                await conn.execute(_INSERT, {"id": str(uuid.uuid4()), "bcm": "sn-abc/1", "src": "demo"})
            for bad_bcm in ("SN-NOT-BCM", "bcm0002"):
                with pytest.raises((IntegrityError, DBAPIError)):
                    async with engine.begin() as conn:
                        await conn.execute(_INSERT, {"id": str(uuid.uuid4()), "bcm": bad_bcm, "src": "pool"})
            # bcm_code stays unique across ALL sources.
            with pytest.raises((IntegrityError, DBAPIError)):
                async with engine.begin() as conn:
                    await conn.execute(_INSERT, {"id": str(uuid.uuid4()), "bcm": "sn-abc/1", "src": "loan"})
            # Source is pinned to the allowed set.
            with pytest.raises((IntegrityError, DBAPIError)):
                async with engine.begin() as conn:
                    await conn.execute(_INSERT, {"id": str(uuid.uuid4()), "bcm": "X1", "src": "bogus"})

            # Downgrade fails closed while a demo/loan row exists ...
            with pytest.raises(Exception):
                _run_alembic("downgrade", "0033_patient_hn")
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM equipment WHERE equipment_source <> 'pool'"))
            # ... and succeeds once none remain, restoring the original constraint.
            _run_alembic("downgrade", "0033_patient_hn")
            async with engine.connect() as conn:
                assert (await conn.execute(_COLS)).all() == []
            _run_alembic("upgrade", "head")
            async with engine.connect() as conn:
                assert {r[0] for r in (await conn.execute(_COLS)).all()} == set(cols)
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()
