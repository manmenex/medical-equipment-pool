from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.v1.deps import VIEW_AND_REPORT_ROLES, require_roles
from app.db.session import get_db
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/export")
async def export_report(
    format: str = Query(default="xlsx", pattern="^(xlsx|csv)$"),
    db: AsyncSession = Depends(get_db),
    # Roadmap PR10: this export surface already existed for admin, viewer,
    # and biomedical_engineer pre-PR10 -- preserved at the same breadth for
    # all three new roles, not narrowed and not newly added.
    _user=Depends(require_roles(*VIEW_AND_REPORT_ROLES)),
):
    if format == "csv":
        content = await report_service.export_csv(db)
        media_type = "text/csv"
        filename = "borrow_report.csv"
    else:
        content = await report_service.export_xlsx(db)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "borrow_report.xlsx"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
