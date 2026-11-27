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


def _ward_table(ws):
    """label (col C) -> [night disp, night rcpt, day disp, day rcpt, total disp, total rcpt]
    for the ward table (rows 5 .. the "รวม" row)."""
    out, total = {}, None
    for r in range(5, ws.max_row + 1):
        label = ws.cell(r, 3).value
        vals = [ws.cell(r, c).value for c in (4, 5, 6, 7, 9, 10)]
        if label == "รวม":
            total = vals
            break
        out[label] = vals
    return out, total


@pytest.mark.asyncio
async def test_workbook_sheets_headers_and_counts(client, seeded_users, db_session):
    await _scenario(db_session, seeded_users)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await _get_xlsx(client, staff, date="2026-07-28")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["รายงาน", "ชนิดเครื่อง", "ผู้คีย์", "รายการ"]

    # Sheet 1 layout (Owner's file): title, 2-row header, merged groups, panes, widths.
    ws = wb["รายงาน"]
    window = "(กะดึก 27/07 20:00 - กะเช้า 28/07 20:00)"
    assert ws["A1"].value == f"รายงานรับ-ส่งเครื่อง Infusion Pump  รวม 2 กะ วันที่ 28/Jul/2026  {window}"
    assert ws["A3"].value == "รูปแบบการจ่าย\nเครื่อง" and ws["B3"].value == "ประเภท\nการรักษา" and ws["C3"].value == "แผนก"
    assert ws["D3"].value == "รอบเวรกลางคืนที่ผ่านมา\nเวลา 27/07 20:00 - 28/07 08:00"
    assert ws["F3"].value == "รอบเวร Day สรุป\nเวลา 28/07 08:00 - 28/07 20:00"
    assert ws["H3"].value == "Stand By" and ws["I3"].value == "Total per DAY"
    assert [ws.cell(4, c).value for c in (4, 5, 6, 7, 9, 10)] == ["ส่ง", "รับ", "ส่ง", "รับ", "ส่งเครื่อง", "รับคืน"]
    merged = {str(m) for m in ws.merged_cells.ranges}
    assert {"A3:A4", "B3:B4", "C3:C4", "D3:E3", "F3:G3", "H3:H4", "I3:J3", "A5:A21", "B5:B11", "B12:B16",
            "B17:B21", "A22:A41", "B22:B41"} <= merged
    assert ws["A5"].value == "Standby support" and ws["B5"].value == "IPD ตึก A" and ws["A22"].value == "After request"
    assert ws.freeze_panes == "D5" and ws.row_dimensions[3].height == 36
    assert [ws.column_dimensions[c].width for c in "ABCDEFGHIJ"] == [15, 14, 24, 8, 8, 8, 8, 8, 11, 11]
    assert ws["H5"].fill.start_color.rgb.endswith("FFFF00") and ws["D6"].fill.start_color.rgb.endswith("DDD9C4")
    assert ws["D5"].border.left.style == "thin"

    # Ward table counts Infusion Pump only; zero cells are blank; unknown labels -> "อื่น ๆ" block.
    body, total = _ward_table(ws)
    assert body["Ward 5"] == [2, 1, None, 1, 2, 2]
    assert body["W5B"] == [1, None, None, None, 1, None]
    assert body["Ward 6"] == [None, None, 1, None, 1, None]  # the Cryo-Cuff dispatch is not in this table
    assert body[svc.UNSPECIFIED_LABEL] == [None, None, 1, None, 1, None]
    assert total == [3, 1, 2, 1, 5, 2]
    assert any(ws.cell(r, 1).value == "อื่น ๆ" for r in range(5, ws.max_row))
    total_row = next(r for r in range(5, ws.max_row) if ws.cell(r, 3).value == "รวม")
    assert ws.cell(total_row, 8).value == f"=SUM(H5:H{total_row - 1})"

    # Pool table: every equipment type, per shift, with turnover = dispatch + receipt.
    start = next(r for r in range(1, ws.max_row) if ws.cell(r, 1).value == "ลำดับ")
    assert ws.cell(start - 2, 1).value.startswith("สรุปจำนวนการใช้งานเครื่องมือกลุ่ม Pool")
    assert ws.cell(start, 2).value == "ชนิดเครื่องมือ Equipment Pool" and ws.cell(start, 10).value == "อัตราการหมุนเวียน\nรวมต่อชนิดเครื่อง"
    assert [ws.cell(start + 1, c).value for c in range(4, 10)] == ["จ่าย", "รับคืน"] * 3
    pool = {ws.cell(r, 2).value: [ws.cell(r, c).value for c in range(4, 11)] for r in range(start + 2, start + 9)}
    assert list(pool)[0] == "INFUSION PUMP" and "CRYO CUFF (ทั้งหมดมีในระบบ 1 รายการ)" in pool
    assert pool["INFUSION PUMP"] == [3, 1, 2, 1, 5, 2, 7]
    assert pool["CRYO CUFF (ทั้งหมดมีในระบบ 1 รายการ)"] == [1, None, None, None, 1, None, 1]
    assert [ws.cell(start + 10, c).value for c in range(4, 11)] == [4, 1, 2, 1, 6, 2, 8]
    footer = [ws.cell(r, 1).value for r in range(start + 11, ws.max_row + 1) if ws.cell(r, 1).value]
    assert footer[0].startswith("ช่วงเปลี่ยนกะ ±60 นาที") and footer[1] == "ตารางแผนกนับเฉพาะ Infusion Pump"

    # Sheet 2: equipment type (fixed types in the Owner's order, then per-ward x type).
    cs = wb["ชนิดเครื่อง"]
    assert cs["A1"].value == f"แยกตามชนิดเครื่อง  รวม 2 กะ วันที่ 28/Jul/2026  {window}"
    assert cs["A3"].value == "ชนิดเครื่อง" and cs["H3"].value == "รวม" and cs.freeze_panes == "B5"
    assert {"A3:A4", "B3:C3", "D3:E3", "F3:G3", "H3:H4"} <= {str(m) for m in cs.merged_cells.ranges}
    names = [cs.cell(r, 1).value for r in range(5, 13)]
    assert names == ["Infusion Pump", "PCA", "Syringe Pump", "Air Mattress", "Cryo cuff", "Bed Alarm", "Pneumatic Pump", "Respirator"]
    assert [cs.cell(5, c).value for c in range(2, 9)] == [3, 1, 2, 1, 5, 2, 7]
    assert [cs.cell(9, c).value for c in range(2, 9)] == [1, None, None, None, 1, None, 1]
    assert [cs.cell(13, c).value for c in range(1, 9)] == ["รวม", 4, 1, 2, 1, 6, 2, 8]
    assert cs["A15"].value == "แยกตามแผนก x ชนิดเครื่อง (รวม 2 กะ)" and cs.row_dimensions[16].height == 30
    assert cs["A16"].value == "แผนก" and cs["B16"].value == "Infusion Pump" and cs["D16"].value == "Cryo cuff"
    assert cs.cell(16, 6).value == "รวม"
    assert cs["B13"].fill.start_color.rgb.endswith("FFFF00")

    # Sheet 3: operators.
    op = _rows(wb["ผู้คีย์"])
    assert op[0][0] == f"รวม 2 กะ วันที่ 28/Jul/2026  {window}"
    assert op[1] == ["ผู้คีย์ (BME)", "กะดึก ส่ง", "กะดึก รับ", "กะเช้า ส่ง", "กะเช้า รับ", "รวม ส่ง", "รวม รับ", "รวมทั้งหมด"]
    by_op = {r[0]: r for r in op[2:-1]}
    assert by_op["BME Alpha"][1:] == [4, 1, 0, 0, 4, 1, 5]
    assert by_op["BME Beta"][1:] == [0, 0, 2, 1, 2, 1, 3]
    assert op[-1] == ["รวม", 4, 1, 2, 1, 6, 2, 8]
    assert wb["ผู้คีย์"].column_dimensions["A"].width == 20

    # Sheet 4: every event, verbatim headers, widths, "ตำแหน่งในฟอร์ม" wording.
    es = wb["รายการ"]
    ev = _rows(es)
    assert ev[0] == ["กะ", "วันที่", "เวลา", "งาน", "ID CODE", "ชนิดเครื่อง", "Ward (ในฟอร์ม)", "แถวในรายงาน",
                     "ผู้คีย์ (BME)", "หมายเหตุ", "ตำแหน่งในฟอร์ม"]
    assert [es.column_dimensions[c].width for c in "ABCDEFGHIJK"] == [8, 12, 10, 6, 12, 16, 26, 18, 16, 14, 20]
    assert es.freeze_panes == "A2" and es.auto_filter.ref in (None, "")
    assert len(ev) - 1 == 8
    first = ev[1]
    assert first[0] == "กะดึก" and first[1] == "27/Jul/2026" and first[2] == "21:00:00" and first[3] == "ส่ง"
    assert first[4].startswith("BCM-") and first[6] == "Ward 5A" and first[7] == "Ward 5" and first[8] == "BME Alpha"
    assert first[10] == "แบบบันทึกส่งเครื่องเมื่อวาน แถว 1"
    after_midnight = next(r for r in ev[1:] if r[2] == "01:30:00")
    assert after_midnight[10] == "แบบบันทึกส่งเครื่อง แถว 1"
    receipt_0820 = next(r for r in ev[1:] if r[2] == "08:20:00")
    assert receipt_0820[0] == "กะดึก" and receipt_0820[3] == "รับ" and receipt_0820[9] == "ok"
    assert receipt_0820[10] == "แบบบันทึกรับเครื่อง แถว 1"


@pytest.mark.asyncio
async def test_strict_grace_changes_attribution(client, seeded_users, db_session):
    await _scenario(db_session, seeded_users)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await _get_xlsx(client, staff, date="2026-07-28", grace_minutes=0)
    wb = load_workbook(io.BytesIO(resp.content))
    ev = _rows(wb["รายการ"])
    receipt_0820 = next(r for r in ev[1:] if r[2] == "08:20:00")
    assert receipt_0820[0] == "กะเช้า"
    body, _ = _ward_table(wb["รายงาน"])
    assert body["Ward 5"][0:4] == [2, None, None, 2]


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
    ws = wb["รายงาน"]
    body, _ = _ward_table(ws)
    assert "Ward 5A" not in body  # slot label shown; 5B has its own slot W5B
    assert body["Ward 5"] == [2, 1, None, 1, 2, 2] and body["W5B"] == [1, None, None, None, 1, None]
    assert body["Ward 6"] == [None, None, 1, None, 1, None]  # Ward 6's own row (unmapped ward name matches the layout)
    assert ws["A5"].value == "Standby support" and [ws["C5"].value, ws["C6"].value] == ["Ward 5", "Ward 6"]
    assert body[svc.UNSPECIFIED_LABEL] == [None, None, 1, None, 1, None]  # unmapped -> "อื่น ๆ" block
    ev = _rows(wb["รายการ"])
    assert {r[7] for r in ev[1:] if r[6] in ("Ward 5A", "Ward 5B")} == {"Ward 5", "W5B"}

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
                if isinstance(cell.value, str) and not re.fullmatch(r"=SUM\(H5:H\d+\)", cell.value):  # the one generated formula
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

    dispatch_html = forms.render_forms_html(report, "dispatch", "night")
    for label in (
        "แบบบันทึกการเบิก-จ่าย Equipment Pool",
        "วันที่ 27/Jul/2026",
        "วันที่ 28/Jul/2026",  # the Night form is split by calendar date
        "ME.Code",
        "Primary Check",
        "ตัวเครื่อง",
        "(หน้าจอไม่แตกร้าว)",
        "(สายไม่ขาด)",
        "(ไม่แตกหัก,ไม่งอ)",
        "Pole Clamp",
        "ผู้รับเครื่อง",
        "( User )",
        "( BME )",
        "Ward",
        "ผู้ส่งเครื่อง",
        "เวลา",
        "หมายเหตุ",
        "FI-CES-BCM-PO-001/1 แก้ไขครั้งที่ 04",
        "วันที่บังคับใช้ 25/06/2569",
        "data:image/jpeg;base64,",  # form logo
    ):
        assert label in dispatch_html, label
    # Dispatch form: User = ผู้รับเครื่อง, BME = ผู้ส่งเครื่อง (in that column order).
    assert dispatch_html.index("ผู้รับเครื่อง") < dispatch_html.index("ผู้ส่งเครื่อง")
    assert "BCM-001" in dispatch_html  # ME.Code column shows the BCM code
    assert "Nurse Som" in dispatch_html  # ward contact name in the User column
    assert "21:00:00" in dispatch_html  # time prints seconds
    assert "BME Alpha" in dispatch_html
    assert dispatch_html.count("chk-ok") >= 3 and dispatch_html.count("chk-bad") >= 2
    assert dispatch_html.count("chk-bad") == 2
    # blank rows pad every page to 33 data rows
    assert dispatch_html.count("<tr><td><div class='c code'>") + dispatch_html.count("<tr><td><div class='c'></div></td>") == 33 * 2

    receipt_html = forms.render_forms_html(report, "receipt", "night")
    assert receipt_html.index("ผู้ส่งเครื่อง") < receipt_html.index("ผู้รับเครื่อง")  # swapped for the receipt form
    assert "Nurse Malee" in receipt_html and "รับเครื่อง" in receipt_html

    day_html = forms.render_forms_html(report, "dispatch", "day")
    assert "BME Beta" in day_html and "BME Alpha" not in day_html  # Day form = Day shift rows only
    assert day_html.count("<section class='page'>") == 1 and "วันที่ 27/Jul/2026" not in day_html
    assert svc.FORM_ROWS_PER_PAGE == 33


@pytest.mark.asyncio
async def test_form_notes_label_non_infusion_equipment(db_session, seeded_users):
    w = await _world(db_session, seeded_users)
    bed = EquipmentCategory(name="ALARMS, OCCUPANCY, BED")
    db_session.add(bed)
    await db_session.flush()
    await _tx(db_session, w, ward=w.w6, category=bed, dispatched=at(28, 10), op_d=w.bme_a)
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    assert "Bed Alarms" in forms.render_forms_html(report, "dispatch", "day")


@pytest.mark.asyncio
async def test_null_checks_print_ticks_and_only_false_prints_cross(db_session, seeded_users):
    """Legacy-sheet rows carry no checks (NULL); the Owner's tool prints a tick for them and
    D4's default is checked, so only an explicit false prints a cross."""
    w = await _world(db_session, seeded_users)
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 10), op_d=w.bme_a, bcm="BCM-NULL")
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 11), op_d=w.bme_a, bcm="BCM-BAD",
              checks_d={"kind": "standard", "screen_ok": True, "charger_ok": False, "clamp_ok": True})
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    body = forms.render_forms_html(report, "dispatch", "day").split("<tbody>", 1)[1]
    assert "BCM-NULL" in body
    assert body.count("chk-ok") == 3 + 2 and body.count("chk-bad") == 1


def test_check_cell_glyphs():
    assert "chk-ok" in forms._check_cell(None) and "chk-ok" in forms._check_cell(True)
    assert "chk-bad" in forms._check_cell(False)
    assert "#22cc22" in forms._TICK and "#e02020" in forms._CROSS  # legacy green / red


@pytest.mark.asyncio
async def test_system_notes_never_printed_but_operator_notes_are(db_session, seeded_users):
    w = await _world(db_session, seeded_users)
    sync_note = "legacy sheet dispatch row be737745; Borrow1000000009210; BME Somchai"
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 10), op_d=w.bme_a, bcm="BCM-SYNC", notes=sync_note)
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 11), op_d=w.bme_a, bcm="BCM-OPER", notes="ฝาครอบร้าว")
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    html_doc = forms.render_forms_html(report, "dispatch", "day")
    assert "legacy sheet" not in html_doc and "be737745" not in html_doc and "Borrow1000" not in html_doc
    assert "ฝาครอบร้าว" in html_doc
    wb = load_workbook(io.BytesIO(xlsx.build_daily_workbook_sync(report)))
    cells = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None]
    assert not any("legacy sheet" in c or "be737745" in c for c in cells)
    assert any("ฝาครอบร้าว" in c for c in cells)


@pytest.mark.asyncio
async def test_keyer_label_replaces_user_name_in_bme_column(db_session, seeded_users):
    w = await _world(db_session, seeded_users)
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 10), op_d=w.bme_a, bcm="BCM-LBL")
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 11), op_d=w.bme_a, bcm="BCM-NOLBL")
    from sqlalchemy import update
    await db_session.execute(
        update(BorrowTransaction).where(BorrowTransaction.transaction_no == "T-1").values(dispatch_keyer_label="LabelOnly")
    )
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    by_code = {e.bcm_code: e for e in report.events}
    assert by_code["BCM-LBL"].operator_name == "LabelOnly"
    assert by_code["BCM-NOLBL"].operator_name != "LabelOnly" and by_code["BCM-NOLBL"].operator_id is not None
    assert by_code["BCM-LBL"].operator_id == by_code["BCM-NOLBL"].operator_id  # actor unchanged
    assert "LabelOnly" in forms.render_forms_html(report, "dispatch", "day")


def test_form_font_is_bundled_ofl_serif_and_fits_only_when_overflowing():
    css = forms._font_css()
    assert "Trirong Form" in css and css.count("@font-face") == 2
    fonts = forms._FONTS_DIR
    assert (fonts / "Trirong-Regular.ttf").exists() and (fonts / "Trirong-Bold.ttf").exists()
    assert "SIL Open Font License" in (fonts / "OFL-Trirong.txt").read_text()
    # Legacy sizes (Angsana 14/15/18) scaled by one factor; data text keeps full size when it fits.
    assert forms.FS_DATA == round(14 * forms.FONT_SCALE, 1) and forms.FS_TITLE > forms.FS_HEAD > forms.FS_DATA
    assert forms._fit("ICU3", 49.5) == ""
    shrunk = forms._fit("Emergency/Trauma Center", 49.5)
    assert shrunk and float(re.search(r"font-size:([\d.]+)pt", shrunk).group(1)) >= forms.FS_MIN
    html_doc = forms.render_forms_html(svc.DailyReport(D, 60, [], [], [], [], svc.Counts()), "dispatch", "day")
    assert 'font-family: "Trirong Form", serif' in html_doc and "font-size: %spt" % forms.FS_DATA in html_doc


@pytest.mark.asyncio
async def test_forms_pdf_renders_paginated_with_thai_font(client, seeded_users, db_session):
    w = await _world(db_session, seeded_users)
    for i in range(40):  # 40 Day dispatches -> 2 pages of 33 rows; 1 receipt -> 1 page
        await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 9, i), op_d=w.bme_a, checks_d=STD_OK,
                  received=at(28, 15) if i == 0 else None, op_r=w.bme_a if i == 0 else None)
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    assert [e.form_position for e in report.events if e.kind == "dispatch"][33] == "แบบบันทึกส่งเครื่อง หน้า 2 แถว 1"

    html_doc = forms.render_forms_html(report, "both", "day")
    assert html_doc.count("<section class='page'>") == 3  # + 1 verify-checklist page (D17) for the one receipt
    document = weasyprint.HTML(string=html_doc).render()
    assert len(document.pages) == 4  # fixed rows keep each form page to one A4 page
    assert abs(float(document.pages[0].width) - 794) < 2  # A4 portrait (CSS px)

    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    # Day: dispatch 2 pages + receipt 1; Night forms are always one page per calendar date.
    for kind, shift, pages in (("dispatch", "day", 2), ("receipt", "day", 2), ("both", "day", 4),
                               ("dispatch", "night", 2), ("both", "night", 4), ("both", "both", 8)):
        resp = await client.get("/api/v1/reports/daily-forms.pdf", headers=staff,
                                params={"date": "2026-07-28", "kind": kind, "shift": shift})
        assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")
        assert len(weasyprint.HTML(string=forms.render_forms_html(report, kind, shift)).render().pages) == pages
        assert len(resp.content) > 5000  # real rendered document (Thai font embedded), not an empty shell

    # Default kind/shift is both/both; an empty day still produces blank forms.
    empty = await client.get("/api/v1/reports/daily-forms.pdf", headers=staff, params={"date": "2020-01-01"})
    assert empty.status_code == 200 and empty.content.startswith(b"%PDF")
    blank = await svc.build_daily_report(db_session, date(2020, 1, 1), 60)
    assert len(weasyprint.HTML(string=forms.render_forms_html(blank, "both", "day")).render().pages) == 2
    assert len(weasyprint.HTML(string=forms.render_forms_html(blank, "both", "both")).render().pages) == 6
    bad = await client.get("/api/v1/reports/daily-forms.pdf", headers=staff, params={"date": "2026-07-28", "shift": "x"})
    assert bad.status_code == 422


def test_summary_sheet_styling_matches_legacy_workbook():
    """Cell styling of the Owner's legacy workbook, on synthetic wards (layout slots, not names)."""
    rows = [
        svc.WardRow("Ward 5", "Standby support", "IPD ตึก A", "92D050"),
        svc.WardRow("Ward 6", "Standby support", "IPD ตึก A", "92D050", None, True),
        svc.WardRow("Ward 6 B", "Standby support", "IPD ตึก A", "92D050", None, True),
        svc.WardRow("Clinic", "After request", "OPD", "F8CBAD"),
    ]
    report = svc.DailyReport(D, 60, [], rows, [], [], svc.Counts())
    ws = load_workbook(io.BytesIO(xlsx.build_daily_workbook_sync(report)))["รายงาน"]
    # Title spans A1:J1 (bold 13); ward names are default (left) aligned, not centred.
    assert "A1:J1" in {str(m) for m in ws.merged_cells.ranges}
    assert ws["A1"].font.b and ws["A1"].font.sz == 13
    for r in (5, 6, 7, 8):
        assert ws.cell(r, 3).alignment.horizontal in (None, "general", "left")
    # Grey (DDD9C4) follows the layout slot: the ward-name cell AND the count cells.
    for r, grey in ((5, False), (6, True), (7, True), (8, False)):
        for c in (3, 4, 5, 6, 7, 8, 9, 10):
            fill = ws.cell(r, c).fill
            assert (fill.fill_type == "solid" and fill.start_color.rgb.endswith("DDD9C4")) == grey, (r, c)
    # Group labels are bold on their colour; mode labels red / purple like the legacy file.
    assert ws["B5"].font.b and ws["B5"].fill.start_color.rgb.endswith("92D050")
    assert ws["A5"].font.color.rgb.endswith("FF0000") and ws["A8"].font.color.rgb.endswith("7030A0")
    assert ws["B8"].font.b and ws["B8"].fill.start_color.rgb.endswith("F8CBAD")
    assert ws.freeze_panes == "D5" and ws.row_dimensions[3].height == 36
    assert [ws.column_dimensions[c].width for c in "ABCDEFGHIJ"] == [15, 14, 24, 8, 8, 8, 8, 8, 11, 11]
    assert ws.sheet_properties.pageSetUpPr.fitToPage and ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 0
    # Turnover column of the pool table is bold on its blue fill.
    start = next(r for r in range(1, ws.max_row) if ws.cell(r, 1).value == "ลำดับ")
    assert ws.cell(start + 2, 10).font.b and ws.cell(start + 2, 10).fill.start_color.rgb.endswith("DDEBF7")


@pytest.mark.asyncio
async def test_empty_day_workbook(client, seeded_users, db_session):
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    resp = await _get_xlsx(client, staff, date="2020-01-01")
    wb = load_workbook(io.BytesIO(resp.content))
    assert _ward_table(wb["รายงาน"])[1] == [0, 0, 0, 0, 0, 0]
    assert len(_rows(wb["รายการ"])) == 1


@pytest.mark.asyncio
async def test_form_positions_count_per_shift_form_and_page(db_session, seeded_users):
    w = await _world(db_session, seeded_users)
    # Night 01:30 dispatch (Night form dated 28) must not take row 1 of the Day form.
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 1, 30), op_d=w.bme_a)
    for i in range(34):
        await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 9, i), op_d=w.bme_b)
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    disp = [e for e in report.events if e.kind == "dispatch"]
    assert disp[0].shift == Shift.NIGHT and disp[0].form_position == "แบบบันทึกส่งเครื่อง แถว 1"
    day = [e for e in disp if e.shift == Shift.DAY]
    assert day[0].form_position == "แบบบันทึกส่งเครื่อง หน้า 1 แถว 1"
    assert day[32].form_position.endswith("หน้า 1 แถว 33") and day[33].form_position.endswith("หน้า 2 แถว 1")


@pytest.mark.asyncio
async def test_each_ward_is_its_own_row_in_layout_order(db_session, seeded_users):
    w = await _world(db_session, seeded_users)
    w7a = Ward(code="W7A", name="Ward 7A", department_id=w.dept_a.id)
    w7b = Ward(code="W7B", name="Ward 7B", department_id=w.dept_a.id)
    odd = Ward(code="LAB", name="Lab Annex", department_id=w.dept_b.id)
    db_session.add_all([w7a, w7b, odd])
    await db_session.flush()
    await _tx(db_session, w, ward=w7a, category=w.pump, dispatched=at(28, 9), op_d=w.bme_a)
    await _tx(db_session, w, ward=w7b, category=w.pump, dispatched=at(28, 10), op_d=w.bme_a)
    await _tx(db_session, w, ward=odd, category=w.pump, dispatched=at(28, 11), op_d=w.bme_a)
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    labels = [r.label for r in report.ward_rows]
    assert "Ward 7A" not in labels  # single ward in the slot shows the slot label
    assert labels.index("Ward 6") < labels.index("Ward 7") < labels.index("Ward 8")
    rows = {r.label: r for r in report.ward_rows}
    assert rows["Ward 7"].mode == "Standby support" and rows["Ward 7"].treatment == "IPD ตึก A"
    assert rows["Lab Annex"].mode == "อื่น ๆ"
    assert rows["Ward 7B"].mode == "อื่น ๆ"  # building-B ward without a W7B slot is not building A
    counted = {e.row_label for e in report.events}
    assert {"Ward 7", "Ward 7B", "Lab Annex"} <= counted  # lossless: every event has its own row


@pytest.mark.asyncio
async def test_verify_checklist_pages_blank_checks_one_row_per_receipt(db_session, seeded_users):
    w = await _world(db_session, seeded_users)
    bed = EquipmentCategory(name="ALARMS, OCCUPANCY, BED")
    db_session.add(bed)
    await db_session.flush()
    for i in range(60):  # 60 Day receipts -> 58 rows/page -> 2 checklist pages
        await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(27, 9), received=at(28, 9, i % 50),
                  op_d=w.bme_a, op_r=w.bme_a, checks_r=STD_OK, notes="free text", bcm=f"SYN-{i:03d}")
    await _tx(db_session, w, ward=w.w6, category=bed, dispatched=at(27, 9), received=at(28, 12), op_r=w.bme_a, bcm="SYN-BED")
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    html_doc = forms.render_forms_html(report, "both", "day")
    assert forms.checklist_rows_per_page() == 58
    checks = html_doc.split("<section class='page check'>")[1:]
    assert len(checks) == 2
    first = checks[0]
    for text in ("Equipment Verify Checklist", "Performance Check", "Cleaner", "Function Test", "Run Test",
                 "Battery Check", "Pass", "Fail", "Remark", "FI-CES-BCM-PO-001/2 แก้ไขครั้งที่ 04", "28/Jul/2026"):
        assert text in first, text
    assert first.count("SYN-") == 58 and checks[1].count("SYN-") == 3  # 61 receipts, one row each
    assert "Bed Alarms" in checks[1] or "Bed Alarms" in first
    # D23: usable rows are pre-ticked (5 ticks: Cleaner..Battery + Pass), never a cross;
    # no free text / HN-like data is printed.
    assert first.count("chk-ok") == 58 * 5 and "chk-bad" not in first and "free text" not in first
    # Dispatch-only output has no checklist; the receipt-bearing outputs do.
    assert "page check" not in forms.render_forms_html(report, "dispatch", "day")
    pages = len(weasyprint.HTML(string=html_doc).render().pages)
    assert pages == 1 + 2 + 2  # blank dispatch form + receipt form (33+28 rows) + 2 checklist pages


@pytest.mark.asyncio
async def test_verify_checklist_defective_receipt_ticks_fail_not_pass(db_session, seeded_users):
    """D23: a defective receipt prints a tick in Fail and leaves Pass blank (synthetic data)."""
    w = await _world(db_session, seeded_users)
    await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(27, 9), received=at(28, 9), op_r=w.bme_a, bcm="SYN-OK")
    bad = await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(27, 9), received=at(28, 10), op_r=w.bme_a, bcm="SYN-BAD")
    bad.condition_on_return = "defective"
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    page = forms.render_forms_html(report, "both", "day").split("<section class='page check'>")[1]
    rows = {c: r for c in ("SYN-OK", "SYN-BAD") for r in page.split("<tr>") if c in r}
    # cells after the code cell: Cleaner, Function, Run, Battery, Pass, Fail
    cells = lambda r: r.split("</div></td>", 2)[2].split("<td><div class='c'><span")[0].split("<td>")[1:]  # noqa: E731
    assert ["chk-ok" in c for c in cells(rows["SYN-OK"])] == [True] * 5 + [False]
    assert ["chk-ok" in c for c in cells(rows["SYN-BAD"])] == [True] * 4 + [False, True]
    assert "chk-bad" not in page


@pytest.mark.asyncio
async def test_receipt_form_never_prints_system_note_labels(db_session, seeded_users):
    """Receipt BME column: keyer label, else receiving user's name; system-note text is never printed."""
    from sqlalchemy import select
    from sqlalchemy import update
    w = await _world(db_session, seeded_users)
    junk = "legacy sheet receipt row 0a1b2c3d; Return1; BME Somchai"
    for code in ("BCM-GOOD", "BCM-JUNK", "BCM-NONE"):
        await _tx(db_session, w, ward=w.w6, category=w.pump, dispatched=at(28, 9), received=at(28, 10),
                  op_d=w.bme_a, op_r=w.bme_b, contact_r="WardPerson", bcm=code)
    await db_session.commit()
    for code, label in (("BCM-GOOD", "Somchai"), ("BCM-JUNK", junk)):
        eq_id = (await db_session.execute(select(Equipment.id).where(Equipment.bcm_code == code))).scalar_one()
        await db_session.execute(
            update(BorrowTransaction).where(BorrowTransaction.equipment_id == eq_id).values(receipt_keyer_label=label))
    await db_session.commit()
    report = await svc.build_daily_report(db_session, D, 60)
    by = {e.bcm_code: e for e in report.events if e.kind == "receipt"}
    assert by["BCM-GOOD"].operator_name == "Somchai"
    assert by["BCM-JUNK"].operator_name == "BME Beta" and by["BCM-NONE"].operator_name == "BME Beta"
    assert by["BCM-GOOD"].contact_name == "WardPerson"
    html_doc = forms.render_forms_html(report, "receipt", "day")
    assert "legacy sheet" not in html_doc and "Somchai" in html_doc and "WardPerson" in html_doc
    by["BCM-GOOD"].operator_name = junk  # print-time guard even if an upstream layer leaks
    assert "legacy sheet" not in forms.render_forms_html(report, "receipt", "day")
