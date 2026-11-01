"""Roadmap PR25E slice B1: `client_operations` ledger model and the optional
explicit-id / business-time parameters of `crud.transaction` (no endpoint yet)."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.crud import transaction as tx_crud
from app.models.client_operation import ClientOperation
from app.models.equipment import Equipment
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import User


async def _user(db_session) -> User:
    return (await db_session.execute(select(User).limit(1))).scalars().first()


def _op(user_id, **kw) -> ClientOperation:
    base = dict(
        op_id=uuid.uuid4(), device_id=uuid.uuid4(), device_seq=1, user_id=user_id,
        op_type="dispatch", payload_hash="h" * 64, status="applied", payload={"k": 1},
    )
    base.update(kw)
    return ClientOperation(**base)


def test_all_foreign_keys_restrict():
    fks = list(ClientOperation.__table__.foreign_keys)
    assert len(fks) == 4
    assert all(fk.ondelete == "RESTRICT" for fk in fks)


def test_indexes_and_unique_declared():
    t = ClientOperation.__table__
    names = {i.name for i in t.indexes}
    assert {
        "ix_client_operations_status_received_at",
        "ix_client_operations_received_at",
        "ix_client_operations_transaction_id",
        "ix_client_operations_collision_group_id",
    } <= names
    assert [c.name for c in t.primary_key.columns] == ["op_id"]


async def test_defaults_and_roundtrip(db_session, seeded_users):
    u = await _user(db_session)
    op = _op(u.id)
    db_session.add(op)
    await db_session.commit()
    await db_session.refresh(op)
    assert op.stale_context is False and op.attempt_count == 1
    assert op.first_seen_at is not None and op.received_at is not None
    assert op.transaction_id is None and op.submitted_by_user_id is None
    assert op.payload == {"k": 1} and op.proposed_sequence is None


@pytest.mark.parametrize("status", ["pending", "applied", "conflict", "rejected", "resolved"])
async def test_valid_statuses_accepted(db_session, seeded_users, status):
    u = await _user(db_session)
    db_session.add(_op(u.id, status=status))
    await db_session.commit()


@pytest.mark.parametrize(
    "kw",
    [
        {"status": "open"},
        {"op_type": "transfer"},
        {"time_flag": "bogus"},
        {"resolution_matches_proposal": "maybe"},
        {"attempt_count": 0},
    ],
)
async def test_check_constraints_reject_bad_values(db_session, seeded_users, kw):
    u = await _user(db_session)
    db_session.add(_op(u.id, **kw))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_check_constraints_accept_listed_flags(db_session, seeded_users):
    u = await _user(db_session)
    for i, (tf, rm) in enumerate([("clamped_future", "same"), ("before_last_receipt", "different"), (None, "dismissed_only")]):
        db_session.add(_op(u.id, device_seq=i + 1, time_flag=tf, resolution_matches_proposal=rm))
    await db_session.commit()


async def test_device_seq_unique_per_device(db_session, seeded_users):
    u = await _user(db_session)
    dev = uuid.uuid4()
    db_session.add(_op(u.id, device_id=dev, device_seq=7))
    db_session.add(_op(u.id, device_id=dev, device_seq=8))
    db_session.add(_op(u.id, device_id=uuid.uuid4(), device_seq=7))  # other device: fine
    await db_session.commit()
    db_session.add(_op(u.id, device_id=dev, device_seq=7))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_op_id_primary_key_unique(db_session, seeded_users):
    u = await _user(db_session)
    oid = uuid.uuid4()
    db_session.add(_op(u.id, op_id=oid))
    await db_session.commit()
    db_session.add(_op(u.id, op_id=oid, device_seq=2))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def _equipment_ward(db_session):
    ward = Ward(code="B1W", name="B1 Ward")
    eq = Equipment(asset_number="B1A", equipment_name="Pump")
    db_session.add_all([ward, eq])
    await db_session.flush()
    return eq, ward


async def test_create_with_explicit_id_and_business_time(db_session, seeded_users):
    eq, ward = await _equipment_ward(db_session)
    tid = uuid.uuid4()
    when = datetime.now(timezone.utc) - timedelta(hours=5)
    tx = await tx_crud.create(
        db_session, data={"transaction_no": "B1T1", "equipment_id": eq.id, "ward_id": ward.id}, id=tid, borrowed_at=when
    )
    assert tx.id == tid and tx.borrowed_at == when and tx.status == TransactionStatus.OPEN


async def test_create_defaults_unchanged(db_session, seeded_users):
    eq, ward = await _equipment_ward(db_session)
    before = datetime.now(timezone.utc)
    tx = await tx_crud.create(db_session, data={"transaction_no": "B1T2", "equipment_id": eq.id, "ward_id": ward.id})
    assert isinstance(tx.id, uuid.UUID) and tx.borrowed_at >= before - timedelta(seconds=1)


async def test_close_with_business_time_and_default(db_session, seeded_users):
    eq, ward = await _equipment_ward(db_session)
    u = await _user(db_session)
    t1 = await tx_crud.create(db_session, data={"transaction_no": "B1T3", "equipment_id": eq.id, "ward_id": ward.id})
    when = datetime.now(timezone.utc) - timedelta(hours=2)
    assert await tx_crud.close(db_session, t1, received_by_user_id=u.id, receipt_outcome="usable", notes=None, returned_at=when)
    await db_session.refresh(t1)
    assert t1.returned_at == when and t1.status == TransactionStatus.CLOSED

    eq2 = Equipment(asset_number="B1B", equipment_name="Pump")
    db_session.add(eq2)
    await db_session.flush()
    t2 = await tx_crud.create(db_session, data={"transaction_no": "B1T4", "equipment_id": eq2.id, "ward_id": ward.id})
    before = datetime.now(timezone.utc)
    assert await tx_crud.close(db_session, t2, received_by_user_id=u.id, receipt_outcome="usable", notes=None)
    await db_session.refresh(t2)
    assert t2.returned_at >= before - timedelta(seconds=1)


async def test_transaction_fk_links_ledger_row(db_session, seeded_users):
    eq, ward = await _equipment_ward(db_session)
    u = await _user(db_session)
    oid = uuid.uuid4()
    tx = await tx_crud.create(db_session, data={"transaction_no": "B1T5", "equipment_id": eq.id, "ward_id": ward.id}, id=oid)
    db_session.add(_op(u.id, op_id=oid, transaction_id=tx.id))
    await db_session.commit()
    row = (await db_session.execute(select(ClientOperation))).scalars().one()
    assert row.transaction_id == oid
