import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidInputError, InvalidStatusTransitionError
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


async def list_for_verify_checklist(
    db: AsyncSession,
    *,
    category_id: uuid.UUID | None = None,
    status: EquipmentStatus | None = None,
    department_id: uuid.UUID | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> tuple[list[Equipment], str | None, int]:
    """Roadmap PR17 Slice 4 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
    §7.3(A)/§8/§10.3, Owner Decision #1 resolved to interpretation A):
    Equipment Verify Checklist query -- a read-only, current-state listing
    of the pool's own equipment master records, not a transaction/event
    report. Deliberately separate from `search()` above (rather than a
    shared helper) because the two have different filter sets and no
    caller needs both at once; the two do, however, intentionally share
    the same base filter (`deleted_at IS NULL`) and the same cursor
    convention (`created_at DESC, id DESC`) as every other equipment query
    in this module, so a checklist row's position is stable across pages
    exactly like every other equipment list.
    """
    base_filters = [Equipment.deleted_at.is_(None)]
    if category_id is not None:
        base_filters.append(Equipment.category_id == category_id)
    if status is not None:
        base_filters.append(Equipment.status == status)
    if department_id is not None:
        base_filters.append(Equipment.department_owner_id == department_id)

    # PR68-Blocker3: the cursor is parsed and validated *before* any query
    # runs (including the count query below) -- a malformed cursor must
    # fail fast with InvalidInputError, not after an already-wasted COUNT
    # against a row set the request will never see.
    cursor_filter = None
    if cursor:
        cursor_dt, cursor_id = decode_cursor(cursor)
        # decode_cursor already rejects a malformed cursor (bad Base64,
        # corrupt JSON, missing fields, unparseable timestamp) as
        # InvalidInputError. The one further parsing step this function
        # performs itself -- cursor_id must be a valid UUID, since it is
        # compared against the native `Uuid`-typed id column below, not a
        # `cast(..., String)` comparison against `str(equipment.id)` (the
        # latter breaks on SQLite, whose `Uuid` type stores/CASTs without
        # dashes while `str(uuid.UUID(...))` always includes them, so the
        # two representations never compare equal and the cursor can never
        # advance past a tie -- the same defect `app.crud.user.
        # list_operators` fixed for its own new cursor, see that
        # function's docstring; `search()` above has this same latent bug
        # in its pre-existing `cast(Equipment.id, String)` comparison,
        # left unfixed there as pre-existing shared infrastructure outside
        # this slice's scope, but fixed directly here since this query is
        # new code introduced by this slice) -- must be validated here
        # too, for the same PR68-Blocker3 reason: an otherwise well-formed
        # cursor whose `id` field is not a real UUID must not escape as an
        # uncaught exception.
        try:
            cursor_uuid = uuid.UUID(cursor_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidInputError("Invalid or malformed pagination cursor.") from exc
        cursor_filter = or_(
            Equipment.created_at < cursor_dt,
            and_(Equipment.created_at == cursor_dt, Equipment.id < cursor_uuid),
        )

    count_stmt = select(func.count()).select_from(Equipment).where(and_(*base_filters))
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = select(Equipment).where(and_(*base_filters))
    if cursor_filter is not None:
        stmt = stmt.where(cursor_filter)
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


# Roadmap PR14A (Backend Audit 4.1): `data` only ever contains keys the
# client explicitly supplied (see EquipmentUpdate/update_equipment's
# exclude_unset=True) -- a key mapped to None here means the client asked
# to clear that field, not that the client omitted it. equipment_name is
# `nullable=False` in the database (app.models.equipment.Equipment) and
# must never be nulled by a PATCH. This only rejects an explicit null;
# blank/whitespace-only string validation is a separate concern left to a
# future focused PR.
REQUIRED_NON_NULL_FIELDS = frozenset({"equipment_name"})

# Roadmap PR14A adjustment #2 (ADR-002): bcm_code/item_no are canonical
# identity fields and have never been clearable via PATCH -- they are not
# immutable in general (canonicalized non-null updates are still allowed,
# see test_bcm_code_update_canonicalization), only non-clearable via an
# explicit null. Previously a null here was silently dropped by the same
# `if value is not None` guard this function used for every field, which
# could produce a misleading audit record showing the submitted null while
# the persisted identifier stayed unchanged. This makes that existing
# non-clearable contract explicit -- a null here is now a rejected
# request, not a silent no-op. Raising before any setattr call below means
# no audit event is ever recorded for the rejected request. Does not alter
# ADR-002 itself.
NON_CLEARABLE_IDENTITY_FIELDS = frozenset({"bcm_code", "item_no"})


async def update(db: AsyncSession, equipment: Equipment, *, data: dict) -> Equipment:
    # Pass 1: validate every incoming field before any mutation occurs.
    for key in REQUIRED_NON_NULL_FIELDS:
        if key in data and data[key] is None:
            raise InvalidInputError(f"'{key}' is required and cannot be cleared.")
    for key in NON_CLEARABLE_IDENTITY_FIELDS:
        if key in data and data[key] is None:
            raise InvalidInputError(f"'{key}' cannot be cleared once assigned.")

    # Pass 2: mutate. Every remaining key/value pair -- including an
    # explicit None on a nullable field (e.g. brand, pm_due_date) -- is
    # now safe to apply: pass 1 already rejected every null this model
    # cannot accept.
    for key, value in data.items():
        setattr(equipment, key, value)
    # Roadmap PR20B (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §24):
    # every successful mutation through this function increments the
    # optimistic-concurrency counter by exactly 1.
    equipment.version += 1
    await db.flush()
    return equipment


async def soft_delete(db: AsyncSession, equipment: Equipment) -> None:
    equipment.deleted_at = datetime.now(timezone.utc)
    # Roadmap PR20B (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §24,
    # fix round 7 H13): soft-delete is a mutation like any other and must
    # not silently bypass the version counter -- a future Equipment Master
    # execute path's CAS predicate also independently requires
    # `deleted_at IS NULL`, but the counter itself must still advance here.
    equipment.version += 1
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
    # Roadmap PR20B (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §24):
    # every status transition through this function -- dispatch, receipt,
    # or manual lifecycle -- is a mutation and must advance the
    # optimistic-concurrency counter, same as any other equipment write.
    equipment.version += 1
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
