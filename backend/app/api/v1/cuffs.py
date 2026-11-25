"""Roadmap PR28 (D11): outstanding Cryo-Cuff cuffs, by ward. Read-only."""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import EQUIPMENT_POOL_OPERATION_ROLES, require_roles
from app.db.session import get_db
from app.schemas.checklist import CuffCounts
from app.services import cuff_service
from app.utils.parsing import parse_uuid

from datetime import datetime

router = APIRouter(prefix="/cuffs", tags=["cuffs"])


class OutstandingCuffTransaction(BaseModel):
    transaction_id: str
    transaction_no: str
    equipment_id: str
    bcm_code: str | None
    equipment_name: str
    dispatched_at: datetime
    # False while the device itself is still out on this transaction.
    device_received: bool
    cuffs: CuffCounts


class OutstandingCuffWard(BaseModel):
    ward_id: str | None
    ward_name: str | None
    cuffs: CuffCounts
    total: int
    transactions: list[OutstandingCuffTransaction]


class OutstandingCuffsOut(BaseModel):
    items: list[OutstandingCuffWard]
    total_outstanding: int


@router.get("/outstanding", response_model=OutstandingCuffsOut)
async def outstanding_cuffs(
    ward_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(*EQUIPMENT_POOL_OPERATION_ROLES)),
):
    ward_uuid: uuid.UUID | None = parse_uuid(ward_id, "ward_id")
    return await cuff_service.outstanding_by_ward(db, ward_id=ward_uuid)
