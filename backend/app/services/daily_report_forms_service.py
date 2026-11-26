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

Not printed: the trailing "Equipment Verify Checklist" (FI-CES-BCM-PO-001/2),
whose "Cleaner" column would assert cleaning data this system never records.
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
.footer {{ position: absolute; bottom: 21.6pt; font-size: 10pt; }}
.footer.left {{ left: 18pt; }}
.footer.right {{ right: 18pt; }}
</style></head><body>{"".join(sections)}</body></html>"""


def render_forms_pdf(report: DailyReport, kind: str, shift: str = "both") -> bytes:
    return weasyprint.HTML(string=render_forms_html(report, kind, shift)).write_pdf()


async def render_forms_pdf_bounded(report: DailyReport, kind: str, shift: str = "both") -> bytes:
    """PR18 admission control (shared PDF semaphore, deadline, slot accounting)."""
    return await report_pdf_service.run_bounded(render_forms_pdf, report, kind, shift)
