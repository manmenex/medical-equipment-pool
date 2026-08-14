import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_session import EquipmentMasterDryRunPlan, EquipmentMasterDryRunPlanRow, ImportSession

# Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §14.2,
# §14.3, §14.4a). Every write here composes onto PR19A's existing
# transaction boundaries (§14.3: `persist_dry_run_plan` writes inside the
# same TX1 as `fenced_phase_success`'s own write; `confirm_plan` is its
# own single-statement conditional UPDATE, mirroring §7's CAS discipline)
# -- this module never calls `db.commit()`/`db.rollback()` itself.


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


async def confirm_plan(
    db: AsyncSession, *, plan_id: uuid.UUID, import_session_id: uuid.UUID, current_user_id: uuid.UUID
) -> EquipmentMasterDryRunPlan | None:
    """§14.4a's exact conditional-UPDATE confirmation contract: a single,
    atomic statement, `COALESCE`-guarded so a repeat confirm is idempotent
    (first confirmation is authoritative -- a second call by a different
    user succeeds but never overwrites the original confirmer), plus an
    `EXISTS` predicate requiring the owning session still be
    `dry_run_completed` (fix round 8, M4 -- catches a session that moved
    to `cancelled`/`dry_run_failed` after the plan was created). Zero rows
    matched (wrong plan id, wrong session, plan not `active`, or the
    session is no longer `dry_run_completed`) is reported to the caller as
    `None` -- the caller raises `409 IMPORT_DRY_RUN_PLAN_STALE`, never
    silently succeeding."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(EquipmentMasterDryRunPlan)
        .where(
            EquipmentMasterDryRunPlan.id == plan_id,
            EquipmentMasterDryRunPlan.import_session_id == import_session_id,
            EquipmentMasterDryRunPlan.status == "active",
            select(ImportSession.id)
            .where(ImportSession.id == EquipmentMasterDryRunPlan.import_session_id, ImportSession.status == "dry_run_completed")
            .exists(),
        )
        .values(
            confirmed_at=func.coalesce(EquipmentMasterDryRunPlan.confirmed_at, now),
            confirmed_by_user_id=func.coalesce(EquipmentMasterDryRunPlan.confirmed_by_user_id, current_user_id),
        )
        .returning(EquipmentMasterDryRunPlan)
    )
    return result.scalar_one_or_none()
