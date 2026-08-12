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
| `IMPORT_SESSION_NOT_FOUND` | 404 | `ImportSessionNotFoundError` | Roadmap PR19A1 (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §23): the `import_sessions.id` in the path doesn't resolve (`GET/POST /import-sessions/{id}...`) |
| `IMPORT_SESSION_INVALID_STATE` | 409 | `ImportSessionInvalidStateError` | Roadmap PR19A1: the requested operation is invalid from the session's current `status`, or a concurrent request already won the CAS race (`cancel`) — one consolidated code per class of problem; the `detail` string carries specifics |
| `IMPORT_SOURCE_MISMATCH` | 409 | `ImportSourceMismatchError` | Roadmap PR19A1 (design §6, §15.2): a `POST /import-sessions/{id}/source` submission's identity fingerprint differs from the session's already-frozen source. The row is never mutated in either case |
| `IMPORT_SOURCE_NOT_REGISTERED` | 409 | `ImportSourceNotRegisteredError` | Roadmap PR19A2 (design §6, §23): `POST /import-sessions/{id}/validate` called with no `ImportSource` row registered for this session at all. Checked before any CAS transition is attempted |
| `IMPORT_RECOVERY_REQUIRED` | 409 | `ImportRecoveryRequiredError` | Roadmap PR19A2 (design §9): a mutating call hit a stale lease (pre-check), or a completion write lost its own fencing check after the fact (post-check, §9.4.2 step 5). Never raised for a cleanly-recorded failure or for `TX2` infrastructure failure (those return `200`/`500` respectively). First reachable via `validate` (PR19A2); reachable via PR19A3's `dry-run`/`execute` once shipped |
| `IMPORT_ATTEMPT_IN_PROGRESS` | 409 | `ImportAttemptInProgressError` | Roadmap PR19A2 (design §7, §17): a concurrent request currently holds the running claim for this phase (the session is already `*_RUNNING` and its lease has not expired). Also reachable via PR19A3's `dry-run`/`execute` |
| `IMPORT_ADAPTER_NOT_REGISTERED` | 422 | `ImportAdapterNotRegisteredError` | Roadmap PR19A2 (design §23): no `ImportAdapter` is registered for the session's `dataset_type`. Production ships with an empty adapter registry -- reachable for every real `dataset_type` until a future concrete-adapter slice registers one. Also reachable via PR19A3's `dry-run`/`execute` (the same registry check) |
| `IMPORT_ADAPTER_NOT_IMPLEMENTED` | 501 | `ImportAdapterNotImplementedError` | Roadmap PR19A3 (design §16, §17, §23): an `ImportAdapter` is registered for this `dataset_type`, but does not override `plan_dry_run`/`execute`. Checked before admission -- a not-implemented adapter never enters `*_RUNNING` |
| `IMPORT_EXECUTION_FAILED` | 500 | `ImportExecutionFailedError` | Roadmap PR19A3 (design §17, §21 endpoint #11, §23): `execute`'s own runtime failure was cleanly recorded via a fenced `TX2` (§9.4.2 step 8) -- the one phase where a completed-but-failed attempt is itself the HTTP error, unlike validate/dry-run's `200`. Never raised for a fencing loss (`409 IMPORT_RECOVERY_REQUIRED`) or `TX2` infrastructure failure (the generic `500 INTERNAL_ERROR` envelope) |
| `IMPORT_SOURCE_REGISTRATION_METHOD_NOT_ALLOWED` | 409 | `ImportSourceRegistrationMethodNotAllowedError` | Roadmap PR20A (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md` §6.2): `POST /import-sessions/{id}/source` was called for `dataset_type="equipment_master"`, which requires the single authoritative, server-checksummed upload path (`POST /import-sessions/{id}/source/upload`) instead. Checked as a pure in-memory guard on the already-loaded session's `dataset_type`, before any CRUD call -- no database write is reachable. Every other `dataset_type` is unaffected |

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
