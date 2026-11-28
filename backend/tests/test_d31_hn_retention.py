"""D31 (Owner Governance 2026-11-28): HN retention -- 2 years from borrowed_at,
`hn_recorded` survives erasure; count-only audit; backups' monthly tier."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus
from app.models.export import ExportEvent
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import ROLE_READ_ONLY
from app.services.hn_retention_service import erase_old_hn
from app.services.standby_summary_service import _open_at_cutoff
from scripts.pg_backup_lib import backup_filename, select_tiered_prune_candidates
from tests.conftest import auth_headers as _auth_headers
from tests.test_pr29_hn import HN, _borrow, _ciphertext, _equipment, _row, ctx, hn_key  # noqa: F401

pytestmark = pytest.mark.asyncio
TOKEN = "gAAAA-fake-token"


async def _mk(db, n, ward, days_ago, *, status=TransactionStatus.OPEN, token=TOKEN):
    eq = Equipment(
        equipment_name=f"Dev{n}", bcm_code=f"BCM-D31-{n}", asset_number=f"AD31-{n}",
        status=EquipmentStatus.ISSUED_TO_WARD, equipment_source="pool",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(eq)
    await db.flush()
    tx = BorrowTransaction(
        transaction_no=f"TD31-{n}", equipment_id=eq.id, ward_id=ward.id,
        borrowed_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        status=status, hn_ciphertext=token, hn_recorded=token is not None,
    )
    db.add(tx)
    await db.flush()
    return tx


async def _ward(db):
    w = Ward(code="W31", name="Ward 31")
    db.add(w)
    await db.flush()
    return w


async def test_erase_old_younger_open_audit_idempotent(db_session):
    w = await _ward(db_session)
    old_open = await _mk(db_session, 1, w, 800)
    old_closed = await _mk(db_session, 2, w, 900, status=TransactionStatus.CLOSED)
    young = await _mk(db_session, 3, w, 700)
    no_hn = await _mk(db_session, 4, w, 900, token=None)
    await db_session.commit()
    ids = [t.id for t in (old_open, old_closed, young, no_hn)]
    old_open_id, old_closed_id, young_id = str(old_open.id), str(old_closed.id), str(young.id)

    assert await erase_old_hn(db_session, apply=False) == 2  # dry-run
    assert (await db_session.execute(select(AuditLog))).scalars().all() == []
    assert await _ciphertext(db_session, old_open_id) == TOKEN

    assert await erase_old_hn(db_session, apply=True) == 2
    assert await _ciphertext(db_session, old_open_id) is None
    assert await _ciphertext(db_session, old_closed_id) is None
    assert await _ciphertext(db_session, young_id) == TOKEN
    db_session.expire_all()
    rows = {t.id: t for t in (await db_session.execute(select(BorrowTransaction))).scalars().all()}
    assert [rows[i].hn_recorded for i in ids] == [True, True, True, False]  # marker kept
    assert rows[ids[0]].status == TransactionStatus.OPEN  # history kept

    [audit] = (await db_session.execute(select(AuditLog))).scalars().all()
    assert audit.after_data == {"erased_count": 2} and audit.entity_id is None
    assert TOKEN not in json.dumps([audit.before_data, audit.after_data])
    assert (await db_session.execute(select(ExportEvent))).scalars().all() == []  # no hn_update

    assert await erase_old_hn(db_session, apply=True) == 0  # idempotent
    assert await _ciphertext(db_session, young_id) == TOKEN


async def test_standby_and_d30_flags_survive_erasure(client, seeded_users, db_session):
    w = await _ward(db_session)
    tx = await _mk(db_session, 1, w, 800)
    eq_id = tx.equipment_id
    await db_session.commit()
    await erase_old_hn(db_session, apply=True)
    h = await _auth_headers(client, ROLE_READ_ONLY)
    r = await client.get("/api/v1/reports/outstanding", headers=h)
    assert r.json()["wards"][0]["rows"][0]["has_hn"] is True
    [t] = await _open_at_cutoff(db_session, {eq_id}, datetime.now(timezone.utc))
    assert t.has_hn is True


async def test_reveal_after_erasure_says_erased(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 31)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)).json()
    await db_session.execute(
        update(BorrowTransaction)
        .where(BorrowTransaction.id == uuid.UUID(tx["id"]))
        .values(borrowed_at=datetime.now(timezone.utc) - timedelta(days=800))
    )
    await db_session.commit()
    assert await erase_old_hn(db_session, apply=True) == 1
    r = await client.post(f"/api/v1/transactions/{tx['id']}/reveal-hn", headers=ctx["staff"])
    assert r.status_code == 410 and "HN_ERASED" in r.text
    assert HN not in r.text
    assert (await _row(db_session, tx["id"])).hn_recorded is True


async def test_add_hn_later_sets_hn_recorded(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 32)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"])).json()
    assert (await _row(db_session, tx["id"])).hn_recorded is False
    r = await client.post(f"/api/v1/transactions/{tx['id']}/hn", headers=ctx["staff"], json={"hn": HN})
    assert r.status_code == 200, r.text
    assert (await _row(db_session, tx["id"])).hn_recorded is True


async def test_cutoff_is_calendar_years_incl_leap_day(db_session):
    from app.services.hn_retention_service import years_ago

    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    assert years_ago(now, 2) == datetime(2024, 11, 28, 12, tzinfo=timezone.utc)  # 731 days, not 730
    assert years_ago(datetime(2028, 2, 29, tzinfo=timezone.utc), 2) == datetime(2026, 2, 28, tzinfo=timezone.utc)
    w = await _ward(db_session)
    keep = await _mk(db_session, 1, w, 0)
    erase = await _mk(db_session, 2, w, 0)
    keep.borrowed_at = datetime(2024, 11, 28, 13, tzinfo=timezone.utc)  # 1 h inside 2 calendar years
    erase.borrowed_at = datetime(2024, 11, 28, 11, tzinfo=timezone.utc)
    await db_session.commit()
    assert await erase_old_hn(db_session, apply=True, now=now) == 1


async def test_reveal_of_erased_hn_is_audited_without_value(client, ctx, db_session):
    eq = await _equipment(client, ctx["admin"], 33)
    tx = (await _borrow(client, ctx["staff"], eq, ctx["ward"], hn=HN)).json()
    await db_session.execute(
        update(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx["id"])).values(hn_ciphertext=None)
    )
    await db_session.commit()
    r = await client.post(f"/api/v1/transactions/{tx['id']}/reveal-hn", headers=ctx["staff"])
    assert r.status_code == 410
    rows = [a for a in (await db_session.execute(select(AuditLog))).scalars().all() if a.action == "hn_reveal"]
    assert len(rows) == 1 and rows[0].after_data["erased"] is True and HN not in json.dumps(rows[0].after_data)


def test_migration_0042_backfills_from_ciphertext():
    src = (Path(__file__).resolve().parents[1] / "alembic/versions/0042_hn_recorded.py").read_text()
    assert 'down_revision: Union[str, None] = "0041_system_heartbeats"' in src
    assert "SET hn_recorded = true WHERE has_hn OR hn_ciphertext IS NOT NULL" in src
    assert "DROP COLUMN IF EXISTS has_hn" in src


# ----------------------------------------------------------- monthly backups
TZ = timezone(timedelta(hours=7))


def _b(dt):
    return (Path(backup_filename("production", dt)), dt)


def test_monthly_tier_keeps_first_backup_of_each_local_month():
    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    # 2026-10-31 18:00 UTC is 2026-11-01 01:00 local (+7): first of November locally.
    first_nov = _b(datetime(2026, 10, 31, 18, tzinfo=timezone.utc))
    later_nov = _b(datetime(2026, 11, 10, 3, tzinfo=timezone.utc))
    first_jul = _b(datetime(2026, 7, 2, 1, tzinfo=timezone.utc))
    later_jul = _b(datetime(2026, 7, 20, 1, tzinfo=timezone.utc))
    ancient = _b(datetime(2025, 5, 2, 1, tzinfo=timezone.utc))  # beyond 12 months
    newest = _b(datetime(2026, 11, 28, 11, tzinfo=timezone.utc))
    got = select_tiered_prune_candidates(
        [first_nov, later_nov, first_jul, later_jul, ancient, newest], now=now, local_tz=TZ
    )
    assert first_nov[0] not in got and first_jul[0] not in got and newest[0] not in got
    assert later_jul[0] in got and ancient[0] in got  # later_nov: daily tier keeps it
    off = select_tiered_prune_candidates([first_jul, newest], now=now, monthly_retention_months=0, local_tz=TZ)
    assert first_jul[0] in off


def test_monthly_tier_never_deletes_newest_and_rejects_negative():
    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    only = _b(datetime(2020, 1, 1, tzinfo=timezone.utc))
    assert select_tiered_prune_candidates([only], now=now, local_tz=TZ) == []
    with pytest.raises(ValueError):
        select_tiered_prune_candidates([only], now=now, monthly_retention_months=-1)


def test_monthly_tier_spans_at_most_12_months_in_total():
    now = datetime(2026, 11, 28, 12, tzinfo=timezone.utc)
    nov25 = _b(datetime(2025, 11, 2, 1, tzinfo=timezone.utc))  # 13th month back: dropped
    dec25 = _b(datetime(2025, 12, 2, 1, tzinfo=timezone.utc))  # current + 11 before: kept
    newest = _b(datetime(2026, 11, 28, 11, tzinfo=timezone.utc))
    got = select_tiered_prune_candidates([nov25, dec25, newest], now=now, local_tz=TZ)
    assert nov25[0] in got and dec25[0] not in got
