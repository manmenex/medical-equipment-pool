"""Roadmap PR22C §15 -- SOURCE_PROVENANCE.

Verifies that every persisted `LegacyEquipmentEvent` still has durable
provenance -- at least one `LegacyEquipmentEventSourceRef` row (PR21's
own contract, §8.1/§26 of the PR21 design). This rule never modifies
provenance; evidence points to the exact event/source references
involved, never a workbook blob.

Scope (Fix Round 1 §13): this rule validates provenance only for events
within this *run's* approved `[legacy_coverage_start, legacy_coverage_
end]` window, i.e. `context.events` as bounded by
`app.services.reconciliation.projection.load_legacy_events` -- it is a
per-run reconciliation finding, not a standalone dataset-wide integrity
sweep over every `LegacyEquipmentEvent` a migration authority has ever
recorded. An event outside this run's window is simply not evaluated by
this run at all (it may be, or have been, evaluated by a different run
whose own coverage includes it).
"""

from __future__ import annotations

from ..candidates import FindingCandidate
from ..context import ReconciliationContext

CODE = "SOURCE_PROVENANCE"


def evaluate(context: ReconciliationContext) -> tuple[FindingCandidate, ...]:
    candidates: list[FindingCandidate] = []
    for e in context.events:
        refs = context.source_refs_by_event.get(e.id, ())
        if refs:
            continue
        candidates.append(
            FindingCandidate(
                code=CODE,
                severity="high",
                equipment_id=e.equipment_id,
                evidence={
                    "reason_code": "no_source_ref",
                    "legacy_source_row_key": e.legacy_source_row_key,
                    "event_type": e.event_type,
                    "import_session_id": str(e.import_session_id),
                    "import_source_id": str(e.import_source_id),
                },
                legacy_event_ids=(e.id,),
                sort_key=(str(e.occurred_at), str(e.id)),
            )
        )
    return tuple(candidates)
