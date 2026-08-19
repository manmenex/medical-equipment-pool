"""PR21's `DryRunPlanProvider` (Roadmap PR21A, design §36/§46). A thin
wrapper around `app.crud.legacy_history_dry_run_plan`, following the
exact same compatibility-wrapper shape as
`app.services.import_plan_providers.equipment_master` -- it does not
rewrite any business rule, change persistence, or alter confirmation
semantics; its sole purpose is to let PR21's own dry-run-plan artifacts
be exercised through the generic internal provider contract PR21-
Foundation (GitHub PR #100) defines.

**No PR21 parser exists yet.** No adapter in this slice ever calls
`get_current_plan`/`list_plan_rows`/`confirm_plan` in production --
this provider exists so retention's fail-closed dispatch
(`app.crud.import_retention.redact_session`) can resolve a provider for
`dataset_type` the moment a future PR21B/C/D adapter's dry-run
completes, and so this slice's own tests can exercise the full
provider contract directly."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ImportDryRunPlanNotFoundError, InvalidInputError
from app.crud import legacy_history_dry_run_plan as legacy_history_dry_run_plan_crud
from app.crud.legacy_history_dry_run_plan import ConfirmationResult
from app.models.legacy_history import LegacyHistoryDryRunPlan, LegacyHistoryDryRunPlanRow
from app.services.import_plan_provider import (
    DryRunPlanProvider,
    Page,
    decode_plan_row_cursor,
    encode_plan_row_cursor,
    register_plan_provider,
)

# Roadmap PR21A. Not read anywhere else yet -- a future PR21B/C/D
# adapter is the one that will set `ImportSession.dataset_type` to this
# value on session creation, matching how `equipment_master`'s own
# `DATASET_TYPE` is used.
DATASET_TYPE = "legacy_transaction_history"


class LegacyHistoryDryRunPlanProvider(
    DryRunPlanProvider[LegacyHistoryDryRunPlan, LegacyHistoryDryRunPlanRow, ConfirmationResult]
):
    dataset_type = DATASET_TYPE

    async def get_current_plan(
        self, db: AsyncSession, *, import_session_id: uuid.UUID
    ) -> LegacyHistoryDryRunPlan | None:
        return await legacy_history_dry_run_plan_crud.get_current_plan(db, import_session_id=import_session_id)

    async def list_plan_rows(
        self,
        db: AsyncSession,
        *,
        import_session_id: uuid.UUID,
        plan_id: uuid.UUID,
        limit: int,
        cursor: str | None,
    ) -> Page[LegacyHistoryDryRunPlanRow]:
        """Mirrors `EquipmentMasterDryRunPlanProvider.list_plan_rows`'s
        own PR100-H2 discipline exactly: ownership-checked before any
        pagination happens, and a cursor is rejected outright if it was
        not issued for this exact `plan_id`."""
        plan = await legacy_history_dry_run_plan_crud.get_plan_by_id(
            db, plan_id=plan_id, import_session_id=import_session_id
        )
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

        rows, total = await legacy_history_dry_run_plan_crud.list_plan_rows(
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
        return await legacy_history_dry_run_plan_crud.confirm_plan(
            db, plan_id=plan_id, import_session_id=import_session_id, current_user_id=current_user_id
        )

    async def redact_plan_artifacts(self, db: AsyncSession, *, import_session_id: uuid.UUID) -> None:
        """§38/§39's fail-closed retention hook, restricted to PR21's own
        **temporary** dry-run-plan row content -- never
        `LegacyEquipmentEvent`/`LegacyEquipmentEventSourceRef`, which are
        permanent historical evidence and must survive the 180-day import-
        artifact retention timer regardless (§39's "temporary vs.
        permanent provenance" boundary, unchanged by this slice). Every
        plan belonging to this session (any status) has its content
        columns redacted; the structural columns (id, dry_run_plan_id,
        source_row_number, event_type, legacy_source_row_key) are left
        untouched, mirroring `EquipmentMasterDryRunPlanProvider`'s own
        redaction shape. A no-op for a session that never reached a
        successful dry-run persistence. Must not call
        `db.commit()`/`db.rollback()` -- the caller's retention
        transaction owns that boundary."""
        plan_ids_subq = select(LegacyHistoryDryRunPlan.id).where(
            LegacyHistoryDryRunPlan.import_session_id == import_session_id
        )
        await db.execute(
            update(LegacyHistoryDryRunPlanRow)
            .where(LegacyHistoryDryRunPlanRow.dry_run_plan_id.in_(plan_ids_subq))
            .values(normalized_values=None, warnings=None)
        )


register_plan_provider(LegacyHistoryDryRunPlanProvider())
