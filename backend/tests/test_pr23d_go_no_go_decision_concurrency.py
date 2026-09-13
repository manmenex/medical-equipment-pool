"""Roadmap PR23D -- Go/No-Go Decision + Current-State Re-Issue Support.

Genuine two-connection PostgreSQL concurrency proofs for
`app.crud.cutover_readiness.create_go_no_go_decision`'s own concurrency
contract: the `UNIQUE(cutover_readiness_run_id)` invariant must hold
under a real race between two concurrent Administrators, with exactly
one deterministic winner and a structured `CutoverDecisionAlreadyExistsError`
for the loser -- never a raw `IntegrityError` and never two persisted
decision rows for the same run.

Reuses `pg_engine`/`pg_session`/`pg_seeded_users` from
`test_postgres_integration.py`, the same real-PostgreSQL fixture pattern
every other genuine concurrency proof in this repository already uses
(see `test_pr22e_reconciliation_signoff_concurrency.py`'s identical
convention, which this file mirrors directly).
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import audit as audit_module
from app.core.exceptions import CutoverDecisionAlreadyExistsError
from app.crud import cutover_readiness as cutover_readiness_crud
from app.crud.cutover_readiness import CompletionEvidence
from app.models.cutover_readiness import CutoverGoNoGoDecision, CutoverReadinessRun
from app.models.import_session import ImportSession, ImportSource
from app.models.legacy_history import LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)

from tests.test_postgres_integration import pg_engine, pg_session, pg_seeded_users  # noqa: F401

pytestmark = pytest.mark.postgres

_COVERAGE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_COVERAGE_END = datetime(2024, 12, 31, tzinfo=timezone.utc)
_LIVE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)
_CUTOVER_INSTANT = datetime(2025, 1, 5, tzinfo=timezone.utc)
_MIGRATION_HEAD = "0099_pr23d_pg_concurrency_head"


@pytest_asyncio.fixture(autouse=True)
async def _seed_alembic_version(pg_session: AsyncSession):
    """`alembic_version` is not part of `Base.metadata`, so `pg_engine`'s
    own `drop_all`/`create_all` never creates or seeds it -- Gate A's
    freshness re-check (reused unchanged by PR23D's fresh evaluation)
    needs a known, stable value. Same rationale as the identically-named
    fixture in `test_pr23d_go_no_go_decision.py`'s own SQLite suite."""
    await pg_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(32) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    await pg_session.execute(text("DELETE FROM alembic_version"))
    await pg_session.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": _MIGRATION_HEAD})
    await pg_session.commit()


def _checksum(seed: str) -> str:
    return (seed * 64)[:64]


def _baseline_sha(seed: str) -> str:
    return (seed * 40)[:40]


async def _seed_completed_run(db: AsyncSession, *, actor_id: uuid.UUID, seed: str) -> CutoverReadinessRun:
    """End-to-end: create and complete one `CutoverReadinessRun` with a
    fully-consistent evidence chain, using the real CRUD functions
    directly (not the HTTP API, since this test operates on `pg_session`
    directly) -- the same evidence-chain shape as
    `test_pr23d_go_no_go_decision.py`'s own `_create_and_complete_run`."""
    equipment_session = ImportSession(
        dataset_type="equipment_master", status="completed", version=0, created_by_user_id=actor_id
    )
    db.add(equipment_session)
    await db.flush()
    source = ImportSource(
        import_session_id=equipment_session.id, status="registered", checksum=_checksum(seed),
        byte_size=10, options_fingerprint="x", source_fingerprint="y",
    )
    db.add(source)

    authority = LegacyMigrationAuthority(
        scope="pr23d_concurrency_test", approved_workbook_sha256=_checksum(seed), approved_by_user_id=actor_id
    )
    db.add(authority)
    await db.flush()

    history_session = ImportSession(
        dataset_type="legacy_transaction_history", status="completed", version=0, created_by_user_id=actor_id
    )
    db.add(history_session)
    await db.flush()
    db.add(
        ImportSource(
            import_session_id=history_session.id, status="registered", checksum=authority.approved_workbook_sha256,
            byte_size=10, options_fingerprint="x", source_fingerprint="y",
        )
    )

    coverage = LegacyMigrationAuthorityCoverage(
        migration_authority_id=authority.id, legacy_coverage_start=_COVERAGE_START,
        legacy_coverage_end=_COVERAGE_END, live_system_start=_LIVE_START,
        approval_basis="explicit_administrator_approval", approved_by_user_id=actor_id,
    )
    db.add(coverage)
    await db.flush()
    reconciliation_run = LegacyReconciliationRun(
        coverage_id=coverage.id, legacy_coverage_start=coverage.legacy_coverage_start,
        legacy_coverage_end=coverage.legacy_coverage_end, live_system_start=coverage.live_system_start,
        rule_version="v1", snapshot_as_of=datetime.now(timezone.utc), created_by_user_id=actor_id,
        status="completed",
    )
    db.add(reconciliation_run)
    await db.flush()
    signoff = LegacyReconciliationSignOff(
        run_id=reconciliation_run.id, signed_off_by_user_id=actor_id,
        attestation_summary={"run_id": str(reconciliation_run.id)}, run_version_at_signoff=reconciliation_run.version,
    )
    db.add(signoff)
    await db.commit()
    await db.refresh(source)
    await db.refresh(authority)
    await db.refresh(coverage)
    await db.refresh(reconciliation_run)
    await db.refresh(signoff)

    run = await cutover_readiness_crud.create_readiness_run(
        db, actor_id=actor_id, application_baseline_sha=_baseline_sha(seed), cutover_instant=_CUTOVER_INSTANT
    )
    await db.commit()

    evidence = CompletionEvidence(
        equipment_master_import_source_id=source.id,
        legacy_migration_authority_id=authority.id,
        legacy_coverage_id=coverage.id,
        reconciliation_run_id=reconciliation_run.id,
        reconciliation_signoff_id=signoff.id,
        current_state_verified_at=datetime.now(timezone.utc),
        current_state_verified_by_user_id=actor_id,
    )
    completed = await cutover_readiness_crud.complete_readiness_run(
        db, run_id=run.id, expected_version=run.version, actor_id=actor_id, evidence=evidence
    )
    await db.commit()
    await db.refresh(completed)
    return completed


async def test_concurrent_decision_writers_exactly_one_wins(pg_engine, pg_session, pg_seeded_users):
    """The core PR23D concurrency proof: two real concurrent PostgreSQL
    Administrators both attempting to record a decision for the same
    completed run -- exactly one may create the `CutoverGoNoGoDecision`
    row; the second must receive a deterministic structured conflict
    (`CutoverDecisionAlreadyExistsError`), never a raw `IntegrityError`
    or a duplicate row, and `UNIQUE(cutover_readiness_run_id)` must hold
    regardless of which writer wins."""
    actor = pg_seeded_users["administrator"]
    completed = await _seed_completed_run(pg_session, actor_id=actor.id, seed="concurrency-winner")

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _attempt():
        async with session_maker() as db:
            decision = await cutover_readiness_crud.create_go_no_go_decision(
                db, run_id=completed.id, expected_version=completed.version, actor_id=actor.id,
                decision="NO_GO", acknowledged_warning_codes=[], no_go_reason=None,
            )
            await db.commit()
            return decision

    results = await asyncio.gather(_attempt(), _attempt(), return_exceptions=True)
    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1, f"exactly one concurrent decision must win, got {results}"
    assert len(failures) == 1
    assert isinstance(failures[0], CutoverDecisionAlreadyExistsError), failures[0]

    rows = (
        await pg_session.execute(
            select(CutoverGoNoGoDecision).where(CutoverGoNoGoDecision.cutover_readiness_run_id == completed.id)
        )
    ).scalars().all()
    assert len(rows) == 1, "UNIQUE(cutover_readiness_run_id) invariant must hold regardless of race outcome"
    assert rows[0].id == successes[0].id


async def test_decision_audit_failure_rolls_back_decision(pg_engine, pg_session, pg_seeded_users, monkeypatch):
    """If the mandatory audit write fails, the decision `INSERT` must
    roll back too: zero decision rows left, never a decision with no
    corresponding audit event.

    **This proof lives here, not in the SQLite API test file, because it
    is only meaningful under a dialect that actually enforces SAVEPOINT
    isolation on rollback** -- the identical rationale documented in
    `test_pr22e_reconciliation_signoff_concurrency.py::
    test_signoff_audit_failure_rolls_back_signoff`, which
    `create_go_no_go_decision`'s own `db.begin_nested()` duplicate-defense
    SAVEPOINT directly mirrors."""
    actor = pg_seeded_users["administrator"]
    completed = await _seed_completed_run(pg_session, actor_id=actor.id, seed="concurrency-audit-fail")

    async def _raise(*args, **kwargs):
        raise RuntimeError("simulated audit-subsystem failure")

    monkeypatch.setattr(audit_module, "record_audit_event", _raise)

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _attempt():
        # Mirrors app.api.v1.cutover_readiness.create_cutover_go_no_go_decision's
        # own shape exactly: create_go_no_go_decision (not yet committed)
        # -> mandatory audit write -> one commit.
        async with session_maker() as db:
            decision = await cutover_readiness_crud.create_go_no_go_decision(
                db, run_id=completed.id, expected_version=completed.version, actor_id=actor.id,
                decision="NO_GO", acknowledged_warning_codes=[], no_go_reason=None,
            )
            await audit_module.record_audit_event(
                db,
                actor_user_id=actor.id,
                action=audit_module.AUDIT_ACTION_CUTOVER_GO_NO_GO_DECISION_RECORDED,
                entity_type=audit_module.AUDIT_ENTITY_CUTOVER_GO_NO_GO_DECISION,
                entity_id=decision.id,
                after={"decision": decision.decision},
            )
            await db.commit()

    with pytest.raises(RuntimeError):
        await _attempt()

    rows = (
        await pg_session.execute(
            select(CutoverGoNoGoDecision).where(CutoverGoNoGoDecision.cutover_readiness_run_id == completed.id)
        )
    ).scalars().all()
    assert rows == [], "audit-write failure must leave zero decision rows -- never a decision with no audit event"
