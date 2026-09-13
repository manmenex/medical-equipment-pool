"""Roadmap PR23B (docs/design/PR23_CUTOVER_READINESS_PLAN.md §9, §10,
§11, §12 Gate D/E, §15, §16, §26 -- OD-PR23-1 through OD-PR23-6, all
RESOLVED / OWNER APPROVED via the PR23 Owner Decision Closure round) --
Cutover Readiness Evidence Foundation.

Covers: `CutoverReadinessRun`'s `pending`/`running`/`completed`/`failed`
status domain, `source_of_truth_strategy` domain (`hard_cutover` only),
`application_baseline_sha` length CHECK, `version` CAS shape, the
`completed_at`/`completed_by_user_id` and `current_state_verified_at`/
`current_state_verified_by_user_id` paired-nullability CHECKs, the
non-negative verification-scope-count CHECK, forward-only supersession
via `supersedes_run_id` (including self-supersession rejection), the
"completion requires every mandatory evidence reference" CHECK, FK
integrity against every referenced evidence table, and a real,
PostgreSQL-only migration upgrade/downgrade/re-upgrade round trip for
`0021_cutover_readiness.py`.

Does not test any readiness-gate evaluation (PR23C), Go/No-Go decision/
sign-off logic (PR23D), or frontend (PR23E) -- none of that exists yet.
Service-layer completion validation (evidence-reference existence,
sign-off/run pairing, `cutover_instant` vs. `live_system_start`) is
covered by `test_pr23b_cutover_readiness_api.py`, not here -- this
module exercises the schema directly via the ORM.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cutover_readiness import CutoverReadinessRun
from app.models.import_session import ImportSession, ImportSource
from app.models.legacy_history import LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.models.master_data import Ward
from app.models.user import User

# No module-level `pytestmark = pytest.mark.asyncio` -- `pytest.ini` sets
# `asyncio_mode = auto`.


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _get_user_id(db_session: AsyncSession) -> uuid.UUID:
    return (await db_session.execute(select(User.id).limit(1))).scalar_one()


async def _seed_import_source(db_session: AsyncSession, *, actor_id: uuid.UUID, checksum: str) -> ImportSource:
    session = ImportSession(dataset_type="equipment_master", status="created", version=0, created_by_user_id=actor_id)
    db_session.add(session)
    await db_session.flush()
    source = ImportSource(
        import_session_id=session.id,
        status="registered",
        checksum=checksum,
        byte_size=10,
        options_fingerprint="x",
        source_fingerprint="y",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    return source


async def _seed_authority(db_session: AsyncSession, *, actor_id: uuid.UUID, checksum: str) -> LegacyMigrationAuthority:
    authority = LegacyMigrationAuthority(
        scope="pr23b_test", approved_workbook_sha256=checksum, approved_by_user_id=actor_id
    )
    db_session.add(authority)
    await db_session.commit()
    await db_session.refresh(authority)
    return authority


async def _seed_coverage(
    db_session: AsyncSession, *, authority_id: uuid.UUID, actor_id: uuid.UUID
) -> LegacyMigrationAuthorityCoverage:
    coverage = LegacyMigrationAuthorityCoverage(
        migration_authority_id=authority_id,
        legacy_coverage_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        legacy_coverage_end=datetime(2025, 1, 1, tzinfo=timezone.utc),
        live_system_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        approval_basis="explicit_administrator_approval",
        approved_by_user_id=actor_id,
    )
    db_session.add(coverage)
    await db_session.commit()
    await db_session.refresh(coverage)
    return coverage


async def _seed_reconciliation_run(
    db_session: AsyncSession, *, coverage: LegacyMigrationAuthorityCoverage, actor_id: uuid.UUID
) -> LegacyReconciliationRun:
    run = LegacyReconciliationRun(
        coverage_id=coverage.id,
        legacy_coverage_start=coverage.legacy_coverage_start,
        legacy_coverage_end=coverage.legacy_coverage_end,
        live_system_start=coverage.live_system_start,
        rule_version="v1",
        snapshot_as_of=datetime.now(timezone.utc),
        created_by_user_id=actor_id,
        status="completed",
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


async def _seed_signoff(
    db_session: AsyncSession, *, run: LegacyReconciliationRun, actor_id: uuid.UUID
) -> LegacyReconciliationSignOff:
    signoff = LegacyReconciliationSignOff(
        run_id=run.id,
        signed_off_by_user_id=actor_id,
        attestation_summary={"run_id": str(run.id)},
        run_version_at_signoff=run.version,
    )
    db_session.add(signoff)
    await db_session.commit()
    await db_session.refresh(signoff)
    return signoff


async def _seed_ward(db_session: AsyncSession, *, code: str) -> Ward:
    ward = Ward(code=code, name=f"Ward {code}")
    db_session.add(ward)
    await db_session.commit()
    await db_session.refresh(ward)
    return ward


def _make_run(*, actor_id: uuid.UUID, **kwargs) -> CutoverReadinessRun:
    defaults = dict(
        created_by_user_id=actor_id,
        application_baseline_sha="a" * 40,
        database_migration_head="0021_cutover_readiness",
        cutover_instant=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return CutoverReadinessRun(**defaults)


async def _seed_evidence_bundle(db_session: AsyncSession, *, actor_id: uuid.UUID, seed: str):
    """Seeds one of each referenced evidence row, uniquely identified by
    `seed` so parametrized/parallel tests never collide on a unique
    constraint (checksum, etc.)."""
    source = await _seed_import_source(db_session, actor_id=actor_id, checksum=(seed * 64)[:64])
    authority = await _seed_authority(db_session, actor_id=actor_id, checksum=(seed * 64)[:64])
    coverage = await _seed_coverage(db_session, authority_id=authority.id, actor_id=actor_id)
    reconciliation_run = await _seed_reconciliation_run(db_session, coverage=coverage, actor_id=actor_id)
    signoff = await _seed_signoff(db_session, run=reconciliation_run, actor_id=actor_id)
    return source, authority, coverage, reconciliation_run, signoff


# ---------------------------------------------------------------------------
# A. Basic persistence / status / version / strategy domains
# ---------------------------------------------------------------------------


async def test_run_persists_with_defaults(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    run = _make_run(actor_id=actor_id)
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    assert run.status == "pending"
    assert run.version == 0
    assert run.source_of_truth_strategy == "hard_cutover"
    assert run.created_at is not None
    assert run.completed_at is None
    assert run.equipment_master_import_source_id is None


async def test_status_domain_rejects_unknown_value(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(_make_run(actor_id=actor_id, status="go"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
async def test_status_domain_accepts_non_completed_values(db_session: AsyncSession, seeded_users, status):
    actor_id = await _get_user_id(db_session)
    run = _make_run(actor_id=actor_id, status=status)
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.status == status


async def test_source_of_truth_strategy_domain_rejects_unknown_value(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(_make_run(actor_id=actor_id, source_of_truth_strategy="dual_write"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_baseline_sha_length_check_rejects_short_value(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(_make_run(actor_id=actor_id, application_baseline_sha="short"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_version_defaults_zero_and_check_rejects_negative(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    run = _make_run(actor_id=actor_id)
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.version == 0

    db_session.add(_make_run(actor_id=actor_id, version=-1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# B. Paired-nullability CHECKs
# ---------------------------------------------------------------------------


async def test_completed_pair_rejects_completed_at_without_user(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(_make_run(actor_id=actor_id, completed_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_completed_pair_rejects_user_without_completed_at(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(_make_run(actor_id=actor_id, completed_by_user_id=actor_id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_verification_pair_rejects_verified_at_without_user(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(_make_run(actor_id=actor_id, current_state_verified_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_verification_scope_count_check_rejects_negative(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(
        _make_run(
            actor_id=actor_id,
            current_state_verified_at=datetime.now(timezone.utc),
            current_state_verified_by_user_id=actor_id,
            current_state_verification_scope_count=-1,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# C. Forward-only supersession (mirrors LegacyReconciliationRun's OD-PR22-3)
# ---------------------------------------------------------------------------


async def test_supersedes_run_id_self_reference_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    run = _make_run(actor_id=actor_id)
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    run.supersedes_run_id = run.id
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_supersedes_run_id_references_prior_run(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    prior = _make_run(actor_id=actor_id)
    db_session.add(prior)
    await db_session.commit()
    await db_session.refresh(prior)

    newer = _make_run(actor_id=actor_id, supersedes_run_id=prior.id)
    db_session.add(newer)
    await db_session.commit()
    await db_session.refresh(newer)
    assert newer.supersedes_run_id == prior.id
    # The prior run is never mutated to record that a later run supersedes
    # it -- OD-PR22-3's forward-only discipline, reused here.
    await db_session.refresh(prior)
    assert prior.supersedes_run_id is None


async def test_supersedes_run_id_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    db_session.add(_make_run(actor_id=actor_id, supersedes_run_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# D. Completion-requires-evidence CHECK
# ---------------------------------------------------------------------------


async def test_completed_status_without_any_evidence_rejected(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    db_session.add(
        _make_run(
            actor_id=actor_id,
            status="completed",
            completed_at=datetime.now(timezone.utc),
            completed_by_user_id=actor_id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_completed_status_with_full_evidence_accepted(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    source, authority, coverage, reconciliation_run, signoff = await _seed_evidence_bundle(
        db_session, actor_id=actor_id, seed="d"
    )
    now = datetime.now(timezone.utc)
    run = _make_run(
        actor_id=actor_id,
        status="completed",
        completed_at=now,
        completed_by_user_id=actor_id,
        equipment_master_import_source_id=source.id,
        legacy_migration_authority_id=authority.id,
        legacy_coverage_id=coverage.id,
        reconciliation_run_id=reconciliation_run.id,
        reconciliation_signoff_id=signoff.id,
        current_state_verified_at=now,
        current_state_verified_by_user_id=actor_id,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.status == "completed"
    assert run.pilot_ward_id is None  # Pilot Ward is deliberately optional


async def test_completed_status_with_partial_evidence_rejected(db_session: AsyncSession, seeded_users):
    """One missing mandatory evidence field (`reconciliation_signoff_id`)
    is enough to reject the whole row -- no partial snapshot (§30 of the
    task)."""
    actor_id = await _get_user_id(db_session)
    source, authority, coverage, reconciliation_run, _signoff = await _seed_evidence_bundle(
        db_session, actor_id=actor_id, seed="e"
    )
    now = datetime.now(timezone.utc)
    run = _make_run(
        actor_id=actor_id,
        status="completed",
        completed_at=now,
        completed_by_user_id=actor_id,
        equipment_master_import_source_id=source.id,
        legacy_migration_authority_id=authority.id,
        legacy_coverage_id=coverage.id,
        reconciliation_run_id=reconciliation_run.id,
        # reconciliation_signoff_id intentionally omitted
        current_state_verified_at=now,
        current_state_verified_by_user_id=actor_id,
    )
    db_session.add(run)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_completed_status_with_pilot_ward_evidence_accepted(db_session: AsyncSession, seeded_users):
    actor_id = await _get_user_id(db_session)
    source, authority, coverage, reconciliation_run, signoff = await _seed_evidence_bundle(
        db_session, actor_id=actor_id, seed="f"
    )
    ward = await _seed_ward(db_session, code="PR23B-WARD")
    now = datetime.now(timezone.utc)
    run = _make_run(
        actor_id=actor_id,
        status="completed",
        completed_at=now,
        completed_by_user_id=actor_id,
        equipment_master_import_source_id=source.id,
        legacy_migration_authority_id=authority.id,
        legacy_coverage_id=coverage.id,
        reconciliation_run_id=reconciliation_run.id,
        reconciliation_signoff_id=signoff.id,
        current_state_verified_at=now,
        current_state_verified_by_user_id=actor_id,
        pilot_ward_id=ward.id,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    assert run.pilot_ward_id == ward.id


# ---------------------------------------------------------------------------
# E. FK integrity against every referenced evidence table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "equipment_master_import_source_id",
        "legacy_migration_authority_id",
        "legacy_coverage_id",
        "reconciliation_run_id",
        "reconciliation_signoff_id",
        "pilot_ward_id",
        "current_state_verified_by_user_id",
    ],
)
async def test_evidence_reference_fk_integrity(db_session: AsyncSession, seeded_users, field):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    actor_id = await _get_user_id(db_session)
    db_session.add(_make_run(actor_id=actor_id, **{field: uuid.uuid4()}))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_created_by_user_id_fk_integrity(db_session: AsyncSession, seeded_users):
    from sqlalchemy import text

    await db_session.execute(text("PRAGMA foreign_keys=ON"))
    db_session.add(_make_run(actor_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# F. No-mutation invariant against Equipment/BorrowTransaction/
#    LegacyEquipmentEvent -- this module never touches any of them.
# ---------------------------------------------------------------------------


async def test_module_defines_no_relationship_to_equipment_or_transaction():
    """Static assertion: `CutoverReadinessRun` has no column or
    relationship targeting `equipment`, `borrow_transactions`, or
    `legacy_equipment_events` -- evidence-foundation only, per the
    module's own docstring."""
    column_names = {c.name for c in CutoverReadinessRun.__table__.columns}
    forbidden_substrings = ("equipment_id", "borrow_transaction", "legacy_equipment_event")
    for name in column_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name or name == "equipment_master_import_source_id", (
                f"Unexpected column '{name}' suggests PR23B mutated or referenced live equipment/transaction "
                "state, which is out of this slice's scope."
            )


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

_NEW_TABLES = {"cutover_readiness_runs"}


async def _cutover_readiness_tables() -> set[str]:
    engine = create_async_engine(_scratch_dsn("postgresql+asyncpg"))
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
            return names & _NEW_TABLES
    finally:
        await engine.dispose()


@pytest.mark.postgres
async def test_migration_0021_upgrade_downgrade_round_trip():
    try:
        await _recreate_scratch_database()
    except Exception as exc:
        pytest.skip(f"Cannot create scratch database for migration test: {exc}")

    try:
        _run_alembic("upgrade", "head")
        tables = await _cutover_readiness_tables()
        assert tables == _NEW_TABLES

        _run_alembic("downgrade", "0020_reconciliation_foundation")
        tables = await _cutover_readiness_tables()
        assert tables == set(), "downgrade must remove exactly the one table this migration added"

        _run_alembic("upgrade", "head")
        tables = await _cutover_readiness_tables()
        assert tables == _NEW_TABLES, "re-upgrade must succeed and converge exactly like a fresh install"
    finally:
        await _drop_scratch_database()
