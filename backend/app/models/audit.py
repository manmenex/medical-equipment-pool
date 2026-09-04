import uuid
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import UTCDateTime, UUIDPKMixin

JSONType = JSONB().with_variant(JSON(), "sqlite")


class AuditLog(UUIDPKMixin, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    before_data: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    # Roadmap PR15B (docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md §3.4/§3.5): the
    # column and its default were bespoke rather than following
    # TimestampMixin's DateTime(timezone=True) + server_default=func.now()
    # pattern -- naive `timestamp without time zone` with a client-computed
    # `datetime.utcnow()` default. Every existing row's stored value is
    # already a UTC wall-clock instant (confirmed write history), so
    # migration 0012_timezone_conversion.py attaches that evidence-backed
    # label via `AT TIME ZONE 'UTC'` rather than reinterpreting an ambiguous
    # value. `datetime.now(timezone.utc)` replaces `datetime.utcnow()` so
    # new rows are written as timezone-aware from the start.
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )
