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

Roadmap PR9A (`docs/archive/audits/03-hospital-equipment-pool-workflow-audit.md` §7
"Ward Recording Rules"): the system records only the first receiving ward
for a dispatch, which is normally immutable. This endpoint is the one
narrow, audited exception — it corrects an incorrect original record. **It
does not represent the equipment moving between wards and is not
ward-transfer tracking**; no such concept exists anywhere in this system.

**Auth:** `administrator` or `equipment_pool_staff` (Roadmap PR10's
confirmed 3-role model — `app.api.v1.deps.WARD_CORRECTION_ROLES`, replacing
the earlier Roadmap PR9A temporary `admin`-only rule now that the confirmed
matrix exists). `read_only` is denied with `403`. This does not inherit
permissions from, and is not derived from, which roles dispatch or receipt
happen to trust — it is asserted independently, even though the two
capability groups are the same set today.

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
| `403` | `FORBIDDEN` | Caller's role isn't `administrator`/`equipment_pool_staff` |
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

Two entry points render a "แก้ไขแผนกรับเครื่อง" action, since this
endpoint has no lifecycle-status precondition (see "Works identically
whether the transaction is `open` or `closed`" above) and a
mis-recorded ward may be discovered after the transaction has already
closed:

- `frontend/src/pages/ReturnPage.tsx` — the transaction currently being
  received (`open`).
- `frontend/src/pages/EquipmentDetailPage.tsx`'s transaction-history
  section — every transaction for that equipment, `open` or `closed`,
  sourced from `GET /transactions?equipment_id=` (this file's `list_transactions`
  above; not the equipment status-history endpoint, whose rows carry no
  transaction ID and cannot substitute for one). Pages through the
  response's `next_cursor` via an explicit "โหลดเพิ่มเติม" action rather
  than a single fixed-size page, so a CLOSED transaction beyond the first
  50 rows stays reachable; a failed history fetch shows an explicit error
  with its own "ลองใหม่" retry, distinct from a genuinely empty history.

Both render the shared `frontend/src/components/WardCorrectionAction.tsx`
(the ward-list query's loading/error/retry state and the trigger button —
loading disables the trigger, a failed load shows an explicit error with a
"ลองใหม่" retry instead of opening the dialog) and
`frontend/src/components/WardCorrectionDialog.tsx` (the form, confirmation,
and submission), so the mutation, error-code mapping, and validation logic
exist exactly once. Both are gated on
`frontend/src/hooks/useAuth.ts`'s `canCorrectTransactionWard(user)`
returning true — a frontend-only mirror of this endpoint's
`administrator`/`equipment_pool_staff` gate, for usability, not security;
every error path below (starting with `403`) is still handled explicitly
because the backend remains the sole authority. The dialog enforces the
same reason length/non-blank rules as this page's request-body table above
before submitting, traps keyboard focus while open, and restores focus to
the exact element that opened it on close. On `WARD_CORRECTION_CONFLICT`
it refetches `GET /transactions/{transaction_id}` and displays the newly
committed ward rather than retrying blindly.

## Entry-error corrections (Owner Governance 2026-11-27, D28)

Four actions on `/transactions/{transaction_id}/`, all in the dispatch/receipt
service layer (`app/services/borrow_service.py`), never manual status
maintenance. Roles: `administrator` and `equipment_pool_staff`; `read_only`
gets `403`. Each success writes exactly one audit entry (`transaction_undo`,
`transaction_void`, `transaction_change_device`, `transaction_switch_action`),
committed with the change and **never containing an HN**. The response of every
action is `CorrectionOut`: `{ "transaction": TransactionOut, "new_transaction":
TransactionOut | null }`.

Which event is corrected is derived from the transaction: an `open`
transaction is a **dispatch**; a `closed` transaction with a receipt is a
**receipt**. A transaction closed by D8 re-dispatch (no receipt) is never
the latest and cannot be corrected.

| Action | Body | Effect |
|---|---|---|
| `POST .../undo` | none | One-tap `void` by the operator who saved it, reason `"เลิกทำ"`. Not limited by shift. |
| `POST .../void` | `{ "reason" }` | Dispatch: the transaction becomes `voided`, the device returns to `prior_equipment_status` (legacy rows without it: `available_at_pool`) and a transaction this dispatch closed by D8 re-dispatch (`closed_by_redispatch_transaction_id`) reopens. Receipt: the transaction is reopened (returned/receipt fields cleared; they stay in the audit `before`) and the device goes back to `issued_to_ward`. |
| `POST .../change-device` | `{ "reason", "equipment_id", "acknowledge_status_warning"? }` | Atomically voids the event on the wrong device and records the same event (time, ward, operator, BME keyer label, contact name, checks) on `equipment_id` through the normal `borrow()` / `return_equipment()` rules. A dispatch's HN is moved server-side (decrypted and re-encrypted in the service, cleared on the voided row, never in a response or audit). The voided dispatch gets `corrected_by_transaction_id` = the new transaction. A receipt needs the correct device to have an open transaction. |
| `POST .../switch-action` | `{ "reason", "outcome"? (default `usable`), "ward_id"? }` | Dispatch to receipt: allowed only if the dispatch closed an earlier transaction by re-dispatch (stored link, else the device's earlier re-dispatch-closed transaction); the dispatch is voided, that transaction reopens and is received at the dispatch time with `outcome`; the voided row's `corrected_by_transaction_id` is that transaction. Receipt to dispatch: needs `ward_id`; the receipt is voided (reopened) and a dispatch to `ward_id` is recorded at the receipt time, closing the reopened transaction as a D8 re-dispatch. Operator, contact name and keyer label carry over; accessory checks do not. |

**Voided-row fields** (on `TransactionOut`, `null` unless `status = "voided"`):
`voided_at`, `void_reason`, `corrected_by_transaction_id`; the row also stores
`voided_by_user_id` (not exposed). At dispatch the service stores
`prior_equipment_status` and `closed_by_redispatch_transaction_id`, and a
receipt stores `receipt_saved_at`; legacy rows have `NULL`s.

**Guards** (a violation changes nothing):

- Only the device's **latest non-voided** transaction (most recently saved:
  `created_at`, tie-break `transaction_no`) -> `409 CORRECTION_NOT_LATEST`.
- **State guard**: the device's current state must equal the state the event
  produced (dispatch: `issued_to_ward`; receipt: `available_at_pool` /
  `unavailable_defective` per outcome) -> `409 CORRECTION_STATE_CHANGED`.
- **Permission**: the administrator always; `equipment_pool_staff` only their
  own entry (`borrower_user_id` / `received_by_user_id`) and only within the
  same PR16 `business_date` + shift as the event -> `403 CORRECTION_NOT_PERMITTED`.
- **Reason** is mandatory (1-500 chars after trimming) except for undo -> `422`.
- **Undo window**, measured from the server **save** time, not the business
  time (which can be in the past for legacy-sheet or offline-synced rows):
  a dispatch within 120 s of `created_at`, a receipt within 30 s of
  `receipt_saved_at`; a legacy receipt without `receipt_saved_at` is not
  undoable. Only the operator who saved it (any role) ->
  `409 UNDO_WINDOW_EXPIRED` / `403 CORRECTION_NOT_PERMITTED`.
- `switch-action` with no earlier open transaction -> `409
  SWITCH_ACTION_NOT_AVAILABLE`; receipt to dispatch without `ward_id` -> `400`.
- A voided transaction cannot be received or corrected again -> `409
  TRANSACTION_VOIDED`.

**Visibility.** Voided rows are excluded from every list, count and report
(`GET /transactions` unless `status=voided` or `equipment_id` is given, the
Receive/Issue reports, CSV/XLSX export, daily report/Excel/forms, Standby
summary, monitor, dashboard, cuff balances). `GET /transactions?equipment_id=`
(the equipment history) still lists them with `status = "voided"`. A voided
dispatch's op_id ledger entry stays `applied`, so the legacy sheet sync never
re-applies it. The read-only export API is unchanged by this document.

## See also

- `docs/api/dispatch.md` — create a transaction (`POST /borrow`), list only open ones (`GET /borrow/active`)
- `docs/api/receipt.md` — close a transaction (`POST /return/{transaction_id}`)
- `docs/api/ward-first-entry.md` — Roadmap PR27/PR28: ward-first batch dispatch/receipt, `TransactionOut`'s contact-name/checklist fields, `POST /transactions/{id}/receive-cuffs`, `GET /cuffs/outstanding`
