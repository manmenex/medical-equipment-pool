from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_roles
from app.core.db_errors import translate_integrity_error
from app.crud import master_data as md_crud
from app.db.session import get_db
from app.models.user import ROLE_ADMIN
from app.schemas.master_data import (
    CategoryCreate,
    CategoryOut,
    DepartmentCreate,
    DepartmentOut,
    LocationCreate,
    LocationOut,
    WardCreate,
    WardOut,
)
from app.utils.parsing import parse_uuid

router = APIRouter(tags=["master-data"])


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await md_crud.list_departments(db)


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(
    payload: DepartmentCreate, db: AsyncSession = Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))
):
    async with translate_integrity_error(db, "A department with this code already exists."):
        obj = await md_crud.create_department(db, code=payload.code, name=payload.name)
    await db.commit()
    return obj


@router.get("/wards", response_model=list[WardOut])
async def list_wards(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await md_crud.list_wards(db)


@router.post("/wards", response_model=WardOut, status_code=201)
async def create_ward(
    payload: WardCreate, db: AsyncSession = Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))
):
    department_id = parse_uuid(payload.department_id, "department_id")
    async with translate_integrity_error(
        db, "Unable to create ward: the code may already be in use, or the referenced department does not exist."
    ):
        obj = await md_crud.create_ward(db, code=payload.code, name=payload.name, department_id=department_id)
    await db.commit()
    return obj


@router.get("/locations", response_model=list[LocationOut])
async def list_locations(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await md_crud.list_locations(db)


@router.post("/locations", response_model=LocationOut, status_code=201)
async def create_location(
    payload: LocationCreate, db: AsyncSession = Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))
):
    # Location has no unique constraint in the current schema (see PR2 known
    # limitations); this wrapper is defense-in-depth against NOT NULL/other
    # integrity failures, not a guarantee of duplicate-location detection.
    async with translate_integrity_error(db, "Unable to create location."):
        obj = await md_crud.create_location(db, name=payload.name, type_=payload.type)
    await db.commit()
    return obj


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await md_crud.list_categories(db)


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    payload: CategoryCreate, db: AsyncSession = Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))
):
    async with translate_integrity_error(db, "A category with this name already exists."):
        obj = await md_crud.create_category(
            db,
            name=payload.name,
            default_pm_interval_days=payload.default_pm_interval_days,
            default_cal_interval_days=payload.default_cal_interval_days,
        )
    await db.commit()
    return obj
