from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.equipment import EquipmentStatus


class EquipmentBase(BaseModel):
    # Governance 2026-10-21: optional. A blank/whitespace value is treated as
    # "not supplied" (None); a non-blank value is trimmed, never fabricated.
    asset_number: str | None = Field(default=None, min_length=1, max_length=50)
    serial_number: str | None = Field(default=None, max_length=100)
    equipment_name: str = Field(min_length=1, max_length=255)
    category_id: str | None = None
    brand: str | None = None
    model: str | None = None
    department_owner_id: str | None = None
    current_location_id: str | None = None
    pm_due_date: date | None = None
    cal_due_date: date | None = None
    # bcm_code is the operator-facing identifier the manual-search endpoint
    # matches against (See ADR-002, ADR-003). Optional -- existing
    # equipment predates this field.
    bcm_code: str | None = Field(default=None, max_length=64)

    @field_validator("asset_number", mode="before")
    @classmethod
    def _blank_asset_number_is_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class EquipmentCreate(EquipmentBase):
    # item_no is a write-only field (See ADR-002: the internal
    # QR-resolution key, structurally ready for a future controlled Excel
    # import, Roadmap PR12). It is settable here but deliberately absent
    # from EquipmentOut below -- see knowledge/architecture/
    # api-information-boundaries.md.
    item_no: str | None = Field(default=None, max_length=64)


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
    # Matches EquipmentCreate's bounds exactly (See PR5-H3R: create and
    # update must apply identical validation, not just identical
    # normalization) -- the final post-normalization bound is enforced
    # separately in app.services.identifiers, since a prefixless BCM Code
    # only becomes overlength once "BCM" is prepended, after schema
    # validation has already run.
    item_no: str | None = Field(default=None, max_length=64)
    bcm_code: str | None = Field(default=None, max_length=64)

    # Roadmap PR91-H1 (docs/archive/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md
    # §24): the same `extra: "forbid"` technique Roadmap PR7b/PR8B/PR9A
    # already established for BorrowRequest/ReturnRequest/
    # WardCorrectionRequest (app.schemas.transaction) -- a caller sending
    # `version` (or any other field this schema does not declare) gets a
    # hard 422 via FastAPI's own centralized validation-error handling,
    # never a silently-ignored field. `version` is deliberately not
    # declared as a field on this schema at all -- it is exposed read-only
    # on EquipmentOut only and must never be settable through a write
    # request.
    model_config = {"extra": "forbid"}


class EquipmentStatusChange(BaseModel):
    status: EquipmentStatus
    reason: str | None = None


class EquipmentOut(EquipmentBase):
    """Operator-facing equipment response. Deliberately excludes item_no
    (See ADR-002 / ADR-003 -- knowledge/architecture/
    api-information-boundaries.md) and the retired legacy qr_code_value
    (See ADR-004).
    """

    id: str
    status: EquipmentStatus
    created_at: datetime
    updated_at: datetime
    # Roadmap PR20B (docs/archive/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §24):
    # read-only optimistic-concurrency counter, exposed for client-side
    # observability/debugging only (e.g. an admin noticing a record changed
    # between two screen loads) -- never accepted as input by
    # EquipmentCreate/EquipmentUpdate/EquipmentStatusChange, and not itself
    # a client-driven CAS mechanism in this slice.
    version: int
    # Roadmap PR33 (D14): demo/loan metadata. For demo/loan devices `bcm_code`
    # holds the manufacturer serial number.
    equipment_source: str = "pool"
    owner_company: str | None = None
    due_back_date: date | None = None
    has_charger: bool = True
    has_clamp: bool = True
    returned_to_owner_at: datetime | None = None

    model_config = {"from_attributes": True}


class DemoLoanShared(BaseModel):
    """Roadmap PR33 (D14): fields shared by every row of a demo/loan batch."""

    category_id: str
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    equipment_name: str | None = Field(default=None, max_length=255)
    equipment_source: Literal["demo", "loan"]
    owner_company: str = Field(min_length=1, max_length=255)
    due_back_date: date | None = None

    model_config = {"extra": "forbid"}

    @field_validator("owner_company", mode="before")
    @classmethod
    def _trim_owner(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("brand", "model", "equipment_name", mode="before")
    @classmethod
    def _blank_is_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class DemoLoanItem(BaseModel):
    serial_number: str = Field(max_length=200)
    has_charger: bool = True
    has_clamp: bool = True

    model_config = {"extra": "forbid"}


DEMO_LOAN_BATCH_MAX_ITEMS = 200


class DemoLoanBatchRequest(BaseModel):
    shared: DemoLoanShared
    items: list[DemoLoanItem] = Field(min_length=1, max_length=DEMO_LOAN_BATCH_MAX_ITEMS)
    # Validate-only mode: nothing is written. Commit mode (default) is
    # all-or-nothing.
    dry_run: bool = False

    model_config = {"extra": "forbid"}


class DemoLoanRowResult(BaseModel):
    index: int
    serial_number: str
    # Machine-readable codes: blank | invalid_serial | duplicate_in_batch | duplicate_in_db
    errors: list[str] = []
    messages: list[str] = []


class DemoLoanBatchOut(BaseModel):
    dry_run: bool
    valid: bool
    committed: bool
    total: int
    created_count: int
    rows: list[DemoLoanRowResult]
    created: list[EquipmentOut] = []


class EquipmentStatusHistoryOut(BaseModel):
    id: str
    from_status: str | None
    to_status: str
    reason: str | None
    changed_at: datetime

    model_config = {"from_attributes": True}


class BcmSuggestion(BaseModel):
    """Manual-search suggestion: the minimum data needed to identify and
    select a result (See ADR-003). Deliberately excludes item_no, device
    name, brand, model, serial number, and status.
    """

    id: str
    bcm_code: str

    model_config = {"from_attributes": True}


class QrResolveRequest(BaseModel):
    """The raw, as-scanned QR payload (See ADR-004). Validation of its
    *content* (empty, too long, URL-shaped, retired legacy format) happens
    in app.services.qr_service.extract_item_no_from_qr, not here, so every
    malformed case reaches the client through the same MalformedQrCodeError
    response shape regardless of which specific check caught it.
    """

    raw_value: str
