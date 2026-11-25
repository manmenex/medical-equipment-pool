"""Roadmap PR32 (D9) Monitor page: read-only event rows.

Explicit whitelist of fields. Roadmap PR29: only the ``has_hn`` indicator is
exposed -- the HN itself is revealed solely by the audited
POST /transactions/{id}/reveal-hn (D1/D9), never listed here.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.checklist import Checks, CuffCounts
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
    # Roadmap PR27 (D7): the ward-side contact name recorded on this event's
    # side (dispatch_contact_name for dispatch events, receipt_contact_name for
    # receipt events). Never a patient name.
    ward_contact_name: str | None = None
    # Roadmap PR28 (D4/D10): the checklist recorded on this event's side;
    # checklist_kind is the transaction's snapshot.
    checklist_kind: str | None = None
    checks: Checks | None = None
    # Roadmap PR28 (D11): cuffs of this transaction still outstanding (null
    # when it never issued cuffs).
    cuffs_outstanding: CuffCounts | None = None
    # Roadmap PR29 (D1): the transaction (``id``) has a patient HN recorded.
    has_hn: bool = False
