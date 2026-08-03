"""Roadmap PR19A (Legacy Import Foundation) API schemas. See
app.services.import_foundation for the full design these serialize."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.import_session import ImportErrorSeverity, ImportJobStatus, ImportJobType, ImportSessionStatus
from app.schemas.common import UUIDStr


class ImportSessionCreate(BaseModel):
    """Request body for `POST /import-sessions`. Deliberately carries no
    file/raw content -- this foundation slice's session-creation step only
    declares *intent* (which dataset type, optional idempotency/duplicate-
    detection hints); the raw input a concrete adapter parses is supplied
    separately to the validate step by a future slice's own contract, once
    a real adapter is registered for the chosen `dataset_type`."""

    dataset_type: str = Field(min_length=1, max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=200)
    source_checksum: str | None = Field(default=None, max_length=128)
    source_filename: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class ImportSessionOut(BaseModel):
    id: UUIDStr
    dataset_type: str
    status: ImportSessionStatus
    created_by_user_id: UUIDStr
    idempotency_key: str | None
    source_checksum: str | None
    source_filename: str | None
    notes: str | None
    total_rows: int | None
    valid_rows: int | None
    invalid_rows: int | None
    imported_rows: int | None
    failure_reason: str | None
    validated_at: datetime | None
    dry_run_completed_at: datetime | None
    executed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImportSessionStatusOut(BaseModel):
    """Lightweight response for `GET /import-sessions/{id}/status` -- the
    "import status" endpoint (design API list). Deliberately narrower than
    `ImportSessionOut`: a caller polling for progress needs the state
    machine position and counts, not the full record."""

    id: UUIDStr
    status: ImportSessionStatus
    total_rows: int | None
    valid_rows: int | None
    invalid_rows: int | None
    imported_rows: int | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImportJobOut(BaseModel):
    id: UUIDStr
    job_type: ImportJobType
    status: ImportJobStatus
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None

    model_config = {"from_attributes": True}


class ImportSessionSummaryOut(BaseModel):
    """Response for `GET /import-sessions/{id}` -- the "import summary"
    endpoint (design API list, "Import result summary model"). Combines
    the session record with its phase history and a bounded count of
    collected row errors (the errors themselves are paginated separately
    via `GET /import-sessions/{id}/errors`, not embedded here in full)."""

    session: ImportSessionOut
    jobs: list[ImportJobOut]
    error_count: int

    model_config = {"from_attributes": True}


class ImportRowErrorOut(BaseModel):
    id: UUIDStr
    row_number: int | None
    field: str | None
    error_code: str
    message: str
    severity: ImportErrorSeverity

    model_config = {"from_attributes": True}
