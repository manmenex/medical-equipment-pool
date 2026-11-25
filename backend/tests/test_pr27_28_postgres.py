"""Roadmap PR27/PR28 PostgreSQL proofs (runs in the postgres CI job): migration
0031 on both the fresh-install and historical-upgrade paths, the CHECK
constraints that make a negative/over-returned cuff balance impossible, and
that concurrent cuff receipts can never exceed what was issued."""
import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import create_ward as _create_ward
from tests.test_postgres_integration import (  # noqa: F401
    _admin_headers,
    _drop_scratch_database,
    _recreate_scratch_database,
    _run_alembic,
    _scratch_dsn,
    pg_client,
    pg_engine,
    pg_seeded_users,
    pg_session,
    pg_transaction_seq,
)

pytestmark = pytest.mark.postgres

_TABLES = ("borrow_transactions", "equipment_categories", "transaction_cuffs")


async def _schema_snapshot(conn) -> dict:
    cols = (
        await conn.execute(
            text(
                "SELECT table_name, column_name, data_type, character_maximum_length, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema='public' AND table_name = ANY(:t) "
                "ORDER BY table_name, column_name"
            ),
            {"t": list(_TABLES)},
        )
    ).all()
    checks = (
        await conn.execute(
            text(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE contype IN ('c','u') AND conrelid IN (SELECT oid FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(:t)) ORDER BY 1, 2"
            ),
            {"t": list(_TABLES)},
        )
    ).all()
    return {"columns": [tuple(r) for r in cols], "constraints": [tuple(r) for r in checks]}


async def test_migration_0031_fresh_and_historical_paths_converge_with_backfill():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")
    try:
        # Fresh install: create_all() builds the final schema, 0031 is a convergent no-op.
        _run_alembic("upgrade", "head")
        engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
        try:
            async with engine.connect() as conn:
                fresh = await _schema_snapshot(conn)
            names = {c[1] for c in fresh["columns"] if c[0] == "transaction_cuffs"}
            assert names == {"id", "transaction_id", "cuff_type", "issued_count", "returned_count", "created_at", "updated_at"}

            # Historical path: undo 0031, seed categories under the old schema, re-apply.
            _run_alembic("downgrade", "0030_non_blocking_dispatch")
            async with engine.connect() as conn:
                old = await _schema_snapshot(conn)
            assert not [c for c in old["columns"] if c[0] == "transaction_cuffs"]
            assert "checklist_kind" not in {c[1] for c in old["columns"]}
            assert "dispatch_contact_name" not in {c[1] for c in old["columns"]}
            async with engine.begin() as conn:
                for name in ("Cryo-Cuff Machine", "CRYO cuff lower", "Infusion Pump", "Cryptic"):
                    await conn.execute(
                        text("INSERT INTO equipment_categories (id, name) VALUES (gen_random_uuid(), :n)"), {"n": name}
                    )

            _run_alembic("upgrade", "head")
            async with engine.connect() as conn:
                upgraded = await _schema_snapshot(conn)
                kinds = dict(
                    (await conn.execute(text("SELECT name, checklist_kind FROM equipment_categories"))).all()
                )
            assert upgraded == fresh
            assert kinds == {
                "Cryo-Cuff Machine": "cryo_cuff",
                "CRYO cuff lower": "cryo_cuff",
                "Infusion Pump": "standard",
                "Cryptic": "standard",
            }
            # Re-running the revision is idempotent (IF NOT EXISTS everywhere).
            _run_alembic("downgrade", "0030_non_blocking_dispatch")
            _run_alembic("upgrade", "head")
        finally:
            await engine.dispose()
    finally:
        await _drop_scratch_database()


async def test_cuff_check_constraints_reject_over_return_and_bad_rows_on_postgres(pg_client, pg_seeded_users, pg_transaction_seq, pg_engine):
    headers = await _admin_headers(pg_client)
    cat = (await pg_client.post("/api/v1/categories", headers=headers, json={"name": "Cryo-Cuff PG"})).json()
    assert cat["checklist_kind"] == "cryo_cuff"
    eq = (
        await pg_client.post(
            "/api/v1/equipment",
            headers=headers,
            json={"asset_number": "PR28-PG-1", "equipment_name": "Cryo", "category_id": cat["id"]},
        )
    ).json()["id"]
    ward = await _create_ward(pg_client, headers, "PR28-PG-W")
    resp = await pg_client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_id": eq, "ward_id": ward, "dispatch_checks": {"kind": "cryo_cuff", "cuffs": {"knee": 2}}},
    )
    assert resp.status_code == 201, resp.text
    tx = resp.json()["id"]
    assert resp.json()["dispatch_checks"]["cuffs"]["knee"] == 2

    for sql in (
        "UPDATE transaction_cuffs SET returned_count = 3 WHERE transaction_id = :t",
        "UPDATE transaction_cuffs SET returned_count = -1 WHERE transaction_id = :t",
        "UPDATE transaction_cuffs SET issued_count = 0, returned_count = 0 WHERE transaction_id = :t",
        "UPDATE transaction_cuffs SET cuff_type = 'elbow' WHERE transaction_id = :t",
    ):
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(text(sql), {"t": uuid.UUID(tx)})
    with pytest.raises(IntegrityError):
        async with pg_engine.begin() as conn:
            await conn.execute(
                text("UPDATE borrow_transactions SET checklist_kind = 'bogus' WHERE id = :t"), {"t": uuid.UUID(tx)}
            )
    # JSONB round trip keeps the structured checklist.
    async with pg_engine.connect() as conn:
        got = (
            await conn.execute(
                text("SELECT dispatch_checks->>'kind', dispatch_checks->'cuffs'->>'knee' FROM borrow_transactions WHERE id = :t"),
                {"t": uuid.UUID(tx)},
            )
        ).one()
    assert tuple(got) == ("cryo_cuff", "2")


async def test_concurrent_cuff_receipts_never_exceed_issued_on_postgres(pg_client, pg_seeded_users, pg_transaction_seq, pg_engine):
    headers = await _admin_headers(pg_client)
    cat = (await pg_client.post("/api/v1/categories", headers=headers, json={"name": "Cryo-Cuff PG2"})).json()
    eq = (
        await pg_client.post(
            "/api/v1/equipment",
            headers=headers,
            json={"asset_number": "PR28-PG-2", "equipment_name": "Cryo", "category_id": cat["id"]},
        )
    ).json()["id"]
    ward = await _create_ward(pg_client, headers, "PR28-PG-W2")
    tx = (
        await pg_client.post(
            "/api/v1/borrow",
            headers=headers,
            json={"equipment_id": eq, "ward_id": ward, "dispatch_checks": {"kind": "cryo_cuff", "cuffs": {"knee": 2}}},
        )
    ).json()["id"]
    assert (await pg_client.post(f"/api/v1/return/{tx}", headers=headers, json={"receipt_outcome": "usable"})).status_code == 200

    async def go():
        return await pg_client.post(
            f"/api/v1/transactions/{tx}/receive-cuffs", headers=headers, json={"cuffs": {"knee": 1}}
        )

    results = await asyncio.gather(*[go() for _ in range(6)])
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 200, 409, 409, 409, 409], [r.text for r in results]
    async with pg_engine.connect() as conn:
        issued, returned = (
            await conn.execute(
                text("SELECT issued_count, returned_count FROM transaction_cuffs WHERE transaction_id = :t"),
                {"t": uuid.UUID(tx)},
            )
        ).one()
    assert (issued, returned) == (2, 2)
