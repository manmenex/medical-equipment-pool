"""Roadmap PR23B -- Cutover Readiness Evidence Foundation. Explicit
Pydantic request/response contracts for every endpoint -- ORM models are
never reused as API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import UUIDStr

RunStatus = Literal["pending", "running", "completed", "failed"]
SourceOfTruthStrategy = Literal["hard_cutover"]


class RunListItem(BaseModel):
    """Review-relevant run metadata only -- never the raw ORM row."""

    id: UUIDStr
    status: RunStatus
    version: int
    created_by_user_id: UUIDStr
    created_at: datetime
    completed_at: datetime | None
    completed_by_user_id: UUIDStr | None
    application_baseline_sha: str
    database_migration_head: str
    source_of_truth_strategy: SourceOfTruthStrategy
    cutover_instant: datetime
    freeze_window_reference: str | None
    supersedes_run_id: UUIDStr | None

    model_config = {"from_attributes": True}


class RunDetail(RunListItem):
    equipment_master_import_source_id: UUIDStr | None
    legacy_migration_authority_id: UUIDStr | None
    legacy_coverage_id: UUIDStr | None
    reconciliation_run_id: UUIDStr | None
    reconciliation_signoff_id: UUIDStr | None
    current_state_verified_at: datetime | None
    current_state_verified_by_user_id: UUIDStr | None
    current_state_verification_scope_count: int | None
    current_state_verification_reference: str | None
    pilot_ward_id: UUIDStr | None
    operational_approver_reference: str | None


class RunCreateRequest(BaseModel):
    """POST request body. `application_baseline_sha` is supplied by the
    caller/deployment context (this module does not itself compute it)
    -- a machine-owned identity fact, never guessed or defaulted
    server-side beyond the length/domain constraints already enforced
    by the schema.

    **PR23B Fix Round 1: `database_migration_head` is deliberately NOT a
    field on this schema.** It must prove the actual database schema
    state at capture time, so it is always read server-side from
    `alembic_version` by `app.crud.cutover_readiness.
    _get_current_database_migration_head` -- never accepted from the
    request body. `model_config = {"extra": "forbid"}` (the same
    technique `EquipmentUpdate`/`BorrowRequest`/`ReturnRequest` already
    use for their own machine-owned fields) means a caller sending
    `database_migration_head` anyway gets a hard `422` via FastAPI's
    own centralized validation-error handling, never a silently-ignored
    field."""

    application_baseline_sha: str = Field(min_length=40, max_length=40)
    cutover_instant: datetime
    source_of_truth_strategy: SourceOfTruthStrategy = "hard_cutover"
    freeze_window_reference: str | None = Field(default=None, max_length=255)
    supersedes_run_id: UUIDStr | None = None

    model_config = {"extra": "forbid"}


class RunCompleteRequest(BaseModel):
    """POST .../complete request body. Every evidence reference the
    completion call needs -- deliberately excludes every machine-owned
    field (`status`, `completed_at`, `completed_by_user_id`, `version`
    itself as a written value) other than `expected_version`, the CAS
    guard. `model_config = {"extra": "forbid"}` for the same reason as
    `RunCreateRequest` above."""

    expected_version: int = Field(ge=0)
    equipment_master_import_source_id: UUIDStr
    legacy_migration_authority_id: UUIDStr
    legacy_coverage_id: UUIDStr
    reconciliation_run_id: UUIDStr
    reconciliation_signoff_id: UUIDStr
    current_state_verified_at: datetime
    current_state_verified_by_user_id: UUIDStr
    current_state_verification_scope_count: int | None = Field(default=None, ge=0)
    current_state_verification_reference: str | None = Field(default=None, max_length=255)
    pilot_ward_id: UUIDStr | None = None
    operational_approver_reference: str | None = Field(default=None, max_length=255)

    model_config = {"extra": "forbid"}
