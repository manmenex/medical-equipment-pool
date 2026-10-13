"""Roadmap PR25E slice B1 -- ``client_operations``: the offline-sync idempotency
ledger and review list (docs/design/PR25D_OFFLINE_OPERATION_PLAN.md sections
6.2, 8.3 and 16.1).

Schema only: no endpoint or service writes this table yet (B2 onwards).

``status`` is bookkeeping about a *request*, not a lifecycle state. It adds no
equipment state and no transaction state: ``BorrowTransaction.status`` stays
OPEN/CLOSED (ADR-005) and equipment keeps its four states.

Every foreign key is ON DELETE RESTRICT (repository invariant).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UTCDateTime
from app.models.audit import JSONType

OP_TYPE_DISPATCH = "dispatch"
OP_TYPE_RECEIPT = "receipt"
ALL_OP_TYPES = (OP_TYPE_DISPATCH, OP_TYPE_RECEIPT)

OP_STATUS_PENDING = "pending"  # retry_later only; non-terminal, always re-executed
OP_STATUS_APPLIED = "applied"
OP_STATUS_CONFLICT = "conflict"
OP_STATUS_REJECTED = "rejected"
OP_STATUS_RESOLVED = "resolved"  # a human closed a conflict
ALL_OP_STATUSES = (
    OP_STATUS_PENDING,
    OP_STATUS_APPLIED,
    OP_STATUS_CONFLICT,
    OP_STATUS_REJECTED,
    OP_STATUS_RESOLVED,
)

TIME_FLAGS = ("clamped_future", "clamped_old", "before_dispatch", "before_last_receipt")
RESOLUTION_MATCHES = ("same", "different", "dismissed_only")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ClientOperation(Base):
    __tablename__ = "client_operations"
    __table_args__ = (
        UniqueConstraint("device_id", "device_seq", name="uq_client_operations_device_seq"),
        CheckConstraint(f"op_type IN ({_in(ALL_OP_TYPES)})", name="ck_client_operations_op_type"),
        CheckConstraint(f"status IN ({_in(ALL_OP_STATUSES)})", name="ck_client_operations_status"),
        CheckConstraint(
            f"time_flag IS NULL OR time_flag IN ({_in(TIME_FLAGS)})", name="ck_client_operations_time_flag"
        ),
        CheckConstraint(
            f"resolution_matches_proposal IS NULL OR resolution_matches_proposal IN ({_in(RESOLUTION_MATCHES)})",
            name="ck_client_operations_resolution_matches",
        ),
        CheckConstraint("attempt_count >= 1", name="ck_client_operations_attempt_count"),
        # Review list (non-applied ops, oldest first) and stats range scans.
        Index("ix_client_operations_status_received_at", "status", "received_at"),
        Index("ix_client_operations_received_at", "received_at"),
        Index("ix_client_operations_transaction_id", "transaction_id"),
        Index("ix_client_operations_collision_group_id", "collision_group_id"),
    )

    # Idempotency key, supplied by the client (and reused as the transaction id
    # for a dispatch); never generated server-side.
    op_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    device_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Original operator (or ``original_user_id`` for an adopted op).
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    # Adopter (section 8.3); equals ``user_id`` for normal ops.
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    adopted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    stale_context: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    op_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # SHA-256 hex of the canonical JSON business payload.
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Set when applied; for a receipt, the target transaction.
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("borrow_transactions.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    occurred_at_local: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    clock_offset_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Server time the op was first received (also for ``pending`` rows, so the
    # 48 h cutoff is server-measured).
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    time_flag: Mapped[str | None] = mapped_column(String(30), nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)

    # Review outcome (section 9.6).
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pilot statistics (section 16.1); aggregates only, no payload bodies.
    collision_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    order_valid_at_detection: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    proposed_sequence: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    bands_overlap: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    offset_age_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_matches_proposal: Mapped[str | None] = mapped_column(String(20), nullable=True)
