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
and calls `register_adapter("equipment_master", EquipmentMasterAdapter())`
at application startup (module import time, alongside existing router
registration in `app/main.py` or an equivalent startup hook — exact wiring
point is an implementation detail for the implementation PR, not a design
question). `dataset_type="equipment_master"` becomes the value clients
must pass to `POST /import-sessions {"dataset_type": "equipment_master"}`.
This is the only change to session-creation behavior; no new endpoint is
needed for this step.

### 6.2 File ingestion — the gap PR19A left open, and its transaction contract

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
  bytes durably, and (c) registers the source's metadata — all as **one
  atomic unit** (see the transaction contract below). The existing `POST
  /{id}/source` endpoint remains usable for future adapters that resolve
  their own checksum out-of-band; PR20 does not remove or modify it.
- **Byte storage location**: proposed default is the same PostgreSQL
  database — a new, narrowly-scoped table, `import_source_blobs
  (import_source_id UUID PK, FK import_sources.id ON DELETE RESTRICT,
  content BYTEA NOT NULL)`, 1:1 with `import_sources` — bounded by the same
  `MAX_UPLOAD_BYTES` ceiling as PR12 (10 MiB). This choice is **deliberate
  and load-bearing for the atomicity contract below**: because the blob
  lives in the same PostgreSQL database as `import_sources`, a genuine,
  single-database-transaction ACID guarantee is achievable for free,
  without a saga or two-phase-commit protocol. A dedicated object-storage
  integration is not justified for V1 at this size ceiling, and none
  exists in this codebase to build on; if a future revision moves byte
  storage to an external system, the atomicity contract below no longer
  applies and must be redesigned around a durable-write-then-orphan-cleanup
  pattern instead (not needed for the V1 architecture proposed here).
- **Retention obligation this reintroduces**: PR19A's design doc explicitly
  warns that a future byte-storing slice "must, as a required acceptance
  criterion of its own design," drive `source_bytes_deleted_at` from a
  genuine, independently-retried deletion attempt, not set it eagerly in
  the same code path as the rest of retention redaction. PR20's retention
  extension must therefore add its own bounded retry/outbox mechanism for
  blob deletion, verified by a dedicated PostgreSQL test proving a blob
  actually disappears (not merely that a timestamp column is set).

**Transaction-ownership contract (resolves the finding that the existing
CRUD layer commits internally and therefore cannot be composed naively):**
`app.crud.import_session.register_or_correct_source` and
`cancel_session` both call `await db.commit()` internally (confirmed by
reading the actual merged code, not assumed). Calling that function and
then separately adding a blob row afterward would **not** be atomic — the
metadata commit would already have closed the transaction before the blob
write ever happened, so a crash between the two leaves an orphaned,
sourceless blob or a source with no blob. The correct contract, using the
review's own requested language, is **"transactional DB finalize" with no
external orphan-cleanup step needed** (not "true cross-system atomic
DB+blob," which V1's architecture does not need to claim, and would not
be true if it did):

1. **Who begins the transaction:** implicit — this codebase's existing
   convention (every endpoint receives one request-scoped `AsyncSession`
   via dependency injection; no manual `BEGIN`).
2. **Ordering:** (a) validate the uploaded bytes' structural/security
   bounds in memory, no DB writes yet (§21); (b) compute the checksum and
   byte_size server-side from the actual received bytes; (c) call a new,
   **additive, non-committing** CRUD entry point —
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
5. **Checksum verification:** trivially satisfied — the checksum persisted
   in step 2(c) is computed directly from the same bytes persisted in step
   2(d), in the same request, closing PR19A's documented trust-boundary
   gap without a separate "verify after the fact" step.
6. **Orphan blob cleanup:** **not needed for this V1 architecture.**
   Because both writes share one physical transaction, no state exists
   where a blob persists without its owning source row, or vice versa.
   This is explicitly a consequence of choosing same-database BYTEA
   storage (above) rather than external object storage; it is not a
   general property of file-upload systems.
7. **Storage failure before metadata finalize / database failure after
   blob write:** both are the same case under this architecture (there is
   only one storage system) — an uncommitted transaction is discarded
   wholesale by the database itself on any failure before step 2(e); no
   PR20-specific handling is required beyond normal database
   crash-recovery, which this codebase already relies on everywhere else.
8. **Retry/idempotency:** a client retry (e.g. after a dropped response
   but a server-side commit that actually succeeded) is handled by the
   same "register-or-correct" semantics `register_or_correct_source`
   already provides for metadata, extended to the blob row via the upsert
   write in step 2(d) — a second identical upload does not create a
   second blob row.

This subsection is **proposed architecture, not a finalized decision** —
it is included so the implementation PRs (§24) have a concrete starting
point for independent review, and so the Owner Decisions in §9 can be
evaluated against a realistic ingestion mechanism rather than an abstract
one. Independent review of the implementation PR that adds this endpoint
must re-validate the bounds, the non-committing CRUD variant's exact
signature, and the blob-retention design before merge.

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

    def parse(self, raw_input: Any) -> list[RawImportRecord]:
        # `raw_input` is the `SourceContentRef` the framework resolves
        # from durable blob storage and passes in (§6.2, §6.4) — never
        # None for this adapter, unlike the PR19A-era default. Opens the
        # workbook via openpyxl (reusing PR12's parsing discipline: header
        # detection, blank-row skip, bounded rows/worksheets/headers),
        # yields one RawImportRecord per data row, 1-based row_number
        # matching the source file. Exact column names: BLOCKED on §9
        # OD-1.
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
        # Re-derives the exact same parse -> preload_business_context ->
        # validate_business_rules pipeline against the same frozen source
        # bytes and the same ruleset_version (deterministic replay, not a
        # second independent implementation), then re-resolves each
        # planned create/update against the *current* database state via
        # `context` — producing counts only (§14). Never writes.
        ...

    async def execute(self, db: AsyncSession) -> int:
        # `db` is the caller's normal read-write session, inside TX1
        # (§3.5, §15) — never commits/rolls back itself. Session/source
        # identity via the same contextvar (§6.4). Re-derives the plan
        # exactly as plan_dry_run does, then applies it: for update-mode
        # rows, using the optimistic-concurrency predicate (§15.1); for
        # create-mode rows (once authorized, §9 OD-2), a plain insert
        # guarded by the existing unique constraints (§16). Returns
        # imported_rows count. Exact write behavior: BLOCKED on §9
        # OD-1/OD-2.
        ...


register_adapter(EquipmentMasterAdapter())
```

Note the corrected registration call: the real `register_adapter(adapter:
ImportAdapter) -> None` takes only the adapter instance — it reads
`adapter.dataset_type` itself — not a separate `dataset_type` argument.

This shape is implementation-grade for every part not gated by an Owner
Decision: the adapter's *structure*, its integration points with PR19A's
lease/fencing/dry-run/execute mechanics, its invocation-context contract
(§6.4), and its reuse of `preload_business_context` for bulk lookups are
fully specified. Only the row-level *content* of
`validate_business_rules`/`execute` — which fields exist, how they map,
and what identity/create-update policy governs them — is blocked.

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
`EquipmentMasterAdapter.plan_dry_run`/`execute` call
`get_adapter_invocation_context()` internally to obtain
`import_source_id` (to load the frozen source's blob and checksum, §6.2)
and `ruleset_version` (to select the correct parsing/mapping logic if
more than one legacy source format is ever authorized, §9 OD-1) — never
`import_session_id` for any write purpose, since `execute()` never writes
to `import_sessions`/`import_jobs` itself (that remains the framework's
own responsibility, §3.3/§3.5); `import_session_id` is retained in the
context only for audit-logging purposes (§18).

This mechanism is **the only backend code this design proposes adding to
`import_execution_service.py`/`import_validation_service.py`** — it does
not change either function's own signature, return type, or any existing
behavior for a session with no adapter-side dependency on this context (a
future adapter that doesn't need session identity simply never calls
`get_adapter_invocation_context()`). It is a technical prerequisite, not
gated by OD-1/OD-2/OD-3, and belongs in PR20A (§24).

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

## 14. Dry-Run Contract — Persistence and API Path

Reuses PR19A's `DryRunPlan(summary: dict)` shape and read-only enforcement
(§3.4, §6.3) directly — no new dry-run *mechanism*. But per the merged
`ImportAdapter.plan_dry_run` docstring itself: `DryRunPlan` is "the opaque
result of a read-only evaluation, computed entirely within
`plan_dry_run`'s read-only transaction, then discarded — never persisted
itself (only whether evaluation succeeded or raised feeds
`session.dry_run_completed_at`/`status`)." **This means the framework, as
merged, throws away the summary's actual content today** — no API
anywhere returns "N creates, M updates, K skipped" from a dry-run. This
must be resolved explicitly, not left implicit:

1. **Where is the summary persisted?** Nowhere new, by design. It is
   **not** added as new columns on `ImportSession` (which would be a
   schema change to an existing, frozen table beyond what this design
   proposes elsewhere) and **not** given a new dedicated result table.
   Instead, this design proposes the summary is **deterministically
   recomputed on demand**, matching the framework's own established
   philosophy for `ValidationFinding` retrieval (`GET
   /import-sessions/{id}/errors` already re-reads persisted findings
   rather than caching a summary elsewhere) and matching `DryRunPlan`'s
   own "computed, then discarded" contract exactly, rather than fighting
   it.
2. **Why recompute is safe and cheap**: given the same frozen source bytes
   (§6.2, immutable once registered) and the same `ruleset_version` (§6.4),
   `parse → preload_business_context → validate_business_rules` is a pure,
   deterministic pipeline (§6.3) — recomputing it costs one bounded pass
   over at most `MAX_IMPORT_ROWS=5000` rows plus the same two bulk lookup
   queries `preload_business_context` already performs, well within a
   normal request's latency budget.
3. **One deliberate consistency caveat, stated explicitly rather than
   hidden**: `preload_business_context`'s BCM/Item No lookup reflects the
   *current* database state at the moment it runs, not a state frozen at
   the original dry-run's `dry_run_completed_at` timestamp. A recomputed
   summary can therefore differ from what was true at the original
   dry-run if the underlying Equipment table changed in between (an
   Administrator edited a matched record, or another import session
   executed first). This is expected and intentional, not a bug to
   suppress — it is exactly why §15.1's optimistic-concurrency check
   exists at execute time regardless of what any dry-run summary claimed.
4. **API path**: a new, read-only endpoint,
   e.g. `GET /import-sessions/{id}/dry-run-summary`, Administrator-only
   (§17), valid only when `session.status` has reached at least
   `dry_run_completed` at some point (i.e. not for a session still in
   `validating`) — re-runs the adapter's `plan_dry_run` pipeline against a
   **fresh, genuinely read-only** transaction (the exact same `SET
   TRANSACTION READ ONLY` enforcement as the real dry-run attempt, §3.4)
   and returns its `summary` dict directly, rather than reading a stored
   value. This is additive (a new endpoint, not a change to any existing
   one) and requires no migration.
5. **Fields** (illustrative, not finalized until OD-1/OD-2/OD-3 resolve
   what is actually countable): `rows_considered`, `creates_planned` (0 if
   OD-2 resolves to update-only), `updates_planned` (0 if OD-2 resolves to
   create-only), `skipped_rows` (rows already correctly reflected, if that
   concept applies once OD-2 resolves), `warnings_count`,
   `blocking_conflicts_count`. Do not finalize this list until OD-1/OD-2/
   OD-3 make it meaningful — these are the *shape* to reuse, not a
   commitment to exactly these six fields.
6. **History**: not retained beyond what `import_row_errors` already
   retains per validation attempt (§3.1) — a dry-run summary is always
   "the current recomputation," never a historical snapshot list; if a
   future need for point-in-time dry-run history emerges, that is a
   separate design question, not solved here.
7. **Frontend consumption**: this mirrors the structure PR19B's frontend
   already expects from its `ImportResultSummary`-adjacent presentation
   work (nullable counts, never fabricated zeros) — PR20's backend summary
   shape should stay compatible with what PR19B already renders where
   reasonable, without PR20 being obligated to match it field-for-field
   (PR19B's own docs state its mock fixtures are presentation-only and do
   not bind PR20's real contract).

**Invariant this section exists to protect**: dry-run and execute must
operate from the same frozen source bytes and the same `ruleset_version`
(§6.4) — satisfied structurally, since both derive from the same
`AdapterInvocationContext.source_checksum`/`ruleset_version` and the same
immutable blob (§6.2). What is *not* frozen between them, by design, is
the live database state each recompute matches against — that gap is
exactly what §15.1's optimistic-concurrency contract closes at the one
point (execute) where it actually matters.

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

### 15.1 Update-mode optimistic concurrency (conditional on §9 OD-2)

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

- At `plan_dry_run` time (and, transitively, whenever `execute` re-derives
  the same plan, §14), for every row resolved to an *update* action, the
  adapter captures `expected_updated_at = matched_equipment.updated_at`
  as part of that row's working decision.
- At `execute` time, the adapter applies each planned update via a
  compare-and-swap predicate conceptually equivalent to:
  ```sql
  UPDATE equipment
  SET ...
  WHERE id = :id AND updated_at = :expected_updated_at
  ```
  (the actual implementation may express this as an ORM-level
  `session.execute(update(...).where(...))` with a rowcount check, rather
  than raw SQL — the predicate shape is what matters, not the exact API
  used to issue it).
- **Zero rows affected means a conflict, not a no-op.** The adapter must
  check the affected-row count after issuing the update and treat zero as
  a genuine staleness conflict, never silently proceed as if nothing
  needed to change.
- **On conflict**: consistent with §15's all-or-nothing execute-attempt
  guarantee, a detected staleness conflict on *any* row causes the
  adapter's `execute()` to raise (surfacing as the existing framework's
  "genuine server error" treatment, mirroring `ImportExecutionFailedError`
  handling already established for other execute failures, §16) — the
  entire attempt rolls back via TX1, never partially applying the other,
  non-conflicting rows. This preserves the framework's existing atomicity
  guarantee cleanly rather than inventing new partial-success semantics;
  an operator investigates the reported conflicting row(s) (identified in
  the bounded, generic failure message, per `bound_failure_message`'s
  existing discipline) and re-runs dry-run/execute after resolving the
  discrepancy. A future revision could weaken this to a per-row
  skip-with-warning instead of a whole-attempt failure, but that is a
  distinct design choice this document does not make by default, since it
  changes execute's observable atomicity contract and should be reviewed
  explicitly if proposed.
- **Scenarios this covers, confirmed one by one**: (a) *manual Equipment
  edit after dry-run* — any `PATCH /equipment/{id}` bumps `updated_at`,
  caught. (b) *another import session updating the same Equipment* —
  same mechanism, whichever `execute` call reaches the row second observes
  a stale `expected_updated_at` and conflicts. (c) *identity field change
  on the existing record* — also bumps `updated_at`, caught by the same
  generic staleness check; no separate identity-specific mechanism is
  needed (and OD-2's own field-mutability rule should already forbid an
  *import-driven* update from touching identity fields in the first
  place, §9 OD-2). (d) *lifecycle/status change* — `change_status_for_*`
  functions persist through the normal ORM update path, which also bumps
  `updated_at` via the mixin, caught the same way.
- **Caveat, stated honestly**: this is a timestamp-equality CAS, not a
  strictly monotonic integer counter. `onupdate=func.now()` provides
  microsecond-resolution UTC timestamps in PostgreSQL, which is
  practically collision-safe for this use case (two genuinely distinct
  updates to the same row landing in the same microsecond is not a
  realistic operational scenario for this system's write volume) — but it
  is a weaker theoretical guarantee than a dedicated monotonic `version`
  column would provide. If independent review prefers the stronger
  guarantee, adding a `version` integer column to `Equipment` (mirroring
  `ImportSession.version` exactly) is the alternative, at the cost of a
  new migration — this is a technical implementation choice for the
  PR20C implementation PR to confirm, not itself an Owner Decision.

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
second identical upload does not create a duplicate blob row, §6.2 step
8); **adapter invocation context** (a dedicated test proving
`get_adapter_invocation_context()` returns the correct session/source
identity inside `plan_dry_run`/`execute`, and that two concurrent
sessions' `asyncio` tasks never observe each other's context, §6.4);
**dry-run summary recompute** (the new `GET
/import-sessions/{id}/dry-run-summary` endpoint returns correct counts,
remains read-only under concurrent load, and reflects a changed database
state on a second call after an intervening Equipment edit, §14);
**optimistic-concurrency conflict detection** (§15.1, conditional on
OD-2 authorizing update mode: a genuine two-connection PostgreSQL test
proving a manual `PATCH /equipment/{id}` between dry-run and execute
causes the affected row's update to be detected as zero-rows-affected,
and that the whole execute attempt then rolls back per §15's atomicity
guarantee rather than partially applying other rows).

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
directionally correct but must be adjusted twice over: once for the
file-ingestion gap (§6.2), and again for this fix round's finding that
"PR20A can start now" was too casual a claim — some of what §6.2/§6.4
require turned out to depend on a real, previously-undesigned transaction
contract and an adapter-context mechanism, not merely "an upload
endpoint." **Revised proposal, with each slice's readiness stated
explicitly rather than assumed:**

- **PR20A — Source ingestion, transaction contract, and adapter
  invocation context.** **READY** — not blocked by OD-1/OD-2/OD-3 (all
  three are business-policy questions; everything in this slice is a
  resolved technical design, §6.2/§6.4), but only after this design's
  H1/H2 resolutions above are themselves independently reviewed and
  approved (design review is an ordinary prerequisite for any
  implementation PR in this codebase, not a special gate unique to
  PR20A). Concrete scope: the `import_source_blobs` table + migration
  (§6.2); the additive, non-committing CRUD variant of
  `register_or_correct_source` (§6.2); the new upload endpoint and its
  transactional-finalize contract (§6.2); the `AdapterInvocationContext`
  contextvar mechanism added to `import_validation_service.py`/
  `import_execution_service.py` (§6.4) — additive, does not change any
  existing function's signature or observable behavior for any adapter
  that doesn't use it. **No Equipment-domain write path is introduced by
  this slice** — it stores bytes and threads context, nothing more.
  **API exposure**: one new endpoint (`POST
  /import-sessions/{id}/source/upload`), Administrator-only, no
  Equipment data reachable through it yet (no adapter is registered until
  PR20B). **Schema/migration impact**: yes, one new additive table
  (`import_source_blobs`), no modification to any existing table.
  **Deployable independently**: yes — with no adapter registered for
  `equipment_master`, uploading a source is possible but validating it
  still returns `422 IMPORT_ADAPTER_NOT_REGISTERED` exactly as it does for
  every other still-unimplemented dataset type today, so this slice alone
  exposes no reachable Equipment-domain behavior, safe or unsafe.
- **PR20B — Equipment Master parser, normalization, and validation
  adapter**: `EquipmentMasterAdapter.parse`/`preload_business_context`/
  `validate_business_rules`, plus `register_adapter(EquipmentMasterAdapter())`
  (§6.1, §6.3). **NOT READY — blocked on OD-1/OD-2/OD-3** (field mapping,
  create/update policy, and identity-conflict policy are all read inside
  `validate_business_rules`, §6.3). Depends on PR20A (needs the blob
  storage and context mechanism to have real bytes/identity to parse
  against). **API exposure**: `POST /{id}/validate` becomes live for
  `dataset_type=equipment_master` once this slice registers the adapter;
  `plan_dry_run`/`execute` remain `NotImplementedError` per the base
  `ImportAdapter` contract's own default until PR20C lands — matching
  PR19A2's own precedent of shipping `validate` safely ahead of
  `dry_run`/`execute`. **Schema/migration impact**: none. **Owner
  Decision required**: yes, OD-1/OD-2/OD-3, before this slice's own
  implementation PR can begin (not merely before it merges).
- **PR20C — Dry-run and execution integration**: `plan_dry_run`/`execute`
  (§6.3), the dry-run summary recompute endpoint (§14), and the
  optimistic-concurrency update path (§15.1, conditional on OD-2).
  **NOT READY — blocked on OD-1/OD-2/OD-3** (inherits PR20B's blockers;
  §15.1's concurrency mechanism itself is technically ready but has
  nothing to protect until OD-2 authorizes update mode). Depends on
  PR20B (re-derives the same parse/validate pipeline, §14). **API
  exposure**: `POST /{id}/dry-run`, `POST /{id}/execute`, `GET
  /{id}/dry-run-summary` become live for this dataset type. **Schema/
  migration impact**: none beyond what PR20A already added, **unless**
  independent review of §15.1 prefers a dedicated `Equipment.version`
  column over the proposed `updated_at`-based CAS, in which case this
  slice would need its own small migration — a decision for PR20C's own
  implementation PR, not this design.
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
