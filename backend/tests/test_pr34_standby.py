"""Roadmap PR34 (Owner Governance 2026-11-26 D15/D16): standby summary, add HN
later, copy text, PR30 Excel "Stand By" column.  SQLite; no real HN is stored
except the greppable marker used by the add-HN tests.
"""
import io
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet
from openpyxl import load_workbook
from sqlalchemy import select

from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.equipment import Equipment, EquipmentStatus
from app.models.master_data import Department, EquipmentCategory, Ward
from app.models.report_mapping import ReportWardRow
from app.models.standby_summary import StandbySummaryConfig, StandbySummaryOverride
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.services import standby_summary_service as svc
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

pytestmark = pytest.mark.asyncio

D = date(2026, 7, 28)
BKK = ZoneInfo("Asia/Bangkok")
HN = "HN-3402/66"  # greppable marker, valid under the HN format rule


def at(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 7, day, hh, mm, tzinfo=BKK).astimezone(timezone.utc)


@pytest.fixture
def hn_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", key)
    return key


# ------------------------------------------------------------------ pure logic


async def test_cutoff_instants_are_bangkok_wall_clock():
    assert svc.cutoff_instant(D, "night") == datetime(2026, 7, 28, 1, 0, tzinfo=timezone.utc)  # 08:00 +07
    assert svc.cutoff_instant(D, "day") == datetime(2026, 7, 28, 13, 0, tzinfo=timezone.utc)  # 20:00 +07
    assert svc.business_day_start(D) == datetime(2026, 7, 27, 13, 0, tzinfo=timezone.utc)  # 20:00 on D-1
    with pytest.raises(Exception):
        svc.cutoff_instant(D, "noon")


async def test_field_key_sections():
    assert svc.section_for_key("ward:W5A") == "infusion"
    assert svc.section_for_key("ready") == "infusion"
    assert svc.section_for_key("pneumatic_in_use") == "pneumatic"
    for bad in ("ward:", "nonsense", "ward:" + "x" * 101):
        with pytest.raises(Exception):
            svc.section_for_key(bad)


# ------------------------------------------------------------------ fixtures

STD_OK = {"kind": "standard", "screen_ok": True, "charger_ok": True, "clamp_ok": True}
STD_NO_CHARGER = {"kind": "standard", "screen_ok": True, "charger_ok": False, "clamp_ok": True}
STD_NO_CLAMP = {"kind": "standard", "screen_ok": True, "charger_ok": True, "clamp_ok": False}


class W:
    pass


async def _world(db) -> W:
    w = W()
    dept = Department(code="DX", name="IPD")
    db.add(dept)
    await db.flush()
    w.w5a = Ward(code="W5A", name="Ward 5A", department_id=dept.id)
    w.w5b = Ward(code="W5B", name="Ward 5B", department_id=dept.id)
    db.add_all([w.w5a, w.w5b])
    w.infusion = EquipmentCategory(name="Infusion Pump")
    w.pneu = EquipmentCategory(name="Pneumatic Pump")
    w.other = EquipmentCategory(name="Monitor")
    db.add_all([w.infusion, w.pneu, w.other])
    await db.flush()
    # Short report labels (PR30 mapping).
    db.add_all(
        [
            ReportWardRow(ward_id=w.w5a.id, report_row_label="W5A", sort_order=1),
            ReportWardRow(ward_id=w.w5b.id, report_row_label="W5B", sort_order=2),
        ]
    )
    w.n = 0
    return w


async def _eq(db, w, category, status=EquipmentStatus.AVAILABLE_AT_POOL) -> Equipment:
    w.n += 1
    e = Equipment(
        equipment_name=f"Dev{w.n}",
        bcm_code=f"BCM-34-{w.n:03d}",
        asset_number=f"A34-{w.n}",
        category_id=category.id,
        status=status,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(e)
    await db.flush()
    return e


async def _tx(db, w, eq, ward, dispatched, received=None, *, has_hn=False, hn_added_at=None,
              checks_d=None, checks_r=None) -> BorrowTransaction:
    w.n += 1
    t = BorrowTransaction(
        transaction_no=f"T34-{w.n}",
        equipment_id=eq.id,
        ward_id=ward.id if ward else None,
        borrowed_at=dispatched,
        returned_at=received,
        status=TransactionStatus.CLOSED if received else TransactionStatus.OPEN,
        has_hn=has_hn,
        hn_added_at=hn_added_at,
        dispatch_checks=checks_d,
        receipt_checks=checks_r,
    )
    db.add(t)
    await db.flush()
    return t


async def _scenario(db) -> W:
    """Date 2026-07-28; night cut-off 08:00, day cut-off 20:00."""
    w = await _world(db)
    ISSUED = EquipmentStatus.ISSUED_TO_WARD
    e1, e2, e3, e4 = [await _eq(db, w, w.infusion, ISSUED) for _ in range(4)]
    e5 = await _eq(db, w, w.infusion)  # returned 07:00 -> at pool at both cut-offs
    await _eq(db, w, w.infusion)  # e6: never dispatched
    await _eq(db, w, w.infusion, EquipmentStatus.UNAVAILABLE_DEFECTIVE)  # e7: excluded
    await _eq(db, w, w.other)  # not infusion/pneumatic

    await _tx(db, w, e1, w.w5a, at(27, 21), checks_d=STD_NO_CHARGER)  # standby at both
    await _tx(db, w, e2, w.w5a, at(28, 1), has_hn=True)  # HN at dispatch: in use
    await _tx(db, w, e3, w.w5b, at(28, 9))  # dispatched after the night cut-off
    await _tx(db, w, e4, w.w5a, at(27, 22), has_hn=True, hn_added_at=at(28, 10), checks_d=STD_OK)  # HN added later
    await _tx(db, w, e5, w.w5b, at(27, 12), at(28, 7), checks_d=STD_OK, checks_r=STD_NO_CLAMP)

    p1, p2, p3, p4 = [await _eq(db, w, w.pneu, EquipmentStatus.ISSUED_TO_WARD) for _ in range(4)]
    await _tx(db, w, p1, w.w5a, at(27, 23))  # open at both
    await _tx(db, w, p2, w.w5a, at(27, 10), at(28, 3))  # returned within the business day
    await _tx(db, w, p3, w.w5b, at(27, 10), at(27, 15))  # returned before the business day began
    await _tx(db, w, p4, w.w5b, at(28, 9), at(28, 15))  # dispatched+returned between the cut-offs
    return w


async def _baseline(db, chargers=10, clamps=8):
    db.add(
        StandbySummaryConfig(
            category_role="infusion", chargers=chargers, clamps=clamps, baseline_set_at=at(27, 8)
        )
    )
    await db.commit()


async def _get(client, headers, cutoff, path=""):
    return await client.get(f"/api/v1/standby-summary{path}", headers=headers, params={"date": "2026-07-28", "cutoff": cutoff})


def _wards(body):
    return {w["label"]: w for w in body["infusion"]["wards"]}


# ------------------------------------------------------------------ counting


async def test_night_cutoff_standby_stock_and_pneumatic(client, seeded_users, db_session):
    await _scenario(db_session)
    await _baseline(db_session)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    r = await _get(client, staff, "night")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cutoff"] == "night" and body["cutoff_at"].startswith("2026-07-28T01:00:00")
    inf = body["infusion"]
    assert inf["categories"] == ["Infusion Pump"]
    wards = _wards(body)
    # e1 (no HN) + e4 (HN added after the cut-off => still Standby at 08:00); e2 has an HN.
    assert wards["W5A"]["system_value"] == 2
    assert wards["W5B"]["system_value"] == 0  # e3 dispatched after 08:00
    assert [w["label"] for w in inf["wards"]] == ["W5A", "W5B"]  # PR30 sort order
    # Devices at pool: e5 (received 07:00), e6, e3 (not yet out at 08:00); e7 defective excluded; e1/e2/e4 out.
    assert inf["bme_devices"]["system_value"] == 3
    # Chargers: baseline 10; dispatches e1(no charger) 0, e2(NULL) -1, e4 -1, e5 -1; receipt e5 +1 => 8.
    assert inf["chargers"]["system_value"] == 8
    # Clamps: baseline 8; dispatches e1,e2,e4,e5 -4; receipt e5 clamp False 0 => 4.
    assert inf["clamps"]["system_value"] == 4
    assert inf["ready"]["system_value"] == 3  # min(3, 8, 4)
    # Pneumatic: p1 open; p2 returned today (03:00); p3 before the business day; p4 later.
    pn = body["pneumatic"]
    assert pn["in_use"]["system_value"] == 1 and pn["returned"]["system_value"] == 1
    # Nothing carries a patient value.
    assert "hn" not in json.dumps(body).lower().replace("hn-", "")


async def test_day_cutoff_moves_counts(client, seeded_users, db_session):
    await _scenario(db_session)
    await _baseline(db_session)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    body = (await _get(client, staff, "day")).json()
    assert body["cutoff_at"].startswith("2026-07-28T13:00:00")
    wards = _wards(body)
    assert wards["W5A"]["system_value"] == 1  # e4's HN was added at 10:00 -> in use by 20:00
    assert wards["W5B"]["system_value"] == 1  # e3 dispatched 09:00, no HN
    inf = body["infusion"]
    assert inf["bme_devices"]["system_value"] == 2  # e5, e6 (e3 now out)
    assert inf["chargers"]["system_value"] == 7  # 8 - e3 (NULL checks count as present)
    assert inf["clamps"]["system_value"] == 3
    assert inf["ready"]["system_value"] == 2
    pn = body["pneumatic"]
    assert pn["in_use"]["system_value"] == 1 and pn["returned"]["system_value"] == 2  # + p4 (15:00)


async def test_no_baseline_means_unknown_stock_and_dash_in_text(client, seeded_users, db_session):
    await _scenario(db_session)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    inf = (await _get(client, staff, "night")).json()["infusion"]
    assert inf["chargers"]["system_value"] is None and inf["ready"]["system_value"] is None
    text = (await _get(client, staff, "night", "/text")).text
    assert "สายชาร์จ = -  Clamp = -" in text and "🟢พร้อมใช้งาน - เครื่อง" in text


async def test_cutoff_before_baseline_is_unknown(client, seeded_users, db_session):
    await _scenario(db_session)
    db_session.add(StandbySummaryConfig(category_role="infusion", chargers=5, clamps=5, baseline_set_at=at(29, 8)))
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    assert (await _get(client, staff, "day")).json()["infusion"]["chargers"]["system_value"] is None


async def test_returned_to_owner_equipment_is_excluded_when_column_exists(client, seeded_users, db_session, monkeypatch):
    w = await _scenario(db_session)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    before = (await _get(client, staff, "night")).json()["infusion"]["bme_devices"]["system_value"]
    # PR33 adds Equipment.returned_to_owner; emulate it without the column.
    monkeypatch.setattr(Equipment, "returned_to_owner", property(lambda self: self.bcm_code == "BCM-34-006"), raising=False)
    after = (await _get(client, staff, "night")).json()["infusion"]["bme_devices"]["system_value"]
    assert (before, after) == (3, 2)


async def test_explicit_category_mapping_replaces_name_match(client, seeded_users, db_session):
    w = await _scenario(db_session)
    await db_session.commit()
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    r = await client.put(
        "/api/v1/standby-summary/categories",
        headers=staff,
        json={"category_role": "infusion", "category_id": str(w.other.id)},
    )
    assert r.status_code == 403  # administrator only
    r = await client.put(
        "/api/v1/standby-summary/categories",
        headers=admin,
        json={"category_role": "infusion", "category_id": str(w.other.id)},
    )
    assert r.status_code == 200, r.text
    assert (await _get(client, staff, "night")).json()["infusion"]["categories"] == ["Monitor"]
    missing = await client.put(
        "/api/v1/standby-summary/categories",
        headers=admin,
        json={"category_role": "infusion", "category_id": str(uuid.uuid4())},
    )
    assert missing.status_code == 404
    reset = await client.put("/api/v1/standby-summary/categories", headers=admin, json={"category_role": "infusion"})
    assert reset.status_code == 200
    assert (await _get(client, staff, "night")).json()["infusion"]["categories"] == ["Infusion Pump"]


# ------------------------------------------------------------------ overrides


async def _audits(db_session, entity_type):
    db_session.expire_all()
    return (await db_session.execute(select(AuditLog).where(AuditLog.entity_type == entity_type).order_by(AuditLog.created_at))).scalars().all()


async def test_override_effective_value_reset_and_audit(client, seeded_users, db_session):
    await _scenario(db_session)
    await _baseline(db_session)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)

    async def put(field_key, value, cutoff="night"):
        return await client.put(
            "/api/v1/standby-summary/overrides",
            headers=staff,
            json={"date": "2026-07-28", "cutoff": cutoff, "field_key": field_key, "value": value},
        )

    r = await put("ward:W5A", 5)
    assert r.status_code == 200, r.text
    w5a = _wards(r.json())["W5A"]
    assert (w5a["system_value"], w5a["override_value"], w5a["effective_value"]) == (2, 5, 5)

    # Chargers edit flows into ready (min of the effective components).
    r = await put("chargers", 1)
    inf = r.json()["infusion"]
    assert (inf["chargers"]["system_value"], inf["chargers"]["effective_value"]) == (8, 1)
    assert inf["ready"]["system_value"] == 1 and inf["ready"]["effective_value"] == 1
    # An edit on ready itself keeps the system value visible.
    inf = (await put("ready", 2)).json()["infusion"]
    assert (inf["ready"]["system_value"], inf["ready"]["override_value"], inf["ready"]["effective_value"]) == (1, 2, 2)
    # Pneumatic edit; the other cut-off is untouched.
    assert (await put("pneumatic_in_use", 9)).json()["pneumatic"]["in_use"]["effective_value"] == 9
    day = (await _get(client, staff, "day")).json()
    assert _wards(day)["W5A"]["override_value"] is None and day["pneumatic"]["in_use"]["override_value"] is None

    # Replace (update, unique per date/cut-off/key) then reset.
    await put("ward:W5A", 6)
    rows = (await db_session.execute(select(StandbySummaryOverride).where(StandbySummaryOverride.field_key == "ward:W5A"))).scalars().all()
    assert len(rows) == 1 and rows[0].value == 6 and rows[0].section == "infusion" and rows[0].edited_by_user_id is not None
    r = await put("ward:W5A", None)
    assert _wards(r.json())["W5A"]["override_value"] is None and _wards(r.json())["W5A"]["effective_value"] == 2
    assert (await put("ward:W5A", None)).status_code == 200  # resetting nothing is harmless

    audits = await _audits(db_session, "standby_summary_override")
    w5a_audits = [a for a in audits if (a.after_data or a.before_data or {}).get("field_key") == "ward:W5A"]
    assert [a.action for a in w5a_audits] == ["create", "update", "delete"]
    assert w5a_audits[0].after_data["value"] == 5 and w5a_audits[1].before_data["value"] == 5
    assert w5a_audits[1].after_data["value"] == 6 and w5a_audits[2].before_data["value"] == 6
    assert all(a.user_id is not None for a in audits)


async def test_override_validation(client, seeded_users, db_session):
    await _scenario(db_session)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    base = {"date": "2026-07-28", "cutoff": "night", "field_key": "ready", "value": 1}
    url = "/api/v1/standby-summary/overrides"
    assert (await client.put(url, headers=staff, json={**base, "value": -1})).status_code == 422
    assert (await client.put(url, headers=staff, json={**base, "cutoff": "noon"})).status_code == 422
    assert (await client.put(url, headers=staff, json={**base, "field_key": "patient_name"})).status_code == 400
    assert (await client.put(url, headers=staff, json={**base, "extra": 1})).status_code == 422


async def test_baseline_put_audited_and_role_gated(client, seeded_users, db_session):
    await _scenario(db_session)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    body = {"category_role": "infusion", "chargers": 12, "clamps": 9}
    assert (await client.put("/api/v1/standby-summary/baseline", headers=ro, json=body)).status_code == 403
    r = await client.put("/api/v1/standby-summary/baseline", headers=staff, json=body)
    assert r.status_code == 200 and r.json()["chargers"] == 12 and r.json()["set_at"] is not None
    r = await client.put("/api/v1/standby-summary/baseline", headers=staff, json={**body, "chargers": 11})
    assert r.status_code == 200
    audits = await _audits(db_session, "standby_summary_config")
    assert [a.action for a in audits] == ["create", "update"]
    assert audits[1].before_data["chargers"] == 12 and audits[1].after_data["chargers"] == 11
    assert (await client.put("/api/v1/standby-summary/baseline", headers=staff, json={**body, "clamps": -1})).status_code == 422


# ------------------------------------------------------------------ copy text


async def test_copy_text_exact_format_uses_effective_values(client, seeded_users, db_session):
    await _scenario(db_session)
    await _baseline(db_session)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    r = await _get(client, staff, "night", "/text")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.text == (
        "Infusion pump standby\n"
        "28/07/2026\n"
        "W5A = 2 เครื่อง\n"
        "W5B = -\n"
        "BME = เครื่องใหม่ 3 เครื่อง\n"
        "🟢พร้อมใช้งาน 3 เครื่อง\n"
        "สายชาร์จ = 8  Clamp = 4\n"
        "🟡 Pneumatic PUMP🟡\n"
        "เครื่องที่ใช้งานอยู่ ⏩ : 1\n"
        "รับคืนเครื่องวันนี้ ⏩ : 1"
    )
    await client.put(
        "/api/v1/standby-summary/overrides",
        headers=staff,
        json={"date": "2026-07-28", "cutoff": "night", "field_key": "ward:W5B", "value": 4},
    )
    await client.put(
        "/api/v1/standby-summary/overrides",
        headers=staff,
        json={"date": "2026-07-28", "cutoff": "night", "field_key": "ward:W5A", "value": 0},
    )
    text = (await _get(client, staff, "night", "/text")).text
    assert "W5A = -\nW5B = 4 เครื่อง\n" in text


# ------------------------------------------------------------------ Excel


async def test_daily_excel_stand_by_column_uses_day_cutoff_effective_values(client, seeded_users, db_session):
    await _scenario(db_session)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)

    def standby_col(content):
        ws = load_workbook(io.BytesIO(content))["รายงาน"]
        header = [c.value for c in ws[1]]
        assert header[7] == "Stand By"
        return {row[2].value: row[7].value for row in ws.iter_rows(min_row=3, max_row=ws.max_row - 1)}

    r = await client.get("/api/v1/reports/daily-summary.xlsx", headers=staff, params={"date": "2026-07-28"})
    assert r.status_code == 200, r.text
    col = standby_col(r.content)
    assert col["W5A"] == 1 and col["W5B"] == 1  # day (20:00) cut-off system values

    # Night-cutoff edits do not leak in; a day-cutoff edit does; 0 renders blank.
    for cutoff, key, value in (("night", "ward:W5A", 9), ("day", "ward:W5A", 5), ("day", "ward:W5B", 0)):
        await client.put(
            "/api/v1/standby-summary/overrides",
            headers=staff,
            json={"date": "2026-07-28", "cutoff": cutoff, "field_key": key, "value": value},
        )
    col = standby_col((await client.get("/api/v1/reports/daily-summary.xlsx", headers=staff, params={"date": "2026-07-28"})).content)
    assert col["W5A"] == 5 and col["W5B"] is None


# ------------------------------------------------------------------ roles


async def test_roles_and_auth(client, seeded_users, db_session):
    await _scenario(db_session)
    await db_session.commit()
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    params = {"date": "2026-07-28", "cutoff": "night"}
    assert (await client.get("/api/v1/standby-summary", params=params)).status_code in (401, 403)
    for path in ("", "/text"):
        assert (await client.get(f"/api/v1/standby-summary{path}", headers=ro, params=params)).status_code == 403
        assert (await client.get(f"/api/v1/standby-summary{path}", headers=admin, params=params)).status_code == 200
    put = {"date": "2026-07-28", "cutoff": "night", "field_key": "ready", "value": 1}
    assert (await client.put("/api/v1/standby-summary/overrides", headers=ro, json=put)).status_code == 403
    assert (await client.get("/api/v1/standby-summary", headers=admin, params={"date": "2026-07-28", "cutoff": "x"})).status_code == 422


# ------------------------------------------------------------------ add HN later (D15)


async def _api_dispatch(client, headers, ward_id, n, **extra):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    r = await client.post(
        "/api/v1/equipment",
        headers=admin,
        json={"asset_number": f"AST-34-{n}", "equipment_name": f"Dev {n}", "bcm_code": f"BCM-HN-{n}"},
    )
    assert r.status_code == 201, r.text
    eq = r.json()["id"]
    b = await client.post("/api/v1/borrow", headers=headers, json={"equipment_id": eq, "ward_id": ward_id, **extra})
    assert b.status_code in (200, 201), b.text
    return eq, b.json()


async def _tx_row(db_session, tx_id) -> BorrowTransaction:
    db_session.expire_all()
    return (await db_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx_id)))).scalar_one()


async def test_add_hn_later_success_rules_audit_and_no_leak(client, seeded_users, db_session, hn_key):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ro = await _auth_headers(client, ROLE_READ_ONLY)
    ward = await _create_ward(client, admin, "W-34", "Ward 34")
    eq, tx = await _api_dispatch(client, staff, ward, 1)
    assert tx["has_hn"] is False
    url = f"/api/v1/transactions/{tx['id']}/hn"

    assert (await client.post(url, headers=ro, json={"hn": HN})).status_code == 403
    assert (await client.post(f"/api/v1/transactions/{uuid.uuid4()}/hn", headers=staff, json={"hn": HN})).status_code == 404

    # Format errors: 422, never echoing the value.
    bad = await client.post(url, headers=staff, json={"hn": "bad hn!!"})
    assert bad.status_code == 422 and "bad hn" not in bad.text
    assert (await client.post(url, headers=staff, json={"hn": "  "})).status_code == 422
    assert (await client.post(url, headers=staff, json={})).status_code == 422
    assert (await _tx_row(db_session, tx["id"])).has_hn is False

    r = await client.post(url, headers=staff, json={"hn": HN})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    out = r.json()
    assert out["has_hn"] is True and HN not in r.text and "hn_ciphertext" not in out

    row = await _tx_row(db_session, tx["id"])
    assert row.has_hn is True and row.hn_added_at is not None
    ciphertext = (
        await db_session.execute(select(BorrowTransaction.hn_ciphertext).where(BorrowTransaction.id == row.id))
    ).scalar_one()
    assert ciphertext and HN not in ciphertext  # encrypted at rest
    assert (await client.post(f"/api/v1/transactions/{tx['id']}/reveal-hn", headers=staff)).json()["hn"] == HN

    # Replacing is refused.
    again = await client.post(url, headers=staff, json={"hn": "HN-9999"})
    assert again.status_code == 409 and again.json()["code"] == "HN_ALREADY_RECORDED"
    assert HN not in again.text

    # Audit: who/which transaction, never the value (nor the ciphertext).
    audits = [a for a in await _audits(db_session, "borrow_transaction") if a.action == "hn_add"]
    assert len(audits) == 1 and audits[0].user_id is not None and str(audits[0].entity_id) == tx["id"]
    blob = json.dumps([audits[0].before_data, audits[0].after_data])
    assert HN not in blob and ciphertext not in blob and "9999" not in blob


async def test_add_hn_requires_open_dispatch_and_key(client, seeded_users, db_session, hn_key, monkeypatch):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward = await _create_ward(client, admin, "W-34B", "Ward 34B")

    # Closed (received) -> 409 TRANSACTION_NOT_OPEN
    eq, tx = await _api_dispatch(client, staff, ward, 2)
    rec = await client.post(f"/api/v1/return/{tx['id']}", headers=staff, json={"receipt_outcome": "usable"})
    assert rec.status_code == 200, rec.text
    closed = await client.post(f"/api/v1/transactions/{tx['id']}/hn", headers=staff, json={"hn": HN})
    assert closed.status_code == 409 and "TRANSACTION_NOT_OPEN" in closed.text
    assert (await _tx_row(db_session, tx["id"])).has_hn is False

    # HN given at dispatch -> cannot be replaced.
    _, tx2 = await _api_dispatch(client, staff, ward, 3, hn=HN)
    assert tx2["has_hn"] is True
    r = await client.post(f"/api/v1/transactions/{tx2['id']}/hn", headers=staff, json={"hn": "HN-1"})
    assert r.status_code == 409 and "HN_ALREADY_RECORDED" in r.text

    # No encryption key -> 503, nothing stored.
    _, tx3 = await _api_dispatch(client, staff, ward, 4)
    monkeypatch.setattr(get_settings(), "HN_ENCRYPTION_KEY", None)
    r = await client.post(f"/api/v1/transactions/{tx3['id']}/hn", headers=staff, json={"hn": HN})
    assert r.status_code == 503
    assert (await _tx_row(db_session, tx3["id"])).has_hn is False


async def test_adding_hn_converts_standby_to_in_use_in_summary(client, seeded_users, db_session, hn_key):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward = await _create_ward(client, admin, "W-34C", "Ward 34C")
    r = await client.post("/api/v1/categories", headers=admin, json={"name": "Infusion Pump"})
    assert r.status_code == 201, r.text
    cat = r.json()["id"]
    eq = await client.post(
        "/api/v1/equipment",
        headers=admin,
        json={"asset_number": "AST-34-S", "equipment_name": "Pump", "bcm_code": "BCM-S-1", "category_id": cat},
    )
    assert eq.status_code == 201, eq.text
    b = await client.post("/api/v1/borrow", headers=staff, json={"equipment_id": eq.json()["id"], "ward_id": ward})
    assert b.status_code in (200, 201), b.text
    tomorrow = datetime.now(BKK).date() + timedelta(days=1)
    params = {"date": tomorrow.isoformat(), "cutoff": "day"}  # cut-off safely after "now"
    before = (await client.get("/api/v1/standby-summary", headers=staff, params=params)).json()
    assert [w["system_value"] for w in before["infusion"]["wards"]] == [1]
    await client.post(f"/api/v1/transactions/{b.json()['id']}/hn", headers=staff, json={"hn": HN})
    after = (await client.get("/api/v1/standby-summary", headers=staff, params=params)).json()
    assert after["infusion"]["wards"] == []  # default-mapped ward with nothing on standby is omitted
    assert HN not in json.dumps(after)


async def test_monitor_flags_open_dispatches_so_add_hn_can_be_offered(client, seeded_users, db_session):
    await _scenario(db_session)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    params = {"kind": "dispatch", "business_date_from": "2026-07-01", "business_date_to": "2026-07-31", "limit": 100}
    items = (await client.get("/api/v1/monitor/events", headers=staff, params=params)).json()["items"]
    by_code = {i["equipment"]["bcm_code"]: i for i in items}
    assert by_code["BCM-34-001"]["is_open"] is True and by_code["BCM-34-001"]["has_hn"] is False  # standby
    assert by_code["BCM-34-005"]["is_open"] is False  # received
    receipts = (await client.get("/api/v1/monitor/events", headers=staff, params={**params, "kind": "receipt"})).json()["items"]
    assert receipts and all(r["is_open"] is False for r in receipts)


async def test_copy_text_shows_dash_for_every_zero_or_blank(client, seeded_users, db_session):
    await _scenario(db_session)
    await _baseline(db_session)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    for key in ("ward:W5A", "bme_devices", "chargers", "clamps", "ready", "pneumatic_in_use", "pneumatic_returned"):
        r = await client.put(
            "/api/v1/standby-summary/overrides",
            headers=staff,
            json={"date": "2026-07-28", "cutoff": "night", "field_key": key, "value": 0},
        )
        assert r.status_code == 200, r.text
    text = (await _get(client, staff, "night", "/text")).text
    assert text == (
        "Infusion pump standby\n28/07/2026\nW5A = -\nW5B = -\n"
        "BME = เครื่องใหม่ - เครื่อง\n🟢พร้อมใช้งาน - เครื่อง\nสายชาร์จ = -  Clamp = -\n"
        "🟡 Pneumatic PUMP🟡\nเครื่องที่ใช้งานอยู่ ⏩ : -\nรับคืนเครื่องวันนี้ ⏩ : -"
    )


async def test_redispatch_closed_transaction_open_state_at_cutoff(client, seeded_users, db_session):
    w = await _world(db_session)
    eq = await _eq(db_session, w, w.infusion, EquipmentStatus.ISSUED_TO_WARD)
    a = await _tx(db_session, w, eq, w.w5a, at(27, 21))
    a.status = TransactionStatus.CLOSED
    a.close_reason = "closed by re-dispatch, receipt not recorded"
    await _tx(db_session, w, eq, w.w5b, at(28, 9))  # B: re-dispatch after the night cut-off (08:00)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    night = _wards((await _get(client, staff, "night")).json())
    day = _wards((await _get(client, staff, "day")).json())
    # Night 08:00: B not yet dispatched -> A still open at W5A.
    assert (night["W5A"]["system_value"], night["W5B"]["system_value"]) == (1, 0)
    # Day 20:00: B at W5B, A closed.
    assert (day["W5A"]["system_value"], day["W5B"]["system_value"]) == (0, 1)


async def test_override_insert_race_retries_instead_of_500(client, seeded_users, db_session, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    await _scenario(db_session)
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    real = svc._set_override_once
    calls = {"n": 0}

    async def racing(db, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # A concurrent request wins the insert first.
            db.add(StandbySummaryOverride(summary_date=D, cutoff="night", section="infusion", field_key="ready", value=7))
            await db.commit()
            raise IntegrityError("insert", {}, Exception("unique"))
        return await real(db, **kw)

    monkeypatch.setattr(svc, "_set_override_once", racing)
    r = await client.put(
        "/api/v1/standby-summary/overrides",
        headers=staff,
        json={"date": "2026-07-28", "cutoff": "night", "field_key": "ready", "value": 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["infusion"]["ready"]["override_value"] == 2 and calls["n"] == 2
