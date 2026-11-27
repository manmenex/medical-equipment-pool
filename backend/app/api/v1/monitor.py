"""Roadmap PR32 (D9/D13): read-only Monitor feed of dispatch/receipt events.

Never writes; never touches the dispatch/receipt services.
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.deps import EQUIPMENT_POOL_OPERATION_ROLES, require_roles
from app.core.exceptions import InvalidInputError
from app.core.reporting_time import business_date_and_shift, business_date_and_shift_sql
from app.db.session import get_db
from app.models.equipment import Equipment
from app.models.master_data import EquipmentCategory, Ward
from app.models.transaction import BorrowTransaction, ReceiptOutcome, TransactionStatus
from app.crud import cuff as cuff_crud
from app.models.user import User
from app.schemas.common import Page
from app.schemas.monitor import MonitorEquipment, MonitorEvent, MonitorOperator, MonitorWard
from app.utils.pagination import decode_cursor, encode_cursor
from app.utils.parsing import parse_uuid

_BKK = timezone(timedelta(hours=7))


def _local_8am_utc(d: date) -> datetime:
    return datetime.combine(d, time(8, 0), tzinfo=_BKK).astimezone(timezone.utc)


router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/events", response_model=Page[MonitorEvent])
async def list_events(
    kind: Literal["dispatch", "receipt"] = "dispatch",
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    ward_id: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    if business_date_from is not None and business_date_to is not None and business_date_from > business_date_to:
        raise InvalidInputError("'business_date_from' must not be after 'business_date_to'")
    ward_uuid: uuid.UUID | None = parse_uuid(ward_id, "ward_id")

    tx = BorrowTransaction
    op = aliased(User)
    is_dispatch = kind == "dispatch"
    event_col = tx.borrowed_at if is_dispatch else tx.returned_at
    op_id_col = tx.borrower_user_id if is_dispatch else tx.received_by_user_id

    filters = [event_col.is_not(None)]
    if ward_uuid is not None:
        filters.append(tx.ward_id == ward_uuid)
    if business_date_from is not None or business_date_to is not None:
        bd_expr, _ = business_date_and_shift_sql(event_col)
        # Loose UTC bound first so the event-time index is usable; the exact
        # business-date predicate below stays authoritative.
        if business_date_from is not None:
            filters.append(event_col >= _local_8am_utc(business_date_from - timedelta(days=1)))
            filters.append(bd_expr >= business_date_from)
        if business_date_to is not None:
            filters.append(event_col < _local_8am_utc(business_date_to + timedelta(days=1)))
            filters.append(bd_expr <= business_date_to)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        contact_col = tx.dispatch_contact_name if is_dispatch else tx.receipt_contact_name
        filters.append(
            or_(
                func.lower(Equipment.bcm_code).like(like),
                func.lower(op.full_name).like(like),
                func.lower(contact_col).like(like),
            )
        )

    base = (
        select(tx, Equipment, EquipmentCategory.name, Ward.name, op)
        .join(Equipment, Equipment.id == tx.equipment_id)
        .outerjoin(EquipmentCategory, EquipmentCategory.id == Equipment.category_id)
        .outerjoin(Ward, Ward.id == tx.ward_id)
        .outerjoin(op, op.id == op_id_col)
        .where(and_(*filters))
    )
    count_stmt = select(func.count()).select_from(base.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = base
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(event_col < cursor_dt, and_(event_col == cursor_dt, cast(tx.id, String) < cursor_id))
        )
    stmt = stmt.order_by(event_col.desc(), tx.id.desc()).limit(limit + 1)
    rows = (await db.execute(stmt)).all()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last_tx = rows[-1][0]
        last_at = last_tx.borrowed_at if is_dispatch else last_tx.returned_at
        next_cursor = encode_cursor(last_at, str(last_tx.id))

    balances = await cuff_crud.balances_for_transactions(db, [r[0].id for r in rows])
    items = []
    for t, eq, cat_name, ward_name, operator in rows:
        at = t.borrowed_at if is_dispatch else t.returned_at
        bd, shift = business_date_and_shift(at)
        outcome = None
        if not is_dispatch:
            try:
                outcome = ReceiptOutcome(t.condition_on_return).value
            except ValueError:
                outcome = None
        items.append(
            MonitorEvent(
                id=t.id,
                kind=kind,
                event_at=at,
                business_date=bd,
                shift=shift.value,
                ward=MonitorWard(id=t.ward_id, name=ward_name),
                operator=MonitorOperator(
                    id=operator.id if operator else None, full_name=operator.full_name if operator else None
                ),
                equipment=MonitorEquipment(
                    id=eq.id,
                    bcm_code=eq.bcm_code,
                    name=eq.equipment_name,
                    category=cat_name,
                    equipment_source=eq.equipment_source,
                ),
                receipt_outcome=outcome,
                # PR31 (D8) may add this column; read defensively.
                keyer_label=t.dispatch_keyer_label if is_dispatch else t.receipt_keyer_label,
                close_reason=getattr(t, "close_reason", None),
                ward_contact_name=t.dispatch_contact_name if is_dispatch else t.receipt_contact_name,
                has_hn=bool(t.has_hn),
                is_open=is_dispatch and t.status == TransactionStatus.OPEN,
                checklist_kind=t.checklist_kind,
                checks=t.dispatch_checks if is_dispatch else t.receipt_checks,
                cuffs_outstanding=(
                    cuff_crud.outstanding_counts(balances[t.id]) if t.id in balances else None
                ),
            )
        )
    return Page(items=items, next_cursor=next_cursor, total=total)
