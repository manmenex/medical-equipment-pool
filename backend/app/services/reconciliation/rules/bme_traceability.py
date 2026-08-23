"""Roadmap PR22C §23 -- BME_TRACEABILITY_GAP.

OD-PR22-4: `LegacyBMEUserAlias` is read-only input here (§40, never
inserted/updated). No `User` is ever auto-created, no fuzzy name
matching, and this rule never asserts the historical BME actor *is* the
resolved `User` -- it only reports whether a display-only alias exists
for the raw historical name. Raw legacy BME text stays in evidence only
where operationally useful (the raw name itself), never the resolved
identity beyond "an alias exists."
"""

from __future__ import annotations

from ..candidates import FindingCandidate
from ..context import ReconciliationContext

CODE = "BME_TRACEABILITY_GAP"


def evaluate(context: ReconciliationContext) -> tuple[FindingCandidate, ...]:
    candidates: list[FindingCandidate] = []
    for e in context.events:
        if e.legacy_bme_name is None:
            continue
        if e.legacy_bme_name in context.bme_alias_by_raw:
            continue
        candidates.append(
            FindingCandidate(
                code=CODE,
                severity="low",
                equipment_id=e.equipment_id,
                evidence={"legacy_bme_name": e.legacy_bme_name},
                legacy_event_ids=(e.id,),
                sort_key=(str(e.occurred_at), str(e.id)),
            )
        )
    return tuple(candidates)
