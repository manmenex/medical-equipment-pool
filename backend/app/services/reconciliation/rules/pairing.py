"""Roadmap PR22C §24, OD-PR22-1 -- PAIRING_CANDIDATE.

PR21 deliberately never pairs Issue/Receive legacy events (event-first
architecture) -- pairing is reconciliation-artifact-only, produced here
as an open finding (`disposition = NULL`), never a mutation of the
source events and never a fabricated `BorrowTransaction` (§2). A later
human review (PR22D) may dispose a `PAIRING_CANDIDATE` finding
`confirmed_valid`, meaning the candidate relationship was reviewed and
accepted -- there is no `confirmed_pair` value (OD-PR22-2, §34) and this
module never assigns a disposition itself.

Only *legacy* ISSUE/RECEIVE events are considered (a modern
`BorrowTransaction` row already carries its own unambiguous issue/
receive pairing internally -- nothing to propose there). Every legacy
ISSUE within the covered window is a candidate for pairing, regardless
of whether `chronology.evaluate` separately flags its own ordering as
anomalous or not -- PR21 never links Issue/Receive events at all, so an
ordinary, chronologically-unremarkable ISSUE-then-RECEIVE sequence is
exactly the primary case a pairing candidate should be proposed for,
not an exception to it.

The matching predicate requires **two independent, non-trivial
dimensions to agree simultaneously** -- `resolved_ward_id` AND
`legacy_order_reference`, both non-null and equal on both sides. Ward
alone, order-reference alone, nearest-timestamp alone, or BCM/equipment
alone are each explicitly insufficient per §24. If more than one
candidate on either side would satisfy the predicate, the match is
ambiguous and no candidate is created for that event at all -- never a
fuzzy tie-break.
"""

from __future__ import annotations

from ..candidates import FindingCandidate, LegacyEventSnapshot
from ..context import ReconciliationContext

CODE = "PAIRING_CANDIDATE"


def _split_issues_and_receives(
    events: tuple[LegacyEventSnapshot, ...],
) -> tuple[list[LegacyEventSnapshot], list[LegacyEventSnapshot]]:
    issues = [e for e in events if e.event_type == "ISSUE"]
    receives = [e for e in events if e.event_type == "RECEIVE"]
    return issues, receives


def _matches(issue: LegacyEventSnapshot, receive: LegacyEventSnapshot) -> bool:
    if receive.occurred_at <= issue.occurred_at:
        return False
    if issue.resolved_ward_id is None or issue.resolved_ward_id != receive.resolved_ward_id:
        return False
    if issue.legacy_order_reference is None or issue.legacy_order_reference != receive.legacy_order_reference:
        return False
    return True


def evaluate(context: ReconciliationContext) -> tuple[FindingCandidate, ...]:
    by_equipment: dict = {}
    for e in context.events:
        by_equipment.setdefault(e.equipment_id, []).append(e)

    candidates: list[FindingCandidate] = []
    for equipment_id in sorted(by_equipment, key=str):
        events = tuple(
            e for e in by_equipment[equipment_id] if e.occurred_at >= context.legacy_coverage_start
        )
        issues, receives = _split_issues_and_receives(events)

        for issue in sorted(issues, key=lambda e: (str(e.occurred_at), str(e.id))):
            matches = [r for r in receives if _matches(issue, r)]
            if len(matches) != 1:
                continue
            receive = matches[0]
            # Ambiguity check the other direction too -- exactly one
            # issue must also match this receive, otherwise the pairing
            # is not uniquely determined from either side.
            reverse_matches = [i for i in issues if _matches(i, receive)]
            if len(reverse_matches) != 1:
                continue

            candidates.append(
                FindingCandidate(
                    code=CODE,
                    severity="low",
                    equipment_id=equipment_id,
                    evidence={
                        "matched_fields": ["resolved_ward_id", "legacy_order_reference"],
                        "issue_occurred_at": issue.occurred_at.isoformat(),
                        "receive_occurred_at": receive.occurred_at.isoformat(),
                        "resolved_ward_id": str(issue.resolved_ward_id),
                        "legacy_order_reference": issue.legacy_order_reference,
                    },
                    legacy_event_ids=(issue.id, receive.id),
                    sort_key=(str(equipment_id), str(issue.occurred_at), str(issue.id)),
                )
            )

    return tuple(candidates)
