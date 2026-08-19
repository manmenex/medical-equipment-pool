"""Roadmap PR21A -- Historical Event Schema / Provenance Foundation.

Authoritative design: `docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`
§8.1 (`LegacyEquipmentEvent` event-first provenance model), §14 (Ward
alias foundation, OD-PR21-4), §24.2 (`LegacyMigrationAuthority`,
migration-authority-scoped stable event identity), §36 (PR21-owned
dry-run plan persistence), merged as GitHub PR #102 (squash SHA
`42dd041b8534c518d006bf05750284bddad7b571`). Do not restate the design
rationale here -- read that document for it. This module implements
exactly the schema/provenance foundation it describes.

**Scope boundary (this slice only):** no parser, no SDC-sheet handling,
no Issue<->Receive pairing/link table, no `BorrowTransaction` write path,
no public HTTP route. PR21B/C (parsers) and PR21D (execution) are later,
separately-authorized slices.

**`dataset_type` normalization decision (§24.2's identity tuple:**
`(migration_authority_id, dataset_type, legacy_source_row_key)`**).**
This module does not add a separate `dataset_type` column on
`LegacyEquipmentEvent`. Within one `LegacyMigrationAuthority`, the
uniqueness scope §24.2 requires is: two rows may never collide merely
because their `legacy_source_row_key` (`ลำดับ`) values happen to match
across the Issue and Receive sheets independently verified (§24) -- i.e.
exactly what already-required `event_type` (`ISSUE`|`RECEIVE`) exists to
distinguish. Adding a second, redundant `dataset_type` column storing
the same distinction under a different name would violate this
codebase's "no duplicated provenance columns with conflicting sources of
truth" discipline. The database-enforced uniqueness constraint below is
therefore `(migration_authority_id, event_type, legacy_source_row_key)`
-- semantically equivalent to the design's own tuple, with `event_type`
filling the `dataset_type` role for this one shared authority. See
`test_legacy_history_models.py`'s identity-collision tests for the
regression proof that Issue/Receive row keys cannot collide."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
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
# `app.models.import_session` (PR20D §14.2) -- defined locally rather
# than imported from that module to avoid a circular import: `app/db/
# base.py`'s own model-registration list imports this module while
# `import_session.py` is still finishing its own top-level definitions
# (both modules import `app.db.base.Base` near the top of their own
# file), so importing a name from `import_session` here at module load
# time is unsafe regardless of import order.
_DryRunPlanJSONType = JSONB().with_variant(JSON(), "sqlite")

# §24.2. Frozen for PR21 V1 -- see `docs/evidence/pr21/
# equipment-pool-workbook-manifest.json`. Never read by generic
# application logic; used only by test fixtures/seed scripts that need a
# realistic value. The authority table itself makes no assumption that
# this is the only checksum it will ever hold across V1's lifetime.
PR21_V1_APPROVED_WORKBOOK_SHA256 = "8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c"

# §24.2's own two-level identity model, §8.1's event_type domain.
LEGACY_EVENT_TYPES = ("ISSUE", "RECEIVE")


class LegacyMigrationAuthority(UUIDPKMixin, Base):
    """§24.2. A governance-level identity representing *one* Owner-approved
    historical migration source, immutably bound to the workbook checksum
    that source was approved against. Deliberately **not** the same
    identity as `ImportSource` (a technical upload-artifact identity that
    a same-file retry creates fresh each time, §7/§26) -- see the design
    doc's own "why this is not `ImportSource.id`" discussion (§24.2).

    `approved_workbook_sha256` is unique and, once set, is never
    reassigned by application code (no `UPDATE ... SET
    approved_workbook_sha256` call site exists anywhere in this
    codebase) -- a corrected/re-exported workbook requires an explicit,
    separately-scoped correction/reconciliation workflow (PR22-or-later)
    that mints a *new* authority row, never a mutation of an existing
    one's approved checksum (§24.2's fail-closed corrected-export
    policy)."""

    __tablename__ = "legacy_migration_authorities"
    __table_args__ = (
        UniqueConstraint("approved_workbook_sha256", name="uq_legacy_migration_authorities_checksum"),
        CheckConstraint(
            "LENGTH(approved_workbook_sha256) = 64", name="ck_legacy_migration_authorities_checksum_length"
        ),
    )

    # Dataset/scope identifier distinguishing this authority from any
    # other, separately-approved migration authority a future correction
    # or a different historical dataset might introduce (§24.2). Free
    # text, application-owned -- e.g. "pr21_legacy_transaction_history_v1".
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_workbook_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())


class LegacyEquipmentEvent(UUIDPKMixin, Base):
    """§8.1. The event-first artifact PR21 V1 actually writes for imported
    history -- one independent, immutable historical `ISSUE`/`RECEIVE`
    fact, never a paired `BorrowTransaction` row (§12's finding: direct
    `BorrowTransaction` representation is structurally impossible for an
    unpaired `RECEIVE` and unsafe for an unpaired `ISSUE`).

    **Immutable by convention, deliberately no `updated_at` column.**
    Historical evidence is append-only (§27, §44) -- nothing in this
    slice's own scope ever updates a persisted row's identity/content
    columns in place (no CRUD function in this slice issues an `UPDATE`
    against this table at all). A generic `TimestampMixin`-style
    `updated_at` would misleadingly suggest in-place mutation is a
    supported operation; omitted rather than added and then never used.

    **`equipment_id`/`resolved_ward_id` use `ON DELETE RESTRICT`** (§19):
    historical evidence must remain durable -- deleting `Equipment` or a
    `Ward` that a permanent historical event still references is refused
    at the database level, never silently cascaded away."""

    __tablename__ = "legacy_equipment_events"
    __table_args__ = (
        CheckConstraint(f"event_type IN {LEGACY_EVENT_TYPES!r}", name="ck_legacy_equipment_events_event_type"),
        # §24.2's database-enforced logical event identity -- see this
        # module's own docstring for why `event_type` fills the design's
        # `dataset_type` tuple component rather than a separate column.
        UniqueConstraint(
            "migration_authority_id",
            "event_type",
            "legacy_source_row_key",
            name="uq_legacy_equipment_events_identity",
        ),
        Index("ix_legacy_equipment_events_equipment_id", "equipment_id"),
        Index("ix_legacy_equipment_events_import_session_id", "import_session_id"),
    )

    migration_authority_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_migration_authorities.id", ondelete="RESTRICT"), nullable=False
    )
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id", ondelete="RESTRICT"), nullable=False)
    # Not an `Equipment` lifecycle state (§18/§44, unchanged) -- this
    # event's own type, never conflated with `EquipmentStatus`.
    event_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # The source's own date+time, normalized to aware UTC (§22).
    # `business_date` is deliberately NOT stored here -- derived at read
    # time via the existing `business_date_and_shift()`, per event,
    # exactly as §23/§8.1 require; never backfilled or stored redundantly.
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    # §24.2: the source's own `ลำดับ`. Durable only in combination with
    # `migration_authority_id` (+ `event_type`, see this module's own
    # docstring) -- never treated as unique or durable on its own, and
    # never claimed durable beyond the one migration authority that
    # imported it. A data-bearing source row missing this key is an
    # `ERROR`-severity validation finding (§24.2, §15) -- no identity is
    # ever synthesized, so any row that actually reaches this table
    # always has a real value here.
    legacy_source_row_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # The source's own เลขที่ใบส่ง/เลขที่ใบรับเครื่อง (order/slip number),
    # preserved as business-reference provenance (§20's resolved
    # OD-PR21-5) -- never the database identity, never a `transaction_no`
    # substitute (`LegacyEquipmentEvent` has no `transaction_no` column
    # at all, §20.1). Nullable: not every source row is guaranteed to
    # carry one, and its presence/absence is not itself an identity or
    # validation concern this slice decides.
    legacy_order_reference: Mapped[str | None] = mapped_column(String(100))
    # Raw legacy Ward text, always preserved regardless of resolution
    # outcome (§14, OD-PR21-4). `resolved_ward_id` is nullable at the
    # schema level -- whether a blank/unresolved Ward is ever permitted
    # to reach this table at all (vs. blocking as `ERROR`) is a row-level
    # validation policy PR21B/C's own parser decides, not fixed here.
    legacy_ward_text: Mapped[str | None] = mapped_column(String(150))
    resolved_ward_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wards.id", ondelete="RESTRICT"))
    # Raw legacy BME/operator text, preserved permanently and verbatim
    # (§13, OD-PR21-3) -- never used to auto-create or auto-map a `User`
    # row. This is the authoritative location for this event's own
    # operator text; `LegacyEquipmentEventSourceRef` below deliberately
    # does not duplicate it (see that class's own docstring).
    legacy_bme_name: Mapped[str | None] = mapped_column(String(150))
    # Direct provenance anchors (§8.1's own field list; §26) -- every
    # `LegacyEquipmentEvent` in PR21 V1's single-workbook-per-session
    # topology (§7 Option A) is created by exactly one import run, so
    # these are a legitimate, non-conflicting defense-in-depth pointer
    # back to it, distinct from (and never overwriting) the finer-grained
    # per-row provenance `LegacyEquipmentEventSourceRef` carries. The
    # source checksum itself is deliberately NOT duplicated here -- it
    # lives only on each `LegacyEquipmentEventSourceRef` row, matching
    # §26's own "provenance refs" framing precisely.
    import_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    import_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sources.id", ondelete="RESTRICT"), nullable=False
    )
    # When this historical fact was imported into this system -- distinct
    # from `occurred_at` (when the historical fact itself happened).
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())


class LegacyEquipmentEventSourceRef(UUIDPKMixin, Base):
    """§8.1's simplified 1:N provenance -- up to two source refs per
    independent event (this event's own order-header row, this event's
    own line-item row), never up to four per paired transaction (the
    now-superseded §11 option (B) shape). Every imported transaction must
    be traceable back to its exact source row (§26): `import_session_id`,
    `import_source_id`, `source_checksum`, sheet/tab identifier, and
    source row number are captured per ref, matching §26's own field
    list exactly.

    **PR #103 fix round -- order-header rows are legitimately shared
    across multiple events, corrected here.** The workbook's own topology
    (§6.1, §9) is one order-header row (`Orders ยืมเครื่อง`/
    `Orders คืนเครื่อง`) describing an order that may cover *multiple*
    equipment line-items -- each line-item is its own
    `LegacyEquipmentEvent`, and every one of them legitimately needs a
    provenance ref back to the *same* header row. A single event
    registering the *same* physical source row twice is still forbidden
    (that would be a genuine double-count within one event's own
    provenance), but two *different* events sharing one header row is the
    normal, expected shape -- not a duplicate. The uniqueness scope below
    is therefore per-event: `(legacy_equipment_event_id, import_source_id,
    sheet_name, source_row_number)`, not merely
    `(import_source_id, sheet_name, source_row_number)`. Header-row
    sharing across events is provenance topology only -- it is not
    Issue<->Receive pairing (§11.2, unaffected) and creates no link
    between the events that share it.

    **Deliberately does not duplicate `event_type` or raw BME text.**
    `event_type` is already known transitively via
    `legacy_equipment_event_id` (a ref never belongs to more than one
    event, and an event's `event_type` never changes); duplicating it
    here would risk a second, potentially-diverging source of truth for
    the same fact. Raw legacy operator text lives on
    `LegacyEquipmentEvent.legacy_bme_name` (that class's own docstring)
    -- not repeated here, for the same reason."""

    __tablename__ = "legacy_equipment_event_source_refs"
    __table_args__ = (
        Index("ix_legacy_equipment_event_source_refs_event_id", "legacy_equipment_event_id"),
        # Defense-in-depth, scoped per event (PR #103 fix round): the
        # same physical source row is never attributed to two different
        # provenance refs *belonging to the same event*, but is
        # explicitly allowed to be shared by multiple distinct events (an
        # order-header row covering several equipment line-items, §6.1/
        # §9). §24.2's own Level 1 identity -- `(import_source_id,
        # sheet_name, source_row_number)` -- artifact-scoped, not durable
        # across a re-upload, and never itself the logical event identity
        # (that is `uq_legacy_equipment_events_identity` above, entirely
        # unaffected by this constraint's scope).
        UniqueConstraint(
            "legacy_equipment_event_id",
            "import_source_id",
            "sheet_name",
            "source_row_number",
            name="uq_legacy_equipment_event_source_refs_event_source_row",
        ),
    )

    legacy_equipment_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_equipment_events.id", ondelete="RESTRICT"), nullable=False
    )
    import_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    import_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("import_sources.id", ondelete="RESTRICT"), nullable=False
    )
    # Defense-in-depth copy, mirroring `ImportSource.checksum` (§26) --
    # never itself a source of truth, never read instead of
    # `ImportSource.checksum`.
    source_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)


class LegacyWardAlias(UUIDPKMixin, Base):
    """§14, OD-PR21-4 (RESOLVED, Owner Decision Closure Round 1).
    Administrator-owned, explicit, auditable, persisted Ward alias
    mapping table -- confirmed absent from `master_data.py` (§43's own
    gap-analysis finding). Exact-string match only: `raw_alias` is
    unique, so a given legacy Ward text resolves to exactly one `Ward` or
    it does not resolve at all (an `ERROR`-severity validation finding,
    decided by PR21B/C's own parser, not this slice). No fuzzy/similarity
    matching mechanism exists anywhere in this table's own schema --
    resolving `raw_alias` is a plain equality lookup. Normalization
    (trimming, case-folding) of `raw_alias` before insert/lookup is an
    application-layer concern, not enforced by this table."""

    __tablename__ = "legacy_ward_aliases"
    __table_args__ = (UniqueConstraint("raw_alias", name="uq_legacy_ward_aliases_raw_alias"),)

    raw_alias: Mapped[str] = mapped_column(String(150), nullable=False)
    ward_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wards.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())


class LegacyHistoryDryRunPlan(UUIDPKMixin, Base):
    """§36. PR21-owned persisted dry-run plan header, registered against
    PR21-Foundation's generic `DryRunPlanProvider` interface (merged as
    GitHub PR #100) -- mirrors `EquipmentMasterDryRunPlan`'s own proven
    shape (immutable header + rows, `active`/`superseded`/`consumed`/
    `failed` lifecycle, explicit confirm gate, at most one `active` plan
    per session) rather than reusing that upsert-oriented table directly
    (§36: PR21's own insert-oriented historical-event import does not fit
    Equipment Master's `action IN ('CREATE','UPDATE','SKIP')` shape).

    **Not yet written by any adapter in this slice** -- no PR21 parser
    exists yet (PR21B/C), so `insert_plan`/`bulk_insert_plan_rows`
    (`app.crud.legacy_history_dry_run_plan`) have no production caller
    until a later slice's adapter calls them. Exercised directly by this
    slice's own tests, exactly as PR21-Foundation's own provider
    abstraction was built and tested before any concrete PR21 provider
    existed."""

    __tablename__ = "legacy_history_dry_run_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','superseded','consumed','failed')",
            name="ck_legacy_history_dry_run_plans_status",
        ),
        CheckConstraint(
            "(confirmed_at IS NULL) = (confirmed_by_user_id IS NULL)",
            name="ck_legacy_history_dry_run_plans_confirmed_pair",
        ),
        CheckConstraint("summary_total_rows >= 0", name="ck_legacy_history_dry_run_plans_summary_total_rows"),
        CheckConstraint(
            "summary_issue_events >= 0", name="ck_legacy_history_dry_run_plans_summary_issue_events"
        ),
        CheckConstraint(
            "summary_receive_events >= 0", name="ck_legacy_history_dry_run_plans_summary_receive_events"
        ),
        CheckConstraint("summary_warnings >= 0", name="ck_legacy_history_dry_run_plans_summary_warnings"),
        CheckConstraint(
            "summary_blocking_conflicts >= 0", name="ck_legacy_history_dry_run_plans_summary_blocking_conflicts"
        ),
        # Same composite-FK "ownership" pair as
        # `EquipmentMasterDryRunPlan` (§14.2's proven pattern) -- proves
        # both job ids actually belong to *this* session.
        ForeignKeyConstraint(
            ["import_session_id", "accepted_validation_job_id"],
            ["import_jobs.import_session_id", "import_jobs.id"],
            name="fk_legacy_history_dry_run_plans_accepted_validation_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["import_session_id", "dry_run_job_id"],
            ["import_jobs.import_session_id", "import_jobs.id"],
            name="fk_legacy_history_dry_run_plans_dry_run_job",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "import_session_id", "dry_run_job_id", name="uq_legacy_history_dry_run_plans_session_dry_run_job"
        ),
        Index(
            "uq_legacy_history_dry_run_plans_one_active_per_session",
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
    migration_authority_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_migration_authorities.id", ondelete="RESTRICT"), nullable=False
    )
    # Defense-in-depth copy -- must match import_sources.checksum,
    # mirroring `EquipmentMasterDryRunPlan.source_checksum`'s identical
    # rationale; never itself a source of truth.
    source_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    accepted_validation_job_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    dry_run_job_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    summary_total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_issue_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_receive_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_warnings: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    summary_blocking_conflicts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class LegacyHistoryDryRunPlanRow(UUIDPKMixin, Base):
    """§36. One planned historical-event row, belonging to exactly one
    `LegacyHistoryDryRunPlan`. A generic, typed-but-flexible shape
    sufficient for a later canonical parser's output (PR21B/C) without
    importing any SDC-sheet semantics (§6.1's ambiguity remains open and
    is not decided by this slice): `event_type`/`source_row_number`/
    `legacy_source_row_key` are real, typed, structural columns (never
    hidden inside an opaque blob); `normalized_values`/`warnings` are the
    same JSON-blob pattern `EquipmentMasterDryRunPlanRow` already uses for
    genuinely dataset-specific content that varies by parser."""

    __tablename__ = "legacy_history_dry_run_plan_rows"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN {LEGACY_EVENT_TYPES!r}", name="ck_legacy_history_dry_run_plan_rows_event_type"
        ),
        UniqueConstraint(
            "dry_run_plan_id", "source_row_number", name="uq_legacy_history_dry_run_plan_rows_plan_row_number"
        ),
        Index("ix_legacy_history_dry_run_plan_rows_plan_id", "dry_run_plan_id"),
    )

    dry_run_plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("legacy_history_dry_run_plans.id", ondelete="RESTRICT"), nullable=False
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Never blank on a real plan row -- a plan is only ever created for a
    # fully-passing (zero-`ERROR`) validation snapshot (§28), and a
    # blank/missing key is itself an `ERROR`-severity finding (§24.2)
    # that blocks plan creation entirely.
    legacy_source_row_key: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_values: Mapped[dict | None] = mapped_column(_DryRunPlanJSONType)
    warnings: Mapped[list | None] = mapped_column(_DryRunPlanJSONType)
