"""Roadmap PR25E slice B4 -- schemas for the conflict review endpoints
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 9.6, 9.8)."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

DismissReason = Literal["already_recorded", "duplicate_physical_entry", "not_real", "handled_elsewhere"]


class ReviewUser(BaseModel):
    id: UUID
    full_name: str


class ReviewEquipment(BaseModel):
    """Operator-facing equipment data only (api-information-boundaries.md):
    internal id, BCM Code, name, status. Never Item No / Asset Number."""

    id: UUID
    bcm_code: str | None
    equipment_name: str
    status: str


class ReviewItem(BaseModel):
    op_id: UUID
    op_type: str
    status: str
    result_code: str | None
    admin_only: bool
    stale_context: bool
    time_flag: str | None
    device_id: UUID
    received_at: datetime
    first_seen_at: datetime
    occurred_at: datetime | None
    attempt_count: int
    operator: ReviewUser | None
    submitted_by: ReviewUser | None
    equipment: ReviewEquipment | None
    ward_name: str | None
    transaction_id: UUID | None
    receipt_outcome: str | None
    resolution: str | None
    dismiss_reason: str | None
    resolved_by: ReviewUser | None
    resolved_at: datetime | None


class ReviewList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ReviewItem]


class ReviewDetail(ReviewItem):
    # Reviewer view of the stored payload: allow-listed fields only.
    payload_summary: dict[str, Any]
    resolution_note: str | None
    apply_now_possible: bool
    apply_now_blocker: str | None


class DismissRequest(BaseModel):
    reason: DismissReason
    note: str | None = Field(default=None, max_length=500)

    model_config = {"extra": "forbid"}


class ApplyNowRequest(BaseModel):
    model_config = {"extra": "forbid"}


class ResolveResponse(BaseModel):
    op_id: UUID
    status: str
    resolution: str
    resolved_by: UUID
    resolved_at: datetime
    # Apply now only: the fresh op that carried out the payload.
    new_op_id: UUID | None = None
    transaction_id: UUID | None = None
