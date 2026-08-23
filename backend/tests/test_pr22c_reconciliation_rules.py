"""Roadmap PR22C (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md
§9-§18, §22-§27, §34) -- rule-module test matrix (§33).

Pure-Python, no database: every rule module is a pure function over an
immutable `ReconciliationContext`, so these tests build that context
directly from hand-crafted snapshot dataclasses (never real ORM rows)
and call `rule.evaluate(context)` directly. `projection.build_projection`/
`group_by_equipment` (real production code, not reimplemented here)
derive the unified projection from the same synthetic events/
transactions, so this suite also exercises the projection module itself.

Engine-level concerns (REPEATABLE READ, CAS claim, determinism,
mutation-safety, all-or-nothing persistence) live in
`test_pr22c_reconciliation_engine.py` instead, since those require a
real PostgreSQL database.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.services.reconciliation.candidates import EquipmentSnapshot, LegacyEventSnapshot, SourceRefSnapshot, TransactionSnapshot
from app.services.reconciliation.context import ReconciliationContext
from app.services.reconciliation.projection import build_projection, group_by_equipment
from app.services.reconciliation.rules import (
    bme_traceability,
    chronology,
    current_state,
    duplicates,
    equipment_identity,
    pairing,
    source_provenance,
    ward_traceability,
)

_COVERAGE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_COVERAGE_END = datetime(2024, 12, 31, tzinfo=timezone.utc)
_LIVE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _uuid(seed: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, seed)


def _event(
    seed: str,
    *,
    equipment_id: uuid.UUID,
    event_type: str,
    occurred_at: datetime,
    order_ref: str | None = None,
    ward_text: str | None = None,
    resolved_ward_id: uuid.UUID | None = None,
    bme_name: str | None = None,
    authority_id: uuid.UUID | None = None,
) -> LegacyEventSnapshot:
    return LegacyEventSnapshot(
        id=_uuid(f"event-{seed}"),
        equipment_id=equipment_id,
        event_type=event_type,
        occurred_at=occurred_at,
        legacy_source_row_key=f"row-{seed}",
        legacy_order_reference=order_ref,
        legacy_ward_text=ward_text,
        resolved_ward_id=resolved_ward_id,
        legacy_bme_name=bme_name,
        migration_authority_id=authority_id or _uuid("authority-default"),
        import_session_id=_uuid("session-default"),
        import_source_id=_uuid("source-default"),
    )


def _equipment(seed: str, *, status: str = "available_at_pool", bcm_code: str | None = "BCM-1", item_no: str | None = None) -> EquipmentSnapshot:
    return EquipmentSnapshot(
        id=_uuid(f"equipment-{seed}"), status=status, asset_number=f"AN-{seed}", bcm_code=bcm_code, item_no=item_no
    )


def _ctx(
    *,
    events: tuple[LegacyEventSnapshot, ...] = (),
    transactions: tuple[TransactionSnapshot, ...] = (),
    equipment: tuple[EquipmentSnapshot, ...] = (),
    source_refs_by_event: dict | None = None,
    ward_alias_by_raw: dict | None = None,
    bme_alias_by_raw: dict | None = None,
    coverage_start: datetime = _COVERAGE_START,
    coverage_end: datetime = _COVERAGE_END,
    live_start: datetime = _LIVE_START,
) -> ReconciliationContext:
    projection = build_projection(legacy_events=events, transactions=transactions)
    return ReconciliationContext(
        run_id=_uuid("run-default"),
        rule_version="pr22-v1",
        migration_authority_id=_uuid("authority-default"),
        legacy_coverage_start=coverage_start,
        legacy_coverage_end=coverage_end,
        live_system_start=live_start,
        events=events,
        source_refs_by_event=source_refs_by_event or {},
        equipment_by_id={e.id: e for e in equipment},
        ward_alias_by_raw=ward_alias_by_raw or {},
        bme_alias_by_raw=bme_alias_by_raw or {},
        projection=projection,
        projection_by_equipment=group_by_equipment(projection),
    )


# ---------------------------------------------------------------------------
# A. EQUIPMENT_IDENTITY
# ---------------------------------------------------------------------------


def test_equipment_identity_coherent_no_finding():
    eq_id = _uuid("equipment-a")
    ctx = _ctx(
        events=(_event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1)),),
        equipment=(_equipment("a", bcm_code="BCM-123"),),
    )
    assert equipment_identity.evaluate(ctx) == ()


def test_equipment_identity_broken_traceability_finding():
    eq_id = _uuid("equipment-b")
    ctx = _ctx(
        events=(_event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1)),),
        equipment=(_equipment("b", bcm_code=None, item_no=None),),
    )
    findings = equipment_identity.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].code == "EQUIPMENT_IDENTITY"
    assert findings[0].equipment_id == eq_id


# ---------------------------------------------------------------------------
# B. SOURCE_PROVENANCE
# ---------------------------------------------------------------------------


def test_source_provenance_valid_no_finding():
    eq_id = _uuid("equipment-c")
    event = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1))
    ctx = _ctx(
        events=(event,),
        equipment=(_equipment("c"),),
        source_refs_by_event={event.id: (SourceRefSnapshot(id=_uuid("ref-1"), legacy_equipment_event_id=event.id, sheet_name="Orders", source_row_number=1, source_checksum="abc"),)},
    )
    assert source_provenance.evaluate(ctx) == ()


def test_source_provenance_missing_finding():
    eq_id = _uuid("equipment-d")
    event = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1))
    ctx = _ctx(events=(event,), equipment=(_equipment("d"),))
    findings = source_provenance.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].code == "SOURCE_PROVENANCE"
    assert findings[0].legacy_event_ids == (event.id,)


# ---------------------------------------------------------------------------
# C. DUPLICATE_EXACT / DUPLICATE_SUSPECTED
# ---------------------------------------------------------------------------


def test_duplicate_exact_true_deterministic_duplicate():
    eq_id = _uuid("equipment-e")
    at = _COVERAGE_START + timedelta(days=1)
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at, order_ref="ORD-1")
    e2 = _event("2", equipment_id=eq_id, event_type="ISSUE", occurred_at=at, order_ref="ORD-1")
    ctx = _ctx(events=(e1, e2), equipment=(_equipment("e"),))
    findings = duplicates.evaluate(ctx)
    exact = [f for f in findings if f.code == "DUPLICATE_EXACT"]
    assert len(exact) == 1
    assert set(exact[0].legacy_event_ids) == {e1.id, e2.id}


def test_duplicate_similar_but_not_duplicate_no_finding():
    eq_id = _uuid("equipment-f")
    at = _COVERAGE_START + timedelta(days=1)
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at, order_ref="ORD-1")
    e2 = _event("2", equipment_id=eq_id, event_type="ISSUE", occurred_at=at + timedelta(days=10), order_ref="ORD-2")
    ctx = _ctx(events=(e1, e2), equipment=(_equipment("f"),))
    findings = duplicates.evaluate(ctx)
    assert findings == ()


def test_duplicate_suspected_exact_predicate_match():
    eq_id = _uuid("equipment-g")
    ward_id = _uuid("ward-1")
    at = _COVERAGE_START + timedelta(days=1)
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at, resolved_ward_id=ward_id, order_ref="ORD-A")
    e2 = _event("2", equipment_id=eq_id, event_type="ISSUE", occurred_at=at + timedelta(hours=2), resolved_ward_id=ward_id, order_ref="ORD-B")
    ctx = _ctx(events=(e1, e2), equipment=(_equipment("g"),))
    findings = duplicates.evaluate(ctx)
    suspected = [f for f in findings if f.code == "DUPLICATE_SUSPECTED"]
    assert len(suspected) == 1
    assert set(suspected[0].legacy_event_ids) == {e1.id, e2.id}


def test_duplicate_suspected_one_required_dimension_differs_no_finding():
    """Ward matches but the events are outside the 24h window -- the
    time-window dimension alone does not carry the match; both
    dimensions must independently agree."""
    eq_id = _uuid("equipment-h")
    ward_id = _uuid("ward-2")
    at = _COVERAGE_START + timedelta(days=1)
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at, resolved_ward_id=ward_id)
    e2 = _event("2", equipment_id=eq_id, event_type="ISSUE", occurred_at=at + timedelta(days=5), resolved_ward_id=ward_id)
    ctx = _ctx(events=(e1, e2), equipment=(_equipment("h"),))
    findings = duplicates.evaluate(ctx)
    assert [f for f in findings if f.code == "DUPLICATE_SUSPECTED"] == []


# ---------------------------------------------------------------------------
# D. CHRONOLOGY_ANOMALY
# ---------------------------------------------------------------------------


def test_chronology_issue_then_receive_valid_no_finding():
    eq_id = _uuid("equipment-i")
    at = _COVERAGE_START + timedelta(days=1)
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at)
    e2 = _event("2", equipment_id=eq_id, event_type="RECEIVE", occurred_at=at + timedelta(days=1))
    ctx = _ctx(events=(e1, e2), equipment=(_equipment("i"),))
    assert chronology.evaluate(ctx) == ()


def test_chronology_orphan_receive_within_coverage():
    eq_id = _uuid("equipment-j")
    e1 = _event("1", equipment_id=eq_id, event_type="RECEIVE", occurred_at=_COVERAGE_START + timedelta(days=1))
    ctx = _ctx(events=(e1,), equipment=(_equipment("j"),))
    findings = chronology.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].evidence["reason_code"] == "orphan_receive"


def test_chronology_unmatched_issue_within_coverage():
    eq_id = _uuid("equipment-k")
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1))
    ctx = _ctx(events=(e1,), equipment=(_equipment("k"),))
    findings = chronology.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].evidence["reason_code"] == "no_later_receive_in_covered_history"


def test_chronology_event_before_coverage_start_not_falsely_blamed():
    eq_id = _uuid("equipment-l")
    # A RECEIVE with no prior ISSUE, but entirely before legacy_coverage_start
    # -- must not be walked/blamed at all.
    e1 = _event("1", equipment_id=eq_id, event_type="RECEIVE", occurred_at=_COVERAGE_START - timedelta(days=10))
    ctx = _ctx(events=(e1,), equipment=(_equipment("l"),))
    assert chronology.evaluate(ctx) == ()


def test_chronology_gap_between_legacy_end_and_live_start_no_fabrication():
    """OD-PR22-7 gap case: legacy_coverage_end < live_system_start. An
    ISSUE just before legacy_coverage_end with genuinely no RECEIVE
    anywhere (legacy or modern) is a real, valid anomaly -- the gap
    itself contributes no events and is never fabricated."""
    eq_id = _uuid("equipment-m")
    coverage_end = _COVERAGE_START + timedelta(days=30)
    live_start = coverage_end + timedelta(days=60)  # genuine gap
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=coverage_end - timedelta(days=1))
    ctx = _ctx(events=(e1,), equipment=(_equipment("m"),), coverage_end=coverage_end, live_start=live_start)
    findings = chronology.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].evidence["reason_code"] == "no_later_receive_in_covered_history"


def test_chronology_overlap_both_sources_visible():
    """OD-PR22-7 overlap case: legacy_coverage_end > live_system_start.
    A legacy RECEIVE and a modern issue both existing in the overlap
    window are both walked -- neither source is silently discarded."""
    eq_id = _uuid("equipment-n")
    coverage_end = _COVERAGE_START + timedelta(days=60)
    live_start = _COVERAGE_START + timedelta(days=30)  # overlap
    legacy_issue = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=10))
    legacy_receive = _event("2", equipment_id=eq_id, event_type="RECEIVE", occurred_at=_COVERAGE_START + timedelta(days=20))
    modern_tx = TransactionSnapshot(
        id=_uuid("tx-1"),
        equipment_id=eq_id,
        status="closed",
        borrowed_at=_COVERAGE_START + timedelta(days=35),
        returned_at=_COVERAGE_START + timedelta(days=40),
        ward_id=None,
    )
    ctx = _ctx(
        events=(legacy_issue, legacy_receive),
        transactions=(modern_tx,),
        equipment=(_equipment("n"),),
        coverage_end=coverage_end,
        live_start=live_start,
    )
    # Both sources present in the projection -- valid ISSUE->RECEIVE,
    # ISSUE->RECEIVE sequence, no anomaly (neither source discarded, both walked).
    assert chronology.evaluate(ctx) == ()
    equipment_events = ctx.projection_by_equipment[eq_id]
    assert {ev.source_kind for ev in equipment_events} == {"legacy_issue", "legacy_receive", "modern_issue", "modern_receive"}


# ---------------------------------------------------------------------------
# E. CURRENT_STATE_MISMATCH
# ---------------------------------------------------------------------------


def test_current_state_plausible_no_finding():
    eq_id = _uuid("equipment-o")
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1))
    ctx = _ctx(events=(e1,), equipment=(_equipment("o", status="issued_to_ward"),))
    assert current_state.evaluate(ctx) == ()


def test_current_state_mismatch_finding():
    eq_id = _uuid("equipment-p")
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1))
    ctx = _ctx(events=(e1,), equipment=(_equipment("p", status="available_at_pool"),))
    findings = current_state.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].evidence["expected_state_signal"] == "issued_to_ward"
    assert findings[0].evidence["actual_equipment_status"] == "available_at_pool"


def test_current_state_defective_never_false_positive():
    eq_id = _uuid("equipment-q")
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1))
    ctx = _ctx(events=(e1,), equipment=(_equipment("q", status="unavailable_defective"),))
    assert current_state.evaluate(ctx) == ()


def test_current_state_decommissioned_never_false_positive():
    eq_id = _uuid("equipment-r")
    e1 = _event("1", equipment_id=eq_id, event_type="RECEIVE", occurred_at=_COVERAGE_START + timedelta(days=1))
    ctx = _ctx(events=(e1,), equipment=(_equipment("r", status="decommissioned"),))
    assert current_state.evaluate(ctx) == ()


# ---------------------------------------------------------------------------
# F. WARD_TRACEABILITY_GAP
# ---------------------------------------------------------------------------


def test_ward_mapped_no_finding():
    eq_id = _uuid("equipment-s")
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1), resolved_ward_id=_uuid("ward-x"))
    ctx = _ctx(events=(e1,), equipment=(_equipment("s"),))
    assert ward_traceability.evaluate(ctx) == ()


def test_ward_unresolved_finding():
    eq_id = _uuid("equipment-t")
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1), ward_text="ไอซียู")
    ctx = _ctx(events=(e1,), equipment=(_equipment("t"),))
    findings = ward_traceability.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].code == "WARD_TRACEABILITY_GAP"


# ---------------------------------------------------------------------------
# G. BME_TRACEABILITY_GAP
# ---------------------------------------------------------------------------


def test_bme_alias_exists_no_finding():
    eq_id = _uuid("equipment-u")
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1), bme_name="Somchai")
    ctx = _ctx(events=(e1,), equipment=(_equipment("u"),), bme_alias_by_raw={"Somchai": _uuid("user-1")})
    assert bme_traceability.evaluate(ctx) == ()


def test_bme_no_alias_finding():
    eq_id = _uuid("equipment-v")
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1), bme_name="Somsri")
    ctx = _ctx(events=(e1,), equipment=(_equipment("v"),))
    findings = bme_traceability.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].code == "BME_TRACEABILITY_GAP"


# ---------------------------------------------------------------------------
# H. PAIRING_CANDIDATE
# ---------------------------------------------------------------------------


def test_pairing_deterministic_candidate():
    eq_id = _uuid("equipment-w")
    ward_id = _uuid("ward-pairing")
    at = _COVERAGE_START + timedelta(days=1)
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at, resolved_ward_id=ward_id, order_ref="ORD-PAIR")
    e2 = _event("2", equipment_id=eq_id, event_type="RECEIVE", occurred_at=at + timedelta(days=2), resolved_ward_id=ward_id, order_ref="ORD-PAIR")
    ctx = _ctx(events=(e1, e2), equipment=(_equipment("w"),))
    findings = pairing.evaluate(ctx)
    assert len(findings) == 1
    assert findings[0].code == "PAIRING_CANDIDATE"
    assert set(findings[0].legacy_event_ids) == {e1.id, e2.id}


def test_pairing_near_timestamp_only_no_candidate():
    """Nearest-timestamp alone must never produce a pairing candidate --
    no Ward/order-reference agreement means no candidate at all."""
    eq_id = _uuid("equipment-x")
    at = _COVERAGE_START + timedelta(days=1)
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at)
    e2 = _event("2", equipment_id=eq_id, event_type="RECEIVE", occurred_at=at + timedelta(minutes=5))
    ctx = _ctx(events=(e1, e2), equipment=(_equipment("x"),))
    assert pairing.evaluate(ctx) == ()


def test_pairing_never_produces_confirmed_pair_disposition():
    """PR22C never assigns a disposition at all -- every candidate is
    open (disposition=NULL at persistence time); this asserts the
    FindingCandidate dataclass itself carries no disposition field a
    caller could misuse to set 'confirmed_pair'."""
    eq_id = _uuid("equipment-y")
    ward_id = _uuid("ward-y")
    at = _COVERAGE_START + timedelta(days=1)
    e1 = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at, resolved_ward_id=ward_id, order_ref="ORD-Y")
    e2 = _event("2", equipment_id=eq_id, event_type="RECEIVE", occurred_at=at + timedelta(days=1), resolved_ward_id=ward_id, order_ref="ORD-Y")
    ctx = _ctx(events=(e1, e2), equipment=(_equipment("y"),))
    findings = pairing.evaluate(ctx)
    assert len(findings) == 1
    assert not hasattr(findings[0], "disposition")


def test_pairing_ambiguous_match_no_candidate():
    """Two candidate receives matching the same issue on both required
    dimensions -- ambiguous, so no candidate is created for either."""
    eq_id = _uuid("equipment-z")
    ward_id = _uuid("ward-z")
    at = _COVERAGE_START + timedelta(days=1)
    issue = _event("1", equipment_id=eq_id, event_type="ISSUE", occurred_at=at, resolved_ward_id=ward_id, order_ref="ORD-Z")
    receive_a = _event("2", equipment_id=eq_id, event_type="RECEIVE", occurred_at=at + timedelta(days=1), resolved_ward_id=ward_id, order_ref="ORD-Z")
    receive_b = _event("3", equipment_id=eq_id, event_type="RECEIVE", occurred_at=at + timedelta(days=2), resolved_ward_id=ward_id, order_ref="ORD-Z")
    ctx = _ctx(events=(issue, receive_a, receive_b), equipment=(_equipment("z"),))
    assert pairing.evaluate(ctx) == ()
