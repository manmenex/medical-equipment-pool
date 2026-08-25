"""Roadmap PR23B -- Cutover Readiness Evidence Foundation.

Read surfaces (list/detail) are available to every authenticated role
(`VIEW_AND_REPORT_ROLES`) -- reviewing is not itself a mutation. Both
mutation endpoints (`POST /cutover-readiness-runs`, `POST .../complete`)
are Administrator-only, mirroring PR22D/E's identical role gate for
every reconciliation mutation.

One route family (`/cutover-readiness-runs`), matching this
repository's existing per-resource prefix convention.

Deliberately absent from this module (later PR23 slices' own scope):
any readiness-gate evaluation (Gates A-G), any BLOCKER/WARNING/INFO
classification, any Go/No-Go decision/sign-off endpoint, and any
frontend.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, VIEW_AND_REPORT_ROLES, require_roles
from app.core.audit import (
    AUDIT_ACTION_CUTOVER_READINESS_RUN_COMPLETED,
    AUDIT_ACTION_CUTOVER_READINESS_RUN_CREATED,
    AUDIT_ENTITY_CUTOVER_READINESS_RUN,
    record_audit_event,
)
from app.core.exceptions import CutoverReadinessRunNotFoundError, InvalidInputError
from app.crud import cutover_readiness as cutover_readiness_crud
from app.crud.cutover_readiness import CompletionEvidence
from app.db.session import get_db
from app.models.cutover_readiness import CutoverReadinessRun
from app.schemas.common import Page
from app.schemas.cutover_readiness import RunCompleteRequest, RunCreateRequest, RunDetail, RunListItem
from app.utils.pagination import decode_cursor, encode_cursor

router = APIRouter(prefix="/cutover-readiness-runs", tags=["cutover-readiness"])


def _decode_pagination_cursor(cursor: str | None) -> tuple:
    if not cursor:
        return None, None
    cursor_dt, cursor_id_raw = decode_cursor(cursor)
    try:
        cursor_id = uuid.UUID(cursor_id_raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidInputError("Invalid or malformed pagination cursor.") from exc
    return cursor_dt, cursor_id


def _run_fields(run: CutoverReadinessRun) -> dict:
    return {
        "id": str(run.id),
        "status": run.status,
        "version": run.version,
        "created_by_user_id": str(run.created_by_user_id),
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "completed_by_user_id": str(run.completed_by_user_id) if run.completed_by_user_id else None,
        "application_baseline_sha": run.application_baseline_sha,
        "database_migration_head": run.database_migration_head,
        "source_of_truth_strategy": run.source_of_truth_strategy,
        "cutover_instant": run.cutover_instant,
        "freeze_window_reference": run.freeze_window_reference,
        "supersedes_run_id": str(run.supersedes_run_id) if run.supersedes_run_id else None,
    }


def _run_detail_fields(run: CutoverReadinessRun) -> dict:
    return {
        **_run_fields(run),
        "equipment_master_import_source_id": (
            str(run.equipment_master_import_source_id) if run.equipment_master_import_source_id else None
        ),
        "legacy_migration_authority_id": (
            str(run.legacy_migration_authority_id) if run.legacy_migration_authority_id else None
        ),
        "legacy_coverage_id": str(run.legacy_coverage_id) if run.legacy_coverage_id else None,
        "reconciliation_run_id": str(run.reconciliation_run_id) if run.reconciliation_run_id else None,
        "reconciliation_signoff_id": (
            str(run.reconciliation_signoff_id) if run.reconciliation_signoff_id else None
        ),
        "current_state_verified_at": run.current_state_verified_at,
        "current_state_verified_by_user_id": (
            str(run.current_state_verified_by_user_id) if run.current_state_verified_by_user_id else None
        ),
        "current_state_verification_scope_count": run.current_state_verification_scope_count,
        "current_state_verification_reference": run.current_state_verification_reference,
        "pilot_ward_id": str(run.pilot_ward_id) if run.pilot_ward_id else None,
        "operational_approver_reference": run.operational_approver_reference,
    }


async def _get_run_or_404(db: AsyncSession, run_id: uuid.UUID) -> CutoverReadinessRun:
    run = await cutover_readiness_crud.get_readiness_run(db, run_id=run_id)
    if run is None:
        raise CutoverReadinessRunNotFoundError(f"Cutover readiness run '{run_id}' not found.")
    return run


@router.get("", response_model=Page[RunListItem])
async def list_cutover_readiness_runs(
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    cursor_dt, cursor_id = _decode_pagination_cursor(cursor)
    rows, total = await cutover_readiness_crud.list_readiness_runs(
        db, limit=limit, cursor_dt=cursor_dt, cursor_id=cursor_id
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))

    items = [RunListItem(**_run_fields(r)) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=total)


@router.get("/{run_id}", response_model=RunDetail)
async def get_cutover_readiness_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    run = await _get_run_or_404(db, run_id)
    return RunDetail(**_run_detail_fields(run))


@router.post("", response_model=RunDetail, status_code=201)
async def create_cutover_readiness_run(
    payload: RunCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    run = await cutover_readiness_crud.create_readiness_run(
        db,
        actor_id=actor.id,
        application_baseline_sha=payload.application_baseline_sha,
        cutover_instant=payload.cutover_instant,
        source_of_truth_strategy=payload.source_of_truth_strategy,
        freeze_window_reference=payload.freeze_window_reference,
        supersedes_run_id=uuid.UUID(payload.supersedes_run_id) if payload.supersedes_run_id else None,
    )
    await record_audit_event(
        db,
        actor_user_id=actor.id,
        action=AUDIT_ACTION_CUTOVER_READINESS_RUN_CREATED,
        entity_type=AUDIT_ENTITY_CUTOVER_READINESS_RUN,
        entity_id=run.id,
        after={
            "run_id": str(run.id),
            "application_baseline_sha": run.application_baseline_sha,
            "database_migration_head": run.database_migration_head,
            "cutover_instant": run.cutover_instant.isoformat(),
            "source_of_truth_strategy": run.source_of_truth_strategy,
            "supersedes_run_id": str(run.supersedes_run_id) if run.supersedes_run_id else None,
        },
        request=request,
    )
    # One atomic transaction: the run INSERT above (not yet committed,
    # still flushed only) and this audit write land together here, or --
    # if anything above raised -- neither lands at all.
    await db.commit()
    return RunDetail(**_run_detail_fields(run))


@router.post("/{run_id}/complete", response_model=RunDetail)
async def complete_cutover_readiness_run(
    run_id: uuid.UUID,
    payload: RunCompleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Captures this run's immutable evidence snapshot. Completion means
    only that the snapshot was successfully captured -- it is never a
    Go/No-Go, readiness, or production-ready judgment (see
    `app.models.cutover_readiness`'s own module docstring)."""
    evidence = CompletionEvidence(
        equipment_master_import_source_id=uuid.UUID(payload.equipment_master_import_source_id),
        legacy_migration_authority_id=uuid.UUID(payload.legacy_migration_authority_id),
        legacy_coverage_id=uuid.UUID(payload.legacy_coverage_id),
        reconciliation_run_id=uuid.UUID(payload.reconciliation_run_id),
        reconciliation_signoff_id=uuid.UUID(payload.reconciliation_signoff_id),
        current_state_verified_at=payload.current_state_verified_at,
        current_state_verified_by_user_id=uuid.UUID(payload.current_state_verified_by_user_id),
        current_state_verification_scope_count=payload.current_state_verification_scope_count,
        current_state_verification_reference=payload.current_state_verification_reference,
        pilot_ward_id=uuid.UUID(payload.pilot_ward_id) if payload.pilot_ward_id else None,
        operational_approver_reference=payload.operational_approver_reference,
    )
    updated = await cutover_readiness_crud.complete_readiness_run(
        db,
        run_id=run_id,
        expected_version=payload.expected_version,
        actor_id=actor.id,
        evidence=evidence,
    )
    await record_audit_event(
        db,
        actor_user_id=actor.id,
        action=AUDIT_ACTION_CUTOVER_READINESS_RUN_COMPLETED,
        entity_type=AUDIT_ENTITY_CUTOVER_READINESS_RUN,
        entity_id=updated.id,
        after={
            "run_id": str(updated.id),
            "version": updated.version,
            "completed_at": updated.completed_at.isoformat(),
            "completed_by_user_id": str(updated.completed_by_user_id),
            "equipment_master_import_source_id": str(updated.equipment_master_import_source_id),
            "legacy_migration_authority_id": str(updated.legacy_migration_authority_id),
            "legacy_coverage_id": str(updated.legacy_coverage_id),
            "reconciliation_run_id": str(updated.reconciliation_run_id),
            "reconciliation_signoff_id": str(updated.reconciliation_signoff_id),
            "current_state_verified_at": updated.current_state_verified_at.isoformat(),
            "current_state_verified_by_user_id": str(updated.current_state_verified_by_user_id),
            "pilot_ward_id": str(updated.pilot_ward_id) if updated.pilot_ward_id else None,
        },
        request=request,
    )
    # One atomic transaction: the completion CAS UPDATE above (not yet
    # committed) and this audit write land together here, or -- if
    # anything above raised -- neither lands at all.
    await db.commit()
    return RunDetail(**_run_detail_fields(updated))
