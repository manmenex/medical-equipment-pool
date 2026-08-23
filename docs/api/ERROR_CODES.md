# Error Codes

**Purpose:** The single, current catalog of every HTTP status code and application error `code` this backend can return, and what each one means.
**Authority:** Documents current behavior as implemented in `backend/app/main.py`, `backend/app/core/exceptions.py`, `backend/app/core/db_errors.py`, and each router/service. Not a design proposal — if this document and the code disagree, the code is correct and this document is stale.
**Update trigger:** A new error code is introduced, an existing code's status/meaning changes, or the envelope shape changes.
**Maintainer:** Repository Owner

## Response envelope

Every error response — whether raised by application code, FastAPI/Pydantic validation, or an unhandled exception — uses the same base JSON shape (`backend/app/schemas/common.py`'s `ErrorResponse`, enforced by the four exception handlers registered in `backend/app/main.py`):

```json
{
  "detail": "Human-readable message, safe to show to a client.",
  "code": "MACHINE_READABLE_CODE",
  "status": 404
}
```

A `422` validation error additionally includes an `errors` array:

```json
{
  "detail": "Request validation failed.",
  "code": "VALIDATION_ERROR",
  "status": 422,
  "errors": [
    {"field": "equipment_id", "message": "Field required"}
  ]
}
```

`errors[].field` is a dotted path built from Pydantic's error location, with a leading `"body"` segment stripped (e.g. `body.equipment_id` becomes `equipment_id`). Every 422 error deliberately omits Pydantic's own per-error `input`/`ctx` fields — those echo the submitted value verbatim, which would otherwise leak sensitive request data (e.g. a password field) back into the response.

**No error response ever includes:** a stack trace, the underlying exception's message or type, raw SQL, a database constraint name, or any client-submitted value that wasn't already safe to echo. See the "Unhandled exceptions" section below and `app.core.db_errors`'s docstring.

## HTTP status codes used

| Status | Meaning in this API | Typical trigger |
|---|---|---|
| `200` | Success (read or non-creating write) | Normal response |
| `201` | Resource created | `POST /equipment`, `POST /borrow` |
| `204` | Success, no response body | `DELETE /equipment/{id}` |
| `400` | Client input problem | Bad UUID, unknown enum value, dangling foreign-key reference, malformed QR payload |
| `401` | Not authenticated | Missing/invalid/expired bearer token, invalid credentials, invalid refresh token |
| `403` | Authenticated but not authorized | Caller's role is not in the endpoint's allowed-roles list |
| `404` | Resource does not exist | Unknown equipment/transaction/user ID, unknown route |
| `405` | HTTP method not supported on this route | e.g. `DELETE /equipment` (only `GET`/`POST` exist at that path) |
| `409` | Conflict with current state | Equipment not available for dispatch, transaction already returned, lost a concurrent receipt race, a ward-correction request matches the already-current ward (no-op) or lost a concurrent ward-correction race, duplicate unique key, disallowed status transition, unclassifiable integrity violation |
| `422` | Request body/query failed schema validation | Missing required field, wrong type, an unrecognized enum value (e.g. `receipt_outcome` not one of `usable`/`defective`, Roadmap PR8B), a `model_validator` rule (e.g. `routine_round` required exactly when `dispatch_type == "routine_round"`), or an unrecognized field on a schema using `extra: "forbid"` (e.g. the retired `condition` on `ReturnRequest`) |
| `500` | Unexpected server error | Any exception not otherwise handled |
| `503` | Transient resource/timeout condition | Roadmap PR18D: `GET /reports/{report_id}/pdf` rendering did not complete within `app.services.report_pdf_service.RENDER_TIMEOUT_SECONDS`; Roadmap PR18E: `GET /reports/{report_id}/xlsx` generation (including time spent queued for renderer capacity) did not complete within `app.services.report_xlsx_service.RENDER_TIMEOUT_SECONDS` |

## Application error codes (`code` field)

### Authentication (`backend/app/services/auth_service.py` — locally-defined `DomainError` subclasses, not in `core/exceptions.py`)

| Code | Status | Raised when |
|---|---|---|
| `INVALID_CREDENTIALS` | 401 | Login `identifier`/`password` do not match, or the matched user has no assigned role |
| `INVALID_REFRESH_TOKEN` | 401 | Refresh cookie missing, malformed/expired, wrong token type, revoked, or the owning user is gone/inactive/roleless |

### Domain errors (`backend/app/core/exceptions.py`)

| Code | Status | Class | Raised when |
|---|---|---|---|
| `EQUIPMENT_NOT_FOUND` | 404 | `EquipmentNotFoundError` | Equipment ID doesn't resolve (`GET/PATCH/DELETE /equipment/{id}`, QR resolve, dispatch, receipt) |
| `EQUIPMENT_NOT_AVAILABLE` | 409 | `EquipmentNotAvailableError` | Dispatch attempted on equipment not in `available_at_pool` status, or a concurrent dispatch won the unique-index race |
| `TRANSACTION_NOT_FOUND` | 404 | `TransactionNotFoundError` | Transaction ID doesn't resolve (`GET /transactions/{id}`, receipt) |
| `TRANSACTION_ALREADY_RETURNED` | 409 | `TransactionAlreadyReturnedError` | Genuine sequential repeat receipt (Case A) — the transaction's `status` was already not `OPEN` *before* this request even read it (e.g. a reload/re-submit after a receipt that already completed) |
| `RECEIPT_RACE_LOST` | 409 | `ReceiptRaceLostError` | Roadmap PR8C: this request read the transaction as `OPEN` (Case A did not trigger), but a concurrent request won Roadmap PR8A's conditional `UPDATE` race and closed it first (Case B). Distinct code from `TRANSACTION_ALREADY_RETURNED` — same HTTP status, but the requester did nothing wrong here, so "already returned" would misdescribe the cause (`knowledge/adr/ADR-006-receipt-outcome-contract.md`) |
| `DUPLICATE` | 409 | `DuplicateError` | A unique-constraint violation was classified as `unique_violation` (see Integrity error translation below) |
| `RESOURCE_NOT_FOUND` | 404 | `ResourceNotFoundError` | Generic not-found for resources without a dedicated error class (currently: user lookup in `app/api/v1/users.py`) |
| `INVALID_INPUT` | 400 | `InvalidInputError` | Malformed UUID (`app.utils.parsing.parse_uuid`), a foreign-key field that doesn't reference an existing row (`app.core.references.ensure_referenced_row_exists`, or a foreign-key/not-null/check violation caught at flush time), or an unrecognized enum-like value (e.g. unknown `role_name`) — receipt's `receipt_outcome` is no longer in this category as of Roadmap PR8B: it is a typed Pydantic enum, so an unrecognized value is now `422 VALIDATION_ERROR`, not this code (see `docs/api/receipt.md`) |
| `MALFORMED_QR_CODE` | 400 | `MalformedQrCodeError` | Scanned QR payload isn't a valid Item No (empty, too long, URL-shaped, or a retired legacy format) — distinct from `EQUIPMENT_NOT_FOUND`: the QR itself is unreadable, not merely unmatched |
| `INVALID_STATUS_TRANSITION` | 409 | `InvalidStatusTransitionError` | Requested equipment status change isn't in the caller's allowed transition set (see `equipment.md`'s status-transition tables) |
| `WARD_CORRECTION_NOOP` | 409 | `WardCorrectionNoOpError` | Roadmap PR9A: a ward-correction request's `ward_id` equals the transaction's current `ward_id` at the moment it was read — rejected as a no-op, no audit entry written. Distinct from the receipt-flow codes above (`docs/api/transactions.md`) |
| `WARD_CORRECTION_CONFLICT` | 409 | `WardCorrectionConflictError` | Roadmap PR9A: a ward-correction request's conditional update affected zero rows because a concurrent correction changed `ward_id` first. Mirrors `RECEIPT_RACE_LOST`'s conditional-UPDATE-loses-the-race shape, applied to a different column, but deliberately a distinct code — never reused between the two flows |
| `CONFLICT` | 409 | `ConflictError` | Safe fallback for an `IntegrityError` that couldn't be classified into unique/foreign-key/not-null/check |
| `EXPORT_TOO_LARGE` | 422 | `ExportTooLargeError` | Roadmap PR18B (`GET /reports/{report_id}/print-data`): the full filtered result set exceeds `app.services.report_export_service.MAX_EXPORT_ROWS`. Rejected outright — never a partial/truncated document — asking the caller to narrow the applied filters |
| `PDF_RENDER_TIMEOUT` | 503 | `PdfRenderTimeoutError` | Roadmap PR18D (`GET /reports/{report_id}/pdf`): a single render did not complete within `app.services.report_pdf_service.RENDER_TIMEOUT_SECONDS` (design §18's explicit rendering time bound). The request itself was well-formed — a transient/retryable condition, not a client input problem — so this is `503`, not a `4xx` |
| `XLSX_RENDER_TIMEOUT` | 503 | `XlsxRenderTimeoutError` | Roadmap PR18E review round 1, H2 (`GET /reports/{report_id}/xlsx`): a single `.xlsx` generation — including time spent queued for renderer capacity — did not complete within `app.services.report_xlsx_service.RENDER_TIMEOUT_SECONDS` (design §18's explicit rendering time bound, mirroring `PDF_RENDER_TIMEOUT`'s own rationale). `503`, not a `4xx`, for the same reason |
| `IMPORT_SESSION_NOT_FOUND` | 404 | `ImportSessionNotFoundError` | Roadmap PR19A1 (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §23): the `import_sessions.id` in the path doesn't resolve (`GET/POST /import-sessions/{id}...`). Roadmap PR21E0's `legacy-history` route family (`GET/POST /import-sessions/{id}/legacy-history/dry-run-plan...`) also returns this code for a session that exists but is not `dataset_type="legacy_transaction_history"` -- collapsed with the genuinely-unknown-id case so a caller can never learn from this route family alone whether a given `session_id` is a real Equipment Master session |
| `IMPORT_SESSION_INVALID_STATE` | 409 | `ImportSessionInvalidStateError` | Roadmap PR19A1: the requested operation is invalid from the session's current `status`, or a concurrent request already won the CAS race (`cancel`) — one consolidated code per class of problem; the `detail` string carries specifics |
| `IMPORT_SOURCE_MISMATCH` | 409 | `ImportSourceMismatchError` | Roadmap PR19A1 (design §6, §15.2): a `POST /import-sessions/{id}/source` submission's identity fingerprint differs from the session's already-frozen source. The row is never mutated in either case |
| `IMPORT_SOURCE_NOT_REGISTERED` | 409 | `ImportSourceNotRegisteredError` | Roadmap PR19A2 (design §6, §23): `POST /import-sessions/{id}/validate` called with no `ImportSource` row registered for this session at all. Checked before any CAS transition is attempted |
| `IMPORT_RECOVERY_REQUIRED` | 409 | `ImportRecoveryRequiredError` | Roadmap PR19A2 (design §9): a mutating call hit a stale lease (pre-check), or a completion write lost its own fencing check after the fact (post-check, §9.4.2 step 5). Never raised for a cleanly-recorded failure or for `TX2` infrastructure failure (those return `200`/`500` respectively). First reachable via `validate` (PR19A2); reachable via PR19A3's `dry-run`/`execute` once shipped |
| `IMPORT_ATTEMPT_IN_PROGRESS` | 409 | `ImportAttemptInProgressError` | Roadmap PR19A2 (design §7, §17): a concurrent request currently holds the running claim for this phase (the session is already `*_RUNNING` and its lease has not expired). Also reachable via PR19A3's `dry-run`/`execute` |
| `IMPORT_ADAPTER_NOT_REGISTERED` | 422 | `ImportAdapterNotRegisteredError` | Roadmap PR19A2 (design §23): no `ImportAdapter` is registered for the session's `dataset_type`. Production ships with an empty adapter registry -- reachable for every real `dataset_type` until a future concrete-adapter slice registers one. Also reachable via PR19A3's `dry-run`/`execute` (the same registry check) |
| `IMPORT_ADAPTER_NOT_IMPLEMENTED` | 501 | `ImportAdapterNotImplementedError` | Roadmap PR19A3 (design §16, §17, §23): an `ImportAdapter` is registered for this `dataset_type`, but does not override `plan_dry_run`/`execute`. Checked before admission -- a not-implemented adapter never enters `*_RUNNING` |
| `IMPORT_EXECUTION_FAILED` | 500 | `ImportExecutionFailedError` | Roadmap PR19A3 (design §17, §21 endpoint #11, §23): `execute`'s own runtime failure was cleanly recorded via a fenced `TX2` (§9.4.2 step 8) -- the one phase where a completed-but-failed attempt is itself the HTTP error, unlike validate/dry-run's `200`. Never raised for a fencing loss (`409 IMPORT_RECOVERY_REQUIRED`) or `TX2` infrastructure failure (the generic `500 INTERNAL_ERROR` envelope) |
| `IMPORT_SOURCE_REGISTRATION_METHOD_NOT_ALLOWED` | 409 | `ImportSourceRegistrationMethodNotAllowedError` | Roadmap PR20A (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md` §6.2): `POST /import-sessions/{id}/source` was called for `dataset_type="equipment_master"`, which requires the single authoritative, server-checksummed upload path (`POST /import-sessions/{id}/source/upload`) instead. Checked as a pure in-memory guard on the already-loaded session's `dataset_type`, before any CRUD call -- no database write is reachable. Every other `dataset_type` is unaffected |
| `IMPORT_DRY_RUN_PLAN_NOT_FOUND` | 404 | `ImportDryRunPlanNotFoundError` | Roadmap PR20D (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md` §14.6, §21): `GET /import-sessions/{id}/dry-run-plan` found no `active` plan for this session (it has never had a successful dry-run). Read-path/resource-lookup semantics only -- fix round 6: `POST .../dry-run-plan/{plan_id}/confirm` no longer returns this code for any reason (see `IMPORT_DRY_RUN_PLAN_STALE` below). Roadmap PR21E0 reuses this same exception class as-is (never a duplicate PR21-specific error) for the PR21-specific `GET /import-sessions/{id}/legacy-history/dry-run-plan` and `GET .../legacy-history/dry-run-plan/{plan_id}/rows` routes -- both a session with no persisted plan and a `plan_id` that does not belong to the requested session return this code, never a distinguishing one |
| `IMPORT_DRY_RUN_PLAN_STALE` | 409 | `ImportDryRunPlanStaleError` | Roadmap PR20D (design §14.4a, fix round 8/M4), fix round 6: `POST /import-sessions/{id}/dry-run-plan/{plan_id}/confirm` found the plan no longer confirmable -- it is no longer `active` (superseded by a newer dry-run, or already `consumed`/`failed`); the *owning session* has itself moved out of `dry_run_completed` (e.g. a concurrent `cancel` or new dry-run won the race, including `dry_run_failed` from a later attempt); `{plan_id}` does not exist at all; or `{plan_id}` belongs to a *different* session. The design deliberately does not distinguish any of these sub-cases with different codes -- all of them mean the same thing to the client: re-fetch `GET .../dry-run-plan` and review the current plan before confirming again, never silently retried against the same stale `plan_id`. Collapsing the missing/foreign-session cases into this same code (rather than a `404`) is also an intentional information-boundary choice: the confirm endpoint's response alone never lets a caller learn whether a given `plan_id` belongs to another session. `IMPORT_SESSION_INVALID_STATE` remains reserved for endpoints whose operation is not "confirm this specific persisted plan" (e.g. `cancel_session`'s own CAS rejection). Roadmap PR21E0 reuses this same exception class as-is for `POST /import-sessions/{id}/legacy-history/dry-run-plan/{plan_id}/confirm`, delegating directly to `app.crud.legacy_history_dry_run_plan.confirm_plan` (already proven by PR21D1/D2's own tests) |
| `IMPORT_NO_CONFIRMED_PLAN` | 409 | `ImportNoConfirmedPlanError` | Roadmap PR20E (design §14.4a): `POST /import-sessions/{id}/execute` -- `EquipmentMasterAdapter.precheck_execute` found no `active` plan with `confirmed_at IS NOT NULL` for this session, checked **before** `admit_phase_job` runs so no session state changes. Either the operator never confirmed a plan, or their confirmed plan has since been superseded by a newer, not-yet-confirmed dry-run. A cheap, retryable rejection -- confirm the current plan (`POST .../dry-run-plan/{plan_id}/confirm`) and retry `execute`, never a terminal execute failure |
| `LEGACY_MIGRATION_AUTHORITY_NOT_FOUND` | 404 | `LegacyMigrationAuthorityNotFoundError` | Roadmap PR21E0 (Legacy Import Operator API Surface): `GET /legacy-migration-authorities/{authority_id}` or `GET /legacy-migration-authorities?checksum=...` found no matching row. Never distinguishes "checksum has never been seen" from "checksum was seen but never approved" -- both look identical to the caller |
| `LEGACY_MIGRATION_AUTHORITY_SCOPE_CONFLICT` | 409 | `LegacyMigrationAuthorityScopeConflictError` | Roadmap PR21E0: `POST /legacy-migration-authorities` was called with `approved_workbook_sha256` already approved under a *different* `scope`. The checksum is unique at the database level -- one checksum is one governance identity, so reusing it under a different scope would silently reinterpret an existing approval. The caller must use the checksum's existing scope, or approve a genuinely different workbook. An identical `(scope, approved_workbook_sha256)` retry is NOT a conflict -- it returns the existing row (`200`), never this error |
| `RECONCILIATION_RUN_NOT_FOUND` | 404 | `ReconciliationRunNotFoundError` | Roadmap PR22D: `GET /legacy-reconciliation-runs/{run_id}` or `GET /legacy-reconciliation-runs/{run_id}/findings` found no matching row. Also guarded defensively inside `PATCH .../disposition`'s own CRUD helper (`app.crud.legacy_reconciliation.update_finding_disposition`) for the finding's owning run, though structurally unreachable there in practice -- `LegacyReconciliationFinding.run_id` is an `ON DELETE RESTRICT` FK to a row that can never be deleted. Roadmap PR22E reuses this same class as-is for `GET/POST /legacy-reconciliation-runs/{run_id}/sign-off` when `{run_id}` does not exist |
| `RECONCILIATION_FINDING_NOT_FOUND` | 404 | `ReconciliationFindingNotFoundError` | Roadmap PR22D: `GET /legacy-reconciliation-findings/{finding_id}` found no matching row, or `PATCH .../disposition`'s own existence probe found none. Never distinguishes "never existed" from "exists under a different run" for a caller reaching a finding via the nested `GET .../runs/{run_id}/findings` route -- both look identical, mirroring `IMPORT_DRY_RUN_PLAN_NOT_FOUND`'s established information-boundary discipline above |
| `RECONCILIATION_FINDING_VERSION_CONFLICT` | 409 | `ReconciliationFindingVersionConflictError` | Roadmap PR22D: `PATCH /legacy-reconciliation-findings/{finding_id}/disposition`'s CAS `UPDATE ... WHERE id=:id AND version=:expected_version` matched zero rows -- a concurrent Administrator already disposed (or re-disposed) this finding, or the caller's `expected_version` is stale. The caller must re-fetch (`GET .../legacy-reconciliation-findings/{finding_id}`) and retry with the fresh version, never blind-retry the same stale value |
| `RECONCILIATION_FINDING_RUN_NOT_COMPLETED` | 409 | `ReconciliationFindingRunNotCompletedError` | Roadmap PR22D: `PATCH .../disposition` was called while the finding's owning `LegacyReconciliationRun.status` is not `completed` (still `pending`/`running`, or terminally `failed`). A `pending`/`running`/`failed` run has no stable, reviewable finding set yet -- a `failed` run's partial analysis state was never persisted at all, per PR22C's all-or-nothing persistence guarantee |
| `RECONCILIATION_FINDING_SIGNED_OFF` | 409 | `ReconciliationFindingSignedOffError` | Roadmap PR22D: `PATCH .../disposition` was called for a finding whose owning run already has a persisted `LegacyReconciliationSignOff` row. Once a run is signed off, every one of its findings' dispositions becomes permanently immutable -- checked under the same `LegacyReconciliationRun` row lock (`SELECT ... FOR UPDATE`) the mutation itself acquires first, so this can never race a concurrent sign-off creation. Roadmap PR22E's `create_signoff` now takes that exact same first lock step, closing the race this docstring originally described only as a future contract |
| `RECONCILIATION_COVERAGE_MISMATCH` | 409 | `ReconciliationCoverageMismatchError` | Roadmap PR22C: defined but genuinely HTTP-unreachable at that PR's own head (no route called `execute_reconciliation_run`). Roadmap PR22E makes this class HTTP-reachable for the first time -- `POST /legacy-reconciliation-runs/{run_id}/sign-off` calls the shared `app.services.reconciliation.coverage.verify_coverage_integrity` helper (extracted from PR22C's own inline check, used unmodified by both PR22C's engine and this sign-off path) and raises this if the run's bound `LegacyMigrationAuthorityCoverage` artifact no longer exists or its `legacy_coverage_start`/`legacy_coverage_end`/`live_system_start` values no longer exactly match the run's own immutable copies. Never repaired or inferred from `MIN`/`MAX` (OD-PR22-7) |
| `RECONCILIATION_SIGNOFF_NOT_FOUND` | 404 | `ReconciliationSignOffNotFoundError` | Roadmap PR22E: `GET /legacy-reconciliation-runs/{run_id}/sign-off` found an existing run but no persisted `LegacyReconciliationSignOff` row for it -- distinct from `RECONCILIATION_RUN_NOT_FOUND` (the run itself may exist and simply not be signed off yet) |
| `RECONCILIATION_SIGNOFF_ALREADY_EXISTS` | 409 | `ReconciliationSignOffAlreadyExistsError` | Roadmap PR22E: `POST .../sign-off` was called for a run that already has a persisted sign-off (`UNIQUE(run_id)`). A sign-off is never created twice or modified -- the caller must `GET .../sign-off` to read the existing, immutable attestation. Checked under the run's own `SELECT ... FOR UPDATE` lock (structural defense-in-depth against the schema's `UNIQUE` constraint is also translated to this same code, never a raw `IntegrityError`) |
| `RECONCILIATION_SIGNOFF_RUN_NOT_COMPLETED` | 409 | `ReconciliationSignOffRunNotCompletedError` | Roadmap PR22E (OD-PR22-6/design §20 precondition 1): `POST .../sign-off` was called while the run's `status` is not `completed`. Only a closed, immutable run/snapshot may be signed off |
| `RECONCILIATION_SIGNOFF_VERSION_CONFLICT` | 409 | `ReconciliationSignOffVersionConflictError` | Roadmap PR22E (design §20 precondition 8): the caller's `expected_version` no longer matches the run's current `version`, checked under the run's own lock. `LegacyReconciliationRun.version` is bumped only by run-lifecycle transitions, never by an individual finding's disposition change (design §22) -- this specifically detects a stale read of the *run*, distinct from `RECONCILIATION_FINDING_VERSION_CONFLICT` |
| `RECONCILIATION_SIGNOFF_FINDINGS_INCOMPLETE` | 409 | `ReconciliationSignOffFindingsIncompleteError` | Roadmap PR22E (design §20 precondition 5): at least one of the run's findings still has `disposition IS NULL`, evaluated in the same transaction as the sign-off `INSERT`, under the run's own lock. Never exposes individual finding contents -- only that review is incomplete |
| `RECONCILIATION_SIGNOFF_REQUIRES_CORRECTION` | 409 | `ReconciliationSignOffRequiresCorrectionError` | Roadmap PR22E (OD-PR22-6/design §20 precondition 6): at least one of the run's findings is dispositioned `requires_correction`, checked independently of `RECONCILIATION_SIGNOFF_FINDINGS_INCOMPLETE`'s null-disposition check -- satisfying one never substitutes for the other. `accepted_unresolved`/`confirmed_valid`/`confirmed_duplicate` never block sign-off; `requires_correction` always does. When a run has both problems, `RECONCILIATION_SIGNOFF_FINDINGS_INCOMPLETE` takes precedence (checked first) |
| `RECONCILIATION_SIGNOFF_EVIDENCE_INCONSISTENT` | 409 | `ReconciliationSignOffEvidenceInconsistentError` | Roadmap PR22E: the run's own persisted `summary_total_findings` does not match the actual count of `LegacyReconciliationFinding` rows for the run, both counted fresh inside the same transaction as the sign-off `INSERT`. Sign-off never proceeds against evidence it cannot reconcile against itself -- fails closed rather than normalizing |

### FastAPI/Starlette-level errors (`backend/app/main.py`)

| Code | Status | Raised when |
|---|---|---|
| `NOT_AUTHENTICATED` | 401 | Missing bearer credentials, invalid/expired JWT, wrong token type, or the token's user is gone/inactive (`app.api.v1.deps.get_current_user`) — response includes a `WWW-Authenticate: Bearer` header |
| `FORBIDDEN` | 403 | Authenticated caller's role is not in the endpoint's `require_roles(...)` allow-list |
| `NOT_FOUND` | 404 | No route matches the request path |
| `METHOD_NOT_ALLOWED` | 405 | Route exists but not for this HTTP method |
| `HTTP_ERROR` | (varies) | Fallback for any other Starlette `HTTPException` not in the table above — status code is whatever the exception specifies |
| `VALIDATION_ERROR` | 422 | FastAPI/Pydantic request validation failed before reaching route code — includes the `errors` array |
| `INTERNAL_ERROR` | 500 | Any exception not otherwise handled — see below |

## Integrity error translation (`backend/app/core/db_errors.py`)

Several write endpoints wrap their database call in `translate_integrity_error(db, resource=...)`, which catches a raw `sqlalchemy.exc.IntegrityError`, rolls back the session, classifies it by PostgreSQL SQLSTATE (or, on SQLite, by driver message prefix — server-side only, never echoed), and re-raises a safe `DomainError`:

| Classification | SQLSTATE (PostgreSQL) | Resulting error |
|---|---|---|
| Unique violation | `23505` | `DUPLICATE` (409) |
| Foreign key violation | `23503` | `INVALID_INPUT` (400) |
| Not-null violation | `23502` | `INVALID_INPUT` (400) |
| Check violation | `23514` | `INVALID_INPUT` (400) |
| Anything else (e.g. exclusion violation) | other | `CONFLICT` (409) |

A foreign-key violation maps to `400`, not `404` — the resource being written isn't itself missing; one of its fields references a related resource that doesn't exist, which is a client input problem. This is the same contract used by `app.core.references.ensure_referenced_row_exists`'s proactive pre-flush check, so a bad reference gets an identical response whether it's caught before the flush (works on both SQLite and PostgreSQL) or by the database itself at flush time (PostgreSQL only, since SQLite doesn't enforce FK constraints by default).

`borrow_service.borrow` is a documented, narrower exception to the generic mapping above: a unique-index collision on `idx_tx_one_active_borrow` (two concurrent dispatch attempts on the same equipment) maps to `EQUIPMENT_NOT_AVAILABLE` (409) instead of `DUPLICATE`, since "someone else just borrowed this equipment" is the accurate description of that specific race. Any other integrity violation in that same call path still maps to `INVALID_INPUT` (400).

## Unhandled exceptions

Any exception that isn't a `DomainError`, `RequestValidationError`, or `StarletteHTTPException` is caught by a catch-all handler, logged server-side with the full traceback (`logger.exception(...)`), and returned to the client as exactly:

```json
{"detail": "An unexpected error occurred.", "code": "INTERNAL_ERROR", "status": 500}
```

The client never sees the original exception's type, message, or traceback.

## Cross-references

| Endpoint group | Full contract |
|---|---|
| Dispatch (`POST /borrow`, `GET /borrow/active`) | `docs/api/dispatch.md` |
| Receipt (`POST /return/{transaction_id}`) | `docs/api/receipt.md` |
| Equipment (`/equipment/*`) | `docs/api/equipment.md` |
| Transactions (`/transactions/*`) | `docs/api/transactions.md` |
