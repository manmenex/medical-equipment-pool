import asyncio
import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.schemas.dashboard import BorrowTrendPoint, DashboardSummary, TopBorrowedItem
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def summary(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await dashboard_service.get_summary(db)


@router.get("/borrow-trend", response_model=list[BorrowTrendPoint])
async def borrow_trend(range: int = 30, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await dashboard_service.get_borrow_trend(db, days=range)


@router.get("/top-borrowed", response_model=list[TopBorrowedItem])
async def top_borrowed(limit: int = 10, db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    return await dashboard_service.get_top_borrowed(db, limit=limit)


@router.get("/stream")
async def stream(db: AsyncSession = Depends(get_db), _user=Depends(get_current_user)):
    async def event_generator():
        while True:
            data = await dashboard_service.get_summary(db)
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
