import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import TimestampMixin, UTCDateTime, UUIDPKMixin

# Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §14.2):
# same PostgreSQL-JSONB/SQLite-JSON variant type already used by
# app.models.equipment/audit/notification/user -- not a new pattern.
_DryRunPlanJSONType = JSONB().with_variant(JSON(), "sqlite")

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
        CheckConstraint("LENGTH(notes) <= 4000", name="ck_import_sessions_notes_length"),
        CheckConstraint("LENGTH(failure_reason) <= 2000", name="ck_import_sessions_failure_reason_length"),
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
    # §4.1: `Default 'created'` is a real PostgreSQL server default, not
    # merely a Python-side convenience -- matching the raw-SQL migration's
    # `DEFAULT 'created'` so the fresh-install (ORM) and historical-upgrade
    # (migration 0015) catalogs converge exactly (§4.6/§8; `default=` alone
    # renders no DDL `DEFAULT` clause at all, the PR84-H1 defect).
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created", server_default=text("'created'"))
    # Optimistic-concurrency counter -- incremented by exactly 1 on every
    # CAS-guarded UPDATE to this row (§7). An additional, independent guard
    # alongside `status`, never a substitute for it.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
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
        # §4.2's Keys/constraints line names exactly `INDEX (checksum)` --
        # not `source_fingerprint` (the PR84-H2 defect). `checksum` is the
        # column callers and support tooling look records up by; the
        # composite `source_fingerprint` has no such lookup requirement
        # anywhere in this design.
        Index("ix_import_sources_checksum", "checksum"),
        # PR #103 fix round (PR21A): minimum supporting composite UNIQUE
        # a downstream composite-FK "ownership" target needs --
        # `import_session_id` is already unique on its own (the 1:1
        # constraint above, unchanged), so this adds no new business
        # rule; it exists purely so `(import_session_id, id)` together
        # can be the target of a composite FK proving some other row's
        # declared source belongs to its declared session (mirrors this
        # module's own `uq_import_jobs_session_id` pattern on
        # `ImportJob`, used by `ImportSession`'s own composite FK to
        # `import_jobs` above).
        UniqueConstraint("import_session_id", "id", name="uq_import_sources_session_id"),
    )

    import_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="registered", server_default=text("'registered'")
    )
    frozen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    filename: Mapped[str | None] = mapped_column(String(255))
    source_version: Mapped[str | None] = mapped_column(String(100))
    options_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # §4.2: `Default now()` is a real PostgreSQL server default (PR84-H1;
    # see ImportSession.status above for the general rationale).
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())


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
        CheckConstraint("LENGTH(error_message) <= 2000", name="ck_import_jobs_error_message_length"),
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
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_owner: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Forward-compatible fencing token, part 2 -- always 1 in this
    # foundation (a new attempt is always a new row, never an in-place
    # re-lease); included so a future completion-fencing check never needs
    # to change shape if that assumption is ever revisited (§9.1).
    lease_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    ruleset_version: Mapped[str | None] = mapped_column(String(50))
    # §4.3: `Default now()` is a real PostgreSQL server default (PR84-H1).
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())


class ImportSourceBlob(Base):
    """Roadmap PR20A (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md
    §6.2). 1:1 durable byte storage for a registered `ImportSource`,
    colocated in the same PostgreSQL database as `import_sources` so
    registration is a single physical transaction -- no saga/orphan-cleanup
    machinery is needed (§6.2's atomicity contract). Deliberately not a
    `UUIDPKMixin` row: `import_source_id` itself is the primary key (1:1,
    never a separate synthetic id), matching the design's exact physical
    schema (`import_source_blobs (import_source_id UUID PK, FK
    import_sources.id ON DELETE RESTRICT, content BYTEA NOT NULL)`)."""

    __tablename__ = "import_source_blobs"

    import_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sources.id", ondelete="RESTRICT"), primary_key=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


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
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="error", server_default=text("'error'"))


class EquipmentMasterDryRunPlan(UUIDPKMixin, Base):
    """Roadmap PR20D (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md
    §14.2). One persisted, immutable dry-run plan header per successful
    Equipment Master dry-run attempt that reached a countable result --
    the exact artifact an operator reviews and confirms; PR20E's
    `execute()` resolves and applies this exact row, never a live
    recomputation (§14.1's five-identity invariant). Never updated in
    place except for its own `status`/`confirmed_at`/`confirmed_by_user_id`
    transitions (§10/§14.4a) -- its identity/summary columns are written
    exactly once, by `persist_dry_run_plan` (§14.3)."""

    __tablename__ = "equipment_master_dry_run_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','superseded','consumed','failed')",
            name="ck_equipment_master_dry_run_plans_status",
        ),
        CheckConstraint(
            "(confirmed_at IS NULL) = (confirmed_by_user_id IS NULL)",
            name="ck_equipment_master_dry_run_plans_confirmed_pair",
        ),
        CheckConstraint("summary_total_rows >= 0", name="ck_equipment_master_dry_run_plans_summary_total_rows"),
        CheckConstraint("summary_creates >= 0", name="ck_equipment_master_dry_run_plans_summary_creates"),
        CheckConstraint("summary_updates >= 0", name="ck_equipment_master_dry_run_plans_summary_updates"),
        CheckConstraint("summary_skips >= 0", name="ck_equipment_master_dry_run_plans_summary_skips"),
        CheckConstraint("summary_warnings >= 0", name="ck_equipment_master_dry_run_plans_summary_warnings"),
        CheckConstraint(
            "summary_blocking_conflicts >= 0", name="ck_equipment_master_dry_run_plans_summary_blocking_conflicts"
        ),
        # §14.2's composite-FK "ownership" pair -- proves both job ids
        # actually belong to *this* session, not merely that some
        # import_jobs row with that id exists somewhere (mirrors
        # ImportSession.current_validation_job_id's own composite FK above).
        ForeignKeyConstraint(
            ["import_session_id", "accepted_validation_job_id"],
            ["import_jobs.import_session_id", "import_jobs.id"],
            name="fk_equipment_master_dry_run_plans_accepted_validation_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["import_session_id", "dry_run_job_id"],
            ["import_jobs.import_session_id", "import_jobs.id"],
            name="fk_equipment_master_dry_run_plans_dry_run_job",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "import_session_id", "dry_run_job_id", name="uq_equipment_master_dry_run_plans_session_dry_run_job"
        ),
        # §14.2/§11: at most one `active` plan per session -- a partial
        # unique index (not a plain UNIQUE(import_session_id)), since
        # `superseded`/`consumed`/`failed` plans for the same session
        # coexist as historical rows.
        Index(
            "uq_equipment_master_dry_run_plans_one_active_per_session",
            "import_session_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    import_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    import_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sources.id", ondelete="RESTRICT"), nullable=False
    )
    # Defense-in-depth copy -- must match import_sources.checksum (§14.2);
    # never itself a source of truth, never read instead of import_sources.
    source_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    # No plain FK to import_jobs.id alone -- see the composite
    # ForeignKeyConstraint pair above, which additionally proves session
    # ownership.
    accepted_validation_job_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    dry_run_job_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    # NULL until an explicit POST .../confirm (§14.4a) -- never set
    # implicitly by persist_dry_run_plan.
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # §14-15: derived from, and must always match, this plan's own
    # persisted rows -- never computed from unrelated current DB state.
    summary_total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_creates: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_updates: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_skips: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_warnings: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_blocking_conflicts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class EquipmentMasterDryRunPlanRow(UUIDPKMixin, Base):
    """§14.2. One planned action row, belonging to exactly one
    `EquipmentMasterDryRunPlan`. Immutable once committed (§10) -- never
    updated in place; a superseding plan gets entirely new rows. Content
    columns (`normalized_values`/`matched_identity_fields`/`warnings`) are
    redacted (set NULL) by retention cleanup (§14.9) -- the structural
    columns (`action`/`target_equipment_id`/`expected_equipment_version`/
    `source_row_number`) are explicitly preserved."""

    __tablename__ = "equipment_master_dry_run_plan_rows"
    __table_args__ = (
        CheckConstraint("action IN ('CREATE','UPDATE','SKIP')", name="ck_equipment_master_dry_run_plan_rows_action"),
        CheckConstraint(
            "(action = 'UPDATE') = (target_equipment_id IS NOT NULL)",
            name="ck_equipment_master_dry_run_plan_rows_update_target",
        ),
        CheckConstraint(
            "(action = 'UPDATE') = (expected_equipment_version IS NOT NULL)",
            name="ck_equipment_master_dry_run_plan_rows_update_expected_version",
        ),
        UniqueConstraint(
            "dry_run_plan_id", "source_row_number", name="uq_equipment_master_dry_run_plan_rows_plan_row_number"
        ),
        Index("ix_equipment_master_dry_run_plan_rows_plan_id", "dry_run_plan_id"),
    )

    dry_run_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("equipment_master_dry_run_plans.id", ondelete="RESTRICT"), nullable=False
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    target_equipment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("equipment.id", ondelete="RESTRICT"))
    normalized_values: Mapped[dict | None] = mapped_column(_DryRunPlanJSONType)
    matched_identity_fields: Mapped[dict | None] = mapped_column(_DryRunPlanJSONType)
    expected_equipment_version: Mapped[int | None] = mapped_column(Integer)
    warnings: Mapped[list | None] = mapped_column(_DryRunPlanJSONType)
