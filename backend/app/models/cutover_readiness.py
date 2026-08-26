"""Roadmap PR23B -- Cutover Readiness Evidence Foundation.

Authoritative design: `docs/design/PR23_CUTOVER_READINESS_PLAN.md` (§9
temporal boundary/`cutover_instant`, §10 current equipment state, §11
outstanding/open transactions, §12 Gate D/E, §15 evidence/audit, §16
concurrency/freshness, §26 OD-PR23-1 through OD-PR23-6, all RESOLVED /
OWNER APPROVED per the PR23 Owner Decision Closure round). Refined by
the PR23B implementation task's own binding field contract. Do not
restate the design rationale here -- read that document for it.

**Scope boundary (this slice only): persistence/schema foundation
only.** No readiness-gate evaluation logic (Gates A-G, PR23C's own
job), no Go/No-Go decision/sign-off logic (PR23D's own job), no
frontend (PR23E), no pilot/cutover/rollback execution (PR23F and
beyond), no `AppSheet` integration change, and no Ward-transfer
workflow of any kind.

**One flat table, not a "God table."** A `CutoverReadinessRun` carries
a small, *fixed* set of evidence-reference columns (never a repeating
or variable-cardinality collection) -- each existing, permanent
evidence artifact from PR20/PR21/PR22 is referenced by id, never
duplicated. This mirrors `LegacyReconciliationSignOff`'s own choice to
embed `attestation_summary` on one row rather than a normalized child
table: none of these reference columns has an independent lifecycle of
its own, so a separate child table would only add join complexity with
no corresponding modeling benefit (§18 of the task: "avoid
over-normalization that adds tables with no independent lifecycle").
Per §17 of the task ("prefer the smallest coherent foundation"), this
slice deliberately does **not** introduce a separate Go/No-Go/decision
table -- OD-PR23-6 approves that a future PR23D-or-later slice may add
its own additive decision/sign-off table referencing
`cutover_readiness_runs.id`, exactly as `LegacyReconciliationSignOff`
references `legacy_reconciliation_runs.id` -- so nothing about this
run's own shape needs to anticipate or hard-code Go/No-Go semantics.

**Completion semantics (read this before writing a completion call
site).** `status = 'completed'` means only: *this run's immutable
evidence snapshot was successfully captured* -- every mandatory
evidence reference exists, was validated to exist, and is now
permanently bound to this row. It does **not** mean "ready for
cutover," "Go approved," or "production ready" -- no gate evaluation,
BLOCKER/WARNING/INFO classification, or Go/No-Go judgment is expressed
by this status value or by any other field on this table. That
judgment belongs to a later PR23 slice.

**Immutability.** Once `status = 'completed'`, this row's evidence
columns are never again mutated by any call site in this codebase --
re-evaluating readiness after any evidence changes creates a **new**
`CutoverReadinessRun` row, superseding the prior one via
`supersedes_run_id` (self-referencing FK, `ON DELETE RESTRICT`,
self-supersession rejected by CHECK) -- the exact same forward-only
supersession discipline `LegacyReconciliationRun.supersedes_run_id`
already established (OD-PR22-3). A prior (possibly completed) run is
never reopened or mutated to record that a later run supersedes it.

**`cutover_instant` is never inferred.** It is an explicit,
governance-provided value (§9 of the design) -- never derived from
`MIN`/`MAX` timestamps, import dates, or `created_at`. This module
imposes no DB-level CHECK tying it to the bound coverage artifact's
`live_system_start` (that comparison requires a cross-row join a CHECK
constraint cannot express); the completion service function validates
`cutover_instant >= coverage.live_system_start` instead (§9: "cutover_
instant must never be earlier than the signed-off run's live_system_
start").

**Reference, never recompute.** `reconciliation_run_id`/
`reconciliation_signoff_id` point at PR22's own immutable evidence;
this module never recomputes finding/disposition counts or attestation
content -- `LegacyReconciliationSignOff.attestation_summary` remains
the sole source of that evidence. Likewise `equipment_master_import_
source_id`/`legacy_migration_authority_id`/`legacy_coverage_id`
reference PR20/PR21/PR22's own provenance identities, never duplicating
workbook contents or re-deriving temporal coverage.

**One provenance chain, not four independent references (PR23B Fix
Round 1).** `legacy_migration_authority_id`, `legacy_coverage_id`,
`reconciliation_run_id`, and `reconciliation_signoff_id` are not
validated for existence alone -- `app.crud.cutover_readiness.
_validate_evidence` also proves `legacy_coverage_id`'s own
`migration_authority_id` matches `legacy_migration_authority_id`, and
`reconciliation_run_id`'s own `coverage_id` matches
`legacy_coverage_id` (the pre-existing `reconciliation_signoff_id.
run_id == reconciliation_run_id` check completes the chain:
`MigrationAuthority -> Coverage -> ReconciliationRun -> SignOff`). A
column-level FK only proves each id resolves to *some* row of the
right type; it cannot express that those rows are mutually consistent
with each other, so this binding is enforced in the completion
service, not the schema.

**Current-state verification is evidence, not mutation.** `current_
state_verified_at`/`current_state_verified_by_user_id`/`current_state_
verification_scope_count`/`current_state_verification_reference` record
that a manual/physical verification occurred (§10/§11/§12 Gate E of the
design) -- they never trigger, and no call site in this module ever
performs, any mutation of `Equipment.status`, `Equipment.version`,
`BorrowTransaction`, or `LegacyEquipmentEvent`. `current_state_
verification_reference` is a short operational label/reference only
(e.g. a runbook checklist id) -- never free-form clinical/PHI content.

**Pilot Ward is a reference, never a new identity.** `pilot_ward_id`
references an existing `Ward` row (OD-PR23-5: resolved from existing
Ward/department master data corresponding to the legacy `แผนกที่ยืม`
value) -- this module never stores raw legacy Ward text as an
authoritative identity and introduces no Pilot-only Ward taxonomy.
Nullable: not every readiness run is necessarily Pilot-scoped, and it
is deliberately excluded from the mandatory completion-evidence CHECK
below.

**No fourth role, no accountable-authority FK.** `operational_
approver_reference` is a short, optional, non-enforced text reference
only (OD-PR23-3: Go/No-Go accountability is operational governance,
recorded outside the application's role system) -- never a FK to
`User`, since the accountable authority is not necessarily an
application account holder.

Mirrors every established modeling convention in this repository (see
`app.models.legacy_reconciliation`/`app.models.legacy_history`/
`app.models.import_session` for the originals, not restated here in
full): `UUIDPKMixin` alone (never `TimestampMixin`) since this table
has no mutable `updated_at` (it uses an explicit `version` CAS column
instead); `UTCDateTime` for every timestamptz column; enum-shaped
columns are a plain `String` plus an explicitly named `CheckConstraint`
(`ck_<table>_<field>`); the paired-nullability CHECK pattern for "all
null or all set" coherence (`completed_at`/`completed_by_user_id`,
`current_state_verified_at`/`current_state_verified_by_user_id`); `ON
DELETE RESTRICT` on every FK to a permanent-evidence/User/Ward table;
and a `version` CAS column mirroring `LegacyReconciliationRun.version`'s
exact shape.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.models.mixins import UTCDateTime, UUIDPKMixin

# Roadmap PR23D (docs/design/PR23_CUTOVER_READINESS_PLAN.md §12 Gate G,
# §13, §26 OD-PR23-3/OD-PR23-6). Same PostgreSQL-JSONB/SQLite-JSON
# variant type already used by `app.models.legacy_reconciliation`/
# `app.models.import_session` -- not a new pattern.
_DecisionJSONType = JSONB().with_variant(JSON(), "sqlite")

# §7 of the task. `running` is reserved for a future PR23C-or-later slice
# that may perform multi-step evidence gathering before completion -- no
# call site in this module ever transitions a run into `running`; PR23B's
# own lifecycle is `pending` -> `completed` (via `complete_readiness_run`)
# with `failed` reserved for a future explicit failure path. No
# `approved`/`go`/`no_go`/`cutover_complete`/`rolled_back` value exists --
# those are Go/No-Go semantics, deliberately out of this slice's scope.
CUTOVER_READINESS_RUN_STATUSES = ("pending", "running", "completed", "failed")

# §1/OD-PR23-1 of the PR23 Owner Decision Closure round: hard cutover
# (Option A) is the sole Owner-approved source-of-truth transition
# strategy. A closed, bounded domain (not free text) so a future Owner
# Decision approving an additional strategy is a explicit, reviewable
# migration, never a silent free-text drift.
CUTOVER_SOURCE_OF_TRUTH_STRATEGIES = ("hard_cutover",)


class CutoverReadinessRun(UUIDPKMixin, Base):
    """§5-19 of the task. One cutover-readiness evidence-capture attempt.
    See the module docstring for the full completion/immutability/
    supersession contract -- not repeated per-column below."""

    __tablename__ = "cutover_readiness_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="ck_cutover_readiness_runs_status",
        ),
        CheckConstraint("version >= 0", name="ck_cutover_readiness_runs_version"),
        CheckConstraint(
            "source_of_truth_strategy IN ('hard_cutover')",
            name="ck_cutover_readiness_runs_source_of_truth_strategy",
        ),
        CheckConstraint(
            "LENGTH(application_baseline_sha) = 40",
            name="ck_cutover_readiness_runs_baseline_sha_length",
        ),
        CheckConstraint(
            "(completed_at IS NULL) = (completed_by_user_id IS NULL)",
            name="ck_cutover_readiness_runs_completed_pair",
        ),
        CheckConstraint(
            "(current_state_verified_at IS NULL) = (current_state_verified_by_user_id IS NULL)",
            name="ck_cutover_readiness_runs_verification_pair",
        ),
        CheckConstraint(
            "current_state_verification_scope_count IS NULL OR current_state_verification_scope_count >= 0",
            name="ck_cutover_readiness_runs_verification_scope_nonneg",
        ),
        CheckConstraint(
            "supersedes_run_id IS NULL OR supersedes_run_id <> id",
            name="ck_cutover_readiness_runs_no_self_supersession",
        ),
        # §6/§27/§30 of the task: completion means the immutable evidence
        # snapshot is fully captured -- every mandatory evidence reference
        # (everything except the optional Pilot Ward and the informational
        # operational-approver reference) must be non-NULL before status
        # may become 'completed'. Enforced at the database level, not only
        # in the service layer, so no code path -- present or future -- can
        # ever mark a run 'completed' with a partial snapshot.
        CheckConstraint(
            "status <> 'completed' OR ("
            "equipment_master_import_source_id IS NOT NULL AND "
            "legacy_migration_authority_id IS NOT NULL AND "
            "legacy_coverage_id IS NOT NULL AND "
            "reconciliation_run_id IS NOT NULL AND "
            "reconciliation_signoff_id IS NOT NULL AND "
            "current_state_verified_at IS NOT NULL AND "
            "current_state_verified_by_user_id IS NOT NULL AND "
            "completed_at IS NOT NULL AND "
            "completed_by_user_id IS NOT NULL"
            ")",
            name="ck_cutover_readiness_runs_completion_requires_evidence",
        ),
        Index("ix_cutover_readiness_runs_created_at", "created_at"),
        Index("ix_cutover_readiness_runs_status", "status"),
        Index("ix_cutover_readiness_runs_supersedes_run_id", "supersedes_run_id"),
        Index("ix_cutover_readiness_runs_reconciliation_run_id", "reconciliation_run_id"),
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    # Optimistic-concurrency counter, mirroring `LegacyReconciliationRun
    # .version`'s exact shape -- incremented by exactly 1 on the CAS
    # `UPDATE` that transitions a run to 'completed' (PR23C/D's own future
    # freshness checks will read this too, per §16 of the design).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    # Full 40-character git SHA-1 hex of the application's own real
    # squash-merge baseline at the time this run was created (§15 of the
    # design: "Application baseline SHA... at deployment time") --
    # supplied by the caller (the deploying/operating context), never
    # inferred by this module.
    application_baseline_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    # `alembic_version.version_num`'s own revision-id string (e.g.
    # `0021_cutover_readiness`), read from the database's own
    # `alembic_version` table by
    # `app.crud.cutover_readiness._get_current_database_migration_head`
    # at creation time -- not a request-body field on
    # `RunCreateRequest` at all (PR23B Fix Round 1), matching this
    # module's "reference, never trust client input for machine-owned
    # facts" discipline. Must prove the actual schema state at capture
    # time; a client-supplied value could never do that.
    database_migration_head: Mapped[str] = mapped_column(String(255), nullable=False)
    source_of_truth_strategy: Mapped[str] = mapped_column(
        String(30), nullable=False, default="hard_cutover", server_default=text("'hard_cutover'")
    )
    # §9 of the design. Explicit, governance-provided -- never inferred.
    cutover_instant: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    # §17 of the design (freeze window T0-T4). A short operational
    # reference/label only (e.g. a runbook section id) -- this slice
    # persists no actual freeze duration or schedule, since neither is
    # architecturally determined yet (OD-PR23-1).
    freeze_window_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # §15 of the design: PR20's `ImportSource` identity -- the Equipment
    # Master import authority/source reference. Nullable until captured at
    # completion (§30: partial evidence is never accepted).
    equipment_master_import_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("import_sources.id", ondelete="RESTRICT"), nullable=True
    )
    # §15 of the design: PR21's `LegacyMigrationAuthority` checksum-approval
    # identity -- the legacy transaction import authority/source reference.
    legacy_migration_authority_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legacy_migration_authorities.id", ondelete="RESTRICT"), nullable=True
    )
    # §9/§15 of the design (OD-PR22-7's governed two-boundary temporal
    # coverage artifact) -- the single authoritative reference for
    # `legacy_coverage_start`/`legacy_coverage_end`/`live_system_start`.
    # Deliberately a reference only, never a redundant copy of those three
    # timestamps on this row -- unlike `LegacyReconciliationRun`'s own
    # snapshot-copy columns (which exist because a reconciliation run's
    # analysis must remain reproducible even if the coverage row were ever
    # superseded), a cutover readiness run has no analogous reproducibility
    # requirement over that specific data; the coverage row itself is
    # already immutable/append-only (never `UPDATE`d).
    legacy_coverage_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legacy_migration_authority_coverages.id", ondelete="RESTRICT"), nullable=True
    )
    # §15 of the design: PR22's `LegacyReconciliationRun.id` -- the
    # reconciliation run ID this cutover is evaluated against.
    reconciliation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legacy_reconciliation_runs.id", ondelete="RESTRICT"), nullable=True
    )
    # §12 Gate D / §15 of the design: PR22's `LegacyReconciliationSignOff
    # .id` -- OD-PR22-6's four sign-off conditions are satisfied by this
    # sign-off's own existence; this module never re-derives them. The
    # completion service validates `signoff.run_id ==
    # reconciliation_run_id` (application-level, since no DB-level
    # composite-FK target exists on `legacy_reconciliation_signoffs` for
    # this pairing).
    reconciliation_signoff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("legacy_reconciliation_signoffs.id", ondelete="RESTRICT"), nullable=True
    )
    # §10/§11/§12 Gate E of the design: current-state verification
    # evidence -- what was checked, by whom, when, and how many records.
    # Paired with `current_state_verified_by_user_id` (see the CHECK
    # above); "who/when" is mandatory together, "how many"/"reference" are
    # independently optional informational detail.
    current_state_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    current_state_verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    current_state_verification_scope_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A short operational reference/label only (e.g. a checklist or
    # verification-log id) -- never free-form clinical/PHI content; no
    # equipment list, ward roster, or patient-adjacent detail is ever
    # stored here.
    current_state_verification_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # OD-PR23-5: the single controlled Pilot Ward, referenced (never a new
    # Ward identity). Nullable and deliberately excluded from the
    # mandatory completion-evidence CHECK above -- not every readiness run
    # is necessarily Pilot-scoped.
    pilot_ward_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wards.id", ondelete="RESTRICT"), nullable=True)
    # OD-PR23-3: an optional, unenforced text placeholder for the
    # operational-governance accountable authority -- never a FK to
    # `User`, and never itself a basis for any authorization decision in
    # this slice.
    operational_approver_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Forward-only supersession, mirroring
    # `LegacyReconciliationRun.supersedes_run_id`'s exact discipline
    # (OD-PR22-3's pattern, reused here) -- re-evaluating readiness after
    # any evidence changes creates a new run referencing the prior one via
    # this column; the prior run is never itself mutated.
    supersedes_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cutover_readiness_runs.id", ondelete="RESTRICT"), nullable=True
    )


# Roadmap PR23D. §12 Gate G / §13's closed BLOCKER/WARNING/INFO category
# domain does not apply here -- this is the final decision *value*
# domain, a different concept. `PENDING`/`APPROVED`/`REJECTED`/
# `CUTOVER`/`MIGRATING` are deliberately not introduced -- Go/No-Go is
# cutover governance evidence, not an Equipment lifecycle state (§40 of
# the task; `app.models.equipment.EquipmentStatus` is untouched by this
# module).
CUTOVER_GO_NO_GO_DECISIONS = ("GO", "NO_GO")


class CutoverGoNoGoDecision(UUIDPKMixin, Base):
    """Roadmap PR23D (docs/design/PR23_CUTOVER_READINESS_PLAN.md §12 Gate
    G, §13 Go/No-Go, §14 Authorization, §15 Evidence/Audit, §16
    Concurrency/Freshness, §26 OD-PR23-3/OD-PR23-6). The immutable final
    Go/No-Go decision for one `CutoverReadinessRun` -- exactly the
    additive decision/sign-off table the PR23B model docstring already
    anticipated ("a future PR23D-or-later slice may add its own
    additive decision/sign-off table referencing cutover_readiness_
    runs.id, exactly as LegacyReconciliationSignOff references
    legacy_reconciliation_runs.id"). Mirrors `LegacyReconciliationSignOff`'s
    shape: `UNIQUE(cutover_readiness_run_id)` enforces at most one final
    decision per run at the schema level; no mutable fields, no update
    timestamp -- a decision is never edited after creation. If readiness
    changes after a decision was recorded, a **new** `CutoverReadinessRun`
    (via `supersedes_run_id`) is created and a fresh decision recorded
    against it -- this row is never reopened or mutated (mirrors
    `CutoverReadinessRun`'s own forward-only supersession discipline;
    see that model's docstring).

    **Never a persisted gate-evaluation snapshot.** Design §13
    deliberately does not introduce a persisted BLOCKER/WARNING/INFO
    model -- `app.services.cutover_readiness_gates.evaluate_gates` is
    computed fresh on every call, never stored. This table therefore
    does not duplicate that evaluation; `run_version_at_decision`
    (mirroring `LegacyReconciliationSignOff.run_version_at_signoff`'s
    exact freshness-proof shape) records which exact `CutoverReadinessRun
    .version` was observed, live, at the moment this decision was
    recorded -- proof of freshness without a redundant persisted
    evaluation. `acknowledged_warning_codes` records exactly which
    currently-live WARNING item codes the approver acknowledged for a
    `GO` decision (§13: "Go remains possible but the approver must
    explicitly acknowledge each WARNING") -- always the empty array for
    `NO_GO`, since a `NO_GO` decision never requires or considers
    warnings (recording that cutover does not proceed needs no
    readiness justification). Acknowledgement here means *the
    accountable approver explicitly reviewed/accepted this item for the
    GO decision*, never that the application itself independently
    verified the underlying operational fact -- see `app.services.
    cutover_readiness_gates`'s own "Honesty over automation theater"
    docstring section; this table preserves, never collapses, that
    distinction.

    **No fourth role, no accountable-authority FK (OD-PR23-3).**
    `recorded_by_user_id` is the `administrator` application account
    that recorded the decision -- not necessarily the same individual
    as the operationally accountable approver, whose identity is
    recorded outside the application's role system (see
    `CutoverReadinessRun.operational_approver_reference`'s identical
    rationale). This table introduces no new accountable-authority FK
    of its own.

    **No PHI, no secrets, no workbook duplication** -- `no_go_reason` is
    a short, optional, bounded operational text field only (never
    authoritative readiness logic, never clinical/patient content), the
    same discipline `CutoverReadinessRun.current_state_verification_
    reference` already establishes."""

    __tablename__ = "cutover_go_no_go_decisions"
    __table_args__ = (
        UniqueConstraint(
            "cutover_readiness_run_id", name="uq_cutover_go_no_go_decisions_cutover_readiness_run_id"
        ),
        CheckConstraint("decision IN ('GO','NO_GO')", name="ck_cutover_go_no_go_decisions_decision"),
        CheckConstraint(
            "run_version_at_decision >= 0", name="ck_cutover_go_no_go_decisions_run_version_at_decision"
        ),
        CheckConstraint("LENGTH(no_go_reason) <= 2000", name="ck_cutover_go_no_go_decisions_no_go_reason_length"),
        Index("ix_cutover_go_no_go_decisions_recorded_at", "recorded_at"),
    )

    cutover_readiness_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cutover_readiness_runs.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    # Freshness proof (§16) -- the exact `CutoverReadinessRun.version`
    # CAS value observed, live, under lock, at the moment this decision
    # was recorded. Mirrors `LegacyReconciliationSignOff.run_version_at_
    # signoff`'s identical purpose and shape.
    run_version_at_decision: Mapped[int] = mapped_column(Integer, nullable=False)
    # Always `[]` for `NO_GO`. For `GO`, the canonical (sorted, backend-
    # computed) list of every currently-live WARNING item `code` (per
    # `app.services.cutover_readiness_gates`) the approver acknowledged
    # at decision time -- never the raw, unvalidated client payload, so
    # a stale/unknown code the client sent can never appear here (see
    # `app.crud.cutover_readiness.create_go_no_go_decision`'s own
    # docstring for the exact acknowledgement-coverage check).
    acknowledged_warning_codes: Mapped[list] = mapped_column(_DecisionJSONType, nullable=False, default=list)
    no_go_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
