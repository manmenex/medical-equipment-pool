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

from sqlalchemy import and_, exists, func, or_, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    CutoverDecisionAlreadyExistsError,
    CutoverDecisionBlockedByReadinessError,
    CutoverDecisionRequiresCompletedRunError,
    CutoverDecisionRunSupersededError,
    CutoverDecisionStaleVersionError,
    CutoverDecisionWarningsNotAcknowledgedError,
    CutoverReadinessDatabaseMigrationHeadUnavailableError,
    CutoverReadinessEvidenceInvalidError,
    CutoverReadinessRunNotFoundError,
    CutoverReadinessRunNotMutableError,
    CutoverReadinessRunVersionConflictError,
)
from app.models.cutover_readiness import CutoverGoNoGoDecision, CutoverReadinessRun
from app.models.legacy_history import LegacyMigrationAuthority
from app.models.legacy_reconciliation import (
    LegacyMigrationAuthorityCoverage,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.models.import_session import ImportSession, ImportSource
from app.services.import_adapters.equipment_master import DATASET_TYPE as EQUIPMENT_MASTER_DATASET_TYPE
from app.models.master_data import Ward
from app.models.user import User


def _use_for_update(db: AsyncSession):
    # Same dialect gate as app.crud.legacy_reconciliation and every other
    # `FOR UPDATE` call site in this codebase -- SQLite (the
    # non-PostgreSQL test suite) does not support `FOR UPDATE` the same
    # way, so it is only ever applied against a real PostgreSQL bind.
    return db.get_bind().dialect.name == "postgresql"


async def get_current_database_migration_head(db: AsyncSession) -> str:
    """PR23B Fix Round 1. Reads the database's own current Alembic
    revision from `alembic_version` -- this repository's migration
    policy assumes exactly one Alembic head (see `backend/alembic/
    versions/*`: every revision's `down_revision` forms one linear
    chain), so exactly one row is required; zero rows (never migrated)
    or more than one row (a multi-head state this repository's
    migration policy does not support) both fail closed rather than
    silently selecting an arbitrary row. Never derives the value from a
    hardcoded constant, a source-tree filename, an environment
    variable, or client/API-caller input -- the value must reflect the
    database itself, read at the moment this run is created."""
    try:
        rows = (await db.execute(text("SELECT version_num FROM alembic_version"))).all()
    except DBAPIError as exc:
        raise CutoverReadinessDatabaseMigrationHeadUnavailableError(
            "Could not read the database's current Alembic revision from 'alembic_version' -- the readiness "
            "evidence snapshot requires a genuine, database-observed schema-state fact."
        ) from exc
    if len(rows) != 1:
        raise CutoverReadinessDatabaseMigrationHeadUnavailableError(
            f"Expected exactly one row in 'alembic_version', found {len(rows)} -- cannot establish a single "
            "authoritative database migration head."
        )
    return rows[0][0]


async def create_readiness_run(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID,
    application_baseline_sha: str,
    cutover_instant: datetime,
    source_of_truth_strategy: str = "hard_cutover",
    freeze_window_reference: str | None = None,
    supersedes_run_id: uuid.UUID | None = None,
) -> CutoverReadinessRun:
    """§5-9 of the task. Creates a new `pending` run with no evidence
    references yet -- `complete_readiness_run` attaches and validates
    them atomically. Does **not** commit.

    **PR23B Fix Round 1: `database_migration_head` is not, and has never
    been, an accepted parameter of this function.** It is always
    read server-side from `alembic_version` by
    `get_current_database_migration_head` -- a caller/API layer cannot
    supply, override, or influence this value; see that helper's own
    docstring for the fail-closed contract if the database's current
    revision cannot be established.

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

    database_migration_head = await get_current_database_migration_head(db)

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


async def _validate_evidence(
    db: AsyncSession, evidence: CompletionEvidence
) -> LegacyMigrationAuthorityCoverage:
    """§26/§30 of the task, hardened by **PR23B Fix Round 1** and
    **PR23C Fix Round 1**: every reference is validated to exist, AND
    the whole provenance chain -- `MigrationAuthority -> Coverage ->
    ReconciliationRun -> SignOff` -- is validated to be internally
    consistent, AND `equipment_master_import_source_id`'s owning
    `ImportSession.dataset_type` is validated to actually be the
    Equipment Master dataset type (PR23C Fix Round 1 -- a field's name
    is not type safety; existence alone is insufficient) -- all inside
    the same transaction as the completion `UPDATE`. A syntactically
    valid but semantically mixed set of references (e.g. Authority A +
    Coverage B, where Coverage B actually belongs to Authority B, or an
    `equipment_master_import_source_id` that actually references a
    `legacy_transaction_history` import) must never pass. Never trusted
    from client input alone. Raises `CutoverReadinessEvidenceInvalidError`
    on the first failure found; does not attempt to collect every
    failure at once (matching this codebase's existing fail-fast
    validation style elsewhere). Returns the validated `coverage` row so
    the caller does not need to re-fetch it for the `cutover_instant`
    boundary check."""
    import_source = (
        await db.execute(select(ImportSource).where(ImportSource.id == evidence.equipment_master_import_source_id))
    ).scalar_one_or_none()
    if import_source is None:
        raise CutoverReadinessEvidenceInvalidError(
            f"equipment_master_import_source_id '{evidence.equipment_master_import_source_id}' does not "
            "reference an existing import source."
        )
    # PR23C Fix Round 1: `equipment_master_import_source_id` is only a
    # UUID reference -- its field name alone does not guarantee the
    # referenced ImportSource belongs to an Equipment Master
    # ImportSession. A completed source/session for a different
    # dataset_type (e.g. legacy_transaction_history) must never be
    # accepted as Equipment Master evidence; evidence must be valid at
    # capture/completion time, not only discovered invalid later by
    # PR23C's own gate evaluation.
    import_source_session = (
        await db.execute(select(ImportSession).where(ImportSession.id == import_source.import_session_id))
    ).scalar_one_or_none()
    if import_source_session is None or import_source_session.dataset_type != EQUIPMENT_MASTER_DATASET_TYPE:
        actual_dataset_type = import_source_session.dataset_type if import_source_session is not None else None
        raise CutoverReadinessEvidenceInvalidError(
            f"equipment_master_import_source_id '{evidence.equipment_master_import_source_id}' references an "
            f"import source whose owning import session's dataset_type is '{actual_dataset_type}', not "
            f"'{EQUIPMENT_MASTER_DATASET_TYPE}' -- Equipment Master evidence must reference an Equipment Master "
            "import."
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
    # PR23B Fix Round 1: the coverage's own approving authority must be
    # the exact authority supplied, not merely some authority that
    # happens to exist.
    if coverage.migration_authority_id != evidence.legacy_migration_authority_id:
        raise CutoverReadinessEvidenceInvalidError(
            f"legacy_coverage_id '{evidence.legacy_coverage_id}' belongs to migration authority "
            f"'{coverage.migration_authority_id}', not the supplied legacy_migration_authority_id "
            f"'{evidence.legacy_migration_authority_id}' -- evidence references must form one internally "
            "consistent provenance chain (design §15)."
        )

    reconciliation_run = (
        await db.execute(
            select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == evidence.reconciliation_run_id)
        )
    ).scalar_one_or_none()
    if reconciliation_run is None:
        raise CutoverReadinessEvidenceInvalidError(
            f"reconciliation_run_id '{evidence.reconciliation_run_id}' does not reference an existing "
            "reconciliation run."
        )
    # PR23B Fix Round 1: the reconciliation run's own bound coverage must
    # be the exact coverage supplied, not merely some coverage that
    # happens to exist.
    if reconciliation_run.coverage_id != evidence.legacy_coverage_id:
        raise CutoverReadinessEvidenceInvalidError(
            f"reconciliation_run_id '{evidence.reconciliation_run_id}' is bound to coverage "
            f"'{reconciliation_run.coverage_id}', not the supplied legacy_coverage_id "
            f"'{evidence.legacy_coverage_id}' -- evidence references must form one internally consistent "
            "provenance chain (design §15)."
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

    return coverage


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
    4. Validate every evidence reference exists AND that the whole
       provenance chain is internally consistent (`_validate_evidence`):
       coverage's authority, reconciliation run's coverage, and
       sign-off's run must each match the corresponding supplied id --
       existence of every individual row is insufficient on its own
       (**PR23B Fix Round 1**); the equipment_master_import_source_id's
       owning session must also actually be an Equipment Master import,
       not merely exist (**PR23C Fix Round 1**).
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

    coverage = await _validate_evidence(db, evidence)

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


async def get_go_no_go_decision(db: AsyncSession, *, run_id: uuid.UUID) -> CutoverGoNoGoDecision | None:
    return (
        await db.execute(select(CutoverGoNoGoDecision).where(CutoverGoNoGoDecision.cutover_readiness_run_id == run_id))
    ).scalar_one_or_none()


async def create_go_no_go_decision(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    expected_version: int,
    actor_id: uuid.UUID,
    decision: str,
    acknowledged_warning_codes: list[str],
    no_go_reason: str | None,
) -> CutoverGoNoGoDecision:
    """Roadmap PR23D (design §12 Gate G, §13, §16). Does **not** commit --
    the caller (the API layer) commits once, together with the mandatory
    audit write, mirroring every other mutation in this module.

    Order, every step inside one transaction (mirrors
    `app.crud.legacy_reconciliation.create_signoff`'s lock-order
    discipline, adapted for this table's own preconditions):

    1. `SELECT ... FOR UPDATE` the `CutoverReadinessRun` row -- always
       first.
    2. Verify `status == 'completed'` under the lock -- a decision is
       only ever recorded against a run whose immutable evidence
       snapshot was fully captured.
    3. Verify this run has not since been superseded (no other
       `CutoverReadinessRun.supersedes_run_id` points back at it) --
       design §16: "final Gate G decision only on the current
       non-superseded completed run." This is a genuinely new check for
       PR23D (distinct from PR23C's own Gate D, which checks
       `LegacyReconciliationRun` supersession, not `CutoverReadinessRun`
       supersession).
    4. Verify `expected_version == run.version` under the lock.
    5. Check for an existing `CutoverGoNoGoDecision` for this run --
       still under the run lock, so no concurrent decision insertion
       (following the same lock order) can land between this check and
       the `INSERT` below.
    6. **Fresh Gate A-F re-evaluation** (`app.services.
       cutover_readiness_gates.evaluate_gates`, imported locally to
       avoid a circular import with that module's own dependency on
       `get_current_database_migration_head` above) against the exact
       locked/current run -- never a client-supplied or earlier `GET
       .../gate-evaluation` response. For `GO` only: any BLOCKER item
       rejects the decision outright (§13: "cutover Go is
       deterministically impossible while any mandatory gate fails");
       every currently-live WARNING item `code` must appear in
       `acknowledged_warning_codes`, or the decision is rejected --
       comparison is against this fresh evaluation's own warning-code
       set, so a stale/unknown code the caller supplied can never
       satisfy a *different*, currently-live warning. `NO_GO` skips
       both checks entirely (§13: recording that cutover does not
       proceed requires no readiness justification) and is not itself
       gate-evaluated.
    7. `INSERT` the decision row, storing (for `GO`) the canonical
       sorted list of exactly the warning codes that were live and
       acknowledged at this moment -- never the raw client payload --
       or `[]` for `NO_GO`. `UNIQUE(cutover_readiness_run_id)` is caught
       as defense-in-depth (structurally redundant with step 5 under
       the run lock) and translated to the same structured conflict,
       never a raw `IntegrityError` (mirrors `create_signoff`'s
       identical `SAVEPOINT` pattern).
    """
    from app.services.cutover_readiness_gates import evaluate_gates

    run_stmt = select(CutoverReadinessRun).where(CutoverReadinessRun.id == run_id)
    if _use_for_update(db):
        run_stmt = run_stmt.with_for_update()
    run = (await db.execute(run_stmt)).scalar_one_or_none()
    if run is None:
        raise CutoverReadinessRunNotFoundError(f"Cutover readiness run '{run_id}' not found.")

    if run.status != "completed":
        raise CutoverDecisionRequiresCompletedRunError(
            f"Cutover readiness run '{run_id}' has status '{run.status}', not 'completed' -- a Go/No-Go decision "
            "requires a fully captured evidence snapshot."
        )

    superseded = (
        await db.execute(select(exists().where(CutoverReadinessRun.supersedes_run_id == run_id)))
    ).scalar_one()
    if superseded:
        raise CutoverDecisionRunSupersededError(
            f"Cutover readiness run '{run_id}' has since been superseded by a newer run -- record the decision "
            "against the current governing run instead."
        )

    if run.version != expected_version:
        raise CutoverDecisionStaleVersionError(
            f"Run '{run_id}' has version {run.version}, but expected_version {expected_version} was supplied -- "
            "re-fetch the run and retry with its current version."
        )

    if await get_go_no_go_decision(db, run_id=run_id) is not None:
        raise CutoverDecisionAlreadyExistsError(
            f"Cutover readiness run '{run_id}' already has a recorded Go/No-Go decision -- a decision is never "
            "created twice or modified; GET the existing decision instead."
        )

    stored_acknowledged_warning_codes: list[str] = []
    if decision == "GO":
        items = await evaluate_gates(db, run=run)
        blockers = [item for item in items if item.category == "blocker"]
        if blockers:
            raise CutoverDecisionBlockedByReadinessError(
                "GO is rejected: a fresh re-evaluation of Gates A-F found "
                f"{len(blockers)} BLOCKER item(s) -- "
                + "; ".join(f"[{b.gate}] {b.code}" for b in blockers)
                + "."
            )
        live_warning_codes = {item.code for item in items if item.category == "warning"}
        acknowledged = set(acknowledged_warning_codes)
        missing = live_warning_codes - acknowledged
        if missing:
            raise CutoverDecisionWarningsNotAcknowledgedError(
                "GO is rejected: the following currently-live WARNING item code(s) were not acknowledged -- "
                f"{sorted(missing)}."
            )
        stored_acknowledged_warning_codes = sorted(live_warning_codes)

    try:
        # SAVEPOINT, not a bare flush -- same rationale as
        # `create_signoff`'s identical comment: on the (structurally
        # unreachable under the run lock, but handled explicitly rather
        # than assumed away) IntegrityError branch below, this rolls
        # back only the failed INSERT, leaving the caller's own outer
        # transaction (and the run lock it holds) usable to continue.
        async with db.begin_nested():
            record = CutoverGoNoGoDecision(
                cutover_readiness_run_id=run_id,
                decision=decision,
                recorded_by_user_id=actor_id,
                run_version_at_decision=run.version,
                acknowledged_warning_codes=stored_acknowledged_warning_codes,
                no_go_reason=no_go_reason,
            )
            db.add(record)
            await db.flush()
    except IntegrityError as exc:
        raise CutoverDecisionAlreadyExistsError(
            f"Cutover readiness run '{run_id}' already has a recorded Go/No-Go decision -- a decision is never "
            "created twice or modified; GET the existing decision instead."
        ) from exc

    await db.refresh(record)
    return record
