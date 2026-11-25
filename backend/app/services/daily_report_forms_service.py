"""Roadmap PR30 (D5/D10/D12): printable daily forms "แบบบันทึกการเบิก-จ่าย
Equipment Pool" (dispatch form and receipt form), A4 portrait, Thai font,
fixed rows per page with the column header repeated on every page.

D12: the first column header is the company form's own "ME.Code" label and
shows the equipment's BCM Code; this is a printed-label exception only.
Check columns show a tick/cross drawn as inline SVG (so no glyph depends on
the font) from the stored checks (Cryo-Cuff items 1/2/3 mapped per D10); a
NULL/unrecorded check prints blank. No HN or patient field is read.
"""

import html

import weasyprint

from app.services import report_pdf_service
from app.services.daily_report_service import FORM_ROWS_PER_PAGE, DailyEvent, DailyReport, format_date

FORM_TITLE = "แบบบันทึกการเบิก-จ่าย Equipment Pool"
KIND_TITLES = {"dispatch": "ส่งเครื่อง", "receipt": "รับเครื่อง"}
COL_ME_CODE = "ME.Code"
COL_PRIMARY_CHECK = "Primary Check"
COL_CHECKS = ["ตัวเครื่อง (หน้าจอไม่แตกร้าว)", "สายชาร์จ (สายไม่ขาด)", "Pole Clamp (ไม่แตกหัก,ไม่งอ)"]
COL_USER = {"dispatch": "ผู้รับเครื่อง ( User )", "receipt": "ผู้ส่งเครื่อง ( User )"}
COL_WARD = "Ward"
COL_BME = "ผู้ส่งเครื่อง ( BME )"
COL_TIME = "เวลา"
COL_NOTES = "หมายเหตุ"

_TICK = (
    '<svg class="chk chk-ok" viewBox="0 0 12 12" width="10" height="10"><title>✔</title>'
    '<path d="M1.5 6.5 L4.8 9.8 L10.5 2.5" fill="none" stroke="#000" stroke-width="1.6"/></svg>'
)
_CROSS = (
    '<svg class="chk chk-bad" viewBox="0 0 12 12" width="10" height="10"><title>✘</title>'
    '<path d="M2 2 L10 10 M10 2 L2 10" fill="none" stroke="#000" stroke-width="1.6"/></svg>'
)


def _e(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _check_cell(value: bool | None) -> str:
    return "" if value is None else (_TICK if value else _CROSS)


def _row_html(e: DailyEvent | None, kind: str) -> str:
    if e is None:
        return "<tr class='blank'>" + "<td></td>" * 9 + "</tr>"
    checks = "".join(
        f"<td class='c'>{_check_cell(e.checks.get(k))}</td>" for k in ("screen", "charger", "clamp")
    )
    return (
        f"<tr><td class='code'>{_e(e.bcm_code)}</td>{checks}"
        f"<td>{_e(e.contact_name)}</td><td>{_e(e.ward_name)}</td><td>{_e(e.operator_name)}</td>"
        f"<td class='c'>{e.local.strftime('%H:%M')}</td><td>{_e(e.notes)}</td></tr>"
    )


def _page_html(events: list[DailyEvent], kind: str, report: DailyReport, page: int, pages: int) -> str:
    padded: list[DailyEvent | None] = list(events) + [None] * (FORM_ROWS_PER_PAGE - len(events))
    head = (
        f"<thead><tr><th rowspan='2'>{COL_ME_CODE}</th><th colspan='3'>{COL_PRIMARY_CHECK}</th>"
        f"<th rowspan='2'>{COL_USER[kind]}</th><th rowspan='2'>{COL_WARD}</th>"
        f"<th rowspan='2'>{COL_BME}</th><th rowspan='2'>{COL_TIME}</th><th rowspan='2'>{COL_NOTES}</th></tr>"
        f"<tr>{''.join(f'<th class=sub>{c}</th>' for c in COL_CHECKS)}</tr></thead>"
    )
    cols = "".join(f"<col style='width:{w}%'>" for w in (12, 8, 8, 8, 15, 12, 14, 6, 17))
    body = "".join(_row_html(e, kind) for e in padded)
    return (
        "<section class='page'>"
        f"<h1>{FORM_TITLE}</h1><div class='meta'><span>{KIND_TITLES[kind]}</span>"
        f"<span>วันที่ {format_date(report.report_date)}</span><span>หน้า {page}/{pages}</span></div>"
        f"<table><colgroup>{cols}</colgroup>{head}<tbody>{body}</tbody></table></section>"
    )


def render_forms_html(report: DailyReport, kind: str) -> str:
    """``kind``: "dispatch", "receipt" or "both" (dispatch form then receipt form)."""
    kinds = ["dispatch", "receipt"] if kind == "both" else [kind]
    sections = []
    for k in kinds:
        events = [e for e in report.events if e.kind == k]
        chunks = [events[i : i + FORM_ROWS_PER_PAGE] for i in range(0, len(events), FORM_ROWS_PER_PAGE)] or [[]]
        for n, chunk in enumerate(chunks, start=1):
            sections.append(_page_html(chunk, k, report, n, len(chunks)))
    return f"""<!DOCTYPE html>
<html lang="th"><head><meta charset="utf-8"><style>
{report_pdf_service._FONT_FACE_CSS}
@page {{ size: A4 portrait; margin: 12mm 10mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: "Noto Sans Thai PDF", sans-serif; font-size: 8.5pt; color: #000; margin: 0; }}
.page {{ page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
h1 {{ font-weight: 700; font-size: 13pt; text-align: center; margin: 0 0 4pt 0; }}
.meta {{ display: flex; justify-content: space-between; font-weight: 700; margin-bottom: 4pt; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
thead {{ display: table-header-group; }}
th, td {{ border: 0.6pt solid #000; padding: 2pt 3pt; vertical-align: middle; overflow-wrap: anywhere; }}
th {{ font-weight: 700; text-align: center; font-size: 7.5pt; }}
th.sub {{ font-size: 6.5pt; }}
tbody tr {{ height: 8.6mm; page-break-inside: avoid; }}
td.c {{ text-align: center; }}
td.code {{ font-weight: 700; }}
.chk {{ vertical-align: middle; }}
</style></head><body>{"".join(sections)}</body></html>"""


def render_forms_pdf(report: DailyReport, kind: str) -> bytes:
    return weasyprint.HTML(string=render_forms_html(report, kind)).write_pdf()


async def render_forms_pdf_bounded(report: DailyReport, kind: str) -> bytes:
    """PR18 admission control (shared PDF semaphore, deadline, slot accounting)."""
    return await report_pdf_service.run_bounded(render_forms_pdf, report, kind)
