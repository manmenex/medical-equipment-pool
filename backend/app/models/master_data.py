import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import UUIDPKMixin


class Department(UUIDPKMixin, Base):
    __tablename__ = "departments"
    # Roadmap PR15B (docs/archive/design/PR15B_SCHEMA_HYGIENE_PLAN.md §6.4): an
    # explicit name converges this column's constraint on the same
    # `uq_<table>_<column>` convention migration 0014 renames the
    # PostgreSQL-catalog constraint to, instead of leaving `unique=True`
    # produce PostgreSQL's own unnamed default (`departments_code_key`).
    __table_args__ = (UniqueConstraint("code", name="uq_departments_code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # Roadmap PR25E slice B0 (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md 3.4):
    # optional contact phone of the department; fallback source for the
    # dispatch form's phone_number. Same 20-char cap as
    # borrow_transactions.phone_number. Not a personal number.
    phone: Mapped[str | None] = mapped_column(String(20))

    wards: Mapped[list["Ward"]] = relationship(back_populates="department")


class Ward(UUIDPKMixin, Base):
    __tablename__ = "wards"
    __table_args__ = (UniqueConstraint("code", name="uq_wards_code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("departments.id", ondelete="RESTRICT")
    )
    # Roadmap PR25E slice B0: optional ward contact phone (primary source for
    # the dispatch form's phone_number prefill). Nullable, no default.
    phone: Mapped[str | None] = mapped_column(String(20))

    department: Mapped["Department | None"] = relationship(back_populates="wards")


class Location(UUIDPKMixin, Base):
    __tablename__ = "locations"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50))


class EquipmentCategory(UUIDPKMixin, Base):
    __tablename__ = "equipment_categories"
    __table_args__ = (UniqueConstraint("name", name="uq_equipment_categories_name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    default_pm_interval_days: Mapped[int | None] = mapped_column(Integer)
    default_cal_interval_days: Mapped[int | None] = mapped_column(Integer)
