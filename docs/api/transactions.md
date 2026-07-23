# Transactions API

**Purpose:** Request/response contract for read-only transaction listing/lookup.
**Authority:** Documents current behavior in `backend/app/api/v1/transactions.py`, `backend/app/crud/transaction.py`, and `backend/app/schemas/transaction.py`. Not a design proposal.
**Update trigger:** A transactions endpoint's request/response shape or error behavior changes.
**Maintainer:** Repository Owner

Base path: `/api/v1/transactions`. `GET /transactions` and `GET /transactions/{transaction_id}` are read-only — transactions are created and closed exclusively through `docs/api/dispatch.md` (`POST /borrow`) and `docs/api/receipt.md` (`POST /return/{transaction_id}`). `POST /transactions/{transaction_id}/correct-ward` (Roadmap PR9A) is the one narrow exception: a purpose-built, audited correction of a transaction's recorded ward — never a general edit endpoint.

## `GET /transactions` — search/list

Cursor-paginated transaction search, including both open and closed transactions (unlike `GET /borrow/active`, which returns only open ones — see `docs/api/dispatch.md`).

**Auth:** Any authenticated user.

### Query parameters

| Parameter | Type | Notes |
|---|---|---|
| `ward_id` | string (UUID), optional | Plain-string query param, validated by `parse_uuid` — malformed value is `400 INVALID_INPUT` |
| `equipment_id` | string (UUID), optional | Same validation as `ward_id` |
| `status` | string, optional | Compared directly against the stored value (`"open"` or `"closed"`). **Not validated against the `TransactionStatus` enum** — an unrecognized value is not an error, it simply matches zero rows. |
| `limit` | integer, default `25`, max `200` | |
| `cursor` | string, optional | Opaque pagination cursor from a prior response's `next_cursor` |

### Response — `200 OK` (`Page[TransactionOut]`)

```json
{
  "items": [ { "...": "TransactionOut, see docs/api/dispatch.md" } ],
  "next_cursor": "opaque-string-or-null",
  "total": 42
}
```

## `GET /transactions/{transaction_id}` — get one

**Auth:** Any authenticated user.

### Response — `200 OK` (`TransactionOut`)

Same shape as `POST /borrow`'s response (see `docs/api/dispatch.md`).

### Errors

| Status | Code | Cause |
|---|---|---|
| `404` | `TRANSACTION_NOT_FOUND` | `transaction_id` doesn't resolve to a transaction |
| `422` | `VALIDATION_ERROR` | `transaction_id` path parameter isn't a valid UUID (FastAPI-typed path parameter) |

Full status/code reference: `docs/api/ERROR_CODES.md`.

## `POST /transactions/{transaction_id}/correct-ward` — correct a recorded ward

Roadmap PR9A (`docs/audits/03-hospital-equipment-pool-workflow-audit.md` §7
"Ward Recording Rules"): the system records only the first receiving ward
for a dispatch, which is normally immutable. This endpoint is the one
narrow, audited exception — it corrects an incorrect original record. **It
does not represent the equipment moving between wards and is not
ward-transfer tracking**; no such concept exists anywhere in this system.

**Auth:** `admin` only, temporarily — an intentionally conservative
restriction, not the confirmed final matrix. The confirmed 3-role
permission matrix (`docs/audits/03-hospital-equipment-pool-workflow-audit.md`
§10) grants this capability to Administrator **and** Equipment Pool Staff,
but the current 5-role model has no confirmed, evidence-backed equivalent
of Equipment Pool Staff — the workflow audit's own §10 note says
`biomedical_engineer`/`ward_nurse`/`transport_staff` "have no clear place
in this workflow as described." Because ward correction modifies
historical operational data, an inferred mapping is unacceptable, so every
role other than `admin` — `biomedical_engineer`, `ward_nurse`,
`transport_staff`, and `viewer` alike — is denied with `403` until Roadmap
PR10's Role Model Consolidation lands the confirmed 3-role model. This
does not inherit permissions from, and is not derived from, which roles
dispatch or receipt happen to trust. See `app.api.v1.deps.
WARD_CORRECTION_ROLES`'s docstring for the single, centralized constant
PR10 will update.

Works identically whether the transaction is `open` or `closed` — this
corrects historical data, not an in-flight workflow step, so there is no
lifecycle-status precondition. Only `ward_id` changes: no other transaction
field, lifecycle state, `dispatch_type`/`routine_round`, or business-event
timestamp is read or written. Equipment lifecycle state is never touched.

### Request body

```json
{
  "ward_id": "<UUID>",
  "reason": "<non-empty correction reason, max 500 characters>"
}
```

| Field | Notes |
|---|---|
| `ward_id` | Required. A native UUID field — a malformed value is `422 VALIDATION_ERROR` (no bespoke normalization is attempted). |
| `reason` | Required. Trimmed before validation; a blank or whitespace-only value is `422 VALIDATION_ERROR`. Max 500 characters. |

`extra: "forbid"` — an unrecognized field (e.g. an attempt to also change
`status`) is `422 VALIDATION_ERROR`. This is deliberately not a generic
transaction PATCH.

### Response — `200 OK` (`TransactionOut`)

Same shape as `POST /borrow`'s response (see `docs/api/dispatch.md`), with
`ward_id` reflecting the correction.

### Errors

| Status | Code | Cause |
|---|---|---|
| `400` | `INVALID_INPUT` | `ward_id` does not reference an existing ward |
| `403` | `FORBIDDEN` | Caller's role is not Administrator/Equipment-Pool-Staff-equivalent |
| `404` | `TRANSACTION_NOT_FOUND` | `transaction_id` doesn't resolve to a transaction |
| `409` | `WARD_CORRECTION_NOOP` | Submitted `ward_id` equals the transaction's current `ward_id` — rejected as a no-op; no audit entry is written |
| `409` | `WARD_CORRECTION_CONFLICT` | A concurrent correction changed this transaction's `ward_id` after this request read it, before this request's own write — refresh and resubmit against the current state. Distinct from Roadmap PR8C's receipt-flow codes (`RECEIPT_RACE_LOST`/`TRANSACTION_ALREADY_RETURNED`), which this endpoint never reuses |
| `422` | `VALIDATION_ERROR` | Missing/blank `reason`, missing/malformed `ward_id`, or an unrecognized request field |

Full status/code reference: `docs/api/ERROR_CODES.md`.

### Audit

Every successful correction writes exactly one audit entry (the canonical
PR3 writer, `app.core.audit.record_audit_event`) — action
`ward_correction`, entity `borrow_transaction`, capturing the actor, the
target transaction, the previous and new `ward_id`, and the mandatory
`reason`, plus the standard request/correlation/IP/user-agent metadata the
audit framework already captures for every other audited action. The
transaction update and the audit write commit atomically — a failure
writing the audit entry rolls back the ward change too. A rejected
same-ward no-op never writes an audit entry, since nothing changed.

### Concurrency

A single conditional `UPDATE ... WHERE id = :id AND ward_id IS NOT
DISTINCT FROM :expected_ward_id`, decided by affected-row count — the same
shape Roadmap PR8A established for the receipt-close guard
(`app.crud.transaction.close`), applied here to `ward_id` via
`app.crud.transaction.correct_ward`. A request whose expected `ward_id` is
no longer current (a concurrent correction won first) gets
`WARD_CORRECTION_CONFLICT`, never a silently-applied lost update.

### Frontend consumer (Roadmap PR9B)

`frontend/src/pages/ReturnPage.tsx` (the only screen that loads and
displays a `TransactionOut`) shows a "แก้ไขแผนกรับเครื่อง" action and
`frontend/src/components/WardCorrectionDialog.tsx`, but only when
`frontend/src/hooks/useAuth.ts`'s `canCorrectTransactionWard(user)`
returns true — a frontend-only mirror of this endpoint's `admin`-only
gate, for usability, not security; every error path below (starting with
`403`) is still handled explicitly because the backend remains the sole
authority. The dialog enforces the same reason length/non-blank rules as
this page's request-body table above before submitting, and on
`WARD_CORRECTION_CONFLICT` refetches `GET /transactions/{transaction_id}`
and displays the newly committed ward rather than retrying blindly.
Roadmap PR10 updates `canCorrectTransactionWard` alongside
`WARD_CORRECTION_ROLES` when the role mapping is consolidated.

## See also

- `docs/api/dispatch.md` — create a transaction (`POST /borrow`), list only open ones (`GET /borrow/active`)
- `docs/api/receipt.md` — close a transaction (`POST /return/{transaction_id}`)
