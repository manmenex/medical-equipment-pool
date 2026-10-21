"""Roadmap PR21E0 -- Legacy Import Operator API Surface. Closes gap B
(§12-§20 of the task): dedicated, statically typed response contracts for
the PR21-specific `/import-sessions/{id}/legacy-history/dry-run-plan...`
routes (`app.api.v1.legacy_history_import`).

Deliberately does NOT reuse `app.schemas.import_session`'s
`DryRunPlanRowOut`/`DryRunPlanSummaryOut`/`DryRunPlanOut`/
`DryRunPlanConfirmOut` -- those describe Equipment Master's own
create/update/skip upsert shape (`action`, `target_equipment_id`,
`matched_identity_fields`, `expected_equipment_version`), fields that do
not exist on `LegacyHistoryDryRunPlan`/`Row` (`app.models.legacy_history`)
at all. Every field below maps only to what PR21's own persistence
actually stores -- see that module and
`app.services.import_adapters.legacy_history.combined._candidate_to_row_dict`
(the sole writer of `LegacyHistoryDryRunPlanRow.normalized_values`) for
the source of truth this schema mirrors."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import UUIDStr


class LegacyHistoryDryRunPlanSummaryOut(BaseModel):
    """Maps `LegacyHistoryDryRunPlan.summary_*` exactly -- PR21's own
    insert-oriented (Issue/Receive event) summary shape, not Equipment
    Master's upsert-oriented creates/updates/skips."""

    total_rows: int
    issue_events: int
    receive_events: int
    warnings: int
    blocking_conflicts: int


class LegacyHistoryDryRunPlanOut(BaseModel):
    """§13 of the task: identity + summary only -- deliberately does NOT
    embed a page of rows the way PR20's `DryRunPlanOut` does. Row content
    is served by the separate `.../rows` endpoint below instead, so
    pagination logic exists in exactly one place."""

    id: UUIDStr
    import_session_id: UUIDStr
    import_source_id: UUIDStr
    migration_authority_id: UUIDStr
    status: str
    # §13: a UX convenience only (`true` iff `status == "active"`), never
    # itself the authoritative staleness check -- mirrors
    # `DryRunPlanOut.is_current`'s identical convention.
    is_current: bool
    created_at: datetime
    confirmed_at: datetime | None
    confirmed_by_user_id: UUIDStr | None
    summary: LegacyHistoryDryRunPlanSummaryOut


class LegacyHistoryDryRunPlanSourceRefOut(BaseModel):
    sheet_name: str
    source_row_number: int


class LegacyHistoryDryRunPlanRowValuesOut(BaseModel):
    """Typed mirror of `_candidate_to_row_dict`'s own
    `normalized_values` dict -- every key that function ever writes, and
    nothing else. `หมายเหตุ`/notes are never present in the persisted
    dict in the first place (OD-PR21-6) -- there is nothing to redact or
    omit here beyond simply not inventing a field that was never
    written."""

    legacy_order_reference: str | None
    equipment_id: UUIDStr
    occurred_at: datetime
    legacy_ward_text: str | None
    resolved_ward_id: UUIDStr | None
    legacy_bme_name: str | None
    header_source_ref: LegacyHistoryDryRunPlanSourceRefOut
    line_source_ref: LegacyHistoryDryRunPlanSourceRefOut


class LegacyHistoryDryRunPlanRowOut(BaseModel):
    id: UUIDStr
    source_row_number: int
    event_type: str
    legacy_source_row_key: str
    # `None` only for a row whose plan artifact content has already been
    # redacted by retention (`LegacyHistoryDryRunPlanProvider.
    # redact_plan_artifacts` sets `normalized_values`/`warnings` to
    # `NULL`, structural columns untouched) -- never `None` for a live,
    # unredacted row.
    values: LegacyHistoryDryRunPlanRowValuesOut | None
    # No adapter has ever populated a non-empty `warnings` list on this
    # table yet (`_candidate_to_row_dict` always writes `[]`) -- typed as
    # a plain string list, the minimum defensible shape for "a warning
    # message", rather than inventing a richer structure nothing
    # currently produces.
    warnings: list[str] | None


class LegacyHistoryDryRunPlanConfirmOut(BaseModel):
    """§17 of the task -- mirrors `DryRunPlanConfirmOut`'s identical
    minimal shape (identity + confirmation state + summary only, not the
    full row-paginated GET response)."""

    id: UUIDStr
    import_session_id: UUIDStr
    status: str
    confirmed_at: datetime | None
    confirmed_by_user_id: UUIDStr | None
    summary: LegacyHistoryDryRunPlanSummaryOut
