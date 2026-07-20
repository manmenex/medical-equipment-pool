import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class TransactionStatus(str, enum.Enum):
    """Roadmap PR7 (knowledge/adr/ADR-005-transaction-model.md) confirmed
    two-state transaction lifecycle.

    Superseded the prior three-value status (borrowed/returned/overdue).
    See migration 0007_transaction_lifecycle.py for the exact
    legacy-to-target mapping and BorrowTransaction.legacy_status for the
    preserved original value. Mirrors app.models.equipment.EquipmentStatus's
    shape (Roadmap PR6 precedent).
    """

    OPEN = "open"
    CLOSED = "closed"


TransactionStatusType = Enum(
    TransactionStatus,
    name="transaction_status",
    native_enum=False,
    length=10,
    # See app.models.equipment.EquipmentStatusType's identical comment:
    # without this, SQLAlchemy's Enum type persists each member's *name*
    # ("OPEN") rather than its .value ("open"). values_callable makes new
    # writes persist the lowercase .value, matching migration 0007's raw
    # SQL and every other part of the system.
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class BorrowTransaction(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "borrow_transactions"
    __table_args__ = (
        Index(
            "idx_tx_one_active_borrow",
            "equipment_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
    )

    transaction_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    borrowed_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(nullable=True)
    borrower_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    borrower_name: Mapped[str] = mapped_column(String(150), nullable=False)
    ward_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wards.id"), index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("departments.id"))
    phone_number: Mapped[str | None] = mapped_column(String(20))
    pickup_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    dropoff_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id"))
    condition_on_return: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    received_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[TransactionStatus] = mapped_column(
        TransactionStatusType, default=TransactionStatus.OPEN, nullable=False, index=True
    )
    # Roadmap PR7: the exact pre-migration status value for any row remapped
    # by 0007_transaction_lifecycle.py (e.g. "borrowed", "overdue"),
    # preserved verbatim for audit/rollback only. Never read by any workflow
    # or eligibility check. Left NULL for every row created after that
    # migration. Mirrors app.models.equipment.Equipment.legacy_status
    # (Roadmap PR6 precedent).
    legacy_status: Mapped[str | None] = mapped_column(String(20))

    equipment: Mapped["Equipment"] = relationship()


class TransactionAttachment(UUIDPKMixin, Base):
    __tablename__ = "transaction_attachments"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("borrow_transactions.id"), nullable=False, index=True
    )
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(30))  # photo | signature
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
