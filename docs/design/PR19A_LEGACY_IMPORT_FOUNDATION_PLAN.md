# Roadmap PR19A — Legacy Import Foundation: Design & Implementation Record

**Status:** Implemented (foundation only). No parser ships in this slice; no legacy data has been imported; no UI exists.
**Repository:** Medical Equipment Pool. Not MEMS, not Recall Monitor — no coupling to either system.
**Baseline:** `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` (`docs(governance): close Roadmap PR18 printing and export (#79)`) — Roadmap PR18 (all slices) is fully merged and governance-synced at this commit.
**Branch:** `feature/pr19a-legacy-import-foundation`.
**Scope authority:** `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8, "PR19 — Legacy Import Foundation."

---

## 1. Objective

Build the backend **architecture** required to eventually import historical AppSheet data (Equipment master, Receive history, Issue history) into this system — without performing any actual import in this slice. This document, together with the code it describes, is the authoritative reference for every `design §N` comment in `app/models/import_session.py`, `app/services/import_foundation.py`, and `alembic/versions/0015_import_foundation.py`.

This PR does **not**:
- Parse Excel or CSV.
- Import Equipment, Receive history, or Issue history.
- Run any background worker, scheduler, or queue.
- Add any UI (wizard, progress bar, or otherwise).

Those are Roadmap PR19B (concrete adapters) and PR20/PR21 (per-dataset import, per `docs/audits/04-consolidated-implementation-plan.md` Part D).

---

## 2. Inputs Reviewed

| Area | Source | What it established |
|---|---|---|
| Roadmap scope | `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8 | PR19 is "Legacy Import Foundation" — architecture only; concrete dataset importers are separate, later PRs. |
| Governance/process | `AGENTS.md`, `docs/PROJECT_PLAYBOOK.md`, `docs/ENGINEERING_WORKFLOW.md` | Standard PR lifecycle: baseline verification, design-before-code, independent review (Codex), no self-approval. |
| Roadmap state | `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md` | PR18 (Printing & Export) is the most recently completed slice; PR19 is next in the approved sequence. |
| Business rules | `docs/BUSINESS_RULES.md` | Confirmed 3-role model (Administrator / Equipment Pool Staff / Read Only); nothing in it describes an import workflow — none exists yet to preserve. |
| Decision history | `docs/DECISION_LOG.md` | No prior decision addresses legacy import; this is a new area. |
| Project history/context | `knowledge/CHANGE_HISTORY.md`, `knowledge/CONTEXT.md`, `knowledge/PROJECT_MEMORY.md` | AppSheet is the legacy system being replaced; migration of its historical data is acknowledged as future scope, not yet designed. |
| Prior import precedent | `backend/app/services/import_service.py`, `backend/app/api/v1/inventory_import.py` (Roadmap PR12) | An existing, narrower import: stateless preview/commit of an equipment-master Excel workbook, capped row count, bulk-lookup validation, `ImportCommitFailedError`-style safe error wrapping, Administrator-only gate. PR19A's `MAX_IMPORT_ROWS` bound and "do not leak the real internal exception" pattern in `run_execute` both directly reuse this precedent. PR12's import is **stateless** (no persisted session) — PR19A is a deliberately different, **staged/session-based** design (§3) because it must support a multi-step human review workflow (validate → dry-run → execute) and traceability across historical, one-off legacy datasets that PR12's live, repeatable workbook-upload flow never needed. |
| Legacy source system | AppSheet Equipment Pool app (referenced throughout `docs/audits/`, `knowledge/`) | The legacy database this foundation will eventually import from has three logical datasets: Equipment master, Receive history, Issue history. No live legacy schema is available to inspect directly in this repository; this foundation is deliberately dataset-agnostic (`dataset_type: str`, not an enum) so it does not need to guess that schema. |

---

## 3. Data Model — What an Import Session Is

An **`ImportSession`** (`app/models/import_session.py`) is one staged attempt to import one dataset type. It is the unit of tracking, review, and audit for the whole pipeline described in §8.

Key decisions:

- **`dataset_type` is a plain bounded string (`String(100)`), not an enum.** Enumerating `"equipment_master"` / `"receive_history"` / `"issue_history"` now would encode PR20/PR21 scope into this migration before either dataset's import is actually designed. The set of dataset types that can progress past `CREATED` is instead whatever is registered at runtime in `ImportAdapterRegistry` (§8) — empty in this slice, so **no dataset type can complete a real import yet**, by construction, not by convention.
- **A session accumulates summary counters** (`total_rows`, `valid_rows`, `invalid_rows`, `imported_rows`) and phase timestamps (`validated_at`, `dry_run_completed_at`, `executed_at`) — the "Import result summary model" required by scope. These are the fields `ImportSessionSummaryOut` (§9) serializes for a human reviewing an import.
- **`failure_reason`** is the single top-level reason a session is in a `*_FAILED` state, distinct from the per-row detail in `import_row_errors` (§6) — a session can fail with zero row errors (e.g. no adapter registered).
- Every enum-shaped column (`status`, job `job_type`/`status`, error `severity`) uses `native_enum=False` + `values_callable` (the same convention as `app.models.equipment.EquipmentStatusType`) — a plain bounded VARCHAR with a CHECK constraint, never a native PostgreSQL enum type, so a future added state never needs `ALTER TYPE ... ADD VALUE`.

---

## 4. State Machine & Transaction Strategy

### 4.1 States

```
CREATED -> VALIDATING -> { VALIDATED, VALIDATION_FAILED }
VALIDATED -> DRY_RUN_RUNNING -> { DRY_RUN_COMPLETED, DRY_RUN_FAILED }
DRY_RUN_COMPLETED -> EXECUTING -> { COMPLETED, FAILED }
{ CREATED, VALIDATED, VALIDATION_FAILED, DRY_RUN_COMPLETED, DRY_RUN_FAILED } -> CANCELLED
```

Every transition is enforced server-side by `app.services.import_foundation` (`_require_status`) — a client can never set `status` directly (it is not writable via any request schema). Once `EXECUTING` begins, a session always resolves to `COMPLETED` or `FAILED`, never `CANCELLED` — the outcome of the write phase must always be recorded truthfully, matching the "no partial silent import" requirement applied to session state itself, not only to row writes. `TERMINAL_SESSION_STATUSES` (`COMPLETED`, `FAILED`, `CANCELLED`) rejects any further state-changing call once reached.

### 4.2 Two-step-commit phase orchestration

Every phase (validate / dry-run / execute) runs through the shared `_run_phase` helper:

1. **Step 1 (durable "started" record):** `session.status` moves to the phase's `*_RUNNING`/`*_VALIDATING` state, one `ImportJob` row is created, and this is committed **immediately** — before any real work happens. This is what makes a session's last-known phase inspectable even if the process crashes mid-phase (§7).
2. **Step 2 (the actual work):** runs inside a fresh, still-open transaction. On success, it commits together with the job's `SUCCEEDED` status and the session's new terminal-for-this-phase status. On any exception, everything step 2 attempted is rolled back (`db.rollback()`), and a **separate**, honest follow-up transaction records the job as `FAILED` and the session's failure state.

This guarantees a crash or exception during row-error insertion, business mapping, or (in a future slice) the real write phase can never leave a partially-applied batch — only a durably-recorded, honestly-reported failure. This is the concrete mechanism behind "no partial silent import," "rollback on failure," and "transaction boundaries."

### 4.3 Cancellation

An operator may cancel a session from any pre-execution state (`CANCELLABLE_SESSION_STATUSES`). Once `EXECUTING` has started, cancellation is not offered — the phase always resolves on its own.

---

## 5. Idempotency & Duplicate Detection

Two independent layers, at two different scopes:

1. **Session-level idempotency.** A caller may supply a client-generated `idempotency_key` when creating a session. `(dataset_type, idempotency_key)` is enforced unique at the database level (`uq_import_sessions_dataset_idempotency_key`). `get_or_create_session()` looks up an existing session by that pair first and returns it unchanged rather than creating a duplicate — a repeated "create session" call (e.g. a retried HTTP request) is always safe. The key is unique only *within* its own `dataset_type`, so the same key reused for a genuinely different dataset is not silently conflated.
2. **In-batch duplicate detection.** Within one parsed batch, `_detect_duplicates()` flags **every** row sharing a duplicate key (an adapter-declared `duplicate_key_fields` tuple) — not just the second-and-later occurrences — mirroring Roadmap PR12's "flag all duplicates within a file, keep none silently as the real one" precedent. This runs after structural validation and before business-rule validation, in the pipeline's fixed order (§8).

`source_checksum` is captured but **not** enforced unique — two independent sessions re-validating the same source content is not itself an error at this foundation layer; a future slice may build stronger cross-session duplicate-file heuristics on top of it.

---

## 6. Error Collection Model

`ImportRowError` (`import_row_errors` table) is one row per collected validation/business-rule failure. Design points:

- **`row_number` is nullable** — not every error is row-scoped (e.g. "no adapter registered for this dataset_type" is a session-level failure with no single row to attribute it to).
- **Deliberately has no `TimestampMixin`** (no `created_at`/`updated_at`): row errors are write-once, append-only records of a single validation pass. `ImportJob.finished_at` on the owning `VALIDATE` job already records when that pass ran.
- **`severity`** distinguishes `ERROR` (blocks the session from reaching `VALIDATED`) from `WARNING` (reserved for a future adapter that wants to surface non-blocking notices; this foundation's own pipeline stages only ever emit `ERROR`).
- Re-validating a session (§8.2) does not delete prior error rows before inserting new ones — see §8.2's documented limitation.

---

## 7. Resumability — Foundation Only

`ImportJob` (`import_jobs` table) records each phase (`validate` / `dry_run` / `execute`) of a session as its **own row**, independent of the session's own summary timestamps. This is what lets a future slice determine exactly which phase last ran and its outcome without re-deriving it from summary counters alone — the schema already supports resuming after an interruption.

This slice runs every phase **synchronously**, inside the HTTP request that triggered it. Running a phase asynchronously/out-of-process (a background worker, a queue, a scheduler) is explicitly future scope — the job-row model is designed so that a future async executor can adopt it without a schema change, but no such executor exists yet.

---

## 8. Architecture — Pipeline Flow

```
Import File -> Parser Adapter -> Validation -> Business Mapping -> Dry Run -> Import Execution -> Summary
```

### 8.1 Pluggable adapters

`ImportAdapter` (abstract base class, `app/services/import_foundation.py`) is the seam between dataset-agnostic pipeline orchestration and dataset-specific logic:

- `parse(raw_input) -> list[RawImportRecord]` — **abstract**, no default. The only stage a real subclass *must* implement; there is no meaningful foundation-level default for "read this format."
- `validate_business_rules(db, record) -> list[FieldError]` — default: no additional errors. A dataset type with nothing beyond structural/duplicate checks may leave this unoverridden.
- `plan_dry_run(db, session) -> DryRunPlan` and `execute(db, session) -> ExecutionOutcome` — **both default to raising `ImportAdapterNotImplementedError`**. This is the deliberate mechanism that makes "no real data movement is possible in this slice" structurally true rather than a promise: with the registry (`ImportAdapterRegistry`) shipping empty, every call against a real `dataset_type` fails fast with `ImportAdapterNotRegisteredError` before any state change, and even a hypothetical registered-but-incomplete adapter cannot reach a real write path without overriding both hooks explicitly.

`plan_dry_run`/`execute` receive the `ImportSession` object itself, not a list of parsed records — this foundation does not persist parsed/validated row content between phases (only `ImportRowError` rows survive). A concrete adapter that needs real row data at dry-run/execute time is responsible for its own strategy (re-parsing a durably-referenced source, or an adapter-owned cache) — that decision belongs to the concrete adapter design in a future slice, not this foundation.

### 8.2 Validation pipeline — deterministic order

Always: **structural → duplicate detection → business rules**, always in original parse order within each stage.

1. **Structural** (`_validate_structural`): required-field presence, per-field max length, both adapter-declared.
2. **Duplicate detection** (`_detect_duplicates`): in-batch key collisions (§5).
3. **Business rules** (`_run_business_validation`): the adapter's own hook, run per-record, async (so a future adapter can cross-reference existing database rows).

A record failing an earlier stage never reaches a later one. All collected errors across all three stages are persisted as `ImportRowError` rows in one batch write (`bulk_add_row_errors`) at the end of the `VALIDATE` phase.

Re-running validation (a session in `VALIDATED` or `VALIDATION_FAILED` may be validated again, e.g. against a corrected source) re-derives counts and error rows from scratch **for that run**, but does not delete previously-persisted `ImportRowError` rows from an earlier run first — row errors are effectively write-once per session lifetime in this slice. This is a **documented limitation**, not a silent one: re-validation is expected to be rare operator behavior, and removing stale error rows correctly (vs. accumulating misleading history) is left to a future slice once a real adapter and real operator workflow exist to inform the right UX.

### 8.3 Dry run and execution

- **Dry run** requires a session that has already reached `VALIDATED` (or is re-running from `DRY_RUN_COMPLETED`/`DRY_RUN_FAILED`) — a session with any recorded validation error can never reach dry run.
- **Execution** requires `DRY_RUN_COMPLETED` only — it is structurally impossible to execute a session that was never validated or dry-run-planned. `adapter.execute()` runs inside the same open transaction `_run_phase` manages; any exception rolls back everything it attempted. On success, exactly one `audit_logs` entry is written (mirroring Roadmap PR12's "one entry per import commit batch" precedent) — see §11.

---

## 9. API — Skeleton Only

Versioned under the existing `/api/v1` prefix, `/import-sessions` resource:

| Method & path | Purpose |
|---|---|
| `POST /import-sessions` | Create (or, if `idempotency_key` matches, return the existing) import session. |
| `GET /import-sessions` | Cursor-paginated list, optional `dataset_type` filter. |
| `GET /import-sessions/{id}` | Full summary: session + its jobs + row-error count ("Import result summary model"). |
| `GET /import-sessions/{id}/status` | Lightweight, poll-friendly status only. |
| `GET /import-sessions/{id}/errors` | Cursor-paginated row errors for one session. |
| `POST /import-sessions/{id}/validate` | Run the validate phase. **No request body** — no parser exists in this slice, so there is no raw input to accept yet; every call fails with `IMPORT_ADAPTER_NOT_REGISTERED` (422). |
| `POST /import-sessions/{id}/dry-run` | Run the dry-run phase. |
| `POST /import-sessions/{id}/execute` | Run the execute phase. |
| `POST /import-sessions/{id}/cancel` | Cancel a cancellable session. |

All nine endpoints are Administrator-only (§10). This is the honest, structural proof that the API contract, permission gate, and session state machine are wired end-to-end — without pretending a real import can succeed yet.

---

## 10. Permission Model

Every `/import-sessions/*` endpoint is gated by `Depends(require_roles(*ADMINISTRATOR_ONLY_ROLES))` — matching Roadmap PR12's precedent for the existing `/import/*` endpoints. There is no unrestricted upload endpoint: even `POST /import-sessions` (session creation, before any file is involved) requires Administrator. "Imported data must pass the same validation as runtime API operations" is satisfied structurally: the validation pipeline (§8.2) is the *only* path by which a session can reach `VALIDATED`, and execution (§8.3) is unreachable without it.

---

## 11. Audit Integration

`run_execute` writes exactly one `audit_logs` entry, only on success, reusing the existing `record_audit_event` helper and `AUDIT_ACTION_IMPORT` action constant (Roadmap PR12 precedent) with a new `AUDIT_ENTITY_IMPORT_SESSION` entity-type constant. The entry's `after` payload records `dataset_type` and the adapter-reported `created`/`updated`/`skipped` counts. No audit entry is written for validate, dry-run, cancellation, or a failed execution in this slice — those are visible via the session/job rows themselves (§3, §7), which is a more complete record than a single audit line would be.

---

## 12. Testing Strategy

`backend/tests/test_import_foundation.py` exercises the pipeline mechanics using an in-memory `_StubAdapter` test double — **not** a CSV/Excel parser, which remains explicitly out of scope for this slice. Coverage:

- Session lifecycle / state machine (every legal and illegal transition, terminal-state rejection, cancellation eligibility).
- Validation pipeline (structural, duplicate detection, business-rule hook, deterministic ordering, row-count bound, re-validation).
- Dry-run behaviour, including the base `ImportAdapter.plan_dry_run` default raising `ImportAdapterNotImplementedError`.
- Transaction rollback (a failing `work()` closure leaves the session/job rows in a consistent, honestly-failed state, never partially applied).
- Duplicate detection framework (in-batch key collisions flag every occurrence).
- Permission checks (non-Administrator roles rejected on every endpoint).
- API contracts (full HTTP round trip: create → validate → 404s → pagination → error codes).

No parser tests exist, per scope.

---

## 13. Non-Goals (Explicit)

This PR does **not** implement, and no code in this slice attempts:

- Excel importer / CSV importer (any real `ImportAdapter.parse()`).
- Legacy Equipment import, Legacy Receive import, Legacy Issue import.
- Background jobs, a scheduler, or any out-of-process execution.
- Progress tracking UI or an import wizard.
- A cutover process.

These belong to later Roadmap PR19 slices (concrete adapters) and PR20/PR21 (per-dataset import), per `docs/audits/04-consolidated-implementation-plan.md` Part D.

---

## 14. Database Impact

Three new, purely additive tables (`import_sessions`, `import_jobs`, `import_row_errors`) via Alembic migration `0015_import_foundation`. No existing table is modified. No foreign key points *into* these tables from any existing domain table (equipment, transactions, master data) — this migration cannot affect any existing behavior. Three new foreign keys point *out*: `import_sessions.created_by_user_id` (to `users.id`), `import_jobs.import_session_id`, and `import_row_errors.import_session_id` (both to `import_sessions.id`) — all three are `ON DELETE RESTRICT`, extending Roadmap PR15B's (migration `0013_fk_ondelete_policy`) explicit "every foreign key is RESTRICT" schema-wide policy rather than introducing a `CASCADE` exception, consistent with that policy's own rationale (no code path in this slice performs a real SQL `DELETE` against any of the three tables).
