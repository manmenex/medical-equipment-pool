import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

JSONType = JSONB().with_variant(JSON(), "sqlite")

ROLE_ADMIN = "admin"
ROLE_BIOMEDICAL_ENGINEER = "biomedical_engineer"
ROLE_WARD_NURSE = "ward_nurse"
ROLE_TRANSPORT_STAFF = "transport_staff"
ROLE_VIEWER = "viewer"

ALL_ROLES = [ROLE_ADMIN, ROLE_BIOMEDICAL_ENGINEER, ROLE_WARD_NURSE, ROLE_TRANSPORT_STAFF, ROLE_VIEWER]


class Role(UUIDPKMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    permissions: Mapped[dict] = mapped_column(JSONType, default=dict)

    users: Mapped[list["User"]] = relationship(back_populates="role")


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    employee_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped["Role"] = relationship(back_populates="users")
