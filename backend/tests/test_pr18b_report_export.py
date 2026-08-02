import uuid
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.exceptions import ExportTooLargeError
from app.models.audit import AuditLog
from app.models.transaction import BorrowTransaction
from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY, User
from app.schemas.report_export import ExportColumn, ExportDocument, ExportMetadata, ExportRow, ReportIdentity
from app.services import report_export_service
from app.utils.export_filename import build_filename_stem, date_range_segment, shift_segment
from tests.conftest import auth_headers as _auth_headers
from tests.conftest import create_ward as _create_ward

# pytest.ini sets asyncio_mode = auto -- async test functions run without any
# explicit marker, so this file deliberately has no module-level pytestmark
# (mixing synchronous filename-generation unit tests with async API/db
# tests in the same module; a blanket `pytest.mark.asyncio` pytestmark would
# incorrectly flag the synchronous tests).

# ---------------------------------------------------------------------------
# Roadmap PR18B (docs/design/PR18_PRINTING_EXPORT_PLAN.md §5-§8, §20, §22
# "PR18B -- Shared backend dataset and document model"): unit and API tests
# for app.services.report_export_service and
# GET /reports/{report_id}/print-data. No browser-print, PDF, or Excel
# implementation is exercised here -- those are future PR18C/PR18D/PR18E
# slices.
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 7, 31, 3, 15, 0, tzinfo=timezone.utc)


async def _create_equipment(client, headers, asset_number: str, *, category_id: str | None = None):
    payload = {"asset_number": asset_number, "equipment_name": "Infusion Pump"}
    if category_id is not None:
        payload["category_id"] = category_id
    resp = await client.post("/api/v1/equipment", headers=headers, json=payload)
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


async def _receive(client, headers, transaction_id: str, *, receipt_outcome: str = "usable"):
    resp = await client.post(
        f"/api/v1/return/{transaction_id}", headers=headers, json={"receipt_outcome": receipt_outcome}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _create_category(client, headers, name: str) -> dict:
    resp = await client.post("/api/v1/categories", headers=headers, json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_department(client, headers, code: str, name: str) -> dict:
    resp = await client.post("/api/v1/departments", headers=headers, json={"code": code, "name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Unit tests: filename generation (design §15, §20.1)
# ---------------------------------------------------------------------------


def test_filename_stem_strips_unsafe_characters():
    stem = build_filename_stem(
        ReportIdentity.RECEIVE_REPORT,
        date_segment="2026-07-01-to-2026-07-15",
        shift_segment_value="day",
        generated_at=_FIXED_NOW,
    )
    assert stem == "receive-report_2026-07-01-to-2026-07-15_day_20260731T031500Z"
    # Design §15's declared safe character set for the identity/date/shift
    # segments is `[a-z0-9._-]`; the trailing UTC timestamp segment is the
    # one deliberate exception -- its ISO-8601 "T"/"Z" markers are always
    # uppercase, exactly as design §15's own worked examples show.
    identity_date_shift_segments = stem.rsplit("_", 1)[0]
    assert all(ch.islower() or ch.isdigit() or ch in "._-" for ch in identity_date_shift_segments)


def test_filename_stem_is_deterministic_for_identical_inputs():
    stem_a = build_filename_stem(
        ReportIdentity.EQUIPMENT_VERIFY_CHECKLIST,
        date_segment="current",
        shift_segment_value="all",
        generated_at=_FIXED_NOW,
    )
    stem_b = build_filename_stem(
        ReportIdentity.EQUIPMENT_VERIFY_CHECKLIST,
        date_segment="current",
        shift_segment_value="all",
        generated_at=_FIXED_NOW,
    )
    assert stem_a == stem_b == "equipment-verify-checklist_current_all_20260731T031500Z"


def test_date_range_segment_variants():
    assert date_range_segment(None, None) == "all"
    d = date(2026, 7, 15)
    assert date_range_segment(d, d) == "2026-07-15"
    assert date_range_segment(date(2026, 7, 1), date(2026, 7, 15)) == "2026-07-01-to-2026-07-15"
    assert date_range_segment(date(2026, 7, 1), None) == "2026-07-01-to-all"


def test_shift_segment_variants():
    assert shift_segment(None) == "all"
    assert shift_segment("day") == "day"
    assert shift_segment("night") == "night"


# ---------------------------------------------------------------------------
# Unit tests: output-neutral document model / metadata (design §7.2, §13,
# §20.1) -- built directly against db_session, no HTTP layer, mirroring
# test_pr17_report_query_service.py's own convention.
# ---------------------------------------------------------------------------


async def test_receive_report_document_empty_result_is_valid(db_session, seeded_users):
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    document = await report_export_service.build_receive_report_document(
        db_session,
        ward_id=uuid.uuid4(),
        generated_by=admin,
        generated_at=_FIXED_NOW,
    )
    assert document.rows == []
    assert document.metadata.row_count == 0
    assert document.metadata.report_identity == ReportIdentity.RECEIVE_REPORT
    assert document.metadata.template_version == report_export_service.EXPORT_TEMPLATE_VERSION
    assert document.metadata.generated_at == _FIXED_NOW
    assert document.metadata.generated_by_display_name == admin.full_name
    assert document.metadata.timezone == "Asia/Bangkok"
    # Thai display name, not an English placeholder (design §9/§17).
    assert document.metadata.display_name_th == "รายงานการรับคืน"
    assert len(document.columns) == len(report_export_service._TRANSACTION_REPORT_COLUMNS)


async def test_receive_report_document_metadata_is_deterministic_for_fixed_clock(db_session, seeded_users):
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    doc_a = await report_export_service.build_receive_report_document(
        db_session, ward_id=uuid.uuid4(), generated_by=admin, generated_at=_FIXED_NOW
    )
    doc_b = await report_export_service.build_receive_report_document(
        db_session, ward_id=uuid.uuid4(), generated_by=admin, generated_at=_FIXED_NOW
    )
    assert doc_a.metadata.generated_at == doc_b.metadata.generated_at == _FIXED_NOW
    assert doc_a.metadata.filename_stem == doc_b.metadata.filename_stem


async def test_receive_report_filter_summary_reflects_applied_filters(db_session, seeded_users):
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    ward_id = uuid.uuid4()
    document = await report_export_service.build_receive_report_document(
        db_session,
        business_date_from=date(2026, 7, 1),
        business_date_to=date(2026, 7, 15),
        ward_id=ward_id,
        generated_by=admin,
        generated_at=_FIXED_NOW,
    )
    labels = {f.label_th for f in document.metadata.applied_filters}
    assert "ช่วงวันที่ทำการ" in labels
    assert "หอผู้ป่วย" in labels
    # No filter summary line for a filter that was never supplied.
    assert "กะ" not in labels


async def test_receive_report_no_filters_produces_empty_filter_summary(db_session, seeded_users):
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    document = await report_export_service.build_receive_report_document(
        db_session, generated_by=admin, generated_at=_FIXED_NOW
    )
    assert document.metadata.applied_filters == []


async def test_equipment_verify_checklist_columns_exclude_item_no(db_session, seeded_users):
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    document = await report_export_service.build_equipment_verify_checklist_document(
        db_session, generated_by=admin, generated_at=_FIXED_NOW
    )
    column_keys = {c.key for c in document.columns}
    assert "item_no" not in column_keys
    # Every row's `values` dict is keyed only by declared column keys.
    for row in document.rows:
        assert set(row.values.keys()) <= column_keys
    assert document.metadata.display_name_th == "รายการตรวจสอบเครื่องมือ"
    assert document.metadata.filename_stem.split("_")[1:3] == ["current", "all"]


async def test_equipment_verify_checklist_status_is_thai_label(client, seeded_users, db_session):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    eq = await _create_equipment(client, admin, "AST-PR18B-0001")
    admin_user: User = seeded_users[ROLE_ADMINISTRATOR]

    document = await report_export_service.build_equipment_verify_checklist_document(
        db_session, generated_by=admin_user, generated_at=_FIXED_NOW
    )
    assert len(document.rows) == 1
    status_value = document.rows[0].values["status"]
    assert status_value == "พร้อมใช้งาน"  # AVAILABLE_AT_POOL Thai label
    assert eq["asset_number"] == "AST-PR18B-0001"


# ---------------------------------------------------------------------------
# Unit tests: row-limit behavior (design §8/§18/§20.1, Owner Decision #3)
# ---------------------------------------------------------------------------


async def test_fetch_all_matching_rows_raises_when_over_limit(db_session, seeded_users):
    async def _query_fn(*, limit: int, cursor: str | None):
        # Simulates a query function that always has one more page --
        # exercises the loop's row_limit short-circuit without needing to
        # seed thousands of real rows.
        rows = list(range(limit))
        next_cursor = "more"
        return rows, next_cursor, 999999

    with pytest.raises(ExportTooLargeError):
        await report_export_service._fetch_all_matching_rows(_query_fn, row_limit=5, page_size=10)


async def test_fetch_all_matching_rows_stops_at_final_page(db_session, seeded_users):
    call_count = 0

    async def _query_fn(*, limit: int, cursor: str | None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return list(range(limit)), "next", 15
        return list(range(5)), None, 15

    rows, total = await report_export_service._fetch_all_matching_rows(_query_fn, row_limit=100, page_size=10)
    assert len(rows) == 15
    assert total == 15
    assert call_count == 2


# ---------------------------------------------------------------------------
# API tests: GET /reports/{report_id}/print-data (design §6/§12/§19/§20.2)
# ---------------------------------------------------------------------------


async def test_print_data_authorized_roles_succeed(client, seeded_users):
    for role in (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY):
        headers = await _auth_headers(client, role)
        resp = await client.get("/api/v1/reports/receive-report/print-data", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["metadata"]["report_identity"] == "receive-report"
        assert body["metadata"]["row_count"] == 0
        assert body["rows"] == []


async def test_print_data_unauthenticated_rejected_with_401(client, seeded_users):
    resp = await client.get("/api/v1/reports/receive-report/print-data")
    assert resp.status_code == 401, resp.text


async def test_print_data_unsupported_report_id_rejected(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get("/api/v1/reports/not-a-real-report/print-data", headers=admin)
    assert resp.status_code == 422, resp.text


async def test_print_data_reverse_business_date_range_rejected(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/receive-report/print-data",
        headers=admin,
        params={"business_date_from": "2026-07-15", "business_date_to": "2026-07-01"},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_print_data_receive_report_excludes_open_transaction(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18B-1")
    eq = await _create_equipment(client, admin, "AST-PR18B-0002")
    await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get(
        "/api/v1/reports/receive-report/print-data", headers=admin, params={"ward_id": ward_id}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["metadata"]["row_count"] == 0


async def test_print_data_receive_report_includes_closed_transaction(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18B-2")
    eq = await _create_equipment(client, admin, "AST-PR18B-0003")
    tx = await _dispatch(client, staff, eq["id"], ward_id)
    await _receive(client, staff, tx["id"])

    resp = await client.get(
        "/api/v1/reports/receive-report/print-data", headers=admin, params={"ward_id": ward_id}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["metadata"]["row_count"] == 1
    assert body["rows"][0]["values"]["asset_number"] == "AST-PR18B-0003"
    assert body["rows"][0]["values"]["receipt_outcome"] == "ใช้งานได้"


async def test_print_data_issue_report_includes_open_transaction(client, seeded_users):
    """Filter parity/eligibility check (design §20.2): Issue report includes
    an OPEN transaction, exactly like GET /reports/issue does (Roadmap PR17
    §7.2) -- the print-data path must not re-derive a stricter rule."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18B-3")
    eq = await _create_equipment(client, admin, "AST-PR18B-0004")
    await _dispatch(client, staff, eq["id"], ward_id)

    on_screen = await client.get("/api/v1/reports/issue", headers=admin, params={"ward_id": ward_id})
    print_data = await client.get(
        "/api/v1/reports/issue-report/print-data", headers=admin, params={"ward_id": ward_id}
    )
    assert on_screen.json()["total"] == 1
    assert print_data.json()["metadata"]["row_count"] == 1
    assert print_data.json()["rows"][0]["values"]["receipt_outcome"] is None


async def test_print_data_equipment_verify_checklist_excludes_item_no_field(client, seeded_users):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    await _create_equipment(client, admin, "AST-PR18B-0005")

    resp = await client.get("/api/v1/reports/equipment-verify-checklist/print-data", headers=admin)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["metadata"]["row_count"] == 1
    column_keys = {c["key"] for c in body["columns"]}
    assert "item_no" not in column_keys
    assert "item_no" not in body["rows"][0]["values"]


async def test_print_data_ignores_cursor_query_param(client, seeded_users):
    """Design §6/§8: the print-data route declares no `cursor` parameter and
    never follows a client-supplied cursor -- an extra, unused `cursor` on
    the wire must not change the result (still the full matching set)."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18B-4")
    for i in range(3):
        eq = await _create_equipment(client, admin, f"AST-PR18B-01{i}")
        await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get(
        "/api/v1/reports/issue-report/print-data",
        headers=admin,
        params={"ward_id": ward_id, "cursor": "bogus-client-supplied-cursor"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["metadata"]["row_count"] == 3


async def test_print_data_row_limit_exceeded_returns_structured_error(monkeypatch, client, seeded_users):
    monkeypatch.setattr(report_export_service, "MAX_EXPORT_ROWS", 0)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18B-5")
    eq = await _create_equipment(client, admin, "AST-PR18B-0006")
    await _dispatch(client, staff, eq["id"], ward_id)

    resp = await client.get(
        "/api/v1/reports/issue-report/print-data", headers=admin, params={"ward_id": ward_id}
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "EXPORT_TOO_LARGE"
    # No partial document is ever returned alongside the error envelope.
    assert "rows" not in body


async def test_print_data_does_not_write_persistent_audit_log(client, seeded_users, db_session):
    """Design §13: this is document metadata, never persistent audit
    logging -- PR18B must not add a new audit_logs row for a print-data
    request."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    before = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()

    resp = await client.get("/api/v1/reports/receive-report/print-data", headers=admin)
    assert resp.status_code == 200, resp.text

    after = (await db_session.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    assert after == before


async def test_print_data_does_not_mutate_transaction_state(client, seeded_users, db_session):
    """Design §26/§12: a read-only export/print request must never mutate
    business data."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    staff = await _auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    ward_id = await _create_ward(client, admin, "W-PR18B-6")
    eq = await _create_equipment(client, admin, "AST-PR18B-0007")
    tx = await _dispatch(client, staff, eq["id"], ward_id)

    before = (await db_session.execute(select(func.count()).select_from(BorrowTransaction))).scalar_one()
    resp = await client.get(
        "/api/v1/reports/issue-report/print-data", headers=admin, params={"ward_id": ward_id}
    )
    assert resp.status_code == 200, resp.text
    after = (await db_session.execute(select(func.count()).select_from(BorrowTransaction))).scalar_one()
    assert after == before

    # The transaction itself is untouched -- still OPEN, same equipment status.
    row = (
        await db_session.execute(select(BorrowTransaction).where(BorrowTransaction.id == uuid.UUID(tx["id"])))
    ).scalar_one()
    assert row.returned_at is None


# ---------------------------------------------------------------------------
# Regression tests: Codex review 4837529462 (PR18B-H1) -- each report_id's
# filter contract is enforced explicitly; an inapplicable filter is rejected
# with the structured INVALID_INPUT error, never silently dropped.
# ---------------------------------------------------------------------------

# One row per (report_id, inapplicable filter) pair, covering every filter
# the print-data route declares that does not belong to that report_id
# (app.api.v1.reports._PRINT_DATA_APPLICABLE_FILTERS).
_INAPPLICABLE_FILTER_CASES = [
    ("receive-report", {"dispatch_type": "on_demand"}),
    ("receive-report", {"routine_round": "06:00"}),
    ("receive-report", {"status": "available_at_pool"}),
    ("receive-report", {"department_id": str(uuid.uuid4())}),
    ("issue-report", {"status": "available_at_pool"}),
    ("issue-report", {"department_id": str(uuid.uuid4())}),
    ("equipment-verify-checklist", {"business_date_from": "2026-07-01"}),
    ("equipment-verify-checklist", {"business_date_to": "2026-07-01"}),
    ("equipment-verify-checklist", {"shift": "day"}),
    ("equipment-verify-checklist", {"ward_id": str(uuid.uuid4())}),
    ("equipment-verify-checklist", {"equipment_id": str(uuid.uuid4())}),
    ("equipment-verify-checklist", {"operator_id": str(uuid.uuid4())}),
    ("equipment-verify-checklist", {"dispatch_type": "on_demand"}),
    ("equipment-verify-checklist", {"routine_round": "06:00"}),
]


@pytest.mark.parametrize("report_id,params", _INAPPLICABLE_FILTER_CASES)
async def test_print_data_rejects_inapplicable_filter(client, seeded_users, report_id, params):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(f"/api/v1/reports/{report_id}/print-data", headers=admin, params=params)
    assert resp.status_code == 400, f"{report_id} {params}: {resp.text}"
    assert resp.json()["code"] == "INVALID_INPUT"


_APPLICABLE_FILTER_SMOKE_CASES = [
    ("receive-report", {"shift": "day"}),
    ("issue-report", {"dispatch_type": "on_demand"}),
    ("equipment-verify-checklist", {"status": "available_at_pool"}),
]


@pytest.mark.parametrize("report_id,params", _APPLICABLE_FILTER_SMOKE_CASES)
async def test_print_data_accepts_applicable_filter(client, seeded_users, report_id, params):
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(f"/api/v1/reports/{report_id}/print-data", headers=admin, params=params)
    assert resp.status_code == 200, f"{report_id} {params}: {resp.text}"


async def test_print_data_malformed_uuid_filter_rejected(client, seeded_users):
    """A filter that *is* applicable to the report still fails deterministic
    validation when malformed -- reuses the existing `parse_uuid` behavior,
    not a new error path."""
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/receive-report/print-data", headers=admin, params={"ward_id": "not-a-uuid"}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


async def test_print_data_rejects_inapplicable_filter_before_query_execution(client, seeded_users, monkeypatch):
    """Proves rejection happens before any report builder (and therefore
    before any database query) runs, not merely that the final HTTP status
    happens to be 400."""

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("report builder must not be called when an inapplicable filter is rejected")

    monkeypatch.setattr(report_export_service, "build_equipment_verify_checklist_document", _fail_if_called)
    admin = await _auth_headers(client, ROLE_ADMINISTRATOR)
    resp = await client.get(
        "/api/v1/reports/equipment-verify-checklist/print-data",
        headers=admin,
        params={"ward_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Regression tests: Codex review 4837529462 (PR18B-H2) -- applied_filters
# metadata is complete (includes equipment_id) and every value is resolved
# to its business-readable display form, never a raw UUID or enum token.
# ---------------------------------------------------------------------------


async def test_receive_report_filter_summary_resolves_ward_category_equipment_operator_names(
    client, seeded_users, db_session
):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    ward_id = await _create_ward(client, admin_headers, "W-PR18B-H2A")
    category = await _create_category(client, admin_headers, "Infusion Devices PR18B-H2")
    equipment = await _create_equipment(
        client, admin_headers, "AST-PR18B-H2A", category_id=category["id"]
    )
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    staff: User = seeded_users[ROLE_EQUIPMENT_POOL_STAFF]

    document = await report_export_service.build_receive_report_document(
        db_session,
        ward_id=uuid.UUID(ward_id),
        equipment_id=uuid.UUID(equipment["id"]),
        equipment_category_id=uuid.UUID(category["id"]),
        operator_id=staff.id,
        generated_by=admin,
        generated_at=_FIXED_NOW,
    )
    by_label = {f.label_th: f.value for f in document.metadata.applied_filters}

    assert by_label["หอผู้ป่วย"] == "W-PR18B-H2A"
    assert by_label["หอผู้ป่วย"] != ward_id

    assert by_label["หมวดหมู่เครื่องมือ"] == "Infusion Devices PR18B-H2"
    assert by_label["หมวดหมู่เครื่องมือ"] != category["id"]

    assert by_label["เครื่องมือ"] == "AST-PR18B-H2A - Infusion Pump"
    assert by_label["เครื่องมือ"] != equipment["id"]

    assert by_label["ผู้รับคืน"] == staff.full_name
    assert by_label["ผู้รับคืน"] != str(staff.id)


async def test_issue_report_filter_summary_resolves_operator_dispatch_type_and_routine_round(
    client, seeded_users, db_session
):
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    staff: User = seeded_users[ROLE_EQUIPMENT_POOL_STAFF]

    document = await report_export_service.build_issue_report_document(
        db_session,
        operator_id=staff.id,
        dispatch_type=None,
        routine_round=None,
        generated_by=admin,
        generated_at=_FIXED_NOW,
    )
    by_label = {f.label_th: f.value for f in document.metadata.applied_filters}
    assert by_label["ผู้เบิก"] == staff.full_name

    from app.models.transaction import DispatchType, RoutineRound

    document_routine = await report_export_service.build_issue_report_document(
        db_session,
        dispatch_type=DispatchType.ROUTINE_ROUND,
        routine_round=RoutineRound.ROUND_0600,
        generated_by=admin,
        generated_at=_FIXED_NOW,
    )
    by_label_routine = {f.label_th: f.value for f in document_routine.metadata.applied_filters}
    assert by_label_routine["ประเภทการเบิก"] == "รอบเวลาปกติ (Routine Round)"
    assert by_label_routine["ประเภทการเบิก"] != "routine_round"
    assert by_label_routine["รอบเวร"] == "รอบ 06:00"


async def test_equipment_verify_checklist_filter_summary_resolves_category_and_department_names(
    client, seeded_users, db_session
):
    admin_headers = await _auth_headers(client, ROLE_ADMINISTRATOR)
    category = await _create_category(client, admin_headers, "Ventilators PR18B-H2")
    department = await _create_department(client, admin_headers, "DPT-PR18B-H2", "ICU PR18B-H2")
    admin: User = seeded_users[ROLE_ADMINISTRATOR]

    document = await report_export_service.build_equipment_verify_checklist_document(
        db_session,
        equipment_category_id=uuid.UUID(category["id"]),
        department_id=uuid.UUID(department["id"]),
        generated_by=admin,
        generated_at=_FIXED_NOW,
    )
    by_label = {f.label_th: f.value for f in document.metadata.applied_filters}
    assert by_label["หมวดหมู่เครื่องมือ"] == "Ventilators PR18B-H2"
    assert by_label["หน่วยงานเจ้าของ"] == "ICU PR18B-H2"
    assert by_label["หน่วยงานเจ้าของ"] != department["id"]


async def test_filter_summary_falls_back_to_not_found_label_for_deleted_reference(db_session, seeded_users):
    """A filter value that no longer resolves (e.g. the row was deleted
    after the filter was chosen) still produces a filter-summary line -- the
    filter *was* applied -- using an explicit not-found label, never a raw
    UUID and never silently omitted, even though the result set is empty."""
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    dangling_operator_id = uuid.uuid4()
    document = await report_export_service.build_receive_report_document(
        db_session,
        operator_id=dangling_operator_id,
        generated_by=admin,
        generated_at=_FIXED_NOW,
    )
    assert document.rows == []
    by_label = {f.label_th: f.value for f in document.metadata.applied_filters}
    assert by_label["ผู้รับคืน"] == "ไม่พบข้อมูล"
    assert by_label["ผู้รับคืน"] != str(dangling_operator_id)


# ---------------------------------------------------------------------------
# Regression tests: Codex review 4837529462 (PR18B-H3) -- ExportDocument
# enforces its own schema invariants at construction time.
# ---------------------------------------------------------------------------


def _valid_metadata(**overrides) -> ExportMetadata:
    fields = dict(
        report_identity=ReportIdentity.RECEIVE_REPORT,
        display_name_th="รายงานการรับคืน",
        template_version="1",
        generated_at=_FIXED_NOW,
        generated_by_display_name="Tester",
        generated_by_user_id=str(uuid.uuid4()),
        timezone="Asia/Bangkok",
        applied_filters=[],
        row_count=1,
        filename_stem="receive-report_all_all_20260731T031500Z",
    )
    fields.update(overrides)
    return ExportMetadata(**fields)


def test_export_document_accepts_a_valid_document():
    document = ExportDocument(
        metadata=_valid_metadata(row_count=1),
        columns=[ExportColumn(key="a", label_th="A", value_type="integer")],
        rows=[ExportRow(values={"a": 1})],
    )
    assert document.rows[0].values["a"] == 1


def test_export_document_rejects_duplicate_column_keys():
    with pytest.raises(ValidationError, match="duplicate column keys"):
        ExportDocument(
            metadata=_valid_metadata(row_count=0),
            columns=[
                ExportColumn(key="a", label_th="A", value_type="string"),
                ExportColumn(key="a", label_th="A2", value_type="string"),
            ],
            rows=[],
        )


def test_export_document_rejects_row_missing_a_declared_column_key():
    with pytest.raises(ValidationError, match="keys do not match declared columns"):
        ExportDocument(
            metadata=_valid_metadata(row_count=1),
            columns=[
                ExportColumn(key="a", label_th="A", value_type="string"),
                ExportColumn(key="b", label_th="B", value_type="string"),
            ],
            rows=[ExportRow(values={"a": "x"})],
        )


def test_export_document_rejects_row_with_an_unexpected_key():
    with pytest.raises(ValidationError, match="keys do not match declared columns"):
        ExportDocument(
            metadata=_valid_metadata(row_count=1),
            columns=[ExportColumn(key="a", label_th="A", value_type="string")],
            rows=[ExportRow(values={"a": "x", "unexpected": "y"})],
        )


def test_export_document_rejects_value_type_mismatch():
    # This is the exact scenario Codex independently reproduced in review
    # 4837529462: a column declared "integer" but the row supplies a string.
    with pytest.raises(ValidationError, match="does not match column"):
        ExportDocument(
            metadata=_valid_metadata(row_count=1),
            columns=[ExportColumn(key="a", label_th="A", value_type="integer")],
            rows=[ExportRow(values={"a": "wrong"})],
        )


def test_export_document_rejects_bool_for_an_integer_column():
    # bool is an int subclass in Python -- must not silently satisfy an
    # "integer" column.
    with pytest.raises(ValidationError, match="does not match column"):
        ExportDocument(
            metadata=_valid_metadata(row_count=1),
            columns=[ExportColumn(key="a", label_th="A", value_type="integer")],
            rows=[ExportRow(values={"a": True})],
        )


def test_export_document_rejects_datetime_for_a_date_column():
    with pytest.raises(ValidationError, match="does not match column"):
        ExportDocument(
            metadata=_valid_metadata(row_count=1),
            columns=[ExportColumn(key="a", label_th="A", value_type="date")],
            rows=[ExportRow(values={"a": _FIXED_NOW})],
        )


def test_export_document_accepts_null_for_any_column_type():
    document = ExportDocument(
        metadata=_valid_metadata(row_count=1),
        columns=[ExportColumn(key="a", label_th="A", value_type="integer")],
        rows=[ExportRow(values={"a": None})],
    )
    assert document.rows[0].values["a"] is None


def test_export_document_rejects_row_count_mismatch():
    with pytest.raises(ValidationError, match="row_count"):
        ExportDocument(
            metadata=_valid_metadata(row_count=5),
            columns=[ExportColumn(key="a", label_th="A", value_type="string")],
            rows=[ExportRow(values={"a": "x"})],
        )


def test_export_metadata_rejects_naive_generated_at():
    with pytest.raises(ValidationError, match="timezone-aware"):
        _valid_metadata(generated_at=datetime(2026, 7, 31, 3, 15, 0))


def test_export_metadata_rejects_empty_template_version():
    with pytest.raises(ValidationError):
        _valid_metadata(template_version="")


def test_export_metadata_rejects_empty_filename_stem():
    with pytest.raises(ValidationError):
        _valid_metadata(filename_stem="")


def test_export_metadata_rejects_negative_row_count():
    with pytest.raises(ValidationError):
        _valid_metadata(row_count=-1)


async def test_every_report_builder_produces_a_schema_valid_document(db_session, seeded_users):
    """Each of the three PR18B report builders' output must already satisfy
    `ExportDocument`'s own invariants -- if it did not, construction inside
    the builder itself would have raised before this test even ran. This
    test documents that guarantee explicitly for all three builders,
    including the empty-result path."""
    admin: User = seeded_users[ROLE_ADMINISTRATOR]
    receive_doc = await report_export_service.build_receive_report_document(
        db_session, generated_by=admin, generated_at=_FIXED_NOW
    )
    issue_doc = await report_export_service.build_issue_report_document(
        db_session, generated_by=admin, generated_at=_FIXED_NOW
    )
    checklist_doc = await report_export_service.build_equipment_verify_checklist_document(
        db_session, generated_by=admin, generated_at=_FIXED_NOW
    )
    for document in (receive_doc, issue_doc, checklist_doc):
        assert document.metadata.row_count == len(document.rows) == 0
        assert document.metadata.generated_at.tzinfo is not None
