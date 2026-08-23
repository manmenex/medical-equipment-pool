"""Roadmap PR22D -- Finding Review / Disposition API.

Read surfaces (run list/detail, finding list/detail) are available to
every authenticated role (`VIEW_AND_REPORT_ROLES`) -- reviewing is not
itself a mutation. The single disposition-mutation endpoint (`PATCH
.../disposition`) is Administrator-only (OD-PR22-5); `equipment_pool_
staff`/`read_only` receive a plain 403, enforced at this dependency
layer, never left to the frontend to hide.

Two route families, matching this repository's existing per-resource
prefix convention (`legacy-migration-authorities`, `legacy-history-
import`, etc. -- never one shared umbrella prefix):
`/legacy-reconciliation-runs` and `/legacy-reconciliation-findings`.

Deliberately absent from this module (PR22E/F/G's own scope, §40/§41 of
the task): any sign-off creation endpoint, any correction workflow, any
frontend. This module only ever *reads* `LegacyReconciliationSignOff`
existence, to enforce disposition immutability once a run is signed off.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, VIEW_AND_REPORT_ROLES, require_roles
from app.core.audit import AUDIT_ACTION_RECONCILIATION_FINDING_DISPOSED, AUDIT_ENTITY_RECONCILIATION_FINDING, record_audit_event
from app.core.exceptions import InvalidInputError, ReconciliationFindingNotFoundError, ReconciliationRunNotFoundError
from app.crud import legacy_reconciliation as reconciliation_crud
from app.db.session import get_db
from app.models.equipment import Equipment
from app.models.legacy_reconciliation import (
    LegacyReconciliationFinding,
    LegacyReconciliationRun,
    RECONCILIATION_DISPOSITIONS,
    RECONCILIATION_SEVERITIES,
)
from app.schemas.common import Page
from app.schemas.legacy_reconciliation import (
    EquipmentSummary,
    FindingDetail,
    FindingDispositionRequest,
    FindingListItem,
    LegacyEventRef,
    RunDetail,
    RunListItem,
)
from app.utils.pagination import decode_cursor, encode_cursor

runs_router = APIRouter(prefix="/legacy-reconciliation-runs", tags=["legacy-reconciliation"])
findings_router = APIRouter(prefix="/legacy-reconciliation-findings", tags=["legacy-reconciliation"])


def _decode_pagination_cursor(cursor: str | None) -> tuple:
    if not cursor:
        return None, None
    cursor_dt, cursor_id_raw = decode_cursor(cursor)
    try:
        cursor_id = uuid.UUID(cursor_id_raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidInputError("Invalid or malformed pagination cursor.") from exc
    return cursor_dt, cursor_id


def _run_common_fields(run: LegacyReconciliationRun) -> dict:
    return {
        "id": str(run.id),
        "status": run.status,
        "version": run.version,
        "rule_version": run.rule_version,
        "snapshot_as_of": run.snapshot_as_of,
        "created_by_user_id": str(run.created_by_user_id),
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "failed_at": run.failed_at,
        "legacy_coverage_start": run.legacy_coverage_start,
        "legacy_coverage_end": run.legacy_coverage_end,
        "live_system_start": run.live_system_start,
        "summary_total_findings": run.summary_total_findings,
        "summary_high": run.summary_high,
        "summary_medium": run.summary_medium,
        "summary_low": run.summary_low,
    }


async def _get_run_or_404(db: AsyncSession, run_id: uuid.UUID) -> LegacyReconciliationRun:
    run = await reconciliation_crud.get_run(db, run_id=run_id)
    if run is None:
        raise ReconciliationRunNotFoundError(f"Reconciliation run '{run_id}' not found.")
    return run


async def _build_finding_detail(db: AsyncSession, finding: LegacyReconciliationFinding) -> FindingDetail:
    equipment = None
    if finding.equipment_id is not None:
        eq_row = await db.get(Equipment, finding.equipment_id)
        if eq_row is not None:
            equipment = EquipmentSummary.model_validate(eq_row)
    events = await reconciliation_crud.list_finding_event_refs(db, finding_id=finding.id)
    base = FindingListItem.model_validate(finding)
    return FindingDetail(
        **base.model_dump(),
        evidence=finding.evidence,
        equipment=equipment,
        events=[LegacyEventRef.model_validate(e) for e in events],
    )


@runs_router.get("", response_model=Page[RunListItem])
async def list_reconciliation_runs(
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    cursor_dt, cursor_id = _decode_pagination_cursor(cursor)
    rows, total = await reconciliation_crud.list_runs(db, limit=limit, cursor_dt=cursor_dt, cursor_id=cursor_id)
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))

    signoff_run_ids = await reconciliation_crud.list_signoff_run_ids(db, run_ids=[r.id for r in rows])
    items = [RunListItem(**_run_common_fields(r), has_signoff=r.id in signoff_run_ids) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=total)


@runs_router.get("/{run_id}", response_model=RunDetail)
async def get_reconciliation_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    run = await _get_run_or_404(db, run_id)
    has_signoff = await reconciliation_crud.run_has_signoff(db, run_id=run.id)
    counts = await reconciliation_crud.finding_counts_by_disposition(db, run_id=run.id)
    return RunDetail(
        **_run_common_fields(run),
        has_signoff=has_signoff,
        coverage_id=str(run.coverage_id),
        supersedes_run_id=str(run.supersedes_run_id) if run.supersedes_run_id is not None else None,
        finding_counts_by_disposition={(disposition or "open"): count for disposition, count in counts.items()},
    )


@runs_router.get("/{run_id}/findings", response_model=Page[FindingListItem])
async def list_reconciliation_findings(
    run_id: uuid.UUID,
    code: str | None = None,
    severity: str | None = None,
    disposition: str | None = None,
    equipment_id: uuid.UUID | None = None,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    # Guarantees findings returned genuinely belong to run_id (§35 of the
    # task) -- the run itself must exist, and list_findings below always
    # filters on run_id in SQL.
    await _get_run_or_404(db, run_id)

    if severity is not None and severity not in RECONCILIATION_SEVERITIES:
        raise InvalidInputError(f"Unknown severity filter value: '{severity}'.")

    disposition_is_null = False
    disposition_value: str | None = None
    if disposition is not None:
        if disposition in ("null", "open"):
            disposition_is_null = True
        elif disposition in RECONCILIATION_DISPOSITIONS:
            disposition_value = disposition
        else:
            raise InvalidInputError(f"Unknown disposition filter value: '{disposition}'.")

    cursor_dt, cursor_id = _decode_pagination_cursor(cursor)
    rows, total = await reconciliation_crud.list_findings(
        db,
        run_id=run_id,
        limit=limit,
        cursor_dt=cursor_dt,
        cursor_id=cursor_id,
        code=code,
        severity=severity,
        disposition=disposition_value,
        disposition_is_null=disposition_is_null,
        equipment_id=equipment_id,
    )
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))
    return Page(items=rows, next_cursor=next_cursor, total=total)


@findings_router.get("/{finding_id}", response_model=FindingDetail)
async def get_reconciliation_finding(
    finding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    finding = await reconciliation_crud.get_finding(db, finding_id=finding_id)
    if finding is None:
        raise ReconciliationFindingNotFoundError(f"Reconciliation finding '{finding_id}' not found.")
    return await _build_finding_detail(db, finding)


@findings_router.patch("/{finding_id}/disposition", response_model=FindingDetail)
async def update_reconciliation_finding_disposition(
    finding_id: uuid.UUID,
    payload: FindingDispositionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    updated, previous = await reconciliation_crud.update_finding_disposition(
        db,
        finding_id=finding_id,
        expected_version=payload.expected_version,
        disposition=payload.disposition,
        disposition_note=payload.disposition_note,
        actor_id=actor.id,
    )
    await record_audit_event(
        db,
        actor_user_id=actor.id,
        action=AUDIT_ACTION_RECONCILIATION_FINDING_DISPOSED,
        entity_type=AUDIT_ENTITY_RECONCILIATION_FINDING,
        entity_id=updated.id,
        before={
            "disposition": previous.disposition,
            "disposed_by_user_id": str(previous.disposed_by_user_id) if previous.disposed_by_user_id else None,
            "disposed_at": previous.disposed_at.isoformat() if previous.disposed_at else None,
            "disposition_note": previous.disposition_note,
            "version": previous.version,
        },
        after={
            "disposition": updated.disposition,
            "disposed_by_user_id": str(updated.disposed_by_user_id),
            "disposed_at": updated.disposed_at.isoformat(),
            "disposition_note": updated.disposition_note,
            "version": updated.version,
        },
        request=request,
    )
    # One atomic transaction: the CAS UPDATE above (not yet committed)
    # and this audit write (flush-only, per app.core.audit's own
    # docstring) land together here, or -- if anything above raised --
    # neither lands at all (§22 of the task).
    await db.commit()
    return await _build_finding_detail(db, updated)
