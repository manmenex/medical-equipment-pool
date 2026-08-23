"""Roadmap PR22C §21/§49 -- CURRENT_STATE_MISMATCH.

A signal only -- Equipment is never mutated by this rule or by anything
else in this package (§2/§35). Compares current `Equipment.status`
against the terminal state implied by the *full* unified history
projection (legacy + modern) for that equipment, never the last legacy
event alone. `context.projection_by_equipment` is already temporally
scoped by `app.services.reconciliation.projection.build_projection`
(OD-PR22-7, Fix Round 1) -- a legacy event after `legacy_coverage_end`
or a modern event before `live_system_start` cannot appear in it, so
this rule never reapplies its own boundary filter on top.

`unavailable_defective`/`decommissioned` are treated conservatively and
never flagged: those are legitimate independent lifecycle transitions
this reconciliation history cannot see or explain, not automatically an
error merely because the issue/receive history implies something else
(§21's explicit "do not assume reconciliation history must override
legitimate later lifecycle changes").
"""

from __future__ import annotations

from ..candidates import FindingCandidate, HistoryProjectionEvent
from ..context import ReconciliationContext

CODE = "CURRENT_STATE_MISMATCH"

_CONSERVATIVE_STATUSES = frozenset({"unavailable_defective", "decommissioned"})


def _terminal_signal(events: tuple[HistoryProjectionEvent, ...]) -> tuple[str, HistoryProjectionEvent] | None:
    """Returns (expected_status_signal, terminal_event) from the
    coverage-filtered projection, or None if there is no history at all
    to derive a signal from."""
    if not events:
        return None
    terminal = events[-1]
    if terminal.event_kind == "ISSUE":
        return "issued_to_ward", terminal
    return "available_at_pool", terminal


def evaluate(context: ReconciliationContext) -> tuple[FindingCandidate, ...]:
    candidates: list[FindingCandidate] = []

    for equipment_id in sorted(context.projection_by_equipment, key=str):
        eq = context.equipment_by_id.get(equipment_id)
        if eq is None or eq.status in _CONSERVATIVE_STATUSES:
            continue

        # Already temporally scoped by `build_projection` -- see this
        # module's own docstring. No filter is reapplied here.
        events = context.projection_by_equipment[equipment_id]
        signal = _terminal_signal(events)
        if signal is None:
            continue
        expected_status, terminal = signal
        if expected_status == eq.status:
            continue

        legacy_event_ids = (terminal.legacy_event_id,) if terminal.legacy_event_id is not None else ()
        candidates.append(
            FindingCandidate(
                code=CODE,
                severity="medium",
                equipment_id=equipment_id,
                evidence={
                    "expected_state_signal": expected_status,
                    "actual_equipment_status": eq.status,
                    "terminal_history_source": terminal.source_kind,
                    "terminal_history_at": terminal.occurred_at.isoformat(),
                },
                legacy_event_ids=legacy_event_ids,
                sort_key=(str(equipment_id), str(terminal.occurred_at)),
            )
        )

    return tuple(candidates)
