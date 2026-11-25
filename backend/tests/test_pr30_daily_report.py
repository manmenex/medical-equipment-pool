"""Roadmap PR30 (D5/D6/D12): daily shift summary workbook + printable daily forms."""
import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import weasyprint
from openpyxl import load_workbook

from app.models.equipment import Equipment
from app.models.master_data import Department, EquipmentCategory, Ward
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, Role, User
from app.core.reporting_time import Shift
from app.services import daily_report_forms_service as forms
from app.services import daily_report_service as svc
from app.services import daily_report_xlsx_service as xlsx
from tests.conftest import auth_headers as _auth_headers, cached_password_hash

D = date(2026, 7, 28)
BKK = ZoneInfo("Asia/Bangkok")


def at(day: int, hh: int, mm: int = 0, ss: int = 0, month: int = 7) -> datetime:
    """Asia/Bangkok wall clock -> aware UTC."""
    return datetime(2026, month, day, hh, mm, ss, tzinfo=BKK).astimezone(timezone.utc)


# ------------------------------------------------------------------ pure logic


def local(day, hh, mm=0):
    return datetime(2026, 7, day, hh, mm)


def test_report_date_is_previous_night_plus_day_shift():
    inst = svc.report_instances(D)
    assert inst == {datetime(2026, 7, 27, 20, 0): Shift.NIGHT, datetime(2026, 7, 28, 8, 0): Shift.DAY}
    # Instance containment, including the post-midnight part of the night shift.
    assert svc.instance_start(local(27, 20, 0)) == datetime(2026, 7, 27, 20, 0)
    assert svc.instance_start(local(28, 3, 0)) == datetime(2026, 7, 27, 20, 0)
    assert svc.instance_start(local(28, 7, 59)) == datetime(2026, 7, 27, 20, 0)
    assert svc.instance_start(local(28, 8, 0)) == datetime(2026, 7, 28, 8, 0)
    assert svc.instance_start(local(28, 19, 59)) == datetime(2026, 7, 28, 8, 0)
    assert svc.instance_start(local(28, 20, 0)) == datetime(2026, 7, 28, 20, 0)


def test_window_boundary_respects_grace_and_zero_is_strict():
    assert svc.window_boundary(local(28, 8, 30), 60) == datetime(2026, 7, 28, 8, 0)
    assert svc.window_boundary(local(28, 7, 0), 60) == datetime(2026, 7, 28, 8, 0)  # window start inclusive
    assert svc.window_boundary(local(28, 6, 59), 60) is None
    assert svc.window_boundary(local(28, 9, 0), 60) is None  # window end exclusive
    assert svc.window_boundary(local(27, 20, 10), 60) == datetime(2026, 7, 27, 20, 0)
    assert svc.window_boundary(local(28, 8, 30), 0) is None
    assert svc.window_boundary(local(28, 7, 59), 0) is None


def _ev(op, day, hh, mm=0, kind="dispatch"):
    t = local(day, hh, mm)
    return svc.DailyEvent(
        kind=kind,
        at=t,
        local=t,
        operator_id=op,
        operator_name="x",
        transaction_id=uuid.uuid4(),
        bcm_code="B",
        category_name="C",
        ward_id=None,
        ward_name="W",
        contact_name=None,
        checks={},
        notes=None,
    )


def test_attribution_predominant_shift_tie_and_strict():
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    # a worked the night (3 events outside any window) and keyed one at 08:20.
    # b has one night + one day event outside windows (tie). c has no other events.
    # d worked the day (outside windows) and keyed one at 07:40 (clock: night).
    events = [
        _ev(a, 27, 22), _ev(a, 27, 23), _ev(a, 28, 2), a_late := _ev(a, 28, 8, 20),
        _ev(b, 27, 22), _ev(b, 28, 12), b_late := _ev(b, 28, 8, 20),
        c_late := _ev(c, 28, 8, 20),
        _ev(d, 28, 10), _ev(d, 28, 11), d_early := _ev(d, 28, 7, 40),
    ]
    svc.attribute_shifts(events, 60)
    assert a_late.clock_shift == Shift.DAY and a_late.shift == Shift.NIGHT
    assert a_late.instance == datetime(2026, 7, 27, 20, 0)
    assert b_late.shift == Shift.DAY  # tie -> clock rule
    assert c_late.shift == Shift.DAY  # no other events -> clock rule
    assert d_early.clock_shift == Shift.NIGHT and d_early.shift == Shift.DAY
    assert d_early.instance == datetime(2026, 7, 28, 8, 0)

    svc.attribute_shifts(events, 0)  # strict
    assert a_late.shift == Shift.DAY and d_early.shift == Shift.NIGHT


def test_attribution_window_events_do_not_vote_and_no_operator_falls_back():
    a = uuid.uuid4()
    # Only window events for `a` (they never count as "outside the window").
    events = [_ev(a, 28, 7, 30), _ev(a, 28, 8, 30), _ev(None, 28, 8, 10)]
    svc.attribute_shifts(events, 60)
    assert [e.shift for e in events] == [Shift.NIGHT, Shift.DAY, Shift.DAY]


def test_grace_validation():
    assert svc.validate_grace(0) == 0
    with pytest.raises(Exception):
        svc.validate_grace(-1)
    with pytest.raises(Exception):
        svc.validate_grace(svc.MAX_GRACE_MINUTES + 1)


def test_format_date():
    assert svc.format_date(date(2026, 7, 5)) == "05/Jul/2026"


# ------------------------------------------------------------------ fixtures


class World:
    pass


async def _world(db, seeded_users) -> World:
    w = World()
    w.dept_a = Department(code="DA", name="IPD ตึก A")
    w.dept_b = Department(code="DB", name="OPD")
    db.add_all([w.dept_a, w.dept_b])
    await db.flush()
    w.w5a = Ward(code="W5A", name="Ward 5A", department_id=w.dept_a.id)
    w.w5b = Ward(code="W5B", name="Ward 5B", department_id=w.dept_a.id)
    w.w6 = Ward(code="W6", name="Ward 6", department_id=w.dept_b.id)
    db.add_all([w.w5a, w.w5b, w.w6])
    w.pump = EquipmentCategory(name="Infusion Pump")
    w.cryo = EquipmentCategory(name="Cryo-Cuff", checklist_kind="cryo_cuff")
    db.add_all([w.pump, w.cryo])
    role = Role(name="pool_extra", permissions={})
    db.add(role)
    await db.flush()
    w.bme_a = User(employee_code="BME-A", full_name="BME Alpha", email="a@t.dev", password_hash="x", role_id=role.id)
    w.bme_b = User(employee_code="BME-B", full_name="BME Beta", email="b@t.dev", password_hash="x", role_id=role.id)
    db.add_all([w.bme_a, w.bme_b])
    await db.flush()
    w.n = 0
    return w


async def _tx(db, w, *, ward, category, dispatched, received=None, op_d=None, op_r=None, checks_d=None,
              checks_r=None, contact_d=None, contact_r=None, notes=None, bcm=None):
    w.n += 1
    eq = Equipment(equipment_name="Dev", bcm_code=bcm or f"BCM-{w.n:03d}", asset_number=f"A-{w.n}", category_id=category.id)
    db.add(eq)
    await db.flush()
    t = BorrowTransaction(
        transaction_no=f"T-{w.n}",
        equipment_id=eq.id,
        borrowed_at=dispatched,
        returned_at=received,
        ward_id=ward.id if ward else None,
        borrower_user_id=op_d.id if op_d else None,
        received_by_user_id=op_r.id if op_r else None,
        status=TransactionStatus.CLOSED if received else TransactionStatus.OPEN,
        dispatch_checks=checks_d,
        receipt_checks=checks_r,
        dispatch_contact_name=contact_d,
        receipt_contact_name=contact_r,
        notes=notes,
    )
    db.add(t)
    await db.flush()
    return t


STD_OK = {"kind": "standard", "screen_ok": True, "charger_ok": True, "clamp_ok": True}
STD_BAD = {"kind": "standard", "screen_ok": True, "charger_ok": False, "clamp_ok": True}


async def _scenario(db, seeded_users) -> World:
    """Report date D=2026-07-28. Night shift started 07-27 20:00; Day 07-28 08:00-20:00."""
    w = await _world(db, seeded_users)
    a, b = w.bme_a, w.bme_b
    # Alpha works the night: 3 dispatches (one past midnight) + a receipt keyed at 08:20 (window).
    await _tx(db, w, ward=w.w5a, category=w.pump, dispatched=at(27, 21, 0), op_d=a, checks_d=STD_OK, contact_d="Nurse Som")
    await _tx(db, w, ward=w.w5b, category=w.pump, dispatched=at(28, 1, 30), op_d=a, checks_d=STD_BAD)
    await _tx(db, w, ward=w.w6, category=w.cryo, dispatched=at(28, 2, 0), op_d=a,
              checks_d={"kind": "cryo_cuff", "body_ok": True, "charger_ok": False, "lid_with_charger_ok": True,
                        "lid_without_charger_ok": False, "hose_oring_ok": False, "cuff_ok": False})
    await _tx(db, w, ward=w.w5a, category=w.pump, dispatched=at(27, 21, 30), op_d=a,
              received=at(28, 8, 20), op_r=a, checks_r=STD_OK, contact_r="Nurse Malee", notes="ok")
    # Beta works the day: dispatch + receipts.
    await _tx(db, w, ward=w.w6, category=w.pump, dispatched=at(28, 10, 0), op_d=b)  # checks NULL
    await _tx(db, w, ward=w.w5a, category=w.pump, dispatched=at(27, 10, 0), received=at(28, 11, 0), op_d=b, op_r=b)
    await _tx(db, w, ward=None, category=w.pump, dispatched=at(28, 12, 0), op_d=b)
    # Outside the report: Night of D (starts 20:00 on D) and an old event.
    await _tx(db, w, ward=w.w6, category=w.pump, dispatched=at(28, 21, 0), op_d=b)
    await _tx(db, w, ward=w.w6, category=w.pump, dispatched=at(26, 12, 0), op_d=b)
    await db.commit()
    return w


async def _get_xlsx(client, headers, **params):
    resp = await client.get("/api/v1/reports/daily-summary.xlsx", headers=headers, params=params)
    return resp


def _rows(ws):
    return [[c.value for c in row] for row in ws.iter_rows()]


# ------------------------------------------------------------------ workbook


@pytest.mark.asyncio
async def test_workbook_sheets_headers_and_counts(client, seeded_users, db_session):
    await _scenario(db_session, seeded_users)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await _get_xlsx(client, staff, date="2026-07-28")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["รายงาน", "ชนิดเครื่อง", "ผู้คีย์", "รายการ"]

    # Sheet 1: verbatim headers; default mapping (row = ward name, treatment = department).
    ws = wb["รายงาน"]
    rows = _rows(ws)
    assert rows[0] == ["รูปแบบการจ่ายเครื่อง", "ประเภทการรักษา", "แผนก", "Night", None, "Day", None, "Stand By", "Total per DAY", None]
    assert rows[1] == [None, None, None, "ส่ง", "รับ", "ส่ง", "รับ", None, "ส่งเครื่อง", "รับคืน"]
    body = {r[2]: r for r in rows[2:-1]}
    # Night (clock) dispatches: 5A(21:00, 21:30), 5B(01:30), 6(02:00); receipt 08:20 attributed to Night by D6.
    assert body["Ward 5A"][1] == "IPD ตึก A"
    assert body["Ward 5A"][3:7] == [2, 1, 0, 1]  # night disp 2 / night rcpt 1 (D6) / day disp 0 / day rcpt 1 (11:00)
    assert body["Ward 5A"][8:10] == [2, 2]
    assert body["Ward 5B"][3:7] == [1, 0, 0, 0]
    assert body["Ward 6"][3:7] == [1, 0, 1, 0]
    assert body[svc.UNSPECIFIED_LABEL][3:7] == [0, 0, 1, 0]
    total = rows[-1]
    assert total[0] == "รวม"
    assert total[3:7] == [4, 1, 2, 1] and total[8:10] == [6, 2]

    # Sheet 2: equipment type.
    cat = _rows(wb["ชนิดเครื่อง"])
    assert cat[0] == ["ชนิดเครื่อง", "Night", None, "Day", None, "Total per DAY", None, "รวม"]
    assert cat[1] == [None, "ส่ง", "รับ", "ส่ง", "รับ", "ส่งเครื่อง", "รับคืน", None]
    by_cat = {r[0]: r for r in cat[2:-1]}
    assert by_cat["Infusion Pump"][1:] == [3, 1, 2, 1, 5, 2, 7]
    assert by_cat["Cryo-Cuff"][1:] == [1, 0, 0, 0, 1, 0, 1]
    assert cat[-1] == ["รวม", 4, 1, 2, 1, 6, 2, 8]

    # Sheet 3: operators.
    op = _rows(wb["ผู้คีย์"])
    assert op[0][0] == "รวม 2 กะ วันที่ 28/Jul/2026"
    assert op[1] == ["ผู้คีย์", "กะดึก ส่ง", "กะดึก รับ", "กะเช้า ส่ง", "กะเช้า รับ", "รวม ส่ง", "รวม รับ", "รวมทั้งหมด"]
    by_op = {r[0]: r for r in op[2:-1]}
    assert by_op["BME Alpha"][1:] == [4, 1, 0, 0, 4, 1, 5]
    assert by_op["BME Beta"][1:] == [0, 0, 2, 1, 2, 1, 3]
    assert op[-1] == ["รวม", 4, 1, 2, 1, 6, 2, 8]
    # Operator totals reconcile with the ward-group totals.
    assert sum(r[7] for r in op[2:-1]) == total[8] + total[9]

    # Sheet 4: every event, verbatim headers, formats.
    ev = _rows(wb["รายการ"])
    assert ev[0] == ["กะ", "วันที่", "เวลา", "งาน", "ID CODE (BCM)", "ชนิดเครื่อง", "Ward (ในฟอร์ม)", "แถวในรายงาน",
                     "ผู้คีย์ (BME)", "หมายเหตุ", "ตำแหน่งในฟอร์ม"]
    assert len(ev) - 1 == 8
    first = ev[1]
    assert first[0] == "กะดึก" and first[1] == "27/Jul/2026" and first[2] == "21:00:00" and first[3] == "ส่ง"
    assert first[4].startswith("BCM-") and first[6] == "Ward 5A" and first[7] == "Ward 5A" and first[8] == "BME Alpha"
    assert first[10] == "หน้า 1 แถว 1"
    receipt_0820 = next(r for r in ev[1:] if r[2] == "08:20:00")
    assert receipt_0820[0] == "กะดึก" and receipt_0820[3] == "รับ" and receipt_0820[9] == "ok"
    # Times are time-ordered.
    keys = [(r[1][-4:], r[1][3:6], r[1][:2], r[2]) for r in ev[1:]]
    assert len(keys) == len(ev) - 1


@pytest.mark.asyncio
async def test_strict_grace_changes_attribution(client, seeded_users, db_session):
    await _scenario(db_session, seeded_users)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await _get_xlsx(client, staff, date="2026-07-28", grace_minutes=0)
    wb = load_workbook(io.BytesIO(resp.content))
    ev = _rows(wb["รายการ"])
    receipt_0820 = next(r for r in ev[1:] if r[2] == "08:20:00")
    assert receipt_0820[0] == "กะเช้า"
    body = {r[2]: r for r in _rows(wb["รายงาน"])[2:-1]}
    assert body["Ward 5A"][3:7] == [2, 0, 0, 2]


@pytest.mark.asyncio
async def test_ward_mapping_rollup_and_admin_api(client, seeded_users, db_session):
    w = await _scenario(db_session, seeded_users)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)

    listing = await client.get("/api/v1/reports/ward-rows", headers=admin)
    assert listing.status_code == 200
    by_name = {r["ward_name"]: r for r in listing.json()}
    assert by_name["Ward 5A"]["report_row_label"] == "Ward 5A" and by_name["Ward 5A"]["treatment_type"] == "IPD ตึก A"
    assert by_name["Ward 5A"]["is_override"] is False

    # Roll both 5A and 5B up into "Ward 5", Standby support group, ordered first.
    for ward in (w.w5a, w.w5b):
        r = await client.put(
            f"/api/v1/reports/ward-rows/{ward.id}",
            headers=admin,
            json={"report_row_label": " Ward 5 ", "dispense_mode": "Standby support", "treatment_type": "IPD ตึก A", "sort_order": 1},
        )
        assert r.status_code == 200, r.text
        assert r.json()["report_row_label"] == "Ward 5" and r.json()["is_override"] is True

    wb = load_workbook(io.BytesIO((await _get_xlsx(client, staff, date="2026-07-28")).content))
    rows = _rows(wb["รายงาน"])[2:-1]
    labels = [r[2] for r in rows]
    assert labels == ["Ward 6", "Ward 5", svc.UNSPECIFIED_LABEL]  # by sort_order; unmapped last
    assert "Ward 5A" not in labels and "Ward 5B" not in labels
    ward5 = next(r for r in rows if r[2] == "Ward 5")
    assert ward5[0] == "Standby support"
    assert ward5[3:7] == [3, 1, 0, 1]
    ev = _rows(wb["รายการ"])
    assert {r[7] for r in ev[1:] if r[6] in ("Ward 5A", "Ward 5B")} == {"Ward 5"}  # Ward (ในฟอร์ม) keeps the real ward

    # Reset reverts to default; unknown ward 404.
    assert (await client.delete(f"/api/v1/reports/ward-rows/{w.w5a.id}", headers=admin)).status_code == 204
    assert (await client.delete(f"/api/v1/reports/ward-rows/{w.w5a.id}", headers=admin)).status_code == 404
    assert (await client.put(f"/api/v1/reports/ward-rows/{uuid.uuid4()}", headers=admin, json={})).status_code == 404
    assert (await client.put(f"/api/v1/reports/ward-rows/{w.w6.id}", headers=admin, json={"bogus": 1})).status_code == 422

    # Mapping is admin only.
    assert (await client.get("/api/v1/reports/ward-rows", headers=staff)).status_code == 403
    assert (await client.put(f"/api/v1/reports/ward-rows/{w.w6.id}", headers=staff, json={})).status_code == 403


@pytest.mark.asyncio
async def test_formula_injection_is_neutralised(client, seeded_users, db_session):
    w = await _world(db_session, seeded_users)
    evil = Ward(code="EV", name="=HYPERLINK(\"http://x\")", department_id=None)
    db_session.add(evil)
    await db_session.flush()
    await _tx(db_session, w, ward=evil, category=w.pump, dispatched=at(28, 10), op_d=w.bme_a, notes="@SUM(1)")
    await db_session.commit()
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    wb = load_workbook(io.BytesIO((await _get_xlsx(client, staff, date="2026-07-28")).content))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    assert not cell.value.startswith(("=", "@", "+")), (ws.title, cell.coordinate, cell.value)
    assert any(c.value == "'@SUM(1)" for row in wb["รายการ"].iter_rows() for c in row)


@pytest.mark.asyncio
async def test_hn_never_present(client, seeded_users, db_session):
    await _scenario(db_session, seeded_users)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    wb = load_workbook(io.BytesIO((await _get_xlsx(client, staff, date="2026-07-28")).content))
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    assert not re.search(r"\bHN\b", cell.value, re.IGNORECASE), (ws.title, cell.value)
    report = await svc.build_daily_report(db_session, D, 60)
    html_doc = forms.render_forms_html(report, "both")
    assert not re.search(r"\bHN\b", html_doc, re.IGNORECASE)
    assert not any("hn" in f.lower().split("_") for f in svc.DailyEvent.__dataclass_fields__)


@pytest.mark.asyncio
async def test_roles_and_validation(client, seeded_users, db_session):
    await _scenario(db_session, seeded_users)
    for path in ("/api/v1/reports/daily-summary.xlsx", "/api/v1/reports/daily-forms.pdf"):
        assert (await client.get(path, params={"date": "2026-07-28"})).status_code == 401
        ro = await _auth_headers(client, ROLE_READ_ONLY)
        assert (await client.get(path, headers=ro, params={"date": "2026-07-28"})).status_code == 403
        for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF):
            h = await _auth_headers(client, role)
            assert (await client.get(path, headers=h, params={"date": "2026-07-28"})).status_code == 200
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    assert (await _get_xlsx(client, staff, date="2026-07-28", grace_minutes=-5)).status_code == 400
    assert (await _get_xlsx(client, staff, date="2026-07-28", grace_minutes=999)).status_code == 400
    assert (await _get_xlsx(client, staff, date="not-a-date")).status_code == 422
    bad_kind = await client.get("/api/v1/reports/daily-forms.pdf", headers=staff, params={"date": "2026-07-28", "kind": "x"})
    assert bad_kind.status_code == 422
    # Default date (current business date) works and an empty day still renders.
    assert (await client.get("/api/v1/reports/daily-summary.xlsx", headers=staff)).status_code == 200


# ------------------------------------------------------------------ forms


@pytest.mark.asyncio
async def test_forms_html_columns_checks_and_labels(db_session, seeded_users):
    await _scenario(db_session, seeded_users)
    report = await svc.build_daily_report(db_session, D, 60)

    dispatch_html = forms.render_forms_html(report, "dispatch")
    for label in (
        "แบบบันทึกการเบิก-จ่าย Equipment Pool",
        "วันที่ 28/Jul/2026",
        "ME.Code",
        "Primary Check",
        "ตัวเครื่อง (หน้าจอไม่แตกร้าว)",
        "สายชาร์จ (สายไม่ขาด)",
        "Pole Clamp (ไม่แตกหัก,ไม่งอ)",
        "ผู้รับเครื่อง ( User )",
        "Ward",
        "ผู้ส่งเครื่อง ( BME )",
        "เวลา",
        "หมายเหตุ",
    ):
        assert label in dispatch_html, label
    assert "ผู้ส่งเครื่อง ( User )" not in dispatch_html
    assert "BCM-001" in dispatch_html  # ME.Code column shows the BCM code
    assert "Nurse Som" in dispatch_html  # ward_contact_name
    assert dispatch_html.count("chk-ok") >= 3 and dispatch_html.count("chk-bad") >= 2
    # Charger unchecked on the second standard dispatch -> exactly one standard cross there;
    # cryo-cuff maps body/charger/lid_with_charger: charger bad -> a second cross; its lid_without is ignored.
    assert dispatch_html.count("chk-bad") == 2

    receipt_html = forms.render_forms_html(report, "receipt")
    assert "ผู้ส่งเครื่อง ( User )" in receipt_html and "ผู้รับเครื่อง ( User )" not in receipt_html
    assert "Nurse Malee" in receipt_html


@pytest.mark.asyncio
async def test_null_checks_print_blank(db_session, seeded_users):
    w = await _world(db_session, seeded_users)
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 10), op_d=w.bme_a, bcm="BCM-NULL")
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    html_doc = forms.render_forms_html(report, "dispatch")
    assert "BCM-NULL" in html_doc
    assert "chk-ok" not in html_doc.split("<tbody>", 1)[1] and "chk-bad" not in html_doc.split("<tbody>", 1)[1]


@pytest.mark.asyncio
async def test_forms_pdf_renders_paginated_with_thai_font(client, seeded_users, db_session):
    w = await _world(db_session, seeded_users)
    for i in range(30):  # 30 dispatches -> 2 pages of 25 rows; 1 receipt -> 1 page
        await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 9, i), op_d=w.bme_a, checks_d=STD_OK,
                  received=at(28, 15) if i == 0 else None, op_r=w.bme_a if i == 0 else None)
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    assert [e.form_position for e in report.events if e.kind == "dispatch"][25] == "หน้า 2 แถว 1"

    html_doc = forms.render_forms_html(report, "both")
    assert html_doc.count("<section class='page'>") == 3
    document = weasyprint.HTML(string=html_doc).render()
    assert len(document.pages) == 3  # fixed rows keep each form page to one A4 page

    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    for kind, pages in (("dispatch", 2), ("receipt", 1), ("both", 3)):
        resp = await client.get("/api/v1/reports/daily-forms.pdf", headers=staff, params={"date": "2026-07-28", "kind": kind})
        assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")
        assert len(weasyprint.HTML(string=forms.render_forms_html(report, kind)).render().pages) == pages
        assert len(resp.content) > 5000  # real rendered document (Thai font embedded), not an empty shell

    # Default kind is both; an empty day still produces one blank form page per kind.
    empty = await client.get("/api/v1/reports/daily-forms.pdf", headers=staff, params={"date": "2020-01-01"})
    assert empty.status_code == 200 and empty.content.startswith(b"%PDF")
    blank = await svc.build_daily_report(db_session, date(2020, 1, 1), 60)
    assert len(weasyprint.HTML(string=forms.render_forms_html(blank, "both")).render().pages) == 2


@pytest.mark.asyncio
async def test_empty_day_workbook(client, seeded_users, db_session):
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await _get_xlsx(client, staff, date="2020-01-01")
    wb = load_workbook(io.BytesIO(resp.content))
    assert _rows(wb["รายงาน"])[-1][:1] == ["รวม"]
    assert len(_rows(wb["รายการ"])) == 1
