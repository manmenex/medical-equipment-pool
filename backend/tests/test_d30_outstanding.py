"""Owner Governance 2026-11-28 (D30): long-outstanding dispatch report."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.equipment import Equipment, EquipmentStatus
from app.models.master_data import Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers as _auth_headers

pytestmark = pytest.mark.asyncio
HN_TOKEN = "gAAAAA-SECRET-HN-TOKEN"
URL = "/api/v1/reports/outstanding"


async def _mk(db, n, ward, days_ago, *, status=TransactionStatus.OPEN, ciphertext=None, returned_owner=False,
              source="pool", label=None):
    eq = Equipment(
        equipment_name=f"Dev{n}", bcm_code=f"BCM-D30-{n}", asset_number=f"AD30-{n}",
        status=EquipmentStatus.ISSUED_TO_WARD, equipment_source=source,
        returned_to_owner_at=datetime.now(timezone.utc) if returned_owner else None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(eq)
    await db.flush()
    db.add(BorrowTransaction(
        transaction_no=f"TD30-{n}", equipment_id=eq.id, ward_id=ward.id,
        borrowed_at=datetime.now(timezone.utc) - timedelta(days=days_ago, minutes=1),
        status=status, hn_ciphertext=ciphertext, has_hn=ciphertext is not None, dispatch_keyer_label=label,
    ))
    await db.flush()


async def _wards(db):
    a, b = Ward(code="WA", name="Ward A"), Ward(code="WB", name="Ward B")
    db.add_all([b, a])
    await db.flush()
    return a, b


async def test_filters_ordering_and_fields(client, seeded_users, db_session):
    a, b = await _wards(db_session)
    await _mk(db_session, 1, b, 10, label="สมชาย")
    await _mk(db_session, 2, a, 8, ciphertext=HN_TOKEN, source="demo")
    await _mk(db_session, 3, a, 20)
    await _mk(db_session, 4, a, 7)  # 7 days + 1 minute: older than threshold
    await _mk(db_session, 5, a, 6)  # younger: excluded
    await _mk(db_session, 6, a, 30, status=TransactionStatus.VOIDED)
    await _mk(db_session, 7, a, 30, status=TransactionStatus.CLOSED)
    await _mk(db_session, 8, a, 30, returned_owner=True)
    await db_session.commit()
    h = await _auth_headers(client, ROLE_READ_ONLY)
    r = await client.get(URL, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert [w["ward"] for w in body["wards"]] == ["Ward A", "Ward B"]
    assert body["total"] == 4
    rows = body["wards"][0]["rows"]
    assert [x["transaction_no"] for x in rows] == ["TD30-3", "TD30-2", "TD30-4"]  # oldest first
    assert rows[1]["has_hn"] is True and rows[0]["has_hn"] is False
    assert rows[1]["source_badge"] == "DEMO" and rows[1]["age_days"] == 8
    assert body["wards"][1]["rows"][0]["keyer"] == "สมชาย"
    assert HN_TOKEN not in r.text
    assert "+07:00" in rows[0]["borrowed_at"]
    assert (await client.get(URL, headers=h, params={"days": 9})).json()["total"] == 2


async def test_days_validation_and_roles(client, seeded_users, db_session):
    h = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    for bad in (0, 366):
        assert (await client.get(URL, headers=h, params={"days": bad})).status_code == 422
    assert (await client.get(URL, headers=h)).status_code == 200
    assert (await client.get(URL)).status_code in (401, 403)


async def test_line_text_has_no_hn(client, seeded_users, db_session):
    a, _ = await _wards(db_session)
    await _mk(db_session, 1, a, 9, ciphertext=HN_TOKEN)
    await _mk(db_session, 2, a, 12)
    await db_session.commit()
    h = await _auth_headers(client, ROLE_READ_ONLY)
    r = await client.get(f"{URL}/line-text", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.text == "เครื่องค้างเกิน 7 วัน (รวม 2 เครื่อง)\nWard A = 2 เครื่อง: BCM-D30-2, BCM-D30-1"
    assert "HN" not in r.text and HN_TOKEN not in r.text
