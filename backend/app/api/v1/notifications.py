import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.notification import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str | None
    is_read: bool
    created_at: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[NotificationOut])
async def list_notifications(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await db.execute(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50)
    )
    notifications = result.scalars().all()
    return [
        NotificationOut(
            id=str(n.id), type=n.type, title=n.title, body=n.body, is_read=n.is_read, created_at=n.created_at.isoformat()
        )
        for n in notifications
    ]


@router.post("/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    notification = await db.get(Notification, notification_id)
    if notification and notification.user_id == user.id:
        notification.is_read = True
        await db.commit()
    return {"detail": "ok"}
