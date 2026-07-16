from pydantic import BaseModel

from app.schemas.common import UUIDStr


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
    role_name: str


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    role_name: str | None = None
    is_active: bool | None = None
    password: str | None = None
