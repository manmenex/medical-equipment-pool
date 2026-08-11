# Roadmap PR20 — Equipment Master Import: Design Specification

**Status:** Design only. Not implemented. This document defines the
architecture, contract, and open questions for PR20; it does **not**
authorize implementation of the parts marked OPEN below. Per
`docs/ENGINEERING_WORKFLOW.md` §7, "implementation depending on an open
Owner Decision MUST NOT begin" — three Owner Decisions are opened by this
document (§9) and implementation of the areas they gate must wait for
Repository Owner resolution.
**Fix round 1** (independent review 4903718985, REQUEST CHANGES on head
`41a9430637d772ed355708a76e1a46baf4366af2`) resolved five technical design
gaps this revision closes without touching OD-1/OD-2/OD-3: the adapter
needed an explicit, immutable invocation-context contract rather than
reconstructing session/source identity itself (§6.4); source
metadata+blob persistence needed an explicit transaction-ownership
contract, since the existing CRUD layer commits internally (§6.2);
PR20A's slice boundary needed correction once that transaction and
context work turned out to be real, non-Owner-Decision-gated prerequisites
(§24); the dry-run summary needed an explicit persistence/API answer,
since `DryRunPlan.summary` is otherwise discarded by the merged framework
(§14); and update-mode execution needed an explicit optimistic-concurrency
contract, since unique constraints alone do not protect against lost
updates (§15.1). Two non-blocking corrections were also made: numeric
Excel identifier cells do not actually preserve leading zeros (§7), and
the `register_adapter()` pseudocode call in §6.3 previously did not match
the real merged signature (§6.3).
**Fix round 2** (independent review 4903888875, REQUEST CHANGES on head
`2c31a30a38b69e32ff21984420c0134b181dd975`) established one coherent,
end-to-end frozen-artifact chain — registered immutable source →
validation snapshot → **persisted** dry-run plan → user confirmation of
that exact plan → execution of that same plan → fenced atomic result —
and closed six further gaps without touching OD-1/OD-2/OD-3: validation
must read real, checksum-verified source content, never `parse(None)`,
via a new `ImportSourceReader` boundary (§6.5, formerly H1R); source
registration must be one authoritative, server-checksummed operation with
no metadata-only path for this dataset type, with an explicit
storage/database failure-and-retry walkthrough (§6.2, formerly H2R);
source-blob retention must integrate into PR19A's existing 180-day policy
rather than invent a second one, which in turn required correcting
PR20A's scope again (§6.6, §24, formerly H3R); the dry-run summary the
user confirms must be a **persisted, immutable artifact** identified by
its own ID, not a live recomputation, requiring two new PR20-owned tables
and two new, additive, default-no-op `ImportAdapter` hooks (§14, formerly
H4R); the Equipment concurrency token must be **captured during dry-run
and persisted in that same artifact**, never refreshed at execute time
(§15.1, formerly H5R); and every remaining `register_adapter()` call site
was swept, not just the one previously cited (§6.1, formerly L1R).
**Fix round 3** (independent review on head
`7f392b19f1273664ba3ca17276a3d9f2095e4673`, REQUEST CHANGES; CI 6/6 green
on that head) confirmed round 2's H3R/H5R/N1/L1R resolutions and closed
seven further blocking gaps in how the frozen-artifact chain actually
integrates with the merged framework, without touching OD-1/OD-2/OD-3:
`plan_dry_run` had no way to obtain the same verified source content
`parse()` receives, since its signature carries no `raw_input` — closed by
threading `VerifiedSourceContent` through the adapter-invocation context
rather than the ABC (§6.4, §6.5, formerly H1R2); "metadata-only
registration is a client error" was asserted but never actually enforced
anywhere — closed by specifying the exact guard added to the existing
`POST /{id}/source` handler, with a stable error code and a
zero-database-write proof (§6.2, formerly H2R2); the persisted plan
header's two job-identity columns had no way to be populated by the
adapter — closed by threading both exact IDs through the same invocation
context (§6.4, formerly H4R2); the execution input contract wrongly
described pre-admission checks as living inside `adapter.execute()`,
which only ever runs post-admission — closed by splitting an explicit
framework-owned pre-admission validation layer from a locked
post-admission re-check, and by explicitly defining the terminal-failure
lifecycle (a post-admission conflict fails the session permanently; a
plan-status check failure does not) (§14.4, §15.1, formerly H6); making
`dry_run_plan_id` unconditionally required would have broken the shared
generic `execute` route for every other dataset type — closed by making
the field optional at the route and required only for this adapter
(§14.4, formerly H7); the two new persisted-plan tables lacked the
physical integrity constraints an execution-driving artifact requires —
closed with composite ownership FKs, partial/row uniqueness, and
nullability CHECKs (§14.2, formerly H8); and the two new tables' own
JSONB content had no retention story, despite carrying the same category
of content the existing blob/session redaction already protects — closed
by extending the same claimed/fenced retention transaction a second time
(§14.9, formerly H9). One non-blocking item was also resolved: the
`updated_at`-vs-`version` concurrency-token choice is now finalized in
this design as `updated_at`, not deferred to the implementation PR
(§15.1, formerly M2).
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
| Adapter call sites (fix round 1) | `backend/app/services/import_execution_service.py::run_dry_run`/`run_execute`, `import_validation_service.py::run_validation` | Confirmed by reading the actual invocation code: `adapter.plan_dry_run(ro_db)`/`adapter.execute(db)` are called with **only** the db session — no session/source identity parameter exists — requiring the `AdapterInvocationContext` mechanism (§6.4). |
| CRUD transaction behavior (fix round 1) | `backend/app/crud/import_session.py::register_or_correct_source`/`cancel_session` | Confirmed by reading the actual code: both call `await db.commit()` internally, meaning a naive "register source, then separately add a blob row" sequence is **not** atomic — requiring the non-committing CRUD variant and explicit transaction-ownership contract (§6.2). |
| Equipment concurrency token (fix round 1) | `backend/app/models/equipment.py`, `app/models/mixins.py::TimestampMixin` | Confirmed by reading the actual model: `Equipment` has no dedicated `version` counter, but does have `updated_at` (`onupdate=func.now()`, server-computed) — usable as an optimistic-concurrency CAS token without a schema change (§15.1). |

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
and calls `register_adapter(EquipmentMasterAdapter())` — the real,
single-argument merged signature (§6.3 — this exact call-site sweep is
the L1R fix-round-2 correction; every occurrence of `register_adapter` in
this document now uses this form, verified by search, not just the one
previously cited) — at application startup (module import time, alongside
existing router registration in `app/main.py` or an equivalent startup
hook — exact wiring point is an implementation detail for the
implementation PR, not a design question). `dataset_type="equipment_master"`
becomes the value clients must pass to `POST /import-sessions
{"dataset_type": "equipment_master"}`. This is the only change to
session-creation behavior; no new endpoint is needed for this step.

### 6.2 File ingestion — one authoritative, server-checksummed registration operation

**This is a genuine, non-Equipment-specific architecture problem PR20 must
solve, independent of §9's business-policy Owner Decisions.** The merged
`POST /{session_id}/source` only accepts `{checksum, byte_size,
content_type?, filename?, source_version?}` — never raw bytes — and
`ImportAdapter.parse(raw_input)` is always invoked with `raw_input=None`
today. **Fix-round-2 correction (H2R): the prior revision left this
endpoint reachable as an alternative, metadata-only path for PR20's own
`dataset_type`, which would allow `import_sources` metadata to diverge
from actual durable bytes. This design now removes that possibility
structurally, not merely by convention.**

**There is exactly one way to register a source for
`dataset_type="equipment_master"`, and it is not the existing metadata-only
endpoint:**

- `POST /import-sessions/{session_id}/source` (the existing PR19A
  endpoint) **remains available, behaviorally unchanged, for every
  `dataset_type` whose adapter resolves its own checksum/bytes entirely
  out-of-band** (a hypothetical future adapter that never needs this
  design's byte storage at all). **Fix-round-3 correction (H2R2): the
  prior revision claimed both "it is not modified" and "calling it is a
  client error" for `dataset_type="equipment_master"` — those cannot both
  be true, since the merged handler has no per-dataset-type storage-mode
  rule today and would otherwise happily register metadata with no bound
  blob behind it, silently, before ever reaching `EquipmentMasterAdapter`.
  Falling through to a later missing-blob failure at read time (§6.5) is
  not the same as rejecting at the registration boundary, and it leaves an
  invalid, metadata-only source durably registered in the meantime. This
  design now specifies the actual code change required, rather than
  asserting the endpoint is untouched:**
  - The existing handler gains one small, additive guard as its own first
    step, **before** calling `register_or_correct_source` or any other
    CRUD function: load the session (already required to resolve
    `session_id` today), read its `dataset_type`, and if it equals
    `"equipment_master"`, return **`409 Conflict`** with a stable,
    catalog-worthy error code (`IMPORT_SOURCE_REGISTRATION_METHOD_NOT_
    ALLOWED`, following this codebase's existing structured-error-code
    convention) **without calling any CRUD function and without any
    database write** — the guard is a pure in-memory check on the
    already-loaded session's `dataset_type`, so no write is reachable
    before it returns.
  - Every other `dataset_type` reaches the existing handler body exactly
    as before the guard — this is a narrowly-scoped, additive
    modification, not a rewrite, and preserves the endpoint's full
    existing behavior for every value the guard doesn't match. (§23's
    non-goal against modifying PR19A's session/job/lease/fencing/
    recovery/retention *mechanisms* is unaffected — this is a guard on a
    source-registration *endpoint*, a different surface, and is now
    stated as an explicit, narrow exception the same way §6.6's retention
    extension already is.)
  - The new upload endpoint below performs the equivalent registration
    step itself, atomically with the blob write, and is the only path
    that can ever leave `dataset_type="equipment_master"` in a
    `registered` state.
  - **Required test coverage (§22)**: an endpoint-level test proving the
    guard rejects `equipment_master` with `409`/the stable error code and
    performs zero database writes (asserted via no new/changed
    `import_sources` row); a companion test proving every other
    `dataset_type` is completely unaffected by the guard and reaches the
    existing handler body unchanged.
- **The one authoritative path**: `POST
  /import-sessions/{session_id}/source/upload`, Administrator-only,
  `multipart/form-data`, bounded by the same discipline PR12 already
  established (`MAX_UPLOAD_BYTES`, zip-entry-count/size/ratio bounds,
  worksheet-count/header-column bounds — reuse PR12's constants and
  pattern rather than re-deriving them). **The client is never
  authoritative for checksum, byte length, or storage key.** If a client
  supplies a checksum (e.g. for its own pre-upload integrity check), the
  server treats it as optional, advisory input to compare against its own
  independently server-computed checksum — a mismatch is a client error
  (the upload is rejected before any registration happens), never a value
  the server trusts and persists as-is. The server performs, as one
  logical operation:
  1. receive and bound-check the uploaded bytes (size/structure, §21) —
     no DB writes yet;
  2. compute the checksum and byte length **server-side**, from the
     actual received bytes;
  3. persist the bytes durably and finalize the source's metadata —
     together, as one physical database transaction (the mechanics are in
     the transaction contract below);
  4. only a source that completed step 3 is ever considered
     `registered`/usable — a source can never reach a state where its
     metadata claims a checksum/byte length that the actual durable blob
     does not match, because both facts are written together or not at
     all.

**Byte storage location**: the same PostgreSQL database — a new,
narrowly-scoped table, `import_source_blobs (import_source_id UUID PK, FK
import_sources.id ON DELETE RESTRICT, content BYTEA NOT NULL)`, 1:1 with
`import_sources` — bounded by the same `MAX_UPLOAD_BYTES` ceiling as PR12
(10 MiB). This choice is **deliberate and load-bearing for the atomicity
contract below**: because the blob lives in the same PostgreSQL database
as `import_sources`, a genuine, single-database-transaction ACID guarantee
is achievable for free, without a saga or two-phase-commit protocol. A
dedicated object-storage integration is not justified for V1 at this size
ceiling, and none exists in this codebase to build on; if a future
revision moves byte storage to an external system, the collapsed
single-transaction guarantee below no longer applies and must be
redesigned around a genuine durable-write-then-orphan-cleanup saga instead
(not needed for the V1 architecture proposed here, and this document does
not pretend otherwise).

**Transaction-ownership and failure/retry contract** (resolves the
finding that the existing CRUD layer commits internally and therefore
cannot be composed naively, and walks through every failure/retry
scenario the review requires rather than asserting atomicity without
proof):

`app.crud.import_session.register_or_correct_source` and
`cancel_session` both call `await db.commit()` internally (confirmed by
reading the actual merged code, not assumed). Calling that function and
then separately adding a blob row afterward would **not** be atomic — the
metadata commit would already have closed the transaction before the blob
write ever happened. The fix is a new, additive, non-committing CRUD
variant, so a single transaction can finalize both writes together:

1. **Who begins the transaction:** implicit — this codebase's existing
   convention (every endpoint receives one request-scoped `AsyncSession`
   via dependency injection; no manual `BEGIN`).
2. **Ordering:** (a) validate the uploaded bytes' structural/security
   bounds in memory, no DB writes yet (§21); (b) compute the checksum and
   byte_size server-side from the actual received bytes (compare against
   an optional client-supplied checksum here, rejecting on mismatch
   *before* any DB write, per the client-not-authoritative rule above);
   (c) call a new, **additive, non-committing** CRUD entry point —
   `register_or_correct_source_pending(db, ..., commit=False)` (or an
   equivalent keyword-argable variant of the existing function that
   preserves the current committing behavior as the default for every
   existing caller, so `POST /{id}/source` is unaffected) — which performs
   the identical INSERT/UPDATE/`await db.flush()` logic the existing
   function already has, but leaves `commit()` to the caller; (d)
   `db.add()` the new `import_source_blobs` row, referencing the
   now-**flushed**-but-not-yet-committed `import_source.id` (visible
   within the same open transaction, so the FK is satisfiable) — using an
   upsert/replace-if-exists write (matching `register_or_correct_source`'s
   own "register-or-correct" idempotent semantics, so a client retry after
   a lost response does not create two blob rows); (e) a single `await
   db.commit()` at the very end, committing the source-metadata row and
   the blob row together as one physical PostgreSQL transaction.
3. **Who commits:** the new upload endpoint itself, once, after step
   2(d) — never the CRUD helper (via the new non-committing variant).
4. **Who rolls back:** this codebase's existing exception-handling
   convention (whatever already triggers `db.rollback()` on an unhandled
   exception for every other endpoint — confirmed at implementation time
   against the actual mechanism, not invented here); since both the source
   row and the blob row live in the same uncommitted transaction, a
   rollback at any point before step 2(e) discards both together — there
   is nothing to orphan.
5. **Explicit failure/retry matrix, as requested — every listed scenario
   walked through, not asserted away:**
   - *Storage succeeds, DB finalize fails*: not a reachable state under
     this architecture — "storage" and "DB finalize" are the same write
     (step 2(d) is a row in the same database as step 2(c)'s metadata
     row), inside the same uncommitted transaction. There is no window
     where the blob "succeeded" independently of the metadata; both are
     pending together until the single commit in step 2(e).
   - *DB pre-registration succeeds, storage fails*: same answer — there
     is no separate "DB pre-registration" step that could commit ahead of
     the blob write; step 2(c)'s flush is not a commit, and nothing is
     durable/visible to any other transaction until step 2(e).
   - *Retry of same request (identical bytes)*: handled by
     `register_or_correct_source`'s existing "register-or-correct"
     idempotent semantics, extended to the blob row via the upsert write
     in step 2(d) — a second identical upload updates in place rather
     than creating a duplicate row.
   - *Retry of same request (conflicting bytes)*: the same "correct"
     semantics apply — the source is not yet `frozen` (freezing happens
     only at validate-admission time, §3.1, unchanged from PR19A), so a
     corrected re-upload before freezing legitimately replaces the prior
     checksum/blob together, atomically, in the same transaction shape as
     step 2. Once a source is `frozen`, `register_or_correct_source`'s
     existing merged behavior (unchanged by this design) governs whether
     a further correction is even accepted — this design does not alter
     that already-established freeze semantics.
   - *Orphan object cleanup*: **not needed for this V1 architecture.**
     Because both writes share one physical transaction, no state exists
     where a blob persists without its owning source row, or vice versa.
     This is explicitly a consequence of choosing same-database BYTEA
     storage (above) rather than external object storage; it is not a
     general property of file-upload systems, and this document does not
     claim it would hold under a different storage choice.
   - *Process crash at every boundary*: crashing before step 2(e)'s commit
     leaves an uncommitted transaction that PostgreSQL itself discards on
     connection loss — neither row exists afterward, nothing to clean up.
     Crashing *after* step 2(e)'s commit succeeds is indistinguishable
     from a normal successful registration to any later observer; the
     client's own retry (if it didn't see the response) is handled by the
     idempotent "register-or-correct" semantics above.
6. **Checksum verification:** trivially satisfied — the checksum persisted
   in step 2(c) is computed directly from the same bytes persisted in step
   2(d), in the same request, closing PR19A's documented trust-boundary
   gap without a separate "verify after the fact" step at *write* time.
   (A second, independent verification happens at *read* time, in
   `ImportSourceReader`, §6.5 — deliberate defense-in-depth, not
   redundant: it protects against corruption or tampering occurring
   between write and read, which write-time verification alone cannot
   detect.)
7. **Retry/idempotency (client perspective):** a client retry (e.g. after
   a dropped response but a server-side commit that actually succeeded)
   is handled by the same "register-or-correct" semantics
   `register_or_correct_source` already provides for metadata, extended
   to the blob row via the upsert write in step 2(d).

**Retention obligation this reintroduces**: integrated into PR19A's
existing 180-day retention policy, not a second policy — see §6.6.

This subsection is **proposed architecture, not a finalized decision** —
it is included so the implementation PRs (§24) have a concrete starting
point for independent review, and so the Owner Decisions in §9 can be
evaluated against a realistic ingestion mechanism rather than an abstract
one. Independent review of the implementation PR that adds this endpoint
must re-validate the bounds, the non-committing CRUD variant's exact
signature, and the retention integration (§6.6) before merge.

### 6.3 `EquipmentMasterAdapter` shape (structure resolved; field-level
content gated by §9 OD-1)

The pseudocode below matches the actual merged `ImportAdapter` ABC
signatures exactly (`backend/app/services/import_adapter.py`, confirmed by
reading the real code, not assumed) — every method takes precisely the
parameters the real base class declares, no more:

```python
from app.services.import_adapter import (
    DryRunPlan,
    FieldError,
    ImportAdapter,
    RawImportRecord,
    register_adapter,
)

class EquipmentMasterAdapter(ImportAdapter):
    dataset_type = "equipment_master"
    ruleset_version = "1"

    def parse(self, raw_input: "VerifiedSourceContent") -> list[RawImportRecord]:
        # `raw_input` is the checksum/length-verified content
        # `ImportSourceReader` resolves and hands to the framework (§6.5)
        # — never None for this adapter, unlike the PR19A-era default, and
        # never bytes the adapter fetched itself. Opens the workbook via
        # openpyxl (reusing PR12's parsing discipline: header detection,
        # blank-row skip, bounded rows/worksheets/headers), yields one
        # RawImportRecord per data row, 1-based row_number matching the
        # source file. Exact column names: BLOCKED on §9 OD-1.
        ...

    async def preload_business_context(
        self, db: AsyncSession, records: list[RawImportRecord]
    ) -> "EquipmentMasterContext":
        # Bulk-resolves every distinct BCM/Item No appearing in `records`
        # via the existing get_by_bcm_codes/get_by_item_nos (§4.3) in
        # exactly two queries, regardless of row count — avoids N+1,
        # matching PR19A2's precedent. Returns a context object exposing
        # both maps to validate_business_rules. No session/source identity
        # needed here — record-level business context only (§6.4).
        ...

    def validate_business_rules(
        self, record: RawImportRecord, context: "EquipmentMasterContext"
    ) -> list[FieldError]:
        # Per-row: canonicalize BCM/Item No (§4.2), check required
        # fields, check within-workbook duplicates, resolve identity
        # against `context` (§9 OD-3), classify legacy status (§9 OD-1),
        # and — if create is authorized (§9 OD-2) — validate the
        # would-be-created record against the same constraints
        # `POST /equipment` already enforces. Exact rules: BLOCKED on
        # §9 OD-1/OD-2/OD-3.
        ...

    async def plan_dry_run(self, db: AsyncSession) -> DryRunPlan:
        # `db` is the caller's genuinely read-only session (§3.4). Session/
        # source identity is obtained from the adapter-invocation
        # contextvar (§6.4), never by querying for "the" running job.
        # Runs parse -> preload_business_context -> validate_business_rules
        # against the verified, frozen source content (§6.5) and the same
        # ruleset_version, resolving each row's planned action (CREATE/
        # UPDATE/SKIP) against the *current* database state, and — for
        # every UPDATE row — capturing that row's concurrency token
        # (matched_equipment.updated_at) *now*, at dry-run time (§15.1).
        # Returns the full row-level plan via `DryRunPlan.summary` (an
        # in-memory, read-only computation only — this method itself never
        # writes; persistence is a separate step, below). Exact
        # create/update content: BLOCKED on §9 OD-1/OD-2.
        ...

    async def persist_dry_run_plan(self, db: AsyncSession, plan: DryRunPlan) -> None:
        # NEW, additive, default-no-op ImportAdapter hook (§14) — called
        # by the framework on the normal *writable* session, immediately
        # after plan_dry_run's read-only evaluation succeeds and closes,
        # in the same transaction as the session's dry_run_completed
        # fenced-completion write. Persists `plan`'s row-level content
        # into the two new PR20-owned tables
        # (equipment_master_dry_run_plans /
        # equipment_master_dry_run_plan_rows, §14) — including each
        # UPDATE row's captured concurrency token — as one immutable,
        # newly `active` plan, marking any prior `active` plan for this
        # session `superseded` in the same transaction. Never called
        # inside plan_dry_run's own read-only transaction.
        ...

    async def execute(self, db: AsyncSession) -> int:
        # `db` is the caller's normal read-write session, inside TX1
        # (§3.5, §15) — never commits/rolls back itself. Session/source/
        # dry_run_plan identity via the same contextvar (§6.4). Loads the
        # *exact* confirmed plan by id (never recomputes, never re-parses
        # the source) and, as its own first step, verifies the plan is
        # `active` (not already `consumed` or `superseded`) — an invalid
        # plan raises immediately, surfacing through the existing
        # crash/fenced-failure path (§15, §6.5's failure-classification
        # table). Applies each plan row's planned action: UPDATE rows via
        # the CAS predicate using that row's own persisted concurrency
        # token (§15.1, never a freshly-read one); CREATE rows (once
        # authorized, §9 OD-2) via a plain insert guarded by the existing
        # unique constraints (§16). Marks the plan `consumed` in the same
        # transaction on success. Returns imported_rows count. Exact write
        # content: BLOCKED on §9 OD-1/OD-2.
        ...


register_adapter(EquipmentMasterAdapter())
```

Note the registration call: the real `register_adapter(adapter:
ImportAdapter) -> None` takes only the adapter instance — it reads
`adapter.dataset_type` itself — not a separate `dataset_type` argument.
(Fix-round-2 L1R: every `register_adapter` call in this document,
including §6.1's, now uses this exact form — swept, not just the
previously-cited instance.)

This shape is implementation-grade for every part not gated by an Owner
Decision: the adapter's *structure*, its integration points with PR19A's
lease/fencing/dry-run/execute mechanics, its invocation-context contract
(§6.4), its verified-content boundary (§6.5), its persisted-plan
lifecycle (§14, §15.1), and its reuse of `preload_business_context` for
bulk lookups are fully specified. Only the row-level *content* of
`validate_business_rules`/`plan_dry_run`/`execute` — which fields exist,
how they map, and what identity/create-update policy governs them — is
blocked.

### 6.4 Adapter Invocation Context — session/source identity for `plan_dry_run`/`execute`

**Real constraint, confirmed by reading the actual call sites (not
assumed):** `import_execution_service.run_dry_run` calls exactly
`await adapter.plan_dry_run(ro_db)`, and `run_execute` calls exactly
`imported_rows = await adapter.execute(db)` — **neither passes
`import_session_id`, `import_source_id`, or any other identity
parameter.** `parse`/`preload_business_context`/`validate_business_rules`
don't need this (they operate on records/db already scoped correctly by
the caller), but `plan_dry_run`/`execute` genuinely cannot know *which*
session's source to act on from their parameters alone. The adapter must
never resolve this by querying for "whichever job is currently running"
— that is exactly the "adapter reconstructing source identity by querying
arbitrary tables on its own" anti-pattern this fix round rules out, and it
would be unsafe under concurrent sessions of the same `dataset_type`
regardless.

**Resolution — a small, additive, backward-compatible extension to the
PR19A service layer** (in scope for PR20A, §24, not a modification of any
existing adapter's observable behavior, since no other adapter exists
yet):

```python
import contextvars
from dataclasses import dataclass

@dataclass(frozen=True)
class AdapterInvocationContext:
    """Immutable. Set by the framework immediately before calling
    `adapter.plan_dry_run`/`adapter.execute`, read by the concrete
    adapter's own implementation of those methods -- never passed as a
    positional/keyword argument, so `ImportAdapter`'s existing merged
    ABC method signatures are not modified."""

    import_session_id: uuid.UUID
    import_source_id: uuid.UUID
    dataset_type: str
    source_checksum: str
    source_fingerprint: str
    ruleset_version: str
    # Populated only for `plan_dry_run` (fix round 3, H1R2) -- the
    # framework calls `source_reader.open_verified(...)` itself on the
    # read-only session and places the result here *before* invoking
    # `plan_dry_run`, exactly mirroring how `run_validation` already
    # passes verified content to `parse()` as an argument. `None` for
    # `execute`, which never re-reads or re-parses the source (§14.4).
    verified_source_content: "VerifiedSourceContent | None"
    # Populated only for `plan_dry_run` (fix round 3, H4R2) -- the exact
    # `ImportJob.id` the framework has just admitted for *this* dry-run
    # attempt (the framework already holds this value; it is threaded
    # here rather than the adapter guessing or querying for "the latest"
    # job). `None` for `execute`.
    dry_run_job_id: uuid.UUID | None
    # Populated only for `plan_dry_run` (fix round 3, H4R2) -- the exact
    # `ImportJob.id` of the session's currently accepted validation
    # snapshot (`ImportSession.current_validation_job_id`, existing
    # PR19A field, §3.1), which the framework already holds. `None` for
    # `execute`.
    accepted_validation_job_id: uuid.UUID | None
    # Populated only for `execute` (from the new required request-body
    # field on `POST /{id}/execute`, §14's "Execution Input Contract") --
    # always `None` for `plan_dry_run`, which is creating a plan, not
    # consuming one.
    dry_run_plan_id: uuid.UUID | None

_adapter_invocation_context: contextvars.ContextVar[AdapterInvocationContext | None] = (
    contextvars.ContextVar("_adapter_invocation_context", default=None)
)

def get_adapter_invocation_context() -> AdapterInvocationContext:
    ctx = _adapter_invocation_context.get()
    if ctx is None:
        raise RuntimeError(
            "No AdapterInvocationContext is set -- plan_dry_run/execute "
            "must only be called from within the framework's own "
            "context-setting wrapper."
        )
    return ctx
```

`import_execution_service.run_dry_run`/`run_execute` (both already have
`session`/`job_row` loaded at the point they call the adapter, per the
actual merged code) set this contextvar immediately before, and reset it
immediately after, each `adapter.plan_dry_run(ro_db)`/`adapter.execute(db)`
call — using `contextvars.Token`-based reset (Python's standard,
task-safe pattern; each `asyncio` task gets its own copy of the context,
so two concurrent sessions' dry-run/execute calls never observe each
other's context, unlike a plain module-level global).
`EquipmentMasterAdapter.plan_dry_run` calls
`get_adapter_invocation_context()` internally to obtain
`verified_source_content` (fix round 3, H1R2 — the framework, not the
adapter, already called `ImportSourceReader.open_verified` before setting
this context, §6.5) to re-parse the same frozen source `run_validation`
already parsed, `ruleset_version` (to select the correct parsing/mapping
logic if more than one legacy source format is ever authorized, §9 OD-1),
and `dry_run_job_id`/`accepted_validation_job_id` (fix round 3, H4R2 — to
populate the persisted plan header's own two job-identity columns, §14.2,
without ever querying for "the latest" of either) — never
`import_session_id` for any write purpose, since neither `plan_dry_run`
nor `execute()` writes to `import_sessions`/`import_jobs` itself (that
remains the framework's own responsibility, §3.3/§3.5); `import_session_id`
is retained in the context only for audit-logging purposes (§18).
`execute()` reads only `dry_run_plan_id`, to load the exact confirmed plan
(§14.4) — `verified_source_content`/`dry_run_job_id`/
`accepted_validation_job_id` are always `None` for `execute()`, since it
never re-reads or re-parses the source.

This mechanism is **one of the small, additive backend extensions this
design proposes to `import_execution_service.py`/
`import_validation_service.py`** (the others are `persist_dry_run_plan`'s
call site and the framework's own `open_verified` call before
`plan_dry_run`, both §14/§6.5) — neither changes either function's own
signature, return type, or any existing behavior for a session with no
adapter-side dependency on this context (a future adapter that doesn't
need session identity simply never calls
`get_adapter_invocation_context()`). All are technical prerequisites, not
gated by OD-1/OD-2/OD-3, and belong in PR20A (§24).

**Concurrent-session isolation, restated for the new fields**: the same
`contextvars`-based, per-`asyncio`-task isolation already claimed for the
identity fields (above) applies identically to
`verified_source_content`/`dry_run_job_id`/`accepted_validation_job_id` —
they are set and reset as part of the same immutable context object, so
two concurrent sessions' dry-run attempts can never observe each other's
verified content or job IDs, exactly as they can never observe each
other's session/source identity (§22 adds a dedicated test for this).

### 6.5 Verified Source Reader — closing the `parse(None)` gap (fix round 2, H1R)

**Fix-round-2 correction: the prior revision still conceptually described
`parse()` receiving `None` or an unverified reference, with no complete
contract for loading and cryptographically verifying the registered
blob.** This is removed. The framework never calls
`adapter.parse(None)` for `dataset_type="equipment_master"`, and the
adapter never independently queries storage or the database to find its
own source content.

**`ImportSourceReader`** — a new, PR20-owned (not PR19A-modifying)
infrastructure component, analogous in spirit to `ImportSourceReader` or
an equivalent repository-consistent name, called by the framework
(`import_validation_service.run_validation`, immediately before invoking
`adapter.parse(...)`) — never by the adapter itself:

```python
@dataclass(frozen=True)
class SourceDescriptor:
    """Immutable. What the framework already knows about a registered
    source before reading its bytes -- never an ORM model."""

    import_source_id: uuid.UUID
    import_session_id: uuid.UUID
    dataset_type: str
    expected_checksum: str
    expected_byte_size: int
    content_type: str | None
    # Untrusted metadata only -- never used for parsing decisions.
    original_filename: str | None
    registration_status: str  # "registered" | "frozen"


@dataclass(frozen=True)
class VerifiedSourceContent:
    """Returned only after every check below has passed. This, not raw
    bytes and not a storage locator, is what `raw_input` actually is by
    the time `adapter.parse()` receives it."""

    content: bytes
    source_descriptor: SourceDescriptor


class ImportSourceReader:
    async def open_verified(
        self, db: AsyncSession, descriptor: SourceDescriptor
    ) -> VerifiedSourceContent:
        # 1. Load the blob referenced by import_source_id from
        #    import_source_blobs (§6.2). Missing row -> raise
        #    SourceBlobMissingError.
        # 2. Enforce the bounded byte/file limit again at read time
        #    (MAX_UPLOAD_BYTES, §7/§21) -- defense in depth, not trusting
        #    that write-time enforcement alone is sufficient forever.
        # 3. Recompute the checksum from the loaded bytes and compare
        #    against descriptor.expected_checksum. Mismatch ->
        #    raise SourceChecksumMismatchError.
        # 4. Verify len(content) == descriptor.expected_byte_size.
        #    Mismatch -> raise SourceLengthMismatchError.
        # 5. Return VerifiedSourceContent, or propagate a typed
        #    exception -- never return partially-verified content.
        ...
```

**Ownership boundary, stated explicitly**: the framework calls
`source_reader.open_verified(db, descriptor)`, then calls
`await asyncio.to_thread(adapter.parse, verified_content)` — conceptually:

```
verified = await source_reader.open_verified(db, descriptor)
records = await asyncio.to_thread(adapter.parse, verified)
```

**never** `adapter.parse(None)`, and **never** the adapter reaching into
`import_source_blobs` or any storage mechanism on its own. `parse()`'s
own signature is unchanged from the merged ABC (`parse(self, raw_input:
Any) -> list[RawImportRecord]`) — `VerifiedSourceContent` is simply the
concrete type `raw_input` holds for this adapter, exactly as
`SourceContentRef` was described (imprecisely, before this fix round) in
the prior revision.

**Fix-round-3 correction (H1R2): this closes the gap only for
`run_validation`'s direct call to `parse(raw_input)` — it does not, by
itself, give `plan_dry_run(self, db)` any way to obtain the same content,
since that method's merged ABC signature takes no `raw_input` parameter at
all.** The prior revision left this silently unaddressed; §6.3's
`plan_dry_run` pseudocode still implied it could "just" re-parse the
source without saying how it would obtain verified bytes. Fixed
explicitly:

- `import_execution_service.run_dry_run` calls `source_reader.open_verified(
  ro_db, descriptor)` itself — on the same read-only session already used
  for `plan_dry_run` (§3.4) — **before** invoking
  `adapter.plan_dry_run(ro_db)`, exactly mirroring what
  `run_validation` already does for `parse()`.
- The resulting `VerifiedSourceContent` is placed into
  `AdapterInvocationContext.verified_source_content` (new field, §6.4),
  set via the same `contextvars.ContextVar` mechanism immediately before
  the `plan_dry_run` call.
- `EquipmentMasterAdapter.plan_dry_run` reads
  `get_adapter_invocation_context().verified_source_content` and calls
  `self.parse(...)` on it itself, internally, to regenerate the identical
  record set `run_validation` already produced (the source is
  checksum-frozen and immutable, §6.2, so re-parsing the same verified
  bytes is deterministic and cannot diverge from what was validated) —
  **the adapter still never calls `ImportSourceReader` itself; the
  framework is unconditionally the only caller of `open_verified`, for
  every phase that needs source content, not `run_validation` alone.**
- **Failure behavior is identical for both phases**: if
  `source_reader.open_verified` raises during `run_dry_run` (e.g. a
  transient storage read failure — checksum/length mismatch should be
  structurally unreachable here since the source was already verified
  once at validate time and is immutable thereafter, but the same defensive
  check runs again, defense-in-depth, exactly as §6.5 already documents
  for validate), it routes through the identical failure-classification
  table (below) and existing TX1/TX2 crash path — scoped to the `dry_run`
  phase's own job/session state transitions, not the `validate` phase's.
- **Execute needs no such threading**: `execute()` never calls `parse()`
  or reads `verified_source_content` — it loads the confirmed persisted
  plan (§14.4) and never re-parses the source, so this context field is
  populated only for the `validate` and `dry_run` phases and is `None`
  during `execute`.

**Failure semantics — stable outcomes, reusing existing PR19A machinery,
not a new error architecture:**

| Condition | Classification | Mechanism |
|---|---|---|
| Blob row missing (`SourceBlobMissingError`) | Structural/crash failure | Raised, uncaught, propagates through `run_validation` exactly as any other unhandled exception during validation already does — triggers the existing TX1 rollback + TX2 fenced-failure path (PR19A design §9.4.2), producing `validation_failed` with null counters, empty findings, and a bounded generic `failure_reason` (the same structural flavor already established for the empty-file case, §7). Should never actually occur given §6.2's atomic registration contract; this is defense against a theoretical data-integrity gap, not an expected operational path. |
| Checksum mismatch (`SourceChecksumMismatchError`) | Structural/crash failure | Same mechanism as above — indicates corruption or tampering after write-time verification (§6.2), not a business/row-level problem, so it is never expressed as a `ValidationFinding` (there is no valid row to attach one to). |
| Byte-length mismatch (`SourceLengthMismatchError`) | Structural/crash failure | Same mechanism as above. |
| Storage/database unavailable while reading the blob | Structural/crash failure, retryable | Same mechanism — this is exactly what PR19A's crash/recovery path (`POST /{id}/recover`) already exists for; once the underlying outage resolves, recovery reclaims the expired lease and a fresh validate attempt can retry `open_verified` from scratch. No new retry machinery is introduced. |
| `.xlsx` invalid/corrupt (parse-time failure inside `adapter.parse()`) | Structural/crash failure | `parse()` raises (e.g. openpyxl fails to open the workbook); propagates uncaught through the same TX1/TX2 path — there is no row to attach a finding to when the file cannot be opened at all. |
| Resource limit exceeded (rows/worksheets/headers/decompressed size, §7/§21) | Structural/crash failure for parse-time bounds PR20 itself enforces (zip-bomb/decompression, worksheet/header counts); already-enforced by the existing framework for `MAX_IMPORT_ROWS` (checked immediately after `parse()` returns, per the merged `import_adapter.py`'s own module-level comment — PR20 does not duplicate this check) | Parse-time bound violations raise from within `parse()` itself, same crash path as above; the row-count bound is already framework-enforced and requires no PR20 code. |

Every row in this table resolves to the **same** existing mechanism
(uncaught exception → TX1/TX2 crash path → `validation_failed`,
structural flavor) or an already-framework-enforced check — no new error
architecture, no new status, no new severity model. A row that genuinely
parses is validated as a normal business row exactly as before
(`validate_business_rules`, §6.3); only whole-file-level failures reach
this table.

### 6.6 Source Blob Retention — integrated into PR19A's existing policy (fix round 2, H3R)

**Fix-round-2 correction: PR19A already owns retention policy/lifecycle
(§3.6, `IMPORT_RETENTION_DAYS`, `import_retention_crud.claim_sessions_for
_cleanup`/`redact_session`). This design does not create a second,
independent retention policy for source blobs — it extends the existing
one.**

- **Eligibility clock**: identical to every other retained field on the
  session — the blob becomes retention-eligible at the same moment the
  rest of the session's redaction becomes eligible, driven by the same
  `terminal_at`-anchored, `IMPORT_RETENTION_DAYS`-configured window (§3.6).
  There is no separate blob-specific clock.
- **Mechanism — extend `redact_session`, don't duplicate it**: because
  `import_source_blobs` lives in the same PostgreSQL database as every
  other row `redact_session` already touches, blob deletion is added as
  one more statement (`DELETE FROM import_source_blobs WHERE
  import_source_id = ...`) **inside the same transaction** as the
  existing redaction `UPDATE`s. This is the same single-database-
  transaction collapse that makes §6.2's registration atomic — it applies
  identically here.
- **Reconciling this with PR19A's own forward-reference guidance**: the
  PR19A design doc explicitly warned that a future byte-storing slice
  "must... drive [deletion] from a genuine, independently-retried
  deletion attempt, not set it eagerly in the same code path as the rest
  of retention redaction" — written under a general assumption that byte
  storage might live in an external system where deletion cannot be
  guaranteed atomic with the database transaction. That risk does not
  apply to same-database BYTEA storage: a `DELETE` inside a transaction
  either commits with the rest of that transaction or the whole
  transaction (redaction included) rolls back together — there is no
  intermediate state where the metadata claims purged but the blob still
  exists, or vice versa. Same-transaction deletion is **stronger** than
  an eventually-consistent outbox/retry pattern here, not a violation of
  the underlying intent (never claim purged without the deletion actually
  having happened) — it satisfies that intent more directly. `PR19A's own
  guidance is honored in spirit; the specific outbox/retry mechanism it
  anticipated is unnecessary given this design's specific storage choice,
  and this document states that reconciliation explicitly rather than
  silently deviating.
- **Idempotent retry, already provided**: if the retention-cleanup
  transaction itself fails or the worker process crashes mid-run, the
  whole transaction (redaction + blob deletion together) rolls back — the
  session remains un-purged, its `retention_cleanup_claimed_by`/
  `retention_cleanup_claim_expires_at` bookkeeping unchanged from before
  the attempt, and a later cleanup run claims and retries it via the
  **existing** `SELECT ... FOR UPDATE SKIP LOCKED` claim mechanism (§3.6)
  — no new retry/tombstone machinery is introduced, because the existing
  one already covers this case once blob deletion is folded into the same
  transaction.
- **Concurrent cleanup claims**: the existing claim mechanism already
  prevents two workers from claiming the same session (§3.6); extending
  the claimed session's own redaction transaction to also delete its
  1:1 blob introduces no new concurrency surface.
- **Metadata survival after blob purge**: unchanged from the existing
  precedent — `import_sources.checksum`/`byte_size` are retained (not
  PII), `filename`/`content_type` are redacted exactly as today;
  `import_source_blobs`'s row for that source no longer exists at all
  after deletion — its *absence* is the tombstone; no separate tombstone
  column is needed since the FK relationship (§6.2) already makes
  "blob row exists" a well-defined, queryable fact.
- **Session/history behavior after blob is gone**: `GET
  /import-sessions/{id}` and `GET /{id}/errors` continue to work exactly
  as before (session and finding metadata retention is unchanged, §3.6);
  a hypothetical future "re-download the original source" feature (not
  proposed anywhere in this design) would simply fail after purge,
  consistent with the existing redaction philosophy of making purged data
  genuinely unavailable, not merely hidden.
- **Audit**: no new audit entry is introduced beyond what the existing
  retention redaction path already produces (if any) and the existing
  `AUDIT_ACTION_IMPORT_FENCE_LOST` path for a lost claim (§3.6, unchanged)
  — confirm the exact existing call site's behavior at implementation
  time; this design does not add a distinct audit event class for blob
  deletion specifically, since it is part of the same redaction action.
- **PR20A scope, revised again**: given the above, retention integration
  is a small, well-defined extension (one additional `DELETE` in an
  already-existing transaction), not a new subsystem — it belongs in
  PR20A alongside the rest of the source-artifact infrastructure (§24),
  not a separate slice.
- **This subsection covers the source blob only.** Fix round 3 (H9)
  identified that the two persisted dry-run plan tables PR20C introduces
  (§14.2) carry their own retention-relevant JSONB content and are
  **not** covered by the extension above — that extension is specified
  separately, in §14.9, since those tables don't exist until PR20C's
  migration lands, and is PR20C's ownership responsibility, not PR20A's,
  even though it composes onto the same underlying transaction this
  subsection extends.

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
- **Numeric cells rendered as identifiers** (e.g. a user typing `00123`
  into Excel, which silently stores the number `123` with a *display*
  format that shows the padding): **correction from the prior revision —
  reading such a cell "as text" does not recover the original leading
  zeros.** Once Excel has stored the value as a number, the padding was
  never persisted as characters; it is presentation metadata (a numeric
  format string) attached to the cell, not retrievable from the
  underlying value. PR20 must distinguish two genuinely different cases:
  (a) the source cell is **text-typed** in the workbook — leading zeros
  are real characters and are preserved correctly by reading the cell as
  a string, no special handling needed; (b) the source cell is
  **numeric-typed** — any leading-zero padding is already, unrecoverably
  lost at the source, and PR20 must not attempt to reconstruct it (e.g. by
  re-padding to a guessed fixed width) except where a specific,
  Owner-approved mapping rule makes the original value unambiguous (for
  example, a *known*, fixed-width identifier format confirmed as part of
  §9 OD-1). Absent such an explicit rule, a numeric-typed identifier
  candidate cell must produce a blocking or warning finding (per §9 OD-1's
  eventual taxonomy) demanding source correction, never a silently
  invented value — this constraint on *behavior* is knowable and fixed now
  even though *which* column is the identifier column, and whether a safe
  re-padding rule exists, is not.
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

## 14. Dry-Run Contract — Persisted, Immutable Plan Artifact (rewritten, fix round 2, H4R)

**Fix-round-2 correction: the prior revision proposed live-recomputing
the dry-run summary on every request. Independent review correctly
rejected this — the user must confirm a specific, persisted, immutable
artifact, not a session whose "dry-run" is really a moving target
recomputed against whatever the database happens to look like at request
time.** This section is rewritten around that requirement.

### 14.1 The core design invariant this section (and §15.1) implements

```
registered immutable source (§6.2)
        |
        v
validation snapshot (existing PR19A ImportJob, job_type="validate")
        |
        v
persisted dry-run plan  <-- NEW, this section
        |
        v
user confirmation of that exact plan (by plan id)
        |
        v
execution of THAT SAME plan  <-- rewritten, this section + §15.1
        |
        v
fenced atomic result (existing PR19A TX1/TX2 + admission/fencing)
```

Five distinct identities are tracked through this chain, deliberately
never collapsed into "latest": (1) source artifact identity
(`import_source_id`/`source_checksum`, §6.2); (2) validation snapshot
identity (the specific validate `ImportJob.id`, existing PR19A); (3)
dry-run plan identity (`dry_run_plan_id`, new, this section); (4)
Equipment concurrency tokens captured *by that plan* (§15.1, one per
planned UPDATE row, not re-read at execute time); (5) execution attempt
identity (the execute `ImportJob.id`, existing PR19A, admitted only after
plan validity is confirmed, §14.4).

### 14.2 Persisted schema — two new, PR20-owned tables

Reuses PR19A's `plan_dry_run(db: AsyncSession) -> DryRunPlan` signature
and read-only enforcement (§3.4, §6.3) for *computing* the plan — that
part of the merged contract is correct and unchanged. What changes is
that the plan's row-level content is now **persisted**, not discarded,
via the new `persist_dry_run_plan` adapter hook (§6.3) called by the
framework on the writable session immediately after the read-only
evaluation succeeds:

```python
# equipment_master_dry_run_plans (plan header, one row per dry-run attempt
# that reached a countable result)
id: UUID PK
import_session_id: UUID  # FK import_sessions.id
import_source_id: UUID  # FK import_sources.id
source_checksum: str  # copy, defense-in-depth (must match import_sources.checksum)
accepted_validation_job_id: UUID  # composite FK (import_session_id,
    # accepted_validation_job_id) -> (import_jobs.import_session_id,
    # import_jobs.id) -- fix round 3, H8: a plain FK could reference a
    # DIFFERENT session's validation job; the composite form makes
    # cross-session binding physically impossible, not merely
    # conventionally avoided, exactly like dry_run_job_id below
dry_run_job_id: UUID  # composite FK (import_session_id, dry_run_job_id)
    # -> (import_jobs.import_session_id, import_jobs.id), mirroring
    # PR19A's existing current_validation_job_id pattern (§3.1) for
    # DB-provable ownership
ruleset_version: str
status: str  # CHECK IN ('active', 'superseded', 'consumed', 'failed')
    # -- 'failed' added fix round 3, H6: a plan whose confirmed execution
    # attempt hit a genuine conflict/error is marked 'failed' in the same
    # transaction that marks the session terminally `failed` (§15.1) --
    # it must never be left `active`/confirmable after that, and it is
    # deliberately a distinct terminal value from 'superseded' (superseded
    # by a newer dry-run) and 'consumed' (applied successfully)
created_at: UTCDateTime
summary_total_rows: int  # CHECK (summary_total_rows >= 0), and likewise
    # for every summary_* column below (fix round 3, H8)
summary_creates: int  # CHECK (summary_creates >= 0)
summary_updates: int  # CHECK (summary_updates >= 0)
summary_skips: int  # CHECK (summary_skips >= 0)
summary_warnings: int  # CHECK (summary_warnings >= 0)
summary_blocking_conflicts: int  # CHECK (summary_blocking_conflicts >= 0)

# Fix round 3, H8: partial unique index enforcing "never more than one
# active plan per session" as a physical constraint, not merely an
# application-level convention (§14.3's superseding logic is the write
# path that keeps this true, but the constraint is what makes it
# impossible to violate even under a bug or a race):
#   CREATE UNIQUE INDEX uq_one_active_plan_per_session
#     ON equipment_master_dry_run_plans (import_session_id)
#     WHERE status = 'active';
# Fix round 3, H8: one plan per dry-run job attempt (a given dry_run
# ImportJob.id can never back more than one persisted plan):
#   UNIQUE (import_session_id, dry_run_job_id)

# equipment_master_dry_run_plan_rows (one row per planned action)
id: UUID PK
dry_run_plan_id: UUID  # FK equipment_master_dry_run_plans.id
source_row_number: int  # 1-based, matches the source file
    # Fix round 3, H8: UNIQUE (dry_run_plan_id, source_row_number) --
    # a given plan can never contain two rows for the same source row
action: str  # CHECK IN ('CREATE', 'UPDATE', 'SKIP') -- no other value
    # without an Owner Decision (§9); no new Equipment lifecycle state
target_equipment_id: UUID | None  # set only for UPDATE -- FK
    # equipment.id ON DELETE RESTRICT (fix round 3, H8: Equipment rows in
    # this codebase are soft-deleted only, via SoftDeleteMixin, confirmed
    # by reading the model directly, §15.1 scenario (e); a hard DELETE of
    # an Equipment row referenced by a plan row is not a reachable
    # operation today, so RESTRICT documents that expectation explicitly
    # rather than silently allowing a future hard-delete path to orphan
    # historical plan rows)
    # Fix round 3, H8, CHECK ((action = 'UPDATE') = (target_equipment_id IS NOT NULL)):
    # target_equipment_id is set if and only if action = 'UPDATE'
normalized_values: JSONB  # the values that would be written -- exact
    # field set BLOCKED on OD-1/OD-2
matched_identity_fields: JSONB  # BCM/Item No used for matching, for audit/
    # display, not re-derivation -- retention-redacted, §6.6/§14.9 (H9)
expected_concurrency_token: UTCDateTime | None  # UPDATE rows only --
    # captured HERE, at dry-run time, never refreshed (§15.1)
    # Fix round 3, H8, CHECK ((action = 'UPDATE') = (expected_concurrency_token IS NOT NULL)):
    # expected_concurrency_token is set if and only if action = 'UPDATE'
warnings: JSONB  # findings relevant to this specific row's confirmation
    # -- retention-redacted, §6.6/§14.9 (H9)
```

Both tables are additive; neither modifies `import_sessions`,
`import_sources`, `import_jobs`, or `import_row_errors`. This is a
schema/migration requirement assigned to **PR20C** (§24), since it is
inseparable from the execute-by-plan-id mechanism (§14.4) — not PR20A,
which has no need for it (PR20A never computes or reads a plan). Every
constraint above is a required part of that migration, following this
codebase's existing fail-closed `_verify_schema_convergence()` discipline
and fresh-install/historical-upgrade PostgreSQL test pattern already used
for migration 0015 (§3.1) — the migration is not considered complete
without a test proving each constraint actually rejects the row it names
(cross-session job binding, a second concurrent `active` plan, a
duplicate `source_row_number`, a negative summary count, and a
CREATE/SKIP row carrying a non-null `target_equipment_id`/
`expected_concurrency_token`, or an UPDATE row missing either).

### 14.3 Write-time mechanics — how a read-only computation becomes a persisted write

`adapter.plan_dry_run(ro_db)` itself remains 100% read-only, exactly as
PR19A's merged contract already enforces (`SET TRANSACTION READ ONLY`,
§3.4) — it computes the full row-level plan in memory and returns it via
`DryRunPlan`, **never writing anything**. Persistence happens as a
**separate, additive step** in `import_execution_service.run_dry_run`,
after the read-only sub-session closes and the computed `DryRunPlan` is
back in scope on the *normal, writable* session — the same session
`fenced_phase_success` already uses to commit the session's
`dry_run_completed` transition:

```
async with AsyncSessionLocal() as ro_db:
    ... SET TRANSACTION READ ONLY ...
    dry_run_plan = await adapter.plan_dry_run(ro_db)   # unchanged, PR19A

# NEW: on the normal writable `db`, same transaction as the fenced
# completion write below -- a session can never reach `dry_run_completed`
# without a matching persisted plan, or vice versa.
await adapter.persist_dry_run_plan(db, dry_run_plan)   # NEW (§6.3)

final_session = await import_job_crud.fenced_phase_success(db, ...)  # unchanged, PR19A
await db.commit()   # unchanged, PR19A -- now also commits the plan
```

`persist_dry_run_plan` (§6.3) marks any prior `active` plan for this
session `superseded` in the same transaction before inserting the new
`active` plan and its rows — **a fresh dry-run always supersedes every
prior plan for that session**; there is never more than one `active` plan
at a time, making "the current confirmable plan" a trivial, unambiguous
query (`WHERE import_session_id = ... AND status = 'active'`).

### 14.4 Execution input contract — confirming a plan id, not a session (rewritten, fix round 3, H6/H7)

**Fix-round-3 correction: the prior revision asserted checks 1–4 below
happen "before admission" but then assigned them to `adapter.execute()`
"as its own first step" — those two claims contradict the actual merged
state machine. `import_execution_service.run_execute` only calls
`adapter.execute(db)` *after* `admit_phase_job` has already won the CAS
race and transitioned the session to `executing` (§3.3, confirmed by
reading the real call order). A check inside `adapter.execute()` is
therefore a *post-admission* check: raising there enters the existing
TX2 path and marks the session terminally `failed` — it is not a
pre-admission request rejection, and (per the unchanged PR19A state
machine) a `failed` session cannot transition back to `dry_run_completed`
to allow a same-session retry. This section now defines two explicit,
separate layers instead of one ambiguous one.** It also corrects a second
defect: the prior revision made `dry_run_plan_id` unconditionally
**required** on the same generic `POST /{id}/execute` route every
dataset type shares, which would break every existing/future adapter
that has no persisted-plan concept of its own (§3.2 still correctly
states the PR19A API surface is reused, not forked).

**API contract (H7 fix)**: the generic request schema gains one new
**optional** field, harmless to every other `dataset_type`:

```
POST /import-sessions/{id}/execute
{ "dry_run_plan_id": "<uuid> | null" }   # optional at the generic route
```

The framework unconditionally threads whatever value is present (or
`None`) into `AdapterInvocationContext.dry_run_plan_id` (§6.4) — no
per-dataset-type branching in the generic route or its Pydantic model.
Whether the field is *required* is an **adapter-specific** rule, enforced
by Layer 1 below for `dataset_type="equipment_master"` only; an adapter
with no plan concept simply never reads `dry_run_plan_id` from the
context and is completely unaffected by its presence in the schema.

**Layer 1 — framework-owned, pre-admission validation (no state
mutation, stable 4xx, runs *before* `admit_phase_job`)**: a new,
additive check in `run_execute`, before the existing CAS admission call,
specific to sessions whose `dataset_type == "equipment_master"`:

1. **the field is present** — if `dry_run_plan_id` is `null`/missing for
   this dataset type, return `400 Bad Request`,
   `IMPORT_EXECUTE_DRY_RUN_PLAN_ID_REQUIRED` (a structural client error,
   not a business one — no session/plan row is touched);
2. **the plan exists and belongs to this session**
   (`plan.import_session_id == session.id`) — `404 Not Found`,
   `IMPORT_DRY_RUN_PLAN_NOT_FOUND`, if not;
3. **the plan belongs to the exact frozen source**
   (`plan.import_source_id == session.import_source_id` and
   `plan.source_checksum == import_sources.checksum`) — structurally
   guaranteed to always hold given §6.2's immutable-once-frozen source,
   but verified defensively, not assumed — `409 Conflict`,
   `IMPORT_DRY_RUN_PLAN_SOURCE_MISMATCH`, if not;
4. **the plan references the currently accepted validation snapshot**
   (`plan.accepted_validation_job_id ==
   session.current_validation_job_id`, existing PR19A field, §3.1) — per
   the merged state machine, a session cannot re-enter `validating` once
   it has reached `dry_run_completed` without an intervening cancel (a
   fresh session), so this is confirmed structurally unreachable as a
   *failure* case, but is included as an explicit, cheap defensive check
   — `409 Conflict`, `IMPORT_DRY_RUN_PLAN_VALIDATION_MISMATCH`, if not;
5. **the plan is `active`** (not `superseded`/`consumed`/`failed`) —
   `409 Conflict`, `IMPORT_DRY_RUN_PLAN_NOT_ACTIVE`, if not. **This is the
   layer that makes "resubmit a stale/superseded plan id" a same-session,
   no-mutation, retryable rejection**: the session's own state is
   completely untouched by a Layer-1 failure, so the operator can request
   a fresh dry-run (§14.3, which supersedes nothing that hasn't already
   been superseded) and retry `execute` with the new plan's id, on the
   *same* session, as many times as needed — Layer 1 never marks anything
   `failed`.

Only a request that passes all five Layer-1 checks reaches
`admit_phase_job` at all.

**Layer 2 — post-admission, same-TX1, locked re-check (closes the race
between Layer 1 and admission)**: `admit_phase_job` is a CAS on the
session's own `version`/`status` (§3.3, unchanged) — it does not
serialize against a *concurrent* dry-run superseding this exact plan in
the narrow window between Layer 1's read and admission's write. As its
own first step inside `execute()`, after admission has succeeded and
before applying any row, the adapter re-reads the confirmed plan **with a
row lock** (`SELECT ... FOR UPDATE` on the specific
`equipment_master_dry_run_plans` row, inside the same TX1 that will apply
the writes) and re-verifies check 5 above (`status == 'active'`) one more
time. A Layer-2 failure here is **not** a client-input problem — a
concurrent dry-run only *could* have superseded the plan after Layer 1
already accepted it — but this design treats it identically to any other
post-admission execution conflict, below, rather than inventing a third
failure category.

**Post-admission failure lifecycle, defined explicitly (H6)**: any
failure from this point forward — Layer 2's re-check, a §15.1 concurrency
conflict on an UPDATE row, or a unique-constraint `IntegrityError` on a
CREATE row — is a **genuine execution failure**, surfacing through the
existing TX2 crash/fenced-failure path exactly as any other adapter's
`execute()` exception already does (§3.3, §15). This means, stated
plainly rather than left implicit: **the session transitions to its
terminal `failed` state and, under the unchanged merged state machine,
cannot transition back to `dry_run_completed` or `validating` — there is
no same-session retry for a post-admission conflict.** An operator who
hits this must start a **new** import session (a fresh
`ImportSession`/source-registration/validate/dry-run cycle) — resolving
the discrepancy first if the conflict was a genuine data problem, or
simply retrying if it was transient. **In the same TX2 write that marks
the session `failed`, the confirmed plan's own `status` is also updated
to `'failed'`** (§14.2's new status value) — it must never be left
`active`/`is_current=true` (§14.6) once its owning session has terminally
failed; a plan in `'failed'` status can never again pass Layer 1's check
5, closing the loop.

On successful completion, `execute()` marks the plan `consumed` in the
same transaction as the rest of its writes (§15), exactly as the prior
revision already specified.

**Required test coverage, added (§22)**: Layer-1 rejection for a missing
field (equipment_master only), a wrong-session plan id, a
superseded/consumed/failed plan id — each proven to leave the session's
own state completely untouched and immediately retryable; a Layer-2 test
proving a dry-run started and completed *during* the admission race
correctly fails the locked re-check; a post-admission conflict test
proving the session reaches terminal `failed`, the plan reaches `failed`
in the *same* transaction, and no same-session retry is possible
(`POST {id}/dry-run` on a `failed` session is rejected by the existing,
unchanged session-state check, §3.3); and a test proving `dry_run_plan_id`
being absent/`null` has zero effect on any other `dataset_type`'s
existing `execute` behavior.

### 14.5 Plan freshness — what makes a plan stale, defined exhaustively, no TTL

- **Source changed/rebound**: cannot happen — a source is immutable once
  frozen (§6.2, unchanged PR19A invariant). Not a real staleness vector;
  listed for completeness, not because it is reachable.
- **Validation snapshot changed**: cannot happen for the same session
  without an intervening cancel, per §14.4 Layer 1 check 4's
  state-machine analysis above — confirmed non-issue, not merely assumed.
- **Adapter/mapping version changed**: not applicable for V1 (a single
  `ruleset_version="1"`, §6.1); becomes relevant only if OD-1 later
  authorizes multiple legacy source formats with different ruleset
  versions, at which point a mismatch would be included in this check.
- **Target Equipment version changed**: **not** a plan-level staleness
  check — this is deliberately a *row-level* check, performed at execute
  time via each row's own persisted `expected_concurrency_token` (§15.1),
  not a whole-plan invalidation. A stale row fails narrowly and
  identifiably; the plan itself isn't "stale" merely because one row's
  target changed.
- **Identity collision introduced after dry-run** (e.g. a new Equipment
  record now occupies a BCM the plan intended to create): caught at
  execute time by the existing unique-constraint boundary for CREATE rows
  (§16), and by the concurrency-token check for UPDATE rows (§15.1) —
  again row-level, not plan-level.
- **Session state changed** (e.g. cancelled between dry-run and execute):
  caught by the existing, unchanged CAS admission check on the session's
  own `version`/`status` (§3.3) — PR20 adds nothing new here.
- **Plan superseded by a newer dry-run, or failed by a prior execution
  attempt**: the explicit `status` check in §14.4 Layer 1 check 5
  (and Layer 2's locked re-check of the same field) — `status` now also
  covers `'failed'` (fix round 3, H6), so a plan whose earlier execution
  attempt genuinely conflicted can never be resubmitted either.

**No arbitrary time-based TTL is used as a substitute for any of the
above** — every staleness vector the review asked about is either
structurally unreachable (source/validation-snapshot rebinding),
version-irrelevant for V1, or covered by an explicit, targeted check
(supersession, session CAS, or the row-level concurrency token) — a TTL
would only add an arbitrary, unjustified failure mode without closing any
gap these checks don't already close.

### 14.6 API path for confirmation UI

`GET /import-sessions/{id}/dry-run-plan`, Administrator-only (§17),
returns the current `active` plan's `id`, its persisted summary fields
(§14.2), relevant warnings, `created_at`, and `is_current: bool` (a UX
convenience — `true` iff `status == "active"`; the *authoritative*
staleness enforcement is always §14.4's execute-time check, never this
read-only flag). The user confirms by supplying this `id` back to
`POST /{id}/execute` (§14.4) — **a plan id, not merely "this session's
dry-run,"** closing exactly the gap the review identified.

### 14.7 Recovery/fencing interaction — two orthogonal layers, not duplicated

PR19A's existing admission/claim/lease/heartbeat/fencing/TX1-TX2/recovery/
audit machinery (§3.3) is **entirely unchanged** and still governs *job
ownership* — "did this specific dry-run or execute attempt complete
safely, exactly once, even across a crash." The persisted `DryRunPlan` +
per-row concurrency tokens (§15.1) solve a **different** problem —
"does the confirmed business plan still match the real Equipment data by
the time it's applied." These are orthogonal safety layers operating at
different levels (job-attempt integrity vs. business-data freshness), and
this design does not duplicate PR19A's own machinery to build the second
layer — it composes on top of it, entirely within the existing TX1
boundary (§15).

### 14.8 Frontend consumption

This mirrors the structure PR19B's frontend already expects from its
`ImportResultSummary`-adjacent presentation work (nullable counts, never
fabricated zeros) — PR20's backend summary shape should stay compatible
with what PR19B already renders where reasonable, without PR20 being
obligated to match it field-for-field (PR19B's own docs state its mock
fixtures are presentation-only and do not bind PR20's real contract). The
frontend's confirmation step now specifically displays and submits a
`dry_run_plan_id`, not merely a session id (§20 updated accordingly).

### 14.9 Plan-artifact retention — closing the gap the two new tables introduce (fix round 3, H9)

**Fix-round-3 finding: §6.6 integrates blob retention into PR19A's
existing `redact_session` transaction, and PR19A's own existing fields
are already redacted by that same transaction (§3.6) — but the two new
tables this section introduces (§14.2) are not covered by either. Their
row-level content can retain real legacy identifiers/content
indefinitely, defeating the stated 180-day retention/privacy boundary.**
Specifically: `normalized_values`, `matched_identity_fields`, and
`warnings` (all `JSONB`, §14.2) can contain the same category of
raw-legacy-cell content as the columns §3.6/§6.6 already redact.

**Resolution — extend the same claimed/fenced retention transaction one
more time, not a third retention mechanism**: `redact_session`'s existing
transaction (already extended once by §6.6 for the source blob) gains one
more step, scoped to sessions with `dataset_type="equipment_master"` that
have persisted plan rows:

- **What is redacted, not deleted**: `equipment_master_dry_run_plan_rows`
  rows belonging to *any* plan (`active`, `superseded`, `consumed`, or
  `failed`) for the session being redacted have their
  `normalized_values`/`matched_identity_fields`/`warnings` columns set to
  `NULL` (or an empty JSON object, whichever this codebase's existing
  redaction convention for JSONB columns already uses — confirmed at
  implementation time). **What is explicitly preserved** (structural, not
  PII, exactly matching §6.6's precedent for `import_sources.checksum`/
  `byte_size`): `id`, `dry_run_plan_id`, `source_row_number`, `action`,
  `target_equipment_id`, `expected_concurrency_token`. This keeps the
  plan's row *shape* (how many creates/updates/skips, which target
  Equipment rows were touched) queryable for historical/audit purposes
  after purge, exactly as session-level counts remain queryable today,
  while removing every field capable of holding raw legacy content.
- **Plan-header summary fields are not PII** (`summary_total_rows`/
  `summary_creates`/etc., §14.2) and are left untouched, matching the
  existing precedent that structural counts survive redaction.
- **Same transaction, same claim**: this redaction runs inside the
  identical `SELECT ... FOR UPDATE SKIP LOCKED`-claimed transaction as
  the rest of `redact_session` (§3.6) and the blob deletion (§6.6) — a
  forced failure anywhere in that transaction leaves plan-row redaction,
  blob deletion, and session-metadata redaction **all** un-applied
  together, and a later cleanup run retries all three via the existing,
  unmodified claim mechanism. No new retry/tombstone machinery is
  introduced, for the same reason §6.6 already gives for the blob.
- **Ownership**: since the two plan tables are themselves a PR20C
  artifact (§14.2, §24 — they do not exist until PR20C's migration
  lands), this retention extension is PR20C's responsibility, not
  PR20A's, even though it composes onto the same transaction §6.6
  (PR20A) already extended once. PR20C's implementation PR must not
  merge without this redaction step, exactly as PR20A's must not merge
  without §6.6's blob deletion.
- **Required test coverage (§22)**: a forced-failure test proving
  plan-row redaction, blob deletion, and session redaction commit or roll
  back together, never partially; a test proving redacted plan rows
  retain their structural fields (action/target/token/row-number) but not
  their content fields; a test proving retention correctly walks *every*
  status value (`active`/`superseded`/`consumed`/`failed`), not only
  `consumed` plans, since a session can be redacted regardless of which
  plans it accumulated along the way.

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

### 15.1 Update-mode optimistic concurrency (conditional on §9 OD-2) — rewritten, fix round 2, H5R

**Fix-round-2 correction: the prior revision described the concurrency
token as captured "at `plan_dry_run` time... and, transitively, whenever
`execute` re-derives the same plan" — i.e. re-read at execute time too.
That is exactly wrong and defeats the purpose of the check: if `execute`
re-reads `updated_at` fresh, it always matches whatever the row currently
is, so a change made after dry-run and before execute can never be
detected.** The correct temporal contract, matching §14's persisted-plan
architecture exactly:

```
DRY-RUN
  |
  v
read Equipment
  |
  v
capture concurrency token T1
  |
  v
persist T1 in the DryRunPlan row (equipment_master_dry_run_plan_rows
  .expected_concurrency_token, §14.2) -- NEVER re-read at execute time
  |
  v
user reviews the persisted plan (§14.4/§14.6)
  |
  v
[another actor may modify the Equipment record here -> T2 != T1]
  |
  v
EXECUTE (by confirmed plan id, §14.4)
  |
  v
UPDATE ... WHERE id = :equipment_id AND updated_at = :T1   (never :T2, never re-read)
  |
  v
if current token != T1 (zero rows affected): STALE PLAN / CONFLICT
```

**If OD-2 authorizes update mode, this contract is mandatory. If OD-2
resolves to create-only, this entire subsection is moot** — a create
either succeeds via the database's own unique constraints or fails with a
duplicate-identifier `IntegrityError`, already covered by §16; there is no
existing row whose freshness needs protecting.

**The problem, confirmed rather than assumed**: the existing unique
constraints on `bcm_code`/`item_no`/`serial_number` (§4.1) protect against
two *creates* colliding on the same identifier — they do **not** protect
an *update* from silently overwriting a change made to the target
Equipment record after the matching/dry-run snapshot was taken. A planned
update computed during `plan_dry_run` (§14) and later applied during
`execute` could clobber an edit made by an Administrator, or by a
different import session, in the window between the two — a classic lost-
update race, and unique constraints are structurally the wrong tool for
it (they guard *identifier* collisions, not *staleness*).

**Existing concurrency token evaluated**: `Equipment` has no dedicated
integer `version` counter (unlike `ImportSession.version`, §3.1). It does
have `updated_at` (`TimestampMixin`, `UTCDateTime`,
`onupdate=func.now()`, server-computed on every UPDATE) — confirmed by
reading `backend/app/models/mixins.py` directly. This design proposes
reusing `updated_at` as the optimistic-concurrency token, **without a
schema change**, rather than adding a new `version` column:

- **Captured exactly once, at `plan_dry_run` time, and nowhere else.**
  For every row resolved to an *update* action, the adapter reads
  `matched_equipment.updated_at` and writes it into
  `expected_concurrency_token` on that row's `persist_dry_run_plan`
  write (§14.2, §14.3) — this is `T1` in the diagram above, and it is
  the **only** place this value is ever captured. `plan_dry_run` never
  runs again for an already-confirmed plan; there is no "re-derive" step
  left in this architecture for `execute` to perform (§14.4 replaced
  that with "load the persisted plan").
- At `execute` time, the adapter applies each planned update via a
  compare-and-swap predicate using **the row's own persisted token**,
  never a freshly-read one:
  ```sql
  UPDATE equipment
  SET ...
  WHERE id = :target_equipment_id AND updated_at = :expected_concurrency_token
  ```
  (the actual implementation may express this as an ORM-level
  `session.execute(update(...).where(...))` with a rowcount check, rather
  than raw SQL — the predicate shape is what matters, not the exact API
  used to issue it). `:expected_concurrency_token` comes from
  `equipment_master_dry_run_plan_rows`, loaded alongside the rest of the
  confirmed plan (§14.4) — `execute()` never issues a fresh `SELECT
  ... updated_at` on the target row before this UPDATE; doing so would
  silently reintroduce the exact bug this fix round closes.
- **Zero rows affected means a conflict, not a no-op.** The adapter must
  check the affected-row count after issuing the update and treat zero as
  a genuine staleness conflict, never silently proceed as if nothing
  needed to change, never silently refresh the token and retry, and never
  overwrite newer data by relaxing the predicate.
- **CREATE-row concurrency, defined explicitly**: if another actor
  creates a conflicting BCM/Item No after the plan was confirmed (a
  planned CREATE now collides), the database's own unique constraints
  remain the final integrity enforcement (§16, unchanged) — the resulting
  `IntegrityError` is treated identically to any other execution
  conflict, below.
- **On conflict**: consistent with §15's all-or-nothing execute-attempt
  guarantee, a detected staleness conflict on *any* row causes the
  adapter's `execute()` to raise (surfacing as the existing framework's
  "genuine server error" treatment, mirroring `ImportExecutionFailedError`
  handling already established for other execute failures, §16) — the
  entire attempt rolls back via TX1, never partially applying the other,
  non-conflicting rows. This preserves the framework's existing atomicity
  guarantee cleanly rather than inventing new partial-success semantics.
  **Fix-round-3 correction (H6): this is a post-admission failure, which
  §14.4 now defines explicitly** — the session transitions to its
  terminal `failed` state (existing TX2 path, unchanged) and, under the
  merged state machine, cannot transition back to `dry_run_completed` or
  `validating`; the confirmed plan's own `status` is set to `'failed'` in
  the same transaction (§14.2). **There is no same-session "re-run
  dry-run/execute after resolving the discrepancy"** — the prior revision
  claimed this was possible, which contradicts the state machine's own
  terminal-failure semantics. An operator investigates the reported
  conflicting row(s) (identified in the bounded, generic failure message,
  per `bound_failure_message`'s existing discipline) and starts a **new**
  import session to retry, after resolving the discrepancy if it was a
  genuine data problem. A future revision could weaken this to a per-row
  skip-with-warning instead of a whole-attempt failure, but that is a
  distinct design choice this document does not make by default, since it
  changes execute's observable atomicity contract and should be reviewed
  explicitly if proposed.
- **Scenarios this covers, confirmed one by one**: (a) *manual Equipment
  edit after dry-run* — any `PATCH /equipment/{id}` bumps `updated_at`,
  caught. (b) *another import session updating the same Equipment* —
  same mechanism, whichever `execute` call reaches the row second observes
  a stale `expected_concurrency_token` and conflicts. (c) *identity field
  change on the existing record* — also bumps `updated_at`, caught by the
  same generic staleness check; no separate identity-specific mechanism is
  needed (and OD-2's own field-mutability rule should already forbid an
  *import-driven* update from touching identity fields in the first
  place, §9 OD-2). (d) *lifecycle/status change* — `change_status_for_*`
  functions persist through the normal ORM update path, which also bumps
  `updated_at` via the mixin, caught the same way. (e) *Equipment record
  deleted after dry-run* — the UPDATE's `WHERE id = :target_equipment_id`
  clause matches zero rows regardless of the token, correctly surfacing
  as the same conflict path (a soft-deleted row, per `SoftDeleteMixin`,
  still physically exists with a `deleted_at` set — its own `updated_at`
  bump from the delete itself is still caught by the token comparison
  before any lookup-scoping question even arises).
- **Concurrency token: finalized in this design, fix round 3 (M2)** — the
  prior revision left `updated_at` vs. a dedicated `Equipment.version`
  column as an open choice for the PR20C implementation PR to confirm.
  Independent review correctly identified this as schema/contract
  architecture belonging in the design itself, not an incidental
  implementation detail. **This design approves `updated_at` as the V1
  concurrency token, decided here, not deferred.** Rationale: this is a
  timestamp-equality CAS, not a strictly monotonic integer counter —
  `onupdate=func.now()` provides microsecond-resolution UTC timestamps in
  PostgreSQL, which is practically collision-safe for this use case (two
  genuinely distinct updates to the same row landing in the same
  microsecond is not a realistic operational scenario for this system's
  write volume), and it requires no new migration, reusing a column that
  already exists on every row. This is a weaker theoretical guarantee
  than a dedicated monotonic `version` column would provide, and that
  trade-off is made explicitly, not silently: if the Repository Owner or
  independent review later prefers the stronger guarantee, adding a
  `version` integer column to `Equipment` (mirroring
  `ImportSession.version` exactly) is a well-understood, self-contained
  follow-up migration — but it is not a prerequisite for PR20C to
  proceed, and this design does not gate PR20C on that choice being
  revisited. **Required test coverage (§22), now made a hard requirement
  rather than an aspiration**: a dedicated test enumerating every known
  Equipment write path reachable in this codebase today (`PATCH
  /equipment/{id}`, every `change_status_for_*` lifecycle-transition
  function, and this design's own `execute()` UPDATE path itself) and
  asserting each one actually advances `updated_at` — approving this
  token without that proof would be exactly the kind of unverified
  assumption this document otherwise commits to avoiding.

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
  deleted by unrelated activity before execute runs. For *create*-mode
  rows, this is the same class of risk PR12's own commit phase already
  accepts (its own design does not lock rows between preview and commit
  either), and is fully covered by the unique-constraint boundary above —
  PR20 inherits this accepted risk rather than introducing new locking
  machinery. For *update*-mode rows (if OD-2 authorizes update), this
  TOCTOU window is **not** merely accepted risk — §15.1's
  `updated_at`-based optimistic-concurrency check exists specifically to
  detect and reject a stale update rather than silently applying it,
  closing this gap for updates while deliberately leaving creates to the
  cheaper, already-sufficient unique-constraint boundary.

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
(not just the existing generic `FakeAdapter`-based PR19A tests);
**source metadata + blob atomicity** (a forced failure between the
metadata flush and the final commit leaves neither an `import_sources`
row nor an `import_source_blobs` row — proving the transaction contract
in §6.2 is real, not merely asserted); **upload retry/idempotency** (a
second identical upload does not create a duplicate blob row, §6.2);
**adapter invocation context** (a dedicated test proving
`get_adapter_invocation_context()` returns the correct session/source/
plan identity, **verified source content, and both job IDs** (fix round
3, H1R2/H4R2) inside `plan_dry_run`/`execute`, and that two concurrent
sessions' `asyncio` tasks never observe each other's context — including
the new content/job-ID fields, not only the original identity fields,
§6.4); **registration endpoint guard** (fix round 3, H2R2 — an
endpoint-level test proving `POST /{id}/source` rejects
`dataset_type="equipment_master"` with `409`/
`IMPORT_SOURCE_REGISTRATION_METHOD_NOT_ALLOWED` and performs zero
database writes, §6.2; a companion test proving every other
`dataset_type` reaches the existing handler body completely unaffected by
the guard);
**verified source reader** (§6.5 — dedicated tests for each row of the
failure-classification table: blob missing, checksum mismatch, length
mismatch, storage unavailable, corrupt `.xlsx`, resource limit exceeded,
each proven to produce the structural `validation_failed` crash-flavor
outcome, never a fabricated per-row finding); **persisted dry-run plan**
(§14: the plan a `GET /{id}/dry-run-plan` response describes exactly
matches what was persisted by `persist_dry_run_plan`, not a live
recomputation; the plan is immutable — no code path ever mutates an
existing plan row; a second `POST /{id}/dry-run` creates a genuinely new
plan and marks the prior one `superseded`, never overwriting it); **two-
layer execution admission** (fix round 3, H6/H7, §14.4: five separate
Layer-1 pre-admission rejection tests — missing `dry_run_plan_id` for
`equipment_master` specifically, with a companion test proving the field
being absent has zero effect on any other `dataset_type`; wrong-session
plan id; source/checksum mismatch; validation-snapshot mismatch;
non-`active` status — each proven to leave the session's own state, CAS
`version`, and `import_jobs` completely untouched, and immediately
retryable on the same session with a fresh `POST {id}/dry-run`; a Layer-2
test proving a dry-run that supersedes the confirmed plan *during* the
admission race is caught by the locked re-check even though Layer 1 had
already accepted it);
**optimistic-concurrency conflict detection** (§15.1, conditional on
OD-2 authorizing update mode: a genuine two-connection PostgreSQL test
proving a manual `PATCH /equipment/{id}` issued *between* dry-run and
execute causes the affected row's update to be detected as
zero-rows-affected using the *persisted* token — explicitly asserting
`execute()` never issues its own fresh `SELECT ... updated_at` before the
CAS UPDATE — and that the whole execute attempt then rolls back per §15's
atomicity guarantee rather than partially applying other rows; a
companion test for a record **deleted** after dry-run, §15.1 scenario
(e); a companion test for a **new** BCM/Item No collision introduced
after dry-run for a planned CREATE row, surfaced via the existing
`IntegrityError` path, §16); **post-admission failure lifecycle** (fix
round 3, H6, §14.4: a test proving that any of the conflicts above
(concurrency-token mismatch, deleted record, CREATE collision, or a
Layer-2 re-check failure) drives the session to terminal `failed` *and*
the confirmed plan to `status='failed'` in the same transaction; a test
proving `POST {id}/dry-run` on a `failed` session is rejected by the
existing, unchanged session-state check — i.e. there is **no**
same-session retry after a post-admission conflict, only a fresh
`ImportSession`; contrasted explicitly against the Layer-1 tests above,
where the session is never touched at all); and a **stale-worker** test
proving a delayed/retried execute attempt against a plan already
`consumed` by an earlier, successful execute is rejected idempotently
rather than double-applying, reusing PR19A's existing state-based execute
idempotency, §3.5).

**Source blob retention** (§6.6): a forced failure mid-retention-cleanup
transaction leaves both the metadata redaction and the blob deletion
un-applied together (proving the same-transaction claim, not merely
asserting it); a second cleanup run successfully claims and completes a
previously-interrupted session, including its blob, via the existing
claim/retry mechanism (no new retry code to test, but the *composition*
with blob deletion must be proven); concurrent cleanup-claim tests
(existing PR19A pattern, extended to confirm the blob is only ever
deleted by the winning claimant); a test confirming session/finding
metadata (excluding the purged blob) remains queryable after purge; a
test confirming that any attempt to read the source (via the verified
source reader, §6.5) after its blob has been purged fails cleanly with
the existing "source unavailable" classification rather than a raw
lookup error, since a purged session should never reach `parse()` again
in practice but the failure mode must still be defined and tested.

**Migration**: only if §6.2's byte-storage proposal is adopted — a new
migration for `import_source_blobs` (or equivalent), following this
repository's established `_verify_schema_convergence()` fail-closed
discipline (§3.1) and upgrade/downgrade/re-upgrade PostgreSQL test pattern
already used for every prior migration in this codebase. **The same
discipline applies, in full, to §14.2's two persisted-plan tables** (fix
round 3, H8) — the migration is not complete without a dedicated test
proving each physical constraint actually rejects the row it names:
cross-session job-ID binding (both the `accepted_validation_job_id` and
`dry_run_job_id` composite FKs), a second concurrent `active` plan for the
same session (the partial unique index), a duplicate `source_row_number`
within one plan, a negative summary count, a CREATE/SKIP row carrying a
non-null `target_equipment_id`/`expected_concurrency_token`, and an
UPDATE row missing either — plus the standard fresh-install and
historical-upgrade convergence tests.

**Equipment concurrency-token finalization** (§15.1, fix round 3, M2): a
dedicated test enumerating every known Equipment write path in this
codebase — `PATCH /equipment/{id}`, every `change_status_for_*`
lifecycle-transition function, and this design's own `execute()` UPDATE
path — and asserting each one actually advances `updated_at`, since the
approved V1 CAS token's correctness depends on that being true for every
reachable write path, not merely the ones exercised elsewhere in this
plan.

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
- Modify PR19A's session/job/lease/fencing/recovery/retention
  *mechanisms* (the state machine, the CAS admission logic, the lease/
  heartbeat/fencing algorithm, the `SELECT ... FOR UPDATE SKIP LOCKED`
  claim scheme, or the retention *policy* itself — window, eligibility,
  redaction semantics). This does not prohibit the one explicitly-scoped
  extension this design itself makes: adding a single same-transaction
  `DELETE FROM import_source_blobs` statement inside the existing,
  unmodified `redact_session` transaction (§6.6, H3R) — the mechanism,
  claim scheme, and policy are reused verbatim; only one additional
  statement is added to the transaction body to cover the new table PR20
  introduces.
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
directionally correct but must be adjusted twice over: once for the
file-ingestion gap (§6.2), and again for this fix round's finding that
"PR20A can start now" was too casual a claim — some of what §6.2/§6.4
require turned out to depend on a real, previously-undesigned transaction
contract and an adapter-context mechanism, not merely "an upload
endpoint." **Revised proposal, with each slice's readiness stated
explicitly rather than assumed:**

- **PR20A — Source ingestion, transaction contract, verified source
  reader, retention integration, and adapter invocation context.**
  **READY** — not blocked by OD-1/OD-2/OD-3 (all three are
  business-policy questions; everything in this slice is a resolved
  technical design, §6.2/§6.4/§6.5/§6.6), but only after this design's
  H1R/H2R/H3R resolutions above are themselves independently reviewed and
  approved (design review is an ordinary prerequisite for any
  implementation PR in this codebase, not a special gate unique to
  PR20A). Per this fix round's H3R finding, PR20A's scope is expanded to
  include **every** technical prerequisite for safe source registration,
  access, and disposal — not merely storage and upload. Concrete scope:
  - the `import_source_blobs` table + migration (§6.2), 1:1 FK to
    `import_sources`;
  - the single authoritative, server-checksummed registration operation
    and its failure/retry matrix (§6.2) — the client never supplies or
    confirms a checksum;
  - the additive, non-committing CRUD variant of
    `register_or_correct_source` used inside that operation (§6.2);
  - the new upload endpoint and its transactional-finalize contract
    (§6.2);
  - the `ImportSourceReader`/`SourceDescriptor`/`VerifiedSourceContent`
    component (§6.5) — blob-load, bound-check, checksum-recompute, and
    length-verify at read time, called by the framework before
    `adapter.parse()`, with its failure-classification table routing
    every failure through the existing PR19A TX1/TX2 crash path;
  - source blob retention integrated into PR19A's existing
    `redact_session` transaction (§6.6) — one additional same-transaction
    `DELETE`, not a second retention mechanism;
  - the `AdapterInvocationContext` contextvar mechanism added to
    `import_validation_service.py`/`import_execution_service.py` (§6.4,
    including its `dry_run_plan_id` field) — additive, does not change
    any existing function's signature or observable behavior for any
    adapter that doesn't use it.

  **No Equipment-domain write path is introduced by this slice** — it
  stores bytes, verifies them at read time, retires them on schedule, and
  threads context; nothing more. **API exposure**: one new endpoint
  (`POST /import-sessions/{id}/source/upload`), Administrator-only, no
  Equipment data reachable through it yet (no adapter is registered until
  PR20B). **Schema/migration impact**: yes, one new additive table
  (`import_source_blobs`), no modification to any existing table.
  **Deployable independently**: yes — with no adapter registered for
  `equipment_master`, uploading a source is possible but validating it
  still returns `422 IMPORT_ADAPTER_NOT_REGISTERED` exactly as it does for
  every other still-unimplemented dataset type today, so this slice alone
  exposes no reachable Equipment-domain behavior, safe or unsafe. This
  design does not state PR20A READY on any narrower scope than the bullet
  list above — if independent review identifies a further undefined
  technical prerequisite, PR20A's scope must expand again (or split
  further) rather than being declared ready with a gap.
- **PR20B — Equipment Master parser, normalization, and validation
  adapter**: `EquipmentMasterAdapter.parse`/`preload_business_context`/
  `validate_business_rules`, plus `register_adapter(EquipmentMasterAdapter())`
  (§6.1, §6.3). **NOT READY — blocked on OD-1/OD-2/OD-3** (field mapping,
  create/update policy, and identity-conflict policy are all read inside
  `validate_business_rules`, §6.3). Depends on PR20A (needs the verified
  source reader, blob storage, and context mechanism to have real,
  checked bytes and identity to parse against — `parse()` receives a
  `VerifiedSourceContent`, never a raw/unverified source, §6.5). **API
  exposure**: `POST /{id}/validate` becomes live for
  `dataset_type=equipment_master` once this slice registers the adapter;
  `plan_dry_run`/`execute` remain `NotImplementedError` per the base
  `ImportAdapter` contract's own default until PR20C lands — matching
  PR19A2's own precedent of shipping `validate` safely ahead of
  `dry_run`/`execute`. **Schema/migration impact**: none. **Owner
  Decision required**: yes, OD-1/OD-2/OD-3, before this slice's own
  implementation PR can begin (not merely before it merges).
- **PR20C — Dry-run and execution integration**: `plan_dry_run`/
  `persist_dry_run_plan`/`execute` (§6.3), the two new persisted-plan
  tables and their full physical constraint set (`equipment_master_dry_run_plans`/
  `equipment_master_dry_run_plan_rows`, including the H8 composite FKs,
  partial unique index, and CHECK constraints, §14.2) and their migration,
  the two-layer pre-admission/post-admission execution contract (§14.4,
  H6/H7 — the optional-at-the-generic-route `dry_run_plan_id` field, the
  Layer-1 framework-owned pre-admission validation, and the Layer-2
  locked post-admission re-check) and the `GET /{id}/dry-run-plan`
  retrieval endpoint (§14.6), the plan-artifact retention integration
  (§6.6/§14.9, H9 — redacting `normalized_values`/`matched_identity_fields`/
  `warnings` in the same claimed/fenced retention transaction that already
  redacts session metadata and deletes the source blob), and the
  optimistic-concurrency execute path reading its token from the
  persisted plan row rather than a fresh read, using the `updated_at`
  token this design now finalizes (§15.1, M2 — conditional on OD-2 for
  whether update mode is authorized at all, not for which token
  mechanism to use, which is no longer an open question). **NOT READY —
  blocked on OD-1/OD-2/OD-3** (inherits PR20B's blockers; §15.1's
  concurrency mechanism itself is technically ready but has nothing to
  protect until OD-2 authorizes update mode). Depends on PR20B (execute
  *loads and applies* the confirmed persisted plan produced by PR20B's
  `validate_business_rules`/`plan_dry_run` pipeline — it never re-derives
  or recomputes that plan, §14.1). **API exposure**: `POST
  /{id}/dry-run`, `GET /{id}/dry-run-plan`, `POST /{id}/execute`
  (`dry_run_plan_id` required for this dataset type only, §14.4) become
  live for this dataset type; there is no `dry-run-summary` recompute
  endpoint. **Schema/migration impact**: yes — the two new persisted-plan
  tables with their full constraint set (§14.2), in addition to whatever
  PR20A already added; the `updated_at`-based CAS token requires no
  further migration, per §15.1's finalized decision.
- **PR20D — Frontend real-API wiring**: replaces the Equipment Master
  `MockImportClient` path only (§20). **Depends on PR20A+PR20B+PR20C's
  API contract being stable enough to integrate against** — likely
  sequenced after PR20C, or in parallel against a contract-frozen API
  surface if the team prefers (an implementation-sequencing choice, not a
  design question). Not blocked by OD-1/OD-2/OD-3 directly, but has
  nothing real to wire against until PR20C lands.
- **PR20E — Governance sync**: records PR20's actual merged scope,
  following this repository's established post-merge documentation-sync
  pattern (as this document's own predecessor, the PR19B governance sync,
  did) — not performed by this Design PR itself (§25).

**Summary — which slice can start now, which is blocked, and by what:**

| Slice | Owner-Decision-blocked? | Depends on | Ready now? |
|---|---|---|---|
| PR20A | No | This design's own review/approval | **Yes** |
| PR20B | Yes — OD-1, OD-2, OD-3 | PR20A | No |
| PR20C | Yes — OD-1, OD-2, OD-3 (and OD-2 specifically for §15.1) | PR20B | No |
| PR20D | No (indirectly gated by having something real to integrate) | PR20C | No |
| PR20E | No | All of the above merged | No |

No slice exposes a production endpoint before its required safety/storage
contract exists: PR20A's own new endpoint reaches no Equipment data;
PR20B's `validate` reaches only findings, never a write; `dry_run`/
`execute` remain unreachable (`NotImplementedError`) until PR20C, which
itself cannot be implemented before OD-1/OD-2/OD-3 resolve.

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
- [x] **Fix round 1**: defined an explicit, immutable adapter-invocation
      context contract for `plan_dry_run`/`execute`, after confirming by
      reading the actual call sites that no session/source identity is
      passed to either (§6.4).
- [x] **Fix round 1**: defined an explicit transaction-ownership contract
      for source metadata + blob persistence, after confirming by reading
      the actual CRUD code that it commits internally and cannot be
      composed naively (§6.2).
- [x] **Fix round 1**: corrected PR20A's readiness claim to state its
      actual, larger scope (ingestion + transaction contract + adapter
      context) while confirming it remains not gated by OD-1/OD-2/OD-3
      (§24), and made every other slice's readiness/blocking status
      explicit rather than assumed.
- [x] **Fix round 1**: defined an explicit dry-run summary persistence/API
      contract (deterministic recompute, not new persisted state) after
      confirming the merged framework otherwise discards `DryRunPlan`'s
      content (§14).
- [x] **Fix round 1**: defined an explicit optimistic-concurrency contract
      for update-mode execution, conditional on OD-2, using the existing
      `updated_at` column as a CAS token without a schema change (§15.1).
- [x] **Fix round 1**: corrected the numeric-Excel-identifier wording to
      state plainly that leading zeros are not recoverable once a cell is
      numeric-typed, rather than implying "read as text" fixes it (§7).
- [x] **Fix round 1**: corrected the `register_adapter()` pseudocode call
      and every adapter method signature to match the actual merged
      `ImportAdapter` ABC exactly (§6.3).
- [x] **Fix round 2 (H1R)**: defined a verified-source-reader contract
      (`ImportSourceReader`/`SourceDescriptor`/`VerifiedSourceContent`)
      that loads, bound-checks, checksum-recomputes, and length-verifies
      source bytes before `adapter.parse()` is ever called, replacing any
      implicit `parse(None)`/unverified-content path, with a full
      failure-classification table routing every failure through the
      existing PR19A TX1/TX2 crash path (§6.5).
- [x] **Fix round 2 (H2R)**: replaced the two-path registration model with
      a single authoritative, server-checksummed registration operation;
      the client is never authoritative for checksum, byte length, or
      storage key; the existing metadata-only `POST /{id}/source` path is
      explicitly a client error for `dataset_type="equipment_master"`;
      defined the explicit failure/retry matrix (§6.2).
- [x] **Fix round 2 (H3R)**: integrated source blob retention into PR19A's
      existing retention policy/transaction rather than a second
      mechanism (§6.6), and expanded PR20A's scope to include every
      technical prerequisite for safe registration/access/retention
      (verified source reader, retention integration, adapter context) —
      PR20A is not stated READY while any technical prerequisite remains
      undefined (§24).
- [x] **Fix round 2 (H4R)**: reversed fix round 1's live-recompute
      resolution; the dry-run plan is now a persisted, immutable artifact
      (two new tables, §14.2) confirmed by `dry_run_plan_id`, never
      recomputed at confirmation or execution time (§14).
- [x] **Fix round 2 (H5R)**: reversed fix round 1's execute-time-refresh
      bug; the Equipment concurrency token is captured exactly once, at
      dry-run time, persisted per row in the plan, and read — never
      freshly re-read — at execute time, with an explicit in-text warning
      against reintroducing a fresh `SELECT ... updated_at` at execute
      time (§15.1).
- [x] **Fix round 2 (L1R)**: swept the entire document for
      `register_adapter` occurrences (not only the previously-cited
      line); all 7 occurrences now match the real, single-argument
      merged signature (§6.1, §6.3, verified via full-document grep).
- [x] **Fix round 2**: performed a full-state consistency sweep of the
      entire document for stale `parse(None)`, metadata-only-registration,
      client-authoritative-checksum, live-recompute, "latest plan",
      execute-time-refreshed-token, and retention-ownership language;
      corrected §23's retention non-goal to explicitly reconcile with
      §6.6's additive extension, and corrected §24's PR20A/PR20C scope and
      dependency wording to match the persisted-plan architecture (§20,
      §23, §24).
- [x] **Fix round 2**: did not close OD-1/OD-2/OD-3 — no repository
      evidence for the real source schema or either business policy has
      appeared since fix round 1; all three remain OPEN (§9).
- [x] **Fix round 2**: did not start PR20A or any implementation PR; this
      remains a design-only document (§26).
- [x] **Fix round 3 (H1R2)**: defined how `plan_dry_run` obtains the same
      verified source content `parse()` already receives — threaded
      through `AdapterInvocationContext.verified_source_content`, set by
      the framework's own call to `ImportSourceReader.open_verified`
      before `plan_dry_run`, never by the adapter calling the reader
      itself (§6.4, §6.5).
- [x] **Fix round 3 (H2R2)**: specified the actual code change that
      enforces "metadata-only registration is a client error" — a guard
      added to the existing `POST /{id}/source` handler, before any CRUD
      call, with a stable error code and a zero-database-write proof
      (§6.2).
- [x] **Fix round 3 (H4R2)**: defined how the persisted plan header
      populates its two job-identity columns — threaded through two new
      `AdapterInvocationContext` fields
      (`dry_run_job_id`/`accepted_validation_job_id`), populated by the
      framework from values it already holds, never queried for "the
      latest" of either (§6.4, §14.2).
- [x] **Fix round 3 (H6)**: corrected the execution admission/failure
      ordering to match the actual merged state machine — split into a
      framework-owned, no-mutation Layer-1 pre-admission check and a
      locked Layer-2 post-admission re-check; defined the terminal
      post-admission failure lifecycle explicitly (session `failed`, plan
      `failed`, no same-session retry) (§14.4, §15.1).
- [x] **Fix round 3 (H7)**: made `dry_run_plan_id` optional at the shared
      generic `execute` route and required only for `equipment_master`,
      preserving the reused PR19A API contract for every other dataset
      type (§14.4).
- [x] **Fix round 3 (H8)**: completed the persisted-plan tables' physical
      integrity contract — composite ownership FKs for both job-identity
      columns, a partial unique index for one active plan per session,
      row uniqueness, non-negative summary checks, and action-shape
      nullability CHECKs (§14.2).
- [x] **Fix round 3 (H9)**: extended plan-artifact retention into the same
      claimed/fenced transaction that already redacts session metadata
      and deletes the source blob, closing the gap where the two new
      tables' JSONB content could survive the 180-day purge indefinitely
      (§14.9).
- [x] **Fix round 3 (M2)**: finalized the Equipment concurrency-token
      choice as `updated_at` in this design, rather than deferring it to
      the PR20C implementation PR, with a required test proving every
      known Equipment write path advances it (§15.1).
- [x] **Fix round 3**: did not close OD-1/OD-2/OD-3 — no repository
      evidence for the real source schema or either business policy has
      appeared since fix round 2; all three remain OPEN (§9).
- [x] **Fix round 3**: did not start PR20A or any implementation PR; this
      remains a design-only document (§26).
