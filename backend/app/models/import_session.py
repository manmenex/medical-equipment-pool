"""Roadmap PR19A -- Legacy Import Foundation.

See docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md for the full design
this module implements, and docs/audits/04-consolidated-implementation-plan.md
Part D ("PR19 -- Legacy Import Foundation") for the authoritative Roadmap
scope boundary this slice must not exceed.

This module defines the persisted foundation for a staged, validation-first,
traceable import framework: an `ImportSession` (one import attempt for one
dataset type), the `ImportJob` rows that record each phase of that attempt
(validate / dry-run / execute) independently, and the `ImportRowError` rows
that collect every validation/business-rule failure a session produces.

No table here is ever written to by any existing runtime code path
(equipment, transaction, dispatch/receipt, reporting, or Roadmap PR12's
inventory-import module) -- these are new, additive tables with no foreign
key pointing *into* them from existing domain tables, so this migration can
never affect existing behavior. Nothing in this module imports or writes
`Equipment`, `BorrowTransaction`, or any other existing domain model; the
adapters that will eventually do that belong to Roadmap PR20/PR21, not this
foundation slice.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import TimestampMixin, UTCDateTime, UUIDPKMixin

JSONType = JSONB().with_variant(JSON(), "sqlite")


class ImportSessionStatus(str, enum.Enum):
    """The import session state machine (design §4). Every transition is
    enforced by `app.services.import_foundation`, never by a client-supplied
    value -- these are the only states that may ever be persisted.

    ``CREATED -> VALIDATING -> {VALIDATED, VALIDATION_FAILED}``
    ``VALIDATED -> DRY_RUN_RUNNING -> {DRY_RUN_COMPLETED, DRY_RUN_FAILED}``
    ``DRY_RUN_COMPLETED -> EXECUTING -> {COMPLETED, FAILED}``
    ``{CREATED, VALIDATED, VALIDATION_FAILED, DRY_RUN_COMPLETED,
      DRY_RUN_FAILED} -> CANCELLED`` (an operator may abandon a session at
    any point before execution starts; once EXECUTING begins the session
    always resolves to COMPLETED or FAILED, never CANCELLED, since the
    outcome of the write phase must always be recorded truthfully).
    """

    CREATED = "created"
    VALIDATING = "validating"
    VALIDATED = "validated"
    VALIDATION_FAILED = "validation_failed"
    DRY_RUN_RUNNING = "dry_run_running"
    DRY_RUN_COMPLETED = "dry_run_completed"
    DRY_RUN_FAILED = "dry_run_failed"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Terminal states an import session can never leave. Used to reject any
# further state-changing call against an already-finished session (design
# §4: "no partial silent import" applies to session state itself, not only
# to row writes -- a COMPLETED or FAILED session must never be silently
# re-validated, re-dry-run, or re-executed).
TERMINAL_SESSION_STATUSES = frozenset(
    {
        ImportSessionStatus.COMPLETED,
        ImportSessionStatus.FAILED,
        ImportSessionStatus.CANCELLED,
    }
)

# States from which an operator may cancel a session (design §4). Once
# EXECUTING has begun, cancellation is no longer offered -- the write phase
# always resolves to COMPLETED or FAILED on its own.
CANCELLABLE_SESSION_STATUSES = frozenset(
    {
        ImportSessionStatus.CREATED,
        ImportSessionStatus.VALIDATED,
        ImportSessionStatus.VALIDATION_FAILED,
        ImportSessionStatus.DRY_RUN_COMPLETED,
        ImportSessionStatus.DRY_RUN_FAILED,
    }
)


class ImportJobType(str, enum.Enum):
    VALIDATE = "validate"
    DRY_RUN = "dry_run"
    EXECUTE = "execute"


class ImportJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ImportErrorSeverity(str, enum.Enum):
    ERROR = "error"
    WARNING = "warning"


def _StrEnum(enum_cls: type[enum.Enum], *, name: str, length: int):
    """Same `native_enum=False` + `values_callable` convention already
    established by `app.models.equipment.EquipmentStatusType` -- persists
    each member's `.value` (e.g. "created"), not its Python name, and keeps
    the on-disk representation a plain bounded VARCHAR CHECK rather than a
    native PostgreSQL enum type (consistent with every other enum column in
    this schema, so new PostgreSQL enum-alteration migrations are never
    needed when a state is added)."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
    )


class ImportSession(TimestampMixin, UUIDPKMixin, Base):
    """One staged import attempt for one dataset type (design §3).

    ``dataset_type`` is a plain bounded string, not a fixed enum: this
    foundation slice intentionally does not enumerate "equipment_master" /
    "receive_history" / "issue_history" as first-class values, since doing
    so would encode PR20/PR21 scope into this migration before either is
    designed. The set of dataset types that can actually progress past
    ``CREATED`` is instead the set of keys registered in
    `app.services.import_foundation.ImportAdapterRegistry` at runtime --
    empty in this slice (see that module's docstring).
    """

    __tablename__ = "import_sessions"
    __table_args__ = (
        # Design §5 (idempotent imports): a client-supplied idempotency key
        # is unique only within its own dataset type, so the same key
        # reused for a genuinely different dataset is not silently treated
        # as the same session.
        UniqueConstraint("dataset_type", "idempotency_key", name="uq_import_sessions_dataset_idempotency_key"),
        Index("ix_import_sessions_dataset_type_status", "dataset_type", "status"),
    )
    # TD-001 precedent (app.models.equipment.Equipment): updated_at
    # (TimestampMixin) is onupdate=func.now() -- server-computed, not known
    # client-side. Every phase transition in app.services.import_foundation
    # updates this row and then serializes it for the same request/response
    # cycle (e.g. `ImportSessionOut.model_validate(session)` immediately
    # after `_run_phase`'s commit); without eager_defaults, that access has
    # no async context left to satisfy the resulting lazy refresh and raises
    # MissingGreenlet. eager_defaults=True makes UPDATE use `RETURNING
    # updated_at` too, so the value is always already loaded.
    __mapper_args__ = {"eager_defaults": True}

    dataset_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[ImportSessionStatus] = mapped_column(
        _StrEnum(ImportSessionStatus, name="import_session_status", length=30),
        nullable=False,
        default=ImportSessionStatus.CREATED,
        server_default=ImportSessionStatus.CREATED.value,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Design §5 (idempotent imports / duplicate detection). Both nullable --
    # a caller is not required to supply either, but when supplied, the
    # idempotency key is enforced unique per dataset_type (see
    # UniqueConstraint above) and the source checksum is available for a
    # future slice's own duplicate-file heuristics (not enforced unique
    # here, since two independent sessions legitimately re-validating the
    # same source content is not itself an error at this foundation layer).
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Populated once the corresponding phase has run. Nullable throughout a
    # session's early states -- absence itself is meaningful (e.g.
    # `dry_run_completed_at IS NULL` means dry run has not yet completed),
    # never defaulted to a sentinel value.
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    dry_run_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    total_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    invalid_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imported_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Design §4: the single top-level reason a session is in a *_FAILED
    # state -- distinct from the per-row detail in `import_row_errors`,
    # which may be empty (e.g. a session fails because no adapter is
    # registered for its dataset_type, not because any row was invalid).
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    jobs: Mapped[list["ImportJob"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ImportJob.created_at"
    )
    row_errors: Mapped[list["ImportRowError"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ImportJob(TimestampMixin, UUIDPKMixin, Base):
    """One phase of one import session (design §7: "resumable import
    sessions -- foundation only"). Recording each phase as its own row,
    rather than only the session's own timestamps, is what lets a future
    slice determine exactly which phase last ran and its outcome without
    re-deriving it from the session's summary counters -- the schema
    already supports resuming after an interruption; running each phase
    asynchronously/out-of-process is explicitly future scope (this slice
    runs every phase synchronously within the request that triggered it).
    """

    __tablename__ = "import_jobs"
    __table_args__ = (Index("ix_import_jobs_session_id_job_type", "import_session_id", "job_type"),)
    # Same TD-001/ImportSession rationale above -- `finish_job` updates this
    # row (status/finished_at/error_message) and callers serialize it
    # (`ImportJobOut.model_validate`) in the same request cycle.
    __mapper_args__ = {"eager_defaults": True}

    # RESTRICT, not CASCADE: Roadmap PR15B (migration 0013_fk_ondelete_policy)
    # established every foreign key in this schema as explicit RESTRICT --
    # no code path anywhere performs a real SQL DELETE that would need
    # cascading (the one DELETE endpoint in this codebase, equipment's, is a
    # soft delete). No endpoint in this slice deletes an ImportSession, so
    # this is consistent with that policy at zero functional cost. The ORM
    # `cascade="all, delete-orphan"` on `ImportSession.jobs` still applies
    # for an ORM-mediated delete, independent of this DB-level constraint.
    import_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    job_type: Mapped[ImportJobType] = mapped_column(
        _StrEnum(ImportJobType, name="import_job_type", length=20), nullable=False
    )
    status: Mapped[ImportJobStatus] = mapped_column(
        _StrEnum(ImportJobStatus, name="import_job_status", length=20),
        nullable=False,
        default=ImportJobStatus.PENDING,
        server_default=ImportJobStatus.PENDING.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["ImportSession"] = relationship(back_populates="jobs")


class ImportRowError(UUIDPKMixin, Base):
    """One collected validation/business-rule failure (design §6, "Error
    collection model"). `row_number` is nullable because not every error is
    row-scoped -- a session-level failure (e.g. no adapter registered for
    this dataset_type) has no single row to attribute it to.

    Deliberately has no `created_at`/`updated_at` (no `TimestampMixin`):
    row errors are write-once, append-only records of a single validation
    pass and are never updated after insertion -- `ImportJob.finished_at`
    on the owning VALIDATE job already records when that pass ran.
    """

    __tablename__ = "import_row_errors"
    __table_args__ = (Index("ix_import_row_errors_session_id_row_number", "import_session_id", "row_number"),)

    # RESTRICT, not CASCADE -- same Roadmap PR15B (migration
    # 0013_fk_ondelete_policy) rationale as `ImportJob.import_session_id`
    # above.
    import_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[ImportErrorSeverity] = mapped_column(
        _StrEnum(ImportErrorSeverity, name="import_error_severity", length=10),
        nullable=False,
        default=ImportErrorSeverity.ERROR,
        server_default=ImportErrorSeverity.ERROR.value,
    )

    session: Mapped["ImportSession"] = relationship(back_populates="row_errors")
