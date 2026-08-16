import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ImportDryRunPlanStaleError,
    ImportSessionNotFoundError,
)
from app.models.import_session import EquipmentMasterDryRunPlan, EquipmentMasterDryRunPlanRow, ImportSession

# Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §14.2,
# §14.3, §14.4a). Every write here composes onto PR19A's existing
# transaction boundaries (§14.3: `persist_dry_run_plan` writes inside the
# same TX1 as `fenced_phase_success`'s own write). Fix round 2
# (PR94-H1/H2): `confirm_plan` now locks `ImportSession` then
# `EquipmentMasterDryRunPlan`, in that order, before its conditional
# `UPDATE` -- the same Session-then-Plan order `persist_dry_run_plan`
# (`app.services.import_adapters.equipment_master`) now also locks in, so
# the two transaction shapes can never deadlock against each other -- this
# module never calls `db.commit()`/`db.rollback()` itself.


async def supersede_active_plan(db: AsyncSession, *, import_session_id: uuid.UUID) -> None:
    """§11/§14.3: marks any existing `active` plan for this session
    `superseded`, in the same transaction as the new plan's own insert
    below -- never a separate, non-atomic step. A no-op if no `active`
    plan exists yet (a session's first successful dry-run)."""
    await db.execute(
        update(EquipmentMasterDryRunPlan)
        .where(
            EquipmentMasterDryRunPlan.import_session_id == import_session_id,
            EquipmentMasterDryRunPlan.status == "active",
        )
        .values(status="superseded")
    )


async def insert_plan(
    db: AsyncSession,
    *,
    import_session_id: uuid.UUID,
    import_source_id: uuid.UUID,
    source_checksum: str,
    accepted_validation_job_id: uuid.UUID,
    dry_run_job_id: uuid.UUID,
    ruleset_version: str,
    summary_total_rows: int,
    summary_creates: int,
    summary_updates: int,
    summary_skips: int,
    summary_warnings: int,
    summary_blocking_conflicts: int,
) -> EquipmentMasterDryRunPlan:
    """§14.2/§14.3: inserts the new, `active`, **unconfirmed**
    (`confirmed_at IS NULL`, §14.4a) plan header. Caller
    (`supersede_active_plan` immediately before this, in the same
    transaction) is responsible for ensuring at most one `active` plan
    survives per session -- this function does not itself re-check that
    invariant (the partial unique index, §14.2, is the final backstop)."""
    plan = EquipmentMasterDryRunPlan(
        import_session_id=import_session_id,
        import_source_id=import_source_id,
        source_checksum=source_checksum,
        accepted_validation_job_id=accepted_validation_job_id,
        dry_run_job_id=dry_run_job_id,
        ruleset_version=ruleset_version,
        status="active",
        summary_total_rows=summary_total_rows,
        summary_creates=summary_creates,
        summary_updates=summary_updates,
        summary_skips=summary_skips,
        summary_warnings=summary_warnings,
        summary_blocking_conflicts=summary_blocking_conflicts,
    )
    db.add(plan)
    await db.flush()
    return plan


async def bulk_insert_plan_rows(db: AsyncSession, rows: list[EquipmentMasterDryRunPlanRow]) -> None:
    """§14.2/§16: one batched insert for every row of one plan -- never one
    `INSERT` per row (mirrors PR20C's own no-N+1 discipline, §19)."""
    if not rows:
        return
    db.add_all(rows)
    await db.flush()


async def get_current_plan(db: AsyncSession, *, import_session_id: uuid.UUID) -> EquipmentMasterDryRunPlan | None:
    """§14.4/§14.6: resolves the session's single `active` plan -- the
    same structural query `execute()` (PR20E) and `GET .../dry-run-plan`
    (§14.6) both depend on. A `superseded`/`consumed`/`failed` plan is
    never returned by this lookup."""
    return (
        await db.execute(
            select(EquipmentMasterDryRunPlan).where(
                EquipmentMasterDryRunPlan.import_session_id == import_session_id,
                EquipmentMasterDryRunPlan.status == "active",
            )
        )
    ).scalar_one_or_none()


async def get_plan_by_id(
    db: AsyncSession, *, plan_id: uuid.UUID, import_session_id: uuid.UUID
) -> EquipmentMasterDryRunPlan | None:
    """§14.4a/§21: an ownership-checked lookup -- a plan id that exists but
    belongs to a different session is never returned (never leaked across
    sessions), matching `list_validation_errors`'s identical
    ownership-check discipline for `attempt_id`."""
    return (
        await db.execute(
            select(EquipmentMasterDryRunPlan).where(
                EquipmentMasterDryRunPlan.id == plan_id,
                EquipmentMasterDryRunPlan.import_session_id == import_session_id,
            )
        )
    ).scalar_one_or_none()


MAX_ROW_NUMBER_SORT_VALUE = 2**31 - 1


async def list_plan_rows(
    db: AsyncSession, *, plan_id: uuid.UUID, limit: int, cursor_n: int | None, cursor_id: uuid.UUID | None
) -> tuple[list[EquipmentMasterDryRunPlanRow], int]:
    """§14.6/§21/§31: cursor pagination ordered by `source_row_number`,
    then `id` -- mirrors `app.crud.import_job.list_findings`'s identical
    limit-plus-one, integer-cursor shape."""
    stmt = select(EquipmentMasterDryRunPlanRow).where(EquipmentMasterDryRunPlanRow.dry_run_plan_id == plan_id)
    if cursor_n is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(
                EquipmentMasterDryRunPlanRow.source_row_number > cursor_n,
                (EquipmentMasterDryRunPlanRow.source_row_number == cursor_n)
                & (EquipmentMasterDryRunPlanRow.id > cursor_id),
            )
        )
    stmt = stmt.order_by(EquipmentMasterDryRunPlanRow.source_row_number.asc(), EquipmentMasterDryRunPlanRow.id.asc())
    stmt = stmt.limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    total = (
        await db.execute(
            select(func.count())
            .select_from(EquipmentMasterDryRunPlanRow)
            .where(EquipmentMasterDryRunPlanRow.dry_run_plan_id == plan_id)
        )
    ).scalar_one()
    return rows, total


@dataclass
class ConfirmationResult:
    """Fix round 2 (PR94-H2): lets the caller (the API endpoint) tell a
    genuine first confirmation apart from an idempotent replay of an
    already-confirmed plan, so the `CONFIRMED` audit event -- and only
    that event -- can be gated on `newly_confirmed`."""

    plan: EquipmentMasterDryRunPlan
    newly_confirmed: bool


async def confirm_plan(
    db: AsyncSession, *, plan_id: uuid.UUID, import_session_id: uuid.UUID, current_user_id: uuid.UUID
) -> ConfirmationResult:
    """Fix round 2 (PR94-H1/H2): replaces the prior unlocked-`EXISTS`
    conditional `UPDATE` with an explicit, ordered lock sequence so
    confirmation genuinely serializes against `cancel_session` and
    dry-run (re)admission (`_claim_session_and_insert_job`) instead of
    merely racing an unlocked read against their writes:

    1. `SELECT ... FOR UPDATE` the `ImportSession` row first (never the
       plan first -- `persist_dry_run_plan` locks in this same
       Session-then-Plan order for exactly this reason, avoiding a
       lock-order deadlock between the two transaction shapes).
       Re-verify `status == 'dry_run_completed'` *after* the lock is
       held, not before -- a plain pre-lock read could still observe a
       value that a concurrent, uncommitted cancellation/admission is
       about to change.
    2. `SELECT ... FOR UPDATE` the `EquipmentMasterDryRunPlan` row,
       ownership-checked, and verify it is still `active`.
    3. If already confirmed, this call is an idempotent replay --
       return the persisted row as-is (`newly_confirmed=False`), never
       re-attributing `confirmed_by_user_id` to a later caller.
    4. Otherwise perform the first-confirm transition via the exact
       conditional `UPDATE ... WHERE confirmed_at IS NULL RETURNING ...`
       shape -- redundant with the row lock already held (no other
       transaction could have raced this write in between), but kept as
       explicit, self-documenting defense-in-depth matching this
       codebase's existing CAS discipline.

    Raises `ImportSessionNotFoundError`/`ImportDryRunPlanStaleError`
    directly (mirroring `app.crud.import_session.cancel_session`'s own
    raise-from-the-CRUD-layer convention) instead of returning `None` for
    the API layer to reinterpret. Fix round 4 (PR20 design §14.4a, fix
    round 8/M4): the owning session no longer being `dry_run_completed`
    (a concurrent cancel or a new dry-run legitimately won the race) is
    reported as `ImportDryRunPlanStaleError`, the SAME unified code as
    every other plan-invalidating condition. Fix round 6: so is a
    `plan_id` that doesn't exist at all, or that exists but belongs to a
    *different* session -- the design doc's own zero-rows-matched list is
    explicit that "either it was already superseded... belongs to a
    different session, does not exist, or... the owning session is no
    longer `dry_run_completed`... this design does not attempt to
    distinguish these sub-cases with different error codes." Collapsing
    missing and foreign-session plan ids into the same stale response
    also closes an information-boundary leak this endpoint would
    otherwise have: a caller could never learn "this plan id belongs to a
    different session" (a 404) from "this plan id never existed" (also a
    404, before this fix -- so no leak there) versus "this plan is merely
    stale" (a 409) -- three distinguishable outcomes from one probe.
    `ImportDryRunPlanNotFoundError`/`404` remains exactly as-is for
    `get_plan_by_id`'s own read-path callers (`GET .../dry-run-plan`) --
    resource-lookup semantics are unaffected; only this write/confirm
    path's zero-rows-matched handling changes. `ImportSessionInvalidStateError`
    remains reserved for endpoints whose semantic operation is not
    "validate/confirm/use this specific persisted DryRunPlan" (e.g.
    `cancel_session`'s own CAS rejection) -- never for this sub-case."""
    session_row = (
        await db.execute(
            select(ImportSession.id, ImportSession.status).where(ImportSession.id == import_session_id).with_for_update()
            if db.get_bind().dialect.name == "postgresql"
            else select(ImportSession.id, ImportSession.status).where(ImportSession.id == import_session_id)
        )
    ).first()
    if session_row is None:
        raise ImportSessionNotFoundError(f"Import session '{import_session_id}' not found.")
    if session_row.status != "dry_run_completed":
        raise ImportDryRunPlanStaleError(
            f"Dry-run plan '{plan_id}' is no longer confirmable: import session '{import_session_id}' is not "
            f"'dry_run_completed' (currently '{session_row.status}') -- a concurrent cancellation or new "
            "dry-run has moved it on. Re-fetch the current plan (GET .../dry-run-plan) before confirming again."
        )

    plan_stmt = select(EquipmentMasterDryRunPlan).where(
        EquipmentMasterDryRunPlan.id == plan_id, EquipmentMasterDryRunPlan.import_session_id == import_session_id
    )
    if db.get_bind().dialect.name == "postgresql":
        plan_stmt = plan_stmt.with_for_update()
    plan_row = (await db.execute(plan_stmt)).scalar_one_or_none()
    if plan_row is None:
        # Fix round 6: the SAME unified stale-plan response as every other
        # zero-rows-matched condition -- never IMPORT_DRY_RUN_PLAN_NOT_FOUND
        # here, which would let a caller distinguish "wrong id" from
        # "foreign session's id" from "genuinely stale", leaking whether a
        # plan id belongs to another session.
        raise ImportDryRunPlanStaleError(
            f"Dry-run plan '{plan_id}' is not confirmable: it does not exist, or does not belong to import "
            f"session '{import_session_id}'. Re-fetch the current plan (GET .../dry-run-plan) before confirming."
        )
    if plan_row.status != "active":
        raise ImportDryRunPlanStaleError(
            f"Dry-run plan '{plan_id}' is no longer confirmable (status='{plan_row.status}'). "
            "Re-fetch the current plan (GET .../dry-run-plan) before confirming again."
        )

    if plan_row.confirmed_at is not None:
        return ConfirmationResult(plan=plan_row, newly_confirmed=False)

    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(EquipmentMasterDryRunPlan)
        .where(EquipmentMasterDryRunPlan.id == plan_id, EquipmentMasterDryRunPlan.confirmed_at.is_(None))
        .values(confirmed_at=now, confirmed_by_user_id=current_user_id)
        .returning(EquipmentMasterDryRunPlan)
    )
    confirmed_row = result.scalar_one_or_none()
    if confirmed_row is None:
        # Unreachable under the row lock held continuously since step 2
        # above -- no other transaction could have confirmed this plan in
        # between. Treated as an idempotent replay rather than raised, to
        # never surface an internal-invariant failure as a user-facing
        # error for what is, from the caller's perspective, a successful
        # confirm.
        refreshed = await db.get(EquipmentMasterDryRunPlan, plan_id)
        return ConfirmationResult(plan=refreshed, newly_confirmed=False)
    return ConfirmationResult(plan=confirmed_row, newly_confirmed=True)
