"""Roadmap PR22B (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md
§9.J, §11, §13-15, §17.2, §18, §20-22, §25, §34, §36 -- OD-PR22-1
through OD-PR22-7, all RESOLVED/OWNER APPROVED) -- Reconciliation
Schema + Run/Snapshot Foundation.

Covers: `LegacyMigrationAuthorityCoverage`'s coverage-window CHECK and
OD-PR22-7's gap/clean-handoff/overlap temporal validity (all three
relationships between `legacy_coverage_end` and `live_system_start` are
valid, none is DB-rejected); `LegacyReconciliationRun`'s status domain,
default/version CAS shape, summary-counter non-negativity, and its
active/superseded/consumed/failed supersession lifecycle (including the
one-active-run-per-coverage partial unique index); `LegacyReconciliation
Finding`'s finding_type domain (including `PAIRING_CANDIDATE`),
OD-PR22-2's closed four-value disposition domain (including the
explicit `confirmed_pair` rejection required by §34), and the
disposition/disposed_by_user_id/disposed_at three-column coherence
CHECKs; `LegacyReconciliationFindingEvent`'s FK integrity and per-
finding/event uniqueness; `LegacyReconciliationSignOff`'s one-signoff-
per-run uniqueness (table shape only -- no sign-off logic exists to
test, per this slice's own scope boundary); the no-mutation invariant
against `Equipment`/`LegacyEquipmentEvent`; and a real, PostgreSQL-only
migration upgrade/downgrade/re-upgrade round trip for
`0020_reconciliation_foundation.py`.

Does not test `LegacyBMEUserAlias` -- deliberately deferred by this
slice, not implemented (see `app.models.legacy_reconciliation`'s module
docstring for the reasoning). Does not test any analysis/detection
logic (PR22C), any disposition-mutation service (PR22D), or any
sign-off precondition/audit logic (PR22E) -- none of that exists yet;
this module exercises the schema directly via the ORM, the same way
`test_pr21a_legacy_history_schema.py` exercised PR21A's foundation
before any adapter/service existed for it.
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
) -> LegacyMigrationAuthorityCoverage:
    return LegacyMigrationAuthorityCoverage(
        migration_authority_id=authority_id,
        legacy_coverage_start=legacy_coverage_start,
        legacy_coverage_end=legacy_coverage_end,
        live_system_start=live_system_start,
        approved_by_user_id=actor_id,
    )


async def _seed_coverage(
    db_session: AsyncSession,
    *,
    authority_id: uuid.UUID,
    actor_id: uuid.UUID,
    legacy_coverage_end_offset_days: int = 0,
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
    )
    db_session.add(coverage)
    await db_session.commit()
    await db_session.refresh(coverage)
    return coverage


def _make_run(*, coverage: LegacyMigrationAuthorityCoverage, actor_id: uuid.UUID, **kwargs) -> LegacyReconciliationRun:
    defaults = dict(
        coverage_id=coverage.id,
        legacy_coverage_start_snapshot=coverage.legacy_coverage_start,
        legacy_coverage_end_snapshot=coverage.legacy_coverage_end,
        live_system_start_snapshot=coverage.live_system_start,
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


def _make_finding(*, run_id: uuid.UUID, equipment_id: uuid.UUID, **kwargs) -> LegacyReconciliationFinding:
    defaults = dict(run_id=run_id, equipment_id=equipment_id, finding_type="PAIRING_CANDIDATE")
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
    assert coverage.approved_at is not None
    assert coverage.created_at is not None


async def test_coverage_window_start_before_end_enforced(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="b" * 64)
    db_session.add(
        _make_coverage(
            authority_id=authority.id,
            actor_id=actor_id,
            legacy_coverage_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            legacy_coverage_end=datetime(2020, 1, 1, tzinfo=timezone.utc),
            live_system_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


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
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="c" * 64)
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


async def test_run_defaults_active_status_and_zero_version(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="d" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    assert run.status == "active"
    assert run.version == 0
    assert run.summary_total_findings == 0


async def test_run_status_invalid_value_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="e" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    db_session.add(_make_run(coverage=coverage, actor_id=actor_id, status="bogus"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("status", ["active", "superseded", "consumed", "failed"])
async def test_run_status_domain_accepts_all_four_values(db_session: AsyncSession, seeded_users, status):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=f"s{status}".ljust(64, "0"))
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status=status)
    assert run.status == status


async def test_run_summary_counters_reject_negative(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="f" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    db_session.add(_make_run(coverage=coverage, actor_id=actor_id, summary_requires_correction=-1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_run_one_active_per_coverage_enforced(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="1" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="active")

    db_session.add(_make_run(coverage=coverage, actor_id=actor_id, status="active"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_run_supersession_allows_new_active_after_old_superseded(db_session: AsyncSession, seeded_users):
    """Re-analysis creates a NEW run row -- once the old `active` run is
    marked `superseded`, a fresh `active` run for the same coverage is
    accepted (the partial unique index only ever governs one live
    `active` row at a time)."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="2" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run_1 = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="active")

    run_1_db = (await db_session.execute(select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == run_1.id))).scalar_one()
    run_1_db.status = "superseded"
    await db_session.commit()

    run_2 = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="active")
    assert run_2.id != run_1.id

    rows = (
        await db_session.execute(select(LegacyReconciliationRun).where(LegacyReconciliationRun.coverage_id == coverage.id))
    ).scalars().all()
    assert {r.status for r in rows} == {"active", "superseded"}


async def test_run_one_active_per_coverage_scoped_not_global(db_session: AsyncSession, seeded_users):
    """The one-active constraint is per-coverage -- two different
    coverage artifacts may each independently have their own `active`
    run."""
    actor_id = await _get_user_id(db_session)
    authority_a = await _seed_authority(db_session, actor_id=actor_id, checksum="3" * 64)
    authority_b = await _seed_authority(db_session, actor_id=actor_id, checksum="4" * 64)
    coverage_a = await _seed_coverage(db_session, authority_id=authority_a.id, actor_id=actor_id)
    coverage_b = await _seed_coverage(db_session, authority_id=authority_b.id, actor_id=actor_id)

    run_a = await _seed_run(db_session, coverage=coverage_a, actor_id=actor_id, status="active")
    run_b = await _seed_run(db_session, coverage=coverage_b, actor_id=actor_id, status="active")
    assert run_a.coverage_id != run_b.coverage_id


async def test_run_snapshot_values_consistent_with_bound_coverage(db_session: AsyncSession, seeded_users):
    """§9.J: the coverage artifact is authoritative at run-creation time;
    the run's own copied values are snapshot evidence of what was
    authoritative then. Proven directly: a run created against a
    coverage carries identical timestamp values to that coverage."""
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="5" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    assert run.legacy_coverage_start_snapshot == coverage.legacy_coverage_start
    assert run.legacy_coverage_end_snapshot == coverage.legacy_coverage_end
    assert run.live_system_start_snapshot == coverage.live_system_start


async def test_run_created_by_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="6" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    db_session.add(_make_run(coverage=coverage, actor_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# C. LegacyReconciliationFinding -- finding_type + OD-PR22-2 disposition domain
# ---------------------------------------------------------------------------


async def test_finding_type_pairing_candidate_accepted(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="7" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    equipment = await _seed_equipment(db_session)

    finding = _make_finding(run_id=run.id, equipment_id=equipment.id, finding_type="PAIRING_CANDIDATE")
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    assert finding.finding_type == "PAIRING_CANDIDATE"
    assert finding.disposition is None


async def test_finding_type_invalid_value_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="8" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    equipment = await _seed_equipment(db_session)

    db_session.add(_make_finding(run_id=run.id, equipment_id=equipment.id, finding_type="NOT_A_REAL_TYPE"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("disposition", ["confirmed_valid", "confirmed_duplicate", "accepted_unresolved", "requires_correction"])
async def test_finding_disposition_domain_accepts_all_four_values(db_session: AsyncSession, seeded_users, disposition):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=f"d{disposition[0]}".ljust(64, "0"))
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    equipment = await _seed_equipment(db_session)

    finding = _make_finding(
        run_id=run.id,
        equipment_id=equipment.id,
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
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="9" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    equipment = await _seed_equipment(db_session)

    db_session.add(
        _make_finding(
            run_id=run.id,
            equipment_id=equipment.id,
            finding_type="PAIRING_CANDIDATE",
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
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="0" * 64)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    equipment = await _seed_equipment(db_session)

    db_session.add(
        _make_finding(
            run_id=run.id,
            equipment_id=equipment.id,
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
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="aa" + "1" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    equipment = await _seed_equipment(db_session)

    finding = _make_finding(run_id=run.id, equipment_id=equipment.id)
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    assert finding.disposition is None
    assert finding.disposed_by_user_id is None
    assert finding.disposed_at is None


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
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="bb" + str(hash(str(overrides)) % 10) * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    equipment = await _seed_equipment(db_session)

    kwargs = {}
    if "disposition" in overrides:
        kwargs["disposition"] = overrides["disposition"]
    if overrides.get("disposed_by_user_id"):
        kwargs["disposed_by_user_id"] = actor_id
    if overrides.get("disposed_at"):
        kwargs["disposed_at"] = datetime.now(timezone.utc)

    db_session.add(_make_finding(run_id=run.id, equipment_id=equipment.id, **kwargs))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_finding_does_not_mutate_equipment_status_or_version(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="cc" + "2" * 62)
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
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="dd" + "3" * 62)
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
    event, authority = await _seed_legacy_event(db_session, actor_id=actor_id, equipment=equipment, checksum="ee" + "4" * 62)
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
    event, authority = await _seed_legacy_event(db_session, actor_id=actor_id, equipment=equipment, checksum="ff" + "5" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)
    finding_a = _make_finding(run_id=run.id, equipment_id=equipment.id, finding_type="MISSING_IN_LIVE_SYSTEM")
    finding_b = _make_finding(run_id=run.id, equipment_id=equipment.id, finding_type="STATUS_CONFLICT")
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
    event, authority = await _seed_legacy_event(db_session, actor_id=actor_id, equipment=equipment, checksum="00" + "6" * 62)
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
    event, authority = await _seed_legacy_event(db_session, actor_id=actor_id, equipment=equipment, checksum="11" + "7" * 62)
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
    run = await _seed_run(db_session, coverage=coverage, actor_id=actor_id)

    sign_off = LegacyReconciliationSignOff(run_id=run.id, signed_off_by_user_id=actor_id, note="all clear")
    db_session.add(sign_off)
    await db_session.commit()
    await db_session.refresh(sign_off)
    assert sign_off.signed_off_at is not None

    db_session.add(LegacyReconciliationSignOff(run_id=run.id, signed_off_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_sign_off_scoped_per_run_not_global(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum="33" + "9" * 62)
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    run_a = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="superseded")
    run_b = await _seed_run(db_session, coverage=coverage, actor_id=actor_id, status="active")

    db_session.add(LegacyReconciliationSignOff(run_id=run_a.id, signed_off_by_user_id=actor_id))
    db_session.add(LegacyReconciliationSignOff(run_id=run_b.id, signed_off_by_user_id=actor_id))
    await db_session.commit()

    rows = (await db_session.execute(select(LegacyReconciliationSignOff))).scalars().all()
    assert {r.run_id for r in rows} == {run_a.id, run_b.id}


async def test_sign_off_run_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    db_session.add(LegacyReconciliationSignOff(run_id=uuid.uuid4(), signed_off_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_sign_off_has_no_logic_only_shape():
    """Structural confirmation, per this slice's own scope boundary
    (§20-22 belong to PR22E): the model exposes no method beyond plain
    ORM attribute access -- no `sign_off()`/`can_sign_off()`/precondition
    helper is defined on this class in this slice."""
    public_callables = {
        name
        for name in vars(LegacyReconciliationSignOff)
        if not name.startswith("_") and callable(getattr(LegacyReconciliationSignOff, name, None))
    }
    assert public_callables == set(), f"unexpected sign-off logic found on the model in this schema-only slice: {public_callables}"


# ---------------------------------------------------------------------------
# F. Migration round trip -- PostgreSQL only, real `alembic` CLI
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
    "legacy_reconciliation_sign_offs",
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
        assert tables == set(), "downgrade must remove exactly the five tables this migration added"

        _run_alembic("upgrade", "head")
        tables = await _reconciliation_tables()
        assert len(tables) == 5, "re-upgrade must succeed and converge exactly like a fresh install"
    finally:
        await _drop_scratch_database()
