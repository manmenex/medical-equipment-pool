# Roadmap PR19A — Legacy Import Foundation: Design (Governance)

**Status:** Design only. No runtime code, migration, API, or test file is part of this PR. Nothing in this document has been implemented.
**Repository:** Medical Equipment Pool. Not MEMS, not Recall Monitor.
**Baseline:** `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` (`docs(governance): close Roadmap PR18 printing and export (#79)`) — Roadmap PR18 is fully merged and governance-synced at this commit. This design branches directly from that commit.
**Scope authority:** `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8, "PR19 — Legacy Import Foundation."
**Supersedes:** PR #81 (`feature/pr19a-legacy-import-foundation`, head `c3813bc93f2100dcb06f02ab9e3098faa61e1706`), which bundled this design with runtime implementation in a single commit — flagged merge-blocking by independent review. **PR #81 has already been closed, unmerged** (comment recorded on that PR pointing here); its branch is retained temporarily pending confirmation that every finding below has been transferred and verified.
**Revision history:**
- Rev 1 (head `b142f4d`) resolved PR #81's original findings (atomic transitions, schema convergence, off-thread parsing, batch validation, warning semantics, cursor hygiene, per-PR error-code registration).
- Rev 2 (head `3c0c8d9`) resolved review comment `5165925838` (D1–D5/M1): domain model, API/RBAC/security contract, source-persistence scope boundary, an atomic validation-snapshot pointer, a creation-time idempotency fingerprint, and enforced dry-run read-only isolation.
- **Rev 3 (this revision)** resolves a third review round (H1–H5/M1, this round's findings) and records **Owner Decision: Data Retention Policy** (also recorded in `docs/DECISION_LOG.md`): a lease/heartbeat crash-recovery model replacing GET-triggered mutation, database-enforced concurrency for source registration with a broader identity fingerprint, a database-enforced (not merely application-checked) ownership constraint on the current-validation pointer, a complete physical schema contract for every table, and the approved retention/cleanup contract.

---

## 1. Objective

Design the complete backend architecture required to eventually import historical AppSheet data (Equipment master, Receive history, Issue history) into this system, such that an implementer can answer every question in §24 (Acceptance Criteria) without guessing. No parser, no legacy data import, and no UI are in scope for the resulting implementation slices (§22).

---

## 2. Inputs Reviewed

| Area | Source | What it established |
|---|---|---|
| Roadmap scope | `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8 | PR19 is "Legacy Import Foundation" — architecture only. |
| Engineering process | `docs/ENGINEERING_WORKFLOW.md` §6 | A Design PR must precede implementation and must define the API proposal, data-model direction, security/information boundaries, performance, risks, acceptance criteria, and slices. |
| PR #81 review | GitHub PR #81 comment `5164590001` | Original findings resolved in §6–§7, §10–§11, §18, §21 (unchanged from Rev 1). |
| PR #83 Rev 1 review | GitHub PR #83 comment `5165925838` | D1–D5/M1, resolved in Rev 2 — domain model, API/RBAC, security/risk (§3, §19, §20), source-persistence scope boundary (§8.1), validation-snapshot pointer (§12), creation-time idempotency fingerprint (§14.1), dry-run read-only transaction (§15). |
| PR #83 Rev 2 review | This round's findings, H1–H5/M1 | H1 (unsafe elapsed-time recovery, GET-side-effect risk) → §8.2. H2 (source-registration concurrency) → §14.2. H3 (cross-session validation-pointer ownership) → §4, §12. H4 (incomplete physical schema) → §4. H5 (retention policy) → §9. M1 (slice/terminology/reference reconciliation, `IMPORT_DRY_RUN_WRITE_ATTEMPT` classification) → §22, §15/§20/§21. |
| Owner Decision | This revision | Data retention policy (§9), recorded once in `docs/DECISION_LOG.md`. |
| Prior import precedent | `backend/app/services/import_service.py`, `backend/app/api/v1/inventory_import.py` (Roadmap PR12) | Bounded row count, bulk-lookup validation, safe generic error wrapping, Administrator-only gate, `ge=1` pagination, bounded decompressed-archive size (zip-bounds "H2R"). Reused directly; cited as a forward obligation on the concrete-adapter slice (§20). |
| Schema-hygiene precedent | `backend/alembic/versions/0013_fk_ondelete_policy.py`, `0014_index_naming_convergence.py` | "Verify → classify → transform/no-op/fail-closed" migration pattern; project-wide explicit `ON DELETE RESTRICT` policy. §7 extends both; §4 uses the same discipline for the new composite FK. |
| Pagination precedent | PR66-H1, PR70 | `ge=1` on `limit`; cursor subfields validated before any query, failing `400 INVALID_INPUT`. §18. |
| RBAC precedent | `backend/app/api/v1/deps.py`, `docs/BUSINESS_RULES.md` | 3-role model; `ADMINISTRATOR_ONLY_ROLES` reused, no new role. §19. |
| Timestamp policy precedent | Roadmap PR15B (migration `0012_timezone_conversion`) | Every persisted timestamp is `TIMESTAMPTZ`, UTC-stored. §4 follows this for every new column. |

---

## 3. Domain Model Contract (Conceptual)

This section is the conceptual entity model — purpose, ownership, relationships, and information sensitivity. The literal column-by-column physical schema (types, constraints, indexes) is §4; this section deliberately does not repeat it, per `docs/ENGINEERING_WORKFLOW.md`'s "do not expose ORM/database models directly as API contracts" — the public API vocabulary (§19) is what callers see; this section and §4 are the implementation's own contract.

### 3.1 ImportSession

*(persisted as `import_sessions`)* — one staged import attempt for one dataset type; the root aggregate of the pipeline. Owned by `created_by_user_id` (the Administrator who created it). Relationships: 1:1 `ImportSource` (§3.2); 1:N `ImportJob` (§3.3). Sensitive fields: `notes` (operator free text), `failure_reason` (bounded, generic — §20). Retention: governed by §9, anchored on `terminal_at`.

### 3.2 ImportSource

*(persisted as `import_sources`)* — the integrity-binding identity record for the data a session will validate/import: checksum and descriptive metadata only. **Does not store raw bytes in this foundation** (§8.1). Owned implicitly via the 1:1 owning session. Sensitive fields: `filename` (§20). Retention: governed by §9 — `filename`/`content_type`/`byte_size`/`source_version` are redacted after the retention period; `checksum` is retained (it is a non-reversible identity marker, not source content).

### 3.3 ImportJob — backing entity for ValidationAttempt / DryRunAttempt / ExecutionAttempt

*(persisted as `import_jobs`; public API concept names: `ValidationAttempt`, `DryRunAttempt`, `ExecutionAttempt` — all the same table, discriminated by `job_type`)*

**Why one table, not three:** the three domain concepts share an identical shape (one row per phase execution, with `status`/lease/heartbeat/timestamps) and identical lifecycle semantics (§5). Splitting them would add schema surface with no behavioral difference, contrary to this slice's foundation-only scope. Owned via the 1:N owning session; 1:N `ValidationFinding` (VALIDATE jobs only). Sensitive fields: `error_message` (bounded, generic — §20). Retention: `error_message` is retained (system-outcome text, not source content, §9).

### 3.4 ValidationFinding

*(persisted as `import_row_errors`)* — one collected validation/business-rule failure or warning, attributed to a specific `ValidationAttempt` (an `ImportJob` of `job_type=VALIDATE`) via `import_job_id`. Sensitive fields: `message`/`field` may echo raw legacy source values (§20). Retention: `message`/`field` are redacted after the retention period (§9); `error_code`/`severity`/`row_number` are retained (structural facts, not source content — needed to keep aggregate counts reconcilable after cleanup).

### 3.5 ImportAuditEvent — integration with the existing audit log

Not a new table. Integrates with `audit_logs` via `record_audit_event`, `entity_type=AUDIT_ENTITY_IMPORT_SESSION`, `entity_id=import_sessions.id`. Three action constants: `AUDIT_ACTION_IMPORT` (existing, execute success), `AUDIT_ACTION_IMPORT_RECOVERY` (crash recovery, §8.2), `AUDIT_ACTION_IMPORT_RETENTION_CLEANUP` (new, §9). No other fields, columns, or retention rules on `audit_logs` itself change.

### 3.6 No source-storage reference table

Explicitly not part of this foundation's schema. §8.1 defines why: no code in PR19A1–A3 stores or re-reads source bytes. A future concrete-adapter slice (PR19B) that adds byte storage introduces its own storage-reference schema at that time — not anticipated here beyond the `ImportSource` identity fields already reserved for it (§4.2).

---

## 4. Physical Schema Contract

Every table this feature introduces, complete: exact names, PostgreSQL types, nullability, defaults, keys, constraints, indexes. No implementation PR may add a table, column, or constraint this section does not describe without a design amendment. **These are internal persistence details — never exposed directly as API fields; §19 defines the public vocabulary.**

Conventions applied uniformly: every enum-shaped column is a plain `VARCHAR` with a named `CHECK` constraint (`native_enum=False`, `create_constraint=True` on the ORM side — §7); every timestamp is `TIMESTAMPTZ` (Roadmap PR15B's project-wide policy); every foreign key is `ON DELETE RESTRICT` (Roadmap PR15B's project-wide policy, §7); UUIDs are application-generated (existing `UUIDPKMixin` convention).

### 4.1 `import_sessions`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | NOT NULL | app-generated | PK |
| `dataset_type` | VARCHAR(100) | NOT NULL | — | |
| `status` | VARCHAR(30) | NOT NULL | `'created'` | `CHECK status IN (11 values, §5)` |
| `created_by_user_id` | UUID | NOT NULL | — | FK → `users.id` RESTRICT |
| `idempotency_key` | VARCHAR(200) | NULL | — | |
| `idempotency_fingerprint` | VARCHAR(64) | NULL | — | SHA-256 hex; §14.1. **Not** the raw checksum — the session itself never stores a raw checksum column (single source of truth is `import_sources.checksum`, §4.2) |
| `notes` | TEXT | NULL | — | `CHECK char_length(notes) <= 4000`; redacted after retention (§9) |
| `current_validation_job_id` | UUID | NULL | — | Composite FK, §4.4/§12 |
| `validated_at`, `dry_run_completed_at`, `executed_at` | TIMESTAMPTZ | NULL | — | |
| `terminal_at` | TIMESTAMPTZ | NULL | — | **New (§9).** Set exactly once, the instant `status` becomes `COMPLETED`/`FAILED`/`CANCELLED` — the retention-clock anchor. Never set for `VALIDATION_FAILED`/`DRY_RUN_FAILED` (not terminal, §5) |
| `retention_purged_at` | TIMESTAMPTZ | NULL | — | **New (§9).** Set once cleanup redacts this session; idempotency guard |
| `total_rows`, `valid_rows`, `invalid_rows`, `warning_rows`, `imported_rows` | INTEGER | NULL | — | |
| `failure_reason` | TEXT | NULL | — | `CHECK char_length(failure_reason) <= 2000`; retained after retention (§9 — "final outcome") |
| `created_at`, `updated_at` | TIMESTAMPTZ | NOT NULL | `now()` | |

**Keys/constraints:** PK `id`. `UNIQUE (dataset_type, idempotency_key)`. Composite FK `(id, current_validation_job_id)` → `import_jobs (import_session_id, id)`, `MATCH SIMPLE` (PostgreSQL default — the constraint is not evaluated while `current_validation_job_id IS NULL`), `ON DELETE RESTRICT` (§4.4, §12). `INDEX (dataset_type, status)`. `INDEX (created_by_user_id)`. `INDEX (terminal_at)` (supports the retention-cleanup scan, §9).

### 4.2 `import_sources`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | NOT NULL | app-generated | PK |
| `import_session_id` | UUID | NOT NULL | — | FK → `import_sessions.id` RESTRICT, `UNIQUE` |
| `checksum` | VARCHAR(128) | NOT NULL | — | `CHECK char_length(checksum) >= 32`; immutable once set (§14.2); retained after retention (§9) |
| `byte_size` | BIGINT | NOT NULL | — | **Required in this revision** — part of the source-identity fingerprint (§14.2, H2) |
| `content_type` | VARCHAR(255) | NULL | — | Redacted after retention |
| `filename` | VARCHAR(255) | NULL | — | Redacted after retention (§20) |
| `source_version` | VARCHAR(100) | NULL | — | **New (§14.2, H2).** Caller-supplied source "vintage" marker |
| `options_fingerprint` | VARCHAR(64) | NOT NULL | — | **New (§14.2, H2).** SHA-256 hex of normalized adapter options; this foundation has no options fields yet, so every caller computes the fixed hash of `{}` — never left `NULL`, avoiding NULL-comparison branching (consistent with this design's established `COALESCE`-over-NULL-branching discipline) |
| `source_fingerprint` | VARCHAR(64) | NOT NULL | — | **New (§14.2, H2).** The full composite identity hash — see §14.2 |
| `created_at` | TIMESTAMPTZ | NOT NULL | `now()` | |

**Keys/constraints:** PK `id`. `UNIQUE (import_session_id)`. `INDEX (checksum)` (cross-session duplicate-source heuristic, not enforced unique). FK `import_session_id` → `import_sessions.id` RESTRICT.

**Removed from Rev 2:** the reserved `retention_expires_at` column is dropped — retention is now computed from the owning session's `terminal_at` plus the deployment-configured retention period (§9), not a per-row expiry timestamp. Carrying both would create two competing retention concepts.

### 4.3 `import_jobs`

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | NOT NULL | app-generated | PK |
| `import_session_id` | UUID | NOT NULL | — | FK → `import_sessions.id` RESTRICT |
| `job_type` | VARCHAR(20) | NOT NULL | — | `CHECK job_type IN ('validate','dry_run','execute')` |
| `status` | VARCHAR(20) | NOT NULL | `'pending'` | `CHECK status IN ('pending','running','succeeded','failed','abandoned')` — **`'abandoned'` is new (§8.2, H1):** distinct from `'failed'` — a lease-expiry recovery marks the job `abandoned` (we never observed a real outcome), never `failed` (the phase actually ran and errored) |
| `attempt_number` | INTEGER | NOT NULL | — | **New (§8.2, H1).** Monotonic per `(import_session_id, job_type)`, computed as `COALESCE(MAX(...), 0) + 1` at job-creation time — race-safe because only the session's own CAS-winning caller ever creates a new job row (§6) |
| `lease_owner` | UUID | NULL | — | **New (§8.2, H1).** Opaque token generated fresh when the phase acquires its lease (session's CAS transition into a `*_RUNNING` status succeeds); no meaning beyond "which attempt holds this lease" |
| `lease_expires_at` | TIMESTAMPTZ | NULL | — | **New (§8.2, H1).** `now() + IMPORT_JOB_LEASE_DURATION_SECONDS` (default 300s, deployment-configurable) at acquisition |
| `heartbeat_at` | TIMESTAMPTZ | NULL | — | **New (§8.2, H1).** Set equal to `started_at` at acquisition; not renewed by this foundation's synchronous phases (§8.2 states why this is still safe); reserved for a future asynchronous executor that would renew it alongside `lease_expires_at` |
| `started_at`, `finished_at` | TIMESTAMPTZ | NULL | — | |
| `error_message` | TEXT | NULL | — | `CHECK char_length(error_message) <= 2000`; retained after retention (§9) |
| `ruleset_version` | VARCHAR(50) | NULL | — | VALIDATE jobs only (§12) |
| `created_at` | TIMESTAMPTZ | NOT NULL | `now()` | |

**Keys/constraints:** PK `id`. FK `import_session_id` → `import_sessions.id` RESTRICT. `UNIQUE (import_session_id, id)` — **required for §4.1's composite FK target** (Postgres requires the referenced column tuple of a composite FK to have a matching unique constraint; this is technically redundant with the single-column PK on `id` alone, but Postgres requires the exact tuple `(import_session_id, id)` to be declared unique for the composite FK to be legal — a standard "ownership FK" pattern, not an oversight). `UNIQUE (import_session_id, job_type, attempt_number)` — enforces `attempt_number` is genuinely unique/monotonic per phase. `INDEX (import_session_id, job_type)`. `INDEX (lease_expires_at) WHERE status = 'running'` (partial index — supports the recovery-claim query's "find expired leases" scan efficiently, §8.2).

### 4.4 `import_row_errors` (ValidationFinding)

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | NOT NULL | app-generated | PK |
| `import_job_id` | UUID | NOT NULL | — | FK → `import_jobs.id` RESTRICT |
| `row_number` | INTEGER | NULL | — | |
| `field` | VARCHAR(100) | NULL | — | Redacted after retention (§9, §20) |
| `error_code` | VARCHAR(100) | NOT NULL | — | Retained after retention |
| `message` | TEXT | NOT NULL | — | Redacted after retention — replaced with a fixed placeholder string (`NOT NULL` is preserved; a real `NULL` is never written) |
| `severity` | VARCHAR(10) | NOT NULL | `'error'` | `CHECK severity IN ('error','warning')` |

**Keys/constraints:** PK `id`. FK `import_job_id` → `import_jobs.id` RESTRICT. `INDEX (import_job_id, row_number)`.

**No per-row `redacted_at`:** redaction happens once, per session, in one transaction covering every finding belonging to that session's jobs — the session-level `import_sessions.retention_purged_at` (§4.1) is the single source of truth for "has this session's data been redacted," so a per-row flag would be redundant schema.

### 4.5 The composite ownership foreign key (H3)

```sql
ALTER TABLE import_jobs
  ADD CONSTRAINT uq_import_jobs_session_id UNIQUE (import_session_id, id);

ALTER TABLE import_sessions
  ADD CONSTRAINT fk_import_sessions_current_validation_job
  FOREIGN KEY (id, current_validation_job_id)
  REFERENCES import_jobs (import_session_id, id)
  ON DELETE RESTRICT;
```

**Why this, not a plain single-column FK:** a plain `FOREIGN KEY (current_validation_job_id) REFERENCES import_jobs(id)` only proves the referenced job exists somewhere — nothing stops it from pointing at a job that belongs to a *different* session (an application bug, or corrupted data, could set session A's pointer to session B's job, and the database would not object). The composite FK above requires the tuple `(session.id, session.current_validation_job_id)` to match a row where `import_jobs.import_session_id = session.id` **and** `import_jobs.id = session.current_validation_job_id` simultaneously — ownership is enforced by the database, not only by application code.

**Null behavior:** `MATCH SIMPLE` (PostgreSQL's default for multi-column FKs) means the constraint is not evaluated whenever *any* column in the FK is `NULL`. Since `current_validation_job_id` is `NULL` for a session with no successful validation attempt yet, the constraint is trivially satisfied in that state — exactly the desired behavior; it activates only once `current_validation_job_id` is actually set.

**Transition/publication transaction:** unchanged from §12's promotion rule — the pointer is set in the same transaction that marks a `VALIDATE` job `SUCCEEDED`. The composite FK now *guarantees* whatever gets promoted is genuinely owned by this session, closing the gap even against a hypothetical application bug.

**Fresh-install/historical-upgrade convergence:** the ORM model declares this via a table-level `ForeignKeyConstraint(["id", "current_validation_job_id"], ["import_jobs.import_session_id", "import_jobs.id"])` (composite FKs need a table-level constraint, unlike single-column `ForeignKey()`), and the migration's raw SQL must define the identical constraint — verified by §7's acceptance criteria, extended to cover this object (§4.6's convergence matrix).

**Downgrade:** drop `fk_import_sessions_current_validation_job` (on `import_sessions`) first, then `uq_import_jobs_session_id` (on `import_jobs`) — the latter is safe to drop once nothing references it, and nothing else in this schema depends on that specific composite unique constraint (the single-column PK on `import_jobs.id` remains independently).

**Application checks may supplement, never replace:** the service layer may still assert `job.import_session_id == session.id` in Python before use, purely as a fail-fast without a round trip to discover a constraint violation — but the database constraint above is what is actually authoritative.

### 4.6 Schema-convergence matrix (§7, extended)

The objects most likely to diverge between the ORM fresh-install path and the Alembic historical-upgrade path if not carefully implemented — §7's PostgreSQL tests must assert convergence for each:

| Object | ORM fresh-create source | Migration historical-upgrade source | Convergence requirement |
|---|---|---|---|
| `ck_import_sessions_status` | `_StrEnum(..., create_constraint=True)` | Raw SQL `CHECK` in `CREATE TABLE` | Identical `pg_get_constraintdef()` |
| `ck_import_jobs_status` (incl. `'abandoned'`) | Same | Same | Identical |
| `ck_import_jobs_job_type` | Same | Same | Identical |
| `ck_import_row_errors_severity` | Same | Same | Identical |
| `uq_import_jobs_session_id` `(import_session_id, id)` | `UniqueConstraint` in `__table_args__` | Raw SQL `ADD CONSTRAINT ... UNIQUE` | Identical column order |
| `fk_import_sessions_current_validation_job` (composite) | `ForeignKeyConstraint` in `__table_args__` | Raw SQL `ADD CONSTRAINT ... FOREIGN KEY` | Identical referenced columns, `MATCH SIMPLE`, `ON DELETE RESTRICT` |
| `uq_import_jobs_session_job_type_attempt` `(import_session_id, job_type, attempt_number)` | `UniqueConstraint` | Raw SQL | Identical |
| `ix_import_jobs_lease_expires_at` (partial, `WHERE status='running'`) | `Index(..., postgresql_where=...)` | Raw SQL partial index | Identical predicate text |

---

## 5. Import Session Lifecycle and Allowed Transitions

States (unchanged — deliberately **not** related to equipment lifecycle states, a separate domain):

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

**Terminal states:** `COMPLETED`, `FAILED`, `CANCELLED` — the only three that set `terminal_at` (§4.1, §9). `VALIDATION_FAILED`/`DRY_RUN_FAILED` are **not** terminal (re-validate/re-dry-run remain possible) and never set `terminal_at`. A `FAILED` execution does not auto-retry.

**Concurrency requirement:** every phase-starting transition (validate, dry-run, execute) and cancel uses the atomic mechanism in §6.

---

## 6. Atomic Transition and Concurrency Policy

Unchanged decision: atomic conditional `UPDATE ... WHERE status = ANY(:allowed) RETURNING id`, not `SELECT ... FOR UPDATE`, not a version column.

```sql
UPDATE import_sessions
SET status = :new_running_status, updated_at = now()
WHERE id = :session_id AND status = ANY(:allowed_from_statuses)
RETURNING id;
```

executed via SQLAlchemy Core, never load-then-mutate-then-commit. Zero rows affected means the caller lost the race or the session is genuinely in the wrong state; it must re-fetch and respond per §16 (execute) or return `409 IMPORT_ATTEMPT_IN_PROGRESS`/`409 IMPORT_SESSION_INVALID_STATE` (§21).

**Why compare-and-set over `FOR UPDATE`:** the two-step-commit strategy commits durably after step 1 ("phase started") before step 2 ("do the work") begins; a row lock taken in step 1 releases at that commit. Compare-and-set needs no cross-step lock.

**Why not a version column:** every transition already names its required source states explicitly.

`get_or_create_session()`'s SELECT-then-INSERT race is resolved by catching the unique-constraint `IntegrityError`, rolling back, and re-querying — §14.1.

---

## 7. Fresh-Install / Historical-Upgrade Schema Convergence

Unchanged decision:

1. `_StrEnum()` passes `create_constraint=True` so the ORM-driven fresh-install path emits a named CHECK constraint identical to the migration's.
2. The migration applies the **verify → classify → transform / no-op / fail-closed** pattern (migrations 0013/0014) to every table this feature introduces, comparing full catalog definitions, not ORM metadata alone.

**Acceptance criteria (PR19A1):** a fresh empty database upgraded directly to head, and a database upgraded historically through 0001→0014 then to head, produce byte-identical `pg_get_constraintdef()` output, identical index definitions, and identical column nullability/defaults — including every object in §4.6's convergence matrix. Downgrade → re-upgrade round-trip reproduces the same converged state. A deliberately mismatched pre-existing table fails closed.

---

## 8. Source Persistence and Crash Recovery

### 8.1 Source persistence — explicit scope boundary (unchanged from Rev 2)

PR19A defines `ImportSource`'s schema and integrity-binding contract (checksum, descriptive metadata) but does **not** implement raw-byte storage or automatic source replay. No code in PR19A1–A3 stores or re-reads source bytes. A concrete adapter (PR19B+) is responsible for its own source-replay strategy, binding whatever it reads to `ImportSource.checksum` and failing closed on mismatch.

### 8.2 Crash recovery — lease/heartbeat model (H1, replaces Rev 2's elapsed-time/GET-triggered mechanism)

**Why the Rev 2 mechanism was unsafe:** it inferred a job was dead purely from `started_at` being more than a fixed 15 minutes old, and let a `GET` request (`/status`, `/{id}`) trigger the recovery mutation as a side effect. Elapsed time alone is not proof of process death (a slow but legitimate request could exceed any fixed threshold), and a `GET` must never mutate state, claim a job, or emit an audit event — that violates basic HTTP safety semantics regardless of how generous the threshold is.

**Required contract: GET is side-effect free, always.** `GET /import-sessions`, `GET /{id}`, `GET /{id}/status`, `GET /{id}/errors` never claim, recover, mark a job failed/abandoned, change session state, or emit any mutation or audit event. `GET /{id}/status` **may** report a computed, non-persisted `is_stale: bool` field (`lease_expires_at < now()` for the current job, evaluated only at response-render time) — purely informational, never a side effect.

**Lease/heartbeat fields (§4.3):** `lease_owner`, `lease_expires_at`, `heartbeat_at`, `attempt_number` on `import_jobs`. A phase acquires its lease as part of the same CAS transition that moves the session into a `*_RUNNING` status (§6): `lease_owner` is set to a freshly generated token, `lease_expires_at = now() + IMPORT_JOB_LEASE_DURATION_SECONDS` (default 300s, deployment-configurable), `heartbeat_at = started_at`. This foundation's phases run synchronously within one HTTP request and do not renew the lease mid-request — safe because the default lease duration comfortably exceeds any realistic single-request phase duration (bounded by `MAX_IMPORT_ROWS = 5000`), and a genuinely hung or crashed request will exceed it. A future asynchronous executor would periodically renew both fields (at `IMPORT_JOB_HEARTBEAT_INTERVAL_SECONDS`, also configurable) while doing real work — the schema already supports this; this foundation simply never exercises the renewal path.

**Recovery is a dedicated mutating operation — `POST /import-sessions/{id}/recover` (Administrator-only, new endpoint, §19) — never a side effect of any other call:**

1. **Identify an expired lease and atomically claim it — one statement, not check-then-act:**
   ```sql
   UPDATE import_jobs
   SET status = 'abandoned', finished_at = now(),
       error_message = 'stale: lease expired, process interruption presumed'
   WHERE id = :job_id AND status = 'running' AND lease_expires_at < now()
   RETURNING id;
   ```
   This single statement **is** "confirm the lease has not been renewed" — a renewed lease (later `lease_expires_at`) or an already-finished job (`status` no longer `'running'`) both fail the `WHERE` clause atomically; there is no separate check step to race against.
2. If (and only if) that claim succeeds, atomically transition the owning session in the **same transaction**: `VALIDATING → VALIDATION_FAILED`, `DRY_RUN_RUNNING → DRY_RUN_FAILED`, or `EXECUTING → FAILED` (setting `terminal_at` only for the `FAILED` case, per §5), with `failure_reason = 'recovered: prior attempt abandoned after lease expiry'`. If this session-level CAS affects zero rows (the session moved on for some other reason between the two statements), the **entire transaction rolls back** — recovery is a no-op, not an error, and the job-level claim from step 1 is undone with it.
3. Mark the job `'abandoned'`, not `'failed'` (§4.3) — a genuine business/adapter failure and a lease-expiry recovery are distinguishable outcomes.
4. **No automatic new attempt is created, ever.** Per §5, `*_FAILED` never auto-retries. An operator must explicitly trigger the next phase, which creates a genuinely new `ImportJob` row with an incremented `attempt_number` (§4.3) — recovery's only job is to honestly close out the abandoned attempt, never to open a new one.
5. Emit exactly one `AUDIT_ACTION_IMPORT_RECOVERY` entry (§3.5), in the same transaction, for **any** recovered phase (broadened from Rev 2's execute-only scope) — `after = {job_id, session_id, job_type, attempt_number, lease_expiry_detected_at}`.
6. **Single-winner guarantee preserved:** because both statements above are themselves CAS operations layered on the same atomic-transition mechanism as every other transition (§6), two concurrent `/recover` calls (or a `/recover` racing a legitimate late-finishing worker) behave exactly like any other concurrent transition attempt in this design — exactly one succeeds.

**Response contract:** if a lease was genuinely expired and recovered, `POST /{id}/recover` returns the now-`*_FAILED` session, `200`. If there is no expired lease to recover (session already terminal, or its current job's lease has not expired), it returns `409 IMPORT_SESSION_INVALID_STATE`.

**Other mutating endpoints do not silently recover.** If `validate`/`dry-run`/`execute`/`cancel` is called against a session whose current job's lease has expired (still `*_RUNNING`, but stale), the endpoint performs **no mutation of its own** and returns `409 IMPORT_RECOVERY_REQUIRED` (§21) — the caller must call `/recover` first, then retry. This keeps every mutation attributable to exactly one dedicated, auditable operation.

**Slice ownership:** the lease/heartbeat schema (§4.3), the generic CAS recovery mechanism, and the `/recover` endpoint skeleton belong to **PR19A1** (alongside CAS/schema, consistent with how `IMPORT_ATTEMPT_IN_PROGRESS` was already scoped). **PR19A2** wires lease acquisition into `VALIDATING`/`DRY_RUN_RUNNING`. **PR19A3** wires it into `EXECUTING`, completing recovery coverage across all three running states.

---

## 9. Data Retention

**Owner Decision (recorded once in `docs/DECISION_LOG.md`):** the Repository Owner approved the following Version 1 retention policy. This section is the design's implementation of that decision; `docs/DECISION_LOG.md` is the governance record of the decision itself.

- **Retention clock:** starts at `import_sessions.terminal_at` (§4.1, §5) — set only for `COMPLETED`/`FAILED`/`CANCELLED`. A non-terminal session (including `VALIDATION_FAILED`/`DRY_RUN_FAILED`, which are re-entrant) is never eligible for cleanup.
- **Retention period:** `IMPORT_RETENTION_DAYS`, default **180**, deployment-configurable (an environment/deployment setting, following this project's existing settings-module convention — **not** an Administrator-editable database value in Version 1; no Administrator UI to change retention exists in V1, per the Owner Decision).
- **After the retention period elapses, in one transaction per session:**
  - `ImportSource.filename`, `content_type`, `byte_size`, `source_version` → redacted (set to `NULL`/a fixed placeholder). `checksum` is **retained** (an opaque identity marker, not source content).
  - `ValidationFinding.message`, `field` → redacted (replaced with a fixed placeholder string; `error_code`/`severity`/`row_number` are retained, so aggregate counts remain reconcilable after cleanup).
  - `ImportSession.notes` → redacted.
  - **Retained, unredacted:** session identity (`id`, `dataset_type`, `created_by_user_id`, `created_at`), `ImportSource.checksum`, summary counters (`total_rows`/`valid_rows`/`invalid_rows`/`warning_rows`/`imported_rows`), attempt status/timestamps (`ImportJob.status`/`started_at`/`finished_at`/`attempt_number`), `ImportJob.error_message` and `ImportSession.failure_reason` (final-outcome text — system-generated, bounded, not raw source content), and all audit metadata (`audit_logs` is never touched by cleanup).
  - `import_sessions.retention_purged_at` is set, in the same transaction, as the idempotency guard.
- **No raw source bytes are ever retained by this foundation** (§8.1) — there is nothing to delete at the storage layer in PR19A1–A3. A future PR19B storage backend must delete storage-layer bytes **only after** the database transaction marking the session purged commits — never speculatively before, to avoid a state where the database no longer references bytes that still exist, or vice versa (the same before/after ordering discipline as §14.2's storage-write-before-DB-commit rule for creation, inverted for deletion).
- **Idempotency and failure behavior:** cleanup for one session is one all-or-nothing transaction (every redaction UPDATE plus setting `retention_purged_at`) — it either fully commits or fully rolls back, so a crash mid-cleanup for one session leaves `retention_purged_at` NULL and that session eligible for the next cleanup pass to retry cleanly. Across a batch of many sessions, an interrupted run simply leaves some sessions purged and others not; the next run's `WHERE retention_purged_at IS NULL AND terminal_at < now() - IMPORT_RETENTION_DAYS` filter naturally skips what is already done.
- **Auditability:** exactly one `AUDIT_ACTION_IMPORT_RETENTION_CLEANUP` entry (§3.5) is written per session cleaned, in the same transaction, recording the session id and which fields were redacted — never the redacted content itself. This audit trail is also the minimum signal for operational metrics (a count of cleanup audit entries over time); no separate metrics/dashboard system is introduced (none exists in this project yet, per Roadmap PR15's own scope boundary).
- **Legal hold / manual hold:** explicitly out of scope for Version 1 — no hold column, no override mechanism exists. If ever needed, it is a future, separately-approved extension.
- **Implementation ownership:** the retention-related **schema columns** (`import_sessions.terminal_at`/`retention_purged_at`) are added by **PR19A1** (cheap, no behavior). The **cleanup logic itself is not implemented in this Design PR**, and is explicitly **not** bundled into PR19A1–A3 — it is operational/maintenance in nature and would eventually need a scheduler (out of scope for this foundation's synchronous-only implementation slices). It is assigned to a later, explicitly-named **Retention Cleanup slice** (unscheduled, to be planned after PR19A1–A3, per §22's "Later governance/maintenance" bucket).

---

## 10. Parser Adapter and Off-Thread Execution Contract

Unchanged: `ImportAdapter.parse()` remains synchronous; the foundation itself invokes it via `await asyncio.to_thread(adapter.parse, raw_input)`. The `MAX_IMPORT_ROWS` bound is checked immediately after `parse()` returns.

---

## 11. Batch Validation and N+1 Prevention

Unchanged: `preload_business_context(db, records)` (called once per pass) plus a synchronous, database-session-free `validate_business_rules(record, context)` — a structural guarantee against per-record queries.

---

## 12. Validation Snapshot Invariant

**Required invariant:** a validation response references exactly one completed `ValidationAttempt`, and the following belong to that same attempt, atomically: source checksum (via the immutable `ImportSource`), `ruleset_version`, `total_rows`/`valid_rows`/`invalid_rows`/`warning_rows`, the `ValidationFinding` rows, and `started_at`/`finished_at`.

**Mechanism:** `import_sessions.current_validation_job_id`, promoted **only** in the same transaction that marks a `VALIDATE` job `SUCCEEDED` — never inferred from `ORDER BY created_at`. **Now database-enforced, not merely application-maintained** (§4.5, H3): a composite foreign key requires the referenced job to actually belong to this session.

**Promotion rule:** moves only when `ImportJob.status` reaches `SUCCEEDED`, regardless of whether the session's own resulting status is `VALIDATED` or `VALIDATION_FAILED`. A crashed job (`status = FAILED` or `ABANDONED`, §8.2) is never promoted.

**In-progress representation:** while `status = VALIDATING`, the pointer still shows the previous successful attempt, never a half-written one.

**Distinct-row counting:** `invalid_rows = COUNT(DISTINCT row_number WHERE severity='ERROR')`; `warning_rows = COUNT(DISTINCT row_number WHERE severity='WARNING')` — independent projections; one row may appear in both.

**Current vs. historical API contract:** `GET /{id}/errors` defaults to `current_validation_job_id`; `?attempt_id=<uuid>` returns a historical attempt's findings instead. Public field name: `validation_attempt_id`.

---

## 13. Warning vs. Error Semantics

Unchanged: partition every pass's findings into `blocking_errors` (severity `ERROR`) and `warnings` (severity `WARNING`). `VALIDATED` iff `blocking_errors` is empty, regardless of `warnings`. Both persisted, both visible; only `blocking_errors`' distinct-row count feeds `invalid_rows`.

---

## 14. Session and Source Idempotency

### 14.1 Session-creation idempotency (unchanged from Rev 2)

`POST /import-sessions` accepts `dataset_type`, `idempotency_key?`, `source_checksum?` (used only to compute the fingerprint below — **not persisted as its own column on `import_sessions`**, §4.1), `notes?` (excluded from the fingerprint). Fingerprint: `SHA-256(canonical_json({dataset_type, source_checksum_or_null_sentinel}))`, stored as `idempotency_fingerprint`. No key → always create. Key present, no existing row → create. Key present, matching fingerprint → `200` idempotent replay. Key present, differing fingerprint → `409 IMPORT_IDEMPOTENCY_CONFLICT`. Race-safety: the unique-constraint `IntegrityError` path, unchanged.

### 14.2 Source registration — concurrency-safe binding (H2, rewritten from Rev 2)

**Required invariant:** a session references exactly one immutable source identity. **Source identity/fingerprint** (§4.2) now includes: `checksum`, `byte_size` (both required — the two components explicitly called for as minimum identity), `dataset_type` (from the owning session, folded into the hash to guard against cross-dataset confusion), normalized `filename` (lowercased/trimmed for hashing purposes only — the *stored* `filename` keeps its original casing for display), `source_version`, and `options_fingerprint` (defaults to the hash of `{}` — this foundation has no options fields yet; a forward-compatible extension point identical in spirit to §14.1's). `source_fingerprint = SHA-256(canonical_json({...all of the above...}))`.

**Database-enforced, not "check then insert":** `POST /{id}/source` performs a plain `INSERT` into `import_sources` (never a `SELECT` first to decide whether to insert). The table's `UNIQUE(import_session_id)` constraint (§4.2) is the arbiter:
- **INSERT succeeds** → this is the first (and only) source for this session; `201`.
- **INSERT fails on the unique constraint** → catch the `IntegrityError`, roll back, `SELECT` the now-existing row, and compare `source_fingerprint`:
  - Matches → `200` idempotent no-op (fills in any still-`NULL` non-identity descriptive field, never overwrites an already-set value).
  - Differs → `409 IMPORT_SOURCE_MISMATCH`.

This same insert-then-compare pattern is what makes every required concurrent scenario correct, not just the sequential ones:
- **Two concurrent requests registering the identical source:** both attempt the INSERT; exactly one wins (the DB constraint decides); the loser's re-query finds a matching fingerprint and converges onto the winner's row via the idempotent-`200` branch — one authoritative record results, by construction.
- **Two concurrent requests registering different sources against one session:** same race, same single winner; the loser's re-query finds a *differing* fingerprint and correctly returns `409 IMPORT_SOURCE_MISMATCH` — only one registration can ever succeed for a given session, enforced by the database's unique constraint, not by an application-level check that could race.
- **Replay of the same request:** covered by the idempotent-`200` branch above.

**Checksum trust boundary (forward requirement, §20):** this foundation trusts the caller-supplied checksum (it never sees raw bytes to verify independently). A future PR19B storage backend must independently recompute and verify the checksum once bytes exist, per §20.

**Storage-write/database-commit ordering (forward requirement for PR19B, when byte storage exists — not applicable to PR19A1–A3, which stores no bytes):** the storage write must complete and be independently checksum-verified **before** the `import_sources` row commits. If the database commit then fails, the already-stored (but now unreferenced) bytes must be recorded for deterministic cleanup — e.g., a `storage_key` logged to a cleanup-candidate ledger before the database transaction begins, cleared once the transaction commits. Never the reverse order: never let a database row commit pointing at bytes that were never confirmed durably stored.

**Once registered, `checksum`/`byte_size`/`source_fingerprint` are immutable for the life of the session** — an operator who picked the wrong file must create a new session, not mutate this one's bound source.

**Why split from execute's idempotency (§16):** creation/source-binding idempotency answers "is this the same request, replay-safe" — a concern independent of whether any phase has run. Execute's idempotency (§16) answers "has this specific write already happened," coupled to the single-winner execution claim, not to request-payload comparison.

---

## 15. Dry-Run Enforcement

**Primary mechanism, unchanged: a PostgreSQL read-only transaction.** `run_dry_run()`'s call to `adapter.plan_dry_run(...)` runs against a separate `AsyncSession`, opened `SET TRANSACTION READ ONLY`. Any write attempt raises `asyncpg.ReadOnlySqlTransactionError` immediately, propagating through the existing rollback + `DRY_RUN_FAILED` path (§6).

**Classification of a caught write attempt (M1, revised):** this is **not** a distinct public API error code. From the client's perspective, a dry-run that fails because an adapter attempted a write looks **identical** to a dry-run that failed for any other adapter-raised reason: `200`, session `status = DRY_RUN_FAILED`, a generic `failure_reason` — the existing, already-representable dry-run-failure envelope (§5). No new client-facing HTTP status or public error code is introduced for this case. Internally, the raw exception is recorded as a distinct, security-relevant log/audit marker (`import.dry_run.write_attempt_detected`, a structured log tag — not an HTTP error code) so operators can specifically search for "did any adapter ever attempt a write during dry run" as an anomaly signal, without exposing that distinction to API consumers. This reclassifies what Rev 2 called `IMPORT_DRY_RUN_WRITE_ATTEMPT` from a public code to an internal-only detection marker — it does **not** appear in §21's public error-code table.

**Defense in depth (secondary):** `plan_dry_run()`'s signature is narrowed to a read-only-typed interface (no `add()`/`delete()`/`commit()`/`flush()`) — a discoverability improvement, not the safety-critical layer.

**Result persistence:** computed entirely within the read-only transaction; `session.dry_run_completed_at`/`status` is persisted via the outer, normal read-write session strictly after the read-only evaluation completes.

**Required PostgreSQL tests (PR19A3):** a test adapter that deliberately attempts a write and asserts it raises and the phase fails; a normal no-op adapter proving success.

---

## 16. Execute Idempotency and Single-Winner Execution Claim

**Single-winner claim:** the §6 atomic conditional UPDATE, applied to `DRY_RUN_COMPLETED → EXECUTING`. Exactly one of two concurrent `execute` requests affects a row and proceeds to create the `EXECUTE` job and call `adapter.execute()` (via the normal read-write session).

**Execute idempotency:**
- `COMPLETED` → repeat call returns the existing session, `200`, not re-executed.
- `EXECUTING` (another request holds the claim) → `409 IMPORT_ATTEMPT_IN_PROGRESS`.
- `FAILED` → `409 IMPORT_SESSION_INVALID_STATE` (fresh dry-run required first).
- Any other state → `409 IMPORT_SESSION_INVALID_STATE`.

**Required PostgreSQL test (PR19A3):** a genuine two-connection concurrency test proving exactly one execution, one `EXECUTE` job, one audit entry, and a deterministic response for the loser.

---

## 17. Audit Transaction Boundaries

Unchanged, plus retention: exactly one `audit_logs` entry on winning execute success, same transaction as the write. Exactly one `AUDIT_ACTION_IMPORT_RECOVERY` entry per recovered phase (§8.2, broadened from execute-only). Exactly one `AUDIT_ACTION_IMPORT_RETENTION_CLEANUP` entry per session cleaned (§9). No audit for validate, dry-run, cancel, or a losing/idempotent-replay execute call.

---

## 18. Cursor and Pagination Validation

Unchanged: `limit: int = Query(default=25, ge=1, le=200)`; every cursor subfield parse wrapped and re-raised as `InvalidInputError` (→ `400 INVALID_INPUT`), fail-fast, no query executed first.

---

## 19. API and RBAC Contract

All eleven endpoints (one more than Rev 2 — `/recover` is new, §8.2) are **Administrator-only**. No broadening without an explicit future Owner Decision.

| # | Method & route | Purpose | Slice |
|---|---|---|---|
| 1 | `POST /import-sessions` | Create (or idempotently return) a session | A1 |
| 2 | `GET /import-sessions` | Cursor-paginated list (side-effect free) | A1 |
| 3 | `GET /import-sessions/{id}` | Summary (side-effect free) | A1 core; extended additively by A2/A3 |
| 4 | `GET /import-sessions/{id}/status` | Lightweight status, may report computed `is_stale` (side-effect free, §8.2) | A1 |
| 5 | `POST /import-sessions/{id}/source` | Register source identity, concurrency-safe (§14.2) | A1 |
| 6 | `POST /import-sessions/{id}/cancel` | Cancel a cancellable session | A1 |
| 7 | `POST /import-sessions/{id}/recover` | **New (§8.2).** Dedicated, mutating lease-recovery claim | A1 (mechanism); meaningful once A2/A3 wire running phases |
| 8 | `POST /import-sessions/{id}/validate` | Run the validate phase | A2 |
| 9 | `GET /import-sessions/{id}/errors` | Paginated `ValidationFinding`s (side-effect free) | A2 |
| 10 | `POST /import-sessions/{id}/dry-run` | Run the dry-run phase, read-only enforced | A3 |
| 11 | `POST /import-sessions/{id}/execute` | Run the execute phase, single-winner claim | A3 |

**Per-endpoint contract (changes from Rev 2 only; unlisted endpoints unchanged):**

- **All `GET` endpoints (2, 3, 4, 9):** explicitly side-effect free (§8.2) — no recovery mutation, no audit, regardless of the session's staleness.
- **All mutating endpoints against a stale session (5, 6, 8, 10, 11):** if the session's current job's lease has expired and it is still `*_RUNNING`, the endpoint performs no mutation of its own and returns `409 IMPORT_RECOVERY_REQUIRED` — call `/recover` first.
- **7. `POST /import-sessions/{id}/recover`** — No request body. Response: `ImportSessionOut`. Codes: `200` (recovered), `404`, `409 IMPORT_SESSION_INVALID_STATE` (nothing to recover). Audit: one `AUDIT_ACTION_IMPORT_RECOVERY` entry on success (§17).

---

## 20. Security, Privacy, Retention, and Risk Contract

**Do not assume legacy files contain no sensitive data.**

| Concern | PR19A1–A3 status | Requirement |
|---|---|---|
| Accepted file types | N/A — no upload endpoint | PR19B: adapter-declared allow-list |
| Maximum source size | N/A — `byte_size` is metadata only | PR19B: Roadmap PR12's cap, including bounded-decompressed-size |
| Filename handling | Opaque metadata, never a filesystem path | PR19B: storage backend generates its own opaque key |
| **Checksum trust boundary** | Client-supplied, unverified (this foundation never sees bytes) | PR19B: independently recompute and verify server-side once bytes exist (§14.2) |
| Malware/content scanning | Out of scope | PR19B: define a scanning boundary |
| Path traversal | Not reachable | PR19B: as above |
| Formula/macro handling | N/A — no parser | PR19B: disable macro execution |
| Storage encryption | N/A — no bytes stored | PR19B: match existing at-rest posture |
| **Source retention** | §9 — 180 days post-terminal, deployment-configurable, redact-in-place | Cleanup logic deferred to a later Retention Cleanup slice (§9, §22) |
| **Finding/error retention** | §9 — `message`/`field` redacted post-retention; structural fields retained | Same |
| PII / employee-name handling | `ValidationFinding.message`/`field`, `ImportSource.filename`, `ImportSession.notes` may contain legacy names/identifying text | Administrator-only everywhere; never in `audit_logs.after`; redacted per §9 |
| Log redaction | Structural facts only in logs (ids, counts, error *codes*) | Never the *contents* of `message`/`notes`/any adapter-reported value |
| **Dry-run write-attempt detection** | Internal invariant/security marker, not a public code (§15) | Logged/audited server-side only |
| Audit requirements | §17 | Execute success + recovery + retention-cleanup only |
| Unauthorized access | Administrator-only, all eleven endpoints (§19) | No broadening without an Owner Decision |
| Replay attacks | Existing session/token auth; import-domain replay made safe by §14/§16 | |
| Duplicate execution | §16 | Primary concurrency risk, fully addressed |
| Cross-session data leakage via validation pointer | Database-enforced composite FK (§4.5) | Not merely an application check |
| Denial of service | `MAX_IMPORT_ROWS`, `limit≤200`, no file-body endpoint | No upload-size DoS surface in PR19A1–A3 |
| Parser bombs / oversized workbooks | Not reachable | PR19B: bounded decompressed size |
| Corrupted files | Not reachable | PR19B: catch format-specific exceptions |
| Temporary file cleanup | N/A — nothing written to disk | PR19B: `finally`-block cleanup |
| External network access | No outbound calls anywhere in this foundation | PR19B: adapter hooks remain database-only |

**Risk table (changes from Rev 2 only; unlisted rows unchanged):**

| Risk | Impact | Mitigation | Owner/slice | Residual risk |
|---|---|---|---|---|
| Duplicate write from concurrent execute | Data corruption | Single-winner CAS (§16) | A3 | Low |
| **Process crash leaves a session stuck in a running state** | Pipeline hangs indefinitely | Lease/heartbeat + dedicated `/recover` (§8.2) — **not** elapsed-time GET-triggered | A1 (mechanism), A2/A3 (wiring) | Low — an operator must eventually call `/recover`; no proactive alerting exists |
| **A `GET` request mutates state** | Violates HTTP safety semantics, unpredictable side effects | All GETs are explicitly side-effect free (§8.2) | A1 | Eliminated by design |
| Idempotency-key reuse with a different source | Wrong data imported unnoticed | Fingerprint mismatch → `409` (§14.1) | A1 | Low |
| **Concurrent source registration race** | Two callers could otherwise both believe they registered the session's source | Database-enforced unique constraint + insert-then-compare (§14.2), not check-then-insert | A1 | Low |
| **`current_validation_job_id` points at another session's job** | Cross-session data exposure via a corrupted pointer | Composite FK enforcement (§4.5) | A1 | Low — enforced by the database, not just application code |
| Adapter writes during dry-run | Data corruption during planning | Read-only PostgreSQL transaction (§15) | A3 | Low |
| Adapter N+1 queries | Performance | `preload_business_context` (§11) | A2 | Medium |
| Re-validation exposes stale findings | Wrong error list shown | Atomic pointer promotion (§12) | A2 | Low |
| **Source bytes/PII retained indefinitely** | Privacy/compliance | 180-day retention + redaction (§9) | Schema: A1; cleanup logic: later Retention Cleanup slice | Medium until the cleanup slice is actually implemented — explicitly flagged, not closed by this design alone |
| **Retention cleanup itself fails partway** | Inconsistent redaction state | Per-session all-or-nothing transaction + idempotent retry (§9) | Later Retention Cleanup slice | Low |
| Adapter writes outside the provided session | Partial write survives a crash | Documented adapter contract obligation (§8.2) | A3 documents; enforced by adapter code review | Medium — not independently enforceable by this foundation |

---

## 21. Public Error Codes

| Code | HTTP | Meaning | Owning slice | Notes |
|---|---|---|---|---|
| `IMPORT_SESSION_NOT_FOUND` | 404 | Session id doesn't exist | A1 | |
| `IMPORT_SESSION_INVALID_STATE` | 409 | Requested operation invalid from current state (includes "nothing to recover") | A1 | Consolidated — no per-transition code |
| `IMPORT_IDEMPOTENCY_CONFLICT` | 409 | Same `(dataset_type, idempotency_key)` reused with a different fingerprint | A1 | §14.1 |
| `IMPORT_SOURCE_MISMATCH` | 409 | Source already registered for this session with a different identity fingerprint | A1 | §14.2 — broadened from checksum-only to the full fingerprint |
| `IMPORT_RECOVERY_REQUIRED` | 409 | A mutating call hit a session whose lease has expired; call `/recover` first | A1 (mechanism); reachable via A2/A3 | §8.2 — no longer self-triggering |
| `IMPORT_ATTEMPT_IN_PROGRESS` | 409 | A concurrent request currently holds the running claim | A1 (mechanism); reachable via A2/A3 | §6, §16 |
| `IMPORT_ADAPTER_NOT_REGISTERED` | 422 | No adapter registered for this `dataset_type` | A2 | |
| `IMPORT_ADAPTER_NOT_IMPLEMENTED` | 501 | Adapter doesn't implement dry-run/execute | A3 | |
| `IMPORT_EXECUTION_FAILED` | 500 | Adapter's `execute()` raised unexpectedly | A3 | |
| `INVALID_INPUT` | 400 | Malformed pagination/cursor input | A1, A2 | Reused existing repository-wide code |

**Removed from the public table (M1):** `IMPORT_DRY_RUN_WRITE_ATTEMPT` is **not** a public error code (§15) — reclassified as an internal invariant-violation log/audit marker, never returned to a client.

`IMPORT_SOURCE_UNAVAILABLE` remains reserved but unregistered by any PR19A1–A3 endpoint (§8.1) — no code path here ever attempts to re-read source bytes.

Each code above must be added to `docs/api/ERROR_CODES.md` in the same implementation PR that first makes it reachable — not deferred to the governance sync.

---

## 22. Implementation Slices (Approved Sequence)

Per Owner-approved recovery plan, each branching from the design's merged baseline (never from PR #81):

1. **PR19A1 — Core physical schema; session/source persistence; lifecycle; CAS/lease/heartbeat schema; source-binding constraints; validation-ownership composite FK foundation; session pagination and cursor validation; migration convergence tests.** Owns: `import_sessions`, `import_sources`, `import_jobs` table shapes (§4.1–§4.4, without `ruleset_version` semantics — A2 populates that column), the composite ownership FK (§4.5), state machine (§5), CAS mechanism (§6), schema-convergence tests (§7, §4.6), the lease/heartbeat schema and generic recovery mechanism plus the `/recover` endpoint (§8.2), the `terminal_at`/`retention_purged_at` schema columns (§9 — cleanup logic itself is **not** A1's job), session-creation and source-registration idempotency (§14), endpoints #1–#7 (§19), and error codes `IMPORT_SESSION_NOT_FOUND`/`IMPORT_SESSION_INVALID_STATE`/`IMPORT_IDEMPOTENCY_CONFLICT`/`IMPORT_SOURCE_MISMATCH`/(mechanism for) `IMPORT_RECOVERY_REQUIRED`/`IMPORT_ATTEMPT_IN_PROGRESS`.
2. **PR19A2 — Adapter contract; off-thread parsing; bounded parsing; batch validation; validation attempts/findings; warning semantics; atomic validation-snapshot publication; checksum verification/replay; no N+1 validation.** Owns: `ImportAdapter` ABC + registry, off-thread contract (§10), batch validation/`preload_business_context` (§11), the validation-snapshot mechanism (§12), warning/error partitioning (§13), endpoints #8–#9 (§19), wiring lease acquisition into `VALIDATING`/`DRY_RUN_RUNNING` (§8.2), and error code `IMPORT_ADAPTER_NOT_REGISTERED`.
3. **PR19A3 — Read-only dry run; dry-run result persistence; execution claim; single-winner execution; heartbeat/lease runtime completion; crash recovery completion; audit; timeout/retry behavior.** Owns: the read-only dry-run transaction (§15), the single-winner claim and execute idempotency (§16), endpoints #10–#11 (§19), wiring lease acquisition and recovery into `EXECUTING` (§8.2), the recovery-audit write (§17), and error codes `IMPORT_ADAPTER_NOT_IMPLEMENTED`/`IMPORT_EXECUTION_FAILED`.
4. **Later governance/maintenance — Retention Cleanup slice (unscheduled, after PR19A1–A3).** Owns: the actual retention-cleanup logic and its operational scheduling (§9) — deliberately **not** implemented in this Design PR, and deliberately **not** bundled into PR19A1–A3, since it is maintenance-oriented and would eventually require a scheduler.
5. **Governance sync** — after PR19A1–A3 merge: updates `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `docs/DECISION_LOG.md`, `knowledge/*`; final `docs/api/ERROR_CODES.md` cross-check sweep.

**Terminology note:** "job" (persisted, `import_jobs`) and "attempt" (`ValidationAttempt`/`DryRunAttempt`/`ExecutionAttempt`, the domain-facing name for the same row, §3.3) are used consistently throughout this document — "job" when describing the physical row/schema, "attempt" when describing the domain concept a caller reasons about.

Each implementation PR must register any new public error code it introduces and must not implement a concrete parser, legacy data import, or UI.

---

## 23. Non-Goals

No implementation slice above may include: an Excel/CSV parser; Legacy Equipment/Receive/Issue import; background workers/scheduler (including the retention-cleanup scheduler itself, §9, §22); an import wizard or progress UI; a cutover process; raw source-byte storage (§8.1); malware scanning, macro/formula handling, or any other item marked "PR19B" in §20; legal/manual hold (§9). These remain later Roadmap PR19 slices, PR20/PR21, or an unscheduled maintenance slice.

---

## 24. Acceptance Criteria

- How a running worker proves liveness → §8.2 (lease/heartbeat)
- Who is allowed to recover an expired lease → §8.2 (`/recover`, Administrator-only, dedicated endpoint)
- Why GET cannot mutate state → §8.2 (explicit contract)
- What tables/entities exist, full physical schema → §3, §4
- How concurrent source registration is serialized → §14.2 (database unique constraint, insert-then-compare)
- How checksum and idempotency fingerprints are bound → §14.1, §14.2
- How the database prevents cross-session current-validation references → §4.5 (composite FK)
- What each endpoint returns, which role may call it → §19
- How dry-run writes are technically prevented → §15
- How long source bytes/findings/PII are retained, how cleanup works → §9
- Whether `IMPORT_DRY_RUN_WRITE_ATTEMPT` is public or internal → §15 (internal only)
- Which slice owns every requirement → §22
