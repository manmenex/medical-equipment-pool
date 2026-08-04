import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UTCDateTime, UUIDPKMixin

# Roadmap PR19A1 (docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md §4).
# Every enum-shaped column below is a plain VARCHAR with an explicitly
# named CHECK constraint in __table_args__ -- not SQLAlchemy's `Enum` type
# -- so the constraint's exact name (and therefore its catalog definition)
# is identical on both the fresh-install path (`Base.metadata.create_all()`,
# alembic/versions/0001_initial.py) and the historical-upgrade path (this
# migration's own raw `CREATE TABLE IF NOT EXISTS`, alembic/versions/
# 0015_import_foundation.py) -- see that migration's convergence tests.


class ImportSession(UUIDPKMixin, TimestampMixin, Base):
    """§4.1. One staged import attempt for one dataset type -- the root
    aggregate of the pipeline."""

    __tablename__ = "import_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created','validating','validated','validation_failed',"
            "'dry_run_running','dry_run_completed','dry_run_failed',"
            "'executing','completed','failed','cancelled')",
            name="ck_import_sessions_status",
        ),
        UniqueConstraint("dataset_type", "idempotency_key", name="uq_import_sessions_dataset_idempotency"),
        # §4.5: the composite ownership FK. `current_validation_job_id`
        # alone only proves *some* import_jobs row exists; this additionally
        # requires that row's own import_session_id to equal this session's
        # id, enforced by the database, not only by application code. Needs
        # the matching `uq_import_jobs_session_id` UNIQUE(import_session_id,
        # id) on ImportJob below as its target.
        ForeignKeyConstraint(
            ["id", "current_validation_job_id"],
            ["import_jobs.import_session_id", "import_jobs.id"],
            name="fk_import_sessions_current_validation_job",
            ondelete="RESTRICT",
        ),
        Index("ix_import_sessions_dataset_type_status", "dataset_type", "status"),
        Index("ix_import_sessions_created_by_user_id", "created_by_user_id"),
        Index("ix_import_sessions_terminal_at", "terminal_at"),
        # §4.1: supports the retention-cleanup claim query (§18, a later
        # slice) -- only sessions not yet purged are ever scanned by it.
        Index(
            "ix_import_sessions_retention_cleanup_claim",
            "retention_cleanup_claim_expires_at",
            postgresql_where=text("retention_purged_at IS NULL"),
            sqlite_where=text("retention_purged_at IS NULL"),
        ),
    )

    dataset_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    # Optimistic-concurrency counter -- incremented by exactly 1 on every
    # CAS-guarded UPDATE to this row (§7). An additional, independent guard
    # alongside `status`, never a substitute for it.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    # No FK to import_jobs here -- see the composite ForeignKeyConstraint in
    # __table_args__ above, which covers this column together with `id`.
    current_validation_job_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    dry_run_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Retention-clock anchor (§18, enforced by a later slice) -- set only
    # for the three terminal statuses (completed/failed/cancelled).
    terminal_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    retention_purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_bytes_deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    retention_cleanup_claimed_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    retention_cleanup_claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    total_rows: Mapped[int | None] = mapped_column(Integer)
    valid_rows: Mapped[int | None] = mapped_column(Integer)
    invalid_rows: Mapped[int | None] = mapped_column(Integer)
    warning_rows: Mapped[int | None] = mapped_column(Integer)
    imported_rows: Mapped[int | None] = mapped_column(Integer)
    failure_reason: Mapped[str | None] = mapped_column(Text)


class ImportSource(UUIDPKMixin, Base):
    """§4.2. The single source-of-truth identity/checksum record for a
    session's data. 1:1 with `ImportSession`. Carries its own two-state
    lifecycle (`registered`/`frozen`, §6). No `version` counter -- `status`
    alone is a sufficient CAS guard for a two-state, one-directional,
    irreversible transition (§6's freeze contract, §15.2's correction CAS)."""

    __tablename__ = "import_sources"
    __table_args__ = (
        CheckConstraint("status IN ('registered','frozen')", name="ck_import_sources_status"),
        CheckConstraint("LENGTH(checksum) >= 32", name="ck_import_sources_checksum_length"),
    )

    import_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered")
    frozen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    filename: Mapped[str | None] = mapped_column(String(255))
    source_version: Mapped[str | None] = mapped_column(String(100))
    options_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class ImportJob(UUIDPKMixin, Base):
    """§4.3. One execution record of one phase (`ValidationAttempt` /
    `DryRunAttempt` / `ExecutionAttempt` at the API layer -- one physical
    table, discriminated by `job_type`). Carries the lease/fencing token
    set (§9, owned by PR19A2/A3) protecting its own completion write from a
    late/superseded commit. PR19A1 owns only the physical columns; the
    lease/heartbeat/recovery mechanism itself is a later slice's
    deliverable."""

    __tablename__ = "import_jobs"
    __table_args__ = (
        CheckConstraint("job_type IN ('validate','dry_run','execute')", name="ck_import_jobs_job_type"),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','abandoned')", name="ck_import_jobs_status"
        ),
        # §4.5's composite-FK target -- required so ImportSession's
        # composite FK can reference (import_session_id, id) together.
        UniqueConstraint("import_session_id", "id", name="uq_import_jobs_session_id"),
        UniqueConstraint(
            "import_session_id", "job_type", "attempt_number", name="uq_import_jobs_session_job_type_attempt"
        ),
        Index("ix_import_jobs_session_id_job_type", "import_session_id", "job_type"),
        # Supports the recovery-claim scan (§9.3, a later slice) -- only a
        # currently-running job is ever a stale-lease candidate.
        Index(
            "ix_import_jobs_lease_expires_at",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    import_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_owner: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Forward-compatible fencing token, part 2 -- always 1 in this
    # foundation (a new attempt is always a new row, never an in-place
    # re-lease); included so a future completion-fencing check never needs
    # to change shape if that assumption is ever revisited (§9.1).
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    ruleset_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class ImportRowError(UUIDPKMixin, Base):
    """§4.4 (`ValidationFinding` at the API layer). One collected finding,
    attributed to a `ValidationAttempt` via `import_job_id`."""

    __tablename__ = "import_row_errors"
    __table_args__ = (
        CheckConstraint("severity IN ('error','warning')", name="ck_import_row_errors_severity"),
        Index("ix_import_row_errors_job_id_row_number", "import_job_id", "row_number"),
    )

    import_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("import_jobs.id", ondelete="RESTRICT"), nullable=False)
    row_number: Mapped[int | None] = mapped_column(Integer)
    field: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="error")
