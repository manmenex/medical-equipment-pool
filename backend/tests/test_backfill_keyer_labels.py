"""Backfill of D22 BME keyer labels from the sheet-sync trace note."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.audit import AuditLog
from app.models.equipment import Equipment
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction, DispatchType, TransactionStatus
from app.models.user import ROLE_EQUIPMENT_POOL_STAFF, Role, User
from app.scripts import backfill_keyer_labels as bk


@pytest.fixture
def maker(db_engine, monkeypatch):
    m = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr(bk, "AsyncSessionLocal", m)
    return m


@pytest.fixture
async def data(maker, seeded_users):
    async with maker() as db:
        role = (await db.execute(select(Role).where(Role.name == ROLE_EQUIPMENT_POOL_STAFF))).scalar_one()
        sync = User(employee_code="LEGACY-SYNC", full_name="Legacy Sync", email="ls@test.dev", password_hash="x", role_id=role.id)
        human = User(employee_code="HUMAN1", full_name="Human", email="h@test.dev", password_hash="x", role_id=role.id)
        ward = Ward(code="ICU3", name="ICU3")
        eqs = [Equipment(asset_number=f"A{i}", equipment_name="Pump", bcm_code=f"BCM0{i}") for i in range(5)]
        db.add_all([sync, human, ward, *eqs])
        await db.flush()

        counter = iter(range(1, 99))

        def tx(eq, borrower, notes, **kw):
            return BorrowTransaction(
                transaction_no=f"T{next(counter)}", equipment_id=eq.id, ward_id=ward.id,
                borrower_user_id=borrower.id, notes=notes,
                dispatch_type=DispatchType.ON_DEMAND, status=TransactionStatus.OPEN, **kw)

        db.add_all([
            tx(eqs[0], sync, "legacy sheet dispatch row 0a1b2c3d; Borrow1; BME Somchai; accessories: x"),
            tx(eqs[1], human, "legacy sheet dispatch row 0a1b2c3e; BME Notsync"),  # non-sync row
            tx(eqs[2], sync, "legacy sheet dispatch row 0a1b2c3f; BME Newname", dispatch_keyer_label="Existing"),
            tx(eqs[3], sync, "ฝาเครื่องร้าว BME fake"),  # operator note, not a trace
            tx(eqs[4], sync, "legacy sheet dispatch row 0a1b2c40; Borrow2"),  # no BME name
        ])
        await db.commit()


async def _labels(maker):
    async with maker() as db:
        rows = (await db.execute(select(BorrowTransaction))).scalars().all()
        return {r.notes.split(";")[0][-8:] if r.notes.startswith("legacy") else r.notes: r.dispatch_keyer_label for r in rows}


def test_parse_bme():
    assert bk.parse_bme("legacy sheet receipt row x; BME Ann; accessories: a") == ("receipt", "Ann")
    assert bk.parse_bme("legacy sheet dispatch row x; doc") is None
    assert bk.parse_bme("typed note; BME Ann") is None
    assert len(bk.parse_bme("legacy sheet dispatch row x; BME " + "ก" * 300)[1]) == 100


async def test_dry_run_writes_nothing(maker, data):
    before = await _labels(maker)
    c = await bk.backfill(apply=False)
    assert c["dispatch_labels"] == 1
    assert await _labels(maker) == before


async def test_apply_sets_only_null_sync_rows_idempotent_with_one_audit(maker, data):
    c = await bk.backfill(apply=True)
    assert c["dispatch_labels"] == 1 and c["receipt_labels"] == 0
    by = await _labels(maker)
    assert by["0a1b2c3d"] == "Somchai"
    assert by["0a1b2c3e"] is None  # not created by the sync user
    assert by["0a1b2c3f"] == "Existing"  # never overwritten
    assert by["ฝาเครื่องร้าว BME fake"] is None
    assert by["0a1b2c40"] is None
    async with maker() as db:
        audits = (await db.execute(select(AuditLog).where(AuditLog.action == bk.AUDIT_ACTION))).scalars().all()
    assert len(audits) == 1 and audits[0].after_data == {"dispatch_labels": 1, "receipt_labels": 0}
    again = await bk.backfill(apply=True)
    assert again["dispatch_labels"] == 0 and again["receipt_labels"] == 0
    async with maker() as db:
        assert len((await db.execute(select(AuditLog).where(AuditLog.action == bk.AUDIT_ACTION))).scalars().all()) == 1


def test_parse_bme_rejects_system_text_name():
    assert bk.parse_bme("legacy sheet receipt row x; BME legacy sheet receipt row y") is None


async def test_repair_clears_system_note_labels_dry_run_then_apply(maker, data):
    n_a = "legacy sheet dispatch row 0a1b2c3d; Borrow1; BME Somchai; accessories: x"
    n_b = "legacy sheet dispatch row 0a1b2c3e; BME Notsync"
    n_c = "ฝาเครื่องร้าว BME fake"
    async with maker() as db:
        by = {t.notes: t for t in (await db.execute(select(BorrowTransaction))).scalars().all()}
        by[n_a].received_by_user_id = by[n_a].borrower_user_id
        by[n_a].receipt_keyer_label = "legacy sheet receipt row 1; BME X"
        by[n_a].dispatch_contact_name = "legacy sheet receipt row 2"
        by[n_b].dispatch_keyer_label = n_b
        by[n_c].dispatch_keyer_label = "Real Name"
        by[n_b].borrower_user_id = (await db.execute(select(User.id).where(User.employee_code == "HUMAN1"))).scalar_one()
        await db.commit()
    assert await bk.repair(apply=False) == {"scanned": 1, "rewritten": 1, "cleared": 1}
    async with maker() as db:
        by = {t.notes: t for t in (await db.execute(select(BorrowTransaction))).scalars().all()}
        assert by[n_a].receipt_keyer_label is not None  # dry-run wrote nothing
    await bk.repair(apply=True)
    async with maker() as db:
        by = {t.notes: t for t in (await db.execute(select(BorrowTransaction))).scalars().all()}
        assert by[n_a].receipt_keyer_label == "X" and by[n_a].receipt_keyer_label and by[n_a].dispatch_contact_name is None
        assert by[n_b].dispatch_keyer_label == n_b  # non-sync row untouched
        assert by[n_c].dispatch_keyer_label == "Real Name"
    assert await bk.repair(apply=True) == {"scanned": 0, "rewritten": 0, "cleared": 0}
