from typing import Literal

from pydantic import BaseModel

from app.models.user import ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from app.schemas.common import UUIDStr

# Roadmap PR10: a closed, generated-OpenAPI-enum type for the 3 confirmed
# role values -- a request naming a retired legacy role (or any other
# unrecognized string) is now rejected at the schema layer with the
# standard 422 VALIDATION_ERROR envelope, not silently accepted and only
# later discovered to be unknown by the runtime `get_role_by_name` lookup.
RoleName = Literal[ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY]


class DepartmentOut(BaseModel):
    id: UUIDStr
    code: str
    name: str

    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    code: str
    name: str


class WardOut(BaseModel):
    id: UUIDStr
    code: str
    name: str
    department_id: UUIDStr | None

    model_config = {"from_attributes": True}


class WardCreate(BaseModel):
    code: str
    name: str
    department_id: str | None = None


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
