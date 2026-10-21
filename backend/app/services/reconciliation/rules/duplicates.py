"""Roadmap PR22C §16/§17 -- DUPLICATE_EXACT and DUPLICATE_SUSPECTED.

**DUPLICATE_EXACT** (§16): PR21's own database-enforced technical
identity (`migration_authority_id`, `event_type`, `legacy_source_row_key`)
already prevents an idempotent same-row retry from ever being persisted
twice -- this rule never reinterprets that as a business duplicate. An
exact-duplicate finding here means two *distinct*, already-persisted
events (different `legacy_source_row_key`, so each individually passed
PR21's own uniqueness) whose full deterministic business-content tuple
-- `(equipment_id, event_type, occurred_at, legacy_order_reference)` --
is identical: the same historical fact was independently recorded twice
under two different source row keys.

**DUPLICATE_SUSPECTED** (§17): deterministic, bounded, explicit
equality/window predicates only -- no fuzzy scoring of any kind. The
exact predicate (documented here, not only in tests): within the same
`(equipment_id, event_type)` group, sorted by `occurred_at`, two events
are a suspected duplicate pair when ALL of the following hold and they
are not already an exact-duplicate pair:
  - both have a non-null `resolved_ward_id`, and it matches on both, AND
  - `abs(delta) <= 24 hours` between their `occurred_at` values.
Ward match alone or the time window alone is never sufficient -- both
independent dimensions must agree, per §17's "no BCM alone, no Ward
alone" instruction generalized to this rule's own available dimensions.
"""

from __future__ import annotations

from datetime import timedelta

from ..candidates import FindingCandidate, LegacyEventSnapshot
from ..context import ReconciliationContext

EXACT_CODE = "DUPLICATE_EXACT"
SUSPECTED_CODE = "DUPLICATE_SUSPECTED"

_SUSPECTED_WINDOW = timedelta(hours=24)


def _exact_key(e: LegacyEventSnapshot) -> tuple:
    return (e.equipment_id, e.event_type, e.occurred_at, e.legacy_order_reference)


def _evaluate_exact(context: ReconciliationContext) -> tuple[tuple[FindingCandidate, ...], frozenset[frozenset]]:
    groups: dict[tuple, list[LegacyEventSnapshot]] = {}
    for e in context.events:
        groups.setdefault(_exact_key(e), []).append(e)

    candidates: list[FindingCandidate] = []
    exact_pairs: set[frozenset] = set()
    for key in sorted(groups, key=lambda k: (str(k[0]), k[1], str(k[2]), k[3] or "")):
        members = groups[key]
        if len(members) < 2:
            continue
        members_sorted = sorted(members, key=lambda e: str(e.id))
        event_ids = tuple(e.id for e in members_sorted)
        for i in range(len(members_sorted)):
            for j in range(i + 1, len(members_sorted)):
                exact_pairs.add(frozenset((members_sorted[i].id, members_sorted[j].id)))
        candidates.append(
            FindingCandidate(
                code=EXACT_CODE,
                severity="high",
                equipment_id=key[0],
                evidence={
                    "matched_fields": ["equipment_id", "event_type", "occurred_at", "legacy_order_reference"],
                    "event_type": key[1],
                    "legacy_source_row_keys": sorted(e.legacy_source_row_key for e in members_sorted),
                },
                legacy_event_ids=event_ids,
                sort_key=(str(key[0]), key[1], str(key[2])),
            )
        )
    return tuple(candidates), frozenset(exact_pairs)


def _evaluate_suspected(
    context: ReconciliationContext, exact_pairs: frozenset[frozenset]
) -> tuple[FindingCandidate, ...]:
    groups: dict[tuple, list[LegacyEventSnapshot]] = {}
    for e in context.events:
        groups.setdefault((e.equipment_id, e.event_type), []).append(e)

    candidates: list[FindingCandidate] = []
    for key in sorted(groups, key=lambda k: (str(k[0]), k[1])):
        members = sorted(groups[key], key=lambda e: (e.occurred_at, str(e.id)))
        # Bounded sliding-window comparison over the sorted-by-time list
        # only (never a full O(n^2) cross product, per §30) -- a pair
        # more than the window apart can never match, so once the time
        # delta from the anchor exceeds the window the inner loop stops.
        for i in range(len(members)):
            anchor = members[i]
            if anchor.resolved_ward_id is None:
                continue
            for j in range(i + 1, len(members)):
                other = members[j]
                if other.occurred_at - anchor.occurred_at > _SUSPECTED_WINDOW:
                    break
                if other.resolved_ward_id != anchor.resolved_ward_id:
                    continue
                pair_key = frozenset((anchor.id, other.id))
                if pair_key in exact_pairs:
                    continue
                candidates.append(
                    FindingCandidate(
                        code=SUSPECTED_CODE,
                        severity="medium",
                        equipment_id=key[0],
                        evidence={
                            "matched_fields": ["equipment_id", "event_type", "resolved_ward_id"],
                            "event_type": key[1],
                            "resolved_ward_id": str(anchor.resolved_ward_id),
                            "occurred_at_delta_seconds": (other.occurred_at - anchor.occurred_at).total_seconds(),
                        },
                        legacy_event_ids=(anchor.id, other.id),
                        sort_key=(str(key[0]), key[1], str(anchor.occurred_at), str(anchor.id)),
                    )
                )
    return tuple(candidates)


def evaluate(context: ReconciliationContext) -> tuple[FindingCandidate, ...]:
    exact_candidates, exact_pairs = _evaluate_exact(context)
    suspected_candidates = _evaluate_suspected(context, exact_pairs)
    return exact_candidates + suspected_candidates
