"""Roadmap PR25E slice B2 -- envelope and result schemas for
``POST /api/v1/sync/operations`` (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md
section 6.1).

The envelope is strict (``extra="forbid"``): the sync layer is a thin wrapper
around dispatch/receipt, so it can carry no equipment status, transaction
status or any other lifecycle field. The inner ``dispatch`` object IS
``BorrowRequest`` and ``receipt`` extends ``ReturnRequest``, so business
validation is not duplicated.
"""
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.transaction import BorrowRequest, ReturnRequest

MAX_BATCH_SIZE = 25
MAX_OP_BYTES = 8 * 1024
MAX_DEVICE_SEQ = 2**62

OP_TYPE_DISPATCH = "dispatch"
OP_TYPE_RECEIPT = "receipt"

RESULT_APPLIED = "applied"
RESULT_DUPLICATE = "duplicate"
RESULT_CONFLICT = "conflict"
RESULT_REJECTED = "rejected"
RESULT_RETRY_LATER = "retry_later"


class SyncReceiptBody(ReturnRequest):
    """``ReturnRequest`` plus the target transaction (``extra="forbid"`` is
    inherited). For a receipt the target is the server transaction id, which
    for an offline dispatch equals that dispatch's ``op_id``."""

    transaction_id: UUID


class SyncOperation(BaseModel):
    op_id: UUID
    device_id: UUID
    device_seq: int = Field(ge=0, le=MAX_DEVICE_SEQ)
    # The operator the client believes keyed the operation. The server takes
    # the real user from the token and rejects a mismatch (OP_USER_MISMATCH).
    user_id: UUID
    op_type: Literal["dispatch", "receipt"]
    occurred_at_local: datetime
    clock_offset_ms: int | None = Field(default=None, ge=-(2**40), le=2**40)
    dispatch: BorrowRequest | None = None
    receipt: SyncReceiptBody | None = None

    model_config = {"extra": "forbid"}

    @field_validator("op_id", "device_id")
    @classmethod
    def _uuid4_only(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("must be a UUID v4")
        return value

    @field_validator("occurred_at_local")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        # UTCDateTime refuses non-UTC aware values; a naive one is read as UTC.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _body_matches_type(self) -> "SyncOperation":
        if self.op_type == OP_TYPE_DISPATCH:
            if self.dispatch is None or self.receipt is not None:
                raise ValueError("op_type 'dispatch' requires 'dispatch' and forbids 'receipt'")
        else:
            if self.receipt is None or self.dispatch is not None:
                raise ValueError("op_type 'receipt' requires 'receipt' and forbids 'dispatch'")
        size = len(json.dumps(self.model_dump(mode="json"), separators=(",", ":")).encode("utf-8"))
        if size > MAX_OP_BYTES:
            raise ValueError(f"operation exceeds {MAX_OP_BYTES} bytes")
        return self

    def business_payload(self) -> dict:
        """The canonical business payload that is hashed and stored."""
        body = self.dispatch if self.op_type == OP_TYPE_DISPATCH else self.receipt
        return {"op_type": self.op_type, self.op_type: body.model_dump(mode="json")}


class SyncBatchRequest(BaseModel):
    operations: list[SyncOperation] = Field(min_length=1, max_length=MAX_BATCH_SIZE)

    model_config = {"extra": "forbid"}


class SyncOpResult(BaseModel):
    op_id: UUID
    result: Literal["applied", "duplicate", "conflict", "rejected", "retry_later"]
    code: str
    transaction_id: UUID | None = None
    message: str


class SyncBatchResponse(BaseModel):
    results: list[SyncOpResult]
