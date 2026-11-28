"""Roadmap PR22D -- Finding Review / Disposition API. Genuine two-
connection PostgreSQL concurrency proofs for
`app.crud.legacy_reconciliation.update_finding_disposition`'s CAS
contract (§30 of the task) and its lock-order contract against a future
sign-off writer (§16).

Reuses `pg_engine`/`pg_session`/`pg_seeded_users` from
`test_postgres_integration.py`, the same real-PostgreSQL fixture pattern
every other genuine concurrency proof in this repository already uses
(see `test_pr22c_reconciliation_engine.py`'s identical convention)."""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import ReconciliationFindingSignedOffError, ReconciliationFindingVersionConflictError
from app.models.legacy_history import LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationFinding,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.crud import legacy_reconciliation as reconciliation_crud
from app.services.reconciliation.rule_version import PR22_RECONCILIATION_RULE_VERSION

from tests.test_postgres_integration import pg_engine, pg_session, pg_seeded_users  # noqa: F401

pytestmark = pytest.mark.postgres

_COVERAGE_START = datetime(2020, 1, 1, tzinfo=timezone.utc)
_COVERAGE_END = datetime(2024, 12, 31, tzinfo=timezone.utc)
_LIVE_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


async def _seed_coverage(db: AsyncSession, *, actor_id: uuid.UUID, checksum: str) -> LegacyMigrationAuthorityCoverage:
    authority = LegacyMigrationAuthority(scope="pr22d_test", approved_workbook_sha256=checksum, approved_by_user_id=actor_id)
    db.add(authority)
    await db.flush()
    coverage = LegacyMigrationAuthorityCoverage(
        migration_authority_id=authority.id, legacy_coverage_start=_COVERAGE_START,
        legacy_coverage_end=_COVERAGE_END, live_system_start=_LIVE_START,
        approval_basis="explicit_administrator_approval", approved_by_user_id=actor_id,
    )
    db.add(coverage)
    await db.commit()
    await db.refresh(coverage)
    return coverage


async def _seed_run(db: AsyncSession, *, coverage: LegacyMigrationAuthorityCoverage, actor_id: uuid.UUID) -> LegacyReconciliationRun:
    run = LegacyReconciliationRun(
        coverage_id=coverage.id, legacy_coverage_start=coverage.legacy_coverage_start,
        legacy_coverage_end=coverage.legacy_coverage_end, live_system_start=coverage.live_system_start,
        rule_version=PR22_RECONCILIATION_RULE_VERSION, snapshot_as_of=datetime.now(timezone.utc),
        created_by_user_id=actor_id, status="completed",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def _seed_finding(db: AsyncSession, *, run_id: uuid.UUID) -> LegacyReconciliationFinding:
    finding = LegacyReconciliationFinding(
        run_id=run_id, code="SOURCE_PROVENANCE", severity="high", evidence={"reason_code": "test"},
        rule_version=PR22_RECONCILIATION_RULE_VERSION,
    )
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    return finding


async def _simulate_signoff_insert(session: AsyncSession, *, run_id: uuid.UUID, actor_id: uuid.UUID) -> LegacyReconciliationSignOff:
    """Test-only simulation of PR22E's future sign-off-creation contract
    -- NOT real PR22E code (PR22E is out of scope for this PR). It exists
    solely to prove that `update_finding_disposition`'s documented lock
    order genuinely serializes against any future writer that follows
    the same discipline: lock the owning `LegacyReconciliationRun` row
    `FOR UPDATE` first, before touching `legacy_reconciliation_signoffs`
    at all."""
    run = (
        await session.execute(select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == run_id).with_for_update())
    ).scalar_one()
    signoff = LegacyReconciliationSignOff(
        run_id=run_id, signed_off_by_user_id=actor_id, attestation_summary={"note": "simulated"},
        run_version_at_signoff=run.version,
    )
    session.add(signoff)
    await session.commit()
    await session.refresh(signoff)
    return signoff


async def test_concurrent_disposition_writers_exactly_one_wins(pg_engine, pg_session, pg_seeded_users):
    """§30 of the task: two real concurrent PostgreSQL writers targeting
    the same finding with the same stale `expected_version` -- exactly
    one wins, the other gets a structured conflict, never a lost update
    or last-write-wins."""
    actor = pg_seeded_users["administrator"]
    coverage = await _seed_coverage(pg_session, actor_id=actor.id, checksum="1" * 64)
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)
    finding = await _seed_finding(pg_session, run_id=run.id)

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _attempt(disposition: str):
        async with session_maker() as db:
            updated, _ = await reconciliation_crud.update_finding_disposition(
                db, finding_id=finding.id, expected_version=0, disposition=disposition,
                disposition_note=None, actor_id=actor.id,
            )
            await db.commit()
            return updated

    results = await asyncio.gather(_attempt("confirmed_valid"), _attempt("confirmed_duplicate"), return_exceptions=True)
    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1, f"exactly one concurrent disposition write must win, got {results}"
    assert len(failures) == 1
    assert isinstance(failures[0], ReconciliationFindingVersionConflictError), failures[0]

    await pg_session.refresh(finding)
    assert finding.version == 1
    assert finding.disposition == successes[0].disposition


async def test_disposition_serializes_against_concurrent_signoff_insert(pg_engine, pg_session, pg_seeded_users):
    """§16 of the task -- the core TOCTOU-safety proof. A disposition
    mutation and a (simulated) concurrent sign-off insertion, both
    following the documented Run-row-lock-first discipline, must
    serialize completely: whichever acquires the run's `FOR UPDATE` lock
    first runs to full completion before the other's lock acquisition
    can proceed. Exactly one of two consistent final states results --
    never a state where a disposition change landed after a sign-off,
    and never a deadlock."""
    actor = pg_seeded_users["administrator"]
    coverage = await _seed_coverage(pg_session, actor_id=actor.id, checksum="2" * 64)
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id)
    finding = await _seed_finding(pg_session, run_id=run.id)

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _attempt_disposition():
        async with session_maker() as db:
            updated, _ = await reconciliation_crud.update_finding_disposition(
                db, finding_id=finding.id, expected_version=0, disposition="confirmed_valid",
                disposition_note=None, actor_id=actor.id,
            )
            await db.commit()
            return updated

    async def _attempt_signoff():
        async with session_maker() as db:
            return await _simulate_signoff_insert(db, run_id=run.id, actor_id=actor.id)

    disposition_result, signoff_result = await asyncio.gather(
        _attempt_disposition(), _attempt_signoff(), return_exceptions=True
    )

    if isinstance(disposition_result, ReconciliationFindingSignedOffError):
        # The sign-off transaction won the race and committed first --
        # the disposition mutation must have fully rejected, leaving the
        # finding completely unchanged.
        assert not isinstance(signoff_result, BaseException), signoff_result
        await pg_session.refresh(finding)
        assert finding.disposition is None
        assert finding.version == 0
    else:
        # The disposition transaction won the race and committed first --
        # it must have fully succeeded, and the sign-off insertion
        # (which does not itself depend on disposition state) must have
        # proceeded normally afterward, never blocked forever (no
        # deadlock) and never observing a half-committed disposition.
        assert not isinstance(disposition_result, BaseException), disposition_result
        assert disposition_result.disposition == "confirmed_valid"
        assert disposition_result.version == 1
        assert not isinstance(signoff_result, BaseException), signoff_result
        assert signoff_result is not None

    signoff_rows = (
        await pg_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))
    ).scalars().all()
    assert len(signoff_rows) == 1, "the UNIQUE(run_id) sign-off invariant must hold regardless of race outcome"
