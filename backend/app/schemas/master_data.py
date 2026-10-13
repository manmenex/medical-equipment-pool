import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.schemas.common import UUIDStr

# Roadmap PR10: a closed, generated-OpenAPI-enum type for the 3 confirmed
# role values -- a request naming a retired legacy role (or any other
# unrecognized string) is now rejected at the schema layer with the
# standard 422 VALIDATION_ERROR envelope, not silently accepted and only
# later discovered to be unknown by the runtime `get_role_by_name` lookup.
RoleName = Literal[ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY]


# Roadmap PR25E slice B0: a ward/department contact phone. Digits, spaces and
# dashes, an optional leading '+', and an optional extension ("ext 123",
# "ext. 123" or "x123"). At most 20 characters (the borrow_transactions
# .phone_number cap) and at least 3 digits. Blank input is stored as NULL.
PHONE_MAX_LENGTH = 20
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 -]*(?: ?(?:ext\.?|x) ?[0-9]{1,6})?$", re.IGNORECASE | re.ASCII)


def _validate_contact_phone(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > PHONE_MAX_LENGTH:
        raise ValueError(f"phone must be at most {PHONE_MAX_LENGTH} characters")
    if not _PHONE_RE.fullmatch(value) or sum(c in "0123456789" for c in value) < 3:
        raise ValueError("phone may contain only digits, spaces, dashes, a leading '+' and an extension (ext/x)")
    return value


ContactPhone = Annotated[str | None, AfterValidator(_validate_contact_phone)]


class DepartmentOut(BaseModel):
    id: UUIDStr
    code: str
    name: str
    phone: str | None = None

    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    code: str
    name: str
    phone: ContactPhone = None


class WardOut(BaseModel):
    id: UUIDStr
    code: str
    name: str
    department_id: UUIDStr | None
    phone: str | None = None

    model_config = {"from_attributes": True}


class WardCreate(BaseModel):
    code: str
    name: str
    department_id: str | None = None
    phone: ContactPhone = None


class PhoneUpdate(BaseModel):
    """PATCH body for a ward/department: `phone` only. Any other field is a
    422; null or blank clears the phone."""

    phone: ContactPhone = None

    model_config = {"extra": "forbid"}


WARD_PHONE_IMPORT_MAX_ROWS = 500


class WardPhoneImportRow(BaseModel):
    ward_name: str
    phone: str | None = None


class WardPhoneImportRequest(BaseModel):
    rows: list[WardPhoneImportRow] = Field(min_length=1, max_length=WARD_PHONE_IMPORT_MAX_ROWS)

    model_config = {"extra": "forbid"}


class WardPhoneImportRowResult(BaseModel):
    row: int
    ward_name: str
    phone: str | None
    outcome: str
    ward_id: str | None = None
    current_phone: str | None = None
    detail: str | None = None


class WardPhoneImportResponse(BaseModel):
    dry_run: bool
    overwrite: bool
    applied: bool
    counts: dict[str, int]
    results: list[WardPhoneImportRowResult]


class LocationOut(BaseModel):
    id: UUIDStr
    name: str
    type: str | None

    model_config = {"from_attributes": True}


class LocationCreate(BaseModel):
    name: str
    type: str | None = None


class CategoryOut(BaseModel):
    id: UUIDStr
    name: str
    default_pm_interval_days: int | None
    default_cal_interval_days: int | None

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    name: str
    default_pm_interval_days: int | None = None
    default_cal_interval_days: int | None = None


class UserOut(BaseModel):
    id: str
    employee_code: str
    full_name: str
    email: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    employee_code: str
    full_name: str
    email: str
    phone: str | None = None
    password: str
    role_name: RoleName


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    role_name: RoleName | None = None
    is_active: bool | None = None
    password: str | None = None
