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
