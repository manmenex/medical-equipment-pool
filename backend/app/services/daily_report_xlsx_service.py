"""Roadmap PR30 (D5): the daily summary workbook, laid out exactly like the
pool team's own report (Owner request 2026-11-26).

Four sheets: "รายงาน" (Infusion Pump by department/ward group, then the
"สรุปจำนวนการใช้งานเครื่องมือกลุ่ม Pool" table), "ชนิดเครื่อง", "ผู้คีย์" and
"รายการ". Every string goes through the PR18E centralized formula-injection
guard (`report_xlsx_service._write_cell`), and generation runs through the
PR18 admission control (`report_xlsx_service.run_bounded`). No HN or any
patient field exists in the input, so none can be emitted.
"""

import io
from datetime import datetime, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.core.reporting_time import Shift
from app.services import report_xlsx_service
from app.services.daily_report_service import (
    ROLE_CRYO,
    ROLE_INFUSION,
    ROLE_ORDER,
    ROLE_SHORT_NAMES,
    OTHER_COLOR,
    WardRow,
    Counts,
    DailyReport,
    _THAI_SHIFT,
    category_role,
    format_date,
)
from app.services.equipment_badge import with_badge
from app.services.report_xlsx_service import _write_cell

SHEET_SUMMARY = "รายงาน"
SHEET_CATEGORY = "ชนิดเครื่อง"
SHEET_OPERATOR = "ผู้คีย์"
SHEET_EVENTS = "รายการ"

OTHER_LABEL = "อื่น ๆ"

# "สรุปจำนวนการใช้งานเครื่องมือกลุ่ม Pool" rows (role -> label on the form).
POOL_LABELS = [
    ("infusion", "INFUSION PUMP"),
    ("pca", "PCA"),
    ("syringe", "INFUSION PUMP, SYRINGE"),
    ("mattress", "MATTRESS SYSTEM,ALTERNATING-PRESSURE"),
    ("cryo", "CRYO CUFF"),
    ("bed", "BED EXIT ALRM"),
    ("pneumatic", "PNEUMATIC PUMP"),
]

# Header text (verbatim from the Owner's file).
SUMMARY_TITLE = "รายงานรับ-ส่งเครื่อง Infusion Pump  รวม 2 กะ วันที่ {d}  ({w})"
CATEGORY_TITLE = "แยกตามชนิดเครื่อง  รวม 2 กะ วันที่ {d}  ({w})"
OPERATOR_TITLE = "รวม 2 กะ วันที่ {d}  ({w})"
POOL_TITLE = "สรุปจำนวนการใช้งานเครื่องมือกลุ่ม Pool ประจำวันของทุกรายการที่เปิดใช้บริการมีดังนี้"
NIGHT_HEAD = "รอบเวรกลางคืนที่ผ่านมา\nเวลา {a} - {b}"
DAY_HEAD = "รอบเวร Day สรุป\nเวลา {a} - {b}"
OPERATOR_HEADERS = ["ผู้คีย์ (BME)", "กะดึก ส่ง", "กะดึก รับ", "กะเช้า ส่ง", "กะเช้า รับ", "รวม ส่ง", "รวม รับ", "รวมทั้งหมด"]
EVENT_HEADERS = [
    "กะ", "วันที่", "เวลา", "งาน", "ID CODE", "ชนิดเครื่อง", "Ward (ในฟอร์ม)", "แถวในรายงาน",
    "ผู้คีย์ (BME)", "หมายเหตุ", "ตำแหน่งในฟอร์ม",
]

_THIN = Side(style="thin")
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
_LEFT = Alignment(horizontal="left", vertical="center")
_BOLD = Font(bold=True)


def _fill(rgb: str) -> PatternFill:
    return PatternFill(fill_type="solid", start_color=rgb, end_color=rgb)


def _put(ws: Worksheet, row: int, col: int, value=None, *, bold=False, fill: str | None = None, align=_CENTER, box=True):
    """Write one table cell: None for blank, thin border, centred by default."""
    cell = _write_cell(ws, row=row, column=col, value=value, font=_BOLD if bold else None)
    if box:
        cell.border = _BOX
    cell.alignment = align
    if fill:
        cell.fill = _fill(fill)
    return cell


def _blank0(n: int) -> int | None:
    return n or None


def _windows(report: DailyReport) -> tuple[str, str, str, str]:
    """(title window, night header, day header...) texts for the report date."""
    d = report.report_date
    n0 = datetime(d.year, d.month, d.day, 20) - timedelta(days=1)
    n1 = datetime(d.year, d.month, d.day, 8)
    d1 = datetime(d.year, d.month, d.day, 20)

    def f(x: datetime) -> str:
        return f"{x.day:02d}/{x.month:02d} {x:%H:%M}"

    title = f"กะดึก {f(n0)} - กะเช้า {f(d1)}"
    return title, NIGHT_HEAD.format(a=f(n0), b=f(n1)), DAY_HEAD.format(a=f(n1), b=f(d1)), format_date(d)


def _title(ws: Worksheet, text: str, *, bold=True, size=13) -> None:
    _write_cell(ws, row=1, column=1, value=text, font=Font(bold=bold, size=size) if bold else None)


def _merge(ws: Worksheet, r1: int, c1: int, r2: int, c2: int) -> None:
    ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)


def _head(ws, row, col, text, *, rows=1, cols=1, fill=None) -> None:
    """Bold centred bordered header cell, merged over rows x cols."""
    for r in range(row, row + rows):
        for c in range(col, col + cols):
            _put(ws, r, c, text if (r, c) == (row, col) else None, bold=(r, c) == (row, col), fill=fill)
    if rows > 1 or cols > 1:
        _merge(ws, row, col, row + rows - 1, col + cols - 1)


def _widths(ws: Worksheet, widths: list[float]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _ward_blocks(
    report: DailyReport, standby: dict[str, int] | None = None
) -> list[tuple[str, list[tuple[str, str, list[WardRow]]]]]:
    """D18: the report's per-ward rows nested as mode -> treatment group -> rows.
    A Stand By label the report has no row for (stored edit, standby-only ward)
    is appended to the "อื่น ๆ" group so no number is lost."""
    rows = list(report.ward_rows)
    known = {r.label for r in rows}
    for label in sorted(set(standby or {}) - known):
        rows.append(WardRow(label, OTHER_LABEL, OTHER_LABEL, OTHER_COLOR))
    blocks: list[tuple[str, list[tuple[str, str, list[WardRow]]]]] = []
    for r in rows:
        if not blocks or blocks[-1][0] != r.mode:
            blocks.append((r.mode, []))
        groups = blocks[-1][1]
        if not groups or groups[-1][0] != r.treatment:
            groups.append((r.treatment, r.color, []))
        groups[-1][2].append(r)
    return blocks


def _role_counts(report: DailyReport, role: str | None) -> dict[str, Counts]:
    out: dict[str, Counts] = {}
    for e in report.events:
        if role is None or category_role(e.category_name) == role:
            out.setdefault(e.row_label, Counts()).add(e)
    return out


def _summary_sheet(ws: Worksheet, report: DailyReport, standby: dict[str, int] | None = None) -> None:
    ws.title = SHEET_SUMMARY
    standby = standby or {}
    window, night_head, day_head, date_text = _windows(report)
    _title(ws, SUMMARY_TITLE.format(d=date_text, w=window))
    ws.row_dimensions[3].height = 36
    _head(ws, 3, 1, "รูปแบบการจ่าย\nเครื่อง", rows=2)
    _head(ws, 3, 2, "ประเภท\nการรักษา", rows=2)
    _head(ws, 3, 3, "แผนก", rows=2)
    _head(ws, 3, 4, night_head, cols=2)
    _head(ws, 3, 6, day_head, cols=2)
    _head(ws, 3, 8, "Stand By", rows=2, fill="FFFF00")
    _head(ws, 3, 9, "Total per DAY", cols=2)
    for col, text in zip((4, 5, 6, 7, 9, 10), ("ส่ง", "รับ", "ส่ง", "รับ", "ส่งเครื่อง", "รับคืน")):
        _put(ws, 4, col, text)

    counts = _role_counts(report, ROLE_INFUSION)
    row = 5
    tot = Counts()
    for mode, groups in _ward_blocks(report, standby):
        mode_start = row
        for treatment, color, rows in groups:
            group_start = row
            for ward_row in rows:
                label = ward_row.label
                c = counts.get(label, Counts())
                for f in ("night_dispatch", "night_receipt", "day_dispatch", "day_receipt"):
                    setattr(tot, f, getattr(tot, f) + getattr(c, f))
                grey = ward_row.shaded
                _put(ws, row, 3, label, align=_CENTER)
                values = [c.night_dispatch, c.night_receipt, c.day_dispatch, c.day_receipt]
                for col, v in zip((4, 5, 6, 7), values):
                    _put(ws, row, col, _blank0(v), fill="DDD9C4" if grey else None)
                _put(ws, row, 8, standby.get(label) or None, fill="DDD9C4" if grey else "FFFF00")
                _put(ws, row, 9, _blank0(c.total_dispatch), fill="DDD9C4" if grey else None)
                _put(ws, row, 10, _blank0(c.total_receipt), fill="DDD9C4" if grey else None)
                row += 1
            for r in range(group_start, row):
                _put(ws, r, 2, treatment if r == group_start else None, fill=color if r == group_start else None)
            _merge(ws, group_start, 2, row - 1, 2)
        for r in range(mode_start, row):
            _put(ws, r, 1, mode if r == mode_start else None)
        ws.cell(mode_start, 1).font = Font(color="FF0000") if mode == "Standby support" else Font()
        _merge(ws, mode_start, 1, row - 1, 1)
    first_data, last_data = 5, row - 1
    _put(ws, row, 1)
    _put(ws, row, 2)
    _put(ws, row, 3, "รวม", bold=True)
    for col, v in zip((4, 5, 6, 7), (tot.night_dispatch, tot.night_receipt, tot.day_dispatch, tot.day_receipt)):
        _put(ws, row, col, v, bold=True, fill="FFFF00")
    # The one formula: a constant we build ourselves, so it bypasses the string guard.
    sum_cell = _put(ws, row, 8, None, bold=True, fill="FFFF00")
    sum_cell.value = f"=SUM(H{first_data}:H{last_data})"
    _put(ws, row, 9, tot.total_dispatch, bold=True, fill="FFFF00")
    _put(ws, row, 10, tot.total_receipt, bold=True, fill="FFFF00")
    row += 3

    # --- pool table: every equipment type
    _write_cell(ws, row=row, column=1, value=POOL_TITLE, font=Font(bold=True, size=12, color="FF0000"))
    row += 2
    ws.row_dimensions[row].height = 36
    _head(ws, row, 1, "ลำดับ", rows=2)
    _head(ws, row, 2, "ชนิดเครื่องมือ Equipment Pool", rows=2, cols=2)
    _head(ws, row, 4, night_head, cols=2, fill="DDEBF7")
    _head(ws, row, 6, day_head, cols=2, fill="FFFF00")
    _head(ws, row, 8, "Total per DAY", cols=2, fill="DDEBF7")
    _head(ws, row, 10, "อัตราการหมุนเวียน\nรวมต่อชนิดเครื่อง", rows=2, fill="DDEBF7")
    for col, text in zip((4, 5, 6, 7, 8, 9), ("จ่าย", "รับคืน") * 3):
        _put(ws, row + 1, col, text)
    row += 2
    by_role: dict[str, Counts] = {}
    other: dict[str, Counts] = {}
    for name, c in report.categories:
        role = category_role(name)
        target = by_role.setdefault(role, Counts()) if role else other.setdefault(name, Counts())
        for f in ("night_dispatch", "night_receipt", "day_dispatch", "day_receipt"):
            setattr(target, f, getattr(target, f) + getattr(c, f))
    lines: list[tuple[str, Counts]] = []
    for role, label in POOL_LABELS:
        if role == ROLE_CRYO and report.pool_counts.get(ROLE_CRYO):
            label = f"CRYO CUFF (ทั้งหมดมีในระบบ {report.pool_counts[ROLE_CRYO]} รายการ)"
        lines.append((label, by_role.get(role, Counts())))
    lines.extend(sorted(other.items()))
    pool_total = Counts()
    for i, (label, c) in enumerate(lines, start=1):
        for f in ("night_dispatch", "night_receipt", "day_dispatch", "day_receipt"):
            setattr(pool_total, f, getattr(pool_total, f) + getattr(c, f))
        _put(ws, row, 1, i)
        _put(ws, row, 2, label, align=_LEFT)
        _put(ws, row, 3)
        _merge(ws, row, 2, row, 3)
        vals = [c.night_dispatch, c.night_receipt, c.day_dispatch, c.day_receipt, c.total_dispatch, c.total_receipt, c.total]
        for col, v in zip(range(4, 11), vals):
            _put(ws, row, col, _blank0(v), fill="DDEBF7" if col == 10 else None)
        row += 1
    for col in (1, 2, 3):
        _put(ws, row, col)
    vals = [pool_total.night_dispatch, pool_total.night_receipt, pool_total.day_dispatch, pool_total.day_receipt,
            pool_total.total_dispatch, pool_total.total_receipt, pool_total.total]
    for col, v in zip(range(4, 11), vals):
        _put(ws, row, col, v, bold=True, fill="DDEBF7")
    row += 2

    moved = _moved_text(report)
    notes = [
        f"ช่วงเปลี่ยนกะ ±{report.grace_minutes} นาที: นับให้กะที่คนนั้นทำเป็นหลัก | {moved}",
        "ตารางแผนกนับเฉพาะ Infusion Pump",
        "Stand By: จากสรุป Standby ของวัน (แก้ไขได้ในระบบ)",
    ]
    row += 1  # the Owner's file keeps one spare line above the notes
    for text in notes:
        _write_cell(ws, row=row, column=1, value=text)
        row += 1
    ws.freeze_panes = "D5"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    ws.page_setup.fitToWidth = 1
    _widths(ws, [15, 14, 24, 8, 8, 8, 8, 8, 11, 11])
    ws["A1"].font = Font(bold=True, size=13)


def _moved_text(report: DailyReport) -> str:
    n_in = sum(1 for e in report.events if e.shift == Shift.NIGHT and e.clock_shift == Shift.DAY)
    n_out = sum(1 for e in report.events if e.shift == Shift.DAY and e.clock_shift == Shift.NIGHT)
    return f"กะดึก ย้ายเข้า {n_in} แถว ย้ายออก {n_out} แถว | กะเช้า ย้ายเข้า {n_out} แถว ย้ายออก {n_in} แถว"


def _category_columns(report: DailyReport) -> list[tuple[str, str | None]]:
    """(display name, role) per ชนิดเครื่อง row: the fixed types in the
    Owner's order, then any other category by its own name."""
    rows: list[tuple[str, str | None]] = [(ROLE_SHORT_NAMES[r], r) for r in ROLE_ORDER]
    for name, _ in report.categories:
        if category_role(name) is None:
            rows.append((name, None))
    return rows


def _category_sheet(ws: Worksheet, report: DailyReport) -> None:
    ws.title = SHEET_CATEGORY
    window, night_head, day_head, date_text = _windows(report)
    _title(ws, CATEGORY_TITLE.format(d=date_text, w=window))
    ws.row_dimensions[3].height = 36
    _head(ws, 3, 1, "ชนิดเครื่อง", rows=2)
    _head(ws, 3, 2, night_head, cols=2)
    _head(ws, 3, 4, day_head, cols=2)
    _head(ws, 3, 6, "Total per DAY", cols=2)
    _head(ws, 3, 8, "รวม", rows=2)
    for col, text in zip(range(2, 8), ("ส่ง", "รับ", "ส่ง", "รับ", "ส่งเครื่อง", "รับคืน")):
        _put(ws, 4, col, text)

    def agg(role, name) -> Counts:
        c = Counts()
        for cat, cc in report.categories:
            if (role and category_role(cat) == role) or (role is None and cat == name):
                for f in ("night_dispatch", "night_receipt", "day_dispatch", "day_receipt"):
                    setattr(c, f, getattr(c, f) + getattr(cc, f))
        return c

    def vals(c: Counts):
        return [c.night_dispatch, c.night_receipt, c.day_dispatch, c.day_receipt, c.total_dispatch, c.total_receipt, c.total]

    columns = _category_columns(report)
    row = 5
    for name, role in columns:
        _put(ws, row, 1, name, align=_LEFT)
        for col, v in zip(range(2, 9), vals(agg(role, name))):
            _put(ws, row, col, _blank0(v))
        row += 1
    _put(ws, row, 1, "รวม", bold=True, align=_LEFT)
    for col, v in zip(range(2, 9), vals(report.totals)):
        _put(ws, row, col, v, bold=True, fill="FFFF00")
    row += 2

    _write_cell(ws, row=row, column=1, value="แยกตามแผนก x ชนิดเครื่อง (รวม 2 กะ)", font=_BOLD)
    row += 1
    active = [(n, r) for n, r in columns if agg(r, n).total]
    ws.row_dimensions[row].height = 30
    _head(ws, row, 1, "แผนก", rows=2)
    for i, (name, _) in enumerate(active):
        _head(ws, row, 2 + 2 * i, name, cols=2)
        _put(ws, row + 1, 2 + 2 * i, "ส่ง")
        _put(ws, row + 1, 3 + 2 * i, "รับ")
    sum_col = 2 + 2 * len(active)
    _head(ws, row, sum_col, "รวม", cols=2)
    _put(ws, row + 1, sum_col, "ส่ง")
    _put(ws, row + 1, sum_col + 1, "รับ")
    row += 2

    per_ward: dict[str, dict[int, Counts]] = {}
    for e in report.events:
        for i, (name, role) in enumerate(active):
            if (role and category_role(e.category_name) == role) or (role is None and e.category_name == name):
                per_ward.setdefault(e.row_label, {}).setdefault(i, Counts()).add(e)
    order = [r.label for _, groups in _ward_blocks(report) for _, _, rows in groups for r in rows]
    total_cols = [0] * (2 * len(active) + 2)
    for label in order:
        cells = per_ward.get(label)
        if not cells:
            continue
        _put(ws, row, 1, label, align=_LEFT)
        wd = wr = 0
        for i in range(len(active)):
            c = cells.get(i, Counts())
            _put(ws, row, 2 + 2 * i, _blank0(c.total_dispatch))
            _put(ws, row, 3 + 2 * i, _blank0(c.total_receipt))
            total_cols[2 * i] += c.total_dispatch
            total_cols[2 * i + 1] += c.total_receipt
            wd, wr = wd + c.total_dispatch, wr + c.total_receipt
        _put(ws, row, sum_col, _blank0(wd))
        _put(ws, row, sum_col + 1, _blank0(wr))
        total_cols[-2] += wd
        total_cols[-1] += wr
        row += 1
    _put(ws, row, 1, "รวม", bold=True, align=_LEFT)
    for k, v in enumerate(total_cols):
        _put(ws, row, 2 + k, v, bold=True, fill="FFFF00")
    ws.freeze_panes = "B5"
    _widths(ws, [24] + [9] * (sum_col + 1))


def _operator_sheet(ws: Worksheet, report: DailyReport) -> None:
    ws.title = SHEET_OPERATOR
    window, _, _, date_text = _windows(report)
    _write_cell(ws, row=1, column=1, value=OPERATOR_TITLE.format(d=date_text, w=window))
    for col, h in enumerate(OPERATOR_HEADERS, start=1):
        _write_cell(ws, row=2, column=col, value=h, font=_BOLD)

    def line(label: str, c: Counts) -> list:
        return [label, c.night_dispatch, c.night_receipt, c.day_dispatch, c.day_receipt, c.total_dispatch, c.total_receipt, c.total]

    row = 3
    for name, c in report.operators:
        for col, v in enumerate(line(name, c), start=1):
            _write_cell(ws, row=row, column=col, value=v)
        row += 1
    for col, v in enumerate(line("รวม", report.totals), start=1):
        _write_cell(ws, row=row, column=col, value=v, font=_BOLD)
    ws.column_dimensions["A"].width = 20


def _events_sheet(ws: Worksheet, report: DailyReport) -> None:
    ws.title = SHEET_EVENTS
    for col, h in enumerate(EVENT_HEADERS, start=1):
        _write_cell(ws, row=1, column=col, value=h, font=_BOLD)
    for row, e in enumerate(report.events, start=2):
        values = [
            _THAI_SHIFT[e.shift],
            format_date(e.local.date()),
            e.local.strftime("%H:%M:%S"),
            "ส่ง" if e.kind == "dispatch" else "รับ",
            with_badge(e.bcm_code, e.source),
            e.category_name,
            e.ward_name,
            e.row_label,
            e.operator_name,
            e.notes,
            e.form_position,
        ]
        for col, v in enumerate(values, start=1):
            _write_cell(ws, row=row, column=col, value=v if v != "" else None)
    ws.freeze_panes = "A2"
    _widths(ws, [8, 12, 10, 6, 12, 16, 26, 18, 16, 14, 20])


def build_daily_workbook_sync(report: DailyReport, standby: dict[str, int] | None = None) -> bytes:
    wb = Workbook()
    _summary_sheet(wb.active, report, standby)
    _category_sheet(wb.create_sheet(), report)
    _operator_sheet(wb.create_sheet(), report)
    _events_sheet(wb.create_sheet(), report)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def build_daily_workbook_bounded(report: DailyReport, standby: dict[str, int] | None = None) -> bytes:
    """PR18 admission control: same semaphore, total deadline and
    renderer-lifetime accounting as the PR18E Excel exports."""
    return await report_xlsx_service.run_bounded(build_daily_workbook_sync, report, standby)
