from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import UUIDStr


class BorrowRequest(BaseModel):
    # Equipment is always selected by internal UUID (See ADR-002) -- a QR
    # scan or BCM Code search resolves to one client-side, before this
    # request is made (See ADR-003, ADR-004). This endpoint does not
    # accept a raw QR/identifier value itself.
    equipment_id: str
    borrower_name: str = Field(min_length=1, max_length=150)
    ward_id: str | None = None
    department_id: str | None = None
    phone_number: str | None = None
    pickup_location_id: str | None = None
    dropoff_location_id: str | None = None
    quantity: int = 1
    due_at: datetime | None = None
    notes: str | None = None


class ReturnRequest(BaseModel):
    condition: str = Field(description="available|cleaning|pm|calibration|repair")
    notes: str | None = None


class EquipmentSummary(BaseModel):
    id: UUIDStr
    asset_number: str
    equipment_name: str
    status: str

    model_config = {"from_attributes": True}


class TransactionOut(BaseModel):
    id: UUIDStr
    transaction_no: str
    equipment: EquipmentSummary
    quantity: int
    borrowed_at: datetime
    due_at: datetime | None
    returned_at: datetime | None
    borrower_name: str
    ward_id: UUIDStr | None
    phone_number: str | None
    condition_on_return: str | None
    status: str
    notes: str | None

    model_config = {"from_attributes": True}
