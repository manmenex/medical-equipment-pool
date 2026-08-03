"""Roadmap PR18D (docs/design/PR18_PRINTING_EXPORT_PLAN.md §10 "PDF
Strategy"): the backend PDF renderer. Turns an already-built
`app.schemas.report_export.ExportDocument` into PDF bytes using WeasyPrint
(a server-controlled HTML/CSS-to-PDF renderer, per design §10.2's
recommendation) -- this module owns no report/query/eligibility logic of its
own and never mutates the `ExportDocument` it is given.

Branding (design §16, interim neutral fallback -- Owner Decision #2 remains
open, not decided here): no hospital name, no department name, no logo. A
product-neutral Thai title (the document's own `metadata.display_name_th`,
the same value Browser Print already uses), "Medical Equipment Pool" as a
secondary label, and a neutral footer. Mirrors the presentational structure
of `frontend/src/components/print/PrintDocumentView.tsx` (Roadmap PR18C) so
Browser Print and PDF present the same information, but this module shares
no code with it -- the backend does not import frontend code.

Fonts: see `backend/app/assets/fonts/NOTICE.md` for why this renderer uses
its own merged static Noto Sans Thai TTF files (weights 400/700) instead of
the split `.woff2` files `frontend/public/fonts/` uses for Browser Print --
WeasyPrint 69.0 does not reliably render the split-file form. Both font
files are embedded into the generated HTML as base64 `data:` URIs (not
`file://` paths), so rendering never touches the filesystem or the network
at request time and can never silently fall back to a system font.
"""

import asyncio
import base64
import html
from datetime import date, datetime, timezone as _timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import weasyprint

from app.core.exceptions import PdfRenderTimeoutError
from app.schemas.report_export import ExportDocument, ExportValue, ExportValueType, ReportIdentity

# Roadmap PR18D review 4838921407 (H1): design §18 "Rendering has explicit
# time, memory, and concurrency bounds." `RENDER_TIMEOUT_SECONDS` bounds any
# single render; `MAX_CONCURRENT_RENDERS` bounds how many WeasyPrint renders
# this worker process admits at once, so a burst of large-report requests
# cannot pile up unboundedly many simultaneous CPU/memory-heavy renders.
# Both are deliberately generous-but-finite constants, not derived from
# MAX_EXPORT_ROWS -- layout/shaping cost is not a simple linear function of
# row count (design §18: "PDF rendering may require a smaller limit because
# layout cost scales with pages and font shaping").
RENDER_TIMEOUT_SECONDS = 30
MAX_CONCURRENT_RENDERS = 4
_render_semaphore = asyncio.Semaphore(MAX_CONCURRENT_RENDERS)

# Roadmap PR18C (design §9): "Receive and Issue default to landscape because
# of their wider transaction columns; Equipment Verify Checklist defaults to
# portrait" -- the same approved per-report-identity orientation Browser
# Print uses (frontend/src/utils/printFormat.ts's PRINT_ORIENTATION), not an
# independently invented PDF-only layout choice.
_PAGE_ORIENTATION: dict[ReportIdentity, str] = {
    ReportIdentity.RECEIVE_REPORT: "landscape",
    ReportIdentity.ISSUE_REPORT: "landscape",
    ReportIdentity.EQUIPMENT_VERIFY_CHECKLIST: "portrait",
}

_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _font_data_uri(filename: str) -> str:
    font_bytes = (_FONTS_DIR / filename).read_bytes()
    encoded = base64.b64encode(font_bytes).decode("ascii")
    return f"data:font/ttf;base64,{encoded}"


# Built once at import time, not per request -- the font files never change
# at runtime, so re-reading and re-encoding ~140 KB of font data on every
# PDF generation would be pure waste.
_FONT_FACE_CSS = f"""
@font-face {{
  font-family: "Noto Sans Thai PDF";
  font-style: normal;
  font-weight: 400;
  src: url("{_font_data_uri("NotoSansThai-Regular.ttf")}") format("truetype");
}}
@font-face {{
  font-family: "Noto Sans Thai PDF";
  font-style: normal;
  font-weight: 700;
  src: url("{_font_data_uri("NotoSansThai-Bold.ttf")}") format("truetype");
}}
"""


def _format_datetime_in_timezone(value: datetime, timezone_name: str) -> str:
    """Mirrors `frontend/src/utils/printFormat.ts`'s
    `formatDateTimeInTimezone` -- the same "YYYY-MM-DD HH:MM" 24-hour
    Gregorian rendering in the document's own declared timezone, no
    Buddhist-calendar conversion (design note in PrintDocumentView.tsx)."""
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone = _timezone.utc
    localized = value.astimezone(zone)
    return localized.strftime("%Y-%m-%d %H:%M")


def _format_value(value: ExportValue, value_type: ExportValueType, *, timezone_name: str) -> str:
    """Mirrors `frontend/src/utils/printFormat.ts`'s `formatPrintValue` --
    the exact same per-type rendering rules, so a PDF cell and its Browser
    Print equivalent never disagree on how a value is displayed."""
    if value is None:
        return "-"
    if value_type == "boolean":
        return "ใช่" if value else "ไม่ใช่"
    if value_type == "datetime" and isinstance(value, datetime):
        return _format_datetime_in_timezone(value, timezone_name)
    if value_type == "date" and isinstance(value, date):
        return value.isoformat()
    return str(value)


def _e(value: str) -> str:
    """Shorthand for `html.escape` -- every piece of dynamic text placed
    into the generated HTML (Thai display names, filter values,
    master-data-resolved names, cell values) must be escaped; none of it is
    developer-authored markup."""
    return html.escape(value, quote=True)


def _render_html(document: ExportDocument) -> str:
    metadata = document.metadata
    orientation = _PAGE_ORIENTATION[metadata.report_identity]
    generated_at_display = _format_datetime_in_timezone(metadata.generated_at, metadata.timezone)

    filters_html = ""
    if metadata.applied_filters:
        items = "".join(
            f"<li><span class='label'>{_e(f.label_th)}: </span>{_e(f.value)}</li>" for f in metadata.applied_filters
        )
        filters_html = f"""
        <section class="filters">
          <h2>ตัวกรองที่ใช้</h2>
          <ul>{items}</ul>
        </section>
        """

    if document.rows:
        header_cells = "".join(f"<th>{_e(c.label_th)}</th>" for c in document.columns)
        body_rows = []
        for row in document.rows:
            cells = "".join(
                f"<td>{_e(_format_value(row.values[c.key], c.value_type, timezone_name=metadata.timezone))}</td>"
                for c in document.columns
            )
            body_rows.append(f"<tr>{cells}</tr>")
        table_html = f"""
        <table>
          <thead><tr>{header_cells}</tr></thead>
          <tbody>{"".join(body_rows)}</tbody>
        </table>
        """
    else:
        table_html = '<p class="empty">ไม่พบข้อมูลตามตัวกรองที่เลือก</p>'

    return f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<style>
{_FONT_FACE_CSS}
@page {{
  size: A4 {orientation};
  margin: 15mm 12mm;
}}
* {{ box-sizing: border-box; }}
body {{
  font-family: "Noto Sans Thai PDF", sans-serif;
  font-weight: 400;
  font-size: 10pt;
  color: #1e293b;
  margin: 0;
}}
header {{ margin-bottom: 10pt; }}
header .secondary-label {{ font-size: 8pt; color: #64748b; margin: 0 0 2pt 0; }}
header h1 {{ font-weight: 700; font-size: 15pt; margin: 0; }}
.meta {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 2pt 12pt;
  font-size: 8pt;
  color: #334155;
  margin-bottom: 10pt;
}}
.meta .label {{ color: #64748b; }}
.filters {{
  border: 1px solid #e2e8f0;
  border-radius: 4pt;
  padding: 6pt 8pt;
  font-size: 8pt;
  margin-bottom: 10pt;
}}
.filters h2 {{ font-weight: 700; font-size: 8pt; margin: 0 0 3pt 0; }}
.filters ul {{ list-style: none; margin: 0; padding: 0; columns: 3; }}
.filters .label {{ color: #64748b; }}
.row-count {{ font-size: 8pt; color: #64748b; margin: 0 0 6pt 0; }}
.empty {{
  border: 1px dashed #cbd5e1;
  border-radius: 4pt;
  padding: 16pt;
  text-align: center;
  font-size: 9pt;
  color: #64748b;
}}
table {{ width: 100%; border-collapse: collapse; font-size: 8pt; }}
th, td {{
  border: 1px solid #e2e8f0;
  padding: 3pt 4pt;
  text-align: left;
  vertical-align: top;
}}
th {{ font-weight: 700; background-color: #f1f5f9; }}
tr {{ break-inside: avoid; }}
thead {{ display: table-header-group; }}
footer {{
  margin-top: 10pt;
  border-top: 1px solid #e2e8f0;
  padding-top: 4pt;
  font-size: 7pt;
  color: #94a3b8;
}}
</style>
</head>
<body>
<header>
  <p class="secondary-label">Medical Equipment Pool</p>
  <h1>{_e(metadata.display_name_th)}</h1>
</header>
<section class="meta">
  <div><span class="label">สร้างเมื่อ: </span>{_e(generated_at_display)} ({_e(metadata.timezone)})</div>
  <div><span class="label">สร้างโดย: </span>{_e(metadata.generated_by_display_name)}</div>
  <div><span class="label">รหัสรายงาน: </span>{_e(metadata.report_identity.value)}</div>
  <div><span class="label">เวอร์ชันเอกสาร: </span>{_e(metadata.template_version)}</div>
</section>
{filters_html}
<p class="row-count">พบทั้งหมด {metadata.row_count} รายการ</p>
{table_html}
<footer>
  {_e(metadata.report_identity.value)} &middot; เวอร์ชันเอกสาร {_e(metadata.template_version)} &middot;
  สร้างเมื่อ {_e(generated_at_display)} ({_e(metadata.timezone)})
</footer>
</body>
</html>
"""


def render_pdf(document: ExportDocument) -> bytes:
    """Renders one `ExportDocument` to PDF bytes. CPU-bound and synchronous
    by design -- callers must run this via `asyncio.to_thread` (or an
    equivalent executor) so it never blocks the event loop, exactly as
    `app.services.import_service._parse_workbook_sync` already does for its
    own CPU-bound work.

    Never reads from the filesystem or the network beyond the two embedded
    font files loaded at import time -- `weasyprint.HTML(string=...)` is
    given a complete, self-contained HTML document with every font and
    every value already inlined, so no `base_url` and no external
    `url_fetcher` is needed or configured.
    """
    html_document = _render_html(document)
    return weasyprint.HTML(string=html_document).write_pdf()


def _release_render_slot_when_done(task: "asyncio.Task[bytes]") -> None:
    """Roadmap PR18D review 4838921407 round 2 (H1): the semaphore models
    *renderer* concurrency, not *request* concurrency -- this callback is
    the only place `_render_semaphore` is released, and it only ever runs
    once the underlying `asyncio.to_thread(render_pdf, ...)` task has
    actually finished (successfully, or with an exception), never merely
    because a caller's `wait_for` gave up waiting on it. Retrieving the
    task's exception (if any) here, even though nothing further is done
    with it, prevents asyncio's "Task exception was never retrieved"
    warning for a render that finishes after its caller already received
    `PdfRenderTimeoutError`."""
    if not task.cancelled():
        task.exception()
    _render_semaphore.release()


async def render_pdf_bounded(document: ExportDocument) -> bytes:
    """Roadmap PR18D review 4838921407 (H1, corrected in round 2): the one,
    single call site that enforces design §18's time and concurrency
    bounds around `render_pdf` -- `render_pdf` itself stays a plain,
    directly-unit-testable synchronous function; callers (the API route)
    must call this wrapper, never `asyncio.to_thread(render_pdf, ...)`
    directly, so no call site can accidentally run an unbounded render.

    Deterministic timeout handling: a render that has not completed within
    `RENDER_TIMEOUT_SECONDS` raises `PdfRenderTimeoutError` (a `DomainError`
    -> structured `503` response) rather than hanging the request
    indefinitely. `asyncio.wait_for`'s cancellation cannot forcibly stop a
    thread already running in the default executor (a `ThreadPoolExecutor`
    thread cannot be killed from the outside in Python) -- the render
    already in flight keeps running to completion on its own rather than
    being interrupted mid-render. This is the accepted, explicitly
    documented bound for this thread-based renderer, consistent with this
    repository's existing CPU-bound-work pattern
    (`app.services.import_service`); a hard, immediate kill would require a
    subprocess-based renderer, which is not introduced here.

    Bounded concurrency that reflects *actual renderer execution*, not
    request lifetime (review round 2's correction): the render itself runs
    as its own `asyncio.Task` (`render_task` below), started only after
    `_render_semaphore` is acquired. `asyncio.wait_for` wraps
    `asyncio.shield(render_task)`, so when the timeout elapses,
    `wait_for` only cancels its own internal wrapper -- `render_task`
    itself is shielded and keeps running in the background exactly as it
    would have without the timeout. The semaphore is released solely by
    `render_task`'s own done-callback (`_release_render_slot_when_done`),
    so a request that times out from the *caller's* perspective does not
    free the slot until the renderer has *actually* finished -- a 5th
    concurrent request genuinely waits behind 4 slow-but-still-running
    renders, never just behind 4 requests that already returned an error
    to their callers. `render_pdf` holds no external resource of its own
    (no temp file, no open connection or socket; the HTML document it
    builds is one self-contained in-memory string with both fonts already
    embedded), so accounting for the slot correctly is the entire cleanup
    obligation here -- there is nothing else to tear down.
    """
    await _render_semaphore.acquire()
    try:
        render_task: "asyncio.Task[bytes]" = asyncio.ensure_future(asyncio.to_thread(render_pdf, document))
    except BaseException:
        # Task creation itself failed before any renderer work could start
        # -- nothing for the done-callback to ever fire for, so release the
        # slot directly here instead of leaking it.
        _render_semaphore.release()
        raise
    render_task.add_done_callback(_release_render_slot_when_done)

    try:
        return await asyncio.wait_for(asyncio.shield(render_task), timeout=RENDER_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        raise PdfRenderTimeoutError(
            f"PDF rendering did not complete within {RENDER_TIMEOUT_SECONDS} seconds. "
            "Narrow the applied filters and try again."
        ) from exc
