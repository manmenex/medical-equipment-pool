from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExportEquipment(BaseModel):
    id: str
    bcm_code: str | None
    name: str
    category: str | None


class ExportWard(BaseModel):
    id: str
    code: str
    name: str


class ExportEventOut(BaseModel):
    seq: int
    event_id: str
    event_type: str
    event_time: datetime
    transaction_id: str
    transaction_no: str
    equipment: ExportEquipment
    ward: ExportWard | None
    dispatch_type: str | None
    routine_round: str | None
    receipt_outcome: str | None
    operator_name: str | None


class ExportEventsPage(BaseModel):
    events: list[ExportEventOut]
    # Pass as ``after`` on the next poll. Equals the request's ``after`` when
    # the page is empty, so it is always safe to persist.
    next_cursor: int
    has_more: bool


class ExportCursorOut(BaseModel):
    cursor: int


class ExportKeyCreate(BaseModel):
    name: str

    model_config = ConfigDict(str_strip_whitespace=True, str_min_length=1, str_max_length=100)


class ExportKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class ExportKeyCreated(ExportKeyOut):
    # Shown exactly once, at creation.
    key: str
