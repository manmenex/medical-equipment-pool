import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import UUIDPKMixin

JSONType = JSONB().with_variant(JSON(), "sqlite")


class Notification(UUIDPKMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # pm | calibration | overdue | broken
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)
