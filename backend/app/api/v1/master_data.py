from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_roles
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

router = APIRouter(tags=["master-data"])


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await md_crud.list_departments(db)


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(
    payload: DepartmentCreate, db: AsyncSession = Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))
):
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
    obj = await md_crud.create_ward(db, code=payload.code, name=payload.name, department_id=payload.department_id)
    await db.commit()
    return obj


@router.get("/locations", response_model=list[LocationOut])
async def list_locations(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await md_crud.list_locations(db)


@router.post("/locations", response_model=LocationOut, status_code=201)
async def create_location(
    payload: LocationCreate, db: AsyncSession = Depends(get_db), _user=Depends(require_roles(ROLE_ADMIN))
):
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
    obj = await md_crud.create_category(
        db,
        name=payload.name,
        default_pm_interval_days=payload.default_pm_interval_days,
        default_cal_interval_days=payload.default_cal_interval_days,
    )
    await db.commit()
    return obj
