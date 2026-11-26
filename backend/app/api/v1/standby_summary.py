"""Roadmap PR34 (Owner Governance 2026-11-26 D16): standby summary API.

Equipment Pool staff + Administrator for everything except the category
mapping (Administrator only). No patient data: the summary only distinguishes
has-HN from no-HN inside the counts.
"""
import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import PlainTextResponse

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, EQUIPMENT_POOL_OPERATION_ROLES, require_roles
from app.db.session import get_db
from app.services import standby_summary_service as svc

router = APIRouter(prefix="/standby-summary", tags=["standby-summary"])

Cutoff = Literal["night", "day"]
Role = Literal["infusion", "pneumatic"]


class FieldOut(BaseModel):
    key: str
    label: str
    system_value: int | None
    override_value: int | None
    effective_value: int | None
    mode: str | None = None
    treatment: str | None = None


class BaselineOut(BaseModel):
    chargers: int | None
    clamps: int | None
    set_at: datetime | None


class InfusionOut(BaseModel):
    categories: list[str]
    wards: list[FieldOut]
    bme_devices: FieldOut
    chargers: FieldOut
    clamps: FieldOut
    ready: FieldOut
    baseline: BaselineOut


class PneumaticOut(BaseModel):
    categories: list[str]
    in_use: FieldOut
    returned: FieldOut


class SummaryOut(BaseModel):
    date: date
    cutoff: Cutoff
    cutoff_at: datetime
    business_day_start: datetime
    infusion: InfusionOut
    pneumatic: PneumaticOut
    approximations: list[str]


def _field(f: svc.FieldValue) -> FieldOut:
    return FieldOut(
        key=f.key,
        label=f.label,
        system_value=f.system_value,
        override_value=f.override_value,
        effective_value=f.effective_value,
        mode=f.mode,
        treatment=f.treatment,
    )


def _out(s: svc.StandbySummary) -> SummaryOut:
    return SummaryOut(
        date=s.summary_date,
        cutoff=s.cutoff,  # type: ignore[arg-type]
        cutoff_at=s.cutoff_at,
        business_day_start=s.business_day_start,
        infusion=InfusionOut(
            categories=s.infusion_categories,
            wards=[_field(w) for w in s.wards],
            bme_devices=_field(s.bme_devices),
            chargers=_field(s.chargers),
            clamps=_field(s.clamps),
            ready=_field(s.ready),
            baseline=BaselineOut(chargers=s.baseline.chargers, clamps=s.baseline.clamps, set_at=s.baseline.set_at),
        ),
        pneumatic=PneumaticOut(
            categories=s.pneumatic_categories,
            in_use=_field(s.pneumatic_in_use),
            returned=_field(s.pneumatic_returned),
        ),
        approximations=svc.APPROXIMATIONS,
    )


@router.get("", response_model=SummaryOut)
async def get_standby_summary(
    summary_date: date = Query(alias="date"),
    cutoff: Cutoff = "night",
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    """Night = 08:00 on the date, Day = 20:00 on the date (Asia/Bangkok)."""
    return _out(await svc.build_summary(db, summary_date, cutoff))


@router.get("/text", response_class=PlainTextResponse)
async def get_standby_summary_text(
    summary_date: date = Query(alias="date"),
    cutoff: Cutoff = "night",
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    """The Owner's LINE-style message built from the effective values."""
    return PlainTextResponse(svc.render_text(await svc.build_summary(db, summary_date, cutoff)))


class OverrideIn(BaseModel):
    date: date
    cutoff: Cutoff
    field_key: str = Field(min_length=1, max_length=120)
    # null removes the edit (the system value applies again).
    value: int | None = Field(default=None, ge=0, le=svc.MAX_OVERRIDE_VALUE)

    model_config = {"extra": "forbid"}


@router.put("/overrides", response_model=SummaryOut)
async def put_override(
    payload: OverrideIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    await svc.set_override(
        db,
        summary_date=payload.date,
        cutoff=payload.cutoff,
        field_key=payload.field_key,
        value=payload.value,
        actor_user_id=actor.id,
        request=request,
    )
    return _out(await svc.build_summary(db, payload.date, payload.cutoff))


class BaselineIn(BaseModel):
    category_role: Role = "infusion"
    chargers: int = Field(ge=0, le=svc.MAX_OVERRIDE_VALUE)
    clamps: int = Field(ge=0, le=svc.MAX_OVERRIDE_VALUE)

    model_config = {"extra": "forbid"}


@router.put("/baseline", response_model=BaselineOut)
async def put_baseline(
    payload: BaselineIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    """Charger/clamp stock at the pool as of now; the system moves it from here."""
    cfg = await svc.set_baseline(
        db,
        category_role=payload.category_role,
        chargers=payload.chargers,
        clamps=payload.clamps,
        actor_user_id=actor.id,
        request=request,
    )
    return BaselineOut(chargers=cfg.chargers, clamps=cfg.clamps, set_at=cfg.baseline_set_at)


class CategoryIn(BaseModel):
    category_role: Role
    # null = default name match (/infusion/i, /pneumatic/i).
    category_id: uuid.UUID | None = None

    model_config = {"extra": "forbid"}


class CategoryOutResp(BaseModel):
    category_role: Role
    category_id: uuid.UUID | None


@router.put("/categories", response_model=CategoryOutResp)
async def put_category(
    payload: CategoryIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Administrator: which equipment category is "Infusion pump" / "Pneumatic pump"."""
    cfg = await svc.set_category(
        db,
        category_role=payload.category_role,
        category_id=payload.category_id,
        actor_user_id=actor.id,
        request=request,
    )
    return CategoryOutResp(category_role=cfg.category_role, category_id=cfg.category_id)  # type: ignore[arg-type]
