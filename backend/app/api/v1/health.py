from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    redis_status = "ok"
    try:
        await get_redis().ping()
    except Exception:
        redis_status = "error"

    return {"status": "ok", "db": db_status, "redis": redis_status}
