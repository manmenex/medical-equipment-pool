from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import UUIDStr

# Roadmap PR19A1 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §21).
# Response/request contracts for endpoints #1-#6 only (create, list,
# summary, status, source register/correct, cancel) -- validate/dry-run/
# execute/recover/errors/retention-cleanup belong to later slices (§25).


class ImportSessionCreate(BaseModel):
    dataset_type: str = Field(min_length=1, max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)


class ImportSessionOut(BaseModel):
    id: UUIDStr
    dataset_type: str
    status: str
    version: int
    created_by_user_id: UUIDStr
    idempotency_key: str | None
    notes: str | None
    terminal_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    # Roadmap PR19A2 (§12): populated only once a validate attempt has
    # completed (COMPATIBLE with PR19A1's response shape -- these are
    # simply always None/unset before this slice's first validate call,
    # exactly like `jobs`/`finding_count` were always empty/zero in
    # PR19A1's ImportSessionSummaryOut before this slice existed).
    validated_at: datetime | None = None
    total_rows: int | None = None
    valid_rows: int | None = None
    invalid_rows: int | None = None
    warning_rows: int | None = None
    # Roadmap PR19A3 (§16, §17): populated only once a dry-run/execute
    # attempt has completed -- always None/unset before this slice's
    # first dry-run/execute call, exactly like PR19A2's own validate-only
    # fields were before PR19A2 existed.
    dry_run_completed_at: datetime | None = None
    executed_at: datetime | None = None
    imported_rows: int | None = None

    model_config = {"from_attributes": True}


class ImportJobSummaryOut(BaseModel):
    """Minimal, public-safe view of one `ImportJob` row, nested inside
    `ImportSessionSummaryOut` (§21 endpoint #3). Deliberately excludes the
    lease/fencing token fields (`lease_owner`, `lease_generation`,
    `lease_expires_at`, `heartbeat_at`) and `error_message`/
    `ruleset_version` -- operational detail with no public API contract in
    this foundation, not a SQLAlchemy-model passthrough (§22)."""

    id: UUIDStr
    job_type: str
    status: str
    attempt_number: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class ImportSessionSummaryOut(ImportSessionOut):
    """§21 endpoint #3 (`GET /import-sessions/{id}`): "session + jobs +
    finding count + validation_attempt_id". PR19A1 establishes this shape
    as the summary response's core; PR19A2/PR19A3 extend it additively by
    populating `jobs`/`finding_count`/`validation_attempt_id` with real
    data once validate/dry-run/execute exist -- in this foundation, no
    endpoint ever creates an `ImportJob` or `ImportRowError` row, so these
    fields are always `[]`/`0`/`None` in practice, but the response shape
    itself does not change later."""

    jobs: list[ImportJobSummaryOut]
    finding_count: int
    validation_attempt_id: UUIDStr | None


class ImportSessionStatusOut(BaseModel):
    id: UUIDStr
    status: str
    version: int
    terminal_at: datetime | None

    model_config = {"from_attributes": True}


class ImportSourceIn(BaseModel):
    checksum: str = Field(min_length=32, max_length=128)
    byte_size: int = Field(ge=0)
    content_type: str | None = Field(default=None, max_length=255)
    filename: str | None = Field(default=None, max_length=255)
    source_version: str | None = Field(default=None, max_length=100)


class ImportSourceOut(BaseModel):
    id: UUIDStr
    import_session_id: UUIDStr
    status: str
    frozen_at: datetime | None
    checksum: str
    byte_size: int
    content_type: str | None
    filename: str | None
    source_version: str | None
    source_fingerprint: str
    created_at: datetime

    model_config = {"from_attributes": True}


# Roadmap PR19A2 (§21 endpoint #9). `ImportRowError` has no `created_at`
# column (§4.4) -- pagination for this response type orders by
# row_number/id instead (see app.crud.import_job.list_findings).
class ValidationFindingOut(BaseModel):
    id: UUIDStr
    row_number: int | None
    field: str | None
    error_code: str
    message: str
    severity: str

    model_config = {"from_attributes": True}


# Roadmap PR19A3 (§21 endpoint #12).
class ImportRetentionCleanupRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


class ImportRetentionCleanupResult(BaseModel):
    purged_count: int
    skipped_count: int
    has_more: bool


# Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §14.2,
# §14.6, §30). Explicit, typed DTOs -- never raw ORM passthrough -- for the
# persisted, immutable DryRunPlan artifact. `action` is a plain string here
# (matching this codebase's existing enum-as-CHECK-constrained-VARCHAR
# convention, e.g. `ImportSession.status`), not a Python `Enum` type.
class DryRunPlanRowOut(BaseModel):
    id: UUIDStr
    source_row_number: int
    action: str
    target_equipment_id: UUIDStr | None
    normalized_values: dict[str, Any] | None
    matched_identity_fields: dict[str, Any] | None
    expected_equipment_version: int | None
    warnings: list[dict[str, Any]] | None

    model_config = {"from_attributes": True}


class DryRunPlanSummaryOut(BaseModel):
    total_rows: int
    creates: int
    updates: int
    skips: int
    warnings: int
    blocking_conflicts: int


class DryRunPlanOut(BaseModel):
    id: UUIDStr
    import_session_id: UUIDStr
    import_source_id: UUIDStr
    status: str
    # §14.6: a UX convenience only (`true` iff `status == "active"`) --
    # the *authoritative* staleness enforcement is always PR20E's own
    # resolution query, never this flag.
    is_current: bool
    created_at: datetime
    confirmed_at: datetime | None
    confirmed_by_user_id: UUIDStr | None
    summary: DryRunPlanSummaryOut
    rows: list[DryRunPlanRowOut]
    rows_next_cursor: str | None
    rows_total: int


# §14.4a: the confirm endpoint's own minimal response -- plan identity and
# confirmation state only, not the full row-paginated GET shape above.
# Fix round 2 (PR94-M1): includes the plan's own persisted `summary` --
# the response describes the artifact that was confirmed, so this is
# always built from the already-loaded, already-persisted plan row
# returned by `confirm_plan`, never recomputed from Equipment, validation
# findings, or a fresh adapter invocation.
class DryRunPlanConfirmOut(BaseModel):
    id: UUIDStr
    import_session_id: UUIDStr
    status: str
    confirmed_at: datetime | None
    confirmed_by_user_id: UUIDStr | None
    summary: DryRunPlanSummaryOut

    model_config = {"from_attributes": True}
