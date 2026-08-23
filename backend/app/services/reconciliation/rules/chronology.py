"""Roadmap PR22C §18 -- CHRONOLOGY_ANOMALY.

Coverage-aware: events before `legacy_coverage_start` are never blamed
-- filtered out of the walk entirely, never merely down-weighted.
"Covered history" for this rule is exactly the set of events the unified
projection actually contains (legacy events only ever exist within
`[legacy_coverage_start, legacy_coverage_end]`, by construction of the
governed coverage artifact; modern `BorrowTransaction` rows are always
current/live data, i.e. always within the covered range from
`live_system_start` onward) -- so no separate "is this instant inside
the gap window" check is needed: the gap between `legacy_coverage_end`
and `live_system_start` (when one exists, OD-PR22-7) naturally contains
zero projected events, and this walk only ever reasons about events that
exist.

A deterministic finite-state walk per equipment over the coverage-
filtered, already-sorted projection:
  - a RECEIVE while not currently "issued" -> orphan RECEIVE (no prior
    ISSUE in covered history);
  - an ISSUE while already "issued" -> overlapping/impossible ordering;
  - after the walk, still "issued" -> ISSUE with no later RECEIVE in
    covered history.
Never phrased as "missing forever" -- evidence always names the covered
range this conclusion is scoped to.
"""

from __future__ import annotations

from ..candidates import FindingCandidate, HistoryProjectionEvent
from ..context import ReconciliationContext

CODE = "CHRONOLOGY_ANOMALY"


def _evidence_base(context: ReconciliationContext) -> dict:
    return {
        "legacy_coverage_start": context.legacy_coverage_start.isoformat(),
        "legacy_coverage_end": context.legacy_coverage_end.isoformat(),
        "live_system_start": context.live_system_start.isoformat(),
    }


def _event_ids(ev: HistoryProjectionEvent) -> tuple:
    return (ev.legacy_event_id,) if ev.legacy_event_id is not None else ()


def evaluate(context: ReconciliationContext) -> tuple[FindingCandidate, ...]:
    base_evidence = _evidence_base(context)
    candidates: list[FindingCandidate] = []

    for equipment_id in sorted(context.projection_by_equipment, key=str):
        events = [
            ev for ev in context.projection_by_equipment[equipment_id] if ev.occurred_at >= context.legacy_coverage_start
        ]
        if not events:
            continue

        issued = False
        last_issue: HistoryProjectionEvent | None = None
        for ev in events:
            if ev.event_kind == "ISSUE":
                if issued:
                    candidates.append(
                        FindingCandidate(
                            code=CODE,
                            severity="high",
                            equipment_id=equipment_id,
                            evidence={
                                **base_evidence,
                                "reason_code": "overlapping_issue",
                                "prior_event_source": last_issue.source_kind if last_issue else None,
                                "next_event_source": ev.source_kind,
                                "occurred_at": ev.occurred_at.isoformat(),
                            },
                            legacy_event_ids=_event_ids(last_issue) + _event_ids(ev) if last_issue else _event_ids(ev),
                            sort_key=(str(equipment_id), str(ev.occurred_at), "overlapping_issue"),
                        )
                    )
                issued = True
                last_issue = ev
            else:  # RECEIVE
                if not issued:
                    candidates.append(
                        FindingCandidate(
                            code=CODE,
                            severity="high",
                            equipment_id=equipment_id,
                            evidence={
                                **base_evidence,
                                "reason_code": "orphan_receive",
                                "next_event_source": ev.source_kind,
                                "occurred_at": ev.occurred_at.isoformat(),
                            },
                            legacy_event_ids=_event_ids(ev),
                            sort_key=(str(equipment_id), str(ev.occurred_at), "orphan_receive"),
                        )
                    )
                issued = False
                last_issue = None

        if issued and last_issue is not None:
            candidates.append(
                FindingCandidate(
                    code=CODE,
                    severity="medium",
                    equipment_id=equipment_id,
                    evidence={
                        **base_evidence,
                        "reason_code": "no_later_receive_in_covered_history",
                        "prior_event_source": last_issue.source_kind,
                        "occurred_at": last_issue.occurred_at.isoformat(),
                    },
                    legacy_event_ids=_event_ids(last_issue),
                    sort_key=(str(equipment_id), str(last_issue.occurred_at), "no_later_receive_in_covered_history"),
                )
            )

    return tuple(candidates)
