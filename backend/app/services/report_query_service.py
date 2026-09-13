import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.reporting_time import Shift
from app.crud import transaction as transaction_crud
from app.models.transaction import BorrowTransaction, DispatchType, RoutineRound

# Roadmap PR17 Slice 1 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md §8/§11,
# §17 Slice 1 boundary: "Report Domain and Query Semantics"). This module is
# the report domain/query layer only -- no HTTP route, no response DTO, no
# operator-lookup query. Per the merged design's Slice boundary, the two
# report endpoints (GET /reports/receive, GET /reports/issue), the
# ReportTransactionOut DTO, and the operator-lookup query/endpoint
# (GET /report-options/operators) are all Slice 2 ("Report APIs and Lookup
# Options", §17) -- explicitly not built here. These two functions return
# plain BorrowTransaction ORM rows, exactly like transaction_crud.search()
# itself; Slice 2 composes them into ReportTransactionOut.
#
# Both functions are thin wrappers that pin transaction_crud.search()'s
# `event` (and, for Receive, `require_receipt`) -- no query logic is
# duplicated (§8 Option A/Option C rejection), and no ambiguous boolean flag
# is exposed to callers: the receive/issue distinction is the function
# chosen, not a parameter.


async def search_receive_report(
    db: AsyncSession,
    *,
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    shift: Shift | None = None,
    ward_id: uuid.UUID | None = None,
    equipment_id: uuid.UUID | None = None,
    equipment_category_id: uuid.UUID | None = None,
    operator_id: uuid.UUID | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[BorrowTransaction], str | None, int]:
    """Canonical Receive Report query (§7.1, §8, §11).

    Pins `event="receipt"` and `require_receipt=True` unconditionally --
    neither is caller-settable. This enforces §7.1's rule that an OPEN
    transaction (`returned_at IS NULL`) never appears in the Receive
    Report, regardless of which other filters (or none at all) are
    supplied -- `require_receipt` is independent of the
    business_date/shift-gated NULL-propagation `transaction_crud.search()`
    already has (see that function's docstring). `operator_id` resolves
    against `received_by_user_id` (event="receipt" selects that column,
    §9/§11). A `CLOSED` transaction with a defective receipt outcome is
    included exactly like a usable one -- `receipt_outcome` is never an
    eligibility criterion here (§7.1).
    """
    return await transaction_crud.search(
        db,
        ward_id=ward_id,
        equipment_id=equipment_id,
        equipment_category_id=equipment_category_id,
        operator_id=operator_id,
        business_date_from=business_date_from,
        business_date_to=business_date_to,
        shift=shift,
        event="receipt",
        require_receipt=True,
        limit=limit,
        cursor=cursor,
    )


async def search_issue_report(
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
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[BorrowTransaction], str | None, int]:
    """Canonical Issue Report query (§7.2, §8, §11).

    Pins `event="dispatch"`. Both OPEN and CLOSED transactions are
    eligible -- a dispatch is a fact about the past regardless of whether
    the item has since been received (§7.2); no lifecycle-status filter is
    applied here beyond what the caller explicitly requests via the base
    `search()` filters this function does not expose (this function never
    sets `require_receipt`, since `dispatch_business_date` is always
    present -- no NULL-exclusion gap exists for dispatch, §8). `operator_id`
    resolves against `borrower_user_id` (event="dispatch" selects that
    column, §9/§11).
    """
    return await transaction_crud.search(
        db,
        ward_id=ward_id,
        equipment_id=equipment_id,
        equipment_category_id=equipment_category_id,
        operator_id=operator_id,
        dispatch_type=dispatch_type,
        routine_round=routine_round,
        business_date_from=business_date_from,
        business_date_to=business_date_to,
        shift=shift,
        event="dispatch",
        limit=limit,
        cursor=cursor,
    )
