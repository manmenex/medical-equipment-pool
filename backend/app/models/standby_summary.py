"""Roadmap PR34 (Owner Governance 2026-11-26 D16): standby summary storage.

- ``StandbySummaryOverride``: a staff-edited value for one number of one
  summary (date + cut-off). The system value is always recomputed; the edit is
  stored beside it, never in place of it.
- ``StandbySummaryConfig``: per summary role (``infusion`` | ``pneumatic``)
  the optional explicit equipment category (NULL = default name match) and the
  staff-entered charger/clamp baseline with the instant it was set.

No patient data of any kind lives here.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UTCDateTime, UUIDPKMixin

ROLE_INFUSION = "infusion"
ROLE_PNEUMATIC = "pneumatic"
STANDBY_ROLES = (ROLE_INFUSION, ROLE_PNEUMATIC)
CUTOFFS = ("night", "day")


class StandbySummaryOverride(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "standby_summary_overrides"
    __table_args__ = (
        UniqueConstraint("summary_date", "cutoff", "field_key", name="uq_standby_override_key"),
        CheckConstraint("cutoff IN ('night', 'day')", name="ck_standby_override_cutoff"),
        CheckConstraint("value >= 0", name="ck_standby_override_value"),
    )

    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    cutoff: Mapped[str] = mapped_column(String(5), nullable=False)
    section: Mapped[str] = mapped_column(String(20), nullable=False)  # infusion | pneumatic
    field_key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    edited_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class StandbySummaryConfig(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "standby_summary_config"
    __table_args__ = (
        UniqueConstraint("category_role", name="uq_standby_config_role"),
        CheckConstraint("category_role IN ('infusion', 'pneumatic')", name="ck_standby_config_role"),
        CheckConstraint("chargers IS NULL OR chargers >= 0", name="ck_standby_config_chargers"),
        CheckConstraint("clamps IS NULL OR clamps >= 0", name="ck_standby_config_clamps"),
    )

    category_role: Mapped[str] = mapped_column(String(20), nullable=False)
    # NULL = default: every category whose name matches the role's pattern.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment_categories.id", ondelete="RESTRICT")
    )
    # Charger/clamp stock at the pool at ``baseline_set_at`` (infusion only).
    chargers: Mapped[int | None] = mapped_column(Integer)
    clamps: Mapped[int | None] = mapped_column(Integer)
    baseline_set_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    baseline_set_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
