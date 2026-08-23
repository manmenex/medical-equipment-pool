"""Roadmap PR22C §25/§26/§28 -- the sole place `FindingCandidate` objects
become `LegacyReconciliationFinding`/`LegacyReconciliationFindingEvent`
ORM rows. No rule module writes to the database directly (§9); this
module never sets `disposition`/`disposed_by_user_id`/`disposed_at`
(always left `NULL` -- that is PR22D/E's exclusive job, §25), and never
commits or rolls back -- the caller (`app.services.reconciliation.
engine`) owns the transaction boundary.

Bulk-inserts every finding and every finding-event junction row in one
pass (no per-row round trip, §30) -- ids are generated client-side so
the junction rows can be constructed together with their findings,
without an intermediate flush.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.legacy_reconciliation import LegacyReconciliationFinding, LegacyReconciliationFindingEvent

from .candidates import FindingCandidate


@dataclass(frozen=True)
class PersistedSummary:
    total_findings: int
    high: int
    medium: int
    low: int


def sort_candidates(candidates: tuple[FindingCandidate, ...]) -> tuple[FindingCandidate, ...]:
    """§11/§26: one fully deterministic combined order across every
    rule's output -- by `code` first (so the persisted order is stable
    regardless of which order the engine invoked the rule modules in),
    then each candidate's own `sort_key`."""
    return tuple(sorted(candidates, key=lambda c: (c.code, c.sort_key)))


async def persist_findings(
    db: AsyncSession, *, run_id: uuid.UUID, rule_version: str, candidates: tuple[FindingCandidate, ...]
) -> PersistedSummary:
    ordered = sort_candidates(candidates)

    high = medium = low = 0
    for candidate in ordered:
        finding_id = uuid.uuid4()
        db.add(
            LegacyReconciliationFinding(
                id=finding_id,
                run_id=run_id,
                code=candidate.code,
                severity=candidate.severity,
                equipment_id=candidate.equipment_id,
                evidence=candidate.evidence,
                rule_version=rule_version,
            )
        )
        for event_id in candidate.legacy_event_ids:
            db.add(LegacyReconciliationFindingEvent(finding_id=finding_id, legacy_equipment_event_id=event_id))
        if candidate.severity == "high":
            high += 1
        elif candidate.severity == "medium":
            medium += 1
        else:
            low += 1

    return PersistedSummary(total_findings=len(ordered), high=high, medium=medium, low=low)
