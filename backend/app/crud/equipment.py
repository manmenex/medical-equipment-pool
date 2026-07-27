import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStatusTransitionError
from app.models.equipment import (
    DISPATCH_RECEIPT_TRANSITIONS,
    MANUAL_LIFECYCLE_TRANSITIONS,
    Equipment,
    EquipmentStatus,
    EquipmentStatusHistory,
)
from app.services.identifiers import strip_bcm_prefix
from app.utils.pagination import decode_cursor, encode_cursor

# Roadmap PR5 / ADR-003: the confirmed operator-facing identifier's prefix,
# reused from app.services.identifiers so search normalization and
# persisted-form canonicalization can never diverge.
_BCM_PREFIX = "BCM"


async def get_by_id(db: AsyncSession, equipment_id: uuid.UUID) -> Equipment | None:
    result = await db.execute(
        select(Equipment).where(Equipment.id == equipment_id, Equipment.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_by_item_no(db: AsyncSession, item_no: str) -> Equipment | None:
    """Exact Item No lookup -- the only supported QR-resolution match.

    No partial/fuzzy matching: this is the internal QR-resolution path, not
    the operator-facing BCM search below.
    """
    result = await db.execute(
        select(Equipment).where(Equipment.item_no == item_no, Equipment.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


def _normalize_bcm_query(raw: str) -> str:
    return strip_bcm_prefix(raw)


async def search_bcm(db: AsyncSession, *, q: str, limit: int = 10) -> list[Equipment]:
    """BCM-Code-only manual-search suggestions (Roadmap PR5).

    Searches `bcm_code` exclusively -- never item_no, equipment_name,
    brand, model, or serial_number (those remain reachable only through the
    separate, pre-existing general equipment list search). Case-insensitive,
    trimmed, and tolerant of an optional leading "BCM" prefix on the query,
    on both the query and target sides implicitly (partial ILIKE matching
    against the full stored bcm_code, which always retains its own "BCM"
    prefix, already finds it once the query's own optional prefix is
    stripped).

    An empty or prefix-only query (nothing left to search once "BCM" -- if
    present -- is stripped) returns an empty list immediately without
    touching the database, rather than falling through to an unbounded
    `LIKE '%%'` scan of every equipment row.

    Ranking: an exact match (case-insensitive, with or without the "BCM"
    prefix on either side) sorts first; ties broken by shorter bcm_code
    (a closer match) then alphabetically. `limit` bounds the result count
    for both the suggestion-list use case and to keep the query cheap
    against a multi-thousand-row table.
    """
    token = _normalize_bcm_query(q)
    if not token:
        return []

    # Escape LIKE wildcards in the user-typed token itself so a BCM code
    # containing a literal "%" or "_" (unlikely, but not guaranteed absent
    # from future imported data) can't be searched for as a wildcard.
    escaped_token = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped_token}%"
    exact_candidates = {token.upper(), f"{_BCM_PREFIX}{token}".upper()}
    exact_rank = case((func.upper(Equipment.bcm_code).in_(exact_candidates), 0), else_=1)

    stmt = (
        select(Equipment)
        .where(
            Equipment.deleted_at.is_(None),
            Equipment.bcm_code.isnot(None),
            Equipment.bcm_code.ilike(like, escape="\\"),
        )
        .order_by(exact_rank, func.length(Equipment.bcm_code), Equipment.bcm_code)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_by_asset_number(db: AsyncSession, asset_number: str) -> Equipment | None:
    result = await db.execute(
        select(Equipment).where(Equipment.asset_number == asset_number, Equipment.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def get_by_bcm_codes(db: AsyncSession, values: Sequence[str]) -> dict[str, Equipment]:
    """Bulk exact BCM Code lookup. Roadmap PR12 (review PR12-H2): a single
    IN(...) query for an entire import batch, replacing what was
    previously one query per row -- app.services.import_service is the
    only caller, and BCM Code is the sole match key it uses to decide
    whether an import row is a new record or an update to an existing
    one (never item_no, asset_id, or serial_number)."""
    if not values:
        return {}
    result = await db.execute(
        select(Equipment).where(Equipment.bcm_code.in_(values), Equipment.deleted_at.is_(None))
    )
    return {e.bcm_code: e for e in result.scalars().all()}


async def get_by_item_nos(db: AsyncSession, values: Sequence[str]) -> dict[str, Equipment]:
    """Bulk exact Item No lookup (Roadmap PR12 review PR12-H2/H3 import
    duplicate check -- item_no is already database-unique)."""
    if not values:
        return {}
    result = await db.execute(
        select(Equipment).where(Equipment.item_no.in_(values), Equipment.deleted_at.is_(None))
    )
    return {e.item_no: e for e in result.scalars().all()}


async def get_by_serial_numbers(db: AsyncSession, values: Sequence[str]) -> dict[str, Equipment]:
    """Bulk exact Serial Number lookup (Roadmap PR12 review PR12-H2/H3
    import duplicate check -- serial_number is already database-unique)."""
    if not values:
        return {}
    result = await db.execute(
        select(Equipment).where(Equipment.serial_number.in_(values), Equipment.deleted_at.is_(None))
    )
    return {e.serial_number: e for e in result.scalars().all()}


async def get_by_asset_ids(db: AsyncSession, values: Sequence[str]) -> dict[str, Equipment]:
    """Roadmap PR12: asset_id carries no database uniqueness constraint
    (see migration 0010's docstring -- hospital-wide uniqueness is
    unconfirmed), so this returns one representative match per value for
    application-layer conflict flagging, not a uniqueness guarantee."""
    if not values:
        return {}
    result = await db.execute(
        select(Equipment).where(Equipment.asset_id.in_(values), Equipment.deleted_at.is_(None))
    )
    mapping: dict[str, Equipment] = {}
    for e in result.scalars().all():
        mapping.setdefault(e.asset_id, e)
    return mapping


async def search(
    db: AsyncSession,
    *,
    q: str | None = None,
    status: EquipmentStatus | None = None,
    department_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[Equipment], str | None, int]:
    base_filters = [Equipment.deleted_at.is_(None)]
    if status is not None:
        base_filters.append(Equipment.status == status)
    if department_id is not None:
        base_filters.append(Equipment.department_owner_id == department_id)
    if category_id is not None:
        base_filters.append(Equipment.category_id == category_id)
    if q:
        like = f"%{q}%"
        base_filters.append(
            or_(
                Equipment.equipment_name.ilike(like),
                Equipment.asset_number.ilike(like),
                Equipment.serial_number.ilike(like),
            )
        )

    count_stmt = select(func.count()).select_from(Equipment).where(and_(*base_filters))
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(Equipment).where(and_(*base_filters))
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Equipment.created_at < cursor_dt,
                and_(Equipment.created_at == cursor_dt, cast(Equipment.id, String) < cursor_id),
            )
        )
    stmt = stmt.order_by(Equipment.created_at.desc(), Equipment.id.desc()).limit(limit + 1)

    rows = list((await db.execute(stmt)).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
        rows = rows[:limit]

    return rows, next_cursor, total


async def create(db: AsyncSession, *, data: dict) -> Equipment:
    equipment = Equipment(**data)
    db.add(equipment)
    await db.flush()
    return equipment


async def update(db: AsyncSession, equipment: Equipment, *, data: dict) -> Equipment:
    for key, value in data.items():
        if value is not None:
            setattr(equipment, key, value)
    await db.flush()
    return equipment


async def soft_delete(db: AsyncSession, equipment: Equipment) -> None:
    equipment.deleted_at = datetime.utcnow()
    await db.flush()


async def change_status(
    db: AsyncSession,
    equipment: Equipment,
    *,
    new_status: EquipmentStatus,
    changed_by_user_id: uuid.UUID | None,
    reason: str | None = None,
    allowed_transitions: dict[EquipmentStatus, frozenset[EquipmentStatus]],
) -> EquipmentStatusHistory:
    """Single mutation point for every equipment status change (writes
    EquipmentStatusHistory, updates Equipment.status). `allowed_transitions`
    is required, not defaulted, so every caller must be explicit about
    which transition authority it is exercising -- see
    change_status_for_dispatch_receipt and change_status_for_manual_
    lifecycle below, the only two call sites this function has (Roadmap
    PR6-H2: a single shared table let the generic maintenance endpoint
    perform dispatch/receipt-only transitions without the atomic
    transaction bookkeeping those flows require). Never reads or writes
    Equipment.legacy_status -- that column is historical/rollback-only
    (Roadmap PR6) and must never gate or record an ordinary transition.
    """
    if new_status not in allowed_transitions.get(equipment.status, frozenset()):
        raise InvalidStatusTransitionError(
            f"Equipment cannot move from '{equipment.status.value}' to '{new_status.value}'."
        )
    history = EquipmentStatusHistory(
        equipment_id=equipment.id,
        from_status=equipment.status.value if equipment.status else None,
        to_status=new_status.value,
        changed_by_user_id=changed_by_user_id,
        reason=reason,
    )
    equipment.status = new_status
    db.add(history)
    await db.flush()
    return history


async def change_status_for_dispatch_receipt(
    db: AsyncSession,
    equipment: Equipment,
    *,
    new_status: EquipmentStatus,
    changed_by_user_id: uuid.UUID | None,
    reason: str | None = None,
) -> EquipmentStatusHistory:
    """The only status-change entry point app.services.borrow_service may
    use -- dispatch (AVAILABLE_AT_POOL -> ISSUED_TO_WARD) and receipt
    (ISSUED_TO_WARD -> AVAILABLE_AT_POOL / UNAVAILABLE_DEFECTIVE), always
    called alongside the BorrowTransaction create/close it must stay
    atomic with. See app.models.equipment.DISPATCH_RECEIPT_TRANSITIONS.
    """
    return await change_status(
        db,
        equipment,
        new_status=new_status,
        changed_by_user_id=changed_by_user_id,
        reason=reason,
        allowed_transitions=DISPATCH_RECEIPT_TRANSITIONS,
    )


async def change_status_for_manual_lifecycle(
    db: AsyncSession,
    equipment: Equipment,
    *,
    new_status: EquipmentStatus,
    changed_by_user_id: uuid.UUID | None,
    reason: str | None = None,
) -> EquipmentStatusHistory:
    """The only status-change entry point the generic admin/BME
    POST /equipment/{id}/status endpoint may use -- authorized maintenance
    lifecycle changes only (defective marking, return-to-service,
    decommission). Never ISSUED_TO_WARD as source or target: dispatch and
    receipt are exclusively change_status_for_dispatch_receipt's job. See
    app.models.equipment.MANUAL_LIFECYCLE_TRANSITIONS.
    """
    return await change_status(
        db,
        equipment,
        new_status=new_status,
        changed_by_user_id=changed_by_user_id,
        reason=reason,
        allowed_transitions=MANUAL_LIFECYCLE_TRANSITIONS,
    )


async def get_history(db: AsyncSession, equipment_id: uuid.UUID) -> list[EquipmentStatusHistory]:
    result = await db.execute(
        select(EquipmentStatusHistory)
        .where(EquipmentStatusHistory.equipment_id == equipment_id)
        .order_by(EquipmentStatusHistory.changed_at.desc())
    )
    return list(result.scalars().all())
