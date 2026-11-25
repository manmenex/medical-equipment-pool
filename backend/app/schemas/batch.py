"""Roadmap PR27 (D3): ward-first batch dispatch / receipt contracts.

One submission = one ward + N equipment; every item is still its own
transaction processed by the ordinary dispatch/receipt services, so one failing
item never rolls back the others. HN is Roadmap PR29 and deliberately absent:
the item schemas are ``extra="forbid"``, so an ``hn`` field is a 422.
"""
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.equipment import EquipmentStatus
from app.models.transaction import ReceiptOutcome
from app.schemas.checklist import Checks, ContactName, CuffCounts

MAX_BATCH_ITEMS = 50


class DispatchBatchItem(BaseModel):
    equipment_id: UUID
    checks: Checks | None = None
    acknowledge_status_warning: bool = False
    expected_open_transaction_id: str | None = None
    expected_status: EquipmentStatus | None = None

    model_config = {"extra": "forbid"}


class DispatchBatchRequest(BaseModel):
    ward_id: UUID
    ward_contact_name: ContactName = None
    phone: str | None = Field(default=None, max_length=20)
    note: str | None = None
    items: list[DispatchBatchItem] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _no_duplicate_equipment(self) -> "DispatchBatchRequest":
        ids = [i.equipment_id for i in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("the same equipment_id appears more than once in items")
        return self


class ReceiptBatchItem(BaseModel):
    # Exactly one of the two: an open transaction is addressed directly, or by
    # the equipment currently out on it.
    transaction_id: UUID | None = None
    equipment_id: UUID | None = None
    receipt_outcome: ReceiptOutcome
    checks: Checks | None = None
    cuffs_returned: CuffCounts | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "ReceiptBatchItem":
        if (self.transaction_id is None) == (self.equipment_id is None):
            raise ValueError("provide exactly one of transaction_id or equipment_id")
        return self


class ReceiptBatchRequest(BaseModel):
    # Informational only (the ward the operator selected); receiving equipment
    # that was dispatched to another ward is accepted with no warning.
    ward_id: UUID | None = None
    ward_contact_name: ContactName = None
    note: str | None = None
    items: list[ReceiptBatchItem] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _no_duplicate_targets(self) -> "ReceiptBatchRequest":
        tx_ids = [i.transaction_id for i in self.items if i.transaction_id is not None]
        eq_ids = [i.equipment_id for i in self.items if i.equipment_id is not None]
        if len(set(tx_ids)) != len(tx_ids) or len(set(eq_ids)) != len(eq_ids):
            raise ValueError("the same transaction_id/equipment_id appears more than once in items")
        return self


class BatchItemError(BaseModel):
    code: str
    message: str
    status: int
    details: dict | None = None


class BatchItemResult(BaseModel):
    index: int
    ok: bool
    equipment_id: str | None = None
    transaction_id: str | None = None
    transaction_no: str | None = None
    # Cuffs still outstanding on this transaction after the item (Cryo-Cuff).
    cuffs_outstanding: CuffCounts | None = None
    error: BatchItemError | None = None


class BatchResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[BatchItemResult]
