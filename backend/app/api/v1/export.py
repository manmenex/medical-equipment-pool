"""Roadmap PR25B -- read-only export API for an external consumer
(Nsmart Realtime). Authenticated by a dedicated machine key in ``X-API-Key``;
a human bearer token is not accepted here, and a machine key is not accepted
anywhere else. This system never calls the consumer."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ExportCursorAheadError
from app.db.session import get_db
from app.schemas.export import ExportCursorOut, ExportEventsPage
from app.services import export_service

router = APIRouter(prefix="/export", tags=["export"])


async def require_export_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
):
    # One message for missing / unknown / revoked: no oracle for key guessing.
    row = await export_service.authenticate_key(db, x_api_key) if x_api_key else None
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return row


@router.get("/events", response_model=ExportEventsPage)
async def list_events(
    after: int = Query(0, ge=0, description="seq of the last event already processed; 0 = from the beginning"),
    limit: int = Query(export_service.DEFAULT_PAGE_SIZE, ge=1, le=export_service.MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    _key=Depends(require_export_key),
):
    # Head is read before the page; events only ever append, so a cursor that
    # is <= head here is valid regardless of commits that land in between.
    if after > 0 and after > await export_service.head_seq(db):
        raise ExportCursorAheadError(
            "The cursor is newer than any event in this database. The database may have been restored "
            "from a backup; re-seed the consumer from GET /export/cursor."
        )
    events, has_more = await export_service.query_events(db, after=after, limit=limit)
    next_cursor = events[-1]["seq"] if events else after
    return ExportEventsPage(events=events, next_cursor=next_cursor, has_more=has_more)


@router.get("/cursor", response_model=ExportCursorOut)
async def get_cursor(
    at: datetime | None = Query(None, description="Return the cursor from which events at/after this instant follow"),
    db: AsyncSession = Depends(get_db),
    _key=Depends(require_export_key),
):
    """Starting point for a new consumer: no ``at`` means "from now" (only
    events recorded after this call); with ``at``, events from that instant."""
    if at is None:
        return ExportCursorOut(cursor=await export_service.head_seq(db))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return ExportCursorOut(cursor=await export_service.cursor_for_time(db, at))
