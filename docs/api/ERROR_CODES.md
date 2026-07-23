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
