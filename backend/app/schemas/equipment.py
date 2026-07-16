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
