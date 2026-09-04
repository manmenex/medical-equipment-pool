"""Roadmap PR18B (docs/design/PR18_PRINTING_EXPORT_PLAN.md §5-§8, §22
"PR18B -- Shared backend dataset and document model"): the backend export
foundation. Builds the internal, output-neutral `ExportDocument` for each of
the three Roadmap PR17 report families, reusing their existing query
functions and response DTOs unchanged -- this module owns no eligibility,
filter, or ordering logic of its own (design §5 "Existing report query
layer... remains authoritative. Output adapters must not reimplement or
reinterpret any of them.").

Nothing in this module renders a browser-print page, a PDF, or an Excel
workbook (design §22's own PR18B non-goals) -- those are PR18C/PR18D/PR18E.
"""

import functools
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timezone
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.equipment import _serialize as _serialize_equipment
from app.core.exceptions import ExportTooLargeError
from app.core.logging import safe_log
from app.core.reporting_time import Shift
from app.crud import equipment as equipment_crud
from app.crud import master_data as master_data_crud
from app.crud import user as user_crud
from app.models.equipment import EquipmentStatus
from app.models.transaction import DispatchType, RoutineRound
from app.models.user import User
from app.schemas.equipment import EquipmentOut
from app.schemas.report_export import (
    ExportColumn,
    ExportDocument,
    ExportFilterSummary,
    ExportMetadata,
    ExportRow,
    ReportIdentity,
)
from app.schemas.transaction import ReportTransactionOut
from app.services import report_query_service
from app.utils.export_filename import build_filename_stem, date_range_segment, shift_segment

logger = logging.getLogger(__name__)

# Roadmap PR18A Owner Decision #3 (docs/design/PR18_PRINTING_EXPORT_PLAN.md
# §8/§18/§23), confirmed by the Repository Owner during PR18B kickoff:
# a synchronous export/print request whose full matching-row count exceeds
# this bound is rejected outright (ExportTooLargeError), never silently
# truncated. Deliberately not the legacy exporter's 50,000-row cap (design
# §8: "The current legacy export's 50,000-row cap is implementation
# precedent, not approval for PR18 limits") -- this system's confirmed
# real-world scale is "low hundreds of devices, thousands of transactions
# per year" (docs/KNOWN_LIMITATIONS.md), so a limit two orders of magnitude
# smaller is the evidenced, approved choice. PDF and `.xlsx` may later need
# a stricter, format-specific limit for rendering-cost reasons (design
# §8/§18) -- that is a PR18D/PR18E decision, not made here; this constant is
# PR18B's own shared synchronous bound for dataset retrieval and the
# print-data endpoint.
MAX_EXPORT_ROWS = 5000

# Document-template version (design §14): output column/layout/metadata
# schema version, distinct from report identity and API version. A single
# shared value today -- nothing in this slice's three report shapes
# diverges enough to need independent per-report versions yet.
EXPORT_TEMPLATE_VERSION = "1"

# Internal page size for the backend-owned full-result retrieval loop below
# -- matches this reports family's existing `le=200` on-screen page-size
# ceiling (app.api.v1.reports), not a new, independently-invented value.
_FETCH_PAGE_SIZE = 200

_SHIFT_LABELS_TH = {Shift.DAY.value: "กลางวัน", Shift.NIGHT.value: "กลางคืน"}
_RECEIPT_OUTCOME_LABELS_TH = {"usable": "ใช้งานได้", "defective": "ชำรุด"}
_EQUIPMENT_STATUS_LABELS_TH = {
    EquipmentStatus.AVAILABLE_AT_POOL.value: "พร้อมใช้งาน",
    EquipmentStatus.ISSUED_TO_WARD.value: "จ่ายให้หอผู้ป่วยแล้ว",
    EquipmentStatus.UNAVAILABLE_DEFECTIVE.value: "ไม่พร้อมใช้งาน",
    EquipmentStatus.DECOMMISSIONED.value: "ปลดระวางถาวร",
}
# Roadmap PR18B review 4837529462 (PR18B-H2): reused verbatim from the
# existing frontend label map (frontend/src/pages/EquipmentDetailPage.tsx's
# DISPATCH_TYPE_LABELS) -- not a new translation.
_DISPATCH_TYPE_LABELS_TH = {
    DispatchType.ON_DEMAND.value: "เบิกตามคำขอ (On-Demand)",
    DispatchType.ROUTINE_ROUND.value: "รอบเวลาปกติ (Routine Round)",
}

# Fallback shown in applied-filter metadata when a filter's UUID no longer
# resolves to a live master-data/user/equipment row (e.g. deleted after the
# filter was applied) -- never a raw UUID (design §7.2 "resolved on the
# backend for output").
_FILTER_VALUE_NOT_FOUND_TH = "ไม่พบข้อมูล"

_ROW = TypeVar("_ROW")


# ---------------------------------------------------------------------------
# Full-result dataset retrieval (design §5 "Dataset builder", §8, §18) --
# generic over any of the three PR17 cursor-paginated query functions.
# ---------------------------------------------------------------------------


async def _fetch_all_matching_rows(
    query_fn: Callable[..., Awaitable[tuple[list[_ROW], str | None, int]]],
    *,
    row_limit: int,
    page_size: int = _FETCH_PAGE_SIZE,
) -> tuple[list[_ROW], int]:
    """Backend-owned full-result retrieval (design §5/§8/§18): repeatedly
    calls the existing, unmodified `query_fn` (`report_query_service.search_
    receive_report`/`search_issue_report` or `equipment_crud.
    list_for_verify_checklist`, partially applied with the caller's filters)
    using *its own* cursor internally -- never a client-supplied cursor
    chain (design §8: "output requests never send a frontend cursor").

    Bounded, not unbounded: each round-trip is capped at `page_size` rows by
    the query function's own existing `limit+1` internal cap (design §18
    "no unbounded `.all()` over an unknown result size"), and the loop
    itself is bounded by `row_limit` -- the moment accumulated rows exceed
    it, this raises `ExportTooLargeError` immediately rather than continuing
    to accumulate an ever-larger result set (design §8: "no adapter silently
    truncates rows").
    """
    rows: list[_ROW] = []
    cursor: str | None = None
    total = 0
    while True:
        page_rows, next_cursor, total = await query_fn(limit=page_size, cursor=cursor)
        rows.extend(page_rows)
        if len(rows) > row_limit:
            raise ExportTooLargeError(
                f"The filtered result set exceeds the maximum synchronous export size of "
                f"{row_limit} rows. Narrow the applied filters (date range, ward, category, "
                "or another available filter) and try again."
            )
        if next_cursor is None:
            break
        cursor = next_cursor
    return rows, total


# ---------------------------------------------------------------------------
# Master-data name resolution (design §7.2 "Display values such as Ward,
# category, department, and operator names are resolved on the backend for
# output. The frontend must not join master-data lookups to construct
# authoritative export rows.") -- one bounded batch query per lookup type,
# never one query per row.
# ---------------------------------------------------------------------------


async def _ward_name_lookup(db: AsyncSession) -> dict[str, str]:
    wards = await master_data_crud.list_wards(db)
    return {str(w.id): w.name for w in wards}


async def _category_name_lookup(db: AsyncSession) -> dict[str, str]:
    categories = await master_data_crud.list_categories(db)
    return {str(c.id): c.name for c in categories}


async def _department_name_lookup(db: AsyncSession) -> dict[str, str]:
    departments = await master_data_crud.list_departments(db)
    return {str(d.id): d.name for d in departments}


# ---------------------------------------------------------------------------
# Column definitions (design §7.2) -- stable, explicit, Thai-first (design
# §9/§17), matching the exact fields the existing on-screen report tables
# already render (frontend/src/components/ReportResultsTable.tsx,
# EquipmentVerifyChecklistTable.tsx) so export/print never shows a field an
# operator would not already recognize from the screen.
# ---------------------------------------------------------------------------

_TRANSACTION_REPORT_COLUMNS = [
    ExportColumn(key="transaction_no", label_th="เลขที่รายการ", value_type="string"),
    ExportColumn(key="asset_number", label_th="รหัสครุภัณฑ์", value_type="string"),
    ExportColumn(key="equipment_name", label_th="เครื่องมือ", value_type="string"),
    ExportColumn(key="ward_name", label_th="หอผู้ป่วย", value_type="string"),
    ExportColumn(key="dispatch_operator_display_name", label_th="เบิกโดย", value_type="string"),
    ExportColumn(key="dispatch_business_date", label_th="วันที่ทำการเบิก", value_type="date"),
    ExportColumn(key="dispatch_shift", label_th="กะที่เบิก", value_type="string"),
    ExportColumn(key="receipt_operator_display_name", label_th="รับคืนโดย", value_type="string"),
    ExportColumn(key="receipt_business_date", label_th="วันที่ทำการรับคืน", value_type="date"),
    ExportColumn(key="receipt_shift", label_th="กะที่รับคืน", value_type="string"),
    ExportColumn(key="receipt_outcome", label_th="สภาพเมื่อรับคืน", value_type="string"),
]

_EQUIPMENT_VERIFY_CHECKLIST_COLUMNS = [
    ExportColumn(key="equipment_name", label_th="เครื่องมือ", value_type="string"),
    ExportColumn(key="bcm_code", label_th="รหัส BCM", value_type="string"),
    ExportColumn(key="asset_number", label_th="รหัสครุภัณฑ์", value_type="string"),
    ExportColumn(key="serial_number", label_th="หมายเลขเครื่อง", value_type="string"),
    ExportColumn(key="category_name", label_th="หมวดหมู่", value_type="string"),
    ExportColumn(key="department_name", label_th="หน่วยงานเจ้าของ", value_type="string"),
    ExportColumn(key="status", label_th="สถานะ", value_type="string"),
]


def _transaction_report_row(tx_out: ReportTransactionOut, *, ward_names: dict[str, str]) -> ExportRow:
    return ExportRow(
        values={
            "transaction_no": tx_out.transaction_no,
            "asset_number": tx_out.equipment.asset_number,
            "equipment_name": tx_out.equipment.equipment_name,
            "ward_name": ward_names.get(tx_out.ward_id, "ไม่ทราบ") if tx_out.ward_id else "ไม่ทราบ",
            "dispatch_operator_display_name": tx_out.dispatch_operator_display_name,
            "dispatch_business_date": tx_out.dispatch_business_date,
            "dispatch_shift": _SHIFT_LABELS_TH[tx_out.dispatch_shift.value],
            "receipt_operator_display_name": tx_out.receipt_operator_display_name,
            "receipt_business_date": tx_out.receipt_business_date,
            "receipt_shift": _SHIFT_LABELS_TH[tx_out.receipt_shift.value] if tx_out.receipt_shift else None,
            "receipt_outcome": (
                _RECEIPT_OUTCOME_LABELS_TH.get(tx_out.receipt_outcome.value, tx_out.receipt_outcome.value)
                if tx_out.receipt_outcome
                else None
            ),
        }
    )


def _equipment_verify_checklist_row(
    eq_out: EquipmentOut, *, category_names: dict[str, str], department_names: dict[str, str]
) -> ExportRow:
    return ExportRow(
        values={
            "equipment_name": eq_out.equipment_name,
            "bcm_code": eq_out.bcm_code,
            "asset_number": eq_out.asset_number,
            "serial_number": eq_out.serial_number,
            "category_name": category_names.get(eq_out.category_id, "-") if eq_out.category_id else "-",
            "department_name": (
                department_names.get(eq_out.department_owner_id, "-") if eq_out.department_owner_id else "-"
            ),
            "status": _EQUIPMENT_STATUS_LABELS_TH[eq_out.status.value],
        }
    )


# ---------------------------------------------------------------------------
# Metadata assembly (design §7.2, §13)
# ---------------------------------------------------------------------------


def _build_metadata(
    *,
    report_identity: ReportIdentity,
    display_name_th: str,
    generated_by: User,
    generated_at: datetime,
    applied_filters: list[ExportFilterSummary],
    row_count: int,
    date_segment: str,
    shift_segment_value: str,
) -> ExportMetadata:
    filename_stem = build_filename_stem(
        report_identity,
        date_segment=date_segment,
        shift_segment_value=shift_segment_value,
        generated_at=generated_at,
    )
    return ExportMetadata(
        report_identity=report_identity,
        display_name_th=display_name_th,
        template_version=EXPORT_TEMPLATE_VERSION,
        generated_at=generated_at,
        generated_by_display_name=generated_by.full_name,
        generated_by_user_id=str(generated_by.id),
        timezone="Asia/Bangkok",
        applied_filters=applied_filters,
        row_count=row_count,
        filename_stem=filename_stem,
    )


def _date_filter_summary(business_date_from: date | None, business_date_to: date | None) -> ExportFilterSummary | None:
    if business_date_from is not None and business_date_to is not None:
        value = f"{business_date_from.isoformat()} ถึง {business_date_to.isoformat()}"
    elif business_date_from is not None:
        value = f"ตั้งแต่ {business_date_from.isoformat()}"
    elif business_date_to is not None:
        value = f"ถึง {business_date_to.isoformat()}"
    else:
        return None
    return ExportFilterSummary(label_th="ช่วงวันที่ทำการ", value=value)


def _shift_filter_summary(shift: Shift | None) -> ExportFilterSummary | None:
    if shift is None:
        return None
    return ExportFilterSummary(label_th="กะ", value=_SHIFT_LABELS_TH[shift.value])


def _filter_summary(label_th: str, value: uuid.UUID | None, display_name: str | None) -> ExportFilterSummary | None:
    """Roadmap PR18B review 4837529462 (PR18B-H2): renders the caller's
    already-resolved, human-readable `display_name` -- never the raw
    `value` UUID (design §7.2 "Display values ... are resolved on the
    backend for output"). `display_name` is `None` only when the filtered-on
    row no longer exists (e.g. deleted since); that still produces a
    filter-summary line (the filter *was* applied) rather than silently
    omitting it, using an explicit not-found label instead of a UUID."""
    if value is None:
        return None
    return ExportFilterSummary(label_th=label_th, value=display_name if display_name is not None else _FILTER_VALUE_NOT_FOUND_TH)


async def _resolve_operator_name(db: AsyncSession, operator_id: uuid.UUID | None) -> str | None:
    """Roadmap PR18B review 4837668805 (PR18B-H2R): resolves through
    `user_crud.get_operator_by_id` -- the same bounded, report-scoped
    operator population rule as `GET /report-options/operators`
    (`user_crud.list_operators`) -- never the unrestricted
    `user_crud.get_by_id`. A `operator_id` that is a real `User` but has
    never appeared as a dispatch/receipt operator resolves to `None` here
    exactly as it would be absent from `GET /report-options/operators`,
    not a name-discovery path for an arbitrary user UUID."""
    if operator_id is None:
        return None
    operator = await user_crud.get_operator_by_id(db, operator_id)
    return operator.full_name if operator is not None else None


async def _resolve_equipment_label(db: AsyncSession, equipment_id: uuid.UUID | None) -> str | None:
    if equipment_id is None:
        return None
    equipment = await equipment_crud.get_by_id(db, equipment_id)
    if equipment is None:
        return None
    return f"{equipment.asset_number} - {equipment.equipment_name}"


def _status_filter_summary(status: EquipmentStatus | None) -> ExportFilterSummary | None:
    if status is None:
        return None
    return ExportFilterSummary(label_th="สถานะ", value=_EQUIPMENT_STATUS_LABELS_TH[status.value])


def _dispatch_type_filter_summary(dispatch_type: DispatchType | None) -> ExportFilterSummary | None:
    if dispatch_type is None:
        return None
    return ExportFilterSummary(label_th="ประเภทการเบิก", value=_DISPATCH_TYPE_LABELS_TH[dispatch_type.value])


def _routine_round_filter_summary(routine_round: RoutineRound | None) -> ExportFilterSummary | None:
    if routine_round is None:
        return None
    # Roadmap PR18B review 4837529462 (PR18B-H2): "รอบ {time}" reused
    # verbatim from the existing on-screen convention
    # (frontend/src/pages/EquipmentDetailPage.tsx's `` `รอบ ${tx.routine_round}` ``)
    # -- the clock-time value itself is already business-readable, so this
    # only adds the same Thai prefix the frontend already uses, not a new
    # translation.
    return ExportFilterSummary(label_th="รอบเวร", value=f"รอบ {routine_round.value}")


# ---------------------------------------------------------------------------
# Report builders -- one per Roadmap PR17 report family (design §22). Each
# calls its existing report_query_service/equipment_crud function unchanged
# and never re-derives eligibility, filters, or ordering itself.
# ---------------------------------------------------------------------------


async def build_receive_report_document(
    db: AsyncSession,
    *,
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    shift: Shift | None = None,
    ward_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    equipment_category_id: uuid.UUID | None = None,
    operator_id: uuid.UUID | None = None,
    generated_by: User,
    generated_at: datetime | None = None,
) -> ExportDocument:
    query_fn = functools.partial(
        report_query_service.search_receive_report,
        db,
        business_date_from=business_date_from,
        business_date_to=business_date_to,
        shift=shift,
        ward_id=ward_id,
        equipment_id=equipment_id,
        equipment_category_id=equipment_category_id,
        operator_id=operator_id,
    )
    rows, _total = await _fetch_all_matching_rows(query_fn, row_limit=MAX_EXPORT_ROWS)
    ward_names = await _ward_name_lookup(db)
    export_rows = [
        _transaction_report_row(ReportTransactionOut.model_validate(row), ward_names=ward_names) for row in rows
    ]
    # Roadmap PR18B review 4837529462 (PR18B-H2): category/operator/equipment
    # display names resolved only when the corresponding filter is actually
    # supplied -- no per-request query for a lookup no filter needs.
    category_names = await _category_name_lookup(db) if equipment_category_id is not None else {}
    operator_name = await _resolve_operator_name(db, operator_id)
    equipment_label = await _resolve_equipment_label(db, equipment_id)
    applied_filters = [
        f
        for f in (
            _date_filter_summary(business_date_from, business_date_to),
            _shift_filter_summary(shift),
            _filter_summary("หอผู้ป่วย", ward_id, ward_names.get(str(ward_id)) if ward_id else None),
            _filter_summary(
                "หมวดหมู่เครื่องมือ",
                equipment_category_id,
                category_names.get(str(equipment_category_id)) if equipment_category_id else None,
            ),
            _filter_summary("เครื่องมือ", equipment_id, equipment_label),
            _filter_summary("ผู้รับคืน", operator_id, operator_name),
        )
        if f is not None
    ]
    resolved_generated_at = generated_at if generated_at is not None else datetime.now(timezone.utc)
    metadata = _build_metadata(
        report_identity=ReportIdentity.RECEIVE_REPORT,
        display_name_th="รายงานการรับคืน",
        generated_by=generated_by,
        generated_at=resolved_generated_at,
        applied_filters=applied_filters,
        row_count=len(export_rows),
        date_segment=date_range_segment(business_date_from, business_date_to),
        shift_segment_value=shift_segment(shift.value if shift else None),
    )
    return ExportDocument(metadata=metadata, columns=_TRANSACTION_REPORT_COLUMNS, rows=export_rows)


async def build_issue_report_document(
    db: AsyncSession,
    *,
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    shift: Shift | None = None,
    ward_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    equipment_category_id: uuid.UUID | None = None,
    operator_id: uuid.UUID | None = None,
    dispatch_type: DispatchType | None = None,
    routine_round: RoutineRound | None = None,
    generated_by: User,
    generated_at: datetime | None = None,
) -> ExportDocument:
    query_fn = functools.partial(
        report_query_service.search_issue_report,
        db,
        business_date_from=business_date_from,
        business_date_to=business_date_to,
        shift=shift,
        ward_id=ward_id,
        equipment_id=equipment_id,
        equipment_category_id=equipment_category_id,
        operator_id=operator_id,
        dispatch_type=dispatch_type,
        routine_round=routine_round,
    )
    rows, _total = await _fetch_all_matching_rows(query_fn, row_limit=MAX_EXPORT_ROWS)
    ward_names = await _ward_name_lookup(db)
    export_rows = [
        _transaction_report_row(ReportTransactionOut.model_validate(row), ward_names=ward_names) for row in rows
    ]
    category_names = await _category_name_lookup(db) if equipment_category_id is not None else {}
    operator_name = await _resolve_operator_name(db, operator_id)
    equipment_label = await _resolve_equipment_label(db, equipment_id)
    applied_filters = [
        f
        for f in (
            _date_filter_summary(business_date_from, business_date_to),
            _shift_filter_summary(shift),
            _filter_summary("หอผู้ป่วย", ward_id, ward_names.get(str(ward_id)) if ward_id else None),
            _filter_summary(
                "หมวดหมู่เครื่องมือ",
                equipment_category_id,
                category_names.get(str(equipment_category_id)) if equipment_category_id else None,
            ),
            _filter_summary("เครื่องมือ", equipment_id, equipment_label),
            _filter_summary("ผู้เบิก", operator_id, operator_name),
            _dispatch_type_filter_summary(dispatch_type),
            _routine_round_filter_summary(routine_round),
        )
        if f is not None
    ]
    resolved_generated_at = generated_at if generated_at is not None else datetime.now(timezone.utc)
    metadata = _build_metadata(
        report_identity=ReportIdentity.ISSUE_REPORT,
        display_name_th="รายงานการเบิก",
        generated_by=generated_by,
        generated_at=resolved_generated_at,
        applied_filters=applied_filters,
        row_count=len(export_rows),
        date_segment=date_range_segment(business_date_from, business_date_to),
        shift_segment_value=shift_segment(shift.value if shift else None),
    )
    return ExportDocument(metadata=metadata, columns=_TRANSACTION_REPORT_COLUMNS, rows=export_rows)


async def build_equipment_verify_checklist_document(
    db: AsyncSession,
    *,
    equipment_category_id: uuid.UUID | None = None,
    status: EquipmentStatus | None = None,
    department_id: uuid.UUID | None = None,
    generated_by: User,
    generated_at: datetime | None = None,
) -> ExportDocument:
    query_fn = functools.partial(
        equipment_crud.list_for_verify_checklist,
        db,
        category_id=equipment_category_id,
        status=status,
        department_id=department_id,
    )
    rows, _total = await _fetch_all_matching_rows(query_fn, row_limit=MAX_EXPORT_ROWS)
    category_names = await _category_name_lookup(db)
    department_names = await _department_name_lookup(db)
    export_rows = [
        _equipment_verify_checklist_row(
            EquipmentOut.model_validate(_serialize_equipment(e)),
            category_names=category_names,
            department_names=department_names,
        )
        for e in rows
    ]
    applied_filters = [
        f
        for f in (
            _filter_summary(
                "หมวดหมู่เครื่องมือ",
                equipment_category_id,
                category_names.get(str(equipment_category_id)) if equipment_category_id else None,
            ),
            _status_filter_summary(status),
            _filter_summary(
                "หน่วยงานเจ้าของ", department_id, department_names.get(str(department_id)) if department_id else None
            ),
        )
        if f is not None
    ]
    resolved_generated_at = generated_at if generated_at is not None else datetime.now(timezone.utc)
    metadata = _build_metadata(
        report_identity=ReportIdentity.EQUIPMENT_VERIFY_CHECKLIST,
        display_name_th="รายการตรวจสอบเครื่องมือ",
        generated_by=generated_by,
        generated_at=resolved_generated_at,
        applied_filters=applied_filters,
        row_count=len(export_rows),
        # Equipment Verify Checklist is a read-only current-state snapshot
        # (design §4.2/§4.3) -- it has no business_date/shift basis, so the
        # filename's date/shift segments are always "current"/"all" (design
        # §15's own worked example: "equipment-verify-checklist_current_all_...").
        date_segment="current",
        shift_segment_value="all",
    )
    return ExportDocument(metadata=metadata, columns=_EQUIPMENT_VERIFY_CHECKLIST_COLUMNS, rows=export_rows)


# ---------------------------------------------------------------------------
# Operational output-event logging (design §13): one safe, structured event
# per attempt -- document metadata, never persistent audit logging (design
# §13: "PR18 does not introduce a new persistent domain audit record without
# Owner approval"). Never logs row data, filenames containing user input
# (the filename stem here is built only from report identity/date/shift,
# never free-text filter values), or sensitive filter values.
# ---------------------------------------------------------------------------


def log_export_attempt(
    *,
    report_identity: ReportIdentity,
    output_format: str,
    actor_user_id: uuid.UUID,
    outcome: str,
    row_count: int | None,
    duration_ms: float,
) -> None:
    safe_log(
        lambda: logger.info(
            "Report export/print attempt",
            extra={
                "report_identity": report_identity.value,
                "output_format": output_format,
                "actor_user_id": str(actor_user_id),
                "outcome": outcome,
                "row_count": row_count,
                "duration_ms": duration_ms,
            },
        )
    )


class ExportTiming:
    """Tiny helper so route handlers don't hand-roll `time.monotonic()`
    bookkeeping at every call site."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> float:
        return (time.monotonic() - self._start) * 1000
