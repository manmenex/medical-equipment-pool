from datetime import datetime

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
