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
Check columns show a green tick / red cross drawn as inline SVG (so no glyph
depends on the font), like the Owner's tool: a tick for a true OR unrecorded
(NULL) check -- D4 defaults to checked and legacy-sheet rows carry no checks --
and a cross only for an explicit false (Cryo-Cuff items 1/2/3 mapped per D10).
The remark column prints only the operator-entered note or the Bed Alarms /
PNEUMATIC PUMP label; system notes (``system_notes``) are never printed.
Fonts: the Owner's tool prints in Angsana New (proprietary, not bundled); this
renderer uses the OFL "Trirong" Thai serif at the legacy sizes scaled by
``FONT_SCALE`` (Angsana is a much narrower face). No HN or patient field is read.

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
from fontTools.ttLib import TTFont

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
from app.services.system_notes import operator_note

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

# Green tick / red cross with a thin black outline, like the Segoe UI Emoji
# glyphs the Owner's tool prints (about 12pt x 10pt and 9pt x 9pt).
_TICK = (
    '<svg class="chk chk-ok" viewBox="0 0 24 19" width="12pt" height="9.5pt"><title>&#10004;</title>'
    '<path d="M1 10 L4.3 6.8 L8.6 10.8 L19.7 1 L23 4.3 L8.8 17.6 Z" fill="#22cc22" stroke="#000" '
    'stroke-width="0.9" stroke-linejoin="round"/></svg>'
)
_CROSS = (
    '<svg class="chk chk-bad" viewBox="0 0 20 20" width="9.5pt" height="9.5pt"><title>&#10008;</title>'
    '<path d="M2 5.5 L5.5 2 L10 6.5 L14.5 2 L18 5.5 L13.5 10 L18 14.5 L14.5 18 L10 13.5 L5.5 18 L2 14.5 L6.5 10 Z" '
    'fill="#e02020" stroke="#000" stroke-width="0.9" stroke-linejoin="round"/></svg>'
)

# Legacy (Angsana New) sizes in pt, scaled for the wider OFL Thai serif.
FONT_SCALE = 0.78
FS_TITLE, FS_DATE, FS_FORM, FS_HEAD, FS_HEAD_SMALL, FS_DATA, FS_NOTE, FS_MIN = (
    round(x * FONT_SCALE, 1) for x in (18.0, 15.0, 15.0, 15.0, 13.0, 14.0, 10.0, 7.0)
)
_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_METRICS: tuple[dict[int, str], dict[str, int], int] | None = None
_FONT_CSS: str | None = None


def _font_css() -> str:
    """@font-face rules for the Trirong form font (single merged TTF per
    weight, base64 inline: WeasyPrint cannot resolve split unicode-range files)."""
    global _FONT_CSS
    if _FONT_CSS is None:
        faces = []
        for weight, name in ((400, "Trirong-Regular.ttf"), (700, "Trirong-Bold.ttf")):
            uri = "data:font/ttf;base64," + base64.b64encode((_FONTS_DIR / name).read_bytes()).decode("ascii")
            faces.append(
                f'@font-face {{ font-family: "Trirong Form"; font-weight: {weight}; font-style: normal; '
                f'src: url("{uri}") format("truetype"); }}'
            )
        _FONT_CSS = "\n".join(faces)
    return _FONT_CSS


def _text_width_em(text: str) -> float:
    """Advance width of ``text`` in em using the bundled font (combining Thai
    marks advance 0)."""
    global _METRICS
    if _METRICS is None:
        font = TTFont(_FONTS_DIR / "Trirong-Regular.ttf")
        cmap = font.getBestCmap()
        hmtx = font["hmtx"]
        upm = font["head"].unitsPerEm
        _METRICS = (cmap, {g: hmtx[g][0] for g in hmtx.metrics}, upm)
    cmap, adv, upm = _METRICS
    return sum(adv.get(cmap.get(ord(c), ".notdef"), upm // 2) for c in text) / upm


def _e(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _logo_uri() -> str:
    global _LOGO_URI
    if _LOGO_URI is None:
        _LOGO_URI = "data:image/jpeg;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return _LOGO_URI


def _check_cell(value: bool | None) -> str:
    """Tick unless explicitly false: unrecorded (NULL) prints the D4 default."""
    return _CROSS if value is False else _TICK


def _fit(text: str, width_pt: float, base: float = FS_DATA, bold: bool = False) -> str:
    """Legacy rule: the text keeps its full size and only shrinks when it
    truly overflows the cell (room = width - 5pt), down to ``FS_MIN``."""
    room = width_pt - 5
    need = _text_width_em(text) * base * (1.1 if bold else 1.0)
    if need <= room:
        return ""
    return f" style='font-size:{max(base * room / need, FS_MIN):.1f}pt'"


def _note(e: DailyEvent) -> str:
    """Operator-entered remark, else the form's equipment label. System notes
    (legacy-sheet trace text) are never printed."""
    note = operator_note(e.notes)
    if note:
        return note
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
        f"<td><div class='c'><span{_fit(e.local.strftime('%H:%M:%S'), W[7])}>{e.local.strftime('%H:%M:%S')}</span></div></td>"
        f"<td><div class='c note'><span{_fit(note, W[8], FS_NOTE)}>{_e(note)}</span></div></td></tr>"
    )


def _page_html(events: list[DailyEvent], kind: str, form_date: date) -> str:
    padded: list[DailyEvent | None] = list(events) + [None] * (FORM_ROWS_PER_PAGE - len(events))
    h1, h2, h3 = TABLE_HEAD_H[kind]
    user_head, bme_head = PERSON_HEAD[kind]
    cols = "".join(f"<col style='width:{w}pt'>" for w in COLUMN_WIDTHS[kind])
    width = sum(COLUMN_WIDTHS[kind])
    W = COLUMN_WIDTHS[kind]

    def hc(text: str, i: int, base: float) -> str:  # header text, shrunk only if it overflows
        return f"<span{_fit(text, W[i], base, True)}>{text}</span>"

    head = (
        f"<thead><tr style='height:{h1}pt'><th rowspan='3'>{hc(COL_ME_CODE, 0, FS_HEAD)}</th>"
        f"<th colspan='3'>{COL_PRIMARY_CHECK}</th>"
        f"<th rowspan='2'>{hc(user_head, 4, FS_HEAD)}</th><th rowspan='3'>{hc(COL_WARD, 5, FS_HEAD)}</th>"
        f"<th rowspan='2'>{hc(bme_head, 6, FS_HEAD)}</th>"
        f"<th rowspan='3'>{hc(COL_TIME, 7, FS_HEAD)}</th><th rowspan='3'>{hc(COL_NOTES, 8, FS_HEAD)}</th></tr>"
        f"<tr style='height:{h2}pt'>{''.join(f'<th class=sub>{hc(a, i, FS_HEAD)}</th>' for i, (a, _) in enumerate(COL_CHECKS, 1))}</tr>"
        f"<tr style='height:{h3}pt'>{''.join(f'<th class=small>{hc(b, i, FS_HEAD_SMALL)}</th>' for i, (_, b) in enumerate(COL_CHECKS, 1))}"
        f"<th class=small>{hc('( User )', 4, FS_HEAD_SMALL)}</th><th class=small>{hc('( BME )', 6, FS_HEAD_SMALL)}</th></tr></thead>"
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
        # D23: pre-printed template ticks (nothing stored): Cleaner..Battery + Pass, Fail blank;
        # a defective receipt ticks Fail instead of Pass. The sign column stays blank.
        pass_m, fail_m = ("", _TICK) if e.defective else (_TICK, "")
        marks = "".join(f"<td><div class='c'>{m}</div></td>" for m in (_TICK,) * 4 + (pass_m, fail_m))
        body.append(
            f"<tr><td><div class='c'>{_e(format_date(form_date))}</div></td>"
            f"<td><div class='c'>{_e(code)}</div></td>{marks}"
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
{_font_css()}
@page {{ size: 595.28pt 841.89pt; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: "Trirong Form", serif; font-size: {FS_DATA}pt; color: #000; }}
.page {{ position: relative; width: 595.28pt; height: 841pt; overflow: hidden; page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
.logo {{ position: absolute; left: 18pt; top: 21.6pt; width: 110.25pt; height: 33pt; }}
.body {{ position: absolute; left: 18pt; top: 54pt; }}
.r1 {{ height: 22.5pt; line-height: 22.5pt; text-align: center; font-size: {FS_TITLE}pt; font-weight: 700; }}
.r2 {{ height: 23.25pt; line-height: 23.25pt; text-align: right; font-size: {FS_DATE}pt; }}
.r3 {{ height: 22.5pt; line-height: 22.5pt; text-align: center; font-size: {FS_FORM}pt; font-weight: 700; border-bottom: 1px solid #000; }}
table {{ border-collapse: collapse; table-layout: fixed; width: 100%; }}
th, td {{ border: 0.75pt solid #000; padding: 0 1pt; font-weight: 400; }}
th {{ font-weight: 700; text-align: center; font-size: {FS_HEAD}pt; line-height: 1.1; white-space: nowrap; }}
th.sub {{ font-size: {FS_HEAD}pt; }}
th.small {{ font-size: {FS_HEAD_SMALL}pt; }}
tbody tr {{ height: {ROW_H}pt; }}
.c {{ height: {ROW_H - 0.75}pt; display: flex; align-items: center; justify-content: center; text-align: center; overflow: hidden; white-space: nowrap; font-size: {FS_DATA}pt; }}
.c.code {{ justify-content: flex-start; padding-left: 2pt; }}
.c.note {{ line-height: 1.05; }}
.chk {{ vertical-align: middle; }}
.sheet {{ position: absolute; left: {MARGIN_X}pt; top: {MARGIN_Y}pt; transform-origin: 0 0; }}
.sheet .logo {{ position: absolute; left: 3pt; top: {CHECK_TITLE_H + 6}pt; width: 110.25pt; height: 33pt; }}
.sheet table {{ width: auto; }}
.sheet tbody tr {{ height: {CHECK_ROW_H}pt; }}
.sheet {{ font-family: "Noto Sans Thai PDF", sans-serif; }}
.sheet .c {{ height: {CHECK_ROW_H - 0.75}pt; font-size: 10pt; padding: 0 2pt; }}
.sheet .c.t {{ height: {CHECK_TITLE_H - 0.75}pt; font-size: 12pt; }}
.footer {{ position: absolute; bottom: 21.6pt; font-size: 10pt; font-family: "Noto Sans Thai PDF", sans-serif; }}
.footer.left {{ left: 18pt; }}
.footer.right {{ right: 18pt; }}
</style></head><body>{"".join(sections)}</body></html>"""


def render_forms_pdf(report: DailyReport, kind: str, shift: str = "both") -> bytes:
    return weasyprint.HTML(string=render_forms_html(report, kind, shift)).write_pdf()


async def render_forms_pdf_bounded(report: DailyReport, kind: str, shift: str = "both") -> bytes:
    """PR18 admission control (shared PDF semaphore, deadline, slot accounting)."""
    return await report_pdf_service.run_bounded(render_forms_pdf, report, kind, shift)
