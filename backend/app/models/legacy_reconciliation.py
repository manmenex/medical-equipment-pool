"""Roadmap PR22B -- Reconciliation Schema + Run/Snapshot Foundation.

Authoritative design: `docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md`
(§9.J two-boundary temporal coverage model, §11/§13-15 reconciliation
run/finding shape, §17.2 recommended domain model, §18 BME alias, §20-22
sign-off preconditions, §25, §34 pairing-candidate disposition
clarification, §36 OD-PR22-1 through OD-PR22-7, all RESOLVED/OWNER
APPROVED), refined by the PR22B implementation task's own binding field
contract. Do not restate the design rationale here -- read that document
for it.

**Scope boundary (this slice only): schema/persistence foundation
only.** No analysis/detection engine (PR22C's own job), no API/frontend,
no disposition-mutation service, and no sign-off logic/audit/checks
(PR22E's own job). `LegacyReconciliationSignOff` exists here as a table
shape only -- nothing in this codebase writes to it yet.

**OD-PR22-7's two-boundary temporal model.** `LegacyMigrationAuthority
Coverage` is the sole authoritative, append-only (never `UPDATE`d --
correcting a coverage window mints a new row, never mutates an existing
one) approval artifact for `legacy_coverage_start`, `legacy_coverage_end`,
and `live_system_start` per migration authority, bound to a bounded
`approval_basis` marker (never arbitrary free text as the only
provenance). `legacy_coverage_start`/`legacy_coverage_end`/
`live_system_start` are never inferred from observed `MIN`/`MAX` event
timestamps or backfilled -- no coverage row exists until an explicit
governed approval creates one; this schema is deliberately createable
with zero coverage-approval rows. All three temporal relationships
between `legacy_coverage_end` and `live_system_start` -- gap (`<`),
clean handoff (`==`), overlap (`>`) -- are valid; no CHECK constraint
here encodes any of them as invalid. `LegacyReconciliationRun` binds to
exactly one approved coverage artifact via `coverage_id` and also
carries its own copies of the three timestamps as immutable
snapshot-bound evidence -- the coverage artifact remains authoritative
at run-creation time; the run's own copies are snapshot evidence, not a
second source of truth (tested for consistency at the application
level).

**OD-PR22-3's supersession model.** A signed run is never reopened or
mutated to record that a later run exists. Supersession is represented
on the NEW run via `supersedes_run_id` (self-referencing FK, `ON DELETE
RESTRICT`, self-supersession rejected by CHECK) -- the prior run is left
completely untouched.

**OD-PR22-2's four-value disposition domain**, closed: `confirmed_valid`,
`confirmed_duplicate`, `accepted_unresolved`, `requires_correction`.
There is no fifth value and specifically no `confirmed_pair` -- a
`PAIRING_CANDIDATE` finding disposed `confirmed_valid` means the
candidate pairing was reviewed and confirmed valid (§34).

**Finding `code` is a bounded, unconstrained `VARCHAR(50)`, deliberately
not a DB-level enum/CHECK domain** -- PR22C (the analysis/detection
engine) owns the actual code taxonomy and must be able to evolve it
without an accompanying schema migration every time. `RECONCILIATION_
FINDING_CODES` below is a documentation/test-fixture reference only, not
an enforced domain.

**OD-PR22-6's sign-off gate** (final sign-off blocked while ANY finding
on the run has `disposition = 'requires_correction'`, full stop --
`accepted_unresolved` remains sign-off-eligible) is not implemented or
enforced by this slice; this module only defines a schema *capable* of
supporting that gate later (the `disposition` CHECK domain, the
Run/Finding/SignOff shape) -- see PR22E for the actual gate.

**OD-PR22-4's BME alias.** `LegacyBMEUserAlias` is a display-only
resolution table (mirrors `LegacyWardAlias`'s exact shape) -- raw
historical BME text is never overwritten or discarded, no fuzzy/
confidence-scored matching exists, and no `User` row is ever created as
a side effect of inserting an alias.

Mirrors every established modeling convention in this repository (see
`app.models.legacy_history`/`app.models.import_session` for the
originals, not restated here in full): `UUIDPKMixin` alone (never
`TimestampMixin`) for every table here, since none has a mutable
`updated_at`; `UTCDateTime` for every timestamptz column; enum-shaped
columns are a plain `String` plus an explicitly named `CheckConstraint`
(`ck_<table>_<field>`) *only* where the domain is genuinely closed (not
for `Finding.code`, see above); a JSONB-with-SQLite-variant type
redefined locally in this module (never imported cross-module, to avoid
a circular import via `app/db/base.py`'s own model-registration list --
see `legacy_history.py`'s identical note); the paired-nullability CHECK
pattern for "all null or all set" coherence; `ON DELETE RESTRICT` on
every FK to a User/Equipment/permanent-evidence table -- permanent
reconciliation evidence is never cascade-deleted; and `version` CAS
columns mirroring `ImportSession.version`'s exact shape.
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

# §6 of the PR22B task contract. No "signed_off" status -- sign-off is a
# separate, immutable artifact (`LegacyReconciliationSignOff`), never a
# run-status value.
RECONCILIATION_RUN_STATUSES = ("pending", "running", "completed", "failed")

# §9/§10. Bounded, closed marker for a coverage approval's provenance --
# never arbitrary free text as the only source of authorization.
COVERAGE_APPROVAL_BASES = ("explicit_owner_approval", "explicit_administrator_approval")

# §13. Reference only -- NOT a DB-enforced domain (see the module
# docstring). PR22C owns the authoritative, evolving taxonomy.
RECONCILIATION_FINDING_CODES = (
    "EQUIPMENT_IDENTITY",
    "SOURCE_PROVENANCE",
    "DUPLICATE_EXACT",
    "DUPLICATE_SUSPECTED",
    "CHRONOLOGY_ANOMALY",
    "CURRENT_STATE_MISMATCH",
    "WARD_TRACEABILITY_GAP",
    "BME_TRACEABILITY_GAP",
    "PAIRING_CANDIDATE",
)

# §11. Closed severity domain.
RECONCILIATION_SEVERITIES = ("high", "medium", "low")

# OD-PR22-2. Closed, four-value vocabulary -- no fifth value, and
# specifically no `confirmed_pair` (§34).
RECONCILIATION_DISPOSITIONS = (
    "confirmed_valid",
    "confirmed_duplicate",
    "accepted_unresolved",
    "requires_correction",
)


class LegacyMigrationAuthorityCoverage(UUIDPKMixin, Base):
    """OD-PR22-7. One immutable, Owner/Administrator-approved temporal-
    coverage artifact per `LegacyMigrationAuthority`. Append-only: no
    call site in this codebase ever issues `UPDATE` against this table
    -- a correction to a previously-approved coverage window mints a new
    row, never mutates an existing one (same discipline as
    `LegacyMigrationAuthority.approved_workbook_sha256`); a corrected/
    re-exported authority gets its own explicit new approval, never
    silent inheritance from a prior one.
    """

    __tablename__ = "legacy_migration_authority_coverages"
    __table_args__ = (
        CheckConstraint(
            "legacy_coverage_start <= legacy_coverage_end",
            name="ck_legacy_migration_authority_coverages_coverage_window",
        ),
        CheckConstraint(
            "approval_basis IN ('explicit_owner_approval','explicit_administrator_approval')",
            name="ck_legacy_migration_authority_coverages_approval_basis",
        ),
        Index(
            "ix_legacy_migration_authority_coverages_migration_authority_id",
            "migration_authority_id",
        ),
        Index(
            "ix_legacy_migration_authority_coverages_authority_approved_at",
            "migration_authority_id",
            "approved_at",
        ),
    )

    migration_authority_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_migration_authorities.id", ondelete="RESTRICT"), nullable=False
    )
    legacy_coverage_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    legacy_coverage_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    live_system_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    approval_basis: Mapped[str] = mapped_column(String(50), nullable=False)
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())


class LegacyReconciliationRun(UUIDPKMixin, Base):
    """§6-8/§17.2. One reconciliation attempt, bound to exactly one
    approved `LegacyMigrationAuthorityCoverage` artifact. `status` has no
    "signed_off" value -- sign-off is a separate immutable artifact.
    OD-PR22-3's supersession is represented forward-only, on the NEW
    run's own `supersedes_run_id` -- a prior (possibly signed) run is
    never mutated to record that a later run supersedes it.

    `legacy_coverage_start`/`legacy_coverage_end`/`live_system_start` are
    immutable copies of the bound coverage artifact's own values,
    captured at run-creation time (§9.J) -- the coverage artifact itself
    remains the authoritative source; these columns are snapshot
    evidence of what was authoritative when this run was created, not a
    second source of truth. `snapshot_as_of` records when this run's
    input snapshot was taken, but does not by itself provide snapshot
    consistency -- PR22C's own analysis must execute inside one
    PostgreSQL `REPEATABLE READ` transaction for that guarantee; this
    slice implements no such transaction.
    """

    __tablename__ = "legacy_reconciliation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="ck_legacy_reconciliation_runs_status",
        ),
        CheckConstraint("version >= 0", name="ck_legacy_reconciliation_runs_version"),
        CheckConstraint(
            "legacy_coverage_start <= legacy_coverage_end",
            name="ck_legacy_reconciliation_runs_coverage_window",
        ),
        CheckConstraint(
            "supersedes_run_id IS NULL OR supersedes_run_id <> id",
            name="ck_legacy_reconciliation_runs_no_self_supersession",
        ),
        CheckConstraint(
            "summary_total_findings >= 0", name="ck_legacy_reconciliation_runs_summary_total_findings"
        ),
        CheckConstraint("summary_high >= 0", name="ck_legacy_reconciliation_runs_summary_high"),
        CheckConstraint("summary_medium >= 0", name="ck_legacy_reconciliation_runs_summary_medium"),
        CheckConstraint("summary_low >= 0", name="ck_legacy_reconciliation_runs_summary_low"),
        Index("ix_legacy_reconciliation_runs_created_at", "created_at"),
        Index("ix_legacy_reconciliation_runs_status", "status"),
        Index("ix_legacy_reconciliation_runs_coverage_id", "coverage_id"),
        Index("ix_legacy_reconciliation_runs_supersedes_run_id", "supersedes_run_id"),
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default=text("'pending'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    snapshot_as_of: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    legacy_coverage_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    legacy_coverage_end: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    live_system_start: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    coverage_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_migration_authority_coverages.id", ondelete="RESTRICT"), nullable=False
    )
    supersedes_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legacy_reconciliation_runs.id", ondelete="RESTRICT"), nullable=True
    )
    summary_total_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_high: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_medium: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_low: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


class LegacyReconciliationFinding(UUIDPKMixin, Base):
    """§11-13/§17.2. One detected discrepancy belonging to exactly one
    `LegacyReconciliationRun`. `code` is a bounded, DB-unconstrained
    `VARCHAR(50)` -- PR22C owns the evolving taxonomy (see the module
    docstring). `disposition` follows OD-PR22-2's closed four-value
    vocabulary (`RECONCILIATION_DISPOSITIONS`) -- `NULL` means not yet
    disposed. `disposition`/`disposed_by_user_id`/`disposed_at` are kept
    coherent by two paired-nullability CHECKs: either all three are
    `NULL`, or all three are set together. No service in this slice ever
    sets them -- that is PR22D/E's job; this schema only defines the
    shape those services will write into.

    `evidence` is structured rule evidence only (§26), required (`NOT
    NULL`) but never a substitute for real referential identity --
    provenance to specific `LegacyEquipmentEvent` rows is a real
    junction table (`LegacyReconciliationFindingEvent`), not a JSONB
    array of UUIDs. `equipment_id` is nullable -- not every finding is
    necessarily equipment-scoped.
    """

    __tablename__ = "legacy_reconciliation_findings"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('high','medium','low')",
            name="ck_legacy_reconciliation_findings_severity",
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
        CheckConstraint("version >= 0", name="ck_legacy_reconciliation_findings_version"),
        Index("ix_legacy_reconciliation_findings_run_id", "run_id"),
        Index("ix_legacy_reconciliation_findings_run_disposition", "run_id", "disposition"),
        Index("ix_legacy_reconciliation_findings_run_code", "run_id", "code"),
        Index("ix_legacy_reconciliation_findings_equipment_id", "equipment_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=True
    )
    evidence: Mapped[dict] = mapped_column(_ReconciliationJSONType, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    disposition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    disposed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    disposed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    disposition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())


class LegacyReconciliationFindingEvent(UUIDPKMixin, Base):
    """§14. Junction table proving which specific, immutable
    `LegacyEquipmentEvent` rows a `LegacyReconciliationFinding`'s
    evidence actually references -- indexed and referentially enforced,
    deliberately not a JSONB array of UUIDs (§26). `finding_id` uses `ON
    DELETE RESTRICT`, not `CASCADE`: findings are permanent evidence and
    are never deleted, so cascading would only ever mask a bug. Never
    mutates `LegacyEquipmentEvent` itself.
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
    """OD-PR22-6/OD-PR22-3. Table shape only -- **zero sign-off logic,
    endpoint, service, precondition check, or audit write exists in this
    slice**; all of that is PR22E's exclusive scope (§16). `UNIQUE
    (run_id)` enforces at most one sign-off per run at the schema level.
    No mutable fields, no update timestamp -- a sign-off is never edited
    after creation; a later review creates a new run
    (`LegacyReconciliationRun.supersedes_run_id`) rather than reopening
    this one. `run_version_at_signoff` records the exact `Run.version`
    CAS value observed at sign-off time, for future staleness detection
    by PR22E.
    """

    __tablename__ = "legacy_reconciliation_signoffs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_legacy_reconciliation_signoffs_run_id"),
        CheckConstraint(
            "run_version_at_signoff >= 0", name="ck_legacy_reconciliation_signoffs_run_version_at_signoff"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    signed_off_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    signed_off_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    attestation_summary: Mapped[dict] = mapped_column(_ReconciliationJSONType, nullable=False)
    run_version_at_signoff: Mapped[int] = mapped_column(Integer, nullable=False)


class LegacyBMEUserAlias(UUIDPKMixin, Base):
    """OD-PR22-4. Display-only, Administrator-managed mapping from a raw
    historical BME name (as it appears verbatim in `LegacyEquipmentEvent
    .legacy_bme_name`) to a current `User`. Mirrors `LegacyWardAlias`'s
    exact shape. No fuzzy/normalized/confidence-scored matching field
    exists -- resolution is plain equality only. Never auto-creates a
    `User`, and never claims the historical actor named by
    `raw_bme_name` literally *is* `resolved_user_id` -- this is a
    display convenience only; raw historical text remains the permanent
    evidence of record on the event itself, untouched by this table.
    """

    __tablename__ = "legacy_bme_user_aliases"
    __table_args__ = (UniqueConstraint("raw_bme_name", name="uq_legacy_bme_user_aliases_raw_bme_name"),)

    raw_bme_name: Mapped[str] = mapped_column(String(150), nullable=False)
    resolved_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
