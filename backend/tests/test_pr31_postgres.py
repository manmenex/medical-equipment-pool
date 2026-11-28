"""Roadmap PR31 (D8) -- genuine two-connection PostgreSQL concurrency proof for
re-dispatch. Reuses the fixtures of ``test_postgres_integration.py`` like every
other concurrency proof in this repository (runs in the postgres CI job)."""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.models.equipment import Equipment, EquipmentStatus
from app.models.transaction import CLOSE_REASON_REDISPATCH, BorrowTransaction, TransactionStatus
from tests.conftest import create_ward as _create_ward
from tests.test_postgres_integration import (  # noqa: F401
    _admin_headers,
    pg_client,
    pg_engine,
    pg_seeded_users,
    pg_session,
    pg_transaction_seq,
)

pytestmark = pytest.mark.postgres


async def test_concurrent_redispatches_never_both_close_the_same_transaction_on_postgres(
    pg_client, pg_seeded_users, pg_transaction_seq, pg_session
):
    headers = await _admin_headers(pg_client)
    resp = await pg_client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": "PR31-PG-001", "equipment_name": "Pump"}
    )
    assert resp.status_code == 201, resp.text
    eq = resp.json()["id"]
    ward_a = await _create_ward(pg_client, headers, "PR31-PG-A")
    ward_b = await _create_ward(pg_client, headers, "PR31-PG-B")
    first = await pg_client.post(
        "/api/v1/borrow", headers=headers, json={"equipment_id": eq, "ward_id": ward_a, "dispatch_type": "on_demand"}
    )
    assert first.status_code == 201, first.text

    async def go(ward):
        return await pg_client.post(
            "/api/v1/borrow",
            headers=headers,
            json={"equipment_id": eq, "ward_id": ward, "dispatch_type": "on_demand", "acknowledge_status_warning": True},
        )

    results = await asyncio.gather(go(ward_a), go(ward_b), go(ward_a), go(ward_b))
    codes = [r.status_code for r in results]
    assert all(c in (201, 409) for c in codes) and 201 in codes, [r.text for r in results]

    pg_session.expire_all()
    rows = (
        await pg_session.execute(select(BorrowTransaction).where(BorrowTransaction.equipment_id == uuid.UUID(eq)))
    ).scalars().all()
    wins = codes.count(201)
    assert len([r for r in rows if r.status == TransactionStatus.OPEN]) == 1
    # Every winner closed exactly one predecessor (no double close, no lost close).
    assert len([r for r in rows if r.close_reason == CLOSE_REASON_REDISPATCH]) == wins
    assert len(rows) == 1 + wins
    assert all(r.returned_at is None and r.condition_on_return is None for r in rows)
    equipment = (await pg_session.execute(select(Equipment).where(Equipment.id == uuid.UUID(eq)))).scalar_one()
    assert equipment.status == EquipmentStatus.ISSUED_TO_WARD
