import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import UUIDPKMixin


class Department(UUIDPKMixin, Base):
    __tablename__ = "departments"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)

    wards: Mapped[list["Ward"]] = relationship(back_populates="department")


class Ward(UUIDPKMixin, Base):
    __tablename__ = "wards"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))

    department: Mapped["Department | None"] = relationship(back_populates="wards")


class Location(UUIDPKMixin, Base):
    __tablename__ = "locations"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[str | None] = mapped_column(String(50))


class EquipmentCategory(UUIDPKMixin, Base):
    __tablename__ = "equipment_categories"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    default_pm_interval_days: Mapped[int | None] = mapped_column(Integer)
    default_cal_interval_days: Mapped[int | None] = mapped_column(Integer)
