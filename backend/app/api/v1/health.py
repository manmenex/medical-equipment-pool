from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.db.session import get_db
from app.schemas.health import ReadinessOut

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Liveness/diagnostic only -- always HTTP 200 regardless of the `db`/
    `redis` field values. NOT a safe readiness probe: see `GET /ready`
    (`docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §15A)."""
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


@router.get("/ready", response_model=ReadinessOut, responses={503: {"model": ReadinessOut}})
async def ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Fail-closed production readiness probe
    (`docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §15A,
    PR24B). PostgreSQL is the sole readiness-blocking dependency: a
    failure returns HTTP 503 so status-code-only platform probes route
    traffic away from this instance. Redis is reported but never blocks
    readiness -- see `ReadinessOut.redis`'s own docstring for why.

    Unauthenticated by design, matching the existing `/health` endpoint's
    own precedent: production readiness probes are invoked by the
    deployment platform itself, before any user session exists, so an
    auth requirement here would make this endpoint unusable for its own
    purpose. The response never includes a database/Redis URL,
    credential, host, or raw exception text -- only the fixed three-value
    enum shape in `ReadinessOut`.
    """
    database_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    redis_ok = True
    try:
        await get_redis().ping()
    except Exception:
        redis_ok = False

    body = ReadinessOut(
        status="ready" if database_ok else "not_ready",
        database="ok" if database_ok else "error",
        redis="ok" if redis_ok else "degraded",
    )
    return JSONResponse(status_code=200 if database_ok else 503, content=body.model_dump())
