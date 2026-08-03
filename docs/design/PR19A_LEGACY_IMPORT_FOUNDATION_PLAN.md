# Roadmap PR19A — Legacy Import Foundation: Design (Governance)

**Status:** Design only. No runtime code, migration, API, or test file is part of this PR. Nothing in this document has been implemented.
**Repository:** Medical Equipment Pool. Not MEMS, not Recall Monitor.
**Baseline:** `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` (`docs(governance): close Roadmap PR18 printing and export (#79)`) — Roadmap PR18 is fully merged and governance-synced at this commit. This design branches directly from that commit.
**Scope authority:** `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8, "PR19 — Legacy Import Foundation."
**Supersedes:** PR #81 (`feature/pr19a-legacy-import-foundation`, head `c3813bc93f2100dcb06f02ab9e3098faa61e1706`), which bundled this design with runtime implementation in a single commit — a violation of `docs/ENGINEERING_WORKFLOW.md` §6 flagged by independent review (PR #81 review comment, finding PR19A-H1). PR #81 is closed without merging once this design is approved; its independent-review findings (H2–H5, M1–M2) are the primary input to this revision and are resolved explicitly below, not deferred.

---

## 1. Objective

Design the backend architecture required to eventually import historical AppSheet data (Equipment master, Receive history, Issue history) into this system. This document resolves every architectural question a reviewer needs answered *before* implementation starts: session lifecycle, concurrency/idempotency mechanism, schema-convergence guarantee, adapter/threading contract, validation-attempt ownership, warning semantics, and public error-code registration. No parser, no legacy data import, and no UI are in scope for the resulting implementation slices (§13).

---

## 2. Inputs Reviewed

| Area | Source | What it established |
|---|---|---|
| Roadmap scope | `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8 | PR19 is "Legacy Import Foundation" — architecture only. |
| Engineering process | `docs/ENGINEERING_WORKFLOW.md` §6 | A Design PR must precede implementation for API-contract, database-model, permission, and cross-module architecture changes, and must not itself contain implementation or migrations. |
| PR #81 independent review | GitHub PR #81 comment `5164590001` (Codex, REQUEST CHANGES) | Six merge-blocking/non-blocking findings (H1–H5, M1–M2) against the original bundled implementation. Each is resolved by a specific section below (cross-referenced). |
| Prior import precedent | `backend/app/services/import_service.py`, `backend/app/api/v1/inventory_import.py` (Roadmap PR12) | Stateless preview/commit import of an equipment-master Excel workbook: bounded row count (`MAX_IMPORT_ROWS`), bulk-lookup validation (no per-row DB query), safe generic error wrapping, Administrator-only gate, `ge=1` pagination bound (PR66-H1). This design reuses all of these precedents directly rather than re-deriving them, and treats PR12's bulk-lookup pattern as the concrete fix for §7 below. |
| Schema-hygiene precedent | `backend/alembic/versions/0013_fk_ondelete_policy.py`, `0014_index_naming_convergence.py` | Established a "verify full semantic definition, then classify as no-op/transform/fail-closed" migration pattern (`_classify_fk()`), and the project-wide "every foreign key is explicit `ON DELETE RESTRICT`" policy. §5 below extends both to this feature's CHECK constraints. |
| Pagination precedent | `backend/app/api/v1/*` (PR66-H1, PR70) | `limit` parameters must declare `ge=1` in addition to `le=<max>`; cursor subfields must be validated before any database query and must fail as `400 INVALID_INPUT`, never propagate to an unhandled 500. §11 below applies this to the two new list endpoints. |
| Audit precedent | `backend/app/core/audit.py`, Roadmap PR12's commit-audit pattern | Exactly one `audit_logs` entry per successful write batch, in the same transaction as the write. §12 below keeps this unchanged. |

---

## 3. Import Session Lifecycle and Allowed Transitions

An `ImportSession` is one staged attempt to import one dataset type. States (unchanged from PR #81's original design — not flagged by review, and deliberately **not** related to equipment lifecycle states, which are a separate domain):

```
CREATED
VALIDATING
VALIDATED
VALIDATION_FAILED
DRY_RUN_RUNNING
DRY_RUN_COMPLETED
DRY_RUN_FAILED
EXECUTING
COMPLETED
FAILED
CANCELLED
```

**Allowed transitions:**

| From | Trigger | To |
|---|---|---|
| `CREATED` | validate | `VALIDATING` |
| `VALIDATING` | (internal) | `VALIDATED` \| `VALIDATION_FAILED` |
| `VALIDATED` | re-validate | `VALIDATING` |
| `VALIDATION_FAILED` | re-validate | `VALIDATING` |
| `VALIDATED` | dry-run | `DRY_RUN_RUNNING` |
| `DRY_RUN_RUNNING` | (internal) | `DRY_RUN_COMPLETED` \| `DRY_RUN_FAILED` |
| `DRY_RUN_COMPLETED` | re-dry-run | `DRY_RUN_RUNNING` |
| `DRY_RUN_FAILED` | re-dry-run | `DRY_RUN_RUNNING` |
| `DRY_RUN_COMPLETED` | execute | `EXECUTING` |
| `EXECUTING` | (internal) | `COMPLETED` \| `FAILED` |
| `{CREATED, VALIDATED, VALIDATION_FAILED, DRY_RUN_COMPLETED, DRY_RUN_FAILED}` | cancel | `CANCELLED` |

**Terminal states:** `COMPLETED`, `FAILED`, `CANCELLED` — no transition leaves any of these. A `FAILED` execution does **not** auto-retry; an operator must create a new session (or, if a future slice adds it, explicitly re-validate/re-dry-run from scratch) — this design does not add a "retry execute" transition, since a failed real write must always be re-examined via a fresh dry run before another attempt, never silently resumed.

**Idempotent vs. re-entrant transitions:**
- Re-validate and re-dry-run are **re-entrant, not idempotent**: each call genuinely re-runs the phase and may produce a different outcome (§8, §9 clarify why "idempotent" is reserved for execute specifically).
- Session creation (`POST /import-sessions`) is idempotent via `(dataset_type, idempotency_key)` (unchanged from the original design — not flagged by review).
- Execute is the one operation that must be idempotent in the strict sense (repeat call after success returns the same success, never re-executes) — see §9.

**Concurrency control requirement:** every phase-starting transition (validate, dry-run, execute) and cancel is a state-changing operation that **must** use the atomic conditional-transition mechanism defined in §4 — not only execute. This directly resolves review finding **PR19A-H3**'s observation that "validate/dry-run/cancel have the same lost-transition race" as execute.

---

## 4. Atomic Transition and Concurrency Policy

**Decision: atomic conditional `UPDATE ... WHERE status = ANY(:allowed) RETURNING id`, not `SELECT ... FOR UPDATE`, not a separate version column.**

Every phase-starting transition is implemented as a single SQL statement:

```sql
UPDATE import_sessions
SET status = :new_running_status, updated_at = now()
WHERE id = :session_id AND status = ANY(:allowed_from_statuses)
RETURNING id;
```

executed via SQLAlchemy Core (`update().where(...).returning(ImportSession.id)`), not by loading the ORM object, checking its `.status` in Python, and mutating it. Under PostgreSQL's READ COMMITTED default isolation, this single statement is atomic: exactly one of two concurrent transitions attempting the same `id`/`allowed_from_statuses` pair affects a row. If zero rows are returned, the caller has lost the race (or the session is genuinely in the wrong state) and must re-fetch the session's current status to decide the correct response (§8, §9) — it must never proceed as if it had won.

**Why compare-and-set over `SELECT ... FOR UPDATE`:** the existing (and retained) two-step-commit transaction strategy commits durably after step 1 ("phase started") before step 2 ("do the work") begins. A row lock taken in step 1 would release at that commit, providing no protection for the gap before step 2 — `FOR UPDATE` would need a *single* long-held transaction spanning both steps, which conflicts with the durability guarantee ("last-known phase survives an interruption") that makes step 1's independent commit valuable in the first place. Compare-and-set needs no cross-step lock: each step-1 UPDATE is independently atomic and self-contained.

**Why not a version/lock column:** every transition here is already expressed as "from one of a known set of statuses, to a specific new status" — the `status` column itself is the exact discriminant every caller cares about. A separate `version` column would duplicate that information without adding protection this design needs (there is no scenario here of "any status, but I must have the freshest row" — every transition names its required source states explicitly).

**Losing the race:** a request whose UPDATE affects zero rows always re-fetches the session and returns a response based on its *actual* current state — see §9 for execute's specific idempotent-vs-conflict handling, and §3 above for cancel/validate/dry-run's rejection semantics (unchanged 409 `ImportSessionStateError`, since those three have no "idempotent replay" case — only execute does, per §9).

This resolves review finding **PR19A-H3** in full: state transitions become atomic and race-free, and `get_or_create_session()`'s SELECT-then-INSERT race (the same finding's second half) is resolved by catching the resulting unique-constraint `IntegrityError` on insert, rolling back, and re-querying by `(dataset_type, idempotency_key)` — the retry path already required by that lookup's own contract, now made race-safe instead of assumed safe.

---

## 5. Fresh-Install / Historical-Upgrade Schema Convergence

**Root cause (review finding PR19A-H2):** the original `_StrEnum()` helper omitted `create_constraint=True` on its `SAEnum(...)` call. On the ORM-driven fresh-install path (`Base.metadata.create_all()`, used by `0001_initial.py` and every SQLite test), no CHECK constraint is emitted for any of this feature's four enum-shaped columns; on the Alembic historical-upgrade path (`0015`'s raw SQL), the CHECK constraint is always present. The two paths diverge.

**Decision:**
1. `_StrEnum()` must pass `create_constraint=True` so the ORM-driven path emits a named CHECK constraint identical (by name and definition) to the migration's.
2. The migration must not treat "a table with this name already exists" as success without verification. Replace the bare `CREATE TABLE IF NOT EXISTS` no-op with the same **verify → classify → transform / no-op / fail-closed** pattern established by migrations 0013/0014 (a single shared helper analogous to `_classify_fk()`, but for table/column/constraint/index definitions): before assuming a pre-existing table is correct, compare its actual catalog definition (`information_schema.columns`, `pg_constraint` + `pg_get_constraintdef()`, `pg_indexes`) against this migration's target definition, field-by-field. A match is a true no-op; a mismatch raises (fails closed) rather than silently passing.
3. Both paths must converge on: constraint names, full `pg_get_constraintdef()` text (not just presence/absence), column defaults, nullability, and index definitions — not ORM metadata alone.

**Acceptance criteria (implementation PR must prove with PostgreSQL tests):**
- Fresh empty PostgreSQL database upgraded directly to head.
- A database upgraded historically through 0001→0014, then to head.
- Both produce byte-identical `pg_get_constraintdef()` output for every constraint this feature introduces, identical index definitions, and identical column nullability/defaults.
- Downgrade → re-upgrade round-trip reproduces the same converged state.
- A deliberately mismatched pre-existing table (wrong column type, missing constraint) causes the migration to fail closed, not silently proceed.

This directly resolves **PR19A-H2**.

---

## 6. Parser Adapter and Off-Thread Execution Contract

**Decision:** `ImportAdapter.parse()` remains a synchronous method (real parsers — `openpyxl`, `csv` — are inherently synchronous, CPU/IO-bound libraries; requiring every adapter author to write async code adds no value). The **foundation itself**, not "a future adapter's own call site" (the ambiguity review finding **PR19A-H5** flagged), is responsible for running it off the event loop: the validation orchestration must call `await asyncio.to_thread(adapter.parse, raw_input)` directly, inside the same service function that today calls `adapter.parse(raw_input)` synchronously. This is a concrete, testable contract, not a documented aspiration.

**Row-count boundary:** the existing `MAX_IMPORT_ROWS` structural check must run immediately after `parse()` returns (before any further work), so a pathological adapter that returns an oversized batch is bounded before validation proceeds — this was already true structurally in PR #81 and is retained unchanged as an explicit contract requirement here, not merely an implementation detail.

---

## 7. Batch Validation and N+1 Prevention

**Root cause (review finding PR19A-H5, second half):** the original `validate_business_rules(db, record)` hook received the database session directly and ran once per record — for up to `MAX_IMPORT_ROWS` (5,000) records, a concrete adapter cannot perform a bulk cross-record lookup (mirroring Roadmap PR12's bulk-lookup precedent) without either hidden singleton cache state or one query per row.

**Decision:** split the business-validation hook into two:
1. `async def preload_business_context(self, db, records: list[RawImportRecord]) -> object` — called **once** per validation pass, before the per-record loop. Default implementation returns `None`. A concrete adapter overrides this to perform its bulk lookups (e.g., one `SELECT ... WHERE bcm_code = ANY(:codes)` covering the whole batch, mirroring PR12) and returns an adapter-defined context object.
2. `def validate_business_rules(self, record: RawImportRecord, context: object) -> list[FieldError]` — becomes **synchronous** and receives only the record and the preloaded context, with **no database session parameter**. This is a structural guarantee, not a convention: an adapter cannot issue a per-record database query from this hook because it has no session to issue one with.

`context`'s shape is opaque to the foundation (declared as `object` in the `ImportAdapter` ABC); each concrete adapter defines its own concrete type. The implementation PR must provide a test double proving the two-call shape (`preload_business_context` called exactly once per validation pass, `validate_business_rules` called once per record with no repeated preload) and asserting no N+1 query pattern, matching the requirement in the recovery task.

This resolves **PR19A-H5** in full (both the off-thread parsing half, §6, and the batch-validation half, here).

---

## 8. Validation Attempt / Findings Ownership

**Root cause (review finding PR19A-H4):** the original `bulk_add_row_errors()` only appended rows; after a failed validation pass followed by a successful one, the session's counters (`invalid_rows=0`, `status=VALIDATED`) and the persisted `ImportRowError` rows disagreed — `GET /errors` kept returning the first pass's stale failures as if they were current.

**Decision:** every `ImportRowError` row is owned by the specific `ImportJob` (of `job_type=VALIDATE`) that produced it, not only by the session. Add `import_row_errors.import_job_id` (`FK -> import_jobs.id`, `ON DELETE RESTRICT`, `NOT NULL`), populated from the `ImportJob` row `_run_phase` already creates for every validation attempt (no new table is introduced — the existing per-phase `ImportJob` row *is* the attempt identity, avoiding schema bloat for a "foundation only" slice).

"Current" errors for a session are defined as: rows whose `import_job_id` equals the session's **most recent** `VALIDATE`-type `ImportJob` (`ORDER BY created_at DESC LIMIT 1`). `GET /import-sessions/{id}/errors` joins through this latest-job lookup by default; historical findings from earlier validation attempts are retained in the table (never deleted) but are not returned unless a caller explicitly requests an older job's id — the design permits this history to exist since discarding it destroys audit value at zero storage-cost benefit, but "current" must always mean "latest attempt only," never "all attempts merged."

The session's own `total_rows`/`valid_rows`/`invalid_rows`/`warning_rows` (§9) counters and the `GET /errors` result **must be derived from the same latest-job join** so they can never disagree — this is the specific guarantee that closes PR19A-H4's failure mode ("counters say 0 but errors endpoint still returns old rows").

This resolves **PR19A-H4** in full.

---

## 9. Warning vs. Error Semantics

**Root cause (review finding PR19A-M2):** `ImportErrorSeverity` (`ERROR`/`WARNING`) already existed as a model concept, but `run_validation()`'s pass/fail decision treated the mere presence of any `FieldError` — regardless of severity — as blocking, so WARNING was defined but never actually non-blocking.

**Decision:** partition every validation pass's collected `FieldError`s by severity:
- `blocking_errors = [e for e in all_errors if e.severity == ERROR]`
- `warnings = [e for e in all_errors if e.severity == WARNING]`

A session reaches `VALIDATED` **if and only if `blocking_errors` is empty**, regardless of how many `warnings` exist. Both are persisted as `ImportRowError` rows (severity preserved, both attributed to the same validation job per §8), so both are visible via `GET /errors`, but only `blocking_errors`' row-count feeds `invalid_rows`. A new `warning_rows` counter is added to the session summary so an operator can distinguish "0 errors, 12 warnings" (proceeds to dry run) from "3 errors" (blocked) at a glance.

Dry-run and execute remain gated on `status == VALIDATED`, which by this definition now correctly means "zero blocking errors, warnings permitted, dry-run/execute proceed" — resolving **PR19A-M2**'s warning-semantics half. The implementation PR's tests must cover: warnings-only batch reaches `VALIDATED` and permits dry-run/execute; any-errors batch (with or without warnings present) reaches `VALIDATION_FAILED` and blocks both.

---

## 10. Dry-Run and Execute Idempotency

**Dry-run** performs zero writes by its own contract (unchanged) — it needs no idempotency mechanism beyond the atomic transition guard of §4, which prevents two concurrent dry-run calls from both leaving `VALIDATED`/`DRY_RUN_COMPLETED`/`DRY_RUN_FAILED` at the same instant; a *sequential* repeat dry-run is expected, safe, and re-entrant by design (§3).

**Execute** is the operation that must be idempotent in the strict sense. Decision:
- A repeat `POST .../execute` call against a session that has already reached `COMPLETED` must return the existing `ImportSessionOut` as a **200 success**, not re-run `adapter.execute()` and not return an error — this is a legitimate outcome of a retried request (e.g., a client timeout after the server-side commit succeeded), not a client mistake.
- A repeat call against a session in `EXECUTING` (another request currently holds the claim, §11) returns `409 ImportSessionStateError` ("execution already in progress").
- A repeat call against a session in `FAILED` also returns `409` — per §3, a failed execution requires a fresh dry-run cycle before another attempt, never an automatic retry.
- Any other state (e.g. `CREATED`, `VALIDATED` — dry run never completed) returns `409`, unchanged from the original design.

The distinguishing logic lives in the execute endpoint: when the §4 atomic UPDATE affects zero rows, re-fetch the session and branch on its actual status — `COMPLETED` → idempotent 200; anything else → 409.

---

## 11. Single-Winner Execution Claim

The atomic conditional UPDATE of §4, applied specifically to the `DRY_RUN_COMPLETED -> EXECUTING` transition, **is** the single-winner execution claim — no separate token/column is needed. Exactly one of two concurrent `POST .../execute` requests' `UPDATE ... WHERE status = 'dry_run_completed' RETURNING id` affects a row and proceeds to create the `EXECUTE`-type `ImportJob` row and call `adapter.execute()`. The request(s) that affect zero rows must not create a job row and must not call the adapter — they instead follow §10's idempotent/conflict branching. This guarantees the required invariant: **two concurrent execute requests can never both perform writes.**

The implementation PR's tests must include a genuine two-connection PostgreSQL concurrency test: two simultaneous `execute` calls against the same `DRY_RUN_COMPLETED` session; assert exactly one adapter-execute path ran, exactly one `EXECUTE`-type `ImportJob` row exists, the audit entry (§12) was written exactly once, and the losing request received the deterministic conflict/idempotent response defined in §10 — not a duplicate write, not an unhandled exception.

This resolves **PR19A-H3**'s execute-specific concurrency requirement in full (paired with §4's general mechanism for the other transitions).

---

## 12. Audit Transaction Boundaries

Unchanged from the original design (not flagged by review): exactly one `audit_logs` entry is written by the *winning* execute request, only on `adapter.execute()`'s success, in the **same** database transaction/commit as the adapter's writes and the session's `COMPLETED` status update (the existing two-step-commit "step 2" transaction). No audit entry is written for validate, dry-run, cancel, a losing/idempotent-replay execute call (§10 — no new write occurred), or a failed execute (the `ImportJob(FAILED)` row and the session's `failure_reason` are that outcome's record, per the original design's rationale that this is a more complete record than a single audit line).

---

## 13. Cursor and Pagination Validation

**Root cause (review finding PR19A-M1):** both list endpoints (`GET /import-sessions`, `GET /import-sessions/{id}/errors`) declared `limit` with only `le=200`, silently clamping zero/negative input to 1 instead of rejecting it (inconsistent with the repository-wide convention fixed by PR66-H1 for every other paginated endpoint). Cursor subfields (`uuid.UUID(cursor_id)` for session cursors, `int(...)` for row-error cursors) were parsed outside the hardened decoder, so a structurally valid but semantically wrong cursor envelope could raise an unhandled `ValueError` and surface as a 500.

**Decision:**
- `limit: int = Query(default=25, ge=1, le=200)` on both endpoints.
- Every cursor subfield parse (the UUID, the integer) must be wrapped at the point of parsing and re-raised as `InvalidInputError` (→ `400 INVALID_INPUT`) on any `ValueError`/`ValueError`-subclass — applied uniformly in the CRUD-layer cursor decoders, not ad hoc per endpoint.
- Implementation PR tests must prove: `limit=0` and negative `limit` are rejected (400, no query executed); a cursor with a well-formed envelope but a malformed UUID/integer subfield is rejected (400, no query executed) — fail-fast, no partial query execution before the rejection.

This resolves **PR19A-M1**.

---

## 14. Public Error Codes

**Decision:** every new `DomainError` subclass this feature introduces — the five already named in the original design (`ImportSessionNotFoundError`, `ImportAdapterNotRegisteredError`, `ImportSessionStateError`, `ImportAdapterNotImplementedError`, `ImportExecutionFailedError`) plus any new code the concurrency/idempotency work (§10, §11) or validation-attempt work (§8, §9) introduces — must be registered in `docs/api/ERROR_CODES.md` **in the same implementation PR that introduces it**, not deferred to the final governance sync. This is a per-PR checklist item for each of the three implementation slices (§15); the governance sync PR only performs a final cross-check sweep, never first-time registration. This resolves **PR19A-M2**'s documentation half.

---

## 15. Implementation Slices (Approved Sequence)

Per Owner-approved recovery plan, implementation proceeds in this order once this Design PR is merged, each branching from the design's merged baseline (never from PR #81):

1. **PR19A1 — Schema, session lifecycle, atomic transitions, session pagination.** Implements §3, §4, §5, and the session-list half of §13. Includes the PostgreSQL fresh-install/historical-upgrade convergence tests (§5) and the atomic-transition concurrency tests for validate/dry-run/cancel (§4).
2. **PR19A2 — Adapter contract, off-thread parsing, batch validation, validation attempts/findings, warning semantics.** Implements §6, §7, §8, §9, and the row-errors-list half of §13.
3. **PR19A3 — Dry-run/execution claim, single-winner execution, idempotency, audit.** Implements §10, §11, and confirms §12 unchanged. Includes the two-connection PostgreSQL concurrency test proving single-winner execution (§11).
4. **Governance sync** — after all three implementation slices merge: updates `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `docs/DECISION_LOG.md`, and `knowledge/*` to record PR19A as complete; performs the final `docs/api/ERROR_CODES.md` cross-check sweep (§14).

Each implementation PR must register any new public error code it introduces (§14) and must not implement a concrete parser, legacy data import, or UI — those remain out of scope for every slice above, per §1.

---

## 16. Non-Goals (Unchanged)

No implementation slice above may include: an Excel/CSV parser; Legacy Equipment/Receive/Issue import; background workers/scheduler; an import wizard or progress UI; a cutover process. These remain later Roadmap PR19 slices (concrete adapters) and PR20/PR21 (per-dataset import).
