"""Roadmap PR22C §22 -- WARD_TRACEABILITY_GAP.

Reuses `LegacyWardAlias` (read-only, §40) -- never creates one. No
fuzzy Ward matching; resolution is the plain-equality lookup
`LegacyWardAlias` itself already implements. `resolved_ward_id` being
set on the event is the actual traceability signal (PR21's own import
already resolved it, alias or not) -- a gap is any event with no
resolved Ward at all.
"""

from __future__ import annotations

from ..candidates import FindingCandidate
from ..context import ReconciliationContext

CODE = "WARD_TRACEABILITY_GAP"


def evaluate(context: ReconciliationContext) -> tuple[FindingCandidate, ...]:
    candidates: list[FindingCandidate] = []
    for e in context.events:
        if e.resolved_ward_id is not None:
            continue
        alias_exists = e.legacy_ward_text is not None and e.legacy_ward_text in context.ward_alias_by_raw
        candidates.append(
            FindingCandidate(
                code=CODE,
                severity="low",
                equipment_id=e.equipment_id,
                evidence={
                    "legacy_ward_text": e.legacy_ward_text,
                    "alias_exists_but_unresolved": alias_exists,
                },
                legacy_event_ids=(e.id,),
                sort_key=(str(e.occurred_at), str(e.id)),
            )
        )
    return tuple(candidates)
