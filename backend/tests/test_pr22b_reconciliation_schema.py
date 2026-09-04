"""Roadmap PR22B (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md
§9.J, §11, §13-15, §17.2, §18, §20-22, §25, §36 -- OD-PR22-1 through
OD-PR22-7, all RESOLVED/OWNER APPROVED), refined by the PR22B
implementation task's own binding field contract -- Reconciliation
Schema + Run/Snapshot Foundation.

Covers: `LegacyMigrationAuthorityCoverage`'s coverage-window CHECK
(`<=`), `approval_basis` domain, and OD-PR22-7's gap/clean-handoff/
overlap temporal validity (all three relationships between
`legacy_coverage_end` and `live_system_start` are valid, none is
DB-rejected); `LegacyReconciliationRun`'s `pending`/`running`/
`completed`/`failed` status domain (no `signed_off` value), version CAS
shape, summary-counter non-negativity, and OD-PR22-3's forward-only
supersession via `supersedes_run_id` (including self-supersession
rejection); `LegacyReconciliationFinding`'s unconstrained `code` column
(deliberately no DB domain -- PR22C owns the taxonomy), closed
`severity` domain, OD-PR22-2's closed four-value disposition domain
(including the explicit `confirmed_pair` rejection required by §34),
and the disposition/disposed_by_user_id/disposed_at three-column
coherence CHECKs; `LegacyReconciliationFindingEvent`'s FK integrity and
per-finding/event uniqueness; `LegacyReconciliationSignOff`'s one-
signoff-per-run uniqueness (table shape only -- no sign-off logic
exists to test, per this slice's own scope boundary);
`LegacyBMEUserAlias`'s uniqueness/FK integrity and no-User-creation
side effect; the no-mutation invariant against `Equipment`/
`LegacyEquipmentEvent`; and a real, PostgreSQL-only migration upgrade/
downgrade/re-upgrade round trip for `0020_reconciliation_foundation.py`.

Does not test any analysis/detection logic (PR22C), any disposition-
mutation service (PR22D), or any sign-off precondition/audit logic
(PR22E) -- none of that exists yet; this module exercises the schema
directly via the ORM, the same way `test_pr21a_legacy_history_schema.py`
exercised PR21A's foundation before any adapter/service existed for it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import Equipment, EquipmentStatus
from app.models.legacy_history import LegacyEquipmentEvent, LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyBMEUserAlias,
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationFinding,
    LegacyReconciliationFindingEvent,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.models.user import User

# No module-level `pytestmark = pytest.mark.asyncio` -- `pytest.ini` sets
# `asyncio_mode = auto`, so every `async def test_*` here is already
# collected as an asyncio test without a marker.


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _get_user_id(db_session: AsyncSession) -> uuid.UUID:
    return (await db_session.execute(select(User.id).limit(1))).scalar_one()


async def _seed_equipment(db_session: AsyncSession, **kwargs) -> Equipment:
    defaults = dict(
        asset_number=f"AN-{uuid.uuid4().hex[:10]}",
        equipment_name="Reconciliation Test Equipment",
        status=EquipmentStatus.AVAILABLE_AT_POOL,
    )
    defaults.update(kwargs)
    eq = Equipment(**defaults)
    db_session.add(eq)
    await db_session.commit()
    await db_session.refresh(eq)
    return eq


async def _seed_authority(db_session: AsyncSession, *, actor_id: uuid.UUID, checksum: str) -> LegacyMigrationAuthority:
    authority = LegacyMigrationAuthority(scope="pr22_test", approved_workbook_sha256=checksum, approved_by_user_id=actor_id)
    db_session.add(authority)
    await db_session.commit()
    await db_session.refresh(authority)
    return authority


def _make_coverage(
    *,
    authority_id: uuid.UUID,
    actor_id: uuid.UUID,
    legacy_coverage_start: datetime,
    legacy_coverage_end: datetime,
    live_system_start: datetime,
    approval_basis: str = "explicit_administrator_approval",
) -> LegacyMigrationAuthorityCoverage:
    return LegacyMigrationAuthorityCoverage(
        migration_authority_id=authority_id,
        legacy_coverage_start=legacy_coverage_start,
        legacy_coverage_end=legacy_coverage_end,
        live_system_start=live_system_start,
        approval_basis=approval_basis,
        approved_by_user_id=actor_id,
    )


async def _seed_coverage(
    db_session: AsyncSession,
    *,
    authority_id: uuid.UUID,
    actor_id: uuid.UUID,
    legacy_coverage_end_offset_days: int = 0,
    approval_basis: str = "explicit_administrator_approval",
) -> LegacyMigrationAuthorityCoverage:
    """Default: clean handoff (`legacy_coverage_end == live_system_start`).
    `legacy_coverage_end_offset_days` shifts `legacy_coverage_end` alone,
    negative for a gap, positive for an overlap."""
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    live_start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = live_start + timedelta(days=legacy_coverage_end_offset_days)
    coverage = _make_coverage(
        authority_id=authority_id,
        actor_id=actor_id,
        legacy_coverage_start=start,
        legacy_coverage_end=end,
        live_system_start=live_start,
        approval_basis=approval_basis,
    )
    db_session.add(coverage)
    await db_session.commit()
    await db_session.refresh(coverage)
    return coverage


def _make_run(*, coverage: LegacyMigrationAuthorityCoverage, actor_id: uuid.UUID, **kwargs) -> LegacyReconciliationRun:
    defaults = dict(
        coverage_id=coverage.id,
        legacy_coverage_start=coverage.legacy_coverage_start,
        legacy_coverage_end=coverage.legacy_coverage_end,
        live_system_start=coverage.live_system_start,
        rule_version="v1",
        snapshot_as_of=datetime.now(timezone.utc),
        created_by_user_id=actor_id,
    )
    defaults.update(kwargs)
    return LegacyReconciliationRun(**defaults)


async def _seed_run(db_session: AsyncSession, *, coverage: LegacyMigrationAuthorityCoverage, actor_id: uuid.UUID, **kwargs) -> LegacyReconciliationRun:
    run = _make_run(coverage=coverage, actor_id=actor_id, **kwargs)
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


def _make_finding(*, run_id: uuid.UUID, **kwargs) -> LegacyReconciliationFinding:
    defaults = dict(run_id=run_id, code="PAIRING_CANDIDATE", severity="medium", evidence={}, rule_version="v1")
    defaults.update(kwargs)
    return LegacyReconciliationFinding(**defaults)


# ---------------------------------------------------------------------------
# A. LegacyMigrationAuthorityCoverage -- OD-PR22-7 two-boundary model
# ---------------------------------------------------------------------------


async def test_coverage_persists_governed_boundaries(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="a" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    assert coverage.migration_authority_id == authority.id
    assert coverage.approval_basis == "explicit_administrator_approval"
    assert coverage.approved_at is not None
    assert coverage.created_at is not None


async def test_coverage_window_start_after_end_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="b" * 64)
    db_session.add(
        _make_coverage(
            authority_id=authority.id,
            actor_id=actor_id,
            legacy_coverage_start=datetime(2025, 1, 2, tzinfo=timezone.utc),
            legacy_coverage_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
            live_system_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_coverage_window_start_equal_end_allowed(db_session: AsyncSession, seeded_users):
    """`<=` (not strict `<`) -- a zero-width coverage window is valid."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="b0" + "1" * 62)
    same = datetime(2025, 1, 1, tzinfo=timezone.utc)
    db_session.add(
        _make_coverage(
            authority_id=authority.id,
            actor_id=actor_id,
            legacy_coverage_start=same,
            legacy_coverage_end=same,
            live_system_start=same,
        )
    )
    await db_session.commit()


async def test_coverage_approval_basis_domain_rejects_unknown_value(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="c" * 64)
    db_session.add(
        _make_coverage(
            authority_id=authority.id,
            actor_id=actor_id,
            legacy_coverage_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            legacy_coverage_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
            live_system_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            approval_basis="verbal_approval",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("basis", ["explicit_owner_approval", "explicit_administrator_approval"])
async def test_coverage_approval_basis_domain_accepts_both_values(db_session: AsyncSession, seeded_users, basis):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=f"cb{basis[0]}".ljust(64, "0"))
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id, approval_basis=basis)
    assert coverage.approval_basis == basis


@pytest.mark.parametrize("offset_days,label", [(-30, "gap"), (0, "clean handoff"), (30, "overlap")])
async def test_coverage_end_vs_live_start_gap_clean_overlap_all_valid(db_session: AsyncSession, seeded_users, offset_days, label):
    """OD-PR22-7: gap (`<`), clean handoff (`==`), and overlap (`>`)
    between `legacy_coverage_end` and `live_system_start` are all valid
    -- none of them is ever DB-rejected."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=f"{label[0]}" * 64)
    coverage = await _seed_coverage(
        db_session, authority_id=authority.id, actor_id=actor_id, legacy_coverage_end_offset_days=offset_days
    )
    assert coverage.id is not None


async def test_coverage_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    db_session.add(
        _make_coverage(
            authority_id=uuid.uuid4(),
            actor_id=actor_id,
            legacy_coverage_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            legacy_coverage_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
            live_system_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_coverage_is_append_only_multiple_rows_per_authority_allowed(db_session: AsyncSession, seeded_users):
    """A correction never mutates an existing coverage row -- it mints a
    new one. Proven by two coverage rows legitimately coexisting for the
    same authority (no uniqueness constraint prevents it)."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="d" * 64)
    coverage_1 = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    coverage_2 = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id, legacy_coverage_end_offset_days=10)
    assert coverage_1.id != coverage_2.id

    rows = (
        await db_session.execute(select(LegacyMigrationAuthorityCoverage).where(LegacyMigrationAuthorityCoverage.migration_authority_id == authority.id))
    ).scalars().all()
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# B. LegacyReconciliationRun -- status domain, CAS shape, supersession
# ---------------------------------------------------------------------------


async def test_run_defaults_pending_status_and_zero_version(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="e" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    assert run.status == "pending"
    assert run.version == 0
    assert run.summary_total_findings == 0
    assert run.supersedes_run_id is None


async def test_run_status_invalid_value_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="f" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    db_session.add(_make_run(coverage=coverage, actor_id=actor_id, status="signed_off"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("status", ["pending", "running", "completed", "failed"])
async def test_run_status_domain_accepts_all_four_values(db_session: AsyncSession, seeded_users, status):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=f"s{status[0]}".ljust(64, "0"))
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status=status)
    assert run.status == status


async def test_run_summary_counters_reject_negative(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="1" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    db_session.add(_make_run(coverage=coverage, actor_id=actor_id, summary_high=-1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_run_version_rejects_negative(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="2" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    db_session.add(_make_run(coverage=coverage, actor_id=actor_id, version=-1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_run_coverage_window_start_after_end_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="3" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    db_session.add(
        _make_run(
            coverage=coverage,
            actor_id=actor_id,
            legacy_coverage_start=datetime(2025, 1, 2, tzinfo=timezone.utc),
            legacy_coverage_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_run_no_self_supersession(db_session: AsyncSession, seeded_users):
    """A run cannot supersede itself -- the CHECK is only satisfiable
    once the row has a real, distinct prior run's id."""
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="4" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    run_db = (await db_session.execute(select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == run.id))).scalar_one()
    run_db.supersedes_run_id = run_db.id
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_run_supersession_new_run_references_prior_without_mutating_it(db_session: AsyncSession, seeded_users):
    """OD-PR22-3: supersession is represented forward-only on the NEW
    run -- the prior (possibly signed) run is never mutated."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="5" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    prior_run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="completed")
    prior_status_before = prior_run.status
    prior_version_before = prior_run.version

    new_run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, supersedes_run_id=prior_run.id)
    assert new_run.supersedes_run_id == prior_run.id

    await db_session.refresh(prior_run)
    assert prior_run.status == prior_status_before
    assert prior_run.version == prior_version_before


async def test_run_may_coexist_without_supersession_relationship(db_session: AsyncSession, seeded_users):
    """Multiple runs may exist for the same coverage without any
    supersession relationship at all -- no "one active run" constraint
    is imposed by this slice."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="6" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run_a = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    run_b = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    assert run_a.id != run_b.id
    assert run_a.supersedes_run_id is None
    assert run_b.supersedes_run_id is None


async def test_run_snapshot_values_consistent_with_bound_coverage(db_session: AsyncSession, seeded_users):
    """§9.J: the coverage artifact is authoritative at run-creation time;
    the run's own copied values are snapshot evidence of what was
    authoritative then. Proven directly: a run created against a
    coverage carries identical timestamp values to that coverage."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="7" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    assert run.legacy_coverage_start == coverage.legacy_coverage_start
    assert run.legacy_coverage_end == coverage.legacy_coverage_end
    assert run.live_system_start == coverage.live_system_start


async def test_run_created_by_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="8" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    db_session.add(_make_run(coverage=coverage, actor_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# C. LegacyReconciliationFinding -- code, severity, OD-PR22-2 disposition
# ---------------------------------------------------------------------------


async def test_finding_code_is_unconstrained_bounded_varchar(db_session: AsyncSession, seeded_users):
    """§13: `code` has deliberately NO DB-level domain CHECK -- any
    bounded string, including a value outside the current reference
    list, is accepted (PR22C owns the evolving taxonomy)."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="9" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    finding = _make_finding(run_id=run.id, code="SOME_FUTURE_PR22C_CODE_NOT_YET_LISTED")
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    assert finding.code == "SOME_FUTURE_PR22C_CODE_NOT_YET_LISTED"
    assert finding.disposition is None


async def test_finding_severity_domain_rejects_invalid_value(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="0" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    db_session.add(_make_finding(run_id=run.id, severity="critical"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("severity", ["high", "medium", "low"])
async def test_finding_severity_domain_accepts_all_three_values(db_session: AsyncSession, seeded_users, severity):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=f"sv{severity[0]}".ljust(64, "0"))
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    finding = _make_finding(run_id=run.id, severity=severity)
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    assert finding.severity == severity


async def test_finding_equipment_id_is_nullable(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="aa" + "1" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    finding = _make_finding(run_id=run.id, equipment_id=None)
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    assert finding.equipment_id is None


async def test_finding_evidence_required_not_null(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="bb" + "2" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    finding = LegacyReconciliationFinding(run_id=run.id, code="X", severity="low", rule_version="v1")
    db_session.add(finding)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("disposition", ["confirmed_valid", "confirmed_duplicate", "accepted_unresolved", "requires_correction"])
async def test_finding_disposition_domain_accepts_all_four_values(db_session: AsyncSession, seeded_users, disposition):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=f"d{disposition[0]}".ljust(64, "0"))
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    finding = _make_finding(
        run_id=run.id,
        disposition=disposition,
        disposed_by_user_id=actor_id,
        disposed_at=datetime.now(timezone.utc),
    )
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    assert finding.disposition == disposition


async def test_finding_disposition_confirmed_pair_explicitly_rejected(db_session: AsyncSession, seeded_users):
    """§34: OD-PR22-2's vocabulary is closed at four values -- there is
    no `confirmed_pair`, even for a `PAIRING_CANDIDATE` finding. A
    `PAIRING_CANDIDATE` finding disposed `confirmed_valid` means the
    candidate pairing was reviewed and confirmed valid."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="cc" + "3" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    db_session.add(
        _make_finding(
            run_id=run.id,
            code="PAIRING_CANDIDATE",
            disposition="confirmed_pair",
            disposed_by_user_id=actor_id,
            disposed_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_finding_disposition_fifth_value_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="dd" + "4" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    db_session.add(
        _make_finding(
            run_id=run.id,
            disposition="ignored",
            disposed_by_user_id=actor_id,
            disposed_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_finding_disposition_pair_all_null_allowed(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="ee" + "5" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    finding = _make_finding(run_id=run.id)
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    assert finding.disposition is None
    assert finding.disposed_by_user_id is None
    assert finding.disposed_at is None
    assert finding.disposition_note is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"disposition": "confirmed_valid"},
        {"disposition": "confirmed_valid", "disposed_by_user_id": True},
        {"disposition": "confirmed_valid", "disposed_at": True},
        {"disposed_by_user_id": True},
        {"disposed_at": True},
    ],
)
async def test_finding_disposition_coherence_rejects_partial_triples(db_session: AsyncSession, seeded_users, overrides):
    """Two paired-nullability CHECKs together enforce: all three of
    `disposition`/`disposed_by_user_id`/`disposed_at` are `NULL`, or all
    three are set. Every partial combination must be rejected."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="ff" + str(hash(str(overrides)) % 10) * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    kwargs = {}
    if "disposition" in overrides:
        kwargs["disposition"] = overrides["disposition"]
    if overrides.get("disposed_by_user_id"):
        kwargs["disposed_by_user_id"] = actor_id
    if overrides.get("disposed_at"):
        kwargs["disposed_at"] = datetime.now(timezone.utc)

    db_session.add(_make_finding(run_id=run.id, **kwargs))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_finding_version_rejects_negative(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="00" + "6" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    db_session.add(_make_finding(run_id=run.id, version=-1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_finding_does_not_mutate_equipment_status_or_version(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="11" + "7" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    equipment = await _seed_equipment(db_session, status=EquipmentStatus.AVAILABLE_AT_POOL)
    version_before, status_before = equipment.version, equipment.status

    db_session.add(_make_finding(run_id=run.id, equipment_id=equipment.id))
    await db_session.commit()

    await db_session.refresh(equipment)
    assert equipment.version == version_before
    assert equipment.status == status_before


async def test_finding_equipment_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="22" + "8" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    db_session.add(_make_finding(run_id=run.id, equipment_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# D. LegacyReconciliationFindingEvent -- provenance junction
# ---------------------------------------------------------------------------


async def _seed_legacy_event(db_session: AsyncSession, *, actor_id: uuid.UUID, equipment: Equipment, checksum: str) -> tuple[LegacyEquipmentEvent, LegacyMigrationAuthority]:
    from app.models.import_session import ImportSession, ImportSource

    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=checksum)
    session = ImportSession(dataset_type="legacy_history", status="dry_run_completed", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id,
        status="frozen",
        checksum=checksum,
        byte_size=1,
        content_type="application/vnd.ms-excel",
        filename="wb.xlsx",
        options_fingerprint="x",
        source_fingerprint="y",
        frozen_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(session)
    await db_session.refresh(source)

    event = LegacyEquipmentEvent(
        migration_authority_id=authority.id,
        equipment_id=equipment.id,
        event_type="ISSUE",
        occurred_at=datetime.now(timezone.utc),
        legacy_source_row_key=f"row-{uuid.uuid4().hex[:8]}",
        import_session_id=session.id,
        import_source_id=source.id,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    return event, authority


async def test_finding_event_links_and_enforces_uniqueness(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    equipment = await _seed_equipment(db_session)
    event, authority = await _seed_legacy_event(db_session, actor_id=actor_id, equipment=equipment, checksum="ee0" + "4" * 61)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = _make_finding(run_id=run.id, equipment_id=equipment.id)
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)

    link = LegacyReconciliationFindingEvent(finding_id=finding.id, legacy_equipment_event_id=event.id)
    db_session.add(link)
    await db_session.commit()

    db_session.add(LegacyReconciliationFindingEvent(finding_id=finding.id, legacy_equipment_event_id=event.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_finding_event_same_event_may_support_multiple_findings(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    equipment = await _seed_equipment(db_session)
    event, authority = await _seed_legacy_event(db_session, actor_id=actor_id, equipment=equipment, checksum="ff0" + "5" * 61)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding_a = _make_finding(run_id=run.id, equipment_id=equipment.id, code="MISSING_IN_LIVE_SYSTEM")
    finding_b = _make_finding(run_id=run.id, equipment_id=equipment.id, code="CHRONOLOGY_ANOMALY")
    db_session.add_all([finding_a, finding_b])
    await db_session.commit()

    db_session.add(LegacyReconciliationFindingEvent(finding_id=finding_a.id, legacy_equipment_event_id=event.id))
    db_session.add(LegacyReconciliationFindingEvent(finding_id=finding_b.id, legacy_equipment_event_id=event.id))
    await db_session.commit()

    rows = (
        await db_session.execute(select(LegacyReconciliationFindingEvent).where(LegacyReconciliationFindingEvent.legacy_equipment_event_id == event.id))
    ).scalars().all()
    assert {r.finding_id for r in rows} == {finding_a.id, finding_b.id}


async def test_finding_event_fk_integrity_both_sides(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    equipment = await _seed_equipment(db_session)
    event, authority = await _seed_legacy_event(db_session, actor_id=actor_id, equipment=equipment, checksum="000" + "6" * 61)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = _make_finding(run_id=run.id, equipment_id=equipment.id)
    db_session.add(finding)
    await db_session.commit()
    finding_id = finding.id
    event_id = event.id

    db_session.add(LegacyReconciliationFindingEvent(finding_id=uuid.uuid4(), legacy_equipment_event_id=event_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    db_session.add(LegacyReconciliationFindingEvent(finding_id=finding_id, legacy_equipment_event_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_finding_event_does_not_mutate_legacy_equipment_event(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    equipment = await _seed_equipment(db_session)
    event, authority = await _seed_legacy_event(db_session, actor_id=actor_id, equipment=equipment, checksum="110" + "7" * 61)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding = _make_finding(run_id=run.id, equipment_id=equipment.id)
    db_session.add(finding)
    await db_session.commit()

    row_key_before = event.legacy_source_row_key
    db_session.add(LegacyReconciliationFindingEvent(finding_id=finding.id, legacy_equipment_event_id=event.id))
    await db_session.commit()

    await db_session.refresh(event)
    assert event.legacy_source_row_key == row_key_before
    assert event.equipment_id == equipment.id


# ---------------------------------------------------------------------------
# E. LegacyReconciliationSignOff -- OD-PR22-6 table shape, one per run
# ---------------------------------------------------------------------------


async def test_sign_off_persists_and_is_unique_per_run(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="22" + "8" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="completed")

    sign_off = LegacyReconciliationSignOff(
        run_id=run.id,
        signed_off_by_user_id=actor_id,
        attestation_summary={"total_findings": 0},
        run_version_at_signoff=run.version,
    )
    db_session.add(sign_off)
    await db_session.commit()
    await db_session.refresh(sign_off)
    assert sign_off.signed_off_at is not None

    db_session.add(
        LegacyReconciliationSignOff(
            run_id=run.id,
            signed_off_by_user_id=actor_id,
            attestation_summary={},
            run_version_at_signoff=run.version,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_sign_off_attestation_summary_required_not_null(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="33" + "9" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="completed")

    db_session.add(
        LegacyReconciliationSignOff(run_id=run.id, signed_off_by_user_id=actor_id, run_version_at_signoff=0)
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_sign_off_run_version_at_signoff_rejects_negative(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="44" + "0" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="completed")

    db_session.add(
        LegacyReconciliationSignOff(
            run_id=run.id, signed_off_by_user_id=actor_id, attestation_summary={}, run_version_at_signoff=-1
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_sign_off_scoped_per_run_not_global(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="55" + "1" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run_a = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="completed")
    run_b = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="completed", supersedes_run_id=run_a.id)

    db_session.add(
        LegacyReconciliationSignOff(
            run_id=run_a.id, signed_off_by_user_id=actor_id, attestation_summary={}, run_version_at_signoff=run_a.version
        )
    )
    db_session.add(
        LegacyReconciliationSignOff(
            run_id=run_b.id, signed_off_by_user_id=actor_id, attestation_summary={}, run_version_at_signoff=run_b.version
        )
    )
    await db_session.commit()

    rows = (await db_session.execute(select(LegacyReconciliationSignOff))).scalars().all()
    assert {r.run_id for r in rows} == {run_a.id, run_b.id}


async def test_sign_off_run_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    db_session.add(
        LegacyReconciliationSignOff(
            run_id=uuid.uuid4(), signed_off_by_user_id=actor_id, attestation_summary={}, run_version_at_signoff=0
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_sign_off_has_no_logic_only_shape():
    """Structural confirmation, per this slice's own scope boundary
    (§16, §20-22 belong to PR22E): the model exposes no method beyond
    plain ORM attribute access -- no `sign_off()`/`can_sign_off()`/
    precondition helper is defined on this class in this slice."""
    public_callables = {
        name
        for name in vars(LegacyReconciliationSignOff)
        if not name.startswith("_") and callable(getattr(LegacyReconciliationSignOff, name, None))
    }
    assert public_callables == set(), f"unexpected sign-off logic found on the model in this schema-only slice: {public_callables}"


# ---------------------------------------------------------------------------
# F. LegacyBMEUserAlias -- OD-PR22-4
# ---------------------------------------------------------------------------


async def test_bme_alias_raw_name_unique(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(LegacyBMEUserAlias(raw_bme_name="สมชาย ใจดี", resolved_user_id=actor_id, created_by_user_id=actor_id))
    await db_session.commit()

    db_session.add(LegacyBMEUserAlias(raw_bme_name="สมชาย ใจดี", resolved_user_id=actor_id, created_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_bme_alias_resolved_user_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    db_session.add(LegacyBMEUserAlias(raw_bme_name="ไม่มีผู้ใช้นี้", resolved_user_id=uuid.uuid4(), created_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_bme_alias_no_fuzzy_resolution_mechanism(db_session: AsyncSession, seeded_users):
    """OD-PR22-4: resolving an alias is a plain equality lookup -- a
    near-miss string never resolves."""
    actor_id = await _get_user_id(db_session)
    db_session.add(LegacyBMEUserAlias(raw_bme_name="Somchai J.", resolved_user_id=actor_id, created_by_user_id=actor_id))
    await db_session.commit()

    resolved = (
        await db_session.execute(select(LegacyBMEUserAlias).where(LegacyBMEUserAlias.raw_bme_name == "somchai j."))
    ).scalar_one_or_none()
    assert resolved is None, "case-differing text must not resolve -- no fuzzy/normalized lookup exists in this table"


async def test_bme_alias_does_not_create_a_user(db_session: AsyncSession, seeded_users):
    """Inserting an alias is a pure mapping row -- no side effect on the
    `users` table (count unchanged)."""
    actor_id = await _get_user_id(db_session)
    user_count_before = (await db_session.execute(select(User))).scalars().all()

    db_session.add(LegacyBMEUserAlias(raw_bme_name="ไม่สร้าง User ใหม่", resolved_user_id=actor_id, created_by_user_id=actor_id))
    await db_session.commit()

    user_count_after = (await db_session.execute(select(User))).scalars().all()
    assert len(user_count_after) == len(user_count_before)


async def test_bme_alias_created_by_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    db_session.add(LegacyBMEUserAlias(raw_bme_name="ผู้สร้างไม่มีจริง", resolved_user_id=actor_id, created_by_user_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# G. Migration round trip -- PostgreSQL only, real `alembic` CLI
# ---------------------------------------------------------------------------

pytest.importorskip("asyncpg")

from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from tests.test_postgres_integration import (  # noqa: E402
    _drop_scratch_database,
    _recreate_scratch_database,
    _run_alembic,
    _scratch_dsn,
)

_NEW_TABLES = {
    "legacy_migration_authority_coverages",
    "legacy_reconciliation_runs",
    "legacy_reconciliation_findings",
    "legacy_reconciliation_finding_events",
    "legacy_reconciliation_signoffs",
    "legacy_bme_user_aliases",
}


async def _reconciliation_tables() -> set[str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
            return names & _NEW_TABLES
    finally:
        await engine.dispose()


@pytest.mark.postgres
async def test_migration_0020_upgrade_downgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")
        tables = await _reconciliation_tables()
        assert tables == _NEW_TABLES

        _run_alembic("downgrade", "0019_legacy_history_foundation")
        tables = await _reconciliation_tables()
        assert tables == set(), "downgrade must remove exactly the six tables this migration added"

        _run_alembic("upgrade", "head")
        tables = await _reconciliation_tables()
        assert len(tables) == 6, "re-upgrade must succeed and converge exactly like a fresh install"
    finally:
        await _drop_scratch_database()
