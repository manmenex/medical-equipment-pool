import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

TX_STATUS_BORROWED = "borrowed"
TX_STATUS_RETURNED = "returned"
TX_STATUS_OVERDUE = "overdue"


class BorrowTransaction(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "borrow_transactions"
    __table_args__ = (
        Index(
            "idx_tx_one_active_borrow",
            "equipment_id",
            unique=True,
            postgresql_where=text("status = 'borrowed'"),
            sqlite_where=text("status = 'borrowed'"),
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
    status: Mapped[str] = mapped_column(String(20), default=TX_STATUS_BORROWED, nullable=False, index=True)

    equipment: Mapped["Equipment"] = relationship()


class TransactionAttachment(UUIDPKMixin, Base):
    __tablename__ = "transaction_attachments"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("borrow_transactions.id"), nullable=False, index=True
    )
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(30))  # photo | signature
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
