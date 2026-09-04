import asyncio
import io
import threading
import time
import uuid
from datetime import datetime, timezone

import pdfplumber
import pytest
from sqlalchemy import func, select

from app.core.exceptions import PdfRenderTimeoutError
from app.models.audit import AuditLog
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.schemas.report_export import (
    ExportColumn,
    ExportDocument,
    ExportFilterSummary,
    ExportMetadata,
    ExportRow,
    ReportIdentity,
)
from app.services import report_export_service, report_pdf_service
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

# ---------------------------------------------------------------------------
# Roadmap PR18D (docs/design/PR18_PRINTING_EXPORT_PLAN.md §10, §16): unit
# tests for app.services.report_pdf_service (the WeasyPrint HTML/CSS-to-PDF
# adapter) and API tests for GET /reports/{report_id}/pdf. No text is
# asserted only by "starts with %PDF" -- every content assertion below opens
# the generated PDF with pdfplumber and inspects extracted text and/or
# per-character embedded-font data.
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 7, 31, 3, 15, 0, tzinfo=timezone.utc)

# The exact realistic mixed Thai/Latin sentence that reproduced silent
# glyph-substitution corruption with the frontend's split-by-unicode-range
# `.woff2` assets under WeasyPrint 69.0 (a Latin 'a' rendered/extracted as
# Thai 'พ', U+0E1E) during PR18D's pre-implementation font investigation.
# The merged static TTF assets this module uses must render it correctly.
_CORRUPTION_REGRESSION_SENTENCE = "รายงานการรับคืนครุภัณฑ์ทางการแพทย์ 0123456789 ABCabc"


def _document(*, rows: list[ExportRow] | None = None, columns: list[ExportColumn] | None = None) -> ExportDocument:
    columns = columns if columns is not None else [ExportColumn(key="note", label_th="หมายเหตุ", value_type="string")]
    rows = rows if rows is not None else []
    return ExportDocument(
        metadata=ExportMetadata(
            report_identity=ReportIdentity.RECEIVE_REPORT,
            display_name_th="รายงานการรับคืน",
            template_version="1",
            generated_at=_FIXED_NOW,
            generated_by_display_name="ผู้ทดสอบ",
            generated_by_user_id="00000000-0000-0000-0000-000000000001",
            timezone="Asia/Bangkok",
            applied_filters=[ExportFilterSummary(label_th="หอผู้ป่วย", value="ICU ทดสอบ")],
            row_count=len(rows),
            filename_stem="receive-report_all_all_20260731T031500Z",
        ),
        columns=columns,
        rows=rows,
    )


def _open(pdf_bytes: bytes):
    assert pdf_bytes.startswith(b"%PDF")
    return pdfplumber.open(io.BytesIO(pdf_bytes))


# ---------------------------------------------------------------------------
# Unit tests: app.services.report_pdf_service.render_pdf
# ---------------------------------------------------------------------------


def test_render_pdf_produces_a_valid_single_page_pdf():
    document = _document(rows=[ExportRow(values={"note": "x"})])
    pdf_bytes = report_pdf_service.render_pdf(document)
    with _open(pdf_bytes) as pdf:
        assert len(pdf.pages) >= 1


def test_render_pdf_embeds_both_font_weights_not_a_system_fallback():
    """The document title is rendered at weight 700, the body at 400 --
    both embedded font subsets must come from this module's own Noto Sans
    Thai PDF font-face, never an unrelated system font name."""
    document = _document(rows=[ExportRow(values={"note": "ข้อมูลทดสอบ"})])
    pdf_bytes = report_pdf_service.render_pdf(document)
    with _open(pdf_bytes) as pdf:
        fontnames = {ch["fontname"] for ch in pdf.pages[0].chars}
    assert fontnames, "expected at least one embedded glyph on the page"
    for fontname in fontnames:
        assert "Noto-Sans-Thai-PDF" in fontname, f"unexpected font (possible system fallback): {fontname}"
    # A genuine PDF font subset uses the "XXXXXX+FontName" tag convention --
    # this rules out an un-subsetted/full system font masquerading under a
    # similar name.
    assert any("+Noto-Sans-Thai-PDF" in f and not f.endswith("-Bold") for f in fontnames)
    assert any("Bold" in f for f in fontnames)


def _data_row_cell_chars(pdf, *, row_index: int = 1, col_index: int = 0):
    """Crops to one table data cell's bounding box (via pdfplumber's
    ruling-line table detection, which finds our CSS-bordered `<table>`
    cleanly) and returns only the glyphs inside it, in PDF content-stream
    order. Scoping to one cell is what makes a per-glyph corruption check
    possible on a full document -- the page header/meta/filters/footer
    around the table would otherwise contaminate a whole-page character
    scan with their own, unrelated ASCII/Thai text."""
    page = pdf.pages[0]
    table = page.find_tables()[0]
    cell_bbox = table.rows[row_index].cells[col_index]
    return page.crop(cell_bbox).chars


def _all_cell_texts(pdf) -> set[str]:
    """Every table cell's text, reconstructed by reading glyphs in PDF
    content-stream order within each cell's own cropped bounding box
    (including re-joining a value that line-wrapped inside a narrow
    column, e.g. "AST-\\nPR18D-0003" -- see the word-wrapping note in
    `test_pdf_receive_report_contains_seeded_asset_number` below).

    Deliberately not `page.extract_table()`'s own cell strings or
    `page.extract_text()`: both apply pdfplumber's x-position-based word/
    line reconstruction, which can reorder a Thai combining mark relative
    to its base consonant (e.g. rendering "พร้อมใช้งาน" back as
    "พรอ้ มใชง้ าน") even when the underlying PDF content stream -- and the
    rendered glyphs themselves -- are correct. Reading `.chars` directly
    in stream order avoids that extraction-only artifact."""
    page = pdf.pages[0]
    table = page.find_tables()[0]
    cell_texts = set()
    for row in table.rows:
        for cell_bbox in row.cells:
            if cell_bbox is None:
                continue
            chars = page.crop(cell_bbox).chars
            cell_texts.add("".join(ch["text"] for ch in chars).replace("\n", ""))
    return cell_texts


def test_render_pdf_renders_mixed_thai_latin_text_without_glyph_corruption():
    """Regression test for the pre-implementation finding: WeasyPrint 69.0
    silently substitutes wrong glyphs when a Thai/Latin font is split across
    two files via `unicode-range` and the text contains enough distinct Thai
    glyphs. This module's merged single-file-per-weight fonts must not
    reproduce it."""
    document = _document(
        columns=[ExportColumn(key="text", label_th="ข้อความ", value_type="string")],
        rows=[ExportRow(values={"text": _CORRUPTION_REGRESSION_SENTENCE})],
    )
    pdf_bytes = report_pdf_service.render_pdf(document)
    with _open(pdf_bytes) as pdf:
        chars = _data_row_cell_chars(pdf)

    # The cell's glyphs, read back in content-stream order, must
    # reconstruct the exact input sentence -- any wrong-glyph substitution
    # (the observed failure: a Latin 'a' drawn as Thai 'พ') would break this.
    assert "".join(ch["text"] for ch in chars) == _CORRUPTION_REGRESSION_SENTENCE

    # Belt-and-suspenders per-character-class check: every ASCII glyph in
    # the cell must be one of the sentence's own ASCII characters, and every
    # Thai-block glyph must be one of its own Thai characters.
    expected_ascii = set(c for c in _CORRUPTION_REGRESSION_SENTENCE if c.isascii())
    ascii_chars_found = {ch["text"] for ch in chars if ch["text"].isascii() and ch["text"].strip()}
    assert ascii_chars_found, "expected at least one ASCII glyph in the cell"
    assert ascii_chars_found <= expected_ascii, f"unexpected ASCII glyph substitution: {ascii_chars_found - expected_ascii}"

    expected_thai = set(c for c in _CORRUPTION_REGRESSION_SENTENCE if "ก" <= c <= "๛")
    thai_chars_found = {ch["text"] for ch in chars if "ก" <= ch["text"] <= "๛"}
    assert thai_chars_found, "expected at least one Thai glyph in the cell"
    assert thai_chars_found <= expected_thai, f"unexpected Thai glyph substitution: {thai_chars_found - expected_thai}"


def test_render_pdf_uses_landscape_for_transaction_reports_and_portrait_for_checklist():
    receive_doc = _document()
    checklist_metadata = receive_doc.metadata.model_copy(
        update={"report_identity": ReportIdentity.EQUIPMENT_VERIFY_CHECKLIST}
    )
    checklist_doc = receive_doc.model_copy(update={"metadata": checklist_metadata})

    with _open(report_pdf_service.render_pdf(receive_doc)) as pdf:
        landscape_box = pdf.pages[0].mediabox
    with _open(report_pdf_service.render_pdf(checklist_doc)) as pdf:
        portrait_box = pdf.pages[0].mediabox

    landscape_width, landscape_height = landscape_box[2] - landscape_box[0], landscape_box[3] - landscape_box[1]
    portrait_width, portrait_height = portrait_box[2] - portrait_box[0], portrait_box[3] - portrait_box[1]
    assert landscape_width > landscape_height
    assert portrait_height > portrait_width


def test_render_pdf_empty_result_set_does_not_crash_and_shows_no_results_message():
    document = _document(rows=[])
    pdf_bytes = report_pdf_service.render_pdf(document)
    with _open(pdf_bytes) as pdf:
        chars_found = {ch["text"] for ch in pdf.pages[0].chars}
    # A per-character presence check (not an ordered substring match) --
    # pdfplumber's `extract_text()` can reorder Thai combining marks
    # relative to their base consonant when reconstructing lines, which
    # would make an ordered substring assertion flaky independent of
    # whether rendering itself is correct.
    assert set("ไม่พบข้อมูลตามตัวกรองที่เลือก") <= chars_found


def test_render_pdf_neutral_branding_no_hospital_name_or_logo():
    """Design §16 interim neutral fallback: "Medical Equipment Pool" is the
    only secondary label, and the Thai title is the document's own
    report-specific display name -- render_pdf must not add any additional
    identity string of its own."""
    document = _document()
    pdf_bytes = report_pdf_service.render_pdf(document)
    with _open(pdf_bytes) as pdf:
        text = pdf.pages[0].extract_text() or ""
        chars_found = {ch["text"] for ch in pdf.pages[0].chars}
    assert "Medical Equipment Pool" in text
    # Per-character presence, not an ordered substring match -- pdfplumber's
    # `extract_text()` can reorder Thai combining marks relative to their
    # base consonant, which would make an ordered substring assertion flaky
    # independent of whether rendering itself is correct (see the per-glyph
    # corruption test above for the authoritative ordered check).
    assert set(document.metadata.display_name_th) <= chars_found


def test_render_pdf_escapes_html_special_characters_in_values():
    """A master-data-resolved display value is administrator-entered free
    text, not developer-authored markup -- it must never be interpreted as
    HTML. Proven two ways: (1) the literal special characters themselves are
    drawn as glyphs (if `<b>` had been parsed as a real tag, no literal '<'
    or '>' glyph would ever reach the page), and (2) the cell's full text,
    reassembled in content-stream order, is byte-for-byte the original
    input -- if any of it had been interpreted as markup, the two closing
    tag characters and the wrapped word would not appear together in that
    exact form."""
    raw_value = "<b>ทดสอบ</b> & \"quoted\""
    document = _document(
        columns=[ExportColumn(key="note", label_th="หมายเหตุ", value_type="string")],
        rows=[ExportRow(values={"note": raw_value})],
    )
    pdf_bytes = report_pdf_service.render_pdf(document)
    with _open(pdf_bytes) as pdf:
        cell_chars = _data_row_cell_chars(pdf)

    reassembled = "".join(ch["text"] for ch in cell_chars)
    assert reassembled == raw_value

    literal_special_chars_found = {ch["text"] for ch in cell_chars if ch["text"] in "<>&\""}
    assert literal_special_chars_found == {"<", ">", "&", '"'}


# ---------------------------------------------------------------------------
# Unit tests: app.services.report_pdf_service.render_pdf_bounded -- design
# §18's explicit time/concurrency bounds (Roadmap PR18D review 4838921407,
# H1).
# ---------------------------------------------------------------------------


async def test_render_pdf_bounded_raises_structured_timeout_error(monkeypatch):
    """A render that does not complete within RENDER_TIMEOUT_SECONDS must
    fail deterministically with the dedicated domain error, not hang the
    request indefinitely."""

    def _slow_render(document):
        time.sleep(0.2)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(report_pdf_service, "render_pdf", _slow_render)
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(PdfRenderTimeoutError):
        await report_pdf_service.render_pdf_bounded(_document())


async def test_render_pdf_bounded_succeeds_within_timeout(monkeypatch):
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 30)
    pdf_bytes = await report_pdf_service.render_pdf_bounded(_document(rows=[ExportRow(values={"note": "x"})]))
    assert pdf_bytes.startswith(b"%PDF")


async def test_render_pdf_bounded_limits_concurrent_renders(monkeypatch):
    """The module-level semaphore must cap how many renders run at once --
    proven by tracking the actual number of simultaneously-running renders
    across a burst of concurrent calls."""
    active = 0
    max_active = 0
    count_lock = threading.Lock()

    def _tracking_render(document):
        nonlocal active, max_active
        with count_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.1)
        with count_lock:
            active -= 1
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(report_pdf_service, "render_pdf", _tracking_render)
    monkeypatch.setattr(report_pdf_service, "_render_semaphore", asyncio.Semaphore(2))

    document = _document()
    await asyncio.gather(*[report_pdf_service.render_pdf_bounded(document) for _ in range(6)])

    assert max_active <= 2


async def test_render_pdf_bounded_releases_semaphore_slot_after_timeout(monkeypatch):
    """H1 "cleanup after timeout/failure": a timed-out render must not
    permanently consume its concurrency slot -- the next render must still
    be admitted, once the original render actually finishes."""
    call_count = 0

    def _slow_render(document):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            time.sleep(0.2)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(report_pdf_service, "render_pdf", _slow_render)
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(report_pdf_service, "_render_semaphore", asyncio.Semaphore(1))

    document = _document()
    with pytest.raises(PdfRenderTimeoutError):
        await report_pdf_service.render_pdf_bounded(document)

    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 30)
    pdf_bytes = await report_pdf_service.render_pdf_bounded(document)
    assert pdf_bytes.startswith(b"%PDF")


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.01) -> None:
    """Polls `predicate` until it is true or `timeout` elapses. Used instead
    of a fixed `asyncio.sleep` wherever a test needs to observe an
    asyncio-scheduled side effect (like a `Task` done-callback) without
    racing a hardcoded delay."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")


# ---------------------------------------------------------------------------
# Roadmap PR18D review 4838921407 round 2 (H1): the concurrency limit must
# reflect *actual renderer execution*, never request lifetime -- releasing
# a semaphore slot the moment a caller's `wait_for` times out (the round 1
# bug) lets a "timed out" render keep consuming a real OS thread/CPU/memory
# in the background while a brand-new render is admitted on top of it,
# silently exceeding the configured bound. These tests use a
# `threading.Event` gate instead of `time.sleep` so the underlying render
# is provably still running (not just "probably still running due to
# timing") at the moment each assertion executes.
# ---------------------------------------------------------------------------


async def test_render_pdf_bounded_timeout_does_not_release_capacity_early(monkeypatch):
    """Direct proof of the round 2 correction: immediately after a render
    times out from the caller's perspective, the semaphore must still show
    the slot as held -- not freed -- because the underlying render has not
    actually finished yet."""
    release_gate = threading.Event()
    started = threading.Event()

    def _blocking_render(document):
        started.set()
        release_gate.wait(timeout=5)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(report_pdf_service, "render_pdf", _blocking_render)
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 0.05)
    test_semaphore = asyncio.Semaphore(2)
    monkeypatch.setattr(report_pdf_service, "_render_semaphore", test_semaphore)

    with pytest.raises(PdfRenderTimeoutError):
        await report_pdf_service.render_pdf_bounded(_document())

    assert started.is_set(), "the render should have actually started before the timeout fired"
    # Started with 2 slots; exactly one must still be held by the
    # still-running (from the renderer's perspective) render.
    assert test_semaphore._value == 1, "the slot must remain held after a caller-facing timeout, not be freed early"

    # Only once the render is allowed to actually finish does the slot free up.
    release_gate.set()
    await _wait_until(lambda: test_semaphore._value == 2)


async def test_render_pdf_bounded_timeout_does_not_increase_effective_concurrency(monkeypatch):
    """A burst of requests that all time out from the caller's perspective
    must not be able to start more simultaneous renders than
    `_render_semaphore` allows -- proven by tracking the real number of
    concurrently-running (not-yet-returned-from-`render_pdf`) renders while
    every one of them "times out" for its own caller almost immediately."""
    active = 0
    max_active = 0
    count_lock = threading.Lock()
    release_gate = threading.Event()

    def _tracking_blocking_render(document):
        nonlocal active, max_active
        with count_lock:
            active += 1
            max_active = max(max_active, active)
        release_gate.wait(timeout=5)
        with count_lock:
            active -= 1
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(report_pdf_service, "render_pdf", _tracking_blocking_render)
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(report_pdf_service, "_render_semaphore", asyncio.Semaphore(2))

    document = _document()

    async def _one_timed_out_call():
        with pytest.raises(PdfRenderTimeoutError):
            await report_pdf_service.render_pdf_bounded(document)

    # 6 requests "arrive" close together; each one times out for its own
    # caller almost immediately (0.02s), but the underlying renders they
    # started keep running (blocked on release_gate) until explicitly
    # released below.
    await asyncio.gather(*[_one_timed_out_call() for _ in range(6)])

    release_gate.set()
    await _wait_until(lambda: active == 0)

    assert max_active <= 2, (
        f"effective concurrent renders ({max_active}) exceeded the configured limit (2) -- "
        "a caller-facing timeout must never let a new render start on top of one still running"
    )


# ---------------------------------------------------------------------------
# Roadmap PR18D review round 3: `RENDER_TIMEOUT_SECONDS` must be one total
# budget covering *both* the wait for renderer capacity and the active
# render, not a budget that only starts once a slot is acquired -- a
# request stuck behind other renders must not be able to queue
# indefinitely and only then get its own full render timeout on top.
# ---------------------------------------------------------------------------


async def test_render_pdf_bounded_times_out_while_queued_for_capacity_without_starting_renderer(monkeypatch):
    """Requirements 1 and 2: a request that never gets a chance to acquire
    the renderer semaphore before its total timeout budget elapses must
    still raise the structured timeout error -- and `render_pdf` must never
    have been invoked on its behalf, because it never got a slot."""
    render_call_count = 0
    hold_gate = threading.Event()
    occupier_started = threading.Event()

    def _holding_render(document):
        nonlocal render_call_count
        render_call_count += 1
        occupier_started.set()
        hold_gate.wait(timeout=5)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(report_pdf_service, "render_pdf", _holding_render)
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(report_pdf_service, "_render_semaphore", asyncio.Semaphore(1))

    document = _document()

    # Occupies the single slot for far longer than the timeout budget, so
    # a second request has no capacity available for the whole time it's
    # allowed to wait.
    occupier_task = asyncio.ensure_future(report_pdf_service.render_pdf_bounded(document))
    await _wait_until(lambda: occupier_started.is_set())

    with pytest.raises(PdfRenderTimeoutError):
        await report_pdf_service.render_pdf_bounded(document)

    assert render_call_count == 1, "the queue-timeout request's renderer must never have been started"

    hold_gate.set()
    with pytest.raises(PdfRenderTimeoutError):
        await occupier_task


async def test_render_pdf_bounded_queue_wait_plus_render_never_exceeds_total_budget(monkeypatch):
    """Requirement 3: however long a request spends queued, the point at
    which it fails (or succeeds) must never be later than
    `RENDER_TIMEOUT_SECONDS` after the request began -- queue wait and
    active render share one clock, they do not each get their own."""
    hold_gate = threading.Event()
    occupier_started = threading.Event()
    timeout_budget = 0.1

    def _holding_render(document):
        occupier_started.set()
        hold_gate.wait(timeout=5)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(report_pdf_service, "render_pdf", _holding_render)
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", timeout_budget)
    monkeypatch.setattr(report_pdf_service, "_render_semaphore", asyncio.Semaphore(1))

    document = _document()
    occupier_task = asyncio.ensure_future(report_pdf_service.render_pdf_bounded(document))
    await _wait_until(lambda: occupier_started.is_set())

    started_at = time.monotonic()
    with pytest.raises(PdfRenderTimeoutError):
        await report_pdf_service.render_pdf_bounded(document)
    elapsed = time.monotonic() - started_at

    # Generous scheduling slack for a shared test-runner CPU -- the point
    # is that this is bounded by the configured budget, not that it never
    # completed at all (which an unbounded queue wait would also satisfy).
    assert elapsed <= timeout_budget + 0.3, (
        f"queue wait + render took {elapsed:.3f}s, exceeding the {timeout_budget}s total timeout budget"
    )

    hold_gate.set()
    with pytest.raises(PdfRenderTimeoutError):
        await occupier_task


async def test_render_pdf_bounded_acquires_capacity_and_renders_within_deadline_succeeds(monkeypatch):
    """Requirement 6: a request that acquires renderer capacity well within
    its total budget, and whose render also finishes in time, must succeed
    normally -- the total-deadline accounting must not make an otherwise
    healthy request fail."""
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(report_pdf_service, "_render_semaphore", asyncio.Semaphore(2))

    document = _document(rows=[ExportRow(values={"note": "x"})])
    pdf_bytes = await report_pdf_service.render_pdf_bounded(document)
    assert pdf_bytes.startswith(b"%PDF")


async def test_render_pdf_bounded_concurrent_requests_never_exceed_configured_limit(monkeypatch):
    """End-to-end proof combining normal completions and timeouts in the
    same burst: whatever the individual outcome, the real number of
    simultaneously-executing renders must never exceed the configured
    limit."""
    active = 0
    max_active = 0
    count_lock = threading.Lock()

    def _tracking_render(document):
        nonlocal active, max_active
        with count_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.08)
        with count_lock:
            active -= 1
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(report_pdf_service, "render_pdf", _tracking_render)
    monkeypatch.setattr(report_pdf_service, "RENDER_TIMEOUT_SECONDS", 30)
    monkeypatch.setattr(report_pdf_service, "_render_semaphore", asyncio.Semaphore(3))

    document = _document()
    results = await asyncio.gather(*[report_pdf_service.render_pdf_bounded(document) for _ in range(9)])

    assert all(r.startswith(b"%PDF") for r in results)
    assert max_active <= 3


# ---------------------------------------------------------------------------
# API tests: GET /reports/{report_id}/pdf
# ---------------------------------------------------------------------------


async def _create_equipment(client, headers, asset_number: str, *, equipment_name: str = "Infusion Pump"):
    resp = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": asset_number, "equipment_name": equipment_name}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _dispatch(client, headers, equipment_id: str, ward_id: str):
    resp = await client.post(
        "/api/v1/borrow",
        headers=headers,
        json={"equipment_id": equipment_id, "ward_id": ward_id, "dispatch_type": "on_demand"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _receive(client, headers, transaction_id: str):
    resp = await client.post(
        f"/api/v1/return/{transaction_id}", headers=headers, json={"receipt_outcome": "usable"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_pdf_authorized_roles_succeed(client, seeded_users):
    for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await client.get("/api/v1/reports/receive-report/pdf", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")


async def test_pdf_unauthenticated_rejected_with_401(client, seeded_users):
    resp = await client.get("/api/v1/reports/receive-report/pdf")
    assert resp.status_code == 401, resp.text


async def test_pdf_unsupported_report_id_rejected(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/not-a-real-report/pdf", headers=admin)
    assert resp.status_code == 422, resp.text


async def test_pdf_reverse_business_date_range_rejected(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/receive-report/pdf",
        headers=admin,
        params={"business_date_from": "2026-07-15", "business_date_to": "2026-07-01"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_pdf_rejects_inapplicable_filter(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/receive-report/pdf", headers=admin, params={"dispatch_type": "on_demand"}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_pdf_content_disposition_filename_is_ascii_safe_and_ends_with_pdf(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/equipment-verify-checklist/pdf", headers=admin)
    assert resp.status_code == 200, resp.text
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="equipment-verify-checklist_')
    assert disposition.endswith('.pdf"')
    filename = disposition.split('filename="')[1].rstrip('"')
    assert filename.encode("ascii")  # raises if not ASCII-safe


async def test_pdf_row_limit_exceeded_returns_structured_error_not_a_pdf(monkeypatch, client, seeded_users):
    monkeypatch.setattr(report_export_service, "MAX_EXPORT_ROWS", 0)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18D-1")
    eq = await _create_equipment(client, admin, "AST-PR18D-0001")
    await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get("/api/v1/reports/issue-report/pdf", headers=admin, params={"ward_id": ward_id})
    assert resp.status_code == 422, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["code"] == "EXPORT_TOO_LARGE"


async def test_pdf_does_not_mutate_transaction_state(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18D-2")
    eq = await _create_equipment(client, admin, "AST-PR18D-0002")
    tx = await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get("/api/v1/reports/issue-report/pdf", headers=admin, params={"ward_id": ward_id})
    assert resp.status_code == 200, resp.text

    row = (
        await db_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx["id"])))
    ).scalar_one()
    assert row.returned_at is None


async def test_pdf_does_not_write_persistent_audit_log(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    before = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()

    resp = await client.get("/api/v1/reports/receive-report/pdf", headers=admin)
    assert resp.status_code == 200, resp.text

    after = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert after == before


async def test_pdf_receive_report_contains_seeded_asset_number(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18D-3", "หอผู้ป่วยทดสอบ PR18D")
    eq = await _create_equipment(client, admin, "AST-PR18D-0003")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, staff, tx["id"])

    resp = await client.get(
        "/api/v1/reports/receive-report/pdf", headers=admin, params={"ward_id": ward_id}
    )
    assert resp.status_code == 200, resp.text
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        # A narrow column in a busy landscape table can wrap a value across
        # two rendered lines (e.g. "AST-PR18D-0003" wrapping after the
        # hyphen) -- the same `word-break` layout behavior Browser Print
        # already has for long codes in narrow columns, not a defect.
        # `_all_cell_texts` re-joins a cell's own wrapped lines back
        # together via stream-order glyph reading.
        cell_values = _all_cell_texts(pdf)
    assert "AST-PR18D-0003" in cell_values


async def test_pdf_equipment_verify_checklist_contains_thai_status_label(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment(client, admin, "AST-PR18D-0004")

    resp = await client.get("/api/v1/reports/equipment-verify-checklist/pdf", headers=admin)
    assert resp.status_code == 200, resp.text
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        cell_values = _all_cell_texts(pdf)
    # AVAILABLE_AT_POOL's Thai status label, cell-scoped (not a whole-page
    # scan) so this is a genuine end-to-end proof the correct glyphs reached
    # the response, not just that *some* Thai text is on the page somewhere.
    assert "พร้อมใช้งาน" in cell_values


@pytest.mark.parametrize(
    "report_id,orientation_wider",
    [("receive-report", True), ("issue-report", True), ("equipment-verify-checklist", False)],
)
async def test_pdf_page_orientation_matches_report_identity(client, seeded_users, report_id, orientation_wider):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(f"/api/v1/reports/{report_id}/pdf", headers=admin)
    assert resp.status_code == 200, resp.text
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        box = pdf.pages[0].mediabox
    width, height = box[2] - box[0], box[3] - box[1]
    assert (width > height) is orientation_wider


# ---------------------------------------------------------------------------
# API tests: render-failure handling (Roadmap PR18D review 4838921407,
# H1/H3) -- a timeout or other renderer failure must surface as a
# structured error response, and must log its own distinguishable
# export-attempt event rather than the "success" event above.
# ---------------------------------------------------------------------------


async def test_pdf_render_timeout_returns_structured_503_not_partial_pdf(monkeypatch, client, seeded_users):
    async def _timeout(document):
        raise PdfRenderTimeoutError("simulated render timeout")

    monkeypatch.setattr(report_pdf_service, "render_pdf_bounded", _timeout)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)

    resp = await client.get("/api/v1/reports/receive-report/pdf", headers=admin)
    assert resp.status_code == 503, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["code"] == "PDF_RENDER_TIMEOUT"


async def test_pdf_render_timeout_logs_a_distinguishable_export_attempt_event(monkeypatch, client, seeded_users):
    logged_calls = []

    def _capture(**kwargs):
        logged_calls.append(kwargs)

    async def _timeout(document):
        raise PdfRenderTimeoutError("simulated render timeout")

    monkeypatch.setattr(report_pdf_service, "render_pdf_bounded", _timeout)
    monkeypatch.setattr(report_export_service, "log_export_attempt", _capture)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)

    resp = await client.get("/api/v1/reports/receive-report/pdf", headers=admin)
    assert resp.status_code == 503, resp.text

    assert len(logged_calls) == 1
    assert logged_calls[0]["output_format"] == "pdf"
    assert logged_calls[0]["outcome"] == "render_timeout"
    assert logged_calls[0]["outcome"] != "success"


async def _raw_client():
    """A second client for the same app, sharing whatever
    dependency_overrides the `client` fixture already installed, but with
    `raise_app_exceptions=False`. Starlette's ServerErrorMiddleware always
    re-raises after sending a 500 response (so real ASGI servers can log
    it); httpx's ASGITransport re-raises that into the caller by default,
    which would make this test fail on the exception itself instead of
    letting us inspect the response the app already sent. Matches the
    established pattern in tests/test_exception_handling.py's own
    `_raw_client` helper for exactly this scenario -- production servers
    (uvicorn etc.) don't have this re-raise behavior; it's a
    test-transport-only quirk."""
    from httpx import ASGITransport, AsyncClient

    from app.main import app as fastapi_app

    transport = ASGITransport(app=fastapi_app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_pdf_unexpected_render_error_returns_500_and_logs_distinguishable_event(monkeypatch, client, seeded_users):
    logged_calls = []

    def _capture(**kwargs):
        logged_calls.append(kwargs)

    async def _boom(document):
        raise RuntimeError("simulated unexpected WeasyPrint failure")

    monkeypatch.setattr(report_pdf_service, "render_pdf_bounded", _boom)
    monkeypatch.setattr(report_export_service, "log_export_attempt", _capture)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)

    async with await _raw_client() as raw_client:
        resp = await raw_client.get("/api/v1/reports/receive-report/pdf", headers=admin)
    assert resp.status_code == 500, resp.text

    assert len(logged_calls) == 1
    assert logged_calls[0]["outcome"] == "render_error"
    assert logged_calls[0]["outcome"] != "success"


async def test_pdf_success_and_render_failure_outcomes_are_distinguishable(monkeypatch, client, seeded_users):
    """Direct proof of design §18/H3's requirement: a success and a render
    failure for the otherwise-identical request must never share the same
    logged outcome."""
    logged_calls = []

    def _capture(**kwargs):
        logged_calls.append(kwargs)

    monkeypatch.setattr(report_export_service, "log_export_attempt", _capture)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)

    ok_resp = await client.get("/api/v1/reports/receive-report/pdf", headers=admin)
    assert ok_resp.status_code == 200, ok_resp.text

    async def _timeout(document):
        raise PdfRenderTimeoutError("simulated render timeout")

    monkeypatch.setattr(report_pdf_service, "render_pdf_bounded", _timeout)
    failed_resp = await client.get("/api/v1/reports/receive-report/pdf", headers=admin)
    assert failed_resp.status_code == 503, failed_resp.text

    assert len(logged_calls) == 2
    assert logged_calls[0]["outcome"] == "success"
    assert logged_calls[1]["outcome"] == "render_timeout"
    assert logged_calls[0]["outcome"] != logged_calls[1]["outcome"]
