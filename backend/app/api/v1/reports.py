from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.v1.deps import VIEW_AND_REPORT_ROLES, require_roles
from app.core.exceptions import InvalidInputError
from app.core.reporting_time import Shift
from app.db.session import get_db
from app.models.transaction import DispatchType, RoutineRound
from app.schemas.common import Page
from app.schemas.transaction import ReportTransactionOut
from app.services import report_query_service, report_service
from app.utils.parsing import parse_uuid

router = APIRouter(prefix="/reports", tags=["reports"])


def _validate_business_date_range(business_date_from: date | None, business_date_to: date | None) -> None:
    # Roadmap PR17 Slice 2 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
    # §10.1/§10.2): the exact same reversed-range check already used by
    # app/api/v1/transactions.py::list_transactions for business_date_from/
    # business_date_to -- reused verbatim, not reimplemented.
    if business_date_from is not None and business_date_to is not None and business_date_from > business_date_to:
        raise InvalidInputError("'business_date_from' must not be after 'business_date_to'")


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
    limit: int = Query(default=25, le=200),
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
    limit: int = Query(default=25, le=200),
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
