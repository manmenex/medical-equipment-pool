"""Roadmap PR22B -- Reconciliation Schema + Run/Snapshot Foundation.

Authoritative design: `docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md`
(§9.J two-boundary temporal coverage model, §11/§13-15 reconciliation
run/finding shape, §17.2 recommended domain model, §18 BME alias
deferral, §20-22 sign-off preconditions, §25, §34 pairing-candidate
disposition clarification, §36 OD-PR22-1 through OD-PR22-7, all
RESOLVED/OWNER APPROVED). Do not restate the design rationale here --
read that document for it.

**Scope boundary (this slice only): schema/persistence foundation
only.** No analysis/detection engine (PR22C's own job), no API/frontend,
no disposition-mutation service, and no sign-off logic/audit/checks
(PR22E's own job). `LegacyReconciliationSignOff` exists here as a table
shape only -- nothing in this codebase writes to it yet.

**`LegacyBMEUserAlias` (§18) is deliberately deferred, not silently
omitted.** §18 explicitly permits deferring this table to a smaller
prerequisite slice when it is not required by the Run/Finding/SignOff
foundation itself -- it is not: no column in this module references it,
and no test in this slice depends on it existing. Introducing it here
would add an unused table with no caller, violating this codebase's "no
dead code" discipline (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md
§31). It is left for a future, narrowly-scoped slice that actually
consumes it.

**OD-PR22-7's two-boundary temporal model.** `LegacyMigrationAuthority
Coverage` is the sole authoritative, append-only (never `UPDATE`d --
correcting a coverage window mints a new row, never mutates an
existing one) approval artifact for `legacy_coverage_start`,
`legacy_coverage_end`, and `live_system_start` per migration authority.
All three temporal relationships between `legacy_coverage_end` and
`live_system_start` -- gap (`<`), clean handoff (`==`), overlap (`>`)
-- are valid per §9.J; no CHECK constraint here encodes any of them as
invalid. `LegacyReconciliationRun` binds to exactly one approved
coverage artifact via `coverage_id` and additionally copies the three
timestamps onto itself as immutable snapshot-bound evidence -- the
coverage artifact is authoritative at run-creation time, the run's own
copied values are snapshot evidence of what was authoritative when the
run was created (§9.J).

**OD-PR22-2's four-value disposition domain**, closed: `confirmed_valid`,
`confirmed_duplicate`, `accepted_unresolved`, `requires_correction`.
There is no fifth value and specifically no `confirmed_pair` -- a
`PAIRING_CANDIDATE` finding disposed `confirmed_valid` means the
candidate pairing was reviewed and confirmed valid (§34).

**OD-PR22-6's sign-off gate** (final sign-off blocked while ANY finding
on the run has `disposition = 'requires_correction'`, full stop --
`accepted_unresolved` remains sign-off-eligible) is not implemented or
enforced by this slice; this module only defines a schema *capable* of
supporting that gate later (the `disposition` CHECK domain, the
Run/Finding/SignOff shape) -- see PR22E for the actual gate.

Mirrors every established modeling convention in this repository (see
`app.models.legacy_history`/`app.models.import_session` for the
originals, not restated here in full): `UUIDPKMixin` alone (never
`TimestampMixin`) for every table here, since none has a mutable
`updated_at`; `UTCDateTime` for every timestamptz column; enum-shaped
columns are a plain `String` plus an explicitly named `CheckConstraint`
(`ck_<table>_<field>`), never a native `Enum`; a JSONB-with-SQLite-
variant type redefined locally in this module (never imported
cross-module, to avoid a circular import via `app/db/base.py`'s own
model-registration list -- see `legacy_history.py`'s identical note);
the paired-nullability CHECK pattern for "all null or all set"
coherence; `ON DELETE RESTRICT` on every FK to a User/Equipment/
permanent-evidence table; the `active`/`superseded`/`consumed`/`failed`
supersession-status domain and its accompanying "one active per parent"
partial unique index, both reused verbatim from
`EquipmentMasterDryRunPlan`/`LegacyHistoryDryRunPlan` rather than
inventing a new lifecycle taxonomy; and a `version` CAS column
mirroring `ImportSession.version`'s exact shape.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
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
from app.models.mixins import UTCDateTime, UUIDPKMixin

# Same PostgreSQL-JSONB/SQLite-JSON variant type already used by
# `app.models.import_session`/`app.models.legacy_history` -- defined
# locally rather than imported from either module to avoid a circular
# import (see `legacy_history.py`'s identical note for the full
# rationale).
_ReconciliationJSONType = JSONB().with_variant(JSON(), "sqlite")

# §17.2/§36. Run/plan-style supersession lifecycle, reused verbatim from
# `EquipmentMasterDryRunPlan`/`LegacyHistoryDryRunPlan` (0018/0019) --
# not a new taxonomy.
RECONCILIATION_RUN_STATUSES = ("active", "superseded", "consumed", "failed")

# §17.2. Minimal, representative finding-type domain sufficient for this
# slice's schema tests. PR22C (the analysis/detection engine) owns the
# authoritative taxonomy and may extend this CHECK domain via its own
# additive migration -- this slice defines only the column shape and
# `PAIRING_CANDIDATE` (§34's own explicit reference point), never the
# detection logic that produces any of these values.
RECONCILIATION_FINDING_TYPES = (
    "MISSING_IN_LIVE_SYSTEM",
    "MISSING_IN_LEGACY_HISTORY",
    "STATUS_CONFLICT",
    "PAIRING_CANDIDATE",
    "DUPLICATE_SUSPECT",
)

# OD-PR22-2. Closed, four-value vocabulary -- no fifth value, and
# specifically no `confirmed_pair` (§34).
RECONCILIATION_DISPOSITIONS = (
    "confirmed_valid",
    "confirmed_duplicate",
    "accepted_unresolved",
    "requires_correction",
)


class LegacyMigrationAuthorityCoverage(UUIDPKMixin, Base):
    """OD-PR22-7. One immutable, Owner-approved temporal-coverage
    artifact per `LegacyMigrationAuthority`. Append-only: no call site
    in this codebase ever issues `UPDATE` against this table -- a
    correction to a previously-approved coverage window mints a new
    row, never mutates an existing one (same discipline as
    `LegacyMigrationAuthority.approved_workbook_sha256`).

    `legacy_coverage_start`/`legacy_coverage_end`/`live_system_start`
    are never inferred from observed `MIN`/`MAX` event timestamps --
    they are authoritative values from an explicit governed approval
    workflow (§9.J), captured here as the columns an approver set, not
    computed.
    """

    __tablename__ = "legacy_migration_authority_coverages"
    __table_args__ = (
        CheckConstraint(
            "legacy_coverage_start < legacy_coverage_end",
            name="ck_legacy_migration_authority_coverages_coverage_window",
        ),
        Index(
            "ix_legacy_migration_authority_coverages_migration_authority_id",
            "migration_authority_id",
        ),
    )

    migration_authority_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_migration_authorities.id", ondelete="RESTRICT"), nullable=False
    )
    legacy_coverage_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    legacy_coverage_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    live_system_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())


class LegacyReconciliationRun(UUIDPKMixin, Base):
    """§11/§13/§17.2. One reconciliation attempt, bound to exactly one
    approved `LegacyMigrationAuthorityCoverage` artifact. Follows the
    same `active`/`superseded`/`consumed`/`failed` supersession
    lifecycle as `LegacyHistoryDryRunPlan`/`EquipmentMasterDryRunPlan`
    -- a re-analysis creates a NEW run row rather than mutating an
    existing one; at most one `active` run may exist per coverage
    artifact at a time (`uq_..._one_active_per_coverage`).

    `legacy_coverage_start_snapshot`/`legacy_coverage_end_snapshot`/
    `live_system_start_snapshot` are immutable copies of the bound
    coverage artifact's own values, captured at run-creation time
    (§9.J) -- the coverage artifact itself remains the authoritative
    source; these columns are snapshot evidence of what was
    authoritative when this run was created, not a second source of
    truth.
    """

    __tablename__ = "legacy_reconciliation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','superseded','consumed','failed')",
            name="ck_legacy_reconciliation_runs_status",
        ),
        CheckConstraint(
            "summary_total_findings >= 0", name="ck_legacy_reconciliation_runs_summary_total_findings"
        ),
        CheckConstraint(
            "summary_requires_correction >= 0",
            name="ck_legacy_reconciliation_runs_summary_requires_correction",
        ),
        CheckConstraint(
            "summary_accepted_unresolved >= 0",
            name="ck_legacy_reconciliation_runs_summary_accepted_unresolved",
        ),
        CheckConstraint(
            "summary_confirmed_valid >= 0", name="ck_legacy_reconciliation_runs_summary_confirmed_valid"
        ),
        CheckConstraint(
            "summary_confirmed_duplicate >= 0",
            name="ck_legacy_reconciliation_runs_summary_confirmed_duplicate",
        ),
        Index("ix_legacy_reconciliation_runs_coverage_id", "coverage_id"),
        Index(
            "uq_legacy_reconciliation_runs_one_active_per_coverage",
            "coverage_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    coverage_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_migration_authority_coverages.id", ondelete="RESTRICT"), nullable=False
    )
    legacy_coverage_start_snapshot: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    legacy_coverage_end_snapshot: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    live_system_start_snapshot: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default=text("'active'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    summary_total_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_requires_correction: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    summary_accepted_unresolved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    summary_confirmed_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_confirmed_duplicate: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class LegacyReconciliationFinding(UUIDPKMixin, Base):
    """§11/§17.2. One detected discrepancy belonging to exactly one
    `LegacyReconciliationRun`. `disposition` follows OD-PR22-2's closed
    four-value vocabulary (`RECONCILIATION_DISPOSITIONS`) -- `NULL`
    means not yet disposed. `disposition`/`disposed_by_user_id`/
    `disposed_at` are kept coherent by two paired-nullability CHECKs
    (the same pattern `LegacyHistoryDryRunPlan.confirmed_at`/
    `confirmed_by_user_id` uses, extended to a third column): either
    all three are `NULL`, or all three are set together. No service in
    this slice ever sets them -- that is PR22D/E's job; this schema
    only defines the shape those services will write into.

    `evidence` is structured rule evidence only (§26), never a
    substitute for real referential identity -- provenance to specific
    `LegacyEquipmentEvent` rows is a real junction table
    (`LegacyReconciliationFindingEvent`), not a JSONB array of UUIDs.
    """

    __tablename__ = "legacy_reconciliation_findings"
    __table_args__ = (
        CheckConstraint(
            "finding_type IN ('MISSING_IN_LIVE_SYSTEM','MISSING_IN_LEGACY_HISTORY','STATUS_CONFLICT',"
            "'PAIRING_CANDIDATE','DUPLICATE_SUSPECT')",
            name="ck_legacy_reconciliation_findings_finding_type",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN "
            "('confirmed_valid','confirmed_duplicate','accepted_unresolved','requires_correction')",
            name="ck_legacy_reconciliation_findings_disposition",
        ),
        CheckConstraint(
            "(disposition IS NULL) = (disposed_by_user_id IS NULL)",
            name="ck_legacy_reconciliation_findings_disposed_by_pair",
        ),
        CheckConstraint(
            "(disposition IS NULL) = (disposed_at IS NULL)",
            name="ck_legacy_reconciliation_findings_disposed_at_pair",
        ),
        Index("ix_legacy_reconciliation_findings_run_id", "run_id"),
        Index("ix_legacy_reconciliation_findings_equipment_id", "equipment_id"),
        Index("ix_legacy_reconciliation_findings_disposition", "disposition"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False)
    finding_type: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(_ReconciliationJSONType, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    disposition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    disposed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    disposed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class LegacyReconciliationFindingEvent(UUIDPKMixin, Base):
    """§17.2. Junction table proving which specific, immutable
    `LegacyEquipmentEvent` rows a `LegacyReconciliationFinding`'s
    evidence actually references -- indexed and referentially enforced,
    deliberately not a JSONB array of UUIDs (§26). Never mutates
    `LegacyEquipmentEvent` itself; `ON DELETE RESTRICT` on both FKs
    means neither side of a link can be silently orphaned by an
    unrelated delete.
    """

    __tablename__ = "legacy_reconciliation_finding_events"
    __table_args__ = (
        UniqueConstraint(
            "finding_id", "legacy_equipment_event_id", name="uq_legacy_reconciliation_finding_events_finding_event"
        ),
        Index("ix_legacy_reconciliation_finding_events_finding_id", "finding_id"),
        Index(
            "ix_legacy_reconciliation_finding_events_event_id",
            "legacy_equipment_event_id",
        ),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_reconciliation_findings.id", ondelete="RESTRICT"), nullable=False
    )
    legacy_equipment_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_equipment_events.id", ondelete="RESTRICT"), nullable=False
    )


class LegacyReconciliationSignOff(UUIDPKMixin, Base):
    """OD-PR22-6. Table shape only -- **zero sign-off logic, endpoint,
    service, precondition check, or audit write exists in this slice**;
    all of that is PR22E's exclusive scope (§20-22). `UNIQUE(run_id)`
    enforces at most one sign-off per run at the schema level; a
    superseded run is never signed off (a new run is created instead,
    per `LegacyReconciliationRun`'s own supersession model), so no
    "active" partial-unique complexity is needed here the way it is on
    `LegacyReconciliationRun` itself.
    """

    __tablename__ = "legacy_reconciliation_sign_offs"
    __table_args__ = (UniqueConstraint("run_id", name="uq_legacy_reconciliation_sign_offs_run_id"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    signed_off_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    signed_off_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
