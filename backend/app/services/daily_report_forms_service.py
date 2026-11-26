"""Roadmap PR30 (D5/D10/D12): printable daily forms "แบบบันทึกการเบิก-จ่าย
Equipment Pool" (dispatch form and receipt form), laid out like the company
form FI-CES-BCM-PO-001/1: A4 portrait, form logo, 3-row column header,
33 data rows per page padded with blank rows, footer form number.

Day form = the Day shift's rows; Night form = the Night shift's rows split
into one form per calendar date (20:00-24:00 and 00:00-08:00), as the Owner's
own tool prints them. Header text, column order, per-form person labels and
column widths/row heights follow that tool's measurements of the paper form.

D12: the first column header is the company form's own "ME.Code" label and
shows the equipment's BCM Code; this is a printed-label exception only.
Check columns show a tick/cross drawn as inline SVG (so no glyph depends on
the font) from the stored checks (Cryo-Cuff items 1/2/3 mapped per D10); a
NULL/unrecorded check prints blank. No HN or patient field is read.

D17 (Owner Governance 2026-11-26): each shift's forms end with the paper form
"Equipment Verify Checklist" (FI-CES-BCM-PO-001/2), reproduced in form and
layout, one row per device RECEIVED in that shift (one page group per date).
It is a printed paper form only: every check cell (Cleaner, Function Test,
Run Test, Battery Check, Pass, Fail) and the sign column print BLANK for hand
completion; the system records, stores and derives no cleaning/check result
from it. Only the date, the BCM Code and the equipment type are printed.
"""

import base64
import html
from datetime import date, timedelta
from pathlib import Path

import weasyprint

from app.core.reporting_time import Shift
from app.services import report_pdf_service
from app.services.daily_report_service import (
    FORM_NOTE_LABELS,
    FORM_ROWS_PER_PAGE,
    ROLE_SHORT_NAMES,
    DailyEvent,
    DailyReport,
    category_role,
    format_date,
)
from app.services.equipment_badge import with_badge

FORM_TITLE = "แบบบันทึกการเบิก-จ่าย Equipment Pool"
KIND_TITLES = {"dispatch": "ส่งเครื่อง", "receipt": "รับเครื่อง"}
COL_ME_CODE = "ME.Code"
COL_PRIMARY_CHECK = "Primary Check"
COL_CHECKS = [("ตัวเครื่อง", "(หน้าจอไม่แตกร้าว)"), ("สายชาร์จ", "(สายไม่ขาด)"), ("Pole Clamp", "(ไม่แตกหัก,ไม่งอ)")]
# (User column, BME column) person labels per form.
PERSON_HEAD = {"dispatch": ("ผู้รับเครื่อง", "ผู้ส่งเครื่อง"), "receipt": ("ผู้ส่งเครื่อง", "ผู้รับเครื่อง")}
COL_WARD = "Ward"
COL_TIME = "เวลา"
COL_NOTES = "หมายเหตุ"
FOOTER_LEFT = "FI-CES-BCM-PO-001/1 แก้ไขครั้งที่ 04"
FOOTER_RIGHT = "วันที่บังคับใช้ 25/06/2569"
SHIFT_FILTERS = ("day", "night", "both")

# D17 Equipment Verify Checklist (FI-CES-BCM-PO-001/2): measurements of the
# paper form (pt). The 10-column sheet is scaled to the printable width.
CHECK_TITLE = "Equipment Verify Checklist"
CHECK_COLUMNS = (75.0, 75.0, 75.0, 75.0, 75.0, 75.0, 75.0, 75.0, 91.5, 91.5)
CHECK_ROW_H = 15.75
CHECK_TITLE_H = 17.25
CHECK_HEAD = ("Date", "ME.Code", "Performance Check", "Status", "Remark")
CHECK_SUB = ("Cleaner", "Function Test", "Run Test", "Battery Check", "Pass", "Fail")
CHECK_FOOTER_LEFT = "FI-CES-BCM-PO-001/2 แก้ไขครั้งที่ 04"
PAGE_W, PAGE_H, MARGIN_X, MARGIN_Y = 595.28, 841.89, 18.0, 54.0

# Measurements of the paper form (pt): column widths, header row heights.
COLUMN_WIDTHS = {
    "dispatch": (67.5, 74.25, 65.25, 70.5, 49.5, 49.5, 49.5, 49.5, 59.25),
    "receipt": (63.75, 86.25, 73.5, 81.0, 49.5, 44.25, 49.5, 45.0, 59.25),
}
TABLE_HEAD_H = {"dispatch": (25.5, 21.75, 21.75), "receipt": (27.0, 21.75, 21.75)}
ROW_H = 18.0
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "form_logo.jpg"

_LOGO_URI: str | None = None

_TICK = (
    '<svg class="chk chk-ok" viewBox="0 0 12 12" width="13" height="13"><title>✔</title>'
    '<path d="M1.5 6.5 L4.8 9.8 L10.5 2.5" fill="none" stroke="#2e7d32" stroke-width="1.8"/></svg>'
)
_CROSS = (
    '<svg class="chk chk-bad" viewBox="0 0 12 12" width="13" height="13"><title>✘</title>'
    '<path d="M2 2 L10 10 M10 2 L2 10" fill="none" stroke="#d32f2f" stroke-width="1.8"/></svg>'
)


def _e(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _logo_uri() -> str:
    global _LOGO_URI
    if _LOGO_URI is None:
        _LOGO_URI = "data:image/jpeg;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return _LOGO_URI


def _check_cell(value: bool | None) -> str:
    return "" if value is None else (_TICK if value else _CROSS)


def _fit(text: str, width_pt: float, base: float = 10.0) -> str:
    """Shrink long text (e.g. long ward names) so it stays inside its cell."""
    size = min(base, (width_pt - 3) / (max(len(text), 1) * 0.68))
    return "" if size >= base else f" style='font-size:{max(size, 4.5):.1f}pt'"


def _note(e: DailyEvent) -> str:
    if e.notes:
        return e.notes
    return FORM_NOTE_LABELS.get(category_role(e.category_name) or "", "")


def _row_html(e: DailyEvent | None, kind: str) -> str:
    W = COLUMN_WIDTHS[kind]
    if e is None:
        return "<tr>" + "<td><div class='c'></div></td>" * 9 + "</tr>"
    checks = "".join(f"<td><div class='c'>{_check_cell(e.checks.get(k))}</div></td>" for k in ("screen", "charger", "clamp"))
    code, user, ward, bme = with_badge(e.bcm_code, e.source), e.contact_name or "", e.ward_name, e.operator_name
    note = _note(e)
    return (
        f"<tr><td><div class='c code'>{_e(code)}</div></td>{checks}"
        f"<td><div class='c'><span{_fit(user, W[4])}>{_e(user)}</span></div></td>"
        f"<td><div class='c'><span{_fit(ward, W[5])}>{_e(ward)}</span></div></td>"
        f"<td><div class='c'><span{_fit(bme, W[6])}>{_e(bme)}</span></div></td>"
        f"<td><div class='c'>{e.local.strftime('%H:%M:%S')}</div></td>"
        f"<td><div class='c note'><span{_fit(note, W[8], 8)}>{_e(note)}</span></div></td></tr>"
    )


def _page_html(events: list[DailyEvent], kind: str, form_date: date) -> str:
    padded: list[DailyEvent | None] = list(events) + [None] * (FORM_ROWS_PER_PAGE - len(events))
    h1, h2, h3 = TABLE_HEAD_H[kind]
    user_head, bme_head = PERSON_HEAD[kind]
    cols = "".join(f"<col style='width:{w}pt'>" for w in COLUMN_WIDTHS[kind])
    width = sum(COLUMN_WIDTHS[kind])
    head = (
        f"<thead><tr style='height:{h1}pt'><th rowspan='3'>{COL_ME_CODE}</th>"
        f"<th colspan='3'>{COL_PRIMARY_CHECK}</th>"
        f"<th rowspan='2'>{user_head}</th><th rowspan='3'>{COL_WARD}</th><th rowspan='2'>{bme_head}</th>"
        f"<th rowspan='3'>{COL_TIME}</th><th rowspan='3'>{COL_NOTES}</th></tr>"
        f"<tr style='height:{h2}pt'>{''.join(f'<th class=sub>{a}</th>' for a, _ in COL_CHECKS)}</tr>"
        f"<tr style='height:{h3}pt'>{''.join(f'<th class=small>{b}</th>' for _, b in COL_CHECKS)}"
        "<th class=small>( User )</th><th class=small>( BME )</th></tr></thead>"
    )
    body = "".join(_row_html(e, kind) for e in padded)
    return (
        "<section class='page'>"
        f"<img class='logo' src='{_logo_uri()}'>"
        f"<div class='body' style='width:{width}pt'>"
        f"<div class='r1'>{KIND_TITLES[kind]}</div>"
        f"<div class='r2'>วันที่ {format_date(form_date)}</div>"
        f"<div class='r3'>{FORM_TITLE}</div>"
        f"<table><colgroup>{cols}</colgroup>{head}<tbody>{body}</tbody></table></div>"
        f"<div class='footer left'>{FOOTER_LEFT}</div><div class='footer right'>{FOOTER_RIGHT}</div>"
        "</section>"
    )


def _check_scale() -> float:
    return (PAGE_W - 2 * MARGIN_X) / sum(CHECK_COLUMNS)


def checklist_rows_per_page() -> int:
    """Rows that fit under the title + 3 logo rows + 3 header rows (58 on A4)."""
    scale = _check_scale()
    head = (CHECK_TITLE_H + CHECK_ROW_H * 6) * scale
    room = PAGE_H - 2 * MARGIN_Y - head
    return max(1, int(room / (CHECK_ROW_H * scale)))


def _check_remark(e: DailyEvent) -> str:
    """Equipment type label (as the form's Remark column); never the free-text note."""
    role = category_role(e.category_name)
    return FORM_NOTE_LABELS.get(role or "") or ROLE_SHORT_NAMES.get(role or "") or e.category_name


def _check_page_html(rows: list[DailyEvent], form_date: date) -> str:
    cells = lambda n: "<td><div class='c'></div></td>" * n  # noqa: E731
    scale = _check_scale()
    per_page = checklist_rows_per_page()
    cols = "".join(f"<col style='width:{w}pt'>" for w in CHECK_COLUMNS)
    body = []
    for e in rows:
        code, remark = with_badge(e.bcm_code, e.source), _check_remark(e)
        # Check cells (Cleaner .. Fail) and the sign column are always blank (D17).
        body.append(
            f"<tr><td><div class='c'>{_e(format_date(form_date))}</div></td>"
            f"<td><div class='c'>{_e(code)}</div></td>{cells(6)}"
            f"<td><div class='c'><span{_fit(remark, CHECK_COLUMNS[8], 10)}>{_e(remark)}</span></div></td>{cells(1)}</tr>"
        )
    body.extend(f"<tr>{cells(10)}</tr>" for _ in range(per_page - len(rows)))
    h3 = CHECK_ROW_H * 3 - 0.75
    head = (
        f"<tr><td colspan='9'><div class='c t'>{CHECK_TITLE}</div></td><td><div class='c t'></div></td></tr>"
        + f"<tr>{cells(10)}</tr>" * 3
        + f"<tr><td rowspan='3'><div class='c' style='height:{h3}pt'>{CHECK_HEAD[0]}</div></td>"
        f"<td rowspan='3'><div class='c' style='height:{h3}pt'>{CHECK_HEAD[1]}</div></td>"
        f"<td colspan='4'><div class='c'>{CHECK_HEAD[2]}</div></td><td colspan='2'><div class='c'>{CHECK_HEAD[3]}</div></td>"
        f"<td rowspan='3'><div class='c' style='height:{h3}pt'>{CHECK_HEAD[4]}</div></td>"
        f"<td rowspan='3'><div class='c' style='height:{h3}pt'></div></td></tr>"
        f"<tr>{''.join(f'<td><div class=c>{t}</div></td>' for t in CHECK_SUB)}</tr>"
        f"<tr>{cells(6)}</tr>"
    )
    return (
        "<section class='page check'>"
        f"<div class='sheet' style='transform:scale({scale:.4f})'><img class='logo' src='{_logo_uri()}'>"
        f"<table style='width:{sum(CHECK_COLUMNS)}pt'><colgroup>{cols}</colgroup><tbody>{head}{''.join(body)}</tbody></table></div>"
        f"<div class='footer left'>{CHECK_FOOTER_LEFT}</div><div class='footer right'>{FOOTER_RIGHT}</div>"
        "</section>"
    )


def _checklist_pages(report: DailyReport, shift: Shift) -> list[str]:
    """D17: one page group per form date that has receipts in this shift."""
    per_page = checklist_rows_per_page()
    pages: list[str] = []
    for form_date, group in _form_groups(report, shift):
        received = [e for e in group if e.kind == "receipt"]
        pages.extend(_check_page_html(received[i : i + per_page], form_date) for i in range(0, len(received), per_page))
    return pages


def _form_groups(report: DailyReport, shift: Shift) -> list[tuple[date, list[DailyEvent]]]:
    """(form date, that form's events). Day = one form dated the report date;
    Night = one form per calendar date, the earlier one first, always both."""
    d = report.report_date
    if shift == Shift.DAY:
        dates = [d]
    else:
        dates = [d - timedelta(days=1), d]
    events = [e for e in report.events if e.shift == shift]
    for e in events:
        if e.local.date() not in dates:
            dates.append(e.local.date())
    dates.sort()
    return [(fd, [e for e in events if e.local.date() == fd]) for fd in dates]


def render_forms_html(report: DailyReport, kind: str, shift: str = "both") -> str:
    """``kind``: "dispatch", "receipt" or "both" (dispatch form then receipt
    form). ``shift``: "day", "night" or "both" (Night then Day)."""
    kinds = ["dispatch", "receipt"] if kind == "both" else [kind]
    shifts = {"day": [Shift.DAY], "night": [Shift.NIGHT], "both": [Shift.NIGHT, Shift.DAY]}[shift]
    sections = []
    for sh in shifts:
        groups = _form_groups(report, sh)
        for k in kinds:
            for form_date, group in groups:
                events = [e for e in group if e.kind == k]
                chunks = [events[i : i + FORM_ROWS_PER_PAGE] for i in range(0, len(events), FORM_ROWS_PER_PAGE)] or [[]]
                sections.extend(_page_html(chunk, k, form_date) for chunk in chunks)
        if "receipt" in kinds:
            sections.extend(_checklist_pages(report, sh))
    return f"""<!DOCTYPE html>
<html lang="th"><head><meta charset="utf-8"><style>
{report_pdf_service._FONT_FACE_CSS}
@page {{ size: 595.28pt 841.89pt; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: "Noto Sans Thai PDF", sans-serif; font-size: 10pt; color: #000; }}
.page {{ position: relative; width: 595.28pt; height: 841pt; overflow: hidden; page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
.logo {{ position: absolute; left: 18pt; top: 21.6pt; width: 110.25pt; height: 33pt; }}
.body {{ position: absolute; left: 18pt; top: 54pt; }}
.r1 {{ height: 22.5pt; line-height: 22.5pt; text-align: center; font-size: 14pt; font-weight: 700; }}
.r2 {{ height: 23.25pt; line-height: 23.25pt; text-align: right; font-size: 11pt; }}
.r3 {{ height: 22.5pt; line-height: 22.5pt; text-align: center; font-size: 11pt; font-weight: 700; border-bottom: 1px solid #000; }}
table {{ border-collapse: collapse; table-layout: fixed; width: 100%; }}
th, td {{ border: 0.75pt solid #000; padding: 0 1pt; font-weight: 400; }}
th {{ font-weight: 700; text-align: center; font-size: 10pt; line-height: 1.1; }}
th.sub {{ font-size: 10pt; }}
th.small {{ font-size: 8pt; }}
tbody tr {{ height: {ROW_H}pt; }}
.c {{ height: {ROW_H - 0.75}pt; display: flex; align-items: center; justify-content: center; text-align: center; overflow: hidden; white-space: nowrap; font-size: 10pt; }}
.c.code {{ justify-content: flex-start; padding-left: 2pt; }}
.c.note {{ line-height: 1.05; }}
.chk {{ vertical-align: middle; }}
.sheet {{ position: absolute; left: {MARGIN_X}pt; top: {MARGIN_Y}pt; transform-origin: 0 0; }}
.sheet .logo {{ position: absolute; left: 3pt; top: {CHECK_TITLE_H + 6}pt; width: 110.25pt; height: 33pt; }}
.sheet table {{ width: auto; }}
.sheet tbody tr {{ height: {CHECK_ROW_H}pt; }}
.sheet .c {{ height: {CHECK_ROW_H - 0.75}pt; font-size: 10pt; padding: 0 2pt; }}
.sheet .c.t {{ height: {CHECK_TITLE_H - 0.75}pt; font-size: 12pt; }}
.footer {{ position: absolute; bottom: 21.6pt; font-size: 10pt; }}
.footer.left {{ left: 18pt; }}
.footer.right {{ right: 18pt; }}
</style></head><body>{"".join(sections)}</body></html>"""


def render_forms_pdf(report: DailyReport, kind: str, shift: str = "both") -> bytes:
    return weasyprint.HTML(string=render_forms_html(report, kind, shift)).write_pdf()


async def render_forms_pdf_bounded(report: DailyReport, kind: str, shift: str = "both") -> bytes:
    """PR18 admission control (shared PDF semaphore, deadline, slot accounting)."""
    return await report_pdf_service.run_bounded(render_forms_pdf, report, kind, shift)
