"""Roadmap PR22C (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md
§9-§18, §22-§27, §34, §36) -- engine-level tests requiring a real
PostgreSQL database: the CAS run-claim contract (§8), the genuine
`REPEATABLE READ` snapshot-consistency proof (§32), determinism (§34),
mutation safety (§35), and all-or-nothing persistence (§26).

Reuses `pg_engine`/`pg_session`/`pg_seeded_users` from
`test_postgres_integration.py` -- the same real-PostgreSQL fixture
pattern every other genuine two-connection concurrency proof in this
repository already uses, rather than inventing a second one.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import (
    ReconciliationAnalysisFailedError,
    ReconciliationCoverageMismatchError,
    ReconciliationRunNotPendingError,
    ReconciliationRunVersionConflictError,
    UnsupportedReconciliationRuleVersionError,
)
from app.models.equipment import Equipment, EquipmentStatus
from app.models.legacy_history import LegacyEquipmentEvent, LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationFinding,
    LegacyReconciliationFindingEvent,
    LegacyReconciliationRun,
)
from app.models.import_session import ImportSession, ImportSource
from app.models.transaction import BorrowTransaction, TransactionStatus
from app.services.reconciliation.engine import execute_reconciliation_run
from app.services.reconciliation.rule_version import PR22_RECONCILIATION_RULE_VERSION
from app.services.reconciliation import projection as projection_mod

from tests.test_postgres_integration import pg_engine, pg_session, pg_seeded_users  # noqa: F401

pytestmark = pytest.mark.postgres

_COVERAGE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_COVERAGE_END = datetime(2024, 12, 31, tzinfo=timezone.utc)
_LIVE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


async def _seed_equipment(db: AsyncSession, *, status=EquipmentStatus.AVAILABLE_AT_POOL) -> Equipment:
    eq = Equipment(asset_number=f"AN-{uuid.uuid4().hex[:10]}", equipment_name="PR22C Test Equipment", status=status)
    db.add(eq)
    await db.commit()
    await db.refresh(eq)
    return eq


async def _seed_authority(db: AsyncSession, *, actor_id: uuid.UUID, checksum: str) -> LegacyMigrationAuthority:
    authority = LegacyMigrationAuthority(scope="pr22c_test", approved_workbook_sha256=checksum, approved_by_user_id=actor_id)
    db.add(authority)
    await db.commit()
    await db.refresh(authority)
    return authority


async def _seed_coverage(
    db: AsyncSession, *, authority_id: uuid.UUID, actor_id: uuid.UUID,
    coverage_start=_COVERAGE_START, coverage_end=_COVERAGE_END, live_start=_LIVE_START,
) -> LegacyMigrationAuthorityCoverage:
    coverage = LegacyMigrationAuthorityCoverage(
        migration_authority_id=authority_id,
        legacy_coverage_start=coverage_start,
        legacy_coverage_end=coverage_end,
        live_system_start=live_start,
        approval_basis="explicit_administrator_approval",
        approved_by_user_id=actor_id,
    )
    db.add(coverage)
    await db.commit()
    await db.refresh(coverage)
    return coverage


async def _seed_legacy_event(
    db: AsyncSession, *, authority_id: uuid.UUID, equipment_id: uuid.UUID, actor_id: uuid.UUID,
    event_type: str, occurred_at: datetime, row_key: str, checksum: str,
) -> LegacyEquipmentEvent:
    session = ImportSession(dataset_type="legacy_history", status="dry_run_completed", version=0, created_by_user_id=actor_id)
    db.add(session)
    await db.flush()
    source = ImportSource(
        import_session_id=session.id, status="frozen", checksum=checksum, byte_size=1,
        content_type="application/vnd.ms-excel", filename="wb.xlsx", options_fingerprint="x",
        source_fingerprint="y", frozen_at=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    db.add(source)
    await db.commit()
    await db.refresh(session)
    await db.refresh(source)

    event = LegacyEquipmentEvent(
        migration_authority_id=authority_id, equipment_id=equipment_id, event_type=event_type,
        occurred_at=occurred_at, legacy_source_row_key=row_key,
        import_session_id=session.id, import_source_id=source.id,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def _seed_run(
    db: AsyncSession, *, coverage: LegacyMigrationAuthorityCoverage, actor_id: uuid.UUID, **overrides,
) -> LegacyReconciliationRun:
    defaults = dict(
        coverage_id=coverage.id,
        legacy_coverage_start=coverage.legacy_coverage_start,
        legacy_coverage_end=coverage.legacy_coverage_end,
        live_system_start=coverage.live_system_start,
        rule_version=PR22_RECONCILIATION_RULE_VERSION,
        snapshot_as_of=datetime.now(timezone.utc),
        created_by_user_id=actor_id,
    )
    defaults.update(overrides)
    run = LegacyReconciliationRun(**defaults)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def _seed_transaction(
    db: AsyncSession, *, equipment_id: uuid.UUID, borrowed_at: datetime, returned_at: datetime | None = None,
) -> BorrowTransaction:
    # `idx_tx_one_active_borrow` allows only one 'open' BorrowTransaction
    # per equipment -- a row with `returned_at` set must be CLOSED so
    # multiple already-returned transactions can be seeded for the same
    # equipment (e.g. a straddling row plus an older, fully historical one).
    tx = BorrowTransaction(
        transaction_no=f"TX-{uuid.uuid4().hex[:10]}", equipment_id=equipment_id,
        borrowed_at=borrowed_at, returned_at=returned_at,
        status=TransactionStatus.CLOSED if returned_at is not None else TransactionStatus.OPEN,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


async def _finding_rows_for_run(db: AsyncSession, run_id: uuid.UUID) -> list[LegacyReconciliationFinding]:
    return (
        await db.execute(select(LegacyReconciliationFinding).where(LegacyReconciliationFinding.run_id == run_id))
    ).scalars().all()


def _semantic_key(f: LegacyReconciliationFinding) -> tuple:
    return (f.code, f.severity, str(f.equipment_id), tuple(sorted(f.evidence.items())))


# ---------------------------------------------------------------------------
# A. Basic execution + persistence
# ---------------------------------------------------------------------------


async def test_engine_completes_run_and_persists_expected_findings(pg_session, pg_seeded_users):
    actor = pg_seeded_users["administrator"]
    equipment = await _seed_equipment(pg_session)
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="a" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1), row_key="row-1", checksum="a" * 64,
    )
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)

    completed = await execute_reconciliation_run(pg_session, run_id=run.id, expected_version=0)
    assert completed.status == "completed"
    assert completed.version == 2  # pending(0) -> running(1) -> completed(2)
    assert completed.summary_total_findings == completed.summary_high + completed.summary_medium + completed.summary_low

    findings = await _finding_rows_for_run(pg_session, run.id)
    assert len(findings) == completed.summary_total_findings
    assert all(f.disposition is None and f.disposed_by_user_id is None and f.disposed_at is None for f in findings)
    codes = {f.code for f in findings}
    # No source ref was seeded for this event, and no BME/Ward mapping --
    # both gaps must surface, plus the ISSUE has no later RECEIVE.
    assert "SOURCE_PROVENANCE" in codes
    assert "CHRONOLOGY_ANOMALY" in codes


async def test_engine_rule_version_mismatch_fails_closed(pg_session, pg_seeded_users):
    actor = pg_seeded_users["administrator"]
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="b" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id, rule_version="pr22-v0-unsupported")

    with pytest.raises(UnsupportedReconciliationRuleVersionError):
        await execute_reconciliation_run(pg_session, run_id=run.id, expected_version=0)

    await pg_session.refresh(run)
    assert run.status == "pending", "a rule-version mismatch must never mutate the run"


async def test_engine_not_pending_rejected(pg_session, pg_seeded_users):
    actor = pg_seeded_users["administrator"]
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="c" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id, status="completed")

    with pytest.raises(ReconciliationRunNotPendingError):
        await execute_reconciliation_run(pg_session, run_id=run.id, expected_version=0)


async def test_engine_coverage_mismatch_rejected(pg_session, pg_seeded_users):
    """§38: the run's own copied coverage timestamps no longer match its
    bound coverage artifact -- fail closed, never repaired."""
    actor = pg_seeded_users["administrator"]
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="d" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    run = await _seed_run(
        pg_session, coverage=coverage, actor_id=actor.id,
        legacy_coverage_end=coverage.legacy_coverage_end + timedelta(days=1),
    )

    with pytest.raises(ReconciliationCoverageMismatchError):
        await execute_reconciliation_run(pg_session, run_id=run.id, expected_version=0)

    await pg_session.refresh(run)
    assert run.status == "pending"


async def test_engine_version_conflict_stale_expected_version(pg_session, pg_seeded_users):
    actor = pg_seeded_users["administrator"]
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="e" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)

    with pytest.raises(ReconciliationRunVersionConflictError):
        await execute_reconciliation_run(pg_session, run_id=run.id, expected_version=99)


# ---------------------------------------------------------------------------
# B. All-or-nothing persistence (§26)
# ---------------------------------------------------------------------------


async def test_engine_all_or_nothing_on_rule_failure(pg_session, pg_seeded_users, monkeypatch):
    actor = pg_seeded_users["administrator"]
    equipment = await _seed_equipment(pg_session)
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="f" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1), row_key="row-1", checksum="f" * 64,
    )
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)

    from app.services.reconciliation import engine as engine_mod
    from app.services.reconciliation.rules import pairing as pairing_mod

    def _boom(context):
        raise RuntimeError("simulated rule failure")

    monkeypatch.setattr(pairing_mod, "evaluate", _boom)
    monkeypatch.setattr(engine_mod, "_RULES", engine_mod._RULES[:-1] + (pairing_mod,))

    with pytest.raises(ReconciliationAnalysisFailedError):
        await execute_reconciliation_run(pg_session, run_id=run.id, expected_version=0)

    await pg_session.refresh(run)
    assert run.status == "failed"
    assert run.failed_at is not None

    findings = await _finding_rows_for_run(pg_session, run.id)
    assert findings == [], "no partial finding set may ever remain visible for a failed run"


# ---------------------------------------------------------------------------
# C. Determinism (§34) and mutation safety (§35)
# ---------------------------------------------------------------------------


async def test_engine_determinism_same_input_same_semantic_result(pg_session, pg_seeded_users):
    actor = pg_seeded_users["administrator"]
    equipment = await _seed_equipment(pg_session)
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="1" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1), row_key="row-1", checksum="1" * 64,
    )
    await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="RECEIVE", occurred_at=_COVERAGE_START + timedelta(days=2), row_key="row-2", checksum="1" * 64,
    )

    run_a = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)
    run_b = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)

    completed_a = await execute_reconciliation_run(pg_session, run_id=run_a.id, expected_version=0)
    completed_b = await execute_reconciliation_run(pg_session, run_id=run_b.id, expected_version=0)

    findings_a = await _finding_rows_for_run(pg_session, run_a.id)
    findings_b = await _finding_rows_for_run(pg_session, run_b.id)

    assert sorted(_semantic_key(f) for f in findings_a) == sorted(_semantic_key(f) for f in findings_b)
    assert completed_a.summary_total_findings == completed_b.summary_total_findings
    assert completed_a.summary_high == completed_b.summary_high
    assert completed_a.summary_medium == completed_b.summary_medium
    assert completed_a.summary_low == completed_b.summary_low


async def test_engine_mutation_safety(pg_session, pg_seeded_users):
    actor = pg_seeded_users["administrator"]
    equipment = await _seed_equipment(pg_session)
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="2" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    event = await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=_COVERAGE_START + timedelta(days=1), row_key="row-1", checksum="2" * 64,
    )
    tx = BorrowTransaction(
        transaction_no=f"TX-{uuid.uuid4().hex[:10]}", equipment_id=equipment.id, borrowed_at=_COVERAGE_START + timedelta(days=1)
    )
    pg_session.add(tx)
    await pg_session.commit()
    await pg_session.refresh(tx)

    equipment_before = (equipment.status, equipment.version)
    tx_before = (tx.status.value, tx.borrowed_at, tx.returned_at, tx.equipment_id)
    event_before = (event.equipment_id, event.event_type, event.occurred_at, event.legacy_source_row_key)

    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)
    await execute_reconciliation_run(pg_session, run_id=run.id, expected_version=0)

    await pg_session.refresh(equipment)
    await pg_session.refresh(tx)
    await pg_session.refresh(event)

    assert (equipment.status, equipment.version) == equipment_before
    assert (tx.status.value, tx.borrowed_at, tx.returned_at, tx.equipment_id) == tx_before
    assert (event.equipment_id, event.event_type, event.occurred_at, event.legacy_source_row_key) == event_before


# ---------------------------------------------------------------------------
# D. Concurrent claim -- exactly one winner (§8)
# ---------------------------------------------------------------------------


async def test_concurrent_claim_single_winner_on_postgres(pg_engine, pg_session, pg_seeded_users):
    actor = pg_seeded_users["administrator"]
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="3" * 64)
    coverage = await _seed_coverage(pg_session, authority_id=authority.id, actor_id=actor.id)
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _attempt():
        async with session_maker() as db:
            return await execute_reconciliation_run(db, run_id=run.id, expected_version=0)

    results = await asyncio.gather(_attempt(), _attempt(), return_exceptions=True)
    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1, f"exactly one concurrent claim must win, got {results}"
    assert len(failures) == 1
    assert isinstance(failures[0], ReconciliationRunVersionConflictError), failures[0]


# ---------------------------------------------------------------------------
# E. Genuine REPEATABLE READ snapshot consistency (§32) -- mandatory
# correctness evidence, not optional performance testing.
# ---------------------------------------------------------------------------


async def test_repeatable_read_snapshot_consistency_on_postgres(pg_engine, pg_session, pg_seeded_users):
    equipment = await _seed_equipment(pg_session, status=EquipmentStatus.AVAILABLE_AT_POOL)
    equipment_id = equipment.id

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    # 1-3: connection A starts at REPEATABLE READ, establishes its
    # snapshot with the first SELECT -- the exact same
    # `connection(execution_options=...)` call `engine.py`'s own TX2
    # uses for its analysis transaction.
    async with session_maker() as conn_a:
        await conn_a.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        before = (await conn_a.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
        assert before.status == EquipmentStatus.AVAILABLE_AT_POOL

        # 4: connection B modifies the row and commits.
        async with session_maker() as conn_b:
            row_b = (await conn_b.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
            row_b.status = EquipmentStatus.ISSUED_TO_WARD
            await conn_b.commit()

        # 5-6: connection A continues -- must still see the pre-B snapshot.
        still_before = (await conn_a.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
        assert still_before.status == EquipmentStatus.AVAILABLE_AT_POOL, (
            "REPEATABLE READ must present one consistent pre-change snapshot for the entire transaction"
        )
        await conn_a.commit()

    # 7: a new transaction started after A finishes must see B's change.
    async with session_maker() as conn_c:
        after = (await conn_c.execute(select(Equipment).where(Equipment.id == equipment_id))).scalar_one()
        assert after.status == EquipmentStatus.ISSUED_TO_WARD


# ---------------------------------------------------------------------------
# F. OD-PR22-7 temporal projection boundary, enforced in real SQL
# (Fix Round 1) -- the pure-Python equivalents in
# test_pr22c_reconciliation_rules.py exercise `_ctx()`'s faithful model
# of this same predicate; these tests prove the real
# `projection.load_legacy_events`/`load_transactions_for_equipment` SQL
# predicates themselves, against a real PostgreSQL database.
# ---------------------------------------------------------------------------


async def test_load_legacy_events_bounds_to_coverage_window(pg_session, pg_seeded_users):
    """Fix Round 1 §16 items 1-5, proven directly against the real SQL
    predicate: before start excluded, at start included, inside included,
    at end included, after end excluded -- both boundaries inclusive."""
    actor = pg_seeded_users["administrator"]
    equipment = await _seed_equipment(pg_session)
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="6" * 64)

    before_start = await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=_COVERAGE_START - timedelta(seconds=1), row_key="before-start", checksum="6" * 64,
    )
    at_start = await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=_COVERAGE_START, row_key="at-start", checksum="6" * 64,
    )
    inside = await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="RECEIVE", occurred_at=_COVERAGE_START + timedelta(days=100), row_key="inside", checksum="6" * 64,
    )
    at_end = await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=_COVERAGE_END, row_key="at-end", checksum="6" * 64,
    )
    after_end = await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="RECEIVE", occurred_at=_COVERAGE_END + timedelta(seconds=1), row_key="after-end", checksum="6" * 64,
    )

    loaded = await projection_mod.load_legacy_events(
        pg_session, migration_authority_id=authority.id,
        legacy_coverage_start=_COVERAGE_START, legacy_coverage_end=_COVERAGE_END,
    )
    loaded_ids = {e.id for e in loaded}

    assert before_start.id not in loaded_ids
    assert at_start.id in loaded_ids
    assert inside.id in loaded_ids
    assert at_end.id in loaded_ids
    assert after_end.id not in loaded_ids
    assert loaded_ids == {at_start.id, inside.id, at_end.id}


async def test_load_transactions_split_row_across_live_system_start(pg_session, pg_seeded_users):
    """Fix Round 1 §6/§17, proven against a real persisted row: a
    BorrowTransaction whose `borrowed_at` is before `live_system_start`
    and whose `returned_at` is after it must be loaded (not pruned away
    entirely by the SQL predicate) and must contribute `modern_receive`
    only, never `modern_issue`, once projected."""
    equipment = await _seed_equipment(pg_session)
    straddling = await _seed_transaction(
        pg_session, equipment_id=equipment.id,
        borrowed_at=_LIVE_START - timedelta(days=5), returned_at=_LIVE_START + timedelta(days=5),
    )
    fully_before = await _seed_transaction(
        pg_session, equipment_id=equipment.id,
        borrowed_at=_LIVE_START - timedelta(days=20), returned_at=_LIVE_START - timedelta(days=15),
    )

    loaded = await projection_mod.load_transactions_for_equipment(
        pg_session, equipment_ids=frozenset({equipment.id}), live_system_start=_LIVE_START
    )
    loaded_ids = {t.id for t in loaded}
    # The straddling row must survive the SQL-level prune (its returned_at
    # alone qualifies it); the fully-before row must not.
    assert straddling.id in loaded_ids
    assert fully_before.id not in loaded_ids

    projection = projection_mod.build_projection(legacy_events=(), transactions=loaded, live_system_start=_LIVE_START)
    kinds = {ev.source_kind for ev in projection}
    assert kinds == {"modern_receive"}


async def test_projection_gap_scenario_excludes_both_out_of_window_sources(pg_session, pg_seeded_users):
    """Fix Round 1 §18 gap test: legacy_coverage_end < live_system_start.
    A legacy event after legacy_coverage_end and a modern transaction
    before live_system_start must both be excluded from the projection
    -- the gap window genuinely has no history source, and neither side
    is fabricated to fill it."""
    actor = pg_seeded_users["administrator"]
    equipment = await _seed_equipment(pg_session)
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="7" * 64)

    coverage_end = _COVERAGE_START + timedelta(days=30)
    live_start = coverage_end + timedelta(days=60)  # genuine gap

    await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=coverage_end + timedelta(days=1), row_key="in-gap-legacy", checksum="7" * 64,
    )
    await _seed_transaction(
        pg_session, equipment_id=equipment.id,
        borrowed_at=live_start - timedelta(days=1), returned_at=None,
    )

    legacy = await projection_mod.load_legacy_events(
        pg_session, migration_authority_id=authority.id,
        legacy_coverage_start=_COVERAGE_START, legacy_coverage_end=coverage_end,
    )
    transactions = await projection_mod.load_transactions_for_equipment(
        pg_session, equipment_ids=frozenset({equipment.id}), live_system_start=live_start
    )
    projection = projection_mod.build_projection(legacy_events=legacy, transactions=transactions, live_system_start=live_start)

    assert projection == (), "the gap window must contain zero projected events from either source"


async def test_projection_overlap_scenario_retains_both_sources(pg_session, pg_seeded_users):
    """Fix Round 1 §19 overlap test: legacy_coverage_end > live_system_start.
    A legacy event and a modern transaction both inside the overlap
    window must both be retained -- neither source is silently
    discarded or deduplicated."""
    actor = pg_seeded_users["administrator"]
    equipment = await _seed_equipment(pg_session)
    authority = await _seed_authority(pg_session, actor_id=actor.id, checksum="8" * 64)

    live_start = _COVERAGE_START + timedelta(days=10)
    coverage_end = _COVERAGE_START + timedelta(days=60)  # overlap: [10, 60] straddles live_start
    overlap_instant = live_start + timedelta(days=1)

    legacy_event = await _seed_legacy_event(
        pg_session, authority_id=authority.id, equipment_id=equipment.id, actor_id=actor.id,
        event_type="ISSUE", occurred_at=overlap_instant, row_key="overlap-legacy", checksum="8" * 64,
    )
    modern_tx = await _seed_transaction(
        pg_session, equipment_id=equipment.id, borrowed_at=overlap_instant, returned_at=None,
    )

    legacy = await projection_mod.load_legacy_events(
        pg_session, migration_authority_id=authority.id,
        legacy_coverage_start=_COVERAGE_START, legacy_coverage_end=coverage_end,
    )
    transactions = await projection_mod.load_transactions_for_equipment(
        pg_session, equipment_ids=frozenset({equipment.id}), live_system_start=live_start
    )
    projection = projection_mod.build_projection(legacy_events=legacy, transactions=transactions, live_system_start=live_start)

    assert {ev.legacy_event_id for ev in projection if ev.legacy_event_id is not None} == {legacy_event.id}
    assert {ev.modern_transaction_id for ev in projection if ev.modern_transaction_id is not None} == {modern_tx.id}
    assert {ev.source_kind for ev in projection} == {"legacy_issue", "modern_issue"}
