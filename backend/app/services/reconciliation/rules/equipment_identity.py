"""Roadmap PR22C §14 -- EQUIPMENT_IDENTITY.

Verifies that Equipment referenced by imported legacy history still has
a durable, machine-checkable identity anchor. The only identity anchor
this schema carries independently of the FK-resolved `equipment_id`
itself (already proven to exist by the foreign key) is `Equipment.
bcm_code`/`Equipment.item_no` -- so the deterministic, non-fabricated
check this rule performs is: does the referenced Equipment have *at
least one* of them set? An Equipment row with neither is not currently
traceable by any durable code, which is a real EQUIPMENT_IDENTITY
concern for reconciliation, not update/repair of Equipment (never
attempted here -- §2/§14 explicitly forbid it).

One finding per Equipment (deduplicated across every event referencing
it), never one per event.

Scope (Fix Round 1 §14): "every event referencing it" means every event
in `context.events`, which is already bounded to this run's approved
`[legacy_coverage_start, legacy_coverage_end]` window by
`app.services.reconciliation.projection.load_legacy_events` -- an event
outside that window never contributes to this run's finding set, same
as every other rule in this package.
"""

from __future__ import annotations

from ..candidates import FindingCandidate
from ..context import ReconciliationContext

CODE = "EQUIPMENT_IDENTITY"


def evaluate(context: ReconciliationContext) -> tuple[FindingCandidate, ...]:
    equipment_ids_with_events: dict = {}
    for e in context.events:
        equipment_ids_with_events.setdefault(e.equipment_id, []).append(e.id)

    candidates: list[FindingCandidate] = []
    for equipment_id in sorted(equipment_ids_with_events, key=str):
        eq = context.equipment_by_id.get(equipment_id)
        if eq is None:
            continue
        if eq.bcm_code is not None or eq.item_no is not None:
            continue
        event_ids = tuple(sorted(equipment_ids_with_events[equipment_id], key=str))
        candidates.append(
            FindingCandidate(
                code=CODE,
                severity="medium",
                equipment_id=equipment_id,
                evidence={
                    "reason_code": "no_bcm_or_item_no",
                    "equipment_asset_number": eq.asset_number,
                    "referencing_legacy_event_count": len(event_ids),
                },
                legacy_event_ids=event_ids,
                sort_key=(str(equipment_id),),
            )
        )
    return tuple(candidates)
