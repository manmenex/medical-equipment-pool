from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import ADMINISTRATOR_ONLY_ROLES, require_roles
from app.db.session import get_db
from app.services import health_alert_service

router = APIRouter(prefix="/system", tags=["system"])


class HealthAlert(BaseModel):
    code: str
    severity: str
    message_th: str
    since: datetime | None = None


@router.get("/health-alerts", response_model=list[HealthAlert])
async def health_alerts(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES)),
):
    return await health_alert_service.compute_alerts(db)
