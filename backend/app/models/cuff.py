"""Roadmap PR28 (Owner Governance 2026-11-25 D11): Cryo-Cuff cuff tracking.

One balance row per (dispatch transaction, cuff type): ``issued_count`` is set
once at dispatch from the Cryo-Cuff checklist, ``returned_count`` only ever
grows (at device receipt or via ``POST /transactions/{id}/receive-cuffs``).
Outstanding = issued - returned, attributed to the transaction's ward (joined
live so a PR9A ward correction is followed). The CHECK constraints make a
negative balance impossible even if application logic regressed.

Cuffs are accessories, not equipment: no equipment state, no cleaning state.
Every movement is additionally written to ``audit_logs`` by the services.
"""
import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin


class TransactionCuff(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "transaction_cuffs"
    __table_args__ = (
        UniqueConstraint("transaction_id", "cuff_type", name="uq_transaction_cuffs_tx_type"),
        CheckConstraint(
            "cuff_type IN ('back_hip_rib', 'knee', 'shoulder', 'ankle')", name="ck_transaction_cuffs_type"
        ),
        CheckConstraint("issued_count > 0", name="ck_transaction_cuffs_issued_positive"),
        CheckConstraint(
            "returned_count >= 0 AND returned_count <= issued_count", name="ck_transaction_cuffs_returned_range"
        ),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("borrow_transactions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    cuff_type: Mapped[str] = mapped_column(String(20), nullable=False)
    issued_count: Mapped[int] = mapped_column(Integer, nullable=False)
    returned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
