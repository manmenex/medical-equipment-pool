"""Equipment Master's `DryRunPlanProvider` (Roadmap PR21-Foundation, design
§30/§46). A pure compatibility wrapper around the already-tested
`app.crud.import_dry_run_plan` CRUD module -- it does not rewrite any
business rule, change persistence, or alter confirmation semantics. Its
sole purpose is to let PR20's existing HTTP routes' behavior be exercised
through the generic internal provider contract (for independent test
coverage and future reuse) while the routes themselves keep calling the
CRUD module directly (§29's "smallest maintainable change" option), and to
give retention (`app.crud.import_retention.redact_session`) a fail-closed
hook for Equipment Master's own persisted plan-row content columns.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import import_dry_run_plan as import_dry_run_plan_crud
from app.models.import_session import EquipmentMasterDryRunPlan, EquipmentMasterDryRunPlanRow
from app.services.import_adapters.equipment_master import DATASET_TYPE
from app.services.import_plan_provider import (
    DryRunPlanProvider,
    PlanConfirmationResult,
    PlanRecord,
    PlanRowRecord,
    PlanSummaryRecord,
    register_plan_provider,
)


def _to_plan_record(plan: EquipmentMasterDryRunPlan) -> PlanRecord:
    return PlanRecord(
        id=plan.id,
        import_session_id=plan.import_session_id,
        import_source_id=plan.import_source_id,
        status=plan.status,
        created_at=plan.created_at,
        confirmed_at=plan.confirmed_at,
        confirmed_by_user_id=plan.confirmed_by_user_id,
        summary=PlanSummaryRecord(
            total_rows=plan.summary_total_rows,
            creates=plan.summary_creates,
            updates=plan.summary_updates,
            skips=plan.summary_skips,
            warnings=plan.summary_warnings,
            blocking_conflicts=plan.summary_blocking_conflicts,
        ),
        raw=plan,
    )


def _to_plan_row_record(row: EquipmentMasterDryRunPlanRow) -> PlanRowRecord:
    return PlanRowRecord(
        id=row.id,
        source_row_number=row.source_row_number,
        action=row.action,
        target_equipment_id=row.target_equipment_id,
        normalized_values=row.normalized_values,
        matched_identity_fields=row.matched_identity_fields,
        expected_equipment_version=row.expected_equipment_version,
        warnings=row.warnings,
    )


class EquipmentMasterDryRunPlanProvider(DryRunPlanProvider):
    dataset_type = DATASET_TYPE

    async def get_current_plan(self, db: AsyncSession, *, import_session_id: uuid.UUID) -> PlanRecord | None:
        plan = await import_dry_run_plan_crud.get_current_plan(db, import_session_id=import_session_id)
        return _to_plan_record(plan) if plan is not None else None

    async def list_plan_rows(
        self,
        db: AsyncSession,
        *,
        plan_id: uuid.UUID,
        limit: int,
        cursor_n: int | None,
        cursor_id: uuid.UUID | None,
    ) -> tuple[list[PlanRowRecord], int]:
        rows, total = await import_dry_run_plan_crud.list_plan_rows(
            db, plan_id=plan_id, limit=limit, cursor_n=cursor_n, cursor_id=cursor_id
        )
        return [_to_plan_row_record(row) for row in rows], total

    async def confirm_plan(
        self,
        db: AsyncSession,
        *,
        plan_id: uuid.UUID,
        import_session_id: uuid.UUID,
        current_user_id: uuid.UUID,
    ) -> PlanConfirmationResult:
        result = await import_dry_run_plan_crud.confirm_plan(
            db, plan_id=plan_id, import_session_id=import_session_id, current_user_id=current_user_id
        )
        return PlanConfirmationResult(plan=_to_plan_record(result.plan), newly_confirmed=result.newly_confirmed)

    async def redact_plan_artifacts(self, db: AsyncSession, *, import_session_id: uuid.UUID) -> None:
        """Roadmap PR20D (design §14.9, fix round 3 H9), relocated here
        unchanged from `app.crud.import_retention.redact_session`'s prior
        inline `UPDATE`. Every plan belonging to this session (any status:
        active/superseded/consumed/failed) has its content columns
        redacted; the structural columns (id, dry_run_plan_id,
        source_row_number, action, target_equipment_id,
        expected_equipment_version) are left untouched. A no-op for any
        session that never reached a successful dry-run persistence (no
        matching plan id). Must not call `db.commit()`/`db.rollback()` --
        the caller's retention transaction owns that boundary."""
        plan_ids_subq = select(EquipmentMasterDryRunPlan.id).where(
            EquipmentMasterDryRunPlan.import_session_id == import_session_id
        )
        await db.execute(
            update(EquipmentMasterDryRunPlanRow)
            .where(EquipmentMasterDryRunPlanRow.dry_run_plan_id.in_(plan_ids_subq))
            .values(normalized_values=None, matched_identity_fields=None, warnings=None)
        )


register_plan_provider(EquipmentMasterDryRunPlanProvider())
