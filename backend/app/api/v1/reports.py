from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.v1.deps import VIEW_AND_REPORT_ROLES, require_roles
from app.api.v1.equipment import _serialize as _serialize_equipment
from app.core.exceptions import ExportTooLargeError, InvalidInputError
from app.core.reporting_time import Shift
from app.crud import equipment as equipment_crud
from app.db.session import get_db
from app.models.equipment import EquipmentStatus
from app.models.transaction import DispatchType, RoutineRound
from app.schemas.common import Page
from app.schemas.equipment import EquipmentOut
from app.schemas.report_export import PrintDocumentOut, ReportIdentity, to_print_document_out
from app.schemas.transaction import ReportTransactionOut
from app.services import report_export_service, report_query_service, report_service
from app.utils.parsing import parse_uuid

router = APIRouter(prefix="/reports", tags=["reports"])


def _validate_business_date_range(business_date_from: date | None, business_date_to: date | None) -> None:
    # Roadmap PR17 Slice 2 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
    # §10.1/§10.2): the exact same reversed-range check already used by
    # app/api/v1/transactions.py::list_transactions for business_date_from/
    # business_date_to -- reused verbatim, not reimplemented.
    if business_date_from is not None and business_date_to is not None and business_date_from > business_date_to:
        raise InvalidInputError("'business_date_from' must not be after 'business_date_to'")


# Roadmap PR18B review 4837529462 (PR18B-H1): `get_report_print_data` below
# declares the union of all three PR17 reports' filters (one route family
# per design §6.2), but each report's underlying query function only
# accepts its own subset -- e.g. `equipment_crud.list_for_verify_checklist`
# has no `ward_id` parameter at all. Silently accepting and dropping an
# inapplicable filter would let a caller believe a returned document was
# filtered when the extra parameter was never forwarded to any query. This
# table is each report identity's *exact* accepted filter set, matching the
# parameters `GET /reports/receive`, `GET /reports/issue`, and
# `GET /reports/equipment-verify-checklist` above already accept -- not a
# new, independently invented filter contract.
_PRINT_DATA_APPLICABLE_FILTERS: dict[ReportIdentity, frozenset[str]] = {
    ReportIdentity.RECEIVE_REPORT: frozenset(
        {
            "business_date_from",
            "business_date_to",
            "shift",
            "ward_id",
            "equipment_id",
            "equipment_category_id",
            "operator_id",
        }
    ),
    ReportIdentity.ISSUE_REPORT: frozenset(
        {
            "business_date_from",
            "business_date_to",
            "shift",
            "ward_id",
            "equipment_id",
            "equipment_category_id",
            "operator_id",
            "dispatch_type",
            "routine_round",
        }
    ),
    ReportIdentity.EQUIPMENT_VERIFY_CHECKLIST: frozenset({"equipment_category_id", "status", "department_id"}),
}


def _reject_inapplicable_print_data_filters(report_id: ReportIdentity, **filters: object) -> None:
    applicable = _PRINT_DATA_APPLICABLE_FILTERS[report_id]
    rejected = sorted(name for name, value in filters.items() if value is not None and name not in applicable)
    if rejected:
        raise InvalidInputError(
            f"The following filters are not supported for report_id '{report_id.value}': {', '.join(rejected)}"
        )


@router.get("/export")
async def export_report(
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    db: AsyncSession = Depends(get_db),
    # Roadmap PR10: this export surface already existed for admin, viewer,
    # and biomedical_engineer pre-PR10 -- preserved at the same breadth for
    # all three new roles, not narrowed and not newly added.
    _user=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    if format == "csv":
        content = await report_service.export_csv(db)
        media_type = "text/csv"
        filename = "borrow_report.csv"
    else:
        content = await report_service.export_xlsx(db)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "borrow_report.xlsx"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/receive", response_model=Page[ReportTransactionOut])
async def get_receive_report(
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    shift: Shift | None = None,
    ward_id: str | None = None,
    equipment_id: str | None = None,
    equipment_category_id: str | None = None,
    operator_id: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    # Roadmap PR17 Slice 2 (§10.1/§14): VIEW_AND_REPORT_ROLES, matching the
    # existing /reports/export precedent above -- not the looser
    # get_current_user-only gate GET /transactions itself uses, since this
    # is a named report surface.
    _user=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    """Roadmap PR17 §7.1/§8/§10.1: `event` is pinned to `"receipt"` and
    `require_receipt=True` is always set internally by
    `report_query_service.search_receive_report` -- neither is a
    client-settable parameter here, enforcing the canonical "OPEN
    transactions never appear" rule unconditionally."""
    _validate_business_date_range(business_date_from, business_date_to)
    rows, next_cursor, total = await report_query_service.search_receive_report(
        db,
        business_date_from=business_date_from,
        business_date_to=business_date_to,
        shift=shift,
        ward_id=parse_uuid(ward_id, "ward_id"),
        equipment_id=parse_uuid(equipment_id, "equipment_id"),
        equipment_category_id=parse_uuid(equipment_category_id, "equipment_category_id"),
        operator_id=parse_uuid(operator_id, "operator_id"),
        limit=limit,
        cursor=cursor,
    )
    return Page(items=rows, next_cursor=next_cursor, total=total)


@router.get("/issue", response_model=Page[ReportTransactionOut])
async def get_issue_report(
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    shift: Shift | None = None,
    ward_id: str | None = None,
    equipment_id: str | None = None,
    equipment_category_id: str | None = None,
    operator_id: str | None = None,
    dispatch_type: DispatchType | None = None,
    routine_round: RoutineRound | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    """Roadmap PR17 §7.2/§8/§10.2: `event` is pinned to `"dispatch"`. Both
    OPEN and CLOSED transactions are eligible -- dispatch is a fact about
    the past regardless of whether the item has since been received."""
    _validate_business_date_range(business_date_from, business_date_to)
    rows, next_cursor, total = await report_query_service.search_issue_report(
        db,
        business_date_from=business_date_from,
        business_date_to=business_date_to,
        shift=shift,
        ward_id=parse_uuid(ward_id, "ward_id"),
        equipment_id=parse_uuid(equipment_id, "equipment_id"),
        equipment_category_id=parse_uuid(equipment_category_id, "equipment_category_id"),
        operator_id=parse_uuid(operator_id, "operator_id"),
        dispatch_type=dispatch_type,
        routine_round=routine_round,
        limit=limit,
        cursor=cursor,
    )
    return Page(items=rows, next_cursor=next_cursor, total=total)


@router.get("/equipment-verify-checklist", response_model=Page[EquipmentOut])
async def get_equipment_verify_checklist(
    equipment_category_id: str | None = None,
    status: EquipmentStatus | None = None,
    department_id: str | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    # Roadmap PR17 Slice 4 (§10.3/§14): same VIEW_AND_REPORT_ROLES gate as
    # the other two report endpoints above.
    _user=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    """Roadmap PR17 §6.3/§7.3(A)/§8/§10.3 (Owner Decision #1 resolved to
    interpretation A): a read-only, current-state listing of the pool's own
    equipment master records and their status -- not a transaction/event
    report, and not date/shift filterable the way Receive/Issue are (§7.3(A)).
    `ward_id` is deliberately not a filter here: `Equipment` has no direct
    Ward relationship, only `department_owner_id` (§10.3's corrected query
    param set). Response rows are `EquipmentOut` -- the exact same shape
    `GET /equipment` already returns, no new fields invented (§8/§10.3).
    """
    rows, next_cursor, total = await equipment_crud.list_for_verify_checklist(
        db,
        category_id=parse_uuid(equipment_category_id, "equipment_category_id"),
        status=status,
        department_id=parse_uuid(department_id, "department_id"),
        limit=limit,
        cursor=cursor,
    )
    items = [EquipmentOut.model_validate(_serialize_equipment(e)) for e in rows]
    return Page(items=items, next_cursor=next_cursor, total=total)


@router.get("/{report_id}/print-data", response_model=PrintDocumentOut)
async def get_report_print_data(
    report_id: ReportIdentity,
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    shift: Shift | None = None,
    ward_id: str | None = None,
    equipment_id: str | None = None,
    equipment_category_id: str | None = None,
    operator_id: str | None = None,
    dispatch_type: DispatchType | None = None,
    routine_round: RoutineRound | None = None,
    status: EquipmentStatus | None = None,
    department_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    # Roadmap PR18B (docs/design/PR18_PRINTING_EXPORT_PLAN.md §6.2/§12):
    # identical report-view authorization to every existing report endpoint
    # above -- export/print introduces no new permission. `require_roles`
    # returns the authenticated `User`, captured here as `generated_by` for
    # the response's generation-metadata (design §7.2/§13).
    generated_by=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    """Roadmap PR18B (design §5/§6/§22 "PR18B -- Shared backend dataset and
    document model"): the print-data adapter -- one typed route family
    dispatching to the three named dataset builders in
    `app.services.report_export_service`, per the approved design's §6.2
    recommendation. Returns the *complete* filtered result set (Owner
    Decision #1, resolved to interpretation A: all rows matching the active
    filters, bounded by `report_export_service.MAX_EXPORT_ROWS`), never a
    cursor page -- this route deliberately declares no `cursor` parameter
    and never follows one.

    Browser Print (a future PR18C deliverable), not PDF or Excel, is this
    route's only consumer -- PDF/Excel export routes are PR18D/PR18E scope,
    not built here (design §22's own PR18B non-goal list).
    """
    timing = report_export_service.ExportTiming()
    _reject_inapplicable_print_data_filters(
        report_id,
        business_date_from=business_date_from,
        business_date_to=business_date_to,
        shift=shift,
        ward_id=ward_id,
        equipment_id=equipment_id,
        equipment_category_id=equipment_category_id,
        operator_id=operator_id,
        dispatch_type=dispatch_type,
        routine_round=routine_round,
        status=status,
        department_id=department_id,
    )
    if report_id in (ReportIdentity.RECEIVE_REPORT, ReportIdentity.ISSUE_REPORT):
        _validate_business_date_range(business_date_from, business_date_to)

    try:
        if report_id == ReportIdentity.RECEIVE_REPORT:
            document = await report_export_service.build_receive_report_document(
                db,
                business_date_from=business_date_from,
                business_date_to=business_date_to,
                shift=shift,
                ward_id=parse_uuid(ward_id, "ward_id"),
                equipment_id=parse_uuid(equipment_id, "equipment_id"),
                equipment_category_id=parse_uuid(equipment_category_id, "equipment_category_id"),
                operator_id=parse_uuid(operator_id, "operator_id"),
                generated_by=generated_by,
            )
        elif report_id == ReportIdentity.ISSUE_REPORT:
            document = await report_export_service.build_issue_report_document(
                db,
                business_date_from=business_date_from,
                business_date_to=business_date_to,
                shift=shift,
                ward_id=parse_uuid(ward_id, "ward_id"),
                equipment_id=parse_uuid(equipment_id, "equipment_id"),
                equipment_category_id=parse_uuid(equipment_category_id, "equipment_category_id"),
                operator_id=parse_uuid(operator_id, "operator_id"),
                dispatch_type=dispatch_type,
                routine_round=routine_round,
                generated_by=generated_by,
            )
        else:
            document = await report_export_service.build_equipment_verify_checklist_document(
                db,
                equipment_category_id=parse_uuid(equipment_category_id, "equipment_category_id"),
                status=status,
                department_id=parse_uuid(department_id, "department_id"),
                generated_by=generated_by,
            )
    except ExportTooLargeError:
        report_export_service.log_export_attempt(
            report_identity=report_id,
            output_format="print-data",
            actor_user_id=generated_by.id,
            outcome="row_limit_exceeded",
            row_count=None,
            duration_ms=timing.elapsed_ms(),
        )
        raise

    report_export_service.log_export_attempt(
        report_identity=report_id,
        output_format="print-data",
        actor_user_id=generated_by.id,
        outcome="success",
        row_count=document.metadata.row_count,
        duration_ms=timing.elapsed_ms(),
    )
    return to_print_document_out(document)
