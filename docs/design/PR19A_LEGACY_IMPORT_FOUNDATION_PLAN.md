# Roadmap PR19A — Legacy Import Foundation: Design (Governance)

**Status:** Design only. No runtime code, migration, API, or test file is part of this PR. Nothing in this document has been implemented.
**Repository:** Medical Equipment Pool. Not MEMS, not Recall Monitor.
**Baseline:** `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` (`docs(governance): close Roadmap PR18 printing and export (#79)`) — Roadmap PR18 is fully merged and governance-synced at this commit. This design branches directly from that commit.
**Scope authority:** `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8, "PR19 — Legacy Import Foundation."
**Supersedes:** PR #81 (`feature/pr19a-legacy-import-foundation`, head `c3813bc93f2100dcb06f02ab9e3098faa61e1706`), which bundled this design with runtime implementation in a single commit — flagged merge-blocking (finding PR19A-H1) by independent review. **PR #81 has already been closed, unmerged** (comment recorded on that PR pointing here); its branch is retained temporarily pending confirmation that every finding below has been transferred and verified.
**Revision history:** This is the second revision of this design. The first revision (head `b142f4d16d4f56c4dac4b1dcdb8d669c98c3ce24`) resolved PR #81's original findings (atomic transitions, schema convergence, off-thread parsing, batch validation, warning semantics, cursor hygiene, per-PR error-code registration — all preserved unchanged below) but was itself returned REQUEST CHANGES (review comment `5165925838`, findings D1–D5/M1) for lacking a complete domain-model/API/security contract, source persistence/recovery semantics, an unambiguous validation-snapshot invariant, an idempotency fingerprint, and enforced dry-run read-only isolation. This revision adds all of those.

---

## 1. Objective

Design the complete backend architecture required to eventually import historical AppSheet data (Equipment master, Receive history, Issue history) into this system, such that an implementer can answer every question in §22 (Acceptance Criteria) without guessing. No parser, no legacy data import, and no UI are in scope for the resulting implementation slices (§20).

---

## 2. Inputs Reviewed

| Area | Source | What it established |
|---|---|---|
| Roadmap scope | `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8 | PR19 is "Legacy Import Foundation" — architecture only. |
| Engineering process | `docs/ENGINEERING_WORKFLOW.md` §6 | A Design PR must precede implementation for API-contract, database-model, permission, and cross-module architecture changes, and must define the API proposal, data-model direction, security/information boundaries, performance, risks, acceptance criteria, and slices — not just resolve point findings. |
| PR #81 independent review | GitHub PR #81 comment `5164590001` (Codex, REQUEST CHANGES) | Original findings H1–H5/M1 against the bundled implementation. Resolved in this design's §5–§8, §16, §19, and preserved unchanged. |
| PR #83 rev.1 independent review | GitHub PR #83 comment `5165925838` (Codex, REQUEST CHANGES) | Findings D1 (incomplete data/API/security contract), D2 (source ownership/replay/crash recovery undefined), D3 (validation snapshot ambiguity), D4 (idempotency not bound to source), D5 (dry-run enforcement assertion-only), M1 (slice/reference reconciliation). Each is resolved by a specific section below, cross-referenced at the start of that section. |
| Prior import precedent | `backend/app/services/import_service.py`, `backend/app/api/v1/inventory_import.py` (Roadmap PR12) | Stateless preview/commit import of an equipment-master Excel workbook: bounded row count (`MAX_IMPORT_ROWS`), bulk-lookup validation (no per-row DB query), safe generic error wrapping, Administrator-only gate, `ge=1` pagination bound (PR66-H1), bounded decompressed-archive size (zip-bounds "H2R" finding). This design reuses all of these precedents directly and cites the zip-bounds precedent explicitly as a forward obligation on the future concrete-adapter slice (§18). |
| Schema-hygiene precedent | `backend/alembic/versions/0013_fk_ondelete_policy.py`, `0014_index_naming_convergence.py` | Established a "verify full semantic definition, then classify as no-op/transform/fail-closed" migration pattern, and the project-wide "every foreign key is explicit `ON DELETE RESTRICT`" policy. §6 extends both to this feature. |
| Pagination precedent | PR66-H1, PR70 | `limit` parameters must declare `ge=1`; cursor subfields must be validated before any database query and fail as `400 INVALID_INPUT`, never propagate to an unhandled 500. §16 applies this. |
| RBAC precedent | `backend/app/api/v1/deps.py`, `docs/BUSINESS_RULES.md` | Confirmed 3-role model: Administrator, Equipment Pool Staff, Read Only. `ADMINISTRATOR_ONLY_ROLES` already gates Roadmap PR12's import endpoints. §17 reuses this without inventing a new role. |
| Audit precedent | `backend/app/core/audit.py`, Roadmap PR12's commit-audit pattern | Exactly one `audit_logs` entry per successful write batch, in the same transaction as the write. §15 keeps this and adds one new, narrowly-scoped recovery-audit case. |

---

## 3. Domain Model Contract

This section is the authoritative target data model. It defines every entity PR19A1–PR19A3 may create; no implementation PR may add a table, column, or constraint this section does not describe without a design amendment. Internal persistence and public/API vocabulary are deliberately different where the public name is clearer (per `docs/ENGINEERING_WORKFLOW.md`'s "do not expose ORM/database models directly as API contracts") — the mapping is stated in each entity's heading.

### 3.1 ImportSession

*(persisted as `import_sessions`; public API name: `ImportSession` / `ImportSessionOut`)*

| Property | Value |
|---|---|
| Purpose | One staged import attempt for one dataset type — the root aggregate of the pipeline. |
| Primary key | `id` (UUID) |
| Business identifiers | `(dataset_type, idempotency_key)` unique when `idempotency_key` is set (§12) |
| Ownership | `created_by_user_id` (FK `users.id`, `ON DELETE RESTRICT`) — the Administrator who created it |
| Required fields | `dataset_type`, `status`, `created_by_user_id` |
| Immutable fields | `id`, `dataset_type`, `created_by_user_id`, `idempotency_key`, `idempotency_fingerprint` (§12), `created_at` |
| Mutable fields | `status`, `current_validation_job_id` (§10), `validated_at`, `dry_run_completed_at`, `executed_at`, `total_rows`, `valid_rows`, `invalid_rows`, `warning_rows`, `imported_rows`, `failure_reason`, `updated_at` |
| Lifecycle/status fields | `status` — the enum defined in §4 |
| Relationships | 1:1 `ImportSource` (§3.2); 1:N `ImportJob` (§3.3); N:1 `users` |
| Delete policy | No DELETE endpoint exists in any planned slice; not otherwise addressed |
| Retention | Indefinite in this foundation — no automatic purge (no scheduler exists, §21) |
| Sensitive fields | `notes` (free-text, operator-supplied — §18); `failure_reason` (bounded to 2000 chars, never a raw exception, §18) |
| Indexes / uniqueness | `UNIQUE(dataset_type, idempotency_key)`; `INDEX(dataset_type, status)`; `INDEX(created_by_user_id)` |
| Concurrency / version fields | None beyond `status` itself — §5 explains why a separate version column is unnecessary |

### 3.2 ImportSource

*(persisted as `import_sources`, new table; public API name: `ImportSource` / `ImportSourceOut`)*

| Property | Value |
|---|---|
| Purpose | The integrity-binding record for the data a session will validate/import: checksum and descriptive metadata only. **Does not store raw bytes in this foundation** — see §7 for the explicit scope boundary this implies. |
| Primary key | `id` (UUID) |
| Business identifiers | `import_session_id` (unique — exactly one source per session in this foundation) |
| Ownership | Implicit, via the owning session |
| Required fields | `import_session_id`, `checksum` |
| Immutable fields | `checksum`, once first set (§7's immutability rule) |
| Mutable fields | `filename`, `byte_size`, `content_type` — fillable only while unset; never overwritten with a different value once set |
| Lifecycle/status fields | None — existence of the row implies "registered"; no separate status |
| Relationships | 1:1 `ImportSession` |
| Delete policy | `ON DELETE RESTRICT` from `import_session_id`, matching the project-wide FK policy (§6) |
| Retention | Same as the owning session; `retention_expires_at` is a reserved, nullable column for a future byte-storage slice — always `NULL` in PR19A1–A3 |
| Sensitive fields | `filename` (may itself describe sensitive content — §18) |
| Indexes / uniqueness | `UNIQUE(import_session_id)`; `INDEX(checksum)` (supports a future cross-session duplicate-source heuristic; not enforced unique across sessions) |
| Concurrency / version fields | None — first-write-wins; a second call is a read-compare, not a lock-requiring race (§7) |

### 3.3 ImportJob — backing entity for ValidationAttempt / DryRunAttempt / ExecutionAttempt

*(persisted as `import_jobs`; public API concept names: `ValidationAttempt`, `DryRunAttempt`, `ExecutionAttempt` — all the same table, discriminated by `job_type`)*

**Why one table, not three:** `ValidationAttempt`, `DryRunAttempt`, and `ExecutionAttempt` are named domain concepts requested for evaluation, but they share an identical shape (one row per phase execution, with `status`/`started_at`/`finished_at`/`error_message`) and identical lifecycle semantics (§4). Splitting them into three tables would add schema surface with no behavioral difference, contrary to this Roadmap slice's "foundation only" scope. They remain one physical table (`import_jobs`), discriminated by `job_type`; the public API and this document use the phase-specific domain name when discussing that phase's behavior.

| Property | Value |
|---|---|
| Purpose | One execution record of one phase (validate / dry_run / execute) of a session. |
| Primary key | `id` (UUID) |
| Business identifiers | None beyond the PK; `(import_session_id, job_type, created_at)` is the natural history-ordering key |
| Ownership | Via the owning session |
| Required fields | `import_session_id`, `job_type` |
| Immutable fields | `import_session_id`, `job_type`, `created_at` |
| Mutable fields | `status`, `started_at`, `finished_at`, `error_message`, `ruleset_version` (VALIDATE jobs only, §10) |
| Lifecycle/status fields | `status` (`PENDING`/`RUNNING`/`SUCCEEDED`/`FAILED`) |
| Relationships | N:1 `ImportSession`; 1:N `ValidationFinding` (VALIDATE jobs only, §3.4) |
| Delete policy | `ON DELETE RESTRICT` from `import_session_id` (unchanged from prior revision) |
| Retention | Indefinite — this is the historical-attempt record §10's snapshot invariant relies on |
| Sensitive fields | `error_message` — same bounding/redaction rule as `ImportSession.failure_reason` (§18) |
| Indexes / uniqueness | `INDEX(import_session_id, job_type)` |
| Concurrency / version fields | None on the row itself — the *owning session's* CAS transition (§5) is what prevents duplicate job creation for the same phase attempt |

### 3.4 ValidationFinding

*(persisted as `import_row_errors`, renamed conceptually; public API name: `ValidationFinding` / `ValidationFindingOut`)*

| Property | Value |
|---|---|
| Purpose | One collected validation/business-rule failure or warning, attributed to a specific `ValidationAttempt` (an `ImportJob` of `job_type=VALIDATE`). |
| Primary key | `id` (UUID) |
| Business identifiers | None |
| Ownership | Via `import_job_id` (**replaces** the prior revision's `import_session_id`-only association — the concrete fix for the D3/H5 snapshot problem, §10) |
| Required fields | `import_job_id`, `error_code`, `message`, `severity` |
| Immutable fields | All fields — write-once, append-only, no `TimestampMixin` (unchanged rationale from prior revision) |
| Mutable fields | None |
| Lifecycle/status fields | None — the owning job's `status` is authoritative |
| Relationships | N:1 `ImportJob` |
| Delete policy | `ON DELETE RESTRICT` from `import_job_id` |
| Retention | Indefinite (historical findings, §10) |
| Sensitive fields | `message`/`field` may echo raw legacy source values — treated as sensitive throughout (§18); never included in log output, only in this table behind Administrator-only access |
| Indexes / uniqueness | `INDEX(import_job_id, row_number)` |
| Concurrency / version fields | None — write-once |

### 3.5 ImportAuditEvent — integration with the existing audit log

**Decision:** not a new table. Integrates with the existing `audit_logs` table via `record_audit_event`, `entity_type=AUDIT_ENTITY_IMPORT_SESSION` (existing constant), `entity_id=import_sessions.id`. One new action constant is added: `AUDIT_ACTION_IMPORT_RECOVERY`, used only by the stale-`EXECUTING` recovery case (§7). No other fields, columns, or retention rules change — `AuditLog`'s existing model, retention, and access rules apply unmodified. The `after` JSON payload for both actions must never include raw row-level source content — only aggregate counts (unchanged from the prior revision) or, for recovery, the stale job's id and detected-stale duration.

---

## 4. Import Session Lifecycle and Allowed Transitions

States (unchanged from the prior revision — not flagged by any review; deliberately **not** related to equipment lifecycle states, a separate domain):

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

**Terminal states:** `COMPLETED`, `FAILED`, `CANCELLED` — no transition leaves any of these. A `FAILED` execution does not auto-retry; an operator must dry-run again before another execute attempt (no "retry execute" transition exists).

**Idempotent vs. re-entrant:** re-validate/re-dry-run are re-entrant (genuinely re-run, may produce a different outcome), not idempotent. Session creation is idempotent via `(dataset_type, idempotency_key)` (§12). Execute is idempotent in the strict sense (§14).

**Concurrency requirement:** every phase-starting transition (validate, dry-run, execute) and cancel uses the atomic mechanism in §5 — not only execute.

---

## 5. Atomic Transition and Concurrency Policy

**Decision (unchanged from prior revision): atomic conditional `UPDATE ... WHERE status = ANY(:allowed) RETURNING id`, not `SELECT ... FOR UPDATE`, not a version column.**

```sql
UPDATE import_sessions
SET status = :new_running_status, updated_at = now()
WHERE id = :session_id AND status = ANY(:allowed_from_statuses)
RETURNING id;
```

executed via SQLAlchemy Core, never via load-then-mutate-then-commit. Under PostgreSQL READ COMMITTED, this single statement is atomic — exactly one of two concurrent transitions attempting the same `id`/`allowed_from_statuses` pair affects a row. Zero rows affected means the caller lost the race (or the session is genuinely in the wrong state); it must re-fetch and respond per §14 (execute) or return `409 IMPORT_ATTEMPT_IN_PROGRESS` (if the current status shows the phase is actively `RUNNING`) or `409 IMPORT_SESSION_INVALID_STATE` (any other mismatch) — §19.

**Why compare-and-set over `FOR UPDATE`:** the two-step-commit strategy commits durably after step 1 ("phase started") before step 2 ("do the work") begins; a row lock taken in step 1 releases at that commit and provides no protection for the gap before step 2. Compare-and-set needs no cross-step lock.

**Why not a version column:** every transition already names its required source states explicitly; there is no "any status, but I must have the freshest row" scenario here.

This resolves **PR19A-H3** (original review). `get_or_create_session()`'s SELECT-then-INSERT race is resolved by catching the resulting unique-constraint `IntegrityError`, rolling back, and re-querying — see §12 for the full idempotency contract this composes with.

---

## 6. Fresh-Install / Historical-Upgrade Schema Convergence

Unchanged decision from the prior revision (not flagged again in the second review):

1. `_StrEnum()` must pass `create_constraint=True` so the ORM-driven fresh-install path (`Base.metadata.create_all()`) emits a named CHECK constraint identical to the migration's.
2. The migration must not treat "a table with this name already exists" as success without verification — apply the same **verify → classify → transform / no-op / fail-closed** pattern established by migrations 0013/0014 to every table this feature introduces (`import_sessions`, `import_sources`, `import_jobs`, `import_row_errors`), comparing full catalog definitions (column types, defaults, nullability, `pg_get_constraintdef()`, index definitions), not ORM metadata alone.

**Acceptance criteria (PR19A1 must prove with PostgreSQL tests):** a fresh empty database upgraded directly to head, and a database upgraded historically through 0001→0014 then to head, produce byte-identical `pg_get_constraintdef()` output, identical index definitions, and identical column nullability/defaults for every object this feature introduces. Downgrade → re-upgrade round-trip reproduces the same converged state. A deliberately mismatched pre-existing table causes the migration to fail closed.

This resolves **PR19A-H2** (original review).

---

## 7. Source Persistence, Replay, and Crash Recovery

*(Resolves PR19A-D2, second review.)*

### 7.1 Source persistence — explicit scope boundary

**Decision:** PR19A defines the `ImportSource` entity's **schema and integrity-binding contract** (checksum, descriptive metadata, retention hook) but does **not** implement raw-byte storage or automatic source replay. This is an explicit, stated limitation, not a silent gap: **no code in PR19A1–A3 stores or re-reads source bytes.** A concrete adapter (Roadmap PR19B+) is responsible for its own strategy for making source data available again at dry-run/execute time (re-parsing a durably-referenced external file, its own adapter-owned cache, etc.) — that decision belongs to the concrete adapter's own design, which must in turn bind whatever bytes it reads to the session's `ImportSource.checksum` (verifying the checksum of what it re-reads matches, and failing closed on mismatch) so the "same validated source used at every phase" guarantee holds even though this foundation itself never touches bytes.

This directly answers the review's requirement: because persistence is intentionally deferred, this design does not claim or expose an automatically-resumable validate→dry-run→execute pipeline against arbitrary re-uploaded bytes — only against whatever an adapter's own (out-of-scope-for-this-design) strategy provides, checksum-verified.

### 7.2 Crash recovery — fully specified now, independent of §7.1

Crash recovery does **not** depend on source-byte persistence — it is a status-column mechanism, fully specifiable within this foundation's existing schema.

**Adapter write-boundary invariant (required for recovery to be safe):** every concrete adapter must perform all of its writes through the `db` `AsyncSession` the foundation provides to it, never through a separate connection or an autocommit statement. Because step 2 of the two-step-commit pattern (§5, carried unchanged from the prior revision) is one transaction that only commits on success, a process crash before that commit leaves **nothing** persisted from step 2 — Postgres rolls back an uncommitted transaction automatically when the connection drops. This invariant is what makes the recovery policy below safe without needing to inspect *what* an interrupted attempt was doing.

**Stale-running detection:** a session is *stale-running* when its `status` is one of `VALIDATING` / `DRY_RUN_RUNNING` / `EXECUTING` **and** its current phase's `ImportJob.started_at` is older than `IMPORT_JOB_STALE_THRESHOLD` (a fixed constant, default 15 minutes — generous, since every phase in this foundation runs synchronously within one HTTP request, so a job still `RUNNING` past this threshold almost certainly means the process that started it died).

**Recovery mechanism — lazy, not a background worker (no scheduler exists, §21):** every endpoint that reads or mutates a specific session (`GET /{id}`, `GET /{id}/status`, `POST /{id}/validate`, `POST /{id}/dry-run`, `POST /{id}/execute`, `POST /{id}/cancel`) performs a stale-check **before** any other logic:

1. If the session is stale-running (as defined above), atomically (CAS, §5) transition it: `VALIDATING → VALIDATION_FAILED`, `DRY_RUN_RUNNING → DRY_RUN_FAILED`, or `EXECUTING → FAILED`, with `failure_reason = "stale: recovered after apparent process interruption, no partial state persisted"`.
2. The stale job's own `status` transitions `RUNNING → FAILED` with a matching `error_message`.
3. For `EXECUTING` specifically (the only state where a real write could theoretically have been attempted), write one `AUDIT_ACTION_IMPORT_RECOVERY` entry (§3.5) — for `VALIDATING`/`DRY_RUN_RUNNING` no audit entry is written, consistent with those phases never writing audit entries in normal operation either.
4. The endpoint's original request then fails with `409 IMPORT_RECOVERY_REQUIRED` (§19) — a distinct code from ordinary `IMPORT_SESSION_INVALID_STATE`, telling the caller "this session was just auto-recovered from an apparent interruption; inspect status/findings before retrying," rather than silently proceeding as if nothing happened. Any *subsequent* call against the now-`*_FAILED` session receives the ordinary `409 IMPORT_SESSION_INVALID_STATE` like any other terminal-state mismatch.

**No automatic resume, no new attempt is auto-created:** per §4, `*_FAILED` never auto-retries. An operator must explicitly re-validate/re-dry-run/re-... from the appropriate earlier state, which creates a genuinely new `ImportJob` row — never a silent resumption of the interrupted one. This guarantees no session is stuck indefinitely, and guarantees no duplicate write (per the adapter write-boundary invariant above).

**Slice ownership of this mechanism (§20):** the generic stale-detection helper operates on schema PR19A1 owns (`import_jobs.started_at`, the CAS primitive) and is implemented there; PR19A2 wires it into the `VALIDATING`/`DRY_RUN_RUNNING` endpoints it owns; PR19A3 wires it into `EXECUTING` and adds the recovery-audit write, "completing" recovery coverage across all three running states.

---

## 8. Parser Adapter and Off-Thread Execution Contract

Unchanged decision from the prior revision: `ImportAdapter.parse()` remains synchronous (real parsers are inherently sync/CPU-bound); the **foundation itself** — not a documented aspiration for "a future adapter's own call site" — must invoke it via `await asyncio.to_thread(adapter.parse, raw_input)` inside the same service function that today calls it directly. The `MAX_IMPORT_ROWS` structural bound is checked immediately after `parse()` returns, before any further work.

This resolves **PR19A-H5**'s off-thread half (original review).

---

## 9. Batch Validation and N+1 Prevention

Unchanged decision from the prior revision: split the business-validation hook into two:

1. `async def preload_business_context(self, db, records: list[RawImportRecord]) -> object` — called **once** per validation pass, before the per-record loop. Default: returns `None`. A concrete adapter performs its bulk lookups here (mirroring Roadmap PR12's bulk-lookup precedent) and returns an adapter-defined context object.
2. `def validate_business_rules(self, record: RawImportRecord, context: object) -> list[FieldError]` — **synchronous**, receives only the record and the preloaded context, **no database session parameter** — a structural guarantee against per-record queries, not a convention.

The implementation PR (PR19A2) must provide a test double proving `preload_business_context` is called exactly once per pass and no per-record query occurs.

This resolves **PR19A-H5**'s batch-validation half (original review).

---

## 10. Validation Snapshot Invariant

*(Resolves PR19A-D3, second review; supersedes the prior revision's "latest job by `created_at`" wording.)*

**Required invariant:** a validation response references exactly one completed `ValidationAttempt` (`ImportJob` of `job_type=VALIDATE`), and the following all belong to that same attempt, atomically: source checksum (via `ImportSource`, immutable per §7 — the same for every attempt on a session, so it does not need its own promotion), a `ruleset_version` string (new `import_jobs.ruleset_version` column, VALIDATE-only; an adapter may declare `ruleset_version: str = "1"` as a class attribute, recorded on the job at run time so findings can be traced to which validation logic produced them), `total_rows`/`valid_rows`/`invalid_rows`/`warning_rows`, the `ValidationFinding` rows themselves, and `started_at`/`finished_at`.

**Mechanism — explicit atomic pointer, not inferred ordering:** add `import_sessions.current_validation_job_id` (nullable FK → `import_jobs.id`, `ON DELETE RESTRICT`). This pointer is updated **only** in the same transaction that marks a `VALIDATE` job `SUCCEEDED` and persists its findings/counters — never inferred from `ORDER BY created_at`. This eliminates the tie-break ambiguity entirely (there is nothing to order at read time).

**Promotion rule:** the pointer moves **only** when `ImportJob.status` reaches `SUCCEEDED` — regardless of whether the *session's* resulting status is `VALIDATED` or `VALIDATION_FAILED` (a completed pass that finds blocking errors is still a legitimate "current" result an operator needs to see: the errors are the point). A job that itself crashes (`ImportJob.status = FAILED`, e.g. an unhandled adapter exception) is **never** promoted — the previous `current_validation_job_id` (if any) is left untouched. `ImportJob.status` (did the validation *process* complete) and `ImportSession.status` (did the validated *data* pass or fail business rules) are independent axes; only the former gates promotion.

**In-progress representation:** while `status = VALIDATING`, `current_validation_job_id` still points at the previous successful attempt (if any) — a caller polling mid-run sees the last known-good snapshot, never a half-written one.

**Distinct-row counting (a row may have both):** `invalid_rows = COUNT(DISTINCT row_number WHERE severity='ERROR')`; `warning_rows = COUNT(DISTINCT row_number WHERE severity='WARNING')`. These are independent projections, **not** a mutually exclusive partition — one `row_number` may legitimately appear in both counts (e.g., one field missing = ERROR, a different field borderline-length = WARNING, same row).

**Current vs. historical API contract:** `GET /import-sessions/{id}/errors` defaults to the session's `current_validation_job_id`; an optional `?attempt_id=<uuid>` query parameter (any historical `ImportJob.id` of `job_type=VALIDATE` belonging to that session) returns that attempt's findings instead — satisfying "historical findings remain available" with an actual contract, not just a database-level retention claim. The public field name is `validation_attempt_id` (§3.4's `ImportJob`/`ValidationAttempt` naming), both on `ImportSessionOut` (mirrors `current_validation_job_id`) and on each `ValidationFindingOut` row (mirrors its `import_job_id`).

This resolves **PR19A-H4** (original review) and **PR19A-D3** (second review) together.

---

## 11. Warning vs. Error Semantics

Unchanged decision from the prior revision: partition every pass's `FieldError`s by severity — `blocking_errors` (severity `ERROR`) and `warnings` (severity `WARNING`). A session reaches `VALIDATED` **iff** `blocking_errors` is empty, regardless of `warnings`. Both are persisted as `ValidationFinding` rows (§3.4, §10), both visible via `GET /errors`, but only `blocking_errors`' distinct-row count feeds `invalid_rows` (§10). Dry-run/execute remain gated on `status == VALIDATED`.

This resolves **PR19A-M2**'s warning-semantics half (original review).

---

## 12. Session and Source Idempotency

*(Resolves PR19A-D4, second review — the creation-time and source-registration halves of idempotency. Execute's own idempotency is §14, deliberately separate — see the rationale at the end of this section.)*

### 12.1 Session-creation idempotency (fingerprint)

`POST /import-sessions` accepts `dataset_type`, `idempotency_key` (optional), `source_checksum` (optional — a caller who already knows the checksum may supply it up front), `notes` (optional, free-text, explicitly **excluded** from the fingerprint since it carries no identity meaning).

**Fingerprint:** `SHA-256(canonical_json({dataset_type, source_checksum_or_null_sentinel}))`, computed server-side and stored as `import_sessions.idempotency_fingerprint`. This is intentionally minimal given this foundation's current fields; it is a documented extension point — a future adapter that adds creation-time mapping/options fields must fold their canonical serialization into this same fingerprint computation.

**Behavior:**
- No `idempotency_key` → always create a new session (server-generated identity; no accidental deduplication).
- `idempotency_key` present, no existing `(dataset_type, idempotency_key)` row → create, store the fingerprint, `201`.
- `idempotency_key` present, existing row, fingerprint **matches** → return the existing session, `200` (idempotent replay).
- `idempotency_key` present, existing row, fingerprint **differs** (e.g., a different `source_checksum` supplied under the same key) → `409 IMPORT_IDEMPOTENCY_CONFLICT` (§19) — the existing session is **not** returned or mutated.

**Concurrency:** the existing `(dataset_type, idempotency_key)` unique constraint remains the race-safety mechanism (§5's closing paragraph): a losing concurrent INSERT catches the `IntegrityError`, rolls back, re-queries by key, and *then* performs the fingerprint comparison above against whatever the winner actually persisted — so race-safety and mismatch-detection compose correctly even under concurrent creation.

**Expiry:** idempotency keys do not expire in this foundation — the uniqueness constraint is permanent for the session's lifetime. A TTL-based reuse policy is an explicit future extension, not assumed here.

### 12.2 Source-registration idempotency (immutability)

`POST /import-sessions/{id}/source` registers the full `ImportSource` (§3.2) metadata: `checksum` (if not already supplied at creation), `filename`, `byte_size`, `content_type`.

- If the session has no checksum yet → this call sets it, `201`.
- If a checksum already exists (from creation or a prior `/source` call) and the new call's checksum **matches** → idempotent `200`; any still-unset descriptive fields are filled in, but an already-set value is never overwritten with a different one.
- If checksums **differ** → `409 IMPORT_SOURCE_MISMATCH` (§19).

Once registered, `ImportSource.checksum` is immutable for the life of the session — an operator who picked the wrong file must create a new session, not mutate an existing one's bound source. This directly closes the review's concern ("reusing a key with a different checksum could silently return the previous session") at the layer where checksum actually lives in this revision's endpoint design.

**Why this is split from execute's idempotency (§14):** creation/source-binding idempotency answers "is this the same *request*, replay-safe," a concern that exists the moment a session/source is created, independent of whether any phase has ever run. Execute's idempotency (§14) answers a narrower, later question — "has this specific write already happened" — and is coupled to the single-winner execution claim (§14) rather than to request-payload comparison. Keeping them as separate mechanisms avoids conflating "same input" with "already executed."

---

## 13. Dry-Run Enforcement

*(Resolves PR19A-D5, second review — supersedes the prior revision's "dry-run performs zero writes by contract" assertion.)*

**Primary mechanism: a PostgreSQL read-only transaction**, not developer convention. `run_dry_run()`'s call to `adapter.plan_dry_run(...)` is made against a **separate** `AsyncSession`/connection, scoped only to that call, opened with `SET TRANSACTION READ ONLY` (equivalently, `connection.execution_options(postgresql_readonly=True)`) — not the outer request's normal read-write session. Any write attempt inside `plan_dry_run()` (`INSERT`/`UPDATE`/`DELETE`/DDL) raises `asyncpg.ReadOnlySqlTransactionError` immediately, which the foundation wraps as `IMPORT_DRY_RUN_WRITE_ATTEMPT` (§19) and propagates through the existing exception-handling path (rollback + `DRY_RUN_FAILED`, §5's transaction strategy) — a misbehaving adapter deterministically fails the phase, it cannot silently commit a write.

**Defense in depth (secondary, not safety-critical on its own):** `plan_dry_run()`'s signature is narrowed to accept a read-only-typed interface (a `Protocol` exposing only `execute()`/`scalar()`/`get()` — no `add()`/`delete()`/`commit()`/`flush()`), so the Python-level contract doesn't even advertise write methods to adapter authors. This is a discoverability improvement layered on top of the database-level guarantee, which remains the real enforcement (a determined adapter could still reach an underlying connection via introspection; the database does not care).

**Result persistence without allowing writes during evaluation:** `plan_dry_run()`'s return value (`DryRunPlan`, already a plain in-memory dataclass) is computed entirely within the read-only transaction/connection; that connection is discarded once the call returns. Persisting `session.dry_run_completed_at`/`status = DRY_RUN_COMPLETED` (and, on failure, `DRY_RUN_FAILED`/`failure_reason`) happens via the **outer**, normal read-write session/transaction, strictly *after* the read-only evaluation completes — the same "evaluate under isolation, then persist the outcome via a separate controlled transaction" pattern requested, applied to session-summary persistence (dry-run does not write an audit entry at all, §15, so there is no separate audit-transaction question here).

**Required PostgreSQL tests (PR19A3):** a test adapter whose `plan_dry_run()` deliberately attempts a write through the provided read-only session and asserts it raises and the phase fails; a normal no-op adapter proving the phase still succeeds and produces a plan.

This resolves **PR19A-D5** (second review).

---

## 14. Execute Idempotency and Single-Winner Execution Claim

**Single-winner claim:** the §5 atomic conditional UPDATE, applied specifically to `DRY_RUN_COMPLETED → EXECUTING`, **is** the claim mechanism — no separate token/column. Exactly one of two concurrent `POST .../execute` requests' `UPDATE ... WHERE status = 'dry_run_completed' RETURNING id` affects a row and proceeds to create the `EXECUTE`-type `ImportJob` and call `adapter.execute()` (via the normal read-write session — execute, unlike dry-run, must actually write). The request(s) affecting zero rows must not create a job row and must not call the adapter.

**Execute idempotency (repeat call, not a request-payload comparison — contrast §12):**
- Session already `COMPLETED` → repeat `POST .../execute` returns the existing `ImportSessionOut`, **`200`, not re-executed** — a legitimate outcome of a retried request (e.g., a client timeout after the server-side commit succeeded).
- Session `EXECUTING` (another request currently holds the claim) → `409 IMPORT_ATTEMPT_IN_PROGRESS` (§19).
- Session `FAILED` → `409 IMPORT_SESSION_INVALID_STATE` — per §4, a failed execution requires a fresh dry-run cycle first, never an automatic retry.
- Any other state (dry run never completed) → `409 IMPORT_SESSION_INVALID_STATE`, unchanged.

The distinguishing logic lives in the execute endpoint: when the §5 UPDATE affects zero rows, re-fetch and branch on the session's actual status per the table above.

**Required PostgreSQL test (PR19A3):** a genuine two-connection concurrency test — two simultaneous `execute` calls against the same `DRY_RUN_COMPLETED` session; assert exactly one adapter-execute path ran, exactly one `EXECUTE`-type `ImportJob` row exists, the audit entry (§15) was written exactly once, and the losing request received the deterministic response above — never a duplicate write, never an unhandled exception.

This resolves **PR19A-H3**'s execute-specific half (original review).

---

## 15. Audit Transaction Boundaries

Unchanged from the prior revision, with one addition: exactly one `audit_logs` entry is written by the *winning* execute request, only on `adapter.execute()`'s success, in the **same** transaction/commit as the adapter's writes and the session's `COMPLETED` update. No audit entry for validate, dry-run, cancel, a losing/idempotent-replay execute call, or a failed execute (the `ImportJob(FAILED)` row and `failure_reason` are that outcome's record). **Addition:** exactly one `AUDIT_ACTION_IMPORT_RECOVERY` entry is written when lazy recovery (§7.2) fires against an `EXECUTING` session specifically — no other recovery case writes an audit entry.

---

## 16. Cursor and Pagination Validation

Unchanged decision from the prior revision: `limit: int = Query(default=25, ge=1, le=200)` on both list endpoints (`GET /import-sessions`, `GET /import-sessions/{id}/errors`); every cursor subfield parse (`uuid.UUID(...)`, `int(...)`) is wrapped and re-raised as `InvalidInputError` (→ `400 INVALID_INPUT`, reusing the existing repository-wide code, §19) on any `ValueError`, applied uniformly in the CRUD-layer decoders. Implementation tests must prove `limit=0`/negative `limit` and a malformed cursor subfield are both rejected fail-fast, with no query executed first.

This resolves **PR19A-M1** (original review).

---

## 17. API and RBAC Contract

All ten endpoints below are **Administrator-only** (`ADMINISTRATOR_ONLY_ROLES`, reusing the existing 3-role model — no new role introduced). **Explicit decision:** no other role may view any import-session data (list/summary/status/errors included) in this foundation. Rationale: `ValidationFinding.message`/`ImportSource.filename`/`ImportSession.notes` may echo raw legacy source content (potentially including names or other identifying text, §18) — restricting even read access to Administrator avoids designing a separate, lower-trust view surface before any real data has ever been imported. Broadening read access to Equipment Pool Staff or Read Only is an explicit future Owner Decision, not assumed here.

| # | Method & route | Purpose | Slice |
|---|---|---|---|
| 1 | `POST /import-sessions` | Create (or idempotently return) a session | A1 |
| 2 | `GET /import-sessions` | Cursor-paginated list | A1 |
| 3 | `GET /import-sessions/{id}` | Summary (session + jobs + finding count) | A1 core; extended additively by A2 (`validation_attempt_id`, `warning_rows`) and A3 (execute fields) — not redesigned, purely additive field growth |
| 4 | `GET /import-sessions/{id}/status` | Lightweight, poll-friendly status | A1 |
| 5 | `POST /import-sessions/{id}/source` | Register source checksum/metadata (§3.2, §12.2) | A1 |
| 6 | `POST /import-sessions/{id}/cancel` | Cancel a cancellable session | A1 |
| 7 | `POST /import-sessions/{id}/validate` | Run the validate phase | A2 |
| 8 | `GET /import-sessions/{id}/errors` | Paginated `ValidationFinding`s, current or `?attempt_id=` (§10) | A2 |
| 9 | `POST /import-sessions/{id}/dry-run` | Run the dry-run phase, read-only enforced (§13) | A3 |
| 10 | `POST /import-sessions/{id}/execute` | Run the execute phase, single-winner claim (§14) | A3 |

**Per-endpoint contract:**

1. **`POST /import-sessions`** — Request: `{dataset_type, idempotency_key?, source_checksum?, notes?}`. Response: `ImportSessionOut`. Transitions: none → `CREATED`. Idempotent: yes (§12.1). Codes: `201` created, `200` idempotent replay, `409 IMPORT_IDEMPOTENCY_CONFLICT`. No pagination. No sensitive fields beyond `notes` (echoed back as supplied). No audit.
2. **`GET /import-sessions`** — Request: `dataset_type?`, `limit` (`ge=1,le=200`), `cursor?`. Response: `Page[ImportSessionOut]`. No transitions. Not idempotency-relevant (read-only). Codes: `200`, `400 INVALID_INPUT` (bad `limit`/cursor). Cursor rules: §16. No sensitive fields exposed beyond session-level `notes`. No audit.
3. **`GET /import-sessions/{id}`** — Response: `ImportSessionSummaryOut` (session + jobs + finding count + `validation_attempt_id`). Codes: `200`, `404 IMPORT_SESSION_NOT_FOUND`, `409 IMPORT_RECOVERY_REQUIRED` (if this call triggers lazy recovery, §7.2). No audit.
4. **`GET /import-sessions/{id}/status`** — Response: `ImportSessionStatusOut` (status + timestamps only, no findings). Same codes as #3.
5. **`POST /import-sessions/{id}/source`** — Request: `{checksum, filename?, byte_size?, content_type?}`. Response: `ImportSourceOut`. Idempotent: yes (§12.2). Codes: `201`, `200` idempotent no-op, `404`, `409 IMPORT_SOURCE_MISMATCH`, `409 IMPORT_RECOVERY_REQUIRED`. No audit.
6. **`POST /import-sessions/{id}/cancel`** — Response: `ImportSessionOut`. Transitions: per §4's cancellable set → `CANCELLED`. Codes: `200`, `404`, `409 IMPORT_SESSION_INVALID_STATE`, `409 IMPORT_RECOVERY_REQUIRED`. No audit.
7. **`POST /import-sessions/{id}/validate`** — No request body (no parser exists, §21). Response: `ImportSessionOut`. Transitions: §4. Codes: `200`, `404`, `409 IMPORT_SESSION_INVALID_STATE`, `409 IMPORT_ATTEMPT_IN_PROGRESS`, `409 IMPORT_RECOVERY_REQUIRED`, `422 IMPORT_ADAPTER_NOT_REGISTERED`. No audit.
8. **`GET /import-sessions/{id}/errors`** — Request: `limit` (`ge=1,le=200`), `cursor?`, `attempt_id?` (§10). Response: `Page[ValidationFindingOut]`. Codes: `200`, `404`, `400 INVALID_INPUT`. Sensitive: `message`/`field` may contain legacy source content (§18) — Administrator-only, never logged. No audit.
9. **`POST /import-sessions/{id}/dry-run`** — Response: `ImportSessionOut`. Transitions: §4. Codes: `200`, `404`, `409 IMPORT_SESSION_INVALID_STATE`, `409 IMPORT_ATTEMPT_IN_PROGRESS`, `409 IMPORT_RECOVERY_REQUIRED`, `501 IMPORT_ADAPTER_NOT_IMPLEMENTED`, `409 IMPORT_DRY_RUN_WRITE_ATTEMPT` (§13). No audit (dry-run never audits, §15).
10. **`POST /import-sessions/{id}/execute`** — Response: `ImportSessionOut`. Transitions/idempotency: §14. Codes: `200` (fresh success or idempotent replay), `404`, `409 IMPORT_SESSION_INVALID_STATE`, `409 IMPORT_ATTEMPT_IN_PROGRESS`, `409 IMPORT_RECOVERY_REQUIRED`, `501 IMPORT_ADAPTER_NOT_IMPLEMENTED`, `500 IMPORT_EXECUTION_FAILED`. Audit: exactly one entry on fresh success only (§15).

---

## 18. Security, Privacy, Retention, and Risk Contract

**Do not assume legacy files contain no sensitive data** — the design below treats every piece of source-derived text (filenames, row-error messages, field values) as potentially containing names or other identifying information carried over from AppSheet, throughout.

| Concern | PR19A1–A3 status | Requirement |
|---|---|---|
| Accepted file types | Not applicable — no upload endpoint exists in this foundation | PR19B: adapter-declared allow-list (e.g. `.xlsx`, `.csv`), enforced by content-type/extension check before parsing |
| Maximum source size | Not applicable — `ImportSource.byte_size` exists as a metadata field only | PR19B: reuse Roadmap PR12's cap, including the bounded-*decompressed*-size ("zip-bounds"/H2R) precedent |
| Filename handling | `filename` is opaque descriptive metadata only; never used to construct a filesystem path (no filesystem write happens in this foundation) | PR19B: any storage backend generates its own opaque storage key (UUID/checksum-derived), never derived from the caller-supplied filename |
| Checksum generation | SHA-256, computed **client-side** by whatever caller registers the source; this foundation never sees raw bytes, so it cannot verify independently | PR19B: once byte storage exists, independently recompute and verify the checksum server-side rather than trust the caller's value |
| Malware/content scanning | Out of scope — no bytes handled | PR19B: define a scanning boundary before persisting/parsing; not selected by this design |
| Path traversal | Not reachable (no paths derived from user input) | PR19B: as above (filename handling) |
| Formula/macro handling | Not applicable — no parser exists | PR19B: any Excel adapter disables macro execution, treats formulas as cached/computed values only |
| Storage encryption | Not applicable — no bytes stored | PR19B: whatever backend is chosen matches the deployment's existing at-rest encryption posture — no new requirement invented |
| Source retention | `retention_expires_at` reserved, unused (`NULL`) | No enforcement in this foundation (no scheduler, §21); explicit Owner Decision required before PR19B if automatic deletion is desired |
| Finding/error retention | Retained indefinitely (§10's snapshot history) | No automatic purge |
| PII / employee-name handling | `ValidationFinding.message`/`field`, `ImportSession.notes`/`failure_reason` may contain legacy names/identifying text | Administrator-only access everywhere (§17); never in an `audit_logs.after` payload (§15) |
| Log redaction | New, stricter-than-default rule for this feature | Application logs may include structural facts (session id, job id, row count, error *code*) but never the *contents* of `ValidationFinding.message`, `ImportSession.notes`, or any adapter-reported field value |
| Audit requirements | §15 | Execute success + `EXECUTING`-recovery only |
| Unauthorized access | Administrator-only, all ten endpoints (§17) | No broadening without an explicit Owner Decision |
| Replay attacks | No new authentication layer added; relies on existing session/token auth | Import-domain "replay" (repeating create/execute) is exactly what §12/§14 make safe rather than harmful |
| Duplicate execution | §14 | Primary risk this design's concurrency work targets — fully addressed |
| Denial of service | `MAX_IMPORT_ROWS` (5000, unchanged) bounds validation work; `limit≤200` bounds list responses; no endpoint accepts a file body (source registration is metadata-only JSON) | No upload-size DoS surface exists in PR19A1–A3 |
| Parser bombs / oversized workbooks | Not reachable — no parser exists | PR19B: bounded decompressed size (Roadmap PR12 zip-bounds precedent) |
| Corrupted files | Not reachable | PR19B: `parse()` must catch format-specific exceptions, translate to a structural `FieldError`, never leak a raw parser exception as a 500 |
| Temporary file cleanup | Not applicable — nothing written to disk | PR19B: any temp file used during parsing is cleaned up in a `finally` block, mirroring Roadmap PR12 |
| External network access | No code in this foundation makes outbound calls | PR19B: `preload_business_context`/`validate_business_rules` (§9) are documented as database-only hooks — no adapter may make outbound network calls from them |

**Risk table:**

| Risk | Impact | Mitigation | Owner/slice | Residual risk |
|---|---|---|---|---|
| Duplicate real-world write from concurrent execute | Data corruption / double-import | Single-winner CAS claim (§14) | A3 | Low — depends on correct implementation, covered by mandated concurrency test |
| Stale `*_RUNNING` session stuck forever | Pipeline silently hangs | Lazy stale-recovery (§7.2) | A1 (mechanism), A2/A3 (wiring) | Low-medium — no proactive alerting exists; relies on someone next touching the session |
| Idempotency-key reuse with a different source | Wrong data imported without the operator noticing | Fingerprint mismatch → `409` (§12.1) | A1 | Low |
| Source re-registration with a different checksum | Same, later in the lifecycle | Immutable source + `409` (§12.2) | A1 | Low |
| Sensitive legacy content leaked via logs | Privacy/compliance | Log-redaction rule (above) | A2 (findings), A1 (session notes) | Medium — depends on disciplined adherence; no automated redaction scanner exists |
| Sensitive legacy content over-exposed to an under-privileged role | Privacy/compliance | Administrator-only on all endpoints (§17) | A1 | Low, contingent on no future broadening without an Owner Decision |
| Adapter performs a real write during dry-run | Data corruption during a supposedly safe planning step | Read-only PostgreSQL transaction (§13) | A3 | Low — DB-level enforcement, not convention |
| Adapter performs N+1 per-record queries | Performance/availability | `preload_business_context` contract (§9) | A2 | Medium — relies on future adapters actually using the batch hook |
| Re-validation exposes stale findings as current | Operator acts on outdated error list | Atomic `current_validation_job_id` promotion (§10) | A2 | Low |
| Malformed cursor/pagination input causes a 500 | Availability / stack-trace leak | Fail-fast `INVALID_INPUT` (§16) | A1, A2 | Low |
| Parser bomb / oversized legacy workbook | Resource exhaustion | Deferred to PR19B; bound documented above | PR19B (not this design's slices) | Medium until PR19B implements it — explicitly flagged, not this design's residual risk to close |
| Source bytes never persisted by this foundation | An interrupted pipeline may require a full re-upload/re-validate | Explicitly scoped out (§7.1), not silently implied | PR19B | Medium — accepted trade-off for foundation-only scope; revisit when PR19B is designed |
| Crash during `EXECUTING` with a non-compliant adapter (writes outside the provided session) | Partial/duplicate write not rolled back by our own transaction boundary | Adapter write-boundary invariant is a documented contract obligation (§7.2, §14), not independently enforceable by this foundation | A3 documents it; enforced by future adapter code review | Medium — this foundation cannot force a misbehaving adapter to comply; flagged for concrete-adapter review |

---

## 19. Public Error Codes

| Code | HTTP | Meaning | Owning slice | Notes |
|---|---|---|---|---|
| `IMPORT_SESSION_NOT_FOUND` | 404 | Session id doesn't exist | A1 | Unchanged |
| `IMPORT_SESSION_INVALID_STATE` | 409 | Requested operation invalid from the session's current state | A1 | Deliberately consolidated — no separate code per specific transition (e.g. no `IMPORT_VALIDATION_REQUIRED`); the `detail` string carries the specific reason, matching the existing `DomainError` pattern of one code per *class* of problem |
| `IMPORT_IDEMPOTENCY_CONFLICT` | 409 | Same `(dataset_type, idempotency_key)` reused with a different creation fingerprint | A1 | New — §12.1 |
| `IMPORT_SOURCE_MISMATCH` | 409 | Source already registered for this session with a different checksum | A1 | New — §12.2 |
| `IMPORT_RECOVERY_REQUIRED` | 409 | This request just triggered lazy stale-session recovery | A1 (mechanism); first reachable via A2/A3 | New — §7.2 |
| `IMPORT_ATTEMPT_IN_PROGRESS` | 409 | A concurrent request currently holds the running claim for this phase | A1 (mechanism); first reachable via A2/A3 | New — §5, §14 |
| `IMPORT_ADAPTER_NOT_REGISTERED` | 422 | No adapter registered for this `dataset_type` | A2 | Unchanged, reachable only via validate |
| `IMPORT_ADAPTER_NOT_IMPLEMENTED` | 501 | Adapter doesn't implement dry-run/execute | A3 | Now A3-only, since dry-run moved there |
| `IMPORT_DRY_RUN_WRITE_ATTEMPT` | 409 | Adapter attempted a write during read-only dry-run evaluation | A3 | New — §13 |
| `IMPORT_EXECUTION_FAILED` | 500 | Adapter's `execute()` raised unexpectedly | A3 | Unchanged |
| `INVALID_INPUT` | 400 | Malformed pagination/cursor input | A1 (session list), A2 (errors list) | Reused existing repository-wide code — **not** a new `INVALID_CURSOR` code, for consistency with the convention already established elsewhere in this codebase (PR66-H1/PR70) |

`IMPORT_SOURCE_UNAVAILABLE` (source bytes cannot be re-read) is **reserved but not registered by any PR19A1–A3 endpoint** — no code path in this foundation ever attempts to re-read source bytes (§7.1), so this code has no reachable meaning until a concrete adapter (PR19B) does. It is named here so PR19B's design can reuse it rather than invent an equivalent.

Each code above must be added to `docs/api/ERROR_CODES.md` in the same implementation PR that first makes it reachable (per the owning-slice column) — not deferred to the governance sync, which performs only a final cross-check sweep.

This resolves **PR19A-M2**'s documentation half (original review).

---

## 20. Implementation Slices (Approved Sequence)

Per Owner-approved recovery plan, implementation proceeds in this order once this Design PR is merged, each branching from the design's merged baseline (never from PR #81):

1. **PR19A1 — Schema, session/source model, lifecycle, atomic CAS transitions, session pagination, migration convergence.** Owns: `ImportSession` and `ImportSource` (§3.1–§3.2), the `ImportJob` table shape (§3.3, without the validation-specific `ruleset_version` semantics — that column exists but only A2 populates it), state machine (§4), CAS mechanism (§5), schema-convergence tests (§6), the generic stale-recovery *helper* (§7.2, wired by A2/A3), session-creation and source-registration idempotency (§12), endpoints #1–#6 (§17), and error codes `IMPORT_SESSION_NOT_FOUND`/`IMPORT_SESSION_INVALID_STATE`/`IMPORT_IDEMPOTENCY_CONFLICT`/`IMPORT_SOURCE_MISMATCH`/(mechanism for) `IMPORT_RECOVERY_REQUIRED`/`IMPORT_ATTEMPT_IN_PROGRESS` (§19).
2. **PR19A2 — Adapter contract, off-thread parsing, batch validation, validation attempts/findings, warning semantics, source replay/recovery foundation as assigned.** Owns: `ImportAdapter` ABC + registry, off-thread contract (§8), batch validation/`preload_business_context` (§9), the validation-snapshot mechanism (`current_validation_job_id`, `ruleset_version`, §10), warning/error partitioning (§11), endpoints #7–#8 (§17), wiring the §7.2 recovery helper into `VALIDATING`/`DRY_RUN_RUNNING`, and error code `IMPORT_ADAPTER_NOT_REGISTERED`.
3. **PR19A3 — Dry-run enforcement, execution claim, single-winner execution, idempotency fingerprint (execute-specific), audit, crash-recovery completion.** Owns: the read-only dry-run transaction (§13), the single-winner claim and execute idempotency (§14), endpoints #9–#10 (§17), the `EXECUTING` half of §7.2 (including the recovery-audit write, §15), and error codes `IMPORT_ADAPTER_NOT_IMPLEMENTED`/`IMPORT_DRY_RUN_WRITE_ATTEMPT`/`IMPORT_EXECUTION_FAILED`.
4. **Governance sync** — after all three implementation slices merge: updates `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `docs/DECISION_LOG.md`, and `knowledge/*`; performs the final `docs/api/ERROR_CODES.md` cross-check sweep (§19).

**Note on "idempotency fingerprint" ownership:** §12 (session/source idempotency) is an A1 deliverable — it concerns creation and source-binding, both A1 entities. §14's execute-idempotency (repeat-call-after-`COMPLETED`) is a distinct, later concern tied to the execution claim and is an A3 deliverable. Where the approved slice outline names "idempotency fingerprint" under PR19A3, that refers specifically to §14's execute-idempotency behavior, not §12's creation-time fingerprint.

Each implementation PR must register any new public error code it introduces (§19) and must not implement a concrete parser, legacy data import, or UI.

---

## 21. Non-Goals (Unchanged)

No implementation slice above may include: an Excel/CSV parser; Legacy Equipment/Receive/Issue import; background workers/scheduler; an import wizard or progress UI; a cutover process; raw source-byte storage (§7.1); malware scanning, macro/formula handling, or any other item marked "PR19B" in §18. These remain later Roadmap PR19 slices (concrete adapters) and PR20/PR21 (per-dataset import).

---

## 22. Acceptance Criteria

This design is ready for implementation once an implementer can answer each of the following without guessing — the section that answers it is noted:

- What tables/entities exist and their full contract → §3
- What each endpoint returns, which role may call it → §17
- How source bytes are retained/replayed → §7.1 (explicitly: not by this foundation)
- How process crashes recover → §7.2
- How validation snapshots remain consistent → §10
- How an idempotency mismatch is detected (both creation-time and execute-time) → §12, §14
- How dry-run writes are technically prevented → §13
- Which slice owns each behavior → §20 (and the "Slice" column throughout §17, §19)
