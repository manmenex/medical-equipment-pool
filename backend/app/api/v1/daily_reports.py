"""Roadmap PR30 (D5/D6/D12): daily shift summary workbook, printable daily
forms, and the admin ward -> report-row mapping.

Read-only reporting: nothing here touches dispatch/receipt write paths.
Access for the two downloads is Equipment Pool staff + Administrator
(`EQUIPMENT_POOL_OPERATION_ROLES`); the mapping edit is Administrator only.
"""

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, EQUIPMENT_POOL_OPERATION_ROLES, require_roles
from app.core.audit import AUDIT_ACTION_CREATE, AUDIT_ACTION_DELETE, AUDIT_ACTION_UPDATE, AUDIT_ENTITY_REPORT_WARD_ROW, record_audit_event
from app.core.exceptions import ExportTooLargeError, PdfRenderTimeoutError, ResourceNotFoundError, XlsxRenderTimeoutError
from app.core.reporting_time import business_date_and_shift
from app.db.session import get_db
from app.models.master_data import Department, Ward
from app.models.report_mapping import ReportWardRow
from app.services import (
    daily_report_forms_service,
    daily_report_service,
    daily_report_xlsx_service,
    report_export_service,
    standby_summary_service,
)
from app.utils.parsing import parse_uuid

router = APIRouter(prefix="/reports", tags=["daily-reports"])

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_IDENTITY_XLSX = SimpleNamespace(value="daily_summary")
_IDENTITY_FORMS = SimpleNamespace(value="daily_forms")


def _resolve_date(report_date: date | None) -> date:
    if report_date is not None:
        return report_date
    return business_date_and_shift(datetime.now(timezone.utc))[0]


async def _build(db: AsyncSession, report_date: date | None, grace_minutes: int):
    return await daily_report_service.build_daily_report(db, _resolve_date(report_date), grace_minutes)


@router.get("/daily-summary.xlsx")
async def get_daily_summary_xlsx(
    report_date: date | None = Query(default=None, alias="date"),
    grace_minutes: int = Query(default=daily_report_service.DEFAULT_GRACE_MINUTES),
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    timing = report_export_service.ExportTiming()
    report = None
    outcome = "error"
    try:
        report = await _build(db, report_date, grace_minutes)
        standby = await standby_summary_service.standby_by_label(db, report.report_date)
        content = await daily_report_xlsx_service.build_daily_workbook_bounded(report, standby)
    except ExportTooLargeError:
        outcome = "row_limit_exceeded"
        raise
    except XlsxRenderTimeoutError:
        outcome = "render_timeout"
        raise
    else:
        outcome = "success"
    finally:
        report_export_service.log_export_attempt(
            report_identity=_IDENTITY_XLSX,
            output_format="xlsx",
            actor_user_id=actor.id,
            outcome=outcome,
            row_count=len(report.events) if report else None,
            duration_ms=timing.elapsed_ms(),
        )
    filename = f"daily-summary-{report.report_date.isoformat()}.xlsx"
    return Response(content=content, media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/daily-forms.pdf")
async def get_daily_forms_pdf(
    report_date: date | None = Query(default=None, alias="date"),
    kind: Literal["dispatch", "receipt", "both"] = "both",
    grace_minutes: int = Query(default=daily_report_service.DEFAULT_GRACE_MINUTES),
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    timing = report_export_service.ExportTiming()
    report = None
    outcome = "error"
    try:
        report = await _build(db, report_date, grace_minutes)
        content = await daily_report_forms_service.render_forms_pdf_bounded(report, kind)
    except ExportTooLargeError:
        outcome = "row_limit_exceeded"
        raise
    except PdfRenderTimeoutError:
        outcome = "render_timeout"
        raise
    else:
        outcome = "success"
    finally:
        report_export_service.log_export_attempt(
            report_identity=_IDENTITY_FORMS,
            output_format="pdf",
            actor_user_id=actor.id,
            outcome=outcome,
            row_count=len(report.events) if report else None,
            duration_ms=timing.elapsed_ms(),
        )
    filename = f"daily-forms-{report.report_date.isoformat()}-{kind}.pdf"
    return Response(
        content=content, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ---------------------------------------------------------------- mapping admin


class WardRowOut(BaseModel):
    ward_id: uuid.UUID
    ward_name: str
    department_name: str | None
    report_row_label: str
    treatment_type: str
    dispense_mode: str
    sort_order: int
    is_override: bool


class WardRowUpdate(BaseModel):
    """Any field left null/blank falls back to the default (ward name /
    department name / blank). `sort_order` orders rows in the workbook."""

    report_row_label: str | None = Field(default=None, max_length=100)
    treatment_type: str | None = Field(default=None, max_length=100)
    dispense_mode: str | None = Field(default=None, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=100000)

    model_config = {"extra": "forbid"}

    @field_validator("report_row_label", "treatment_type", "dispense_mode")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


def _out(m: daily_report_service.WardMapping) -> WardRowOut:
    return WardRowOut(
        ward_id=m.ward_id,
        ward_name=m.ward_name,
        department_name=m.department_name,
        report_row_label=m.report_row_label,
        treatment_type=m.treatment_type,
        dispense_mode=m.dispense_mode,
        sort_order=m.sort_order,
        is_override=m.is_override,
    )


@router.get("/ward-rows", response_model=list[WardRowOut])
async def list_ward_rows(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Every ward with its effective report row (default or override)."""
    mappings = await daily_report_service.load_ward_mappings(db)
    return [_out(m) for m in mappings.values()]


@router.put("/ward-rows/{ward_id}", response_model=WardRowOut)
async def put_ward_row(
    ward_id: str,
    payload: WardRowUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    wid = parse_uuid(ward_id, "ward_id")
    ward = (await db.execute(select(Ward).where(Ward.id == wid))).scalar_one_or_none()
    if ward is None:
        raise ResourceNotFoundError("Ward not found")
    row = (await db.execute(select(ReportWardRow).where(ReportWardRow.ward_id == wid))).scalar_one_or_none()
    before = None
    action = AUDIT_ACTION_CREATE
    if row is None:
        row = ReportWardRow(ward_id=wid)
        db.add(row)
    else:
        action = AUDIT_ACTION_UPDATE
        before = payload_dict(row)
    row.report_row_label = payload.report_row_label
    row.treatment_type = payload.treatment_type
    row.dispense_mode = payload.dispense_mode
    row.sort_order = payload.sort_order
    await db.flush()
    await record_audit_event(
        db,
        actor_user_id=actor.id,
        action=action,
        entity_type=AUDIT_ENTITY_REPORT_WARD_ROW,
        entity_id=row.id,
        before=before,
        after=payload_dict(row),
        request=request,
    )
    await db.commit()
    department = (
        await db.execute(select(Department).where(Department.id == ward.department_id))
    ).scalar_one_or_none() if ward.department_id else None
    return _out(daily_report_service.effective_mapping(ward, department, row))


def payload_dict(row: ReportWardRow) -> dict:
    return {
        "ward_id": str(row.ward_id),
        "report_row_label": row.report_row_label,
        "treatment_type": row.treatment_type,
        "dispense_mode": row.dispense_mode,
        "sort_order": row.sort_order,
    }


@router.delete("/ward-rows/{ward_id}", status_code=204)
async def reset_ward_row(
    ward_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    """Remove the override; the ward reverts to its defaults."""
    wid = parse_uuid(ward_id, "ward_id")
    row = (await db.execute(select(ReportWardRow).where(ReportWardRow.ward_id == wid))).scalar_one_or_none()
    if row is None:
        raise ResourceNotFoundError("No report-row override for this ward")
    before = payload_dict(row)
    entity_id = row.id
    await db.delete(row)
    await record_audit_event(
        db,
        actor_user_id=actor.id,
        action=AUDIT_ACTION_DELETE,
        entity_type=AUDIT_ENTITY_REPORT_WARD_ROW,
        entity_id=entity_id,
        before=before,
        request=request,
    )
    await db.commit()
    return Response(status_code=204)
