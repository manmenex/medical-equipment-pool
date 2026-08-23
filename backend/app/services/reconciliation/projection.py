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

Set-based, batch queries only (§30): one `SELECT` for the legacy events
belonging to the run's migration authority, one `SELECT` for every
`BorrowTransaction` whose `equipment_id` is referenced by at least one of
those legacy events -- never a per-equipment or per-event query.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legacy_history import LegacyEquipmentEvent
from app.models.transaction import BorrowTransaction

from .candidates import HistoryProjectionEvent, LegacyEventSnapshot, TransactionSnapshot


async def load_legacy_events(db: AsyncSession, *, migration_authority_id: uuid.UUID) -> tuple[LegacyEventSnapshot, ...]:
    """One bulk `SELECT` for every `LegacyEquipmentEvent` under the given
    migration authority -- the full set this run's analysis is scoped to.
    Ordered deterministically (occurred_at, id) so downstream consumers
    never depend on DB natural row order (§11/§30)."""
    rows = (
        await db.execute(
            select(LegacyEquipmentEvent)
            .where(LegacyEquipmentEvent.migration_authority_id == migration_authority_id)
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
    db: AsyncSession, *, equipment_ids: frozenset[uuid.UUID]
) -> tuple[TransactionSnapshot, ...]:
    """One bulk `SELECT ... WHERE equipment_id IN (...)` for every
    `BorrowTransaction` touching the given equipment set -- never one
    query per equipment (§30). Empty input returns an empty tuple without
    issuing a query."""
    if not equipment_ids:
        return ()
    rows = (
        await db.execute(
            select(BorrowTransaction)
            .where(BorrowTransaction.equipment_id.in_(equipment_ids))
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
) -> tuple[HistoryProjectionEvent, ...]:
    """Pure, in-memory normalization -- no DB access. Every
    `LegacyEquipmentEvent` becomes exactly one projected event
    (`legacy_issue`/`legacy_receive`); every `BorrowTransaction` becomes
    one `modern_issue` event (from `borrowed_at`, always present) and,
    only when `returned_at` is set, one additional `modern_receive` event
    -- never inferred from any other field (§48). Sorted by
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
        if t.returned_at is not None:
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
