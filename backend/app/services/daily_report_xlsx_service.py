"""Roadmap PR30 (D5): the daily summary workbook "รายงานรับ-ส่งเครื่อง".

Four sheets matching the pool team's current Excel file: "รายงาน" (ward
groups), "ชนิดเครื่อง", "ผู้คีย์" and "รายการ". Every string goes through the
PR18E centralized formula-injection guard (`report_xlsx_service._write_cell`),
and generation runs through the PR18 admission control
(`report_xlsx_service.run_bounded`). No HN or any patient field exists in the
input, so none can be emitted.
"""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.services import report_xlsx_service
from app.services.daily_report_service import Counts, DailyReport, _THAI_SHIFT, format_date
from app.services.report_xlsx_service import _write_cell

SHEET_SUMMARY = "รายงาน"
SHEET_CATEGORY = "ชนิดเครื่อง"
SHEET_OPERATOR = "ผู้คีย์"
SHEET_EVENTS = "รายการ"

# Verbatim headers of the Owner's file.
SUMMARY_HEADERS_TOP = ["รูปแบบการจ่ายเครื่อง", "ประเภทการรักษา", "แผนก", "Night", "", "Day", "", "Stand By", "Total per DAY", ""]
SUMMARY_HEADERS_SUB = ["", "", "", "ส่ง", "รับ", "ส่ง", "รับ", "", "ส่งเครื่อง", "รับคืน"]
CATEGORY_HEADERS_TOP = ["ชนิดเครื่อง", "Night", "", "Day", "", "Total per DAY", "", "รวม"]
CATEGORY_HEADERS_SUB = ["", "ส่ง", "รับ", "ส่ง", "รับ", "ส่งเครื่อง", "รับคืน", ""]
OPERATOR_HEADERS = ["ผู้คีย์", "กะดึก ส่ง", "กะดึก รับ", "กะเช้า ส่ง", "กะเช้า รับ", "รวม ส่ง", "รวม รับ", "รวมทั้งหมด"]
EVENT_HEADERS = [
    "กะ",
    "วันที่",
    "เวลา",
    "งาน",
    "ID CODE (BCM)",
    "ชนิดเครื่อง",
    "Ward (ในฟอร์ม)",
    "แถวในรายงาน",
    "ผู้คีย์ (BME)",
    "หมายเหตุ",
    "ตำแหน่งในฟอร์ม",
]

_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill(fill_type="solid", start_color="1E293B", end_color="1E293B")
_BOLD = Font(bold=True)
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _header_cell(ws: Worksheet, row: int, column: int, value: str) -> None:
    cell = _write_cell(ws, row=row, column=column, value=value if value != "" else None, font=_HEADER_FONT)
    cell.fill = _HEADER_FILL
    cell.alignment = _CENTER


def _two_row_header(ws: Worksheet, top: list[str], sub: list[str], *, merges: list[tuple[int, int]], row: int = 1) -> None:
    for c, (t, s) in enumerate(zip(top, sub), start=1):
        _header_cell(ws, row, c, t)
        _header_cell(ws, row + 1, c, s)
    for first, last in merges:  # 1-based inclusive column spans merged on the top row
        ws.merge_cells(start_row=row, start_column=first, end_row=row, end_column=last)
    for c, s in enumerate(sub, start=1):
        if s == "":  # single-row labels span both header rows
            ws.merge_cells(start_row=row, start_column=c, end_row=row + 1, end_column=c)


def _widths(ws: Worksheet, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _summary_sheet(ws: Worksheet, report: DailyReport) -> None:
    ws.title = SHEET_SUMMARY
    _two_row_header(ws, SUMMARY_HEADERS_TOP, SUMMARY_HEADERS_SUB, merges=[(4, 5), (6, 7), (9, 10)])
    row = 3
    for r in report.ward_rows:
        c = r.counts
        values = [
            r.dispense_mode,
            r.treatment_type,
            r.label,
            c.night_dispatch,
            c.night_receipt,
            c.day_dispatch,
            c.day_receipt,
            None,  # Stand By: no data source in this system (Standby Snapshots are future work)
            c.total_dispatch,
            c.total_receipt,
        ]
        for col, v in enumerate(values, start=1):
            _write_cell(ws, row=row, column=col, value=v)
        row += 1
    t = report.totals
    for col, v in enumerate(
        ["รวม", "", "", t.night_dispatch, t.night_receipt, t.day_dispatch, t.day_receipt, None, t.total_dispatch, t.total_receipt],
        start=1,
    ):
        _write_cell(ws, row=row, column=col, value=None if v == "" else v, font=_BOLD)
    ws.freeze_panes = "D3"
    _widths(ws, [24, 24, 20, 8, 8, 8, 8, 10, 12, 12])


def _category_sheet(ws: Worksheet, report: DailyReport) -> None:
    ws.title = SHEET_CATEGORY
    _two_row_header(ws, CATEGORY_HEADERS_TOP, CATEGORY_HEADERS_SUB, merges=[(2, 3), (4, 5), (6, 7)])

    def line(label: str, c: Counts) -> list:
        return [label, c.night_dispatch, c.night_receipt, c.day_dispatch, c.day_receipt, c.total_dispatch, c.total_receipt, c.total]

    row = 3
    for name, c in report.categories:
        for col, v in enumerate(line(name, c), start=1):
            _write_cell(ws, row=row, column=col, value=v)
        row += 1
    for col, v in enumerate(line("รวม", report.totals), start=1):
        _write_cell(ws, row=row, column=col, value=v, font=_BOLD)
    ws.freeze_panes = "B3"
    _widths(ws, [30, 8, 8, 8, 8, 12, 12, 10])


def _operator_sheet(ws: Worksheet, report: DailyReport) -> None:
    ws.title = SHEET_OPERATOR
    _write_cell(ws, row=1, column=1, value=f"รวม 2 กะ วันที่ {format_date(report.report_date)}", font=Font(bold=True, size=13))
    for col, h in enumerate(OPERATOR_HEADERS, start=1):
        _header_cell(ws, 2, col, h)

    def line(label: str, c: Counts) -> list:
        return [label, c.night_dispatch, c.night_receipt, c.day_dispatch, c.day_receipt, c.total_dispatch, c.total_receipt, c.total]

    row = 3
    for name, c in report.operators:
        for col, v in enumerate(line(name, c), start=1):
            _write_cell(ws, row=row, column=col, value=v)
        row += 1
    for col, v in enumerate(line("รวม", report.totals), start=1):
        _write_cell(ws, row=row, column=col, value=v, font=_BOLD)
    ws.freeze_panes = "B3"
    _widths(ws, [28, 10, 10, 10, 10, 10, 10, 12])


def _events_sheet(ws: Worksheet, report: DailyReport) -> None:
    ws.title = SHEET_EVENTS
    for col, h in enumerate(EVENT_HEADERS, start=1):
        _header_cell(ws, 1, col, h)
    for row, e in enumerate(report.events, start=2):
        values = [
            _THAI_SHIFT[e.shift],
            format_date(e.local.date()),
            e.local.strftime("%H:%M:%S"),
            "ส่ง" if e.kind == "dispatch" else "รับ",
            e.bcm_code,
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
    ws.auto_filter.ref = f"A1:{get_column_letter(len(EVENT_HEADERS))}{max(len(report.events) + 1, 1)}"
    _widths(ws, [10, 13, 10, 6, 16, 24, 20, 18, 24, 30, 16])


def build_daily_workbook_sync(report: DailyReport) -> bytes:
    wb = Workbook()
    _summary_sheet(wb.active, report)
    _category_sheet(wb.create_sheet(), report)
    _operator_sheet(wb.create_sheet(), report)
    _events_sheet(wb.create_sheet(), report)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def build_daily_workbook_bounded(report: DailyReport) -> bytes:
    """PR18 admission control: same semaphore, total deadline and
    renderer-lifetime accounting as the PR18E Excel exports."""
    return await report_xlsx_service.run_bounded(build_daily_workbook_sync, report)
