"""Roadmap PR22C -- assembles the single immutable `ReconciliationContext`
every rule module reads from. Building this context is the *only* place
`app.services.reconciliation.engine` reads application data inside the
`REPEATABLE READ` analysis transaction (§6) -- every `SELECT` this module
issues therefore shares that one consistent snapshot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment
from app.models.legacy_history import LegacyEquipmentEvent, LegacyEquipmentEventSourceRef, LegacyWardAlias
from app.models.legacy_reconciliation import LegacyBMEUserAlias, LegacyReconciliationRun

from . import projection as projection_mod
from .candidates import EquipmentSnapshot, HistoryProjectionEvent, LegacyEventSnapshot, SourceRefSnapshot


@dataclass(frozen=True)
class ReconciliationContext:
    run_id: uuid.UUID
    rule_version: str
    migration_authority_id: uuid.UUID
    legacy_coverage_start: object
    legacy_coverage_end: object
    live_system_start: object
    events: tuple[LegacyEventSnapshot, ...]
    source_refs_by_event: dict[uuid.UUID, tuple[SourceRefSnapshot, ...]]
    equipment_by_id: dict[uuid.UUID, EquipmentSnapshot]
    ward_alias_by_raw: dict[str, uuid.UUID]
    bme_alias_by_raw: dict[str, uuid.UUID]
    projection: tuple[HistoryProjectionEvent, ...]
    projection_by_equipment: dict[uuid.UUID, tuple[HistoryProjectionEvent, ...]]


async def build_context(
    db: AsyncSession, *, run: LegacyReconciliationRun, migration_authority_id: uuid.UUID
) -> ReconciliationContext:
    """Loads every input the rule modules need, as a set of bulk, batch
    queries (§30) -- never a per-event or per-equipment query. Called
    exactly once per run execution, inside the `REPEATABLE READ`
    transaction `app.services.reconciliation.engine` opens for TX2.
    `migration_authority_id` is resolved by the caller from the run's
    bound coverage artifact (§38's own coverage-integrity check already
    loads that row, so it is passed in here rather than re-queried).

    OD-PR22-7 (Fix Round 1): `run.legacy_coverage_start`/`legacy_
    coverage_end`/`live_system_start` -- already verified by the
    caller's own coverage-integrity check (§38) to match the run's bound
    coverage artifact -- are the sole source of the temporal scope
    enforced here, passed straight into `projection.load_legacy_events`/
    `load_transactions_for_equipment`/`build_projection`. No other
    boundary value (observed MIN/MAX, import time, `created_at`) is ever
    substituted."""
    events = await projection_mod.load_legacy_events(
        db,
        migration_authority_id=migration_authority_id,
        legacy_coverage_start=run.legacy_coverage_start,
        legacy_coverage_end=run.legacy_coverage_end,
    )

    event_ids = tuple(e.id for e in events)
    source_refs_by_event: dict[uuid.UUID, list[SourceRefSnapshot]] = {}
    if event_ids:
        ref_rows = (
            await db.execute(
                select(LegacyEquipmentEventSourceRef)
                .where(LegacyEquipmentEventSourceRef.legacy_equipment_event_id.in_(event_ids))
                .order_by(LegacyEquipmentEventSourceRef.sheet_name, LegacyEquipmentEventSourceRef.source_row_number)
            )
        ).scalars().all()
        for r in ref_rows:
            source_refs_by_event.setdefault(r.legacy_equipment_event_id, []).append(
                SourceRefSnapshot(
                    id=r.id,
                    legacy_equipment_event_id=r.legacy_equipment_event_id,
                    sheet_name=r.sheet_name,
                    source_row_number=r.source_row_number,
                    source_checksum=r.source_checksum,
                )
            )
    frozen_source_refs = {k: tuple(v) for k, v in source_refs_by_event.items()}

    equipment_ids = frozenset(e.equipment_id for e in events)
    equipment_by_id: dict[uuid.UUID, EquipmentSnapshot] = {}
    if equipment_ids:
        eq_rows = (await db.execute(select(Equipment).where(Equipment.id.in_(equipment_ids)))).scalars().all()
        for eq in eq_rows:
            equipment_by_id[eq.id] = EquipmentSnapshot(
                id=eq.id,
                status=eq.status.value if hasattr(eq.status, "value") else eq.status,
                asset_number=eq.asset_number,
                bcm_code=eq.bcm_code,
                item_no=eq.item_no,
            )

    transactions = await projection_mod.load_transactions_for_equipment(
        db, equipment_ids=equipment_ids, live_system_start=run.live_system_start
    )
    proj = projection_mod.build_projection(
        legacy_events=events, transactions=transactions, live_system_start=run.live_system_start
    )
    proj_by_equipment = projection_mod.group_by_equipment(proj)

    # §22/§40: read-only inputs -- PR22C never inserts/updates/deletes
    # either alias table.
    ward_alias_rows = (await db.execute(select(LegacyWardAlias))).scalars().all()
    ward_alias_by_raw = {r.raw_alias: r.ward_id for r in ward_alias_rows}

    bme_alias_rows = (await db.execute(select(LegacyBMEUserAlias))).scalars().all()
    bme_alias_by_raw = {r.raw_bme_name: r.resolved_user_id for r in bme_alias_rows}

    return ReconciliationContext(
        run_id=run.id,
        rule_version=run.rule_version,
        migration_authority_id=migration_authority_id,
        legacy_coverage_start=run.legacy_coverage_start,
        legacy_coverage_end=run.legacy_coverage_end,
        live_system_start=run.live_system_start,
        events=events,
        source_refs_by_event=frozen_source_refs,
        equipment_by_id=equipment_by_id,
        ward_alias_by_raw=ward_alias_by_raw,
        bme_alias_by_raw=bme_alias_by_raw,
        projection=proj,
        projection_by_equipment=proj_by_equipment,
    )
