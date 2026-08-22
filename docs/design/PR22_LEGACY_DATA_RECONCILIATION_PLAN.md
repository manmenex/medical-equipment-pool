# Roadmap PR22 — Legacy Data Validation and Reconciliation: Design Specification

**Status:** DESIGN MERGED (GitHub PR #112, folded into baseline
`c924d8ba2c8c5d933ea36ea3d488e2550615df40`). All seven Owner Decisions
(OD-PR22-1 through OD-PR22-7, §36) are **RESOLVED / OWNER APPROVED**.
**Implementation is still not started** — no `backend/**`, `frontend/**`,
`alembic/**`, or `tests/**` file is created or modified by this document
or by the PR22 Owner Decision Closure round that resolved §36; every
PR22B-G implementation slice becomes eligible only after the governance
PR recording this closure round itself merges (§34).

**Baseline (this closure round):** `c802d66c9d1e5395cd20591c451ebdc0cefbf7df`
— the real squash-merge SHA of GitHub PR #113 (the post-PR22A
governance synchronization), independently re-verified against `git
log`/`git rev-parse` before this branch was created. `c802d66...`
follows `c924d8ba2c8c5d933ea36ea3d488e2550615df40` (GitHub PR #112,
this design's own merge) and `e07a36aa8482b7b97368a6adb9cfcc81c93d0ee0`
(GitHub PR #111, PR21F — Governance Sync and Roadmap PR21 Closure). With
PR21F merged, Roadmap PR21 (Legacy Receive and Issue History Import) is
fully complete — implementation (Foundation, A, B, C, D1, D2, E0, E) and
governance are both merged. This design's own dependency, "PR20 and PR21
both complete" (`docs/audits/04-consolidated-implementation-plan.md`
Part D, quoted in §3 below), is satisfied.

**Purpose:** Design Roadmap PR22 — Legacy Data Validation and
Reconciliation — the workflow by which a hospital operator (in practice,
an Administrator) validates and reconciles the legacy data already
imported by PR20 (Equipment Master) and PR21 (Receive/Issue history)
against the actual current system state, before Roadmap PR23 (Cutover
Readiness) and PR24 (Go-live).

**This is not another import pipeline.** PR22 reads what PR20/PR21
already wrote; it does not create new `Equipment` rows, new
`LegacyEquipmentEvent` rows, or new source imports. Its own output is a
new kind of evidence — a reconciliation run, its findings, and an
eventual sign-off — layered on top of already-immutable historical data.

---

## 1. Status

DESIGN MERGED; all seven Owner Decisions RESOLVED / OWNER APPROVED
(§36); implementation still not started, as stated above. This
document's own governance footprint remains minimal by design: this
Owner Decision Closure round records that the Owner approved OD-PR22-1
through OD-PR22-7, and nothing more — it does not itself mark any
implementation slice as begun, only as eligible (§34).

---

## 2. Purpose

Restated from the header, with scope boundary: PR22 must define, precisely
enough to implement without further architecture debate:

- what "reconciled" means for legacy-imported data (§9-§15);
- how a reconciliation analysis run is computed, persisted, and made
  reproducible (§17-§18);
- how a human reviews and disposes of findings, and what a sign-off
  actually attests to (§19-§20);
- the authorization, concurrency, lock-ordering, API, and error
  contracts that support that workflow (§21-§23, §25-§26);
- performance, audit, retention, and privacy requirements given the real
  ~51,000-row dataset scale already established by PR21 (§27-§29);
- a minimized set of genuine Owner Decisions this design cannot resolve
  on its own (§36).

---

## 3. Dependencies

Per `docs/audits/04-consolidated-implementation-plan.md` Part D (quoted
verbatim, `docs/audits/04-consolidated-implementation-plan.md:552-556`):

> #### PR22 — Legacy Data Validation and Reconciliation
> - **Objective:** Perform cross-import validation and reconciliation,
>   verify source traceability, review duplicates, and validate the
>   unified display of legacy and new transaction history before Go-live.
> - **Dependencies:** PR20, PR21.

Both dependencies are merged and complete:

- **PR20 (Equipment Master Import):** PR20A-F, GitHub PR #90/#91/#93/#94/#95/#96,
  squash SHA `2743af849702ef551927b9c362421df08c80b5d9` (PR20's own final
  baseline at the time — since superseded as the repository's current
  baseline; see `docs/ROADMAP.md`).
- **PR21 (Legacy Receive and Issue History Import):** Foundation through
  E, GitHub PR #100/#103/#104/#105/#107/#108/#109/#110, plus governance
  closure GitHub PR #111, squash SHA
  `e07a36aa8482b7b97368a6adb9cfcc81c93d0ee0` — this design's own baseline.

PR22 is unblocked from a dependency-ordering standpoint. This design does
not begin, define, or scope PR23 or PR24.

---

## 4. Existing authoritative state

This section is the required-reading record: every claim below was
independently verified against merged code, not copied from prose or
from this conversation's own memory. File:line citations are exact as of
this design's baseline.

### 4.1 `LegacyEquipmentEvent` and PR21's six-table schema

Source: `backend/app/models/legacy_history.py`, migration
`backend/alembic/versions/0019_legacy_history_foundation.py` (revision
`0019_legacy_history_foundation`, merged as GitHub PR #103, with fix
rounds folded into the same migration file).

**`legacy_equipment_events`** (`legacy_history.py:113-247`) — the
permanent historical record. Columns: `id` (UUID PK), `migration_authority_id`
(UUID, NOT NULL, FK → `legacy_migration_authorities.id` ON DELETE
RESTRICT), `equipment_id` (UUID, **NOT NULL**, FK → `equipment.id` ON
DELETE RESTRICT), `event_type` (`VARCHAR(10)`, NOT NULL, CHECK
`IN ('ISSUE','RECEIVE')`), `occurred_at` (`TIMESTAMP WITH TIME ZONE`, NOT
NULL — no stored `business_date`, derived at read time), `legacy_source_row_key`
(`VARCHAR(64)`, NOT NULL — the source's `ลำดับ`), `legacy_order_reference`
(`VARCHAR(100)`, nullable), `legacy_ward_text` (`VARCHAR(150)`, nullable),
`resolved_ward_id` (UUID, **nullable**, FK → `wards.id` ON DELETE
RESTRICT), `legacy_bme_name` (`VARCHAR(150)`, nullable, raw text only,
never auto-mapped to a `User` row), `import_session_id` (UUID, NOT NULL),
`import_source_id` (UUID, NOT NULL, proven valid only via a composite FK,
never a plain one), `imported_at` (NOT NULL, `server_default=func.now()`).
**No `updated_at` column** — deliberately omitted; the table is immutable
by convention (`legacy_history.py:120-126`).

The composite identity/uniqueness constraint PR22 must treat as
authoritative: `UniqueConstraint("migration_authority_id", "event_type",
"legacy_source_row_key", name="uq_legacy_equipment_events_identity")`
(`legacy_history.py:156-161`; raw DDL confirmed at
`0019_legacy_history_foundation.py:123-124`). This is PR21's own
write-time idempotency guarantee — **PR22 must never duplicate or
re-implement this; it can only read against it (§6 below).**

The other five tables PR21A created: `legacy_migration_authorities`
(§4.2), `legacy_equipment_event_source_refs` (per-event provenance,
scoped per event since one order-header row can legitimately be shared
by multiple events), `legacy_ward_aliases` (§4.3), and
`legacy_history_dry_run_plans`/`legacy_history_dry_run_plan_rows` (PR21's
own pre-execution staging tables — not consulted by PR22, which only
reads already-executed, permanent `legacy_equipment_events` rows).

**Confirmed absent: no pairing/link table between events.** The model
file's own module docstring states this is an explicit scope boundary
(`legacy_history.py:12-15`); a repo-wide grep for pairing/link-table
implementations found only comments confirming its absence (e.g.
`backend/app/services/import_adapters/legacy_history/combined.py:32`:
"No Issue↔Receive pairing (§4/§55.4)"), never an actual table.

### 4.2 `LegacyMigrationAuthority`

`legacy_history.py:77-110`, table `legacy_migration_authorities`.
Columns: `id`, `scope` (`VARCHAR(100)`, NOT NULL, free-text
application-owned identifier, e.g. `"pr21_legacy_transaction_history_v1"`),
`approved_workbook_sha256` (`VARCHAR(64)`, NOT NULL, **UNIQUE**),
`approved_by_user_id` (FK → `users.id`), `approved_at`, `created_at`.

Sole production write path: `create_or_get_approval()`
(`backend/app/crud/legacy_migration_authority.py:49-107`),
Administrator-gated. Race-safe insert-then-catch-`IntegrityError`
pattern; same checksum + same scope → returns existing row unchanged
(`created=False`, approval fields never rewritten); same checksum +
different scope → `LegacyMigrationAuthorityScopeConflictError` (409).
**Never updated or deleted after creation** — confirmed by the model's
own docstring and an empty repo-wide grep for update/delete call sites
(`legacy_history.py:85-92`). A corrected workbook requires minting a
**new** authority row, never mutating an existing one.

### 4.3 `LegacyWardAlias` — already exists, added by PR21A, not new to PR22

`legacy_history.py:356-375`, table `legacy_ward_aliases`. Columns: `id`,
`raw_alias` (`VARCHAR(150)`, NOT NULL, **UNIQUE**), `ward_id` (FK →
`wards.id`), `created_by_user_id` (FK → `users.id`), `created_at`.
Exact-string-match only — no fuzzy/similarity matching mechanism exists
anywhere in this table's own schema (`legacy_history.py:363-367`).
Lookup helper: `load_ward_alias_lookup()`
(`backend/app/services/import_adapters/legacy_history/common.py:302`).
**This table already solves Ward-alias governance for import-time
resolution; PR22 reuses it as read evidence (§9.F) rather than
reinventing it.**

**No equivalent table exists for BME-name-to-User mapping.**
`LegacyEquipmentEvent.legacy_bme_name` is raw, verbatim text only,
explicitly never auto-mapped (`legacy_history.py:224-225`). If PR22 wants
BME-to-User resolution, it must design a new table — see OD-PR22-4 (§36).

### 4.4 `BorrowTransaction`, `Equipment`, `Ward` — the modern/live side

**`BorrowTransaction`** (`backend/app/models/transaction.py:121-265`,
table `borrow_transactions`): `transaction_no` (`String(30)`, UNIQUE, NOT
NULL, generated via `nextval('transaction_no_seq')`, format
`TX-{date}-{08d}`), `equipment_id` (FK, NOT NULL), `status`
(`TransactionStatus` enum — **exactly** `OPEN` / `CLOSED`, per
`transaction.py:13-25`), `borrowed_at`, `due_at`, `returned_at`,
`borrower_user_id`/`borrower_name`, `ward_id` (FK, nullable),
`department_id`, `received_by_user_id`, `legacy_status` (an existing,
unrelated pre-Roadmap-PR6/PR7 provenance column — not to be confused
with anything PR22 introduces). The partial unique index
`idx_tx_one_active_borrow` (`transaction.py:140-148`, raw DDL in
`alembic/versions/0007_transaction_lifecycle.py:346-350`) enforces at
most one `OPEN` transaction per `equipment_id` — this is a **live-system**
constraint PR22 must never touch or reason its way around; `LegacyEquipmentEvent`
rows are structurally outside it (§4.1) and must stay that way.

**`Equipment`** (`backend/app/models/equipment.py:100-219`): `status`
(`EquipmentStatus` — **exactly** `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`,
`UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`, `equipment.py:17-29`),
`version` (`Integer, nullable=False, default=1, server_default=text("1")`,
`equipment.py:212` — the CAS column PR22 must model its own concurrency
columns after, §17). **`Equipment` has no direct FK/relationship to
`Ward`** — only `department_owner_id` (confirmed by
`backend/app/api/v1/reports.py:206-207`'s own comment). This matters for
§9.F: Ward traceability for legacy events is inherently indirect (via
`resolved_ward_id` on the event itself, not via `Equipment`).

**`Ward`** (`backend/app/models/master_data.py:25-35`): `id`, `code`
(unique), `name`, `department_id` (FK, optional).

### 4.5 ImportSession framework: CAS, lease/fencing, audit, lock order

PR22's own concurrency, audit, and lifecycle model is designed to mirror
this framework exactly — not because reuse is merely convenient, but
because `docs/ENGINEERING_WORKFLOW.md` and every prior PR19-PR21 slice
establish this as the repository's one shared pattern for exactly this
class of problem (long-running, auditable, concurrency-sensitive backend
workflow with a human review step).

- **CAS column shape**: `ImportSession.version` — `Integer, nullable=False,
  default=0, server_default=text("0")` (`backend/app/models/import_session.py:90`),
  "incremented by exactly 1 on every CAS-guarded UPDATE... an additional,
  independent guard alongside `status`, never a substitute for it."
  `Equipment.version` uses the identical shape with `default=1` instead
  of `0` (§4.4). The concrete UPDATE pattern (`backend/app/crud/equipment.py:382-420`,
  `update_with_cas`):
  ```python
  UPDATE equipment SET version = version + 1, ...
  WHERE id = :id AND version = :expected_version AND deleted_at IS NULL
  RETURNING *
  ```
  Zero matched rows → `None` → caller raises a domain conflict error,
  **never** retried with a relaxed predicate.
- **Status enum as a named `CheckConstraint`**, not a bare SQLAlchemy
  `Enum` with only an ORM-side default — `ImportSession`'s own status
  column uses `server_default` explicitly because "`default=` alone would
  not render DDL" (`import_session.py:81-89`, a documented past defect,
  PR84-H1). PR22's own run/finding status columns must follow this same
  pattern.
- **Lease/heartbeat/fencing** (`ImportJob`, `backend/app/models/import_session.py:164-218`;
  `backend/app/crud/import_job.py`): `lease_owner`, `lease_generation`
  (fencing token), `lease_expires_at`, `heartbeat_at`. Single-winner
  admission is one atomic `UPDATE import_sessions SET status=... WHERE
  id=... AND status IN (allowed) AND version=expected_version`
  (`import_job.py:57-66`), followed by inserting a new `ImportJob` row.
  Completion fencing reuses the identical `WHERE id/lease_owner/lease_generation/status='running'`
  predicate for both success and failure (`import_job.py:221-248`).
  Renewal loop: `backend/app/services/import_lease.py:32-63`.
- **Canonical audit writer**: `record_audit_event()`
  (`backend/app/core/audit.py:168-200`) — `actor_user_id`, `action`,
  `entity_type`/`entity_id`, `before`/`after` (redacted), `request_id`/`correlation_id`,
  `ip_address`, `user_agent`. Only flushes, never commits — the caller's
  transaction decides atomicity. New action/entity constants are added to
  the same file, never inline string literals (module comment,
  `audit.py:27-29`).
- **Global lock order — Job → Session → resource**: documented in
  `docs/ROADMAP.md` (lines 330, 407, 416-417) and enforced concretely in
  `backend/app/services/import_execution_service.py` — job/session
  fencing (`fenced_phase_success`) always runs *before* the
  adapter-owned resource (e.g. the `DryRunPlan`) is mutated
  (`import_execution_service.py:468-490`, comment explicitly: "the global
  lock order is now Job -> Session -> Plan on every path"). PR22 must
  define and hold to an equivalent order for its own entities (§23).
- **Flat exception hierarchy**: every domain exception subclasses
  `DomainError` directly (`backend/app/core/exceptions.py:1-7`) with a
  `code` string and `status_code`; ~30 leaf classes, no intermediate
  hierarchy. The "unified-stale-contract" convention — one error code
  covering several distinct invalidation sub-causes, disambiguated only
  in the `detail` string, never a separate code per sub-cause — is
  explicit in `ImportDryRunPlanStaleError`'s own docstring
  (`exceptions.py:307-317`). PR22's own stale/conflict errors must follow
  this same shape (§26).
- **Retention job pattern** (PR19A3, 180 days): explicit
  Administrator-only endpoint (`POST /import-sessions/retention/cleanup`,
  `backend/app/api/v1/import_sessions.py:142-157`) — **no in-repo
  cron/scheduler**; `SELECT ... FOR UPDATE SKIP LOCKED` claim
  (`backend/app/crud/import_retention.py:24-84`) followed by a separate,
  fenced per-row redaction transaction. `settings.IMPORT_RETENTION_DAYS
  = 180` (`backend/app/core/config.py:79`). This 180-day *temporary
  artifact* policy is explicitly **not** what PR22's own governance
  evidence should follow (§29) — reconciliation/sign-off evidence is
  permanent, not a temporary artifact.
- **Role model**: exactly three confirmed roles —
  `ROLE_ADMINISTRATOR = "administrator"`, `ROLE_EQUIPMENT_POOL_STAFF =
  "equipment_pool_staff"`, `ROLE_READ_ONLY = "read_only"`
  (`backend/app/models/user.py:14-24`). Gating mechanism:
  `require_roles(*allowed_roles)` (`backend/app/api/v1/deps.py:64-75`),
  always via a named capability-group constant (e.g.
  `ADMINISTRATOR_ONLY_ROLES`), never an inline tuple.

### 4.6 Reporting/export architecture (PR16-PR18)

`backend/app/schemas/report_export.py`: `ReportIdentity` enum (currently
exactly `receive-report` / `issue-report` / `equipment-verify-checklist`),
`ExportDocument` (`metadata` + `columns` + `rows`, validated for
consistency) as the single shared dataset shape consumed by all three
output adapters — Browser Print (`app/api/v1/reports.py:298-371`), PDF
(`backend/app/services/report_pdf_service.py`, `render_pdf_bounded`),
Excel (`backend/app/services/report_xlsx_service.py`,
`build_workbook_bounded`, explicitly mirroring the PDF admission-control
model). Single dispatch point for all three:
`_build_export_document_for_request` (`app/api/v1/reports.py:229-295`).
Row bound: `MAX_EXPORT_ROWS = 5000` (`report_export_service.py:63`).

**Bounded-concurrency/admission-control pattern**
(`report_pdf_service.py:296-388`): a module-level
`asyncio.Semaphore(MAX_CONCURRENT_RENDERS)`, one total deadline computed
once via `loop.time()`, `asyncio.wait_for` around both the semaphore
acquire and a shielded compute task, slot released only via the task's
own done-callback (never on caller-side timeout). This is the pattern
PR22's own analysis engine should reuse for the ~51,000-row dataset
(§27).

### 4.7 Pagination convention

`Page[T]` (`backend/app/schemas/common.py`): `items`, `next_cursor`,
`total`. Cursor codec: `encode_cursor`/`decode_cursor`
(`backend/app/utils/pagination.py:9-30`, base64/JSON of
`{created_at, id}`), plus alpha/int variants for non-timestamp orderings.
Example: `GET /reports/receive` (`app/api/v1/reports.py:114-150`),
`limit: int = Query(default=25, ge=1, le=200)`, keyset pagination
ordered `created_at DESC, id DESC`, `limit+1` fetch to detect a next
page. PR22's findings-list endpoint follows this identical shape (§25).

### 4.8 No existing unified legacy/modern history query

Confirmed absent: no query, view, or ORM join spans `BorrowTransaction`
and `LegacyEquipmentEvent` anywhere in the merged codebase today (a
repo-wide search for "unified"/"reconcil" in `backend/` returns no
application-code matches). PR22 is the first slice to build this (§15).
Real scale: `backend/app/crud/legacy_equipment_event.py:71` documents "a
~51,464-row combined dataset" for PR21D2's own batch-insert path — the
same order of magnitude this design's performance section (§27) must
handle.

### 4.9 PR21 design's own PR22-deferred items (binding on this design)

Quoted from `docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`
(§1, §11.2/§46 Owner Decision Closure Round 2), which this design treats
as authoritative and does not reopen:

> **PR22 boundary, reaffirmed and sharpened (§1):** PR22 owns optional
> reconciliation, likely-pair review, duplicate review across imports,
> unified history validation, and sign-off. PR22 (or a later, explicitly
> scoped PR21 sub-slice) **may propose or persist a link** between two
> already-imported `LegacyEquipmentEvent` rows (one `ISSUE`, one
> `RECEIVE`) — but only through deterministic evidence or explicit
> authorized review, **never** a nearest-timestamp/same-day/BCM-alone/
> Ward-alone/BME-alone/order-sequence/row-proximity/fuzzy-scoring
> heuristic (all explicitly forbidden). Any such later reconciliation
> step **must not rewrite or delete** the original `LegacyEquipmentEvent`
> rows or their provenance — they remain the permanent, immutable
> historical record regardless of whether a later link is ever
> established.

And on corrected/re-exported workbooks (§13 below, `PR21_LEGACY_...md:1742-1861`):

> A different checksum **must not** be automatically attached to the
> existing migration authority, must **not** be automatically
> deduplicated against, and must **not** be treated as an update to an
> existing event — fail closed. PR21 V1 makes **no automatic same-event
> determination across exports**: whether a row in a corrected workbook
> represents the same underlying historical fact as a row already
> imported under the existing authority is an **explicit, separately-scoped
> correction/reconciliation question** (PR22-or-later, under a new or
> explicitly superseding `LegacyMigrationAuthority`).

These two quoted passages are the binding constraints §11 (pairing) and
§13 (source correction) below implement.

---

## 5. Business workflow

Before any domain object is named, the operator-facing workflow PR22
must support, end to end:

1. An Administrator, once satisfied PR20/PR21 imports are complete,
   triggers a **reconciliation run** — a deterministic, read-only
   analysis over the current state of Equipment Master, legacy events,
   Ward aliases, and (where in scope) live `BorrowTransaction` history.
2. The system computes and **persists** a bounded set of **findings** —
   machine-detected, evidence-backed observations, each tagged with a
   category and severity, never a business conclusion.
3. A reviewer (role TBD by Owner Decision, §36) works through the
   findings list, filtering by category/status, and assigns each a
   **disposition** — a human conclusion, distinct from the finding's own
   machine-computed severity.
4. Once every finding on a run has a disposition (or the review is
   otherwise judged complete per the Owner-approved completion policy,
   §36), an Administrator performs **sign-off** — an immutable,
   auditable attestation bound to the exact run/snapshot reviewed.
5. A signed-off run's evidence remains available indefinitely (§29) and
   feeds Roadmap PR23's cutover-readiness evidence (not designed here).

This workflow is explicitly **not** "detect anomaly, fix data
immediately." No step here writes to `Equipment`, `BorrowTransaction`, or
`LegacyEquipmentEvent`. If genuine data correction is ever needed, §16
requires a separate, explicitly audited correction workflow — not an
implicit side-effect of reconciliation review.

---

## 6. Definitions

Six deliberately distinct concepts (per the review brief's explicit
requirement not to collapse them into one "duplicate" flag):

1. **Technical idempotency.** Already fully solved by PR21's own
   `uq_legacy_equipment_events_identity` constraint (§4.1). Re-running
   the *same* approved workbook under the *same* authority creates zero
   new rows. PR22 does not re-solve this; it only reads its result.
2. **Exact duplicate.** Two `LegacyEquipmentEvent` rows that, despite
   passing PR21's own identity constraint (different `legacy_source_row_key`
   values, or different `migration_authority_id`s entirely), represent
   the identical underlying historical fact with byte-identical
   business-relevant fields (`equipment_id`, `event_type`, `occurred_at`,
   `legacy_ward_text`, `legacy_bme_name`, `legacy_order_reference`) —
   almost always the signature of a corrected/re-exported workbook
   creating a second authority over overlapping source rows (§13).
3. **Suspected semantic duplicate.** Different source identity, business
   fields *not* byte-identical, but a deterministic rule judges them
   likely to represent the same event (e.g. same `equipment_id`, same
   `event_type`, `occurred_at` within a narrow tolerance window, same
   resolved Ward) — a candidate for human review, never auto-confirmed.
4. **Chronological anomaly.** An event sequence that is statistically or
   logically unusual (e.g. two consecutive `ISSUE` events for the same
   equipment with no intervening `RECEIVE`) but may still be historically
   true — the legacy source may simply record reality that way. Flagged,
   never rewritten.
5. **Traceability gap.** A row that cannot be proven to link correctly to
   `Equipment`, a resolved `Ward`, or its own source provenance — e.g. an
   `equipment_id` that no longer resolves (should be structurally
   impossible per the NOT NULL RESTRICT FK, but the *current* Equipment
   record's own BCM/Item No./QR continuity may still have drifted since
   import, which is a distinct, real traceability question, §9.A).
6. **Reconciliation disposition.** The human-reviewed conclusion attached
   to a finding — never inferred, never defaulted, never derived from
   severity (§10).

A finding belongs to exactly one detection category (§10) but its
underlying *nature*, per this taxonomy, informs which category and
severity it receives. These six concepts are documentation/design
vocabulary, not necessarily six separate database columns — §17
(domain model) maps them onto the actual finding schema.

---

## 7. Scope

**In scope for PR22 (architecture) and its implementation slices:**

- A. Equipment Master traceability review (§9.A)
- B. Historical-event traceability review (§9.B)
- C. Duplicate review — exact, semantic-suspected, and re-export-driven (§9.C)
- D. Cross-event chronology review, as observations only (§9.D)
- E. Current-state plausibility comparison, as a review signal only,
  never automatic mutation (§9.E)
- F. Ward traceability review, reusing PR21A's existing alias table (§9.F)
- G. BME/operator traceability review, including display-only
  BME-to-User mapping per OD-PR22-4's resolution (§9.G)
- H. Corrected/re-exported workbook governance (§9.H, §13)
- I. Reconciliation sign-off, its evidence, and its semantics (§9.I, §20)
- A read-only-first, persisted-snapshot analysis architecture (§17-§18)
- A unified read/query projection over legacy + modern history, without
  physically merging the tables (§15)

**Explicitly out of scope (do not absorb into PR22):**

- Any new import pipeline, adapter, or `ImportSession`/`ImportJob` reuse
  for *importing* new data — PR22 reads, it does not import.
- Redefining `LegacyEquipmentEvent` as `BorrowTransaction` rows, or any
  other rewrite of PR21's schema/semantics (§4.9).
- Any new `Equipment` lifecycle state (§8).
- Automatic Issue↔Receive pairing as authoritative truth — any pairing
  this design permits is an explicit, human-reviewable candidate, never
  silently authoritative (§4.9, §12).
- Fabricating `transaction_no`, `User` rows, or `BorrowTransaction` rows
  for legacy data.
- Expanding the SDC (Special Data Categories) exclusion PR21 already
  resolved (§55.1 of the PR21 design) — out of scope entirely unless a
  future, separately-scoped Owner Decision reopens it.
- QR system redesign, deployment/PR23/PR24 work, MEMS, or Recall
  Monitor.

---

## 8. Non-goals

Restated as an explicit, standalone list per the review brief's own
"what not to do" section (§38 there), because these are exactly the
mistakes a reconciliation feature is most likely to accidentally make:

- Do not add `RECONCILED`/`UNRECONCILED`/`LEGACY_PENDING`/`MISMATCHED` or
  any other value to `Equipment.status`. Reconciliation status is
  tracked entirely in PR22's own new tables (§17), never on `Equipment`
  itself.
- Do not mutate `LegacyEquipmentEvent` rows to "fix" anything a finding
  surfaces. They are permanent (§4.1, §16).
- Do not require Issue↔Receive pairing to validate that an event exists
  or is traceable — pairing is optional analytical/review-time
  enrichment, never a precondition (§4.9).
- Do not automatically rewrite `Equipment.status` from historical
  chronology (§16).
- Do not treat "reconcile" as synonymous with "correct the data" (§16).
- Do not introduce a general analytics/BI dashboard — only a narrowly
  scoped operational reconciliation summary tied to the review workflow
  itself (§31).

---

## 9. Reconciliation semantics — the business concerns PR22 must cover

Each of the nine concern areas the review brief specified (A-I), grounded
in what already exists (§4) and what PR22 must add.

### 9.A Equipment Master traceability

PR20 already establishes `Equipment.bcm_code`, `Equipment.item_no`,
`Equipment.qr_code_value` as the durable identity surface (§4.4). PR21's
`LegacyEquipmentEvent.equipment_id` is a **NOT NULL, RESTRICT** FK
(§4.1) — a legacy event can never point at a nonexistent or deleted
`Equipment` row at the database level. This means the traceability
question PR22 must actually answer is narrower and more useful than "is
the FK valid" (it always is): **has the target `Equipment` row's own
identity fields (BCM, Item No., QR) drifted or been retired since the
event was imported**, in a way that would make a human reviewing
imported history unable to correlate it with what they see in the
current Equipment Master screen today. PR22's traceability finding for
this concern compares the event's own recorded context (nothing on the
event stores a BCM/Item No. snapshot — deliberately, per §4.1's column
list) against the *live* `Equipment` row at analysis time, and flags
cases where — for example — the equipment has since been decommissioned,
or its BCM/Item No. has been edited by ordinary master-data maintenance
since import. This is a review signal (§16), never a data-correctness
claim about the import itself.

### 9.B Historical-event traceability

Every `LegacyEquipmentEvent` already has an internally consistent,
database-enforced link to `Equipment` (equipment_id FK), to its own
provenance (`legacy_equipment_event_source_refs`, composite FK proving
the source row genuinely belongs to the claimed session/source), and
optionally to a resolved `Ward`. PR22's traceability finding category
here is deliberately narrow: it verifies these existing links are
*jointly* coherent for review purposes (e.g. an event whose
`resolved_ward_id` is null but `legacy_ward_text` is non-blank — an
unresolved-Ward gap, §9.F) rather than re-verifying constraints the
database already guarantees.

### 9.C Duplicate review

Three distinct mechanisms, matching §6's taxonomy:

- **Exact duplicates** are detected by a deterministic SQL rule
  comparing business-relevant fields across events that passed PR21's
  identity constraint under *different* `migration_authority_id`s (the
  only way two logically-identical events can coexist, since the
  constraint already prevents duplication within one authority). This is
  the primary signal that a corrected workbook (§13) re-imported
  overlapping rows under a new authority.
- **Suspected semantic duplicates** use a bounded, explicit, documented
  rule (not fuzzy scoring) — e.g. same `equipment_id` + same `event_type`
  + `occurred_at` within N hours + same `resolved_ward_id` — flagged at
  a lower confidence than exact duplicates, always requiring human
  disposition.
- **Repeated source rows from corrected/re-export scenarios** are the
  same underlying mechanism as exact/semantic duplicates, but the
  finding's evidence explicitly names both `LegacyMigrationAuthority`
  rows involved, so a reviewer immediately sees "these two events came
  from two different approved workbooks," not just "these look similar."

Technical idempotency (§6.1) is never re-detected as a "duplicate"
finding — it cannot occur, by construction.

### 9.D Cross-event chronology review

Deterministic, per-`equipment_id` sequencing of `ISSUE`/`RECEIVE` events
ordered by `occurred_at`, producing chronology findings for: RECEIVE
without a prior ISSUE, ISSUE without a later RECEIVE, consecutive ISSUEs
with no intervening RECEIVE, and any other sequence a documented rule
set (versioned, §24) flags as unusual. **These are always classified as
observations (findings), never automatically paired or rewritten** — the
review brief is explicit on this, and it matches PR21's own
Owner-Decision-resolved event-first architecture (§4.9). A chronology
anomaly may later become a **pairing candidate** (§9.D overlaps §12) once
a human reviews it, but the finding itself never asserts a pairing.
**Every chronology finding must be phrased relative to the approved
temporal coverage window (§9.J), not as an absolute claim** — "ISSUE with
no later RECEIVE before coverage end" is a fundamentally different,
narrower claim than "ISSUE with no later RECEIVE, ever," and a `RECEIVE`
with no earlier `ISSUE` may simply reflect history that predates the
source's own coverage start rather than a genuine anomaly. This wording
is now **authorized per OD-PR22-7's resolution (§36)** — the same
resolution that authorizes the current-state comparison in §9.E.

### 9.E Current-state plausibility

**Authorized per OD-PR22-7's resolution (§9.J, §36).** A read-only
comparison between an equipment's last-known imported historical event
and its *current* `Equipment.status` (e.g. last historical event is
`ISSUE`, current status is `AVAILABLE_AT_POOL`) is the intended shape,
per §16. Per OD-PR22-7's resolution, this comparison runs through the
**unified legacy + modern history projection** (§15, §9.J option (d)) —
the approved post-cutoff treatment: post-boundary live activity
(`BorrowTransaction` rows after `legacy_coverage_end`/
`live_system_start`) is compared through that unified projection rather
than excluded, treated as legacy history, or used to mutate Equipment's
current state. A `CURRENT_STATE_MISMATCH` finding is produced only when
the unified projection — spanning both the approved legacy coverage
window and subsequent modern-system activity — genuinely contradicts
`Equipment.status`; activity that the projection itself resolves (e.g.
a later `BorrowTransaction` explaining an apparent legacy-side mismatch)
does not raise a finding. Other candidate explanations for a raw
mismatch remain unaffected: a missing historical row, a valid manual
correction, or a normal operational transition.

### 9.F Ward traceability

Reuses `LegacyWardAlias` as-is (§4.3) — PR22 does not reinvent Ward
alias matching. The traceability finding here is: for every distinct
`legacy_ward_text` value across imported events, is there a resolved
`Ward` (either directly via `resolved_ward_id` already being non-null
on the event, or resolvable today via `LegacyWardAlias`)? Any
`legacy_ward_text` with **no** alias and **no** resolved Ward is a
traceability-gap finding, with the raw text and affected event count as
evidence. This finding never auto-creates a `LegacyWardAlias` row —
alias creation is Administrator-only via PR21A's existing mechanism, not
a PR22 mutation path.

### 9.G BME/operator traceability

**Resolved per OD-PR22-4 (§36): display-only mapping is approved.** A
new alias-style table (mirroring `LegacyWardAlias`'s own shape:
`raw_bme_name` UNIQUE, `resolved_user_id` FK, `created_by_user_id`,
`created_at`) may be added, Administrator-managed. PR22's BME
traceability finding covers distinct raw `legacy_bme_name` values and
their event counts, presented as-is when unmapped, and resolved to a
current `User` for display purposes only where an Administrator-approved
alias exists. The mapping is **never** used to auto-create a `User`,
never inferred automatically from string similarity, and never presented
as proof that the current authenticated operator and the historical
actor are the same person (§28) — current actor audit identity remains
completely separate from this display-only mapping.

### 9.H Corrected/re-exported workbook governance

See §13 for the full model. In summary here: PR21's design already
resolved the high-level policy (§4.9 quote) — a corrected workbook must
mint a new or explicitly superseding `LegacyMigrationAuthority`, never
silently reuse the existing one. PR22 owns the actual reconciliation
findings comparing old-authority events against corrected-authority
events (an instance of §9.C's exact/semantic duplicate detection, scoped
by authority pair).

### 9.I Reconciliation sign-off

See §20 for full semantics. In summary: sign-off is a per-run,
Administrator-authored, immutable attestation binding an exact run
snapshot to a statement that its findings were reviewed and disposed —
never a claim that the underlying data is objectively perfect.

### 9.J Temporal coverage boundary (data cutoff)

**RESOLVED by OD-PR22-7 (§36).** A prior round of this design stated
that current-state mismatches "may be explained by activity after the
legacy cutoff," without ever defining what that cutoff *is*. That gap
was real; this subsection names the problem precisely, compares the
real alternatives that were considered, and records below which
alternative the Owner approved. The alternatives-comparison and
historical framing below are retained as the record of *why* the
Owner's decision was made this way, not as an open question.

**Observed evidence is not the same thing as authoritative coverage.**
`MIN(occurred_at)`/`MAX(occurred_at)` across a migration authority's
imported `LegacyEquipmentEvent` rows (`observed_min_event_at`/
`observed_max_event_at`) answer only "where does the data we happen to
have stop" — never "where the source was *intended* to stop." If the
approved workbook is itself missing trailing rows (a real, admitted
possibility — PR21's own evidence manifest already records blank/
missing-row cases, §4.1), silently treating the observed maximum
timestamp as the coverage boundary would make the system *confidently
wrong*: every gap after the true (but unrecorded) cutoff would read as
a plausible reconciliation anomaly instead of an out-of-scope period,
and every gap before it would read as a false "complete" claim. This
design does **not** infer the cutoff from `MIN`/`MAX` event timestamps,
the upload timestamp, or the import-completion timestamp, and does not
treat any of those as authoritative merely because they are easy to
compute.

**Alternatives compared** (none silently chosen):

- **(A) Owner-provided / governance-approved explicit cutoff datetime.**
  A human states the coverage boundary directly, independent of any
  computed value. Most defensible, least automatable.
- **(B) Approved source metadata carries a governed coverage end.** The
  boundary is recorded as part of the `LegacyMigrationAuthority`
  approval itself (§4.2) — still human-approved, but bound to the
  authority rather than entered as a free-standing value.
- **(C) Derive from the latest imported legacy event timestamp.**
  Rejected as the *sole* source, per the reasoning above — an
  `observed_max_event_at` value remains useful as evidence, never as
  the authoritative boundary by itself.
- **(D) System cutover/go-live boundary.** The point at which the
  modern system became authoritative. Necessary for the "live-system
  start" half of the model below, but not by itself a statement about
  where *legacy* coverage ends — the two can differ (overlap or gap).
- **(E) Two-boundary model** — `legacy_coverage_end` (Option A or B,
  above) kept **separate** from `live_system_start`/cutover (Option D).

**RESOLVED (§36): the two-boundary model (E) is adopted**, with
`legacy_coverage_start`/`legacy_coverage_end` sourced via an explicit
Administrator/Owner-governed approval workflow associated with the
relevant migration authority/reconciliation scope — combining option
(A)'s explicit-approval character with option (B)'s binding to the
governed authority record; never option (C) alone. A single boundary
cannot represent all three real possibilities — a clean handoff, a
genuine history gap between the legacy source's end and the modern
system's start, or an overlap where both sources describe the same
period — and collapsing them into one value would silently pick a
wrong interpretation for at least one of the three.

**Coverage start, not only coverage end.** §9.D's own chronology
rewording ("RECEIVE without a prior ISSUE" vs. "RECEIVE reflecting
history before source coverage start") only becomes meaningful if a
`legacy_coverage_start` is also approved — otherwise "before coverage
start" is exactly as undefined as "after coverage end" was before this
subsection. OD-PR22-7's resolution covers **both**
`legacy_coverage_start` and `legacy_coverage_end`, not only the end
boundary the original gap report named.

**Overlap and gap cases the design must not silently collapse:**

| Case | Condition | Interpretation |
|---|---|---|
| A — Gap | `legacy_coverage_end` < `live_system_start` | A genuine history gap exists between the two sources; neither is authoritative for the gap period. |
| B — Clean boundary | `legacy_coverage_end` == `live_system_start` | Simple handoff; no overlap-authority question arises. |
| C — Overlap | `legacy_coverage_end` > `live_system_start` | Both sources describe part of the same period. **Resolved (§36): both sources remain visible for the overlap period** — neither is deleted merely because the other covers the same date; any duplicate/conflict between them becomes reconciliation evidence/a finding, resolved through the unified history projection (§15). |

**Binding to the reconciliation run.** Now that OD-PR22-7 is resolved, a
`LegacyReconciliationRun` (§17.2) carries its approved
`legacy_coverage_start`/`legacy_coverage_end`/`live_system_start`
alongside its existing `rule_version`, `migration_authority_id` scope,
`created_by_user_id`, and `created_at` — so a signed-off run remains
fully interpretable later without depending on live, mutable state to
reconstruct what temporal window it actually covered. Exact field
names/types are finalized in PR22B's own migration design (§17.2, §34).

**Post-cutoff live activity — RESOLVED (§36): option (d).** Four
candidate treatments were compared:

- **(a) Exclude** post-boundary activity from mismatch evaluation
  entirely. Not adopted.
- **(b) Include only as explanatory evidence** attached to a finding,
  never as the trigger for one. Not adopted.
- **(c) Downgrade** mismatch severity for anything explainable by
  post-boundary activity, without excluding it. Not adopted.
- **(d) Compare through the unified history projection** (§15) using
  both legacy and modern history together, letting the projection
  itself resolve which source is authoritative per the overlap/gap
  table above. **Adopted** — the most architecturally consistent option
  with §15's own unified-projection goal, and the option §9.E's
  current-state comparison now implements.

**Corrected/re-exported authorities and coverage.** A corrected
workbook (§13) is not assumed to inherit its predecessor's temporal
coverage — a correction may genuinely extend, narrow, or leave coverage
unchanged, and assuming otherwise would silently misstate what the
corrected authority actually represents. **Resolved (§36):** each
new/superseding authority must have explicitly approved coverage of its
own; §13's corrected-source policy binds coverage independently per
authority by default, and an approved supersession relationship may
record intended inheritance only if the Administrator explicitly
confirms it — never inferred.

**Sign-off must attest to coverage, not only to review completeness.**
§20's own sign-off semantics is updated (§20 below) so the attestation
names the exact `rule_version`, migration authority, **and approved
temporal coverage** a run was evaluated against — never a claim that
covers "all hospital history," only the approved window.

**What this subsection resolves, and what it still does not do:** this
subsection, together with §36's OD-PR22-7 entry, resolves which
alternative ((A)/(B) combined, via the two-boundary model (E)) and
which post-cutoff treatment ((d), the unified projection) apply, and
authorizes PR22B/C/E to implement cutoff-dependent behavior accordingly
(§34). It still does **not** compute or approve any *actual* date value
for a specific migration authority — that remains an operational,
per-authority approval act performed through the governed workflow this
decision establishes, not a value this design document itself sets. It
does not touch PR21's own already-resolved scope (SDC exclusion,
event-first architecture, pairing prohibition, §4.9) in any way.

---

## 10. Finding taxonomy

**Proposed, not finalized** — names below follow the review brief's own
suggested groups, refined by §9's analysis:

| Code | Concern (§9) | Typical severity |
|---|---|---|
| `EQUIPMENT_IDENTITY` | 9.A | Medium-High (drifted/decommissioned identity) |
| `SOURCE_PROVENANCE` | 9.B | Low (informational coherence check) |
| `DUPLICATE_EXACT` | 9.C | High |
| `DUPLICATE_SUSPECTED` | 9.C | Medium |
| `CHRONOLOGY_ANOMALY` | 9.D | Medium-High depending on pattern |
| `CURRENT_STATE_MISMATCH` | 9.E | Medium (signal only) |
| `WARD_TRACEABILITY_GAP` | 9.F | Low-Medium |
| `BME_TRACEABILITY_GAP` | 9.G | Low (informational; display-only mapping per OD-PR22-4) |
| `PAIRING_CANDIDATE` | §11 | Informational (never blocks sign-off by itself) |

Each finding carries (schema in §17): a machine-readable `code` (from
this table, or its eventual Owner-refined version), a `severity` (above,
kept fully separate from disposition — see §19), affected entity
references (`equipment_id`, one or more `legacy_equipment_event_id`s,
optionally a `ward_id`/raw ward text), a bounded, structured `evidence`
payload (not free text — see §17), and a `rule_version` (§24). Names are
provisional;
the actual enum is fixed at implementation time against real analysis
results, not finalized here.

---

## 11. Pairing policy

**RESOLVED / OWNER APPROVED under OD-PR22-1 (§36).** Per the review
brief's own strong default recommendation, which the Owner approved as
the answer to OD-PR22-1:

- Pairing is **never** persisted as a mutation of `LegacyEquipmentEvent`
  or as a `BorrowTransaction` row.
- Issue↔Receive pairing is persisted only as an explicit, separate
  reconciliation artifact/finding (§17's `LegacyReconciliationFinding`
  with code `PAIRING_CANDIDATE`, or a dedicated relation table if
  implementation evidence later demonstrates it is cleaner without
  changing these semantics — the table shape is an implementation
  detail; the business decision is final) — never inferred solely from
  nearest timestamps, same-day proximity, BCM alone, Ward alone, BME
  alone, order-sequence, row-proximity, or fuzzy scoring (all explicitly
  forbidden, restated from PR21's own §11 prohibition, §4.9).
- No fuzzy auto-link ever becomes authoritative without an explicit
  human disposition (§19, §22).
- A `PAIRING_CANDIDATE` finding is created only when a *deterministic*
  rule is satisfied (§9.C's semantic-duplicate-style bounded rule,
  adapted for ISSUE→RECEIVE ordering rather than duplication), and its
  disposition vocabulary (§19) includes a value meaning "confirmed pair"
  — at which point the finding itself, not a new event mutation, is the
  durable record of the confirmed relationship. Provenance of both
  source events must remain intact.

---

## 12. Duplicate policy

Fully specified in §6 (taxonomy) and §9.C (detection mechanisms). The
one remaining design commitment: duplicate detection is **read-only
analysis**, computed fresh (or from a persisted snapshot, §18) each run
— it never deletes, merges, or marks any `LegacyEquipmentEvent` row. A
disposition of "confirmed duplicate" on a finding is a review
conclusion, not an instruction to delete anything (§16).

---

## 13. Corrected-source policy

See §9.H (business framing) and §4.9 (PR21's binding constraints, quoted
above). Summary of the binding constraint already resolved by PR21's own
design (§4.9): fail closed, mint a new/superseding authority, never
silently reuse or infer same-event equivalence automatically. **Temporal
coverage per authority — RESOLVED under OD-PR22-7 (§9.J, §36):** a
corrected authority is not assumed to inherit its predecessor's coverage
boundary. Each new/superseding authority must have explicitly approved
coverage of its own; an approved supersession relationship may record
intended inheritance only if the Administrator explicitly confirms
it — never inferred.

---

## 14. Current-state comparison

See §9.E and §16 — **authorized per OD-PR22-7's resolution (§9.J,
§36)**: the comparison runs through the unified history projection
(§15), producing a `CURRENT_STATE_MISMATCH` finding only where that
projection — spanning the approved legacy coverage window and
subsequent modern-system activity — genuinely contradicts
`Equipment.status`.

---

## 15. Unified history projection

See §4.8 (confirms no such query exists today) and §25 (the proposed
read-only companion endpoint). **Overlap/gap authority — RESOLVED under
OD-PR22-7 (§9.J's Case A/B/C table, §36):** during an overlap period,
both legacy and modern sources remain visible — neither is deleted
merely because the other covers the same date; a duplicate/conflict
between them becomes reconciliation evidence/a finding, not a silent
pick of one source over the other. Legacy and modern source identity/
provenance stay distinct — `LegacyEquipmentEvent` and
`BorrowTransaction` are never physically merged; the projection is
read/query/service-layer only, uses source/type markers, applies
deterministic rules only, and performs no automatic destructive
reconciliation.

---

## 16. Current Equipment state — never mutated

Restated as its own standalone principle, because it is the single
highest-risk mistake this design must foreclose: **no PR22 code path
ever writes `Equipment.status`, `Equipment.version`, current
Ward/location, or any live dispatch/receipt state.** Every comparison
against current state (§9.A, §9.E) is read-only, and every finding that
results is presented to a human as a *signal*, with the explanation
space explicitly including "this may not indicate any problem" (§9.E).
If a genuine correction is warranted, it happens through the **existing**
manual Equipment/dispatch/receipt workflows PR6-PR20 already built —
never through a PR22-specific write path.

---

## 17. Recommended domain model

### 17.1 Data model options considered

**Option A — no new persistence; calculate findings live.**
*Pros:* no new schema, trivially simple to prototype.
*Cons:* poor auditability (a sign-off can't cite exactly what was
reviewed once live data changes underneath it — e.g. a new PR21
correction slice runs, or `Equipment.version` bumps between review and
sign-off); results silently drift over time; cannot answer "what did the
Administrator actually see when they signed off" months later, which is
precisely the kind of evidence Roadmap PR23 (Cutover Readiness) and any
future audit will need. **Rejected** for the same reason PR20D rejected
a live-recomputed dry-run plan (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`
established persisted, immutable plans over live queries) — this
repository's own established precedent already answers this question.

**Option B — persist `ReconciliationRun` + `ReconciliationFinding` +
`SignOff`.**
*Pros:* auditable, repeatable, explicit workflow; matches every
analogous workflow already merged in this repository (`ImportSession`/
`ImportJob`, `DryRunPlan`/`DryRunPlanRow`, `LegacyMigrationAuthority`);
a sign-off can cite an exact, immutable run identity forever.
*Cons:* new schema and its own lifecycle to design and maintain (this
document does that work).

**Option C — persist only a final sign-off summary, discard individual
findings after review.**
*Pros:* smaller schema footprint.
*Cons:* destroys the very evidence a reviewer's disposition decisions
were based on — a later question ("why was this specific duplicate
accepted?") becomes unanswerable. Contradicts §28's audit requirement
and this repository's own "provenance is never discarded" convention
(`LegacyEquipmentEvent` itself is the paradigm case).

**Recommended: Option B.** It is the only option consistent with this
repository's established evidence-persistence convention, and it is what
the review brief's own §12/§11 preference already points to.

### 17.2 Proposed entities

Names provisional (per review brief §13's own instruction not to treat
names as approved). Each entity's responsibility, immutability,
ownership, lifecycle, FKs, retention, and audit requirement:

**`LegacyReconciliationRun`**
- Responsibility: the immutable snapshot boundary and lifecycle anchor
  for one reconciliation analysis pass.
- Immutability: append-only after creation for its identity/snapshot
  fields (§18); its `status` and `version` (CAS) columns are the only
  ones that change, and only through the fenced lifecycle transitions
  in §18.
- Ownership: created by an Administrator (§21).
- Lifecycle: `pending` → `running` → `completed` | `failed`, then
  externally (via `LegacyReconciliationSignOff`, a separate table, not a
  status value on the run itself — see rationale below) →
  `signed_off`... but a run's own `status` column tracks only the
  *analysis* lifecycle (whether it computed successfully), not the
  *review* lifecycle (whether it's been reviewed/signed-off) — those are
  tracked by the findings' dispositions and the sign-off row's existence,
  to avoid conflating "did the computation succeed" with "did a human
  finish reviewing it," which are genuinely different questions with
  different failure modes.
- Columns: `id` (UUID PK), `status` (CheckConstraint enum:
  `pending|running|completed|failed`, `server_default` — matching
  `ImportSession`'s own DDL-rendering discipline, §4.5), `version`
  (Integer, CAS, `default=0`/`server_default=text("0")` matching
  `ImportSession.version`'s exact shape), `rule_version` (`VARCHAR(50)`,
  NOT NULL — the analysis rule set version this run was computed under,
  §24), `snapshot_as_of` (`TIMESTAMP WITH TIME ZONE`, NOT NULL — the
  single logical instant this run's read queries are bound to; see §18's
  snapshot-consistency discussion), `created_by_user_id` (FK →
  `users.id`, RESTRICT), `created_at` (`server_default=func.now()`),
  `started_at`/`completed_at`/`failed_at` (nullable, mirroring
  `ImportSession.terminal_at`'s pattern for its own terminal states),
  and summary counters mirroring `LegacyHistoryDryRunPlan`'s own
  `summary_*` column shape (`summary_total_findings`,
  `summary_by_severity_high`/`medium`/`low`, all `Integer NOT NULL
  DEFAULT 0`, `>= 0` check-constrained) — populated once, at completion,
  never recomputed live.
- **Temporal coverage — RESOLVED / authorized for implementation under
  OD-PR22-7 (§9.J, §36):** the run additionally carries its bound
  `legacy_coverage_start`/`legacy_coverage_end`/`live_system_start`
  (the two-boundary model, adopted) — the authoritative window, never
  the observed `MIN`/`MAX` of imported event timestamps (§9.J) — plus a
  `coverage_source` marker recording how the bound value was produced
  (the Administrator/Owner-governed approval workflow, §36), so a
  signed-off run remains self-describing without depending on live,
  mutable state to reconstruct what it actually covered. Exact column
  names/types are fixed in PR22B's own migration design (§34).
- Retention: permanent (§29) — not the 180-day temporary-artifact policy.
- Audit: run creation and every status transition is audited via
  `record_audit_event` with new constants
  (`AUDIT_ACTION_RECONCILIATION_RUN_CREATED`,
  `_COMPLETED`, `_FAILED`) added to `backend/app/core/audit.py`
  alongside the existing import constants (§4.5).

**`LegacyReconciliationFinding`**
- Responsibility: one machine-detected, evidence-backed observation
  belonging to exactly one run.
- Immutability: the machine-computed fields (`code`, `severity`,
  `evidence`, `affected_*` references, `rule_version`) are
  **write-once** — set only by the analysis engine at run-completion
  time, never edited afterward. Only the disposition fields are ever
  updated post-creation, and only through the CAS pattern in §22.
- Ownership: created by the analysis engine (system-authored, no
  `created_by_user_id` in the sense of a human actor — the run's own
  `created_by_user_id` already records who *triggered* the run).
- Lifecycle: `open` (no disposition yet) → `disposed` (a human has
  assigned a disposition, §19) — a two-state lifecycle only; there is no
  "in review" state, since disposition-setting is a single atomic CAS
  write, not a multi-step checkout.
- Columns: `id` (UUID PK), `run_id` (FK → `legacy_reconciliation_runs.id`,
  RESTRICT, NOT NULL, indexed), `code` (`VARCHAR(50)`, NOT NULL — from
  §10's taxonomy), `severity` (`VARCHAR(10)`, NOT NULL, CheckConstraint
  `IN ('high','medium','low')` — kept structurally separate from
  disposition per §19), `equipment_id` (UUID, nullable FK → `equipment.id`
  RESTRICT — nullable because not every finding is equipment-scoped,
  e.g. a Ward-traceability-gap finding may span many pieces of
  equipment), `legacy_equipment_event_ids` (a small bounded array or a
  separate one-to-many junction table — see implementation note below;
  never more than the handful of events one finding genuinely concerns),
  `evidence` (JSONB, NOT NULL — a bounded, schema-validated structure
  per finding code, e.g. `{"other_authority_id": ..., "matched_fields":
  [...]}`for a duplicate finding — **never** free text as the sole
  evidence, per the review brief's explicit requirement), `rule_version`
  (`VARCHAR(50)`, NOT NULL, matches the owning run's `rule_version`),
  `disposition` (`VARCHAR(30)`, **nullable** — null means `open`; see
  §19 for the vocabulary, approved under OD-PR22-2), `disposed_by_user_id`
  (nullable FK → `users.id`), `disposed_at` (nullable), `disposition_note`
  (nullable `Text`, bounded length — a human's brief rationale, never
  the sole evidence for the disposition itself), `version` (Integer, CAS,
  same shape as `Equipment.version`), `created_at`
  (`server_default=func.now()`).
- Implementation note on `legacy_equipment_event_ids`: given PostgreSQL
  is this repository's only production dialect for JSONB/array columns
  elsewhere (e.g. `normalized_values`/`warnings` on
  `LegacyHistoryDryRunPlanRow`, §4.1), a `JSONB` array of event UUIDs is
  simplest and sufficient for *read* purposes (a finding's evidence is
  never queried "which findings reference event X" at meaningful scale —
  reviewers work run-by-run, not event-by-event). If a future need
  arises to query findings by affected event efficiently, a junction
  table (`LegacyReconciliationFindingEvent(finding_id, event_id)`) can be
  added additively without disturbing this shape — not needed for V1.
- Retention: permanent, same as the owning run (§29).
- Audit: disposition changes are audited
  (`AUDIT_ACTION_RECONCILIATION_FINDING_DISPOSED`), `before`/`after`
  capturing the disposition transition. Read-only finding-list queries
  are **not** audited (matches the existing convention of avoiding audit
  spam for read-only analysis queries, per §4.5's audit-writer
  discipline and this design's own §28 instruction).

**`LegacyReconciliationSignOff`**
- Responsibility: the immutable, auditable attestation that a specific
  run's findings have all been reviewed.
- Immutability: fully immutable once created — no update path at all.
  "Reopening" (§36, OD-PR22-3) is modeled as creating a **new** run (or
  a new sign-off superseding the old one, depending on the Owner's
  answer), never as mutating an existing sign-off row — mirroring
  `LegacyMigrationAuthority`'s own "never updated, mint a new one"
  convention (§4.2).
- Ownership: Administrator-authored (§21).
- Columns: `id` (UUID PK), `run_id` (FK → `legacy_reconciliation_runs.id`,
  RESTRICT, NOT NULL, UNIQUE — enforcing at most one active sign-off per
  run at the database level, matching the "one active DryRunPlan per
  session" partial-unique-index pattern conceptually, though here it's a
  plain unique constraint since a sign-off, once created, is never
  superseded in place), `signed_off_by_user_id` (FK → `users.id`,
  RESTRICT, NOT NULL), `signed_off_at` (`server_default=func.now()`,
  NOT NULL), `attestation_summary` (JSONB, NOT NULL — a snapshot of the
  run's own summary counters *as attested*, e.g. total findings, counts
  by disposition, captured at sign-off time so this row remains
  self-describing even if someone later queries the findings table
  directly), `run_version_at_signoff` (Integer, NOT NULL — the run's
  `version` at the moment of sign-off, §22's concurrency guard),
  `superseded_by_run_id` (nullable, self-referential-via-run FK — set if
  a later run/sign-off explicitly supersedes this one, per OD-PR22-3's
  eventual answer).
- Retention: permanent (§29), highest-priority governance evidence in
  this design.
- Audit: sign-off creation is always audited
  (`AUDIT_ACTION_RECONCILIATION_SIGNOFF`), never best-effort (§4.5's
  distinction between mandatory business-mutation audit and best-effort
  auth-flow audit — sign-off is unambiguously the former).

**Avoiding a God table:** these three entities are kept deliberately
separate — a run's identity/snapshot concerns, a finding's
detection/disposition concerns, and a sign-off's attestation concerns
are three different lifecycles with three different mutability profiles
(write-once-then-CAS-status, write-once-then-single-CAS-disposition, and
fully-immutable, respectively). Merging any two would force a
lowest-common-denominator mutability policy onto data that doesn't share
one.

---

## 18. Run lifecycle

1. **`pending`** — row created (`POST /legacy-reconciliation-runs`, §25),
   `created_by_user_id` recorded, `snapshot_as_of` set to `now()` at
   creation (the single logical instant every read query in this run is
   bound to — see the next paragraph for how that binding is enforced).
2. **`running`** — the analysis engine claims the run via the identical
   CAS admission pattern `ImportJob` uses (§4.5): one atomic `UPDATE ...
   WHERE status='pending' AND version=expected_version`. If the analysis
   is long-running enough to need its own lease/heartbeat (§27 addresses
   whether it will be), it reuses `ImportJob`'s exact lease/fencing shape
   rather than inventing a second one; if the ~51k-row analysis proves
   fast enough to run synchronously within one bounded request (§27's
   own performance section makes this determination against real query
   plans, not assumed here), a lease may be unnecessary and the run
   simply transitions `pending → running → completed` within one
   request/transaction.
3. **`completed`** — every finding for this run has been inserted
   (bulk-inserted in one transaction, mirroring PR21D2's own
   `bulk_insert_events` batching discipline, §4.1), summary counters
   populated, `completed_at` set. From this point, findings exist and
   are independently reviewable (§19) — completion of the *run* and
   completion of *review* are different events (§17.2).
4. **`failed`** — analysis aborted; no findings are considered valid
   from a failed run (partial results are never surfaced — matches
   PR20E's own all-or-nothing execute() semantics).

**Snapshot-consistency mechanism.** `snapshot_as_of` is not merely a
timestamp label — every read query the analysis engine issues (against
`Equipment`, `BorrowTransaction`, `LegacyEquipmentEvent`, `Ward`,
`LegacyWardAlias`) is executed inside **one PostgreSQL transaction using
`REPEATABLE READ` isolation**, opened at the moment the run transitions
to `running` and held open for the duration of the analysis. This gives
the run a genuinely consistent snapshot of every table it reads, without
requiring point-in-time row versioning anywhere else in the schema
(`Equipment`/`BorrowTransaction` have no existing temporal/versioning
columns beyond `Equipment.version`, which is a conflict counter, not a
history table). `snapshot_as_of` is recorded as the wall-clock time this
transaction began, for human-readable evidence — the actual consistency
guarantee comes from the transaction isolation level, not the timestamp
column. This directly answers the review brief's own requirement: "a
reconciliation result must be reproducible and auditable... do not rely
on a live query whose result silently changes after sign-off" — after
`completed`, the
findings are already persisted rows, immune to any subsequent live-data
drift by construction (Option B, §17.1).

**No `signed_off` run-status value exists in this lifecycle, and none is
added by this design.** Sign-off is modeled as the existence of a
separate, fully immutable `LegacyReconciliationSignOff` row bound to the
run (§17.2, §20), not as a fifth `status` transition — so a run reaching
`completed` never implies, by itself, that it has been (or can be)
signed off. This keeps the sign-off preconditions (§20) a property of
when a `LegacyReconciliationSignOff` row may be inserted, with no
run-lifecycle change required to enforce them.

---

## 19. Finding lifecycle and disposition

A finding is `open` (disposition `NULL`) until a human sets its
disposition via a single CAS-guarded UPDATE (§22) — identical shape to
`Equipment.update_with_cas` (§4.5): `WHERE id=:id AND version=:expected_version`,
`SET disposition=..., disposed_by_user_id=..., disposed_at=now(),
version=version+1`. There is no intermediate "claimed for review" state —
per §17.2, disposition-setting is a single atomic write, not a
multi-step checkout, so no lease/lock is held on a finding between a
reviewer opening it and submitting a decision (avoiding the UX problem
of one reviewer accidentally locking a finding another reviewer could
have disposed of faster).

**Disposition vocabulary — RESOLVED / OWNER APPROVED under OD-PR22-2
(§36).** The review brief's own instruction was explicit: "Do not
invent final disposition enum without carefully minimizing it. If an
enum is needed, propose it as Owner Decision, not silently finalize
it." The Owner approved the proposed four-value set exactly as
proposed, unchanged — no additional value may be added without a new
Owner Decision:

- `confirmed_valid` — reviewed, the underlying data is correct as
  imported; the finding was a false positive or an acceptable, explained
  anomaly.
- `confirmed_duplicate` — reviewed, this genuinely is a duplicate (exact
  or semantic); no data is deleted, but the finding's own disposition is
  now the durable record of that conclusion.
- `accepted_unresolved` — reviewed, the underlying issue is real but
  will not be corrected before Go-live (e.g. a traceability gap in data
  too old to recover source context for); explicitly distinct from
  `confirmed_valid` because it acknowledges a real gap rather than
  denying one exists.
- `requires_correction` — reviewed, a genuine data-correction workflow
  (§16) is needed; this disposition does not itself trigger that
  workflow — it is a signal for a human to separately initiate it.

Severity (§10) is never inferred from disposition, or vice versa — a
`high`-severity duplicate finding can be `confirmed_duplicate` (fully
resolved, review-wise) while remaining `high` severity for historical
record purposes; a `low`-severity traceability gap can be
`requires_correction` if the Owner judges it operationally important
despite low machine-assigned severity.

---

## 20. Sign-off semantics

Restated with full precision, addressing the review brief's own
requirement that sign-off must never mean "data is objectively perfect":

> "The reviewer confirms that all findings generated for the exact
> immutable reconciliation run `{run_id}`, rule version
> `{rule_version}`, migration authority scope, and approved temporal
> coverage (`legacy_coverage_start`/`legacy_coverage_end`, and
> `live_system_start` if applicable) have been reviewed according to the
> permitted disposition policy."

This is a statement about **review completeness against one specific,
immutable run**, never a statement about the objective correctness of
the imported data itself. A run with findings dispositioned
`confirmed_valid`, `confirmed_duplicate`, or `accepted_unresolved` can
still be validly signed off — sign-off attests that review happened and
conclusions were reached, not that every conclusion was "everything is
fine." **A run with any finding still dispositioned `requires_correction`
can never be signed off** (OD-PR22-6, §36) — that disposition means a
separate, explicit, audited correction workflow is required first (§19);
sign-off is never used to bypass it. Whether a given mix of the three
sign-off-eligible dispositions is *acceptable for Go-live* is a Roadmap
PR23 cutover-readiness policy question, explicitly out of this design's
scope (§7) — but whether sign-off can occur *at all* is not a PR23
question, it is decided here and by OD-PR22-6.

Sign-off never certifies hospital history outside the approved coverage
window — only that the findings generated *for that window* were
reviewed.

**Sign-off preconditions (all required, no exceptions)**: a run may
reach final sign-off only when every one of the following holds:

1. The reconciliation run and its snapshot are immutable and completed
   (§17.2, §18) — sign-off binds to one exact, closed run.
2. The rule set version (§24) under which the run's findings were
   computed is recorded and unambiguous.
3. The applicable data/migration authorities (§4.9, §13) in scope for
   the run are recorded and unambiguous.
4. **The authoritative temporal coverage boundary is resolved under
   OD-PR22-7 (§9.J, §36)** — `legacy_coverage_start`/
   `legacy_coverage_end`/`live_system_start` are explicit, persisted,
   and approved; an implicit `observed_min_event_at`/
   `observed_max_event_at` value never substitutes for an approved
   boundary.
5. Every finding on the run has been assigned an accepted disposition
   under the approved disposition policy (§19) — `COUNT(findings WHERE
   disposition IS NULL) == 0` for the run.
6. **Zero findings on the run are dispositioned `requires_correction`**
   (OD-PR22-6, §36) — `COUNT(findings WHERE disposition =
   'requires_correction') == 0` for the run. `accepted_unresolved`,
   `confirmed_valid`, and `confirmed_duplicate` do not block sign-off;
   `requires_correction` always does, with no exception.
7. The caller invoking sign-off is authorized to sign off (§21).
8. Freshness/concurrency checks pass (§22) — the run's `version` matches
   what the sign-off call supplied, and no finding's disposition changed
   between the caller's last read and the sign-off write.

Preconditions 5 and 6 are evaluated together, in the same transaction as
the sign-off INSERT (§22): a finding with a null disposition and a
finding dispositioned `requires_correction` are two independently
sufficient reasons to reject a sign-off attempt, and both are checked —
satisfying one never substitutes for the other.

**OD-PR22-6 and OD-PR22-7 are both now RESOLVED / OWNER APPROVED (§36)
— final sign-off is authorized**, subject strictly to every precondition
above continuing to hold for the specific run being signed off. There is
no separate interim, partial, or provisional sign-off mode: no
precondition above is optional, and a sign-off write is rejected if any
one of them is not satisfied for that run. The original, narrower
attestation wording (naming only `rule_version` and `snapshot_as_of`,
without a temporal coverage clause) is retired by this design and must
not be implemented as an alternative or fallback attestation — the
attestation wording above, binding temporal coverage, is the only
sign-off contract this design authorizes.

*Historical note (fix round 3, superseded by OD-PR22-7's resolution
above): before OD-PR22-7 resolved, this section stated that no
reconciliation run could reach final sign-off while it remained OPEN,
though run creation, analysis, snapshot persistence, finding review, and
(where otherwise authorized) disposition assignment remained permitted.
That gate no longer applies — it is recorded here only as the design's
own review history, not as current normative status.*

*Historical note (Owner Decision Closure fix round 1): an earlier
version of this section stated "a run with findings dispositioned
`accepted_unresolved` or `requires_correction` can still be validly
signed off." That statement was a genuine contradiction with §34's and
§36's own OD-PR22-6 text, which always required
`requires_correction == 0` before sign-off. It has been corrected above
— `requires_correction` never permits sign-off; only `confirmed_valid`,
`confirmed_duplicate`, and `accepted_unresolved` do.*

**Acceptance criterion (current normative rule):** final sign-off is
allowed only if every precondition above is satisfied for the run being
signed off — an immutable, completed run/snapshot, unambiguous rule
version and data/migration authority scope, explicit approved
`legacy_coverage_start`/`legacy_coverage_end`/`live_system_start`
(never an implicit `observed_min_event_at`/`observed_max_event_at`
value in their place), every finding dispositioned with zero findings
left `requires_correction`, an authorized caller, and passing
freshness/concurrency checks. Sign-off binds the exact immutable
reconciliation snapshot and the approved temporal coverage.

**Binding to exact run/snapshot identity**: enforced structurally by
`LegacyReconciliationSignOff.run_id` (UNIQUE FK) and
`run_version_at_signoff` (§17.2) — the sign-off API call (§25) must
supply the run's currently-known `version`, and the INSERT is rejected
(§22) if that no longer matches, exactly mirroring how `DryRunPlan`
confirmation binds to an exact plan identity rather than "whatever the
current plan happens to be." This structural binding is necessary but
not sufficient: it prevents sign-off from targeting a stale run
version, but does not by itself satisfy precondition 4 — the temporal
coverage precondition is enforced separately, and both must hold before
any sign-off write is accepted.

---

## 21. Authorization

Per §4.5's existing three-role model, and per the review brief's own
instruction not to invent a new role:

- **Administrator**: create a run, trigger analysis, perform sign-off.
  (Matches the existing pattern — `LegacyMigrationAuthority` approval
  and `POST /import-sessions` are both already Administrator-only.)
- **Finding disposition**: Administrator-only for V1 — **RESOLVED /
  OWNER APPROVED under OD-PR22-5 (§36)**, exactly as this design's
  default proposed. `equipment_pool_staff` may view/review reconciliation
  information where existing read permissions already allow, but may
  **not** set dispositions in V1; sign-off remains Administrator-only.
  The current role matrix (`docs/BUSINESS_RULES.md`) does not mention any
  import/migration/reconciliation capability for `equipment_pool_staff`
  at all — its existing capabilities are dispatch/receipt/ward-correction/
  defective-marking and view/search/report, none of which map cleanly
  onto "review a reconciliation finding." A future loosening of
  disposition-setting permission may be an additive change but requires
  its own new, explicit governance decision.
- **Read-only viewing of runs/findings**: available to all three roles
  per the existing "every role may view every list/search surface"
  convention (`docs/BUSINESS_RULES.md`'s own `equipment_pool_staff`/
  `read_only` capability note, §4.5) — viewing a reconciliation run's
  findings is a report/search surface, not a write capability.
- Enforced identically to every existing route: `require_roles(*<a new
  named capability-group constant>)` added to `backend/app/api/v1/deps.py`
  (e.g. `RECONCILIATION_ADMINISTRATION_ROLES = ADMINISTRATOR_ONLY_ROLES`
  as an explicit alias, so a future OD-PR22-5 answer that loosens
  disposition-setting only requires changing one named constant, not
  every route decorator).

---

## 22. Concurrency

Every scenario the review brief names, addressed:

- **Two Administrators reviewing the same finding concurrently**: the
  second writer's CAS UPDATE (§19) matches zero rows (the first writer
  already incremented `version`) and receives a structured 409 conflict
  (§26) — never a silent overwrite, never a last-write-wins race.
- **Concurrent disposition changes generally**: same CAS mechanism,
  applied per-finding — findings are independently concurrency-controlled,
  so two reviewers working *different* findings on the same run never
  contend with each other.
- **Sign-off racing with disposition changes**: sign-off (§25's
  `POST .../sign-off`) requires the caller to supply the run's current
  `version` (§20); if a disposition change on any of that run's findings
  happens to also require bumping the *run's* own `version` (a design
  choice — see the alternative below), a concurrent disposition change
  during sign-off submission causes the sign-off to be rejected with a
  stale-version conflict, forcing the Administrator to re-fetch and
  retry. **Design choice recorded here, not deferred**: the run's
  `version` is bumped only by run-lifecycle transitions (§18's
  `pending→running→completed/failed`), *not* by individual finding
  disposition changes, because coupling every finding-level write to a
  run-level version bump would make concurrent review by multiple
  reviewers on the same run needlessly contentious (every reviewer's
  CAS write would collide with every other reviewer's). Instead,
  sign-off's own endpoint independently re-verifies, in the same
  transaction as the sign-off INSERT, **two** counts against the run's
  findings: (a) `SELECT COUNT(*) ... WHERE run_id=:id AND disposition IS
  NULL` must return zero (every finding has been reviewed), and (b)
  `SELECT COUNT(*) ... WHERE run_id=:id AND disposition =
  'requires_correction'` must also return zero (OD-PR22-6, §20, §36) —
  this is the actual concurrency guard for "did review truly finish, and
  cleanly," not the run's own `version` column. A finding disposed
  `requires_correction` *after* the caller's last read but *before* the
  sign-off transaction commits is caught by check (b) exactly as a
  newly-undispositioned finding is caught by check (a) — neither check
  substitutes for the other. These two checks are sign-off preconditions
  among several (§20) and do not by themselves authorize the INSERT: the
  same transaction must also confirm the run's approved temporal
  coverage boundary (`legacy_coverage_start`/`legacy_coverage_end`/
  `live_system_start`, per OD-PR22-7's resolution, §36) is explicit and
  approved for that run — the INSERT is rejected if any of these
  confirmations fails.
- **A new corrected authority appearing during review**: does not
  invalidate an in-progress run — the run's `REPEATABLE READ` snapshot
  (§18) already fixed its view of the data at `running` time; a new
  authority appearing afterward simply means the *next* run will surface
  it. No live-blocking mechanism is needed.
- **Stale snapshot**: by construction, a `completed` run's findings never
  go stale relative to *that run* — they are the permanent record of
  what the snapshot showed (§17.1, Option B's whole rationale). "Staleness"
  only matters when deciding *whether to trust an old run for a new
  decision*, which is a human judgment (start a new run) — not something
  the schema needs to detect automatically.

---

## 23. Lock ordering

Extending the existing Job → Session → resource convention (§4.5)
directly:

**(Job, if async) → Run → Finding | SignOff**

- If the analysis engine needs its own lease/fencing job row (§18), it
  is claimed and fenced exactly as `ImportJob` is, and that fencing
  always completes *before* the `LegacyReconciliationRun`'s own status
  transitions — mirroring `import_execution_service.py`'s documented
  "Job -> Session -> Plan" order (§4.5) with Run playing Session's role.
- `LegacyReconciliationFinding` rows are only ever inserted (at
  `completed`) or individually CAS-updated (disposition, §19) — never
  locked as a set, and never locked before the owning Run's own
  transition has already completed, matching the existing convention
  that the "resource" tier is always the last thing touched in the
  chain.
- `LegacyReconciliationSignOff` insertion locks/reads the owning Run row
  (to verify version and completeness, §22) strictly before inserting
  the sign-off itself — Run before SignOff, the same "session before its
  owned resource" shape.
- Where multiple `Equipment` rows are touched by one analysis pass (read
  only, never locked for write by PR22 at all — §16), no lock ordering
  concern arises, since PR22 never issues `SELECT ... FOR UPDATE`
  against `Equipment`/`BorrowTransaction`/`LegacyEquipmentEvent` — it is
  read-only against all three, by design (§16).

---

## 24. Rule versioning

`rule_version` (`VARCHAR(50)`, e.g. `"v1"`, semantic-versioned by
convention rather than enforced) is stored on both
`LegacyReconciliationRun` and (redundantly, deliberately) on each
`LegacyReconciliationFinding` it produced. A **new** rule version is
never applied retroactively to old runs or findings — a signed-off run
remains fully interpretable using its own recorded `rule_version`
forever, satisfying the review brief's explicit requirement: "a
historical signed-off run must remain interpretable after rules evolve...
do not silently recalculate an old signed run using new rules." Changing
detection logic in a later implementation slice always means introducing
a new `rule_version` value and leaving every prior run's findings exactly
as originally computed.

---

## 25. API

Provisional — endpoint names/shapes not finalized until the domain model
(§17) is Owner-confirmed. Proposed surface, following this repository's
existing `Page[T]`/cursor and `require_roles` conventions exactly (§4.7,
§4.5):

```
POST   /legacy-reconciliation-runs                          (Administrator)
GET    /legacy-reconciliation-runs                           (all roles, Page[LegacyReconciliationRunOut])
GET    /legacy-reconciliation-runs/{run_id}                  (all roles)
GET    /legacy-reconciliation-runs/{run_id}/findings         (all roles, Page[LegacyReconciliationFindingOut],
                                                                filterable by code/severity/disposition)
POST   /legacy-reconciliation-runs/{run_id}/findings/{finding_id}/disposition
                                                               (Administrator only, per OD-PR22-5)
POST   /legacy-reconciliation-runs/{run_id}/sign-off          (Administrator only)
GET    /legacy-reconciliation-runs/{run_id}/sign-off          (all roles — read the attestation, if any)
```

**Sign-off endpoint status**: `POST .../sign-off` is listed here as a
proposed endpoint. Its implementation is now authorized — OD-PR22-7 and
every other sign-off-gating Owner Decision have resolved (§20, §36,
§34's PR22E entry) — subject to every sign-off precondition in §20
continuing to hold at call time. `GET .../sign-off` (reading an existing
attestation, if any) was never gated.

Deliberately **not** nested under `/import-sessions` — a reconciliation
run is not an `ImportSession` (it imports nothing), so it gets its own
top-level resource, matching how `/legacy-migration-authorities` (PR21E0)
already got its own top-level resource rather than being force-fit under
`/import-sessions` (§4.2).

Potential read-only companion endpoint, addressing §15's unified-history
requirement:

```
GET /equipment/{id}/history?include_legacy=true
```

returning a merged, paginated, `Page[T]`-shaped projection (§15) — not
finalized here; belongs to an implementation slice once its query
design is validated against real `EXPLAIN ANALYZE` output (§27).

No frontend-specific RPC-style endpoint is introduced — every endpoint
above is a plain resource-oriented REST route, matching this
repository's entire existing API surface.

---

## 26. Error contract

Following the flat `DomainError` hierarchy exactly (§4.5), proposed
(provisional) codes:

| Code | HTTP | Meaning |
|---|---|---|
| `RECONCILIATION_RUN_NOT_FOUND` | 404 | `run_id` does not resolve. |
| `RECONCILIATION_RUN_INVALID_STATE` | 409 | An operation requires the run to be in a state it isn't (e.g. triggering analysis on an already-`running` run). |
| `RECONCILIATION_FINDING_NOT_FOUND` | 404 | `finding_id` does not resolve, or does not belong to the given `run_id` (unified, per the existing "never distinguish missing vs. wrong-parent" information-boundary convention PR21E0 already established for dry-run-plan rows, §4.5). |
| `RECONCILIATION_FINDING_STALE` | 409 | Disposition CAS write matched zero rows — `version` mismatch or the finding was concurrently disposed. |
| `RECONCILIATION_SIGNOFF_INCOMPLETE` | 409 | Sign-off attempted while at least one finding on the run still has `disposition IS NULL` — review is not yet complete. |
| `RECONCILIATION_SIGNOFF_BLOCKED_REQUIRES_CORRECTION` | 409 | Sign-off attempted while at least one finding on the run is dispositioned `requires_correction` (OD-PR22-6, §20, §36) — review is complete, but a blocking correction is still outstanding. Deliberately a distinct code from `RECONCILIATION_SIGNOFF_INCOMPLETE`: "not yet reviewed" and "reviewed, blocking correction outstanding" are different classes of problem the caller must resolve differently (disposition the finding, vs. complete the separate correction workflow, §19). |
| `RECONCILIATION_SIGNOFF_ALREADY_EXISTS` | 409 | A sign-off already exists for this run (the UNIQUE constraint on `run_id`, surfaced as a domain error rather than a raw integrity-error 500). |

Each is a single flat `DomainError` subclass with a stable `code` and
`status_code`, documented with its specific sub-causes in its own
docstring — never split into multiple codes for what is really one class
of problem (§4.5's unified-stale-contract convention, e.g.
`RECONCILIATION_FINDING_STALE` deliberately covers both "someone else
just disposed it" and "you're operating on stale data" without
distinguishing them, matching `IMPORT_DRY_RUN_PLAN_STALE`'s own
precedent). No free-text business branching is exposed to the frontend —
every conditional UI behavior keys off `code`, never `detail` string
content.

---

## 27. Performance

Given the real ~51,000-row combined dataset (§4.8):

- **No per-event `SELECT`.** Every detection rule in §9/§10 is a single
  set-based SQL query (joins/window functions), never a per-row Python
  loop issuing individual queries — mirroring PR21D2's own
  `bulk_insert_events`/`bulk_get_existing_by_identity` batching
  discipline (§4.1).
- **No N+1.** Finding-evidence construction (`evidence` JSONB, §17.2)
  is built from the same batch query results already fetched for
  detection, never a second per-finding round-trip.
- **No full-dataset frontend load.** All read endpoints (§25) return
  `Page[T]` (§4.7); the frontend never fetches "all findings" in one
  call.
- **SQL window functions** are the natural tool for §9.D's chronology
  analysis (e.g. `LAG()`/`LEAD()` over `PARTITION BY equipment_id ORDER
  BY occurred_at`) and for duplicate-candidate grouping (§9.C) — proposed
  here as the mechanism, with exact query shapes deferred to the
  implementation slice, validated against `EXPLAIN ANALYZE` on
  production-representative data volume before merge (matching this
  repository's own established evidence bar for PR14A/PR14B-class
  performance work, `docs/audits/05-pr14a-transaction-boundary-audit.md`,
  `06-pr14b-pagination-index-evidence.md`).
- **Bounded pagination** everywhere findings are listed (§25).
- **Asynchronous job framework reuse, if needed**: whether the full
  cross-table analysis genuinely requires the `ImportJob` lease/heartbeat
  machinery (i.e. whether it cannot complete inside one bounded HTTP
  request) is an empirical question for the implementation slice, not
  assumed here either way (§18 already designed the run lifecycle to
  support either outcome without a schema change). If synchronous, the
  bounded-concurrency/admission-control pattern from §4.6
  (`asyncio.Semaphore` + single deadline + shielded task) is reused
  directly, with new constants sized for this workload rather than
  reusing PDF/Excel's own tuned values verbatim.
- Do not assume synchronous HTTP analysis is safe without that
  empirical validation — this design deliberately keeps both paths open.

---

## 28. Audit

Per §4.5's existing framework and constants convention:

- **Audited, always (mandatory, not best-effort)**: run creation, run
  status transitions (`running`/`completed`/`failed`), every finding
  disposition change, sign-off creation. New constants added to
  `backend/app/core/audit.py` alongside the existing import constants,
  never inline strings.
- **Not audited**: read-only run/finding-list/detail queries — avoiding
  audit spam for pure reads, matching the review brief's own explicit
  instruction and this repository's existing convention (import-session
  reads are not individually audited either).
- **Actor vs. historical BME**: the audited `actor_user_id` on every
  PR22 mutation is always the current authenticated operator performing
  the action — never conflated with a `LegacyEquipmentEvent.legacy_bme_name`
  value, which remains historical personnel data with no live-identity
  claim attached (§9.G).

---

## 29. Retention/privacy

**Retention.** Reconciliation and sign-off evidence is governance
evidence — recommended **permanent retention**, explicitly *not* PR19A3's
180-day temporary-artifact policy (§4.5), which exists for transient
import-working-data, not for durable review/attestation records. This
mirrors how `LegacyMigrationAuthority` and `LegacyEquipmentEvent`
themselves are permanent, never subject to the 180-day cleanup job.

**Privacy.** `legacy_bme_name` is historical personnel data (§9.G) —
displayed only where operationally required for review (i.e. inside a
finding's own evidence when relevant, never copied redundantly into
every table that happens to reference the same event). No PR22 endpoint
exposes raw source-workbook contents, arbitrary internal identifiers
beyond what a reviewer operationally needs, or unnecessary free-text
notes fields beyond the bounded `disposition_note` (§17.2, length-bounded
by design, not a general-purpose comment box).

---

## 30. Frontend workflow

Only after the API (§25) is settled at implementation time — proposed
principles now, no component design:

- Thai-first, per this repository's established UI convention.
- Reconciliation review may reasonably favor a desktop/tablet-optimized
  layout over strict mobile-first, since the review brief itself notes
  this is a different usage pattern from dispatch/receipt's
  handheld-at-the-pool-desk context — but no raw JSON, no mass-edit
  without confirmation, and large touch targets remain baseline
  requirements regardless of device.
- Priorities: a clear per-run summary (§31), filters by finding
  category/status/severity, an equipment-centric drill-down view,
  evidence presented side-by-side (e.g. "this event" vs. "the other
  authority's event" for a duplicate finding) rather than as an opaque
  JSON blob.
- No business-rule enforcement in the frontend — every disposition
  transition, every sign-off completeness check, is re-verified
  server-side regardless of what the UI already showed (§22, §26). In
  particular, the sign-off preconditions in §20 (all findings
  dispositioned, zero `requires_correction`, and the rest) are enforced
  entirely by the backend: even if the UI incorrectly presents a
  sign-off action as available, the server-side transaction rejects the
  write (`RECONCILIATION_SIGNOFF_INCOMPLETE`/
  `RECONCILIATION_SIGNOFF_BLOCKED_REQUIRES_CORRECTION`, §26) — the
  backend is the sole source of truth for whether sign-off is possible.

---

## 31. Reconciliation dashboard

**Not general analytics/BI** — a narrowly scoped, run-bound operational
summary only, directly serving the review workflow itself: total
findings, open vs. disposed counts, breakdown by severity and by
category, and (once sign-off exists) the attestation summary (§17.2's
`attestation_summary`). **The `requires_correction` count is always
surfaced as its own distinct, visible figure — never folded silently
into "disposed"** (OD-PR22-6, §20, §36): a finding dispositioned
`requires_correction` is reviewed, but it is also an outstanding
sign-off blocker, and the dashboard must not present a run as
sign-off-eligible while that count is nonzero. No cross-run trend
analysis, no organization-wide metrics, no scheduling/alerting — those
would be Roadmap PR15's own broader observability scope (still
unscheduled per `docs/ROADMAP_STATUS.md`), not PR22's.

---

## 32. Report/export recommendation

**Not implemented in this design or in PR22A** — a future implementation
slice may add a sign-off report/export, and **should reuse the existing
`ExportDocument`/report-adapter architecture** (§4.6) rather than
introducing a new PDF/XLSX stack: a `LEGACY_RECONCILIATION_SIGNOFF` value
added to `ReportIdentity`, a new dataset builder function alongside
`build_receive_report_document`/etc., consumed by the same
`_build_export_document_for_request` dispatch point and the same three
existing output adapters (Browser Print/PDF/Excel). This recommendation
is recorded now so no future slice reinvents export infrastructure this
repository already has.

---

## 33. Migration strategy (design-only)

No migration is written by this document. When implementation begins,
the new tables (`legacy_reconciliation_runs`,
`legacy_reconciliation_findings`, `legacy_reconciliation_signoffs`, and
optionally a BME-alias table per OD-PR22-4) are additive-only, following
this repository's own "General rule applied throughout" migration
convention (`docs/audits/04-consolidated-implementation-plan.md` Part
E: "every migration below is additive-first... no migration in this plan
drops a column or deletes rows") and PR21A's own raw-SQL-plus-fail-closed-
convergence-check pattern (`0019_legacy_history_foundation.py`'s
`_verify_schema_convergence()`, §4.1) as the template to follow, not
reinvent.

---

## 34. Implementation slices

**All seven Owner Decisions (OD-PR22-1 through OD-PR22-7) are now
RESOLVED / OWNER APPROVED (§36).** PR22 implementation remains **not
started** as of this Owner Decision Closure round — no slice below has
begun. Every slice becomes eligible only after the governance PR
recording this closure round itself merges (per this repository's
Final Merge Gate discipline); listing a slice as "authorized" here
means its Owner-Decision-level blockers are cleared, not that
implementation work has commenced.

Proposed split (adjustable after implementation begins — not a
commitment):

- **PR22A — architecture/design (this document). Merged (GitHub PR
  #112).**
- **PR22B** — reconciliation schema + `LegacyReconciliationRun`
  foundation (migration, models, CAS admission, no analysis logic yet).
  **Authorized to implement the full column set, including the
  temporal-coverage columns (§17.2: `legacy_coverage_start`/
  `legacy_coverage_end`/`live_system_start`, `coverage_source`) —
  OD-PR22-7's resolution fixes their semantics, so this slice is no
  longer restricted to nullable/unused placeholders for them.**
- **PR22C** — deterministic analysis engine (§9's detection rules, §27's
  batch queries, finding persistence at run completion). **Authorized to
  implement §9.E's current-state comparison and §9.D's coverage-window-
  scoped chronology wording, per OD-PR22-7's resolution (§9.J) —
  including traceability, exact/semantic duplicate detection, chronology,
  Ward/BME traceability, pairing candidates (§11, per OD-PR22-1), and the
  unified legacy/modern projection comparison (§15). No destructive
  mutation.**
- **PR22D** — finding review/disposition API (§19, §25, §26).
  Administrator-only writes (OD-PR22-5), the approved four-value
  disposition vocabulary only (OD-PR22-2), CAS/freshness required, no
  bulk silent overwrite.
- **PR22E** — sign-off + concurrency/audit (§20, §22, §28). **Authorized
  to implement sign-off mechanics in full** — the attestation wording,
  the sign-off write path, and the sign-off acceptance criterion (§20) —
  now that OD-PR22-7 and every other sign-off-gating Owner Decision have
  resolved: the sign-off write path, the "all findings dispositioned"
  precondition, the `requires_correction == 0` precondition (per
  OD-PR22-6), exact run/snapshot/version binding, approved temporal
  coverage binding (per OD-PR22-7), Administrator-only sign-off (per
  OD-PR22-5), audit, concurrency protection, and superseding-run support
  where appropriate (per OD-PR22-3). Signed runs remain immutable. No
  interim, partial, or provisional sign-off endpoint is authorized under
  any circumstance — there is no rule-version-only fallback attestation
  contract to implement (§20 already retired it).
- **PR22F** — frontend real integration (§30).
- **PR22G** — governance sync (closes Roadmap PR22, mirrors PR21F's own
  pattern).

Each slice should remain independently reviewable, per this repository's
established preference for small slices over one large PR — matching how
PR21 itself split into Foundation/A/B/C/D1/D2/E0/E rather than one
monolithic change. **OD-PR22-7's resolution (§9.J, §36) removes the
cutoff-dependent-behavior gate that previously applied to PR22C and
PR22E, and the column-shape restriction that previously applied to
PR22B — every slice above is now eligible on Owner-Decision grounds,
subject only to this closure round's own merge and to each slice's
ordinary implementation dependencies (e.g. PR22C depends on PR22B's
schema, PR22E depends on PR22D's disposition API).**

---

## 35. Risks

- **Snapshot-consistency correctness** (§18) depends on `REPEATABLE READ`
  behaving as expected under this codebase's existing async SQLAlchemy
  session/transaction management — must be validated with a concrete
  concurrency test (two connections, one mutating `Equipment` mid-run)
  before PR22C merges, mirroring the two-connection PostgreSQL
  concurrency tests already established for PR19/PR20's own CAS paths.
- **Finding-evidence schema drift**: since `evidence` is JSONB
  (structured, but not database-enforced per-code), a future
  `rule_version` bump changing a finding code's evidence shape could
  make old findings' evidence harder to render generically in the
  frontend. Mitigated by keeping evidence rendering keyed off
  `(code, rule_version)` pairs, not `code` alone.
  performance is unproven until real `EXPLAIN ANALYZE` evidence exists
  against production-representative volume (§27) — genuinely a risk,
  not yet resolved by this design.
- **Future role-authorization loosening** (§21, OD-PR22-5) —
  Administrator-only disposition-setting is the Owner-approved policy
  for V1; revisiting it later (loosening to `equipment_pool_staff`)
  would be an additive, low-risk change if the Owner later approves a
  new, explicit governance decision to do so.
- **Temporal coverage implementation risk** (§9.J, OD-PR22-7) — the
  *business decision* is resolved (the two-boundary model, source via
  governed approval workflow, unified-projection post-cutoff treatment,
  per-authority coverage, §36); the remaining risk is purely
  implementation-correctness: (1) correct persistence and validation of
  `legacy_coverage_start`/`legacy_coverage_end`/`live_system_start` per
  migration authority (PR22B); (2) correct overlap/gap query logic
  against the unified projection, including the three cases in §9.J's
  table, without silently collapsing any of them (PR22C); (3)
  performance of the unified-projection comparison at production-
  representative volume (§27); and (4) concurrency/snapshot-consistency
  correctness for a run reading temporal coverage alongside
  `Equipment`/`BorrowTransaction`/`LegacyEquipmentEvent` under
  `REPEATABLE READ` (§18, §22). Mitigated by PR22B/PR22C's own
  implementation-time validation against real `EXPLAIN ANALYZE` evidence
  and concrete two-connection concurrency tests, matching the
  established pattern above.

---

## 36. Owner Decisions

*Status as of the PR22 Owner Decision Closure round (2026-08-22): the
Repository Owner approved all seven decisions below ("อนุมัติ OD-PR22-1
ถึง OD-PR22-7 ตาม Recommendation") — every decision below is
**RESOLVED / OWNER APPROVED**, not OPEN. This section retains each
decision's original framing (why it was escalated, what alternatives
were compared) as historical context, followed by its final approved
answer.*

Per the review brief's own instruction to inspect repository truth first
and minimize Owner Decisions, this design resolves everything it can
from existing convention (persistence model §17.1, read-only-first
lifecycle §18, append-only/no-destructive-CRUD policy §16, rule
versioning §24, lock ordering §23, error-contract shape §26) without
escalating any of those as Owner Decisions — they are engineering
judgment calls grounded in this repository's own established precedent,
not open business questions. The following, genuinely business-policy
questions were escalated, deliberately minimized to seven (six from the
original architecture round, plus OD-PR22-7 added in fix round 2 to
resolve a genuine content gap — the temporal-coverage boundary — an
independent review found this design had left undefined). All seven are
now resolved:

- **OD-PR22-1 — Pairing persistence model.** *Original question:* Is
  Issue↔Receive pairing (a) a purely analytical/review-time relation
  with no persisted artifact of its own, (b) a persisted reconciliation
  finding/artifact (this design's recommended default, §11-§12), or (c)
  excluded from PR22 V1 entirely, deferred further? **RESOLVED / OWNER
  APPROVED: option (b).** Issue↔Receive pairing is persisted only as a
  separate reconciliation artifact/finding — never as a mutation of
  `LegacyEquipmentEvent` into a paired transaction, and never as a
  fabricated `BorrowTransaction`. Pairing candidates are generated only
  by deterministic rules (§11) — never a nearest-timestamp heuristic,
  and fuzzy matching never becomes authoritative on its own. A
  human-approved disposition is required before a candidate becomes a
  confirmed reconciliation relationship; provenance of both source
  events remains intact throughout. The recommended representation
  remains the `PAIRING_CANDIDATE` reconciliation finding/artifact (§10,
  §11) unless implementation evidence later demonstrates a dedicated
  relation table is cleaner — the choice of table shape is an
  implementation detail; the business decision above is final.
- **OD-PR22-2 — Finding disposition vocabulary.** *Original question:*
  Is the four-value proposed set in §19 (`confirmed_valid`,
  `confirmed_duplicate`, `accepted_unresolved`, `requires_correction`)
  correct and complete, or does the Owner want it narrowed/extended?
  **RESOLVED / OWNER APPROVED: the four-value set exactly as proposed,
  unchanged.** Approved meanings: `confirmed_valid` = reviewed; data is
  correct as imported or the anomaly is valid/explained.
  `confirmed_duplicate` = reviewed; the finding represents a genuine
  exact or semantic duplicate — no source data is deleted.
  `accepted_unresolved` = reviewed; a real gap/problem exists but is
  explicitly accepted without correction before progression.
  `requires_correction` = reviewed; a separate, explicit, audited
  correction workflow is required — the disposition itself performs no
  correction. Severity and disposition remain independent (§19). No
  additional disposition value may be added without a new Owner
  Decision.
- **OD-PR22-3 — Reopen/supersede policy after sign-off.** *Original
  question:* Can a signed-off run ever be reopened or superseded, and
  under what authority/evidence? **RESOLVED / OWNER APPROVED:** a
  signed reconciliation run is immutable and is **never** reopened for
  mutation. If later evidence or corrected data requires another
  reconciliation, a **new** reconciliation run is created; the old
  signed run is preserved permanently, explicitly superseded (via
  `superseded_by_run_id`, §17.2), with a complete provenance/audit
  trail. No in-place editing of signed findings, signed dispositions, or
  a signed attestation is ever permitted. A superseding run does not
  erase the historical validity of what was reviewed at the time.
- **OD-PR22-4 — BME-name-to-User mapping (§9.G).** *Original question:*
  May raw historical BME names ever be mapped to current `User` records
  for display-only purposes, given they are historical personnel data?
  **RESOLVED / OWNER APPROVED: yes, display-only mapping is allowed.**
  An explicit, Administrator-managed alias mapping is added, comparable
  in principle to `LegacyWardAlias` (§4.1). Rules: the raw historical
  `legacy_bme_name` remains permanent and is never overwritten; the
  mapping may resolve a historical display name to a current `User` for
  display purposes only; a `User` is never auto-created; identity is
  never inferred automatically from string similarity; the mapping never
  claims "historical actor == authenticated current operator"; current
  actor audit identity (§28) remains completely separate from this
  display-only mapping. Exact schema/table naming remains an
  implementation detail.
- **OD-PR22-5 — Disposition-setting authorization.** *Original
  question:* Is finding disposition-setting Administrator-only (this
  design's default, §21), or should `equipment_pool_staff` also be
  permitted to set dispositions while sign-off itself remains
  Administrator-only? **RESOLVED / OWNER APPROVED: Administrator-only
  for V1, exactly as this design's default proposed (§21).**
  `equipment_pool_staff` may view/review reconciliation information where
  existing read permissions already allow, but may **not** set
  dispositions in V1. `read_only` remains view-only per the existing
  role rules. Final sign-off remains Administrator-only. No new role is
  introduced. A future loosening of the disposition-setting permission
  may be an additive change, but requires its own new, explicit
  governance decision — it is not authorized by this entry.
- **OD-PR22-6 — "PR22 complete" / cutover-readiness threshold.**
  *Original question:* What measurable condition constitutes
  "reconciliation passed" for Roadmap PR23's own cutover-readiness
  gating? **RESOLVED / OWNER APPROVED:** PR22 reconciliation may be
  considered passed/complete for progression to PR23 only when (1) every
  reconciliation finding has a disposition; (2) the `requires_correction`
  count is zero; (3) the reconciliation run has a valid final sign-off;
  and (4) that sign-off is against the exact immutable run/snapshot,
  approved rule version, approved data/migration authorities, and
  approved temporal coverage (§20). `accepted_unresolved` **is**
  permitted at PR22 completion / PR23 entry, provided it was explicitly
  reviewed, carries an authorized disposition, and is included
  transparently in the final sign-off evidence; `confirmed_valid` and
  `confirmed_duplicate` are likewise acceptable terminal review
  conclusions. Any outstanding `requires_correction` finding blocks PR22
  completion / PR23 cutover readiness — and, per §20's sign-off
  preconditions (fix round 1), also structurally blocks condition (3)
  itself: a valid final sign-off cannot exist while any finding remains
  `requires_correction`, so conditions (2) and (3) are never actually in
  tension — they are restated together here for clarity, not because
  either could hold without the other. "PR22 complete" does **not** mean
  "all historical data is objectively perfect" — it means the defined
  reconciliation workflow is complete and no known item requiring
  correction remains outstanding. This resolves the policy question this
  design surfaced for Roadmap PR23's benefit; PR23's own cutover-evidence
  design remains out of this document's scope (§7).
- **OD-PR22-7 — Legacy data cutoff / temporal reconciliation boundary
  (§9.J).** *Added in fix round 2, responding to an independent-review
  [P1] finding.* *Original question:* What authoritative temporal
  boundary defines the historical coverage against which a PR22
  reconciliation run is evaluated, and how must post-boundary live
  activity be treated? **RESOLVED / OWNER APPROVED: the two-boundary
  model (§9.J's recommended-but-previously-not-adopted direction).**
  Three authoritative, governance-approved concepts: `legacy_coverage_start`,
  `legacy_coverage_end`, and `live_system_start` — legacy coverage
  **must** be governance-approved; `observed_min_event_at`/
  `observed_max_event_at` remain evidence only and **must not**
  automatically become authoritative coverage boundaries. Source of
  coverage (resolving §9.J's alternatives (A)-(E)): `legacy_coverage_start`/
  `legacy_coverage_end` must be explicitly approved by an
  Administrator/Owner-governed workflow, associated with the relevant
  legacy migration authority/reconciliation scope — never derived solely
  from `MIN(event timestamp)`, `MAX(event timestamp)`, workbook upload
  timestamp, or import-completion timestamp (those remain displayable
  supporting evidence only, never the authoritative value).
  `live_system_start` is a distinct governed boundary — representing
  when modern-system transaction history becomes authoritative for the
  reconciliation projection — and is not automatically assumed equal to
  `legacy_coverage_end`; the system represents all three relationships
  explicitly: **gap** (`legacy_coverage_end < live_system_start`),
  **clean handoff** (`legacy_coverage_end == live_system_start`), and
  **overlap** (`legacy_coverage_end > live_system_start`), never
  collapsing any of the three. Post-cutoff/overlap treatment (resolving
  §9.J's four options): the **unified legacy + modern history
  projection** (§15) is the reconciliation context — post-cutoff live
  activity is used through that unified projection, never blindly
  excluded, never treated as legacy history, and never changes
  Equipment's current state; legacy and modern source identity/
  provenance stay distinct (never physically merging
  `LegacyEquipmentEvent` and `BorrowTransaction` tables), the projection
  is read/query/service-layer only, uses source/type markers,
  deterministic rules only, and performs no automatic destructive
  reconciliation. During overlap periods both sources remain visible —
  one source is never deleted merely because another source covers the
  same date; any duplicate/conflict becomes reconciliation evidence/a
  finding. Corrected/re-exported authorities (resolving §13's open
  question): do **not** silently inherit temporal coverage — each
  new/superseding authority must have explicitly approved coverage; an
  approved supersession relationship may record intended inheritance
  only if the Administrator explicitly confirms it, never inferred.
  **Because OD-PR22-7 is now resolved, final sign-off is authorized**
  (§20) under the preconditions defined there — no partial/interim/
  provisional sign-off exists. Unblocks: PR22C's current-state-comparison
  and coverage-scoped chronology rules, and all of PR22E's sign-off
  mechanics (§20, §34) — these were the behaviors this decision, while
  OPEN, had blocked.

**What did NOT require an Owner Decision, and why**: the persistence
option (§17.1 — matches every analogous already-merged workflow, no
genuine ambiguity); the read-only-first/snapshot architecture (§5, §18 —
directly requested by the task brief itself, not a new choice); the
append-only/no-destructive-CRUD policy (§16 — directly required by
PR21's own already-Owner-approved immutability principle, §4.9, not a
new question); rule versioning (§24 — a standard engineering practice,
no business tradeoff); lock ordering (§23 — a direct, non-ambiguous
extension of the existing Job→Session→resource convention); the
corrected-source technical mechanism (§13 — PR21's design already
resolved the governing policy, §4.9; only the exact table shape remained,
which is an implementation detail, not a policy question).

---

*(End of design document. See the PR description for the required final
report covering evidence reviewed, recommendations, and confirmation
items.)*
