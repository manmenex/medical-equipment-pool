import asyncio
import json
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.v1.deps import bearer_scheme, get_current_user
from app.core.security import decode_token
from app.db.session import AsyncSessionLocal, get_db
from app.models.user import User
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


async def get_current_user_for_stream(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    """Authenticate the SSE stream caller without depending on app.api.v1.deps.get_db.

    Applies the same checks as get_current_user (valid access token, active
    user) but resolves the user through its own short-lived session opened
    and closed here, so no dependency-injected session survives past this
    function into the StreamingResponse's body_iterator, which otherwise
    stays alive for the entire connection.
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


@router.get("/stream")
async def stream(_user: User = Depends(get_current_user_for_stream)):
    async def event_generator():
        while True:
            async with AsyncSessionLocal() as session:
                data = await dashboard_service.get_summary(session)
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
