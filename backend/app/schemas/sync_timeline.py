"""Roadmap PR25E slice B4b -- schemas for the per-equipment timeline, Apply
sequence and collision statistics (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md
sections 9.7, 16.1)."""
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.sync_review import ReviewEquipment, ReviewUser


class TimelineEvent(BaseModel):
    """One point on an equipment timeline. ``source`` is ``transaction``
    (a committed dispatch/receipt; read-only) or ``op`` (a reviewable ledger
    op; ``selectable`` for Apply sequence)."""

    source: Literal["transaction", "op"]
    kind: Literal["dispatch", "receipt"]
    at: datetime
    band_s: int
    order_uncertain: bool
    selectable: bool
    op_id: UUID | None = None
    status: str | None = None
    result_code: str | None = None
    admin_only: bool = False
    stale_context: bool = False
    time_flag: str | None = None
    device_id: UUID | None = None
    device_seq: int | None = None
    operator: ReviewUser | None = None
    ward_name: str | None = None
    receipt_outcome: str | None = None
    transaction_id: UUID | None = None


class EquipmentTimeline(BaseModel):
    equipment: ReviewEquipment
    server_time: datetime
    events: list[TimelineEvent]


class ApplySequenceRequest(BaseModel):
    op_ids: list[UUID] = Field(min_length=1, max_length=25)
    # Advisory lifecycle simulation only; writes nothing.
    dry_run: bool = False

    model_config = {"extra": "forbid"}


class SequenceStep(BaseModel):
    op_id: UUID
    ok: bool
    code: str | None = None
    message: str | None = None
    new_op_id: UUID | None = None
    transaction_id: UUID | None = None


class ApplySequenceResponse(BaseModel):
    dry_run: bool
    # Steps applied (or, for a dry run, simulated), in order.
    steps: list[SequenceStep]
    # First failure (null when the whole sequence held); later ops untouched.
    failed: SequenceStep | None = None
    remaining: list[UUID] = []


class CollisionStats(BaseModel):
    range_from: datetime
    range_to: datetime
    total_conflicts: int
    by_result_code: dict[str, int]
    by_status: dict[str, int]
    by_day: dict[str, int]
    groups: dict[str, Any]
    truncated: bool
