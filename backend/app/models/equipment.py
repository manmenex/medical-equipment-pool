import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDPKMixin

JSONType = JSONB().with_variant(JSON(), "sqlite")


class EquipmentStatus(str, enum.Enum):
    AVAILABLE = "available"
    BORROWED = "borrowed"
    CLEANING = "cleaning"
    PM = "pm"
    CALIBRATION = "calibration"
    REPAIR = "repair"
    OUT_OF_SERVICE = "out_of_service"
    LOST = "lost"


EquipmentStatusType = Enum(EquipmentStatus, name="equipment_status", native_enum=False, length=30)


class Equipment(UUIDPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "equipment"

    asset_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    serial_number: Mapped[str | None] = mapped_column(String(100), unique=True)
    equipment_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("equipment_categories.id"))
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(100))
    department_owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    status: Mapped[EquipmentStatus] = mapped_column(
        EquipmentStatusType, default=EquipmentStatus.AVAILABLE, nullable=False, index=True
    )
    current_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    qr_code_value: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    rfid_tag: Mapped[str | None] = mapped_column(String(64))
    pm_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    cal_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    equipment_metadata: Mapped[dict] = mapped_column("metadata", JSONType, default=dict)

    category: Mapped["EquipmentCategory | None"] = relationship()
    department_owner: Mapped["Department | None"] = relationship()
    current_location: Mapped["Location | None"] = relationship()
    status_history: Mapped[list["EquipmentStatusHistory"]] = relationship(
        back_populates="equipment", order_by="EquipmentStatusHistory.changed_at.desc()"
    )


class EquipmentStatusHistory(UUIDPKMixin, Base):
    __tablename__ = "equipment_status_history"

    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, nullable=False
    )

    equipment: Mapped["Equipment"] = relationship(back_populates="status_history")


class PMSchedule(UUIDPKMixin, Base):
    __tablename__ = "pm_schedules"

    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class CalibrationSchedule(UUIDPKMixin, Base):
    __tablename__ = "calibration_schedules"

    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    certificate_number: Mapped[str | None] = mapped_column(String(100))
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class EquipmentAttachment(UUIDPKMixin, Base):
    __tablename__ = "equipment_attachments"

    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50))
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
