"""Roadmap PR32 (D9) Monitor page: read-only event rows.

Explicit whitelist of fields -- no HN (no such field exists yet; when it is
added it must be masked here, never exposed unmasked, per D9).
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import UUIDStr


class MonitorWard(BaseModel):
    id: UUIDStr | None = None
    name: str | None = None


class MonitorOperator(BaseModel):
    id: UUIDStr | None = None
    full_name: str | None = None


class MonitorEquipment(BaseModel):
    id: UUIDStr
    bcm_code: str | None = None
    name: str
    category: str | None = None


class MonitorEvent(BaseModel):
    id: UUIDStr
    kind: Literal["dispatch", "receipt"]
    event_at: datetime
    business_date: date
    shift: Literal["day", "night"]
    ward: MonitorWard
    operator: MonitorOperator
    equipment: MonitorEquipment
    receipt_outcome: Literal["usable", "defective"] | None = None
    close_reason: str | None = None
