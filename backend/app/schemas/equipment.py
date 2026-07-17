from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.equipment import EquipmentStatus


class EquipmentBase(BaseModel):
    asset_number: str = Field(min_length=1, max_length=50)
    serial_number: str | None = Field(default=None, max_length=100)
    equipment_name: str = Field(min_length=1, max_length=255)
    category_id: str | None = None
    brand: str | None = None
    model: str | None = None
    department_owner_id: str | None = None
    current_location_id: str | None = None
    pm_due_date: date | None = None
    cal_due_date: date | None = None
    # Roadmap PR5: item_no is the internal QR-resolution key (structurally
    # ready for a future controlled Excel import, PR8); bcm_code is the
    # operator-facing identifier the manual-search endpoint matches
    # against. Both optional -- existing equipment predates these fields.
    item_no: str | None = Field(default=None, max_length=64)
    bcm_code: str | None = Field(default=None, max_length=64)


class EquipmentCreate(EquipmentBase):
    pass


class EquipmentUpdate(BaseModel):
    equipment_name: str | None = None
    serial_number: str | None = None
    category_id: str | None = None
    brand: str | None = None
    model: str | None = None
    department_owner_id: str | None = None
    current_location_id: str | None = None
    pm_due_date: date | None = None
    cal_due_date: date | None = None
    item_no: str | None = None
    bcm_code: str | None = None


class EquipmentStatusChange(BaseModel):
    status: EquipmentStatus
    reason: str | None = None


class EquipmentOut(EquipmentBase):
    id: str
    status: EquipmentStatus
    qr_code_value: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EquipmentStatusHistoryOut(BaseModel):
    id: str
    from_status: str | None
    to_status: str
    reason: str | None
    changed_at: datetime

    model_config = {"from_attributes": True}


class BcmSuggestion(BaseModel):
    """Roadmap PR5 manual-search suggestion: the minimum data needed to
    identify and select a result. Deliberately excludes item_no, device
    name, brand, model, serial number, and status -- see
    docs/kickoffs/PR5-equipment-master-bcm-search.md.
    """

    id: str
    bcm_code: str

    model_config = {"from_attributes": True}


class QrResolveRequest(BaseModel):
    """Roadmap PR5: the raw, as-scanned QR payload. Validation of its
    *content* (empty, too long, URL-shaped) happens in
    app.services.qr_service.extract_item_no_from_qr, not here, so every
    malformed case reaches the client through the same MalformedQrCodeError
    response shape regardless of which specific check caught it.
    """

    raw_value: str
