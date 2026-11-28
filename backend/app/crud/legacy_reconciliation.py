"""Roadmap PR22D/PR22E -- Finding Review / Disposition API (PR22D) and
Reconciliation Sign-off (PR22E). Read/query functions for
`LegacyReconciliationRun`/`LegacyReconciliationFinding`, the disposition-
mutation function, and the sign-off-creation function -- both mutation
functions share one TOCTOU-safe lock order.

**Lock-order contract (PR22D §14-16, PR22E §11-12 of their respective
tasks) -- read this before touching `update_finding_disposition` or
`create_signoff`.** A naive "check no sign-off exists, then `UPDATE` the
finding" (or, symmetrically, "check findings complete, then `INSERT` the
sign-off") is unsafe: a concurrent transaction on the *other* write path
could commit in between the check and the write. This module closes that
gap the same way `app.crud.import_dry_run_plan.confirm_plan` already
closes an analogous one for `ImportSession`/`EquipmentMasterDryRunPlan`:
acquire an explicit `SELECT ... FOR UPDATE` on the *parent* row first
(here, `LegacyReconciliationRun`), in a fixed order, and hold it for the
entire transaction.

`update_finding_disposition` locks `LegacyReconciliationRun` first, then
`LegacyReconciliationFinding`, then checks for an existing `SignOff` row
-- all before the CAS `UPDATE`. `create_signoff` locks
`LegacyReconciliationRun` first too -- then validates status/version/
coverage, checks for an existing `SignOff` row, then queries finding
completeness/`requires_correction` -- all before the `SignOff` `INSERT`.
Both are inside one transaction the Run lock spans start to finish.
**Two transactions that both lock the same `Run` row before doing
anything else can never interleave**: whichever acquires the lock first
runs to completion (commit or rollback) before the other's lock
acquisition can proceed, so "check the other side's state, then act" is
safe on both sides without either transaction needing to know about the
other's existence. Neither function may invent a different lock order or
avoid locking the run row "since it's not modifying [disposition
fields|which sign-off to check]" -- the lock's entire purpose is mutual
exclusion between the two write paths, not protecting the run's own
columns.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ReconciliationFindingNotFoundError,
    ReconciliationFindingRunNotCompletedError,
    ReconciliationFindingSignedOffError,
    ReconciliationFindingVersionConflictError,
    ReconciliationRunNotFoundError,
    ReconciliationSignOffAlreadyExistsError,
    ReconciliationSignOffEvidenceInconsistentError,
    ReconciliationSignOffFindingsIncompleteError,
    ReconciliationSignOffRequiresCorrectionError,
    ReconciliationSignOffRunNotCompletedError,
    ReconciliationSignOffVersionConflictError,
)
from app.models.legacy_history import LegacyEquipmentEvent
from app.models.legacy_reconciliation import (
    LegacyReconciliationFinding,
    LegacyReconciliationFindingEvent,
    LegacyReconciliationRun,
    LegacyReconciliationSignOff,
)
from app.services.reconciliation.coverage import verify_coverage_integrity


def _use_for_update(db: AsyncSession):
    # Same dialect gate as app.crud.import_dry_run_plan.confirm_plan and
    # every other `FOR UPDATE` call site in this codebase -- SQLite (used
    # by the non-PostgreSQL test suite) does not support `FOR UPDATE` the
    # same way, so it is only ever applied against a real PostgreSQL bind.
    return db.get_bind().dialect.name == "postgresql"


async def list_runs(
    db: AsyncSession, *, limit: int, cursor_dt: datetime | None, cursor_id: uuid.UUID | None
) -> tuple[list[LegacyReconciliationRun], int]:
    """Newest-first, cursor-paginated -- the same shape as
    `app.crud.import_session.list_sessions`."""
    stmt = select(LegacyReconciliationRun)
    if cursor_dt is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(
                LegacyReconciliationRun.created_at < cursor_dt,
                and_(LegacyReconciliationRun.created_at == cursor_dt, LegacyReconciliationRun.id < cursor_id),
            )
        )
    stmt = stmt.order_by(LegacyReconciliationRun.created_at.desc(), LegacyReconciliationRun.id.desc()).limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    total = (await db.execute(select(func.count()).select_from(LegacyReconciliationRun))).scalar_one()
    return rows, total


async def get_run(db: AsyncSession, *, run_id: uuid.UUID) -> LegacyReconciliationRun | None:
    return (
        await db.execute(select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == run_id))
    ).scalar_one_or_none()


async def list_signoff_run_ids(db: AsyncSession, *, run_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Batched existence check for a whole page of runs at once -- never
    one query per row (§23 of the task)."""
    if not run_ids:
        return set()
    rows = (
        await db.execute(select(LegacyReconciliationSignOff.run_id).where(LegacyReconciliationSignOff.run_id.in_(run_ids)))
    ).scalars().all()
    return set(rows)


async def run_has_signoff(db: AsyncSession, *, run_id: uuid.UUID) -> bool:
    return (
        await db.execute(select(LegacyReconciliationSignOff.id).where(LegacyReconciliationSignOff.run_id == run_id))
    ).first() is not None


async def finding_counts_by_disposition(db: AsyncSession, *, run_id: uuid.UUID) -> dict[str | None, int]:
    """One `GROUP BY` query -- never one query per disposition value."""
    rows = (
        await db.execute(
            select(LegacyReconciliationFinding.disposition, func.count())
            .where(LegacyReconciliationFinding.run_id == run_id)
            .group_by(LegacyReconciliationFinding.disposition)
        )
    ).all()
    return {disposition: count for disposition, count in rows}


async def list_findings(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    limit: int,
    cursor_dt: datetime | None,
    cursor_id: uuid.UUID | None,
    code: str | None,
    severity: str | None,
    disposition: str | None,
    disposition_is_null: bool,
    equipment_id: uuid.UUID | None,
) -> tuple[list[LegacyReconciliationFinding], int]:
    """Oldest-first (`created_at ASC, id ASC`), cursor-paginated -- this
    repository has no explicit severity-priority ordering convention, so
    this mirrors `app.crud.import_job.list_findings`'s own default
    (creation order), never DB natural row order (§8 of the task). All
    filters are applied in SQL, never loaded unbounded and Python-
    filtered (§23)."""
    filters = [LegacyReconciliationFinding.run_id == run_id]
    if code is not None:
        filters.append(LegacyReconciliationFinding.code == code)
    if severity is not None:
        filters.append(LegacyReconciliationFinding.severity == severity)
    if disposition_is_null:
        filters.append(LegacyReconciliationFinding.disposition.is_(None))
    elif disposition is not None:
        filters.append(LegacyReconciliationFinding.disposition == disposition)
    if equipment_id is not None:
        filters.append(LegacyReconciliationFinding.equipment_id == equipment_id)

    stmt = select(LegacyReconciliationFinding).where(*filters)
    if cursor_dt is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(
                LegacyReconciliationFinding.created_at > cursor_dt,
                and_(LegacyReconciliationFinding.created_at == cursor_dt, LegacyReconciliationFinding.id > cursor_id),
            )
        )
    stmt = stmt.order_by(LegacyReconciliationFinding.created_at.asc(), LegacyReconciliationFinding.id.asc()).limit(
        limit + 1
    )
    rows = list((await db.execute(stmt)).scalars().all())

    total = (await db.execute(select(func.count()).select_from(LegacyReconciliationFinding).where(*filters))).scalar_one()
    return rows, total


async def get_finding(db: AsyncSession, *, finding_id: uuid.UUID) -> LegacyReconciliationFinding | None:
    return (
        await db.execute(select(LegacyReconciliationFinding).where(LegacyReconciliationFinding.id == finding_id))
    ).scalar_one_or_none()


async def list_finding_event_refs(db: AsyncSession, *, finding_id: uuid.UUID) -> list[LegacyEquipmentEvent]:
    stmt = (
        select(LegacyEquipmentEvent)
        .join(
            LegacyReconciliationFindingEvent,
            LegacyReconciliationFindingEvent.legacy_equipment_event_id == LegacyEquipmentEvent.id,
        )
        .where(LegacyReconciliationFindingEvent.finding_id == finding_id)
        .order_by(LegacyEquipmentEvent.occurred_at, LegacyEquipmentEvent.id)
    )
    return list((await db.execute(stmt)).scalars().all())


@dataclass(frozen=True)
class DispositionPreviousState:
    """Captured under the finding's own row lock, immediately before the
    CAS `UPDATE` -- the exact "before" half of the mandatory audit
    before/after payload (§21 of the task)."""

    disposition: str | None
    disposed_by_user_id: uuid.UUID | None
    disposed_at: datetime | None
    disposition_note: str | None
    version: int


async def update_finding_disposition(
    db: AsyncSession,
    *,
    finding_id: uuid.UUID,
    expected_version: int,
    disposition: str,
    disposition_note: str | None,
    actor_id: uuid.UUID,
) -> tuple[LegacyReconciliationFinding, DispositionPreviousState]:
    """OD-PR22-5/§13-17 of the task. Does **not** commit -- the caller (the
    API layer) commits once, together with the mandatory audit write, so
    the two either land together or neither does (§22).

    Order, every step inside one transaction:
    1. A cheap, unlocked existence probe for the finding, to discover its
       `run_id` (needed to know which run to lock -- cannot lock the run
       before knowing its id).
    2. `SELECT ... FOR UPDATE` the `LegacyReconciliationRun` row --
       always first, per this module's own docstring. Verify
       `status == 'completed'` under the lock (§34 of the task): a
       `pending`/`running`/`failed` run has no stable, reviewable finding
       set to disposition against.
    3. `SELECT ... FOR UPDATE` the `LegacyReconciliationFinding` row,
       ownership-checked against `run_id`.
    4. Check for an existing `LegacyReconciliationSignOff` for this run --
       still under the run lock acquired in step 2, so no concurrent
       sign-off insertion (following the same lock order) can land
       between this check and the `UPDATE` below.
    5. The CAS `UPDATE ... WHERE id = :finding_id AND version =
       :expected_version` -- redundant with the row lock already held
       (no other transaction could have raced this write in between),
       kept as explicit, self-documenting defense-in-depth matching
       `confirm_plan`'s identical discipline.
    """
    probe = (
        await db.execute(
            select(LegacyReconciliationFinding.id, LegacyReconciliationFinding.run_id).where(
                LegacyReconciliationFinding.id == finding_id
            )
        )
    ).first()
    if probe is None:
        raise ReconciliationFindingNotFoundError(f"Reconciliation finding '{finding_id}' not found.")
    run_id = probe.run_id

    run_stmt = select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == run_id)
    if _use_for_update(db):
        run_stmt = run_stmt.with_for_update()
    run = (await db.execute(run_stmt)).scalar_one_or_none()
    if run is None:
        # Unreachable under normal operation -- `finding.run_id` is an
        # `ON DELETE RESTRICT` FK to a row that can never be deleted.
        # Raised rather than assumed away, matching this codebase's
        # defensive-but-explicit style.
        raise ReconciliationRunNotFoundError(f"Reconciliation run '{run_id}' not found.")
    if run.status != "completed":
        raise ReconciliationFindingRunNotCompletedError(
            f"Reconciliation run '{run_id}' is not 'completed' (currently '{run.status}') -- disposition mutation "
            "is only permitted against a completed run's stable finding set."
        )

    finding_stmt = select(LegacyReconciliationFinding).where(
        LegacyReconciliationFinding.id == finding_id, LegacyReconciliationFinding.run_id == run_id
    )
    if _use_for_update(db):
        finding_stmt = finding_stmt.with_for_update()
    finding = (await db.execute(finding_stmt)).scalar_one_or_none()
    if finding is None:
        raise ReconciliationFindingNotFoundError(f"Reconciliation finding '{finding_id}' not found.")

    if await run_has_signoff(db, run_id=run_id):
        raise ReconciliationFindingSignedOffError(
            f"Reconciliation run '{run_id}' has already been signed off -- finding '{finding_id}''s disposition "
            "is now permanently immutable."
        )

    previous = DispositionPreviousState(
        disposition=finding.disposition,
        disposed_by_user_id=finding.disposed_by_user_id,
        disposed_at=finding.disposed_at,
        disposition_note=finding.disposition_note,
        version=finding.version,
    )

    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(LegacyReconciliationFinding)
        .where(
            LegacyReconciliationFinding.id == finding_id,
            LegacyReconciliationFinding.run_id == run_id,
            LegacyReconciliationFinding.version == expected_version,
        )
        .values(
            disposition=disposition,
            disposed_by_user_id=actor_id,
            disposed_at=now,
            disposition_note=disposition_note,
            version=LegacyReconciliationFinding.version + 1,
        )
        .returning(LegacyReconciliationFinding)
    )
    updated = result.scalar_one_or_none()
    if updated is None:
        raise ReconciliationFindingVersionConflictError(
            f"Finding '{finding_id}' was modified concurrently, or expected_version {expected_version} is stale."
        )
    return updated, previous


async def get_signoff(db: AsyncSession, *, run_id: uuid.UUID) -> LegacyReconciliationSignOff | None:
    return (
        await db.execute(select(LegacyReconciliationSignOff).where(LegacyReconciliationSignOff.run_id == run_id))
    ).scalar_one_or_none()


async def create_signoff(
    db: AsyncSession,
    *,
    run_id: uuid.UUID,
    expected_version: int,
    actor_id: uuid.UUID,
) -> tuple[LegacyReconciliationSignOff, dict]:
    """Roadmap PR22E §9-22 of the task; §20 of the design (all eight
    sign-off preconditions). Does **not** commit -- the caller (the API
    layer) commits once, together with the mandatory audit write (§23-24
    of the task), so the two either land together or neither does.

    Order, every step inside one transaction:
    1. `SELECT ... FOR UPDATE` the `LegacyReconciliationRun` row --
       always first, per this module's own docstring.
    2. Verify `status == 'completed'` under the lock (precondition 1).
    3. Verify `expected_version == run.version` under the lock
       (precondition 8's run-freshness half; `run.version` is bumped
       only by run-lifecycle transitions, never by a finding disposition
       change -- see the design's §22).
    4. Verify coverage integrity (precondition 4/OD-PR22-7) via the
       shared `app.services.reconciliation.coverage.verify_coverage_
       integrity` helper -- fail closed, never repaired/inferred.
    5. Check for an existing `LegacyReconciliationSignOff` for this run
       -- still under the run lock acquired in step 1, so no concurrent
       sign-off insertion (following the same lock order) can land
       between this check and the `INSERT` below (precondition 8's
       concurrency half).
    6. One `GROUP BY` aggregate query (`finding_counts_by_disposition`,
       already used by PR22D's own run-detail endpoint -- reused here
       rather than a second, duplicated query) to evaluate preconditions
       5 and 6 together: `disposition IS NULL` count must be zero
       (precondition 5), and `disposition = 'requires_correction'` count
       must independently also be zero (precondition 6, OD-PR22-6) --
       neither substitutes for the other. Evaluated in that order
       (incomplete review first, then requires_correction) for a
       deterministic precedence when a run has both problems at once.
    7. Cross-check the fresh finding total against `run.summary_total_
       findings` -- sign-off never proceeds against evidence it cannot
       reconcile against itself.
    8. Construct the immutable `attestation_summary` from database truth
       observed under this same transaction/lock -- never from
       client-supplied values (§20/§21 of the task).
    9. `INSERT` the `SignOff` row. `UNIQUE(run_id)` is caught as
       defense-in-depth (structurally redundant with step 5 under the
       run lock) and translated to the same structured conflict, never a
       raw `IntegrityError`.
    """
    run_stmt = select(LegacyReconciliationRun).where(LegacyReconciliationRun.id == run_id)
    if _use_for_update(db):
        run_stmt = run_stmt.with_for_update()
    run = (await db.execute(run_stmt)).scalar_one_or_none()
    if run is None:
        raise ReconciliationRunNotFoundError(f"Reconciliation run '{run_id}' not found.")

    if run.status != "completed":
        raise ReconciliationSignOffRunNotCompletedError(
            f"Reconciliation run '{run_id}' is not 'completed' (currently '{run.status}') -- only a closed, "
            "immutable run/snapshot may be signed off."
        )
    if run.version != expected_version:
        raise ReconciliationSignOffVersionConflictError(
            f"Run '{run_id}' has version {run.version}, but expected_version {expected_version} was supplied -- "
            "re-fetch the run and retry with its current version."
        )

    coverage = await verify_coverage_integrity(db, run=run)

    if await run_has_signoff(db, run_id=run_id):
        raise ReconciliationSignOffAlreadyExistsError(
            f"Reconciliation run '{run_id}' has already been signed off -- a sign-off is never created twice or "
            "modified; GET the existing attestation instead."
        )

    counts = await finding_counts_by_disposition(db, run_id=run_id)
    total_findings = sum(counts.values())
    null_count = counts.get(None, 0)
    requires_correction_count = counts.get("requires_correction", 0)

    if total_findings != run.summary_total_findings:
        raise ReconciliationSignOffEvidenceInconsistentError(
            f"Run '{run_id}' has {total_findings} persisted findings, but its own summary_total_findings records "
            f"{run.summary_total_findings} -- sign-off never proceeds against evidence it cannot reconcile "
            "against itself."
        )
    if null_count > 0:
        raise ReconciliationSignOffFindingsIncompleteError(
            f"Run '{run_id}' has {null_count} finding(s) with no disposition yet -- every finding must be "
            "reviewed before sign-off."
        )
    if requires_correction_count > 0:
        raise ReconciliationSignOffRequiresCorrectionError(
            f"Run '{run_id}' has {requires_correction_count} finding(s) dispositioned 'requires_correction' -- "
            "sign-off is never permitted while any finding remains in this state (OD-PR22-6)."
        )

    attestation_summary = {
        "run_id": str(run.id),
        "rule_version": run.rule_version,
        "snapshot_as_of": run.snapshot_as_of.isoformat(),
        "coverage_id": str(coverage.id),
        "legacy_coverage_start": run.legacy_coverage_start.isoformat(),
        "legacy_coverage_end": run.legacy_coverage_end.isoformat(),
        "live_system_start": run.live_system_start.isoformat(),
        "summary_total_findings": total_findings,
        "dispositions": {
            "confirmed_valid": counts.get("confirmed_valid", 0),
            "confirmed_duplicate": counts.get("confirmed_duplicate", 0),
            "accepted_unresolved": counts.get("accepted_unresolved", 0),
            "requires_correction": 0,
        },
        "unreviewed_findings": 0,
    }

    try:
        # A SAVEPOINT, not a bare flush: on the (structurally unreachable
        # under the run lock, but handled explicitly rather than assumed
        # away) IntegrityError branch below, this rolls back only the
        # failed INSERT -- the caller's own outer transaction (and the
        # run lock it holds) remains perfectly usable for the caller to
        # continue, or for the API layer to still commit whatever else
        # it already did in this same transaction. Construction/`add`/
        # `flush` all happen *inside* this block -- entering
        # `begin_nested()` can itself trigger an autoflush of any
        # already-pending ORM state, so `db.add(signoff)` must not occur
        # before the nested block starts, or the INSERT would not be
        # genuinely isolated inside the SAVEPOINT.
        async with db.begin_nested():
            signoff = LegacyReconciliationSignOff(
                run_id=run_id,
                signed_off_by_user_id=actor_id,
                attestation_summary=attestation_summary,
                run_version_at_signoff=run.version,
            )
            db.add(signoff)
            await db.flush()
    except IntegrityError as exc:
        raise ReconciliationSignOffAlreadyExistsError(
            f"Reconciliation run '{run_id}' has already been signed off -- a sign-off is never created twice or "
            "modified; GET the existing attestation instead."
        ) from exc
    await db.refresh(signoff)
    return signoff, attestation_summary
