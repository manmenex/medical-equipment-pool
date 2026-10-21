"""Roadmap PR22C §19/§47/§48 -- the unified legacy + modern history
projection.

Sources: `LegacyEquipmentEvent` (`event_type` ISSUE/RECEIVE) and
`BorrowTransaction` (`borrowed_at` always present -> one `modern_issue`
projected event; `returned_at` set -> one additional `modern_receive`
projected event -- never inferred from `created_at`/`updated_at`, only
from the actual `borrowed_at`/`returned_at` fields, per §48). The two
tables are never physically merged -- this module only ever produces an
in-memory, read-only `tuple[HistoryProjectionEvent, ...]`; nothing here
writes to the database.

**OD-PR22-7 temporal scope, enforced here and only here (Fix Round 1):**
a `LegacyEquipmentEvent` may exist outside `[legacy_coverage_start,
legacy_coverage_end]` (nothing in PR21's own schema prevents it -- the
coverage window is a governance artifact, not a DB constraint on the
event table), and a `BorrowTransaction` may straddle `live_system_start`
(it is ordinary live operational data, not scoped to any particular
run). Every consumer of this module's output -- every rule module, via
`ReconciliationContext.events`/`.projection`/`.projection_by_equipment`
-- therefore receives an *already* temporally-scoped result and must
never reapply or reinterpret the coverage window itself (§8 of this
fix round's own instructions): `load_legacy_events` only ever returns
rows with `legacy_coverage_start <= occurred_at <= legacy_coverage_end`
(inclusive both ends), and `build_projection` only ever emits a
`modern_issue`/`modern_receive` event when its own individual instant
(`borrowed_at`/`returned_at` respectively) is `>= live_system_start` --
never the whole `BorrowTransaction` row admitted or rejected as one
unit, since one row's `borrowed_at` and `returned_at` can straddle
`live_system_start` independently (§6 of this fix round).

Set-based, batch queries only (§30): one `SELECT` for the legacy events
belonging to the run's migration authority (temporally bounded in SQL,
never loaded unbounded and then Python-filtered), one `SELECT` for every
`BorrowTransaction` whose `equipment_id` is referenced by at least one of
those legacy events (also temporally pre-filtered in SQL to the rows
that could possibly contribute an in-scope event -- see
`load_transactions_for_equipment`'s own docstring for why a final
per-synthesized-event check in `build_projection` is still required and
is not "loading everything then Python-filtering") -- never a
per-equipment or per-event query.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legacy_history import LegacyEquipmentEvent
from app.models.transaction import BorrowTransaction

from .candidates import HistoryProjectionEvent, LegacyEventSnapshot, TransactionSnapshot


async def load_legacy_events(
    db: AsyncSession,
    *,
    migration_authority_id: uuid.UUID,
    legacy_coverage_start: datetime,
    legacy_coverage_end: datetime,
) -> tuple[LegacyEventSnapshot, ...]:
    """One bulk `SELECT` for every `LegacyEquipmentEvent` under the given
    migration authority that also falls inside the run's own approved
    `[legacy_coverage_start, legacy_coverage_end]` window (inclusive both
    ends, OD-PR22-7) -- the temporal predicate is pushed into the SQL
    `WHERE` clause itself, never applied after an unbounded load. An
    event outside this window structurally cannot participate in this
    run's analysis at all (§8/§13/§14 of Fix Round 1) -- it is not
    merely down-weighted or filtered later by an individual rule.
    Ordered deterministically (occurred_at, id) so downstream consumers
    never depend on DB natural row order (§11/§30)."""
    rows = (
        await db.execute(
            select(LegacyEquipmentEvent)
            .where(
                LegacyEquipmentEvent.migration_authority_id == migration_authority_id,
                LegacyEquipmentEvent.occurred_at >= legacy_coverage_start,
                LegacyEquipmentEvent.occurred_at <= legacy_coverage_end,
            )
            .order_by(LegacyEquipmentEvent.occurred_at, LegacyEquipmentEvent.id)
        )
    ).scalars().all()
    return tuple(
        LegacyEventSnapshot(
            id=r.id,
            equipment_id=r.equipment_id,
            event_type=r.event_type,
            occurred_at=r.occurred_at,
            legacy_source_row_key=r.legacy_source_row_key,
            legacy_order_reference=r.legacy_order_reference,
            legacy_ward_text=r.legacy_ward_text,
            resolved_ward_id=r.resolved_ward_id,
            legacy_bme_name=r.legacy_bme_name,
            migration_authority_id=r.migration_authority_id,
            import_session_id=r.import_session_id,
            import_source_id=r.import_source_id,
        )
        for r in rows
    )


async def load_transactions_for_equipment(
    db: AsyncSession, *, equipment_ids: frozenset[uuid.UUID], live_system_start: datetime
) -> tuple[TransactionSnapshot, ...]:
    """One bulk `SELECT ... WHERE equipment_id IN (...)` for every
    `BorrowTransaction` touching the given equipment set that could
    *possibly* contribute at least one in-scope projected event -- never
    one query per equipment (§30), and never an unbounded load of every
    historical transaction for these equipment (§22 of Fix Round 1).

    A single `BorrowTransaction` row can generate up to two projected
    events (`modern_issue` from `borrowed_at`, `modern_receive` from
    `returned_at`) whose individual instants can straddle
    `live_system_start` independently -- e.g. `borrowed_at` before,
    `returned_at` after. The row therefore cannot be admitted or
    rejected as a single unit by one timestamp predicate; the SQL filter
    here (`borrowed_at >= live_system_start OR returned_at >=
    live_system_start`) only prunes rows that cannot contribute *any*
    in-scope event at all (both instants before `live_system_start`, or
    an open transaction whose only instant, `borrowed_at`, is before
    it). `build_projection` still applies the final, per-synthesized-
    event `>= live_system_start` check before emitting each one
    individually -- this is row-level SQL pruning followed by a
    necessarily event-level split, not "load everything, then
    Python-filter" (§6/§22)."""
    if not equipment_ids:
        return ()
    rows = (
        await db.execute(
            select(BorrowTransaction)
            .where(
                BorrowTransaction.equipment_id.in_(equipment_ids),
                or_(
                    BorrowTransaction.borrowed_at >= live_system_start,
                    BorrowTransaction.returned_at >= live_system_start,
                ),
            )
            .order_by(BorrowTransaction.borrowed_at, BorrowTransaction.id)
        )
    ).scalars().all()
    return tuple(
        TransactionSnapshot(
            id=r.id,
            equipment_id=r.equipment_id,
            status=r.status.value if hasattr(r.status, "value") else r.status,
            borrowed_at=r.borrowed_at,
            returned_at=r.returned_at,
            ward_id=r.ward_id,
        )
        for r in rows
    )


def build_projection(
    *,
    legacy_events: tuple[LegacyEventSnapshot, ...],
    transactions: tuple[TransactionSnapshot, ...],
    live_system_start: datetime,
) -> tuple[HistoryProjectionEvent, ...]:
    """Pure, in-memory normalization -- no DB access. `legacy_events` is
    trusted to already be bounded to `[legacy_coverage_start,
    legacy_coverage_end]` by `load_legacy_events`'s own SQL predicate --
    every one of them becomes exactly one projected event
    (`legacy_issue`/`legacy_receive`), unconditionally.

    Each `BorrowTransaction` becomes a `modern_issue` event (from
    `borrowed_at`) only when `borrowed_at >= live_system_start`, and,
    independently, a `modern_receive` event (from `returned_at`) only
    when `returned_at` is set AND `returned_at >= live_system_start`
    (OD-PR22-7, Fix Round 1 §6) -- never inferred from any other field
    (§48). A row can therefore legitimately contribute zero, one, or two
    projected events: e.g. `borrowed_at` before `live_system_start` and
    `returned_at` after it emits `modern_receive` alone, never
    `modern_issue`, and never the whole row dropped. Sorted by
    `HistoryProjectionEvent.sort_key` for a fully deterministic output
    order (§11)."""
    events: list[HistoryProjectionEvent] = []

    for e in legacy_events:
        events.append(
            HistoryProjectionEvent(
                source_kind="legacy_issue" if e.event_type == "ISSUE" else "legacy_receive",
                equipment_id=e.equipment_id,
                event_kind=e.event_type,
                occurred_at=e.occurred_at,
                ward_id=e.resolved_ward_id,
                legacy_event_id=e.id,
                modern_transaction_id=None,
                authority_id=e.migration_authority_id,
            )
        )

    for t in transactions:
        if t.borrowed_at >= live_system_start:
            events.append(
                HistoryProjectionEvent(
                    source_kind="modern_issue",
                    equipment_id=t.equipment_id,
                    event_kind="ISSUE",
                    occurred_at=t.borrowed_at,
                    ward_id=t.ward_id,
                    legacy_event_id=None,
                    modern_transaction_id=t.id,
                    authority_id=None,
                )
            )
        if t.returned_at is not None and t.returned_at >= live_system_start:
            events.append(
                HistoryProjectionEvent(
                    source_kind="modern_receive",
                    equipment_id=t.equipment_id,
                    event_kind="RECEIVE",
                    occurred_at=t.returned_at,
                    ward_id=t.ward_id,
                    legacy_event_id=None,
                    modern_transaction_id=t.id,
                    authority_id=None,
                )
            )

    events.sort(key=lambda ev: ev.sort_key)
    return tuple(events)


def group_by_equipment(
    projection: tuple[HistoryProjectionEvent, ...],
) -> dict[uuid.UUID, tuple[HistoryProjectionEvent, ...]]:
    """Groups an already-sorted projection by `equipment_id`, preserving
    the deterministic order within each group -- a single pass, never a
    per-equipment query or filter (§30)."""
    grouped: dict[uuid.UUID, list[HistoryProjectionEvent]] = {}
    for ev in projection:
        grouped.setdefault(ev.equipment_id, []).append(ev)
    return {eid: tuple(evs) for eid, evs in grouped.items()}
