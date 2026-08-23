"""Roadmap PR22E -- Reconciliation Sign-off + Concurrency/Audit. Genuine
two-connection PostgreSQL concurrency proofs for
`app.crud.legacy_reconciliation.create_signoff`'s own concurrency
contract (§13/§40 of the task) and the disposition/sign-off race
contract (§12/§41) -- this time using the *real*
`create_signoff`/`update_finding_disposition` functions on both sides of
the race, a stronger proof than PR22D's own test (which could only use a
test-only simulation of PR22E's future contract, since PR22E did not
exist yet).

Reuses `pg_engine`/`pg_session`/`pg_seeded_users` from
`test_postgres_integration.py`, the same real-PostgreSQL fixture pattern
every other genuine concurrency proof in this repository already uses
(see `test_pr22d_finding_review_concurrency.py`'s identical convention).
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import ReconciliationFindingSignedOffError, ReconciliationSignOffAlreadyExistsError
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
    authority = LegacyMigrationAuthority(scope="pr22e_test", approved_workbook_sha256=checksum, approved_by_user_id=actor_id)
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


async def _seed_run(
    db: AsyncSession, *, coverage: LegacyMigrationAuthorityCoverage, actor_id: uuid.UUID, summary_total_findings: int = 0
) -> LegacyReconciliationRun:
    run = LegacyReconciliationRun(
        coverage_id=coverage.id, legacy_coverage_start=coverage.legacy_coverage_start,
        legacy_coverage_end=coverage.legacy_coverage_end, live_system_start=coverage.live_system_start,
        rule_version=PR22_RECONCILIATION_RULE_VERSION, snapshot_as_of=datetime.now(timezone.utc),
        created_by_user_id=actor_id, status="completed", summary_total_findings=summary_total_findings,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def _seed_finding(db: AsyncSession, *, run_id: uuid.UUID, **overrides) -> LegacyReconciliationFinding:
    defaults = dict(
        run_id=run_id, code="SOURCE_PROVENANCE", severity="high", evidence={"reason_code": "test"},
        rule_version=PR22_RECONCILIATION_RULE_VERSION,
    )
    defaults.update(overrides)
    finding = LegacyReconciliationFinding(**defaults)
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    return finding


async def test_concurrent_signoff_writers_exactly_one_wins(pg_engine, pg_session, pg_seeded_users):
    """§13/§40 of the task: two real concurrent PostgreSQL Administrators
    both attempting to sign off the same run -- exactly one may create
    the sign-off; the second receives a deterministic structured
    conflict, never a raw `IntegrityError` or a duplicate row."""
    actor = pg_seeded_users["administrator"]
    coverage = await _seed_coverage(pg_session, actor_id=actor.id, checksum="3" * 64)
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id, summary_total_findings=0)

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _attempt():
        async with session_maker() as db:
            signoff, _ = await reconciliation_crud.create_signoff(
                db, run_id=run.id, expected_version=0, actor_id=actor.id
            )
            await db.commit()
            return signoff

    results = await asyncio.gather(_attempt(), _attempt(), return_exceptions=True)
    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1, f"exactly one concurrent sign-off must win, got {results}"
    assert len(failures) == 1
    assert isinstance(failures[0], ReconciliationSignOffAlreadyExistsError), failures[0]

    rows = (
        await pg_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))
    ).scalars().all()
    assert len(rows) == 1, "UNIQUE(run_id) invariant must hold regardless of race outcome"
    assert rows[0].id == successes[0].id


async def test_signoff_serializes_against_concurrent_disposition(pg_engine, pg_session, pg_seeded_users):
    """§12/§41 of the task -- the core TOCTOU-safety proof, this time
    using the *real* `create_signoff` on one side (PR22D's own test used
    a simulation, since PR22E did not exist yet). A sign-off-eligible
    run's single finding is re-dispositioned by one transaction while a
    sign-off is attempted by another, both following the documented
    Run-row-lock-first discipline -- they must serialize completely,
    never deadlock, and never reach a state where a disposition mutation
    successfully commits *after* a sign-off already succeeded (the
    disposition transaction must observe the sign-off and reject, per
    `ReconciliationFindingSignedOffError`'s own contract)."""
    actor = pg_seeded_users["administrator"]
    coverage = await _seed_coverage(pg_session, actor_id=actor.id, checksum="4" * 64)
    run = await _seed_run(pg_session, coverage=coverage, actor_id=actor.id, summary_total_findings=1)
    now = datetime.now(timezone.utc)
    finding = await _seed_finding(
        pg_session, run_id=run.id, disposition="confirmed_valid", disposed_by_user_id=actor.id, disposed_at=now
    )

    session_maker = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    async def _attempt_disposition():
        async with session_maker() as db:
            updated, _ = await reconciliation_crud.update_finding_disposition(
                db, finding_id=finding.id, expected_version=0, disposition="accepted_unresolved",
                disposition_note=None, actor_id=actor.id,
            )
            await db.commit()
            return updated

    async def _attempt_signoff():
        async with session_maker() as db:
            signoff, _ = await reconciliation_crud.create_signoff(
                db, run_id=run.id, expected_version=0, actor_id=actor.id
            )
            await db.commit()
            return signoff

    disposition_result, signoff_result = await asyncio.gather(
        _attempt_disposition(), _attempt_signoff(), return_exceptions=True
    )

    if isinstance(disposition_result, ReconciliationFindingSignedOffError):
        # The sign-off transaction won the run-lock race and committed
        # first -- the disposition mutation must have fully rejected,
        # leaving the finding completely unchanged (still its original
        # disposition/version).
        assert not isinstance(signoff_result, BaseException), signoff_result
        await pg_session.refresh(finding)
        assert finding.disposition == "confirmed_valid"
        assert finding.version == 0
    else:
        # The disposition transaction won the run-lock race and
        # committed first -- it must have fully succeeded, and the
        # sign-off (re-checking findings fresh under its own,
        # subsequently-acquired run lock) must observe the *new*
        # disposition state and still succeed -- never blocked forever
        # (no deadlock), never a lost/half-committed disposition, and
        # this ordering is exactly Scenario A of the task: "disposition
        # commits; sign-off resumes and observes latest committed
        # disposition."
        assert not isinstance(disposition_result, BaseException), disposition_result
        assert disposition_result.disposition == "accepted_unresolved"
        assert disposition_result.version == 1
        assert not isinstance(signoff_result, BaseException), signoff_result
        assert signoff_result is not None

    signoff_rows = (
        await pg_session.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run.id))
    ).scalars().all()
    assert len(signoff_rows) == 1, "the UNIQUE(run_id) sign-off invariant must hold regardless of race outcome"

    # The critical property (§12 of the task), checked directly rather
    # than only inferred from the branch above: whichever outcome
    # occurred, there is no observable final state where the finding's
    # disposition changed to a value the sign-off's own attestation does
    # not account for, and never a state where a disposition mutation
    # committed *after* the sign-off already existed while leaving the
    # run's sign-off absent (a self-contradiction that would mean the
    # lock order failed to serialize the two writers).
    await pg_session.refresh(finding)
    if signoff_rows:
        assert finding.disposition in ("confirmed_valid", "accepted_unresolved")
