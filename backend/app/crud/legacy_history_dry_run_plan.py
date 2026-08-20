import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ImportDryRunPlanStaleError,
    ImportSessionNotFoundError,
)
from app.models.import_session import ImportSession
from app.models.legacy_history import LegacyHistoryDryRunPlan, LegacyHistoryDryRunPlanRow

# Roadmap PR21A (docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md
# §36). Mirrors `app.crud.import_dry_run_plan`'s proven shape (§14.2-§14.4a
# of the Equipment Master design) function-for-function, applied to PR21's
# own `LegacyHistoryDryRunPlan`/`Row` tables -- including PR94/PR100's own
# fix-round lessons already baked in (Session-then-Plan lock order in
# `confirm_plan`, below, to avoid a lock-order deadlock against a future
# PR21D adapter's own `persist_dry_run_plan`-equivalent, exactly as
# `import_dry_run_plan.confirm_plan`'s own docstring explains for Equipment
# Master). No adapter in this slice calls `insert_plan`/
# `bulk_insert_plan_rows` yet -- exercised directly by this slice's own
# tests, the same way PR21-Foundation's provider abstraction was built and
# tested before any concrete PR21 provider existed.


async def supersede_active_plan(db: AsyncSession, *, import_session_id: uuid.UUID) -> None:
    """Marks any existing `active` plan for this session `superseded`, in
    the same transaction as the new plan's own insert below -- never a
    separate, non-atomic step. A no-op if no `active` plan exists yet."""
    await db.execute(
        update(LegacyHistoryDryRunPlan)
        .where(
            LegacyHistoryDryRunPlan.import_session_id == import_session_id,
            LegacyHistoryDryRunPlan.status == "active",
        )
        .values(status="superseded")
    )


async def insert_plan(
    db: AsyncSession,
    *,
    import_session_id: uuid.UUID,
    import_source_id: uuid.UUID,
    migration_authority_id: uuid.UUID,
    source_checksum: str,
    accepted_validation_job_id: uuid.UUID,
    dry_run_job_id: uuid.UUID,
    ruleset_version: str,
    summary_total_rows: int,
    summary_issue_events: int,
    summary_receive_events: int,
    summary_warnings: int,
    summary_blocking_conflicts: int,
) -> LegacyHistoryDryRunPlan:
    """Inserts the new, `active`, **unconfirmed** (`confirmed_at IS
    NULL`) plan header. Caller (`supersede_active_plan` immediately
    before this, in the same transaction) is responsible for ensuring at
    most one `active` plan survives per session -- this function does not
    itself re-check that invariant (the partial unique index is the
    final backstop)."""
    plan = LegacyHistoryDryRunPlan(
        import_session_id=import_session_id,
        import_source_id=import_source_id,
        migration_authority_id=migration_authority_id,
        source_checksum=source_checksum,
        accepted_validation_job_id=accepted_validation_job_id,
        dry_run_job_id=dry_run_job_id,
        ruleset_version=ruleset_version,
        status="active",
        summary_total_rows=summary_total_rows,
        summary_issue_events=summary_issue_events,
        summary_receive_events=summary_receive_events,
        summary_warnings=summary_warnings,
        summary_blocking_conflicts=summary_blocking_conflicts,
    )
    db.add(plan)
    await db.flush()
    return plan


async def bulk_insert_plan_rows(db: AsyncSession, rows: list[LegacyHistoryDryRunPlanRow]) -> None:
    """One batched insert for every row of one plan -- never one `INSERT`
    per row."""
    if not rows:
        return
    db.add_all(rows)
    await db.flush()


async def get_current_plan(db: AsyncSession, *, import_session_id: uuid.UUID) -> LegacyHistoryDryRunPlan | None:
    """Resolves the session's single `active` plan. A
    `superseded`/`consumed`/`failed` plan is never returned by this
    lookup."""
    return (
        await db.execute(
            select(LegacyHistoryDryRunPlan).where(
                LegacyHistoryDryRunPlan.import_session_id == import_session_id,
                LegacyHistoryDryRunPlan.status == "active",
            )
        )
    ).scalar_one_or_none()


async def get_active_confirmed_for_session(
    db: AsyncSession, *, import_session_id: uuid.UUID
) -> LegacyHistoryDryRunPlan | None:
    """Roadmap PR21D2. Mirrors `import_dry_run_plan.
    get_active_confirmed_for_session`'s exact resolution query and
    rationale: `status = 'active' AND confirmed_at IS NOT NULL`,
    deliberately distinct from `get_current_plan` above (which returns a
    merely-`active`, possibly-unconfirmed plan). The partial unique index
    on `(import_session_id) WHERE status = 'active'` guarantees at most
    one row -- no "pick the newest" heuristic."""
    return (
        await db.execute(
            select(LegacyHistoryDryRunPlan).where(
                LegacyHistoryDryRunPlan.import_session_id == import_session_id,
                LegacyHistoryDryRunPlan.status == "active",
                LegacyHistoryDryRunPlan.confirmed_at.isnot(None),
            )
        )
    ).scalar_one_or_none()


async def mark_plan_consumed(db: AsyncSession, *, plan_id: uuid.UUID) -> None:
    """Roadmap PR21D2. Called by the adapter's own `on_execution_success`,
    inside the framework's TX1, only after the Job->Session completion
    fence has already succeeded -- mirrors `import_dry_run_plan.
    mark_plan_consumed` exactly."""
    await db.execute(
        update(LegacyHistoryDryRunPlan).where(LegacyHistoryDryRunPlan.id == plan_id).values(status="consumed")
    )


async def mark_plan_failed(db: AsyncSession, *, plan_id: uuid.UUID) -> None:
    """Roadmap PR21D2. Called by the adapter's own `on_execution_failure`,
    on the framework's TX2 session, immediately before that transaction's
    own commit -- mirrors `import_dry_run_plan.mark_plan_failed`
    exactly."""
    await db.execute(
        update(LegacyHistoryDryRunPlan).where(LegacyHistoryDryRunPlan.id == plan_id).values(status="failed")
    )


async def mark_active_plan_failed_for_session(db: AsyncSession, *, import_session_id: uuid.UUID) -> None:
    """Roadmap PR21D2. Called by the adapter's own `on_execution_recovery`
    -- reconciles a hard worker crash during `execute()` that never
    raised anything at all. Mirrors `import_dry_run_plan.
    mark_active_plan_failed_for_session` exactly: no `confirmed_at`
    predicate needed, since reaching `executing` already required a
    confirmed plan."""
    await db.execute(
        update(LegacyHistoryDryRunPlan)
        .where(
            LegacyHistoryDryRunPlan.import_session_id == import_session_id,
            LegacyHistoryDryRunPlan.status == "active",
        )
        .values(status="failed")
    )


async def list_all_plan_rows(db: AsyncSession, *, plan_id: uuid.UUID) -> list[LegacyHistoryDryRunPlanRow]:
    """Roadmap PR21D2. Unpaginated -- `execute()`'s own internal
    consumption of one confirmed plan's rows, never an API response
    (contrast `list_plan_rows` above, the cursor-paginated read path).
    Ordered by `(event_type, source_row_number, id)` -- `source_row_number`
    alone is not globally unique across a combined plan (Issue and
    Receive sheets independently renumber from 1, §23 of the PR21D2 task),
    so `event_type` is included as the primary sort key ahead of it, with
    `id` as a final deterministic tiebreaker. The final database outcome
    of `execute()` must never depend on accidental SQL row order."""
    return list(
        (
            await db.execute(
                select(LegacyHistoryDryRunPlanRow)
                .where(LegacyHistoryDryRunPlanRow.dry_run_plan_id == plan_id)
                .order_by(
                    LegacyHistoryDryRunPlanRow.event_type.asc(),
                    LegacyHistoryDryRunPlanRow.source_row_number.asc(),
                    LegacyHistoryDryRunPlanRow.id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )


async def get_plan_by_id(
    db: AsyncSession, *, plan_id: uuid.UUID, import_session_id: uuid.UUID
) -> LegacyHistoryDryRunPlan | None:
    """An ownership-checked lookup -- a plan id that exists but belongs
    to a different session is never returned."""
    return (
        await db.execute(
            select(LegacyHistoryDryRunPlan).where(
                LegacyHistoryDryRunPlan.id == plan_id,
                LegacyHistoryDryRunPlan.import_session_id == import_session_id,
            )
        )
    ).scalar_one_or_none()


async def list_plan_rows(
    db: AsyncSession, *, plan_id: uuid.UUID, limit: int, cursor_n: int | None, cursor_id: uuid.UUID | None
) -> tuple[list[LegacyHistoryDryRunPlanRow], int]:
    """Cursor pagination ordered by `source_row_number`, then `id` --
    mirrors `import_dry_run_plan.list_plan_rows`'s identical
    limit-plus-one, integer-cursor shape."""
    stmt = select(LegacyHistoryDryRunPlanRow).where(LegacyHistoryDryRunPlanRow.dry_run_plan_id == plan_id)
    if cursor_n is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(
                LegacyHistoryDryRunPlanRow.source_row_number > cursor_n,
                (LegacyHistoryDryRunPlanRow.source_row_number == cursor_n)
                & (LegacyHistoryDryRunPlanRow.id > cursor_id),
            )
        )
    stmt = stmt.order_by(LegacyHistoryDryRunPlanRow.source_row_number.asc(), LegacyHistoryDryRunPlanRow.id.asc())
    stmt = stmt.limit(limit + 1)
    rows = list((await db.execute(stmt)).scalars().all())

    total = (
        await db.execute(
            select(func.count())
            .select_from(LegacyHistoryDryRunPlanRow)
            .where(LegacyHistoryDryRunPlanRow.dry_run_plan_id == plan_id)
        )
    ).scalar_one()
    return rows, total


@dataclass
class ConfirmationResult:
    """Mirrors `import_dry_run_plan.ConfirmationResult` -- lets the
    caller tell a genuine first confirmation apart from an idempotent
    replay of an already-confirmed plan."""

    plan: LegacyHistoryDryRunPlan
    newly_confirmed: bool


async def confirm_plan(
    db: AsyncSession, *, plan_id: uuid.UUID, import_session_id: uuid.UUID, current_user_id: uuid.UUID
) -> ConfirmationResult:
    """Mirrors `import_dry_run_plan.confirm_plan`'s exact lock-order and
    fencing discipline (PR94-H1/H2's own fix-round lessons, already
    reused here rather than re-derived): `ImportSession` locked first,
    then the plan row, both ownership/state re-verified *after* the lock
    is held. A `plan_id` that does not exist, or belongs to a different
    session, or is no longer `active`, or whose owning session is no
    longer `dry_run_completed`, all collapse into the same
    `ImportDryRunPlanStaleError` -- never a distinguishing 404 that would
    leak whether a plan id belongs to another session (the same
    information-boundary discipline `import_dry_run_plan.confirm_plan`'s
    own docstring documents)."""
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
            "dry-run has moved it on. Re-fetch the current plan before confirming again."
        )

    plan_stmt = select(LegacyHistoryDryRunPlan).where(
        LegacyHistoryDryRunPlan.id == plan_id, LegacyHistoryDryRunPlan.import_session_id == import_session_id
    )
    if db.get_bind().dialect.name == "postgresql":
        plan_stmt = plan_stmt.with_for_update()
    plan_row = (await db.execute(plan_stmt)).scalar_one_or_none()
    if plan_row is None:
        raise ImportDryRunPlanStaleError(
            f"Dry-run plan '{plan_id}' is not confirmable: it does not exist, or does not belong to import "
            f"session '{import_session_id}'. Re-fetch the current plan before confirming."
        )
    if plan_row.status != "active":
        raise ImportDryRunPlanStaleError(
            f"Dry-run plan '{plan_id}' is no longer confirmable (status='{plan_row.status}'). "
            "Re-fetch the current plan before confirming again."
        )

    if plan_row.confirmed_at is not None:
        return ConfirmationResult(plan=plan_row, newly_confirmed=False)

    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(LegacyHistoryDryRunPlan)
        .where(LegacyHistoryDryRunPlan.id == plan_id, LegacyHistoryDryRunPlan.confirmed_at.is_(None))
        .values(confirmed_at=now, confirmed_by_user_id=current_user_id)
        .returning(LegacyHistoryDryRunPlan)
    )
    confirmed_row = result.scalar_one_or_none()
    if confirmed_row is None:
        # Unreachable under the row lock held continuously since above --
        # no other transaction could have confirmed this plan in between.
        # Treated as an idempotent replay rather than raised.
        refreshed = await db.get(LegacyHistoryDryRunPlan, plan_id)
        return ConfirmationResult(plan=refreshed, newly_confirmed=False)
    return ConfirmationResult(plan=confirmed_row, newly_confirmed=True)
