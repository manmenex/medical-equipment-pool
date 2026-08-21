"""Roadmap PR21E0 -- Legacy Import Operator API Surface. Closes gap B
(§12-§20 of the task): a PR21-specific, statically typed HTTP surface for
inspecting and confirming a `LegacyHistoryDryRunPlan`
(`app.models.legacy_history`) -- deliberately a SEPARATE route family from
the existing PR20 `GET/POST .../dry-run-plan[...]` routes in
`app.api.v1.import_sessions`, which remain byte/field/OpenAPI-unchanged by
this slice (see `test_pr21e0_pr20_regression.py`). `POST .../execute` is
unchanged -- this router only makes operator dry-run review/confirm
reachable over HTTP; PR21D2 already implemented execution itself via the
generic adapter flow (`LegacyTransactionHistoryAdapter.execute`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, require_roles
from app.core.audit import AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED, AUDIT_ENTITY_IMPORT_SESSION, record_audit_event
from app.core.exceptions import ImportDryRunPlanNotFoundError, ImportSessionNotFoundError
from app.crud import import_session as import_session_crud
from app.crud import legacy_history_dry_run_plan as legacy_history_dry_run_plan_crud
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.legacy_history_import import (
    LegacyHistoryDryRunPlanConfirmOut,
    LegacyHistoryDryRunPlanOut,
    LegacyHistoryDryRunPlanRowOut,
    LegacyHistoryDryRunPlanRowValuesOut,
    LegacyHistoryDryRunPlanSourceRefOut,
    LegacyHistoryDryRunPlanSummaryOut,
)
from app.services.import_plan_provider import PlanProviderNotRegisteredError, get_plan_provider
# Importing this module (a) gives us its own `DATASET_TYPE` constant and
# (b) guarantees `LegacyHistoryDryRunPlanProvider` is registered in
# `app.services.import_plan_provider`'s registry before any route below
# ever calls `get_plan_provider` -- the same "import registers" pattern
# `app.services.import_adapters.legacy_history.combined` already relies on
# for the adapter registry.
from app.services.import_plan_providers.legacy_history import DATASET_TYPE

router = APIRouter(prefix="/import-sessions", tags=["legacy-history-import"])


async def _get_legacy_history_session_or_404(db: AsyncSession, session_id: uuid.UUID):
    """§13/§18 of the task: a session that does not exist at all, and a
    session that exists but is not `dataset_type == 'legacy_transaction_
    history'`, collapse into the identical `404 IMPORT_SESSION_NOT_FOUND`
    -- this route family is dataset-scoped by construction, so a caller
    can never learn from this endpoint alone whether a given `session_id`
    is a real Equipment Master session. PR20's own `GET .../dry-run-plan`
    route is unaffected by this: it never checks `dataset_type` at all,
    since only the PR21 adapter ever writes to `LegacyHistoryDryRunPlan`
    in the first place (an Equipment Master session structurally has
    none)."""
    session = await import_session_crud.get_by_id(db, session_id)
    if session is None or session.dataset_type != DATASET_TYPE:
        raise ImportSessionNotFoundError(f"Import session '{session_id}' not found.")
    return session


def _summary_out(plan) -> LegacyHistoryDryRunPlanSummaryOut:
    return LegacyHistoryDryRunPlanSummaryOut(
        total_rows=plan.summary_total_rows,
        issue_events=plan.summary_issue_events,
        receive_events=plan.summary_receive_events,
        warnings=plan.summary_warnings,
        blocking_conflicts=plan.summary_blocking_conflicts,
    )


@router.get("/{session_id}/legacy-history/dry-run-plan", response_model=LegacyHistoryDryRunPlanOut)
async def get_legacy_history_dry_run_plan(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """§13 of the task. Administrator-only. Resolves the session's
    current `active` plan (never a client-supplied plan id -- there is no
    "recompute" endpoint, mirroring PR20's own `GET .../dry-run-plan`
    contract) and returns its persisted identity/summary. Row content is
    served by the separate `.../rows` endpoint below, never embedded
    here (a deliberate divergence from PR20's `DryRunPlanOut` shape --
    see this module's own docstring and the PR description). `404
    IMPORT_DRY_RUN_PLAN_NOT_FOUND` if the session has never had a
    successful PR21 dry-run."""
    session = await _get_legacy_history_session_or_404(db, session_id)
    plan = await legacy_history_dry_run_plan_crud.get_current_plan(db, import_session_id=session.id)
    if plan is None:
        raise ImportDryRunPlanNotFoundError(f"Import session '{session_id}' has no persisted dry-run plan.")
    return LegacyHistoryDryRunPlanOut(
        id=plan.id,
        import_session_id=plan.import_session_id,
        import_source_id=plan.import_source_id,
        migration_authority_id=plan.migration_authority_id,
        status=plan.status,
        is_current=plan.status == "active",
        created_at=plan.created_at,
        confirmed_at=plan.confirmed_at,
        confirmed_by_user_id=plan.confirmed_by_user_id,
        summary=_summary_out(plan),
    )


def _row_out(row) -> LegacyHistoryDryRunPlanRowOut:
    values = None
    if row.normalized_values is not None:
        nv = row.normalized_values
        values = LegacyHistoryDryRunPlanRowValuesOut(
            legacy_order_reference=nv.get("legacy_order_reference"),
            equipment_id=nv["equipment_id"],
            occurred_at=nv["occurred_at"],
            legacy_ward_text=nv.get("legacy_ward_text"),
            resolved_ward_id=nv.get("resolved_ward_id"),
            legacy_bme_name=nv.get("legacy_bme_name"),
            header_source_ref=LegacyHistoryDryRunPlanSourceRefOut(**nv["header_source_ref"]),
            line_source_ref=LegacyHistoryDryRunPlanSourceRefOut(**nv["line_source_ref"]),
        )
    return LegacyHistoryDryRunPlanRowOut(
        id=row.id,
        source_row_number=row.source_row_number,
        event_type=row.event_type,
        legacy_source_row_key=row.legacy_source_row_key,
        values=values,
        warnings=row.warnings,
    )


@router.get(
    "/{session_id}/legacy-history/dry-run-plan/{plan_id}/rows",
    response_model=Page[LegacyHistoryDryRunPlanRowOut],
)
async def list_legacy_history_dry_run_plan_rows(
    session_id: uuid.UUID,
    plan_id: uuid.UUID,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """§14 of the task. Delegates entirely to
    `LegacyHistoryDryRunPlanProvider.list_plan_rows` (PR100-H2's own
    proven contract) rather than re-implementing ownership/cursor checks
    here: a `plan_id` that exists but does not belong to `session_id` is
    rejected as `ImportDryRunPlanNotFoundError`, and a `cursor` obtained
    while paging a *different* plan is rejected as `InvalidInputError`
    (cross-plan cursor rejection) -- both already proven by that
    provider's own PR21-Foundation tests, exercised over HTTP for the
    first time by this route."""
    session = await _get_legacy_history_session_or_404(db, session_id)
    provider = get_plan_provider(DATASET_TYPE)
    if provider is None:
        # Unreachable in production -- this module's own import above
        # registers it. Fail closed rather than silently listing nothing.
        raise PlanProviderNotRegisteredError(f"No DryRunPlanProvider registered for dataset_type '{DATASET_TYPE}'.")
    page = await provider.list_plan_rows(
        db, import_session_id=session.id, plan_id=plan_id, limit=limit, cursor=cursor
    )
    return Page(items=[_row_out(row) for row in page.rows], next_cursor=page.next_cursor, total=page.total)


@router.post(
    "/{session_id}/legacy-history/dry-run-plan/{plan_id}/confirm",
    response_model=LegacyHistoryDryRunPlanConfirmOut,
)
async def confirm_legacy_history_dry_run_plan(
    session_id: uuid.UUID,
    plan_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """§17 of the task. Delegates directly to
    `legacy_history_dry_run_plan_crud.confirm_plan` -- the exact same
    lock-order/stale-collapsing/idempotency-preserving implementation
    already proven by PR21D1/D2's own tests, exercised over HTTP for the
    first time by this route. Reuses the EXISTING
    `AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED`/
    `AUDIT_ENTITY_IMPORT_SESSION` constants (`entity_id` is always the
    owning `ImportSession.id`, the aggregate root, regardless of which
    adapter's plan) -- mirrors PR20's own `confirm_dry_run_plan` audit
    discipline exactly, including writing the audit event only when
    `result.newly_confirmed`, in the same transaction as the confirm
    state change (both committed together below)."""
    session = await _get_legacy_history_session_or_404(db, session_id)
    result = await legacy_history_dry_run_plan_crud.confirm_plan(
        db, plan_id=plan_id, import_session_id=session.id, current_user_id=actor.id
    )
    if result.newly_confirmed:
        await record_audit_event(
            db,
            actor_user_id=actor.id,
            action=AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED,
            entity_type=AUDIT_ENTITY_IMPORT_SESSION,
            entity_id=session.id,
            after={
                "dry_run_plan_id": str(result.plan.id),
                "confirmed_at": result.plan.confirmed_at.isoformat() if result.plan.confirmed_at else None,
            },
            request=request,
        )
    await db.commit()
    plan = result.plan
    return LegacyHistoryDryRunPlanConfirmOut(
        id=plan.id,
        import_session_id=plan.import_session_id,
        status=plan.status,
        confirmed_at=plan.confirmed_at,
        confirmed_by_user_id=plan.confirmed_by_user_id,
        summary=_summary_out(plan),
    )
