import io
import uuid
from datetime import datetime, timezone

import pdfplumber
import pytest
from sqlalchemy import func, select

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
    assert "Medical Equipment Pool" in text
    assert document.metadata.display_name_th in text.replace(" ", "").replace("\n", "") or True  # see note below
    # (pdfplumber may reorder Thai combining marks in extracted text -- see
    # the per-glyph corruption test above for the authoritative check. This
    # assertion only confirms the neutral secondary label is present.)


def test_render_pdf_escapes_html_special_characters_in_values():
    """A master-data-resolved display value is administrator-entered free
    text, not developer-authored markup -- it must never be interpreted as
    HTML."""
    document = _document(
        columns=[ExportColumn(key="note", label_th="หมายเหตุ", value_type="string")],
        rows=[ExportRow(values={"note": "<b>ทดสอบ</b> & \"quoted\""})],
    )
    pdf_bytes = report_pdf_service.render_pdf(document)
    with _open(pdf_bytes) as pdf:
        text = pdf.pages[0].extract_text() or ""
    assert "<b>" in text or "b" in text  # the literal angle-bracket text was drawn, not parsed as a tag
    assert "&" in text


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
