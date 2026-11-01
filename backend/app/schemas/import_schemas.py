"""Roadmap PR12 (Inventory Import) response schemas. See
app.services.import_service for the full design this serializes."""

from pydantic import BaseModel

from app.services.import_service import ImportRowAction, ImportRowStatus


class ImportRowResultOut(BaseModel):
    row_number: int
    bcm_code: str | None
    item_no: str | None
    asset_id: str | None
    status: ImportRowStatus
    action: ImportRowAction | None = None
    reason: str | None = None
    equipment_id: str | None = None

    model_config = {"from_attributes": True}


class ImportPreviewResponse(BaseModel):
    """Response for POST /import/preview. Nothing in this response implies
    any database write occurred -- see import_service's module docstring."""

    filename: str
    total_rows: int
    succeeded: int
    failed: int
    skipped: int
    rows: list[ImportRowResultOut]

    model_config = {"from_attributes": True}


class ImportCommitResponse(ImportPreviewResponse):
    """Response for POST /import/commit. `audit_log_id` is the single
    batch-level audit_logs entry (Part F.1 step 7) -- not one entry per
    row."""

    audit_log_id: str | None = None
