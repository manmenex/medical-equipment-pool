"""Roadmap PR23B -- Cutover Readiness Evidence Foundation. Create/read/
list functions for `CutoverReadinessRun`, and the single completion
function that captures its immutable evidence snapshot.

**Lock-order contract for `complete_readiness_run`.** Mirrors
`app.crud.legacy_reconciliation.create_signoff`'s own discipline: lock
the `CutoverReadinessRun` row first (`SELECT ... FOR UPDATE`), verify
its mutability/version under that lock, validate every evidence
reference, then perform one CAS `UPDATE` -- all inside one transaction.
Only one call site in this module ever writes to a `CutoverReadinessRun`
row after creation (`complete_readiness_run`), so there is no second
concurrent write path this lock needs to exclude the way PR22D/E's dual
disposition/sign-off paths do -- the lock here exists purely so two
concurrent completion attempts against the same run can never both
observe "not yet completed" and race the CAS `UPDATE` (whichever
acquires the lock first completes the run; the second's own `WHERE
version = :expected_version` clause then correctly fails as a version
conflict, or its own `status != 'completed'` check fails first if it
re-reads under the lock).

**No commit anywhere in this module.** Every function's docstring
follows this repository's existing convention: the caller (the API
layer) commits once, together with the mandatory audit write, so the
two either land together or neither does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    CutoverReadinessEvidenceInvalidError,
    CutoverReadinessRunNotFoundError,
    CutoverReadinessRunNotMutableError,
    CutoverReadinessRunVersionConflictError,
)
from app.models.cutover_readiness import CutoverReadinessRun
from app.models.legacy_history import LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.models.import_session import ImportSource
from app.models.master_data import Ward
from app.models.user import User


def _use_for_update(db: AsyncSession):
    # Same dialect gate as app.crud.legacy_reconciliation and every other
    # `FOR UPDATE` call site in this codebase -- SQLite (the
    # non-PostgreSQL test suite) does not support `FOR UPDATE` the same
    # way, so it is only ever applied against a real PostgreSQL bind.
    return db.get_bind().dialect.name == "postgresql"


async def create_readiness_run(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    application_baseline_sha: str,
    database_migration_head: str,
    cutover_instant: datetime,
    source_of_truth_strategy: str = "hard_cutover",
    freeze_window_reference: str | None = None,
    supersedes_run_id: uuid.UUID | None = None,
) -> CutoverReadinessRun:
    """§5-9 of the task. Creates a new `pending` run with no evidence
    references yet -- `complete_readiness_run` attaches and validates
    them atomically. Does **not** commit.

    If `supersedes_run_id` is supplied, it is validated to exist before
    the new row is constructed -- a clean, structured
    `CutoverReadinessEvidenceInvalidError` rather than a raw FK
    `IntegrityError` for an obviously-wrong id, even though the FK's own
    `ON DELETE RESTRICT` provides defense-in-depth at the database level.
    """
    if supersedes_run_id is not None:
        exists = (
            await db.execute(select(CutoverReadinessRun.id).where(CutoverReadinessRun.id == supersedes_run_id))
        ).first()
        if exists is None:
            raise CutoverReadinessEvidenceInvalidError(
                f"supersedes_run_id '{supersedes_run_id}' does not reference an existing cutover readiness run."
            )

    run = CutoverReadinessRun(
        created_by_user_id=actor_id,
        application_baseline_sha=application_baseline_sha,
        database_migration_head=database_migration_head,
        cutover_instant=cutover_instant,
        source_of_truth_strategy=source_of_truth_strategy,
        freeze_window_reference=freeze_window_reference,
        supersedes_run_id=supersedes_run_id,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def list_readiness_runs(
    db: AsyncSession, *, limit: int, cursor_dt: datetime | None, cursor_id: uuid.UUID | None
) -> tuple[list[CutoverReadinessRun], int]:
    """Newest-first, cursor-paginated -- the same shape as
    `app.crud.legacy_reconciliation.list_runs`."""
    stmt = select(CutoverReadinessRun)
    if cursor_dt is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(
                CutoverReadinessRun.created_at < cursor_dt,
                and_(CutoverReadinessRun.created_at == cursor_dt, CutoverReadinessRun.id < cursor_id),
            )
        )
    stmt = stmt.order_by(CutoverReadinessRun.created_at.desc(), CutoverReadinessRun.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    total = (await db.execute(select(func.count()).select_from(CutoverReadinessRun))).scalar_one()
    return rows, total


async def get_readiness_run(db: AsyncSession, *, run_id: uuid.UUID) -> CutoverReadinessRun | None:
    return (
        await db.execute(select(CutoverReadinessRun).where(CutoverReadinessRun.id == run_id))
    ).scalar_one_or_none()


@dataclass(frozen=True)
class CompletionEvidence:
    """Every evidence reference `complete_readiness_run` accepts. A
    dataclass, not a loose keyword-argument list, so the completion
    function's own signature stays readable (§26/§30 of the task)."""

    equipment_master_import_source_id: uuid.UUID
    legacy_migration_authority_id: uuid.UUID
    legacy_coverage_id: uuid.UUID
    reconciliation_run_id: uuid.UUID
    reconciliation_signoff_id: uuid.UUID
    current_state_verified_at: datetime
    current_state_verified_by_user_id: uuid.UUID
    current_state_verification_scope_count: int | None = None
    current_state_verification_reference: str | None = None
    pilot_ward_id: uuid.UUID | None = None
    operational_approver_reference: str | None = None


async def _validate_evidence(db: AsyncSession, evidence: CompletionEvidence) -> None:
    """§26/§30 of the task: every reference is validated to exist, and the
    sign-off/run pairing and `cutover_instant` boundary are validated,
    inside the same transaction as the completion `UPDATE` -- never
    trusted from client input alone. Raises
    `CutoverReadinessEvidenceInvalidError` on the first failure found;
    does not attempt to collect every failure at once (matching this
    codebase's existing fail-fast validation style elsewhere)."""
    import_source = (
        await db.execute(select(ImportSource).where(ImportSource.id == evidence.equipment_master_import_source_id))
    ).scalar_one_or_none()
    if import_source is None:
        raise CutoverReadinessEvidenceInvalidError(
            f"equipment_master_import_source_id '{evidence.equipment_master_import_source_id}' does not "
            "reference an existing import source."
        )

    authority_exists = (
        await db.execute(
            select(LegacyMigrationAuthority.id).where(
                LegacyMigrationAuthority.id == evidence.legacy_migration_authority_id
            )
        )
    ).first()
    if authority_exists is None:
        raise CutoverReadinessEvidenceInvalidError(
            f"legacy_migration_authority_id '{evidence.legacy_migration_authority_id}' does not reference an "
            "existing migration authority."
        )

    coverage = (
        await db.execute(
            select(LegacyMigrationAuthorityCoverage).where(
                LegacyMigrationAuthorityCoverage.id == evidence.legacy_coverage_id
            )
        )
    ).scalar_one_or_none()
    if coverage is None:
        raise CutoverReadinessEvidenceInvalidError(
            f"legacy_coverage_id '{evidence.legacy_coverage_id}' does not reference an existing coverage artifact."
        )

    reconciliation_run_exists = (
        await db.execute(
            select(LegacyReconciliationRun.id).where(LegacyReconciliationRun.id == evidence.reconciliation_run_id)
        )
    ).first()
    if reconciliation_run_exists is None:
        raise CutoverReadinessEvidenceInvalidError(
            f"reconciliation_run_id '{evidence.reconciliation_run_id}' does not reference an existing "
            "reconciliation run."
        )

    signoff = (
        await db.execute(
            select(LegacyReconciliationSignOff).where(
                LegacyReconciliationSignOff.id == evidence.reconciliation_signoff_id
            )
        )
    ).scalar_one_or_none()
    if signoff is None:
        raise CutoverReadinessEvidenceInvalidError(
            f"reconciliation_signoff_id '{evidence.reconciliation_signoff_id}' does not reference an existing "
            "sign-off."
        )
    if signoff.run_id != evidence.reconciliation_run_id:
        raise CutoverReadinessEvidenceInvalidError(
            f"reconciliation_signoff_id '{evidence.reconciliation_signoff_id}' belongs to reconciliation run "
            f"'{signoff.run_id}', not the supplied reconciliation_run_id '{evidence.reconciliation_run_id}'."
        )

    verifier_exists = (
        await db.execute(select(User.id).where(User.id == evidence.current_state_verified_by_user_id))
    ).first()
    if verifier_exists is None:
        raise CutoverReadinessEvidenceInvalidError(
            f"current_state_verified_by_user_id '{evidence.current_state_verified_by_user_id}' does not "
            "reference an existing user."
        )

    if evidence.pilot_ward_id is not None:
        ward_exists = (await db.execute(select(Ward.id).where(Ward.id == evidence.pilot_ward_id))).first()
        if ward_exists is None:
            raise CutoverReadinessEvidenceInvalidError(
                f"pilot_ward_id '{evidence.pilot_ward_id}' does not reference an existing ward."
            )


async def complete_readiness_run(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    expected_version: int,
    actor_id: uuid.UUID,
    evidence: CompletionEvidence,
) -> CutoverReadinessRun:
    """§17/§26/§27/§30 of the task. Does **not** commit -- the caller (the
    API layer) commits once, together with the mandatory audit write.

    Order, every step inside one transaction:
    1. `SELECT ... FOR UPDATE` the `CutoverReadinessRun` row.
    2. Verify `status IN ('pending', 'running')` under the lock -- a
       `completed`/`failed` run's evidence snapshot is permanently
       immutable (module docstring).
    3. Verify `expected_version == run.version` under the lock.
    4. Validate every evidence reference exists and is internally
       consistent (`_validate_evidence`), including the sign-off/run
       pairing.
    5. Validate `cutover_instant >= coverage.live_system_start` (design
       §9) -- the reconciliation evidence a Go decision would rely on
       later can never postdate the moment it claims to cover.
    6. One CAS `UPDATE ... WHERE id = :run_id AND version =
       :expected_version` setting every evidence column, `completed_at`,
       `completed_by_user_id`, `status = 'completed'`, and
       `version = version + 1` together -- no partial snapshot is ever
       persisted (§30 of the task: "if any required reference is
       invalid, rollback whole completion" -- achieved here by raising
       before this single `UPDATE` is ever issued).
    """
    run_stmt = select(CutoverReadinessRun).where(CutoverReadinessRun.id == run_id)
    if _use_for_update(db):
        run_stmt = run_stmt.with_for_update()
    run = (await db.execute(run_stmt)).scalar_one_or_none()
    if run is None:
        raise CutoverReadinessRunNotFoundError(f"Cutover readiness run '{run_id}' not found.")

    if run.status not in ("pending", "running"):
        raise CutoverReadinessRunNotMutableError(
            f"Cutover readiness run '{run_id}' is not mutable (status='{run.status}') -- a completed or failed "
            "run's evidence snapshot is permanently immutable; create a new run (supersedes_run_id) instead."
        )
    if run.version != expected_version:
        raise CutoverReadinessRunVersionConflictError(
            f"Run '{run_id}' has version {run.version}, but expected_version {expected_version} was supplied -- "
            "re-fetch the run and retry with its current version."
        )

    await _validate_evidence(db, evidence)

    coverage = (
        await db.execute(
            select(LegacyMigrationAuthorityCoverage).where(
                LegacyMigrationAuthorityCoverage.id == evidence.legacy_coverage_id
            )
        )
    ).scalar_one()
    if run.cutover_instant < coverage.live_system_start:
        raise CutoverReadinessEvidenceInvalidError(
            f"cutover_instant ({run.cutover_instant.isoformat()}) is earlier than the bound coverage artifact's "
            f"live_system_start ({coverage.live_system_start.isoformat()}) -- the reconciliation evidence a Go "
            "decision would rely on cannot postdate the moment it claims to cover (design §9)."
        )

    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(CutoverReadinessRun)
        .where(CutoverReadinessRun.id == run_id, CutoverReadinessRun.version == expected_version)
        .values(
            status="completed",
            version=CutoverReadinessRun.version + 1,
            completed_at=now,
            completed_by_user_id=actor_id,
            equipment_master_import_source_id=evidence.equipment_master_import_source_id,
            legacy_migration_authority_id=evidence.legacy_migration_authority_id,
            legacy_coverage_id=evidence.legacy_coverage_id,
            reconciliation_run_id=evidence.reconciliation_run_id,
            reconciliation_signoff_id=evidence.reconciliation_signoff_id,
            current_state_verified_at=evidence.current_state_verified_at,
            current_state_verified_by_user_id=evidence.current_state_verified_by_user_id,
            current_state_verification_scope_count=evidence.current_state_verification_scope_count,
            current_state_verification_reference=evidence.current_state_verification_reference,
            pilot_ward_id=evidence.pilot_ward_id,
            operational_approver_reference=evidence.operational_approver_reference,
        )
        .returning(CutoverReadinessRun)
    )
    updated = result.scalar_one_or_none()
    if updated is None:
        raise CutoverReadinessRunVersionConflictError(
            f"Run '{run_id}' was modified concurrently, or expected_version {expected_version} is stale."
        )
    return updated
