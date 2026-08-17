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

PR100-H1 fix round: this provider now returns its own already-existing
domain objects directly -- `EquipmentMasterDryRunPlan`/
`EquipmentMasterDryRunPlanRow` ORM rows and the CRUD layer's own
`ConfirmationResult` -- as `DryRunPlanProvider`'s opaque `PlanT`/`RowT`/
`ConfirmT`. There is no longer a parallel `PlanRecord`/`PlanRowRecord`
mapping layer: that mapping was the exact mechanism by which Equipment
Master's field vocabulary (`creates`/`target_equipment_id`/...) leaked into
what was supposed to be a provider-neutral shared contract.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ImportDryRunPlanNotFoundError, InvalidInputError
from app.crud import import_dry_run_plan as import_dry_run_plan_crud
from app.crud.import_dry_run_plan import ConfirmationResult
from app.models.import_session import EquipmentMasterDryRunPlan, EquipmentMasterDryRunPlanRow
from app.services.import_adapters.equipment_master import DATASET_TYPE
from app.services.import_plan_provider import (
    DryRunPlanProvider,
    Page,
    decode_plan_row_cursor,
    encode_plan_row_cursor,
    register_plan_provider,
)


class EquipmentMasterDryRunPlanProvider(
    DryRunPlanProvider[EquipmentMasterDryRunPlan, EquipmentMasterDryRunPlanRow, ConfirmationResult]
):
    dataset_type = DATASET_TYPE

    async def get_current_plan(self, db: AsyncSession, *, import_session_id: uuid.UUID) -> EquipmentMasterDryRunPlan | None:
        return await import_dry_run_plan_crud.get_current_plan(db, import_session_id=import_session_id)

    async def list_plan_rows(
        self,
        db: AsyncSession,
        *,
        import_session_id: uuid.UUID,
        plan_id: uuid.UUID,
        limit: int,
        cursor: str | None,
    ) -> Page[EquipmentMasterDryRunPlanRow]:
        """PR100-H2: ownership-checked before any pagination happens (the
        same `get_plan_by_id` lookup `confirm_plan`'s own docstring
        describes as "never leaked across sessions") -- a `plan_id` that
        exists but belongs to a different `import_session_id` is rejected
        as `ImportDryRunPlanNotFoundError`, the same code this dataset's
        read path (`GET .../dry-run-plan`) already uses for "no plan to
        read here". A `cursor` is rejected the same way (`InvalidInputError`,
        via `decode_plan_row_cursor`) if it was not issued for this exact
        `plan_id` -- it is never reinterpreted as an anchor into this
        plan's own rows."""
        plan = await import_dry_run_plan_crud.get_plan_by_id(db, plan_id=plan_id, import_session_id=import_session_id)
        if plan is None:
            raise ImportDryRunPlanNotFoundError(
                f"Dry-run plan '{plan_id}' does not exist, or does not belong to import session "
                f"'{import_session_id}'."
            )

        cursor_n: int | None = None
        cursor_id: uuid.UUID | None = None
        if cursor is not None:
            decoded = decode_plan_row_cursor(cursor)
            if decoded.plan_id != plan_id:
                raise InvalidInputError("Pagination cursor does not belong to the requested plan.")
            cursor_n, cursor_id = decoded.sort_value, decoded.row_id

        rows, total = await import_dry_run_plan_crud.list_plan_rows(
            db, plan_id=plan_id, limit=limit, cursor_n=cursor_n, cursor_id=cursor_id
        )
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = encode_plan_row_cursor(plan_id=plan_id, sort_value=last.source_row_number, row_id=last.id)
        return Page(rows=rows, total=total, next_cursor=next_cursor)

    async def confirm_plan(
        self,
        db: AsyncSession,
        *,
        plan_id: uuid.UUID,
        import_session_id: uuid.UUID,
        current_user_id: uuid.UUID,
    ) -> ConfirmationResult:
        return await import_dry_run_plan_crud.confirm_plan(
            db, plan_id=plan_id, import_session_id=import_session_id, current_user_id=current_user_id
        )

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
