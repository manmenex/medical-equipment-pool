"""Roadmap PR25E slice B3 -- schemas for ``POST /sync/verify``,
``GET /sync/snapshot``, ``GET /sync/status`` and ``GET /sync/stats``
(docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections 6.1, 6.5, 10, 16, 16.1)."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

MAX_VERIFY_IDS = 1000


class SyncVerifyRequest(BaseModel):
    op_ids: list[UUID] = Field(min_length=1, max_length=MAX_VERIFY_IDS)

    model_config = {"extra": "forbid"}


class SyncVerifyResponse(BaseModel):
    checked: int
    unknown_op_ids: list[UUID]


class SyncSnapshotPage(BaseModel):
    section: str
    items: list[dict[str, Any]]
    next_cursor: str | None
    etag: str
    server_time: datetime


class SyncStatusResponse(BaseModel):
    window_hours: int
    server_time: datetime
    ops_by_status: dict[str, int]
    resent_attempts: int
    time_flag_ops: int
    unresolved_conflicts: int
    oldest_unresolved_conflict_age_s: int | None
    verify_calls: int
    verify_calls_with_unknown: int


class SyncStatsResponse(BaseModel):
    range_from: datetime
    range_to: datetime
    volume: dict[str, Any]
    clock_skew: dict[str, Any]
