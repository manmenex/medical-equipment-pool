"""Roadmap PR25B -- read-only export API (outbox, counter, machine keys).

Three tables, all new and additive:

* ``export_events`` -- an outbox: one row per dispatch or receipt, keyed by a
  gap-free, commit-ordered ``seq``. The export API pages over this table by
  ``seq`` and never by a timestamp (see ``app.services.export_service`` for
  why that is safe under concurrent writers).
* ``export_event_counter`` -- a single row holding the last assigned ``seq``.
  Taking its row lock is what makes ``seq`` follow commit order.
* ``export_api_keys`` -- credentials for the external machine consumer
  (Nsmart Realtime). Only a SHA-256 digest of the key is stored.

This system never calls the consumer; the consumer polls.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UTCDateTime, UUIDPKMixin

EVENT_TYPE_DISPATCH = "dispatch"
EVENT_TYPE_RECEIPT = "receipt"
ALL_EVENT_TYPES = (EVENT_TYPE_DISPATCH, EVENT_TYPE_RECEIPT)


class ExportEvent(Base):
    __tablename__ = "export_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_export_events_event_id"),
        # One dispatch and at most one receipt per transaction: a transaction
        # opens once and closes once (ADR-005), so the pair is a natural key
        # that also makes a double-emit impossible.
        UniqueConstraint("transaction_id", "event_type", name="uq_export_events_transaction_type"),
        CheckConstraint("event_type IN ('dispatch', 'receipt')", name="ck_export_events_event_type"),
        Index("ix_export_events_event_at", "event_at"),
    )

    # Assigned explicitly from export_event_counter -- deliberately NOT a
    # SERIAL/IDENTITY column: a sequence hands out numbers in *call* order,
    # not commit order, which is exactly the bug this table exists to avoid.
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("borrow_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    event_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)


class ExportEventCounter(Base):
    __tablename__ = "export_event_counter"
    __table_args__ = (CheckConstraint("id = 1", name="ck_export_event_counter_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default=text("0"))


class ExportApiKey(UUIDPKMixin, Base):
    __tablename__ = "export_api_keys"
    __table_args__ = (UniqueConstraint("key_hash", name="uq_export_api_keys_key_hash"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # SHA-256 hex of the full key. The key is 256 bits of CSPRNG output, so a
    # fast hash is the right tool (no dictionary to slow down); bcrypt would
    # only add latency to every poll.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # First characters of the key, shown in listings so an administrator can
    # tell keys apart. Not sufficient to authenticate.
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
