"""Roadmap PR21D2 -- Historical Event Execution. CRUD helpers for the
permanent, append-only `LegacyEquipmentEvent`/`LegacyEquipmentEventSourceRef`
tables (Roadmap PR21A schema, GitHub PR #103). No function here issues an
`UPDATE` against either table -- both are immutable-by-convention once
written (see `app.models.legacy_history.LegacyEquipmentEvent`'s own
docstring); execution only ever inserts new rows or reads existing ones
for idempotency verification, never mutates a previously-written row."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legacy_history import LegacyEquipmentEvent, LegacyEquipmentEventSourceRef


async def bulk_get_existing_by_identity(
    db: AsyncSession, *, migration_authority_id: uuid.UUID
) -> dict[tuple[str, str], LegacyEquipmentEvent]:
    """One bulk query for every already-persisted event under this
    authority, keyed by `(event_type, legacy_source_row_key)` -- the
    identity tuple `uq_legacy_equipment_events_identity` enforces
    (together with `migration_authority_id`, held constant here). Scoped
    to a single `migration_authority_id` (never all events database-wide)
    -- bounded by the same admission cap the persisted plan itself was
    already validated against (§25 of the PR21D2 task), so this is never
    an unbounded scan. Used once, at the start of `execute()`'s own
    per-row loop, so no per-row `SELECT` is ever issued for the common
    (non-colliding) case."""
    rows = (
        (
            await db.execute(
                select(LegacyEquipmentEvent).where(
                    LegacyEquipmentEvent.migration_authority_id == migration_authority_id
                )
            )
        )
        .scalars()
        .all()
    )
    return {(row.event_type, row.legacy_source_row_key): row for row in rows}


async def get_source_refs_for_event(
    db: AsyncSession, *, legacy_equipment_event_id: uuid.UUID
) -> list[LegacyEquipmentEventSourceRef]:
    """Targeted lookup used only on the rare identity-collision path, to
    compare an existing event's own persisted provenance against the
    colliding plan row's own source references (§10 of the PR21D2 task's
    equivalence set: "permanent provenance identity required by the
    plan") -- never called on the common, non-colliding insert path."""
    return list(
        (
            await db.execute(
                select(LegacyEquipmentEventSourceRef).where(
                    LegacyEquipmentEventSourceRef.legacy_equipment_event_id == legacy_equipment_event_id
                )
            )
        )
        .scalars()
        .all()
    )


async def bulk_insert_events(db: AsyncSession, events: list[LegacyEquipmentEvent]) -> None:
    """One batched insert for a bounded chunk of new events -- never one
    `INSERT` per row. Callers are responsible for their own batch sizing
    (§24 of the PR21D2 task: bounding SQLAlchemy session/parameter growth
    for a ~51,464-row combined dataset)."""
    if not events:
        return
    db.add_all(events)
    await db.flush()


async def bulk_insert_source_refs(db: AsyncSession, refs: list[LegacyEquipmentEventSourceRef]) -> None:
    """One batched insert for a bounded chunk of new provenance refs --
    same batching discipline as `bulk_insert_events` above."""
    if not refs:
        return
    db.add_all(refs)
    await db.flush()
