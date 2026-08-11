# Roadmap PR20 — Equipment Master Import: Design Specification

**Status:** Design only. Not implemented. This document defines the
architecture, contract, and open questions for PR20; it does **not**
authorize implementation of the parts marked OPEN below. Per
`docs/ENGINEERING_WORKFLOW.md` §7, "implementation depending on an open
Owner Decision MUST NOT begin" — three Owner Decisions are opened by this
document (§9) and implementation of the areas they gate must wait for
Repository Owner resolution.
**Repository:** Medical Equipment Pool. Not MEMS, not Recall Monitor.
**Baseline:** `e3156bfc231fcbc126251f41292bc397fdf8ad3f` — the real
squash-merge SHA of GitHub PR #88 (Post-PR19B Governance Sync), itself on
top of GitHub PR #80 (Roadmap PR19B, real squash SHA
`04f5bf5c76b51744981d1cc8072c074e604224e9`). Roadmap PR19 (Legacy Import
Foundation, backend + frontend skeleton) is fully merged at this baseline.
This design branches directly from this commit.
**Scope authority:** `docs/audits/04-consolidated-implementation-plan.md`
Part D, Group 8, "PR20 — Equipment Master Import."
**Dependency:** PR19A (the backend import framework) only. PR19B is a
frontend preview and is not a dependency (confirmed in
`docs/audits/04-consolidated-implementation-plan.md`).
**Provenance (for audit trail only — every section below is
self-contained and does not require reading any of this history to
implement):** written after a full inspection of the actual merged PR19A
runtime (models, schemas, API, services, adapter contract, migration,
config, RBAC, tests) and the actual current Equipment domain runtime
(model, schemas, CRUD, API, and the pre-existing, unrelated Roadmap PR12
update-only Inventory Import feature), not from Roadmap prose alone, per
this task's explicit instruction.

---

## 1. Objective

Specify the complete design for importing Equipment Master data — BCM
Code, Item Number, equipment attributes, and existing hospital QR linkage
— into this system as a concrete adapter over the already-merged PR19A
Legacy Import Foundation, with equipment duplicate detection and
equipment-record validation, per
`docs/audits/04-consolidated-implementation-plan.md`'s PR20 Objective.

This document resolves every question that the merged PR19A runtime and
existing governance can answer authoritatively. It explicitly does **not**
resolve, and instead opens as Owner Decisions (§9), the questions that
depend on evidence not present anywhere in this repository: the real
legacy Equipment Master source-file column layout, the create-vs-update
policy for this specific dataset, and the BCM/Item-Number identity-conflict
resolution policy. No parser is written, no field mapping is finalized, no
create/update decision is made, and no implementation code is included in
this PR (§26).

---

## 2. Inputs Reviewed

| Area | Source | What it established |
|---|---|---|
| PR19A backend runtime | `backend/app/models/import_session.py`, `app/schemas/import_session.py`, `app/api/v1/import_sessions.py`, `app/crud/import_session.py`, `app/crud/import_job.py`, `app/crud/import_retention.py`, `app/services/import_validation_service.py`, `app/services/import_execution_service.py`, `app/services/import_retention_service.py`, `app/services/import_lease.py`, `app/services/import_adapter.py`, `alembic/versions/0015_import_foundation.py`, `app/core/config.py` | The exact reusable mechanisms available to PR20 (§3) and, critically, that **no file-upload endpoint exists anywhere in the merged framework** — `POST /{session_id}/source` accepts only checksum+metadata, never raw bytes, and `ImportAdapter.parse(raw_input)` is always called with `raw_input=None` in the merged code. |
| PR19A design doc | `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §26 (Non-Goals), and its explicit "a future concrete-adapter slice" forward-references (§3.6, source freeze, checksum trust, retention, security table) | PR19A deliberately built zero parsing/upload/byte-storage/security-scanning machinery — that entire surface is PR20's to design, not merely "write an adapter." |
| Current Equipment domain runtime | `backend/app/models/equipment.py`, `app/schemas/equipment.py`, `app/crud/equipment.py`, `app/api/v1/equipment.py` | Exact column list, lookup functions, and that **no create-or-update/upsert-by-BCM helper exists** — PR20 must design its own resolution logic. |
| Existing, unrelated PR12 Inventory Import | `backend/app/services/import_service.py`, `app/api/v1/inventory_import.py`, `backend/tests/test_import.py` | A **different, already-shipped, update-only** feature (BCM-only match key, `.xlsx`-only, its own `REQUIRED_HEADERS` explicitly marked "illustrative... pending confirmation against a real hospital inventory export"). PR20 must not duplicate this code path or its models; it is informative precedent, not an authoritative source for PR20's own field mapping or policy. |
| Identifier model | `knowledge/adr/ADR-002-identifier-model.md`, `ADR-003-bcm-manual-search.md`, `ADR-004-hospital-item-no-qr.md`, `knowledge/architecture/identifiers.md` | UUID/BCM Code/Item No/Asset Number each have exactly one fixed role; canonicalization functions (`normalize_bcm_code`, `normalize_item_no`) already exist and must be reused, not reimplemented; Asset Number must never be fabricated or inferred from BCM/Item No — the same constraint that forced PR12 into update-only mode is directly relevant to PR20's own create-vs-update question (§9, OD-2). |
| Roadmap scope | `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8 | PR20's Objective, Boundary (Ward/BME values belong to PR21, not PR20), and Dependency (PR19A only). |
| Engineering process | `docs/ENGINEERING_WORKFLOW.md` §6, §7 | A Design PR is required before this work (new API surface, new database writes, new business-rule matching/duplicate-detection semantics); an Owner Decision is required for unresolved business policy, and implementation depending on one must not begin. |
| Source-evidence search | Repository-wide search for "Equipment Master," legacy column names, sample `.xlsx`/`.csv` fixtures | **Zero real evidence found** anywhere in the repository of the actual legacy Equipment Master column layout, encoding, or sample data (§7, §9 OD-1). |

---

## 3. What PR19A Already Provides — Reused Without Modification

PR20 is a **consumer** of the PR19A framework. Nothing in this section is
re-implemented, forked, or weakened by PR20.

### 3.1 Session / source / job lifecycle (reused as-is)

`ImportSession` (`import_sessions`), `ImportSource` (`import_sources`),
`ImportJob` (`import_jobs`, discriminated by `job_type` ∈
`{validate, dry_run, execute}`), `ImportRowError` (`import_row_errors`, =
`ValidationFinding`) — all four tables, their CHECK-constrained status
enums, the 11-state session state machine (`created → validating →
validated|validation_failed → dry_run_running → dry_run_completed|
dry_run_failed → executing → completed|failed`, plus `cancelled` reachable
from `{created, validated, validation_failed, dry_run_completed,
dry_run_failed}`), and the `version` optimistic-concurrency counter are
used exactly as merged. PR20 introduces no new table for session/job
bookkeeping.

### 3.2 API surface (reused as-is)

`POST /import-sessions`, `GET /import-sessions`, `GET
/import-sessions/{id}`, `GET /import-sessions/{id}/status`, `POST
/import-sessions/{id}/source`, `POST /import-sessions/{id}/cancel`, `POST
/import-sessions/{id}/recover`, `POST /import-sessions/{id}/validate`,
`POST /import-sessions/{id}/dry-run`, `POST /import-sessions/{id}/execute`,
`GET /import-sessions/{id}/errors`, `POST
/import-sessions/retention/cleanup` — all reused unmodified, gated by the
same `require_roles(*ADMINISTRATOR_ONLY_ROLES)` dependency (§10). PR20
adds **no new endpoint under `/import-sessions`**; the only new API
surface PR20 may need is a separate, narrowly-scoped byte-ingestion
endpoint (§6.2 — architecture proposed, exact shape gated by design
review, not by an Owner Decision).

### 3.3 Admission, lease, fencing, recovery (reused as-is)

`admit_phase_job` (generic CAS admission for all three phases),
`renew_lease_loop`, `fenced_phase_success`/`fenced_phase_failure`,
`claim_stale_job`/`transition_session_for_recovery`,
`bound_failure_message` (never persists raw exception text), and the
TX1/TX2 crash-recovery split (a genuine crash rolls back TX1 entirely; a
clean completion — even one that finds blocking errors — commits TX1 with
its findings) are all reused unmodified. PR20's adapter code runs *inside*
these mechanisms; it never re-implements lease/fencing/recovery itself.

### 3.4 Dry-run enforcement (reused as-is)

`run_dry_run` opens a separate DB session and (on PostgreSQL) issues `SET
TRANSACTION READ ONLY` before calling `adapter.plan_dry_run(ro_db)`. PR20's
`plan_dry_run` implementation is therefore *structurally* prevented from
writing to the database by the database itself, not merely by convention.

### 3.5 Execute idempotency and CAS admission (reused as-is)

State-based replay (`completed` → return existing session unchanged;
`executing` → `409` conflict or recovery-required; anything else →
`409 IMPORT_SESSION_INVALID_STATE`), single-winner CAS admission
(`dry_run_completed → executing`), and `adapter.execute(db)` running
inside the same read-write transaction (TX1) as the fenced completion
write are reused unmodified (§6.6, §16).

### 3.6 Retention (reused as-is)

`POST /import-sessions/retention/cleanup`, 180-day `IMPORT_RETENTION_DAYS`
(configurable), `SELECT ... FOR UPDATE SKIP LOCKED` claim, redact-in-place
of `import_sources.filename/content_type`, `import_row_errors.message/
field`, `import_sessions.notes`. PR20 must apply the same discipline to
any *new* PII-bearing field it introduces (§13) but does not modify the
retention mechanism itself. **PR20 must not eagerly set
`source_bytes_deleted_at`-equivalent bookkeeping for any new byte-storage
field it adds** — the PR19A design doc (§18, forward reference) explicitly
requires a future byte-storing slice to drive that field from a real,
independently-retried deletion attempt, not from the same code path that
performs the redaction UPDATE.

### 3.7 What PR19A explicitly does *not* provide (PR20 must design these)

Per PR19A design doc §26 (Non-Goals) and its forward-reference notes: **no
Excel/CSV parser, no upload endpoint, no raw source-byte storage, no
malware/formula/macro handling, no checksum-verification-against-real-bytes
step.** PR19A's `POST /{id}/source` trusts a caller-supplied checksum with
no bytes behind it. This is the single largest architectural gap PR20 must
close (§6.2), independent of, and prior to, any Equipment-specific mapping
question.

---

## 4. What the Current Equipment Domain Already Provides — Reused Without Modification

### 4.1 Model and identifiers (reused as-is)

`Equipment` (table `equipment`): `id` (UUID PK), `asset_number` (unique,
NOT NULL), `serial_number` (unique via `uq_equipment_serial_number`,
nullable), `equipment_name` (NOT NULL), `item_no` (unique, nullable),
`bcm_code` (unique, nullable), `category_id`/`department_owner_id`/
`current_location_id` (FKs, `ON DELETE RESTRICT`), `status`
(`EquipmentStatus`, NOT NULL, default `AVAILABLE_AT_POOL`),
`legacy_status` (historical-only, never read by workflow), `qr_code_value`
(retired legacy QR, never read), `pm_due_date`/`cal_due_date`, `asset_id`
(PR12 provenance field, **not** unique-constrained), `raw_source_status`
(PR12 provenance field), `equipment_metadata` (JSON). PR20 introduces no
new column to this table without an explicit justification recorded as an
Owner Decision (per the user's instruction and this document's own
scope-guard, §26).

### 4.2 Canonicalization (reused as-is)

`app.services.identifiers.normalize_bcm_code` / `normalize_item_no`
already implement ADR-002's canonicalization rules (BCM: trim, uppercase,
canonical `BCM`-prefixed form, digit width preserved; Item No: trim only,
case/formatting preserved exactly). PR20's adapter must call these
functions on every incoming BCM/Item No value before any lookup or write
— exactly as PR12's `import_service.py` already does. PR20 must not invent
a second canonicalization implementation.

### 4.3 Lookup functions (reused as-is)

`get_by_bcm_codes(db, values) -> dict[str, Equipment]` and
`get_by_item_nos(db, values) -> dict[str, Equipment]` (both bulk, exact,
unique-guaranteed by DB constraint) are the correct, existing, bulk
building blocks for PR20's matching step (§8) — reused directly, avoiding
N+1 queries exactly as `preload_business_context` intends (§6.4). No new
lookup function is needed for BCM/Item No matching.

### 4.4 What the Equipment domain does *not* provide (informs, does not
block, PR20 design)

No `create_or_update`/upsert-by-BCM helper exists — §9 OD-2 must resolve
whether PR20 needs one at all (update-only would not). `asset_id` has no
DB uniqueness guarantee (deliberately, per PR12's own Owner Decision — see
`get_by_asset_ids`'s "application-layer conflict flagging, not a
uniqueness guarantee" behavior) — if PR20's field mapping ends up including
`asset_id` (§9 OD-1, not yet knowable), it must follow the same
non-unique, conflict-flagging pattern PR12 established, not invent a new
uniqueness constraint unilaterally.

---

## 5. Relationship to Roadmap PR12's Existing Inventory Import — Explicit Boundary

Roadmap PR12 already shipped a **complete, separate, update-only** import
feature (`POST /import/preview`, `POST /import/commit`, BCM-only match
key, its own `REQUIRED_HEADERS`, its own bounded-upload/zip-bomb
protections). PR20 is **not** an extension, replacement, or superset of
PR12's feature. The two are architecturally disjoint:

| | PR12 Inventory Import (existing, shipped) | PR20 Equipment Master Import (this design) |
|---|---|---|
| Framework | Standalone (`import_service.py`, no PR19A involvement) | PR19A `ImportSession`/`ImportJob` framework |
| API | `/import/preview`, `/import/commit` | `/import-sessions/*` (reused, §3.2) |
| Match key | BCM Code only | Undecided — §9 OD-3 |
| Create vs update | Update-only, by Owner Decision (PR12-H1/H1R) | Undecided — §9 OD-2 |
| Fields written | `asset_id, brand, model, raw_source_status` + opaque metadata only | Undecided — §9 OD-1 |
| Source-column evidence | Its own `REQUIRED_HEADERS`, itself marked illustrative/unconfirmed | None found anywhere (§7) |
| Concurrency/lease/retention | None (single-request preview→commit) | Full PR19A session/job/lease/retention lifecycle |

PR12's precedent is **informative** (it establishes that this codebase
already once concluded "invent no new identifiers, update-only, when
source evidence is thin" — see ADR-002's explicit "Asset Number... not
merged with, or inferred from, BCM Code or Item No" clause) but is **not**
directly authoritative for PR20, because PR20 targets a different dataset
(the full Equipment Master, not incremental attribute refresh) with a
materially different objective (durable legacy migration, not periodic
sync) per `docs/audits/04-consolidated-implementation-plan.md`. §9 OD-2
must resolve PR20's own policy explicitly, not inherit PR12's by default.

Both features may coexist permanently; PR20 does not deprecate or replace
PR12's `/import/*` endpoints.

---

## 6. Architecture: How PR20 Plugs Into PR19A

### 6.1 `dataset_type` and adapter registration

PR20 implements a concrete `EquipmentMasterAdapter(ImportAdapter)` in a
new module (e.g. `backend/app/services/import_adapters/equipment_master.py`)
and calls `register_adapter("equipment_master", EquipmentMasterAdapter())`
at application startup (module import time, alongside existing router
registration in `app/main.py` or an equivalent startup hook — exact wiring
point is an implementation detail for the implementation PR, not a design
question). `dataset_type="equipment_master"` becomes the value clients
must pass to `POST /import-sessions {"dataset_type": "equipment_master"}`.
This is the only change to session-creation behavior; no new endpoint is
needed for this step.

### 6.2 File ingestion — the gap PR19A left open

**This is a genuine, non-Equipment-specific architecture problem PR20 must
solve, independent of §9's business-policy Owner Decisions.** The merged
`POST /{session_id}/source` only accepts `{checksum, byte_size,
content_type?, filename?, source_version?}` — never raw bytes — and
`ImportAdapter.parse(raw_input)` is always invoked with `raw_input=None`
today. For PR20 to parse an actual workbook, one of the following must
exist, and this design proposes the first as the default, subject to
independent review (not an Owner Decision — this is a technical
architecture question the design/review process can resolve on its own,
per `docs/ENGINEERING_WORKFLOW.md` §7's "unresolved *business* policy"
qualifier):

- **Proposed default: a new, narrowly-scoped upload endpoint** — e.g.
  `POST /import-sessions/{session_id}/source/upload`, Administrator-only,
  accepting `multipart/form-data`, bounded by the same discipline PR12
  already established (`MAX_UPLOAD_BYTES`, zip-entry-count/size/ratio
  bounds, worksheet-count/header-column bounds — reuse PR12's constants
  and pattern rather than re-deriving them), which (a) computes the
  checksum server-side from the uploaded bytes (closing PR19A's own
  documented "checksum trust boundary" gap — the design doc explicitly
  requires this of "a future concrete-adapter slice"), (b) stores the
  bytes in a bounded, retention-aware location, and (c) calls the existing
  `register_or_correct_source` CRUD function with the server-computed
  checksum/byte_size, exactly as `POST /{id}/source` does today for the
  metadata-only case. The existing `POST /{id}/source` endpoint remains
  usable for future adapters that resolve their own checksum out-of-band;
  PR20 does not remove or modify it.
- **Byte storage location**: proposed default is the same PostgreSQL
  database (a new column or a new narrowly-scoped table, e.g.
  `import_source_blobs(import_source_id PK/FK, content BYTEA)`, 1:1 with
  `import_sources`, `ON DELETE RESTRICT`), bounded by the same
  `MAX_UPLOAD_BYTES` ceiling as PR12 (10 MiB) — small enough that a
  dedicated object-storage integration is not justified for V1, and
  consistent with this repository's existing pattern of storing bounded
  binary content in PostgreSQL only where a size ceiling already exists
  (there is no existing object-storage integration in this codebase to
  build on). This keeps retention/redaction trivial (same transactional
  boundary as the rest of PR19A's redact-in-place mechanism, §3.6) instead
  of requiring a second, out-of-band deletion contract.
- **Retention obligation this reintroduces**: PR19A's design doc explicitly
  warns that a future byte-storing slice "must, as a required acceptance
  criterion of its own design," drive `source_bytes_deleted_at` from a
  genuine, independently-retried deletion attempt, not set it eagerly in
  the same code path as the rest of retention redaction. PR20's retention
  extension must therefore add its own bounded retry/outbox mechanism for
  blob deletion, verified by a dedicated PostgreSQL test proving a blob
  actually disappears (not merely that a timestamp column is set).

This subsection is **proposed architecture, not a finalized decision** —
it is included so the implementation PRs (§24) have a concrete starting
point for independent review, and so the Owner Decisions in §9 can be
evaluated against a realistic ingestion mechanism rather than an abstract
one. Independent review of the implementation PR that adds this endpoint
must re-validate the bounds and the blob-retention design before merge.

### 6.3 `EquipmentMasterAdapter` shape (structure resolved; field-level
content gated by §9 OD-1)

```python
class EquipmentMasterAdapter(ImportAdapter):
    dataset_type = "equipment_master"
    ruleset_version = "1"

    def parse(self, raw_input: bytes) -> list[RawImportRecord]:
        # Opens the workbook via openpyxl (reusing PR12's parsing
        # discipline: header detection, blank-row skip, bounded rows/
        # worksheets/headers), yields one RawImportRecord per data row,
        # 1-based row_number matching the source file. Exact column
        # names: BLOCKED on §9 OD-1.
        ...

    async def preload_business_context(self, db, records) -> EquipmentMasterContext:
        # Bulk-resolves every distinct BCM/Item No appearing in `records`
        # via the existing get_by_bcm_codes/get_by_item_nos (§4.3) in
        # exactly two queries, regardless of row count — avoids N+1,
        # matching PR19A2's precedent. Returns a context object exposing
        # both maps to validate_business_rules.
        ...

    def validate_business_rules(self, record, context) -> list[FieldError]:
        # Per-row: canonicalize BCM/Item No (§4.2), check required
        # fields, check within-workbook duplicates, resolve identity
        # against `context` (§9 OD-3), classify legacy status (§9 OD-1),
        # and — if create is authorized (§9 OD-2) — validate the
        # would-be-created record against the same constraints
        # `POST /equipment` already enforces. Exact rules: BLOCKED on
        # §9 OD-1/OD-2/OD-3.
        ...

    async def plan_dry_run(self, ro_db) -> DryRunPlan:
        # Re-runs the same matching/classification logic (business logic
        # duplicated intentionally between validate and plan_dry_run is
        # avoided by sharing a common pure-function core, not by two
        # independent implementations) against the read-only session,
        # producing counts only (§12). Never writes.
        ...

    async def execute(self, rw_db) -> int:
        # Applies the resolved create/update decisions from the dry-run
        # plan to `rw_db`, inside the caller's existing transaction
        # (§3.5) — never commits/rolls back itself. Returns imported_rows
        # count. Exact write behavior: BLOCKED on §9 OD-1/OD-2.
        ...
```

This shape is implementation-grade for every part not gated by an Owner
Decision: the adapter's *structure*, its integration points with PR19A's
lease/fencing/dry-run/execute mechanics, and its reuse of
`preload_business_context` for bulk lookups are fully specified. Only the
row-level *content* of `validate_business_rules`/`execute` — which fields
exist, how they map, and what identity/create-update policy governs them
— is blocked.

---

## 7. Source Workbook Contract — Partially OPEN

The following bounds and behaviors are resolvable *without* knowing the
real column layout, and are specified now:

- **File type**: `.xlsx` only (matches this codebase's only existing
  precedent, PR12; no evidence anywhere suggests a different legacy
  export format).
- **Size/structural bounds**: reuse PR12's exact constants
  (`MAX_UPLOAD_BYTES=10MiB`, zip-entry/decompression-ratio bounds,
  `MAX_WORKSHEET_COUNT=25`, `MAX_HEADER_COLUMNS=200`) and its
  `MAX_IMPORT_ROWS=5000` ceiling — already proven correct by PR12's own
  independent review (findings H2/H2R). PR20 must not re-derive these
  numbers from scratch.
- **Blank rows**: skipped (not counted toward `total_rows`), matching
  PR12's convention.
- **Repeated headers / merged cells / hidden rows / formulas**: PR20 must
  read literal cell *values* only (never formula text, never execute
  formulas — §21), reject a worksheet whose declared header row does not
  parse to a set of distinct non-blank names, and treat merged-cell
  regions as their top-left value only (openpyxl's default merged-cell
  read behavior) — this is a parsing-robustness requirement independent
  of what the columns are named.
- **Numeric cells rendered as identifiers** (e.g. Excel silently storing
  `"00123"` as the number `123`): PR20 must read BCM/Item No/Asset Number
  candidate cells as text, not numeric, to avoid silent leading-zero loss
  — this constraint is knowable now (any identifier can suffer this bug)
  even though *which* column is the identifier column is not.
- **Duplicate rows** (byte-identical row content repeated): treated as two
  separate logical rows for row-numbering/finding purposes; whether they
  collapse to one BCM/Item-No conflict is §9 OD-3's concern, not a
  parsing concern.
- **Completely empty file**: `total_rows = 0`, a structural
  `validation_failed` outcome (mirrors PR19B's own "structural failure"
  fixture semantics already established in the merged frontend — a
  `validation_failed` session with null counters and a bounded generic
  `failure_reason`, not a fabricated zero-row "success").

**What remains OPEN**: the actual header row's column names, their order,
their data types, and how many distinct sheets/tabs a real legacy export
contains. §9 OD-1.

---

## 8. Field Mapping — OPEN (§9 OD-1)

No field mapping can be specified. The repository contains zero real
evidence of the legacy Equipment Master source's column layout (§2, source
row "Source-evidence search"). PR12's `REQUIRED_HEADERS` is the closest
artifact in the codebase and is explicitly marked "illustrative...
pending confirmation against a real hospital inventory export" by its own
authors — it must not be treated as PR20's source contract by inheritance.

Per the user's explicit instruction for this design round: **this document
does not guess column names, does not assume PR12's headers apply, and
does not propose a field mapping.** §9 OD-1 requests the concrete artifact
needed (a real sample export, or an Owner-provided column specification)
before this section can be completed in a follow-up revision of this
document or a dedicated field-mapping addendum.

---

## 9. Owner Decisions Opened by This Design

Per `docs/ENGINEERING_WORKFLOW.md` §7, each of the following is a genuine
business-policy question this repository's evidence cannot resolve.
**Implementation of the areas each gates must not begin until the
Repository Owner resolves it.**

### OD-1 — Real Equipment Master source schema

**Status: OPEN. Blocking.**

**Question:** What are the actual column names, order, data types, and
sheet/tab structure of the legacy Equipment Master export this system must
import? Does more than one legacy source format exist (e.g. different
export vintages)?

**Why this repository cannot resolve it:** exhaustive search (file
contents, filenames, fixtures) found zero real sample data or column
specification anywhere in the repository (§2). PR12's own `REQUIRED_HEADERS`
is explicitly marked unconfirmed by its own author and governs a different
feature.

**What is needed to close this:** a real sample legacy Equipment Master
export (redacted of any real patient/PII if applicable — equipment data
itself is not expected to be patient-identifying, but the Owner should
confirm), or a written, Owner-approved column specification, provided to
the implementing session before §7/§8/§10 (validation taxonomy,
lifecycle-status mapping) can be completed.

### OD-2 — Create-vs-update policy

**Status: OPEN. Blocking.**

**Question:** When a legacy row does not match any existing Equipment
record (by whatever identity policy OD-3 settles), does PR20 (a) create a
new Equipment record, (b) reject the row as a blocking validation finding
(update-only, mirroring PR12's precedent), or (c) something else (e.g.
create only for rows within a specific legacy status subset)? If update is
permitted for a matched row, which fields may be overwritten by the
legacy value, and which must be preserved from the existing record
regardless of what the workbook contains?

**Why this repository cannot resolve it:** PR12's update-only decision was
made for a *different* dataset/objective (periodic incremental sync of
attributes for already-known equipment) under an explicit Owner Decision
recorded for that PR, not for PR20's objective (initial legacy-data
migration, which by its nature is likely to encounter equipment that has
never existed in this system before — an update-only policy could make
correct migration outcomes structurally impossible for genuinely new
records). ADR-002's constraint that Asset Number must never be fabricated
or inferred is directly relevant here but does not, by itself, forbid
*legacy-provided* Asset Number values from being used to create a record —
that is exactly the open question.

**The user's explicit instruction for this round applies directly here:**
this design does not choose an answer or default. If create is authorized,
the specific field set a create may populate, and the exact rule for which
existing-record fields an update may or may not touch (mirroring PR12's
own restriction — see §4.4 — to a small, explicit, non-identity field
set), must be recorded as part of the Owner Decision's resolution, not
inferred afterward.

### OD-3 — BCM / Item Number identity-conflict policy

**Status: OPEN. Blocking.**

**Question:** How does an incoming legacy row match an existing Equipment
record? Specifically:

- Is a legacy row's BCM value alone sufficient to identify a match (PR12's
  precedent), or must both BCM and Item No agree (per
  `docs/audits/04-consolidated-implementation-plan.md`'s literal
  "BCM and Item Number matching" Objective wording, which is ambiguous
  between "either" and "both")?
- What happens when a row's BCM matches Equipment A but its Item No
  matches Equipment B (a genuine identity conflict)?
- What happens when one identifier matches an existing record and the
  other identifier on the same row is blank, or differs from that
  record's own value, or matches no record at all?
- What happens when a row's BCM and Item No both match the *same*
  existing record (the unambiguous, safe case) versus when they disagree?
- Can the legacy source itself contain duplicate BCM or duplicate Item No
  values across different rows? If so, is that a per-row blocking finding,
  or a workbook-level structural failure?

**Why this repository cannot resolve it:** ADR-002/003/004 define what
each identifier *means* (one fixed role each) but not the cross-identifier
conflict-resolution algorithm a bulk import must apply when two
independent identifiers on the same incoming row disagree about which
existing record they describe. No prior PR in this codebase has needed to
resolve this — PR12 uses BCM only and never encounters this class of
conflict.

**Default recommendation for Owner consideration (not a decision made by
this design):** identity conflicts (both identifiers present but pointing
at different existing records, or contradicting an unambiguous prior
match) should be a **blocking ERROR finding**, never a silent merge or a
"pick one" heuristic — consistent with this codebase's "never silently
merge conflicting identities" review discipline demonstrated elsewhere
(e.g. PR19B's own PR80-H1R fix). The Owner should confirm or override this
default.

---

## 10. Equipment Lifecycle Mapping — OPEN, gated by OD-1

Only `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`,
`DECOMMISSIONED` are legal target values (§4.1); this design introduces no
fifth state, and any legacy status this design cannot safely map produces
a blocking `ERROR` finding rather than inventing a placeholder state
(`UNKNOWN`/`IMPORTED`/`PENDING`/etc. are explicitly disallowed by this
document, matching the task's own constraint). **The concrete mapping
table itself cannot be written without knowing what legacy status values
actually appear in the source** (§9 OD-1) — this section is a placeholder
for that mapping table once OD-1 resolves, plus the classification rule
above, which is final regardless of OD-1's outcome.

---

## 11. Location / Ward Consistency — Partially OPEN

Per `docs/audits/04-consolidated-implementation-plan.md`'s PR20 Boundary,
"Legacy BME names and Ward values belong to transaction history and are
handled by PR21, not this Equipment Master import" — PR20 must not import
transaction/ward history. However, if the legacy Equipment Master source
itself carries a "current location" or "current ward" field *at the
equipment level* (distinct from transaction history, which is out of
scope), that would interact with `status`: an equipment record imported as
`ISSUED_TO_WARD` implies an active issue, which this system currently
represents only via an active `BorrowTransaction`, not an equipment-level
location column being set independently. The current domain has no
equipment-level "current ward" field at all (`current_location_id` exists
but is a different concept — see `app/models/equipment.py`).

**Recommendation for Owner consideration**: PR20 should likely never
import equipment directly into `ISSUED_TO_WARD` (since doing so without a
corresponding transaction would violate the invariant that
`ISSUED_TO_WARD` equipment always has an active transaction, and creating
a synthetic transaction is explicitly PR21's scope, not PR20's) — any
legacy status that appears to represent "currently issued" should map to
a blocking `ERROR` finding under §10's classification rule, deferred to
whatever PR21 or a later reconciliation PR designs for that case, rather
than PR20 inventing a workaround. This is a recommendation, not a
decision; it becomes concrete only once OD-1 reveals whether this
situation is even present in the real source data.

---

## 12. Validation Finding Taxonomy — Structure resolved, exact codes gated
by OD-1

PR20 findings are `ValidationFinding` rows exactly as PR19A already
defines them (`row_number, field, error_code, message, severity ∈
{error, warning}`, §3.1) — no schema change. Per PR19A design §12/§13,
`invalid_rows`/`warning_rows` are independent `COUNT(DISTINCT row_number)`
projections; `valid_rows = total_rows - invalid_rows` only.

**Naming convention** (resolvable now): error codes should follow this
codebase's existing convention of a short, stable, machine-readable
identifier documented in `docs/api/ERROR_CODES.md` if that file's own
existing convention requires it (confirm at implementation time against
that file's current structure) — e.g. `EQUIPMENT_MASTER_BCM_MISSING`,
`EQUIPMENT_MASTER_BCM_DUPLICATE_IN_SOURCE`, `EQUIPMENT_MASTER_IDENTITY_
CONFLICT`, `EQUIPMENT_MASTER_STATUS_UNMAPPABLE` — illustrative examples
only, not a final list.

**Categories resolvable now** (structure, not exact codes): missing
required identifier(s); malformed identifier (fails canonicalization);
duplicate identifier within the same workbook; identifier collides with
an existing record in a way OD-2/OD-3 classifies as a conflict;
unmappable legacy status (§10); field length/type violations (once OD-1
defines the fields); create attempted where create is not authorized (if
OD-2 resolves to update-only, this becomes the correct rejection path,
mirroring PR12-H1's precedent exactly).

**What remains OPEN**: the exact, final error-code list and their
ERROR-vs-WARNING classification per code — both require OD-1's field list
and OD-2/OD-3's identity/create policy to be meaningful.

---

## 13. Duplicate Policy — Structure resolved, resolution gated by OD-3

Distinguishing the six categories the task requires:

- **(A) Duplicate rows within the same workbook** (byte-identical row
  content repeated): a parsing-level fact (§7), not itself a conflict —
  becomes a conflict only via (B)/(C) below if the repeated row's
  identifiers collide.
- **(B) Duplicate BCM within the source**: two distinct rows share a
  canonicalized BCM value. Resolvable structurally via
  `preload_business_context`'s bulk map (§6.3) without needing OD-1 — but
  whether this is a blocking `ERROR` or an accepted "last row wins"
  behavior is OD-3's concern.
- **(C) Duplicate Item No within the source**: same as (B) for Item No.
- **(D) Duplicate against the existing database**: resolved via
  `get_by_bcm_codes`/`get_by_item_nos` (§4.3) — this *is* the matching
  step, not a separate duplicate-detection step; its outcome (create vs.
  update vs. reject) is OD-2/OD-3.
- **(E) Repeated import of an identical source**: already solved by
  PR19A's `source_fingerprint`/`options_fingerprint`/idempotency-key
  mechanism (§3.1, §3.2) — a byte-identical re-upload with the same
  `idempotency_key` replays the existing session rather than creating a
  new one. PR20 adds nothing here.
- **(F) Same logical equipment reappearing with changed data in a later,
  separate import session**: this is exactly the create-vs-update
  question (OD-2) applied across sessions rather than within one — no
  additional mechanism beyond OD-2's resolution is needed.

**What remains OPEN**: whether (B)/(C) block the whole row, block only the
duplicate rows, or are accepted with a warning — OD-3.

---

## 14. Dry-Run Contract

Reuses PR19A's `DryRunPlan(summary: dict)` shape and read-only enforcement
(§3.4, §6.3) directly — no new dry-run mechanism. The summary must report
(once OD-1/OD-2/OD-3 make these countable): `rows_considered`,
`creates_planned` (0 if OD-2 resolves to update-only),
`updates_planned` (0 if OD-2 resolves to create-only), `skipped_rows`
(rows already correctly reflected, if that concept applies once OD-2
resolves), `warnings_count`, `blocking_conflicts_count`. This mirrors the
structure PR19B's frontend already expects from `ImportResultSummary`-
adjacent presentation work (nullable counts, never fabricated zeros) —
PR20's backend summary shape should stay compatible with what PR19B
already renders where reasonable, without PR20 being obligated to match it
field-for-field (PR19B's own docs state its mock fixtures are
presentation-only and do not bind PR20's real contract).

---

## 15. Execution and Atomicity Contract

`adapter.execute(rw_db)` runs inside the caller's existing read-write
transaction (TX1, §3.5) and must never call `commit()`/`rollback()` itself
— exactly as PR19A's contract already requires of every adapter. This
gives PR20 an inherent **all-or-nothing guarantee per execute attempt**:
if `execute()` raises for any reason partway through applying rows, TX1
rolls back in full (no partially-imported Equipment Master row becomes
visible), and the existing TX1/TX2 crash-recovery split (§3.3) handles the
failure-publication path exactly as it already does for every other
adapter phase. **PR20 does not need, and must not invent, a weaker or
per-row-commit guarantee** — the framework's existing boundary already
provides row-set atomicity for free, provided PR20's `execute()`
implementation performs all of its writes (creates/updates) via the same
`rw_db` session without any intermediate commit.

One consequence worth flagging for implementation: `MAX_IMPORT_ROWS=5000`
(§7) bounds a single execute transaction to at most 5000 Equipment
writes — well within normal PostgreSQL transaction-size tolerances, so no
chunking/batching design is needed.

---

## 16. Concurrency Strategy

PR19A already guarantees single-winner admission at the *job* level
(`admit_phase_job`'s CAS UPDATE, §3.3) — two concurrent `execute` calls on
the same session can never both proceed. What PR19A does **not** guarantee
is protection against a **different** session (or manual `POST
/equipment` creation) racing against PR20's own execute for the *same*
BCM/Item No. Analysis:

- **Two import sessions with overlapping BCM/Item No**: each session's own
  `validate`/`dry_run` snapshot is taken independently; if both reach
  `execute` for overlapping identifiers, the database's existing unique
  constraints on `bcm_code`/`item_no`/`serial_number` (§4.1) are the
  final integrity boundary — a second `execute` attempting to create a
  now-duplicate identifier will hit an `IntegrityError`. PR20's
  `execute()` must catch this and surface it as an `ImportExecutionFailedError`
  (or an equivalent bounded failure) rather than a raw exception leaking
  to the client — consistent with PR19A's "genuine server error" treatment
  of execute failures (§3.5). This is a rare, timing-dependent race
  (two full-Equipment-Master-import sessions running concurrently is not
  an expected operational pattern) and does not need a bespoke
  distributed-lock mechanism beyond the database's own constraint
  enforcement.
- **Manual Equipment creation concurrent with import**: same analysis —
  the database's existing unique constraints are the authoritative
  boundary; PR20 does not need application-level locking beyond what
  already protects `POST /equipment` today.
- **Retry after timeout / stale worker after lease loss**: fully handled
  by PR19A's existing recovery contract (§3.3) — PR20 adds nothing here.
- **TOCTOU between validate/dry-run and execute**: since PR19A does not
  hold row locks between phases (by design — validate/dry-run/execute are
  separate transactions, potentially separated by real wall-clock time),
  a record matched during validation could theoretically be modified or
  deleted by unrelated activity before execute runs. This is the same
  class of risk PR12's own commit phase already accepts (its own design
  does not lock rows between preview and commit either) — PR20 inherits
  this accepted risk rather than introducing new locking machinery beyond
  what the unique constraints already provide.

---

## 17. Authorization

Unchanged from PR19A: every `/import-sessions/*` endpoint remains gated by
`require_roles(*ADMINISTRATOR_ONLY_ROLES)` (§3.2). Any new
byte-ingestion endpoint (§6.2) must use the identical dependency — PR20
introduces no new role, no capability-based relaxation, and no
frontend-only authorization check (backend remains authoritative, per
`docs/BUSINESS_RULES.md`). Who may create a session, register/upload a
source, validate, dry-run, execute, or view results/history is identical:
Administrator only, exactly as it already is for the entire
`/import-sessions/*` surface today.

---

## 18. Audit Strategy

Reuses the existing generic audit-event framework (`record_audit_event`,
per this codebase's PR3-era central audit module) rather than duplicating
PR19A's own internal lease/fence audit hooks (`write_fence_lost_audit`,
§3.3, already reused unmodified). A new audit entry should be recorded
once per successful `execute` completion (mirroring PR12's "exactly one
`audit_logs` entry per commit batch" precedent), carrying: the acting
Administrator's user id, the `ImportSession` id, the `ImportSource`'s
`checksum`/`source_fingerprint` (not the raw filename, which is subject to
retention redaction, §3.6), and the counts already computed by the dry-run/
execute summary (§14) — created/updated/skipped counts, never raw legacy
row content (no PII beyond what the audit framework already permits for
existing equipment audit events). This does not require a new audit
entity type if the existing framework's generic `entity`/`entity_id`
fields (as PR12 already uses, `entity=EQUIPMENT, entity_id=None` for a
batch action) are sufficient — confirm the exact call site's field
requirements at implementation time against the current audit framework
code, which this design does not modify.

---

## 19. Rollback Philosophy

No "delete all imported equipment" feature is in scope for PR20 (matches
the task's explicit instruction). Two rollback mechanisms exist, and no
third is added:

- **Transactional failure rollback during execute** (§15): already
  provided by TX1's all-or-nothing boundary — an execute attempt that
  fails partway through leaves zero trace in the Equipment table.
- **Explicit corrective workflow after a committed import**: out of scope
  for PR20. If a completed import later turns out to have imported
  incorrect data, correcting it uses the *existing* `PATCH /equipment/{id}`
  update path (or, for records that should never have been created, a
  manual soft-delete via the existing `DELETE /equipment/{id}`) — the same
  tools an operator already has for any other equipment-data mistake.
  Equipment created by PR20 may already be referenced by later
  transactions by the time a correction is needed, which is precisely why
  a bulk "undo the import" feature is unsafe and explicitly out of scope
  here, consistent with the task's own instruction. Any future dedicated
  bulk-correction feature requires its own separate design.

---

## 20. Frontend Integration Strategy

PR19B already ships a complete, mock-backed Equipment Master workflow-review
skeleton (session list/create/validation-summary/dry-run/result screens,
Thai-first, mobile-first, `MockImportClient`-backed). The minimum PR20
frontend integration is:

1. Replace `MockImportClient`'s Equipment Master code path with a real
   `LegacyImportClient` implementation calling the actual
   `/import-sessions/*` endpoints (§3.2) plus whatever byte-ingestion
   endpoint §6.2 resolves to for file selection — the existing
   `legacyImportClient.ts` seam (already isolated behind one named
   interface per PR19B's own Exception Record mitigations) is the
   intended swap point; no UI redesign.
2. Update `frontend/src/types/legacyImport.ts` only insofar as PR20's real
   API contract differs from PR19B's already-reconciled mock shapes
   (`ImportSessionOut`/`ValidationFindingOut` field names, §6.1 of the
   prior PR19B work) — expected to be a small delta given PR19B was
   already reconciled against PR19A's real contracts.
3. Preserve every UX principle PR19B already established: Thai-first,
   mobile-first, QR-first, minimal typing, large touch targets. This
   design does not redesign the frontend.
4. Receive-History and Issue-History mock paths (PR21's future scope)
   remain mocked; only the Equipment Master path is wired to real data by
   PR20.

This is a backend/domain-adapter slice primarily (§24); the frontend
change is a real-client wiring exercise, not new UI design.

---

## 21. Security and Resource Bounds

- **Never execute workbook formulas or macros** — read cell *values* only
  (openpyxl's default non-formula-evaluating read mode); `.xlsx` macro
  content (`.xlsm` in particular) must be rejected outright by content-type/
  structure check, not merely by file-extension trust.
- **Never trust the uploaded filename or declared MIME type alone** —
  validate actual `.xlsx` zip/OOXML structure before parsing, exactly as
  PR12 already does.
- **Reuse PR12's exact zip-bomb/decompression bounds** (§7) rather than
  re-deriving new constants — `MAX_ZIP_ENTRIES`,
  `MAX_ZIP_ENTRY_UNCOMPRESSED_BYTES`, `MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES`,
  `MAX_ZIP_COMPRESSION_RATIO`.
- **Parser CPU/memory bounds**: parsing runs via `asyncio.to_thread`
  (matching PR19A2's off-event-loop discipline for `adapter.parse()`,
  §3 of the PR19A design), bounded by `MAX_IMPORT_ROWS`/
  `MAX_HEADER_COLUMNS`/`MAX_WORKSHEET_COUNT` (§7).
- **External links**: reject or ignore workbook external-reference cells
  (openpyxl does not resolve these by default; confirm this remains true
  at implementation time rather than assuming).
- **Oversized strings**: every persisted string field (once OD-1 defines
  the field set) must have an explicit bounded length, enforced at both
  the Pydantic/validation layer and (where the field lands on an existing
  `Equipment` column) the database's own existing column-length
  constraint.
- **Temporary file / in-memory buffer cleanup**: if the implementation
  writes any intermediate temp file during parsing, it must be cleaned up
  in a `finally` block (matches the PR19A design doc's own explicit
  forward-reference requirement, §3.7).
- **Formula-injection in any later export/logging path**: any legacy cell
  value that is later rendered in a CSV/Excel export or audit log must
  pass through this codebase's existing formula-injection-protection
  write helper (the same `_write_cell`-style discipline PR18E's Excel
  exporter already established) if PR20's own audit/error messages ever
  echo raw legacy cell content — confirm at implementation time whether
  any PR20 surface actually does this (findings currently propose bounded,
  generic messages, §12, which may make this moot).

---

## 22. Testing Strategy

**Unit**: parsing (header detection, blank-row skip, numeric-as-identifier
handling, malformed-workbook rejection — all resolvable without OD-1);
canonicalization reuse (BCM/Item No via `app.services.identifiers`, no new
canonicalization logic to test); duplicate detection within a workbook
(§13 B/C, structurally testable with synthetic column names even before
OD-1 resolves the real ones — implementation PRs may need to use
placeholder field names until OD-1 lands, or may need to be sequenced
after OD-1 resolves, per §24); lifecycle-status classification (§10,
gated by OD-1); identifier-conflict detection (§9 OD-3, once resolved).

**Integration (real PostgreSQL)**: existing-Equipment conflict scenarios
(unique-constraint collision surfaced correctly, §16); concurrent-session
identity conflicts (two sessions racing on overlapping BCM, §16);
dry-run read-only enforcement specifically for the new adapter (a
dedicated test proving `EquipmentMasterAdapter.plan_dry_run` cannot write,
mirroring PR19A3's own write-attempting-adapter test pattern); execute
atomicity (a failure partway through a multi-row execute leaves zero
Equipment rows created, §15); idempotency (a `completed` session replay
returns unchanged, inherited from PR19A, re-verified for this adapter);
lease/fencing behavior specifically exercised through the real adapter
(not just the existing generic `FakeAdapter`-based PR19A tests).

**Migration**: only if §6.2's byte-storage proposal is adopted — a new
migration for `import_source_blobs` (or equivalent), following this
repository's established `_verify_schema_convergence()` fail-closed
discipline (§3.1) and upgrade/downgrade/re-upgrade PostgreSQL test pattern
already used for every prior migration in this codebase.

**Frontend**: real-client integration tests for the Equipment Master path
(loading/error/result states against a real or realistically-mocked
backend contract, not the PR19B `MockImportClient`); explicit regression
test proving Receive/Issue History mock placeholders are unaffected by
this change (PR21's scope remains untouched).

**Security**: zip-bomb/decompression-bound tests reusing PR12's existing
test patterns against the new endpoint (§6.2); macro/formula-content
rejection test; oversized-file rejection test.

Do not weaken existing CI — every existing PR19A/PR12/Equipment test suite
must remain green; PR20 adds tests, it does not modify or relax any
existing one.

---

## 23. Non-Goals

Per the task's explicit scope guard and this design's own findings, PR20
implementation PRs must **not**:

- Guess or invent the legacy Equipment Master column layout (§8, blocked
  on OD-1).
- Decide create-vs-update policy unilaterally (blocked on OD-2).
- Decide BCM/Item No identity-conflict resolution unilaterally (blocked
  on OD-3).
- Introduce a fifth equipment lifecycle state.
- Modify PR12's existing `/import/*` Inventory Import feature.
- Modify PR19A's session/job/lease/fencing/recovery/retention mechanisms.
- Build a bulk "undo the import" / mass-delete feature (§19).
- Redesign the existing hospital QR/Item No resolution behavior (ADR-004).
- Import Receive/Issue transaction history or Ward values (PR21's scope,
  per the Roadmap Boundary already quoted in §2/§11).
- Weaken the existing Administrator-only RBAC gate.
- Begin any implementation PR before OD-1/OD-2/OD-3 are resolved by the
  Repository Owner, for the specific areas each gates (§9). Architecture
  work that is *not* gated by an Owner Decision — e.g. the byte-ingestion
  endpoint's shape (§6.2), reusable across whatever field mapping OD-1
  eventually resolves — may proceed independently once this design itself
  is reviewed and approved, at the Owner's discretion, since it is a
  technical rather than business-policy question.

---

## 24. Proposed Implementation Slicing

The task's suggested starting hypothesis (PR20A parser/validation, PR20B
dry-run/execution, PR20C frontend wiring, PR20D governance sync) is
directionally correct but must be adjusted for the file-ingestion gap
(§6.2), which is not covered by that hypothesis's PR20A framing and is a
prerequisite for *any* real Equipment Master data reaching the parser.
Revised proposal:

- **PR20A — Source ingestion**: the byte-upload endpoint, checksum
  computation, and byte-storage schema (§6.2). Independently testable
  (security bounds, checksum correctness) without any Equipment-specific
  logic and without depending on OD-1/OD-2/OD-3 at all — this slice can
  begin once this design document itself is approved, since it resolves a
  technical gap, not a business-policy one.
- **PR20B — Equipment Master parser, normalization, and validation
  adapter**: `EquipmentMasterAdapter.parse`/`preload_business_context`/
  `validate_business_rules`. **Blocked on OD-1/OD-2/OD-3.**
- **PR20C — Dry-run and execution integration**: `plan_dry_run`/`execute`,
  wired to the same matching/policy core as PR20B. **Blocked on
  OD-1/OD-2/OD-3** (inherits PR20B's blockers).
- **PR20D — Frontend real-API wiring**: replaces the Equipment Master
  `MockImportClient` path only (§20). Can begin once PR20A+PR20B+PR20C's
  API contract is stable enough to integrate against (likely sequenced
  after PR20C, or in parallel against a contract-frozen API surface if the
  team prefers — an implementation-sequencing choice, not a design
  question).
- **PR20E — Governance sync**: records PR20's actual merged scope,
  following this repository's established post-merge documentation-sync
  pattern (as this document's own predecessor, the PR19B governance sync,
  did) — not performed by this Design PR itself (§25).

Each slice remains independently testable and does not leave an unsafe
production endpoint exposed: PR20A alone introduces no Equipment-domain
write path at all (it only stores bytes); PR20B alone introduces no
`execute` capability (dry-run/execute remain `422`/`501`
`IMPORT_ADAPTER_NOT_REGISTERED` — actually, once PR20B registers the
adapter, `validate` becomes live but `plan_dry_run`/`execute` remain
`NotImplementedError` per the base `ImportAdapter` contract until PR20C
lands, matching PR19A2's own precedent of shipping `validate` safely ahead
of `dry_run`/`execute`).

---

## 25. Governance Updates In This Design PR

This Design PR records only that PR20's design has started and opens the
three Owner Decisions above (§9) — following the same minimal-update
convention PR19A's own design PR used (recording the design as approved/
pending, not marking the Roadmap item implemented). No broad governance
sync (ROADMAP.md/ROADMAP_STATUS.md/DECISION_LOG.md/knowledge/* rewrite) is
performed here; that follows the established pattern only after actual
implementation slices merge (§24, PR20E), mirroring how PR19A's own design
doc (GitHub PR #83) did not itself update the full governance surface —
the post-implementation governance-sync PRs (#87, #88) did.

---

## 26. Scope Guard For This PR

This PR (the Design PR itself) touches only:

- `docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md` (this file, new).

No `backend/**`, `frontend/**`, `migrations/**`, `tests/**`, `.github/**`,
or other `docs/**`/`knowledge/**` file is modified by this PR. No Roadmap
item is marked implemented. PR20 implementation does not begin in this PR
or any PR that follows it without independent review of this design and
Repository Owner resolution of §9's Owner Decisions for the areas each
gates.

---

## 27. Acceptance Criteria For This Design Document

- [x] Read and inspected the actual merged PR19A runtime, not Roadmap text
      alone (§2, §3).
- [x] Read and inspected the actual current Equipment domain runtime,
      including the pre-existing, unrelated PR12 Inventory Import feature
      (§2, §4, §5).
- [x] Searched the repository for real Equipment Master source-schema
      evidence and reported the exhaustive, explicit result (§7, §8, OD-1).
- [x] Did not invent or guess a field mapping (§8).
- [x] Did not decide create-vs-update policy unilaterally (OD-2).
- [x] Did not decide BCM/Item No identity-conflict policy unilaterally
      (OD-3).
- [x] Did not introduce a fifth equipment lifecycle state (§10).
- [x] Identified the file-ingestion architecture gap PR19A left open and
      proposed a concrete, independently-reviewable solution for it
      (§6.2), distinguished from the business-policy Owner Decisions.
- [x] Proposed an implementation slicing adjusted for that gap (§24).
- [x] Defined testing strategy, security/resource bounds, authorization,
      audit, rollback philosophy, and frontend integration strategy at an
      implementation-grade level for everything not gated by an Owner
      Decision (§14–§22).
- [x] Explicitly enumerated non-goals and STOP conditions (§9, §23).
- [x] No backend, frontend, migration, or test file modified by this PR
      (§26).
