from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import VIEW_AND_REPORT_ROLES, require_roles
from app.crud import user as user_crud
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.report_options import ReportOperatorOut

router = APIRouter(prefix="/report-options", tags=["report-options"])


@router.get("/operators", response_model=Page[ReportOperatorOut])
async def list_report_operators(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, le=200),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
    # Roadmap PR17 Slice 2 (docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md
    # §10.4/§14): deliberately VIEW_AND_REPORT_ROLES, not
    # ADMINISTRATOR_ONLY_ROLES (which gates the existing GET /users) --
    # Equipment Pool Staff and Read Only, both authorized to view the
    # Receive/Issue reports, need this lookup to use the operator_id filter
    # at all.
    _user=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    rows, next_cursor, total = await user_crud.list_operators(db, q=q, limit=limit, cursor=cursor)
    items = [
        ReportOperatorOut(id=str(row.id), display_name=row.full_name, is_active=row.is_active) for row in rows
    ]
    return Page(items=items, next_cursor=next_cursor, total=total)
