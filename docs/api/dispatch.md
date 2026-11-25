# Dispatch API

**Purpose:** Request/response contract for dispatching pool-owned equipment to a ward.
**Authority:** Documents current behavior in `backend/app/api/v1/borrow.py`, `backend/app/schemas/transaction.py`, and `backend/app/services/borrow_service.py`. Not a design proposal.
**Update trigger:** The dispatch endpoint's request/response shape, validation, or error behavior changes.
**Maintainer:** Repository Owner

> **Naming note:** The domain term is **dispatch** (see `knowledge/adr/ADR-005-transaction-model.md`); the route path and Python module are still named `borrow` for historical reasons. Both terms refer to the same operation.

## `POST /api/v1/borrow` — create a dispatch

Creates a new borrow transaction and moves the selected equipment from `available_at_pool` to `issued_to_ward`, atomically. (Amended by Owner Governance 2026-11-25 second set, D8: PR31 will allow dispatch of already-dispatched and `unavailable_defective` equipment on confirmation; `decommissioned` stays blocked. Current behavior below applies until then.)

**Auth:** Bearer token required. Allowed roles (Roadmap PR10's confirmed 3-role model): `administrator`, `equipment_pool_staff` (`app.api.v1.deps.EQUIPMENT_POOL_OPERATION_ROLES`).

### Request body (`BorrowRequest`)

```json
{
  "equipment_id": "3f2b6b9e-...-uuid",
  "ward_id": "8a1c...-uuid",
  "department_id": null,
  "phone_number": null,
  "pickup_location_id": null,
  "dropoff_location_id": null,
  "notes": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `equipment_id` | string (UUID) | Yes | Internal equipment ID, already resolved client-side (QR scan or BCM Code search) — this endpoint never accepts a raw scanned/typed identifier. |
| `ward_id` | string (UUID), min length 1 | Yes | Receiving ward. Required for every dispatch (Roadmap PR7b). |
| `dispatch_type` | `"routine_round"` \| `"on_demand"` \| `null` | No | **Optional since Roadmap PR26** (2026-11-25 D2 amendment): new dispatches omit it and it is stored `NULL`; the shift is derived from the dispatch time instead. Still accepted/validated for backward compatibility with queued offline operations. See `DispatchType` (`backend/app/models/transaction.py`). |
| `routine_round` | `"06:00"` \| `"11:00"` \| `"15:00"` \| `"21:00"` \| `null` | No | Optional since PR26. If supplied it is only valid with `dispatch_type == "routine_round"` (**required** with that type; **rejected** with `"on_demand"` or when `dispatch_type` is omitted) — enforced by a `model_validator`, not just documentation. Fixed four-round MVP schedule (`RoutineRound`); see `docs/HOSPITAL_DOMAIN_MODEL.md` for why this isn't a free-form time. |
| `department_id` | string (UUID) or `null` | No | |
| `phone_number` | string or `null` | No | |
| `pickup_location_id` | string (UUID) or `null` | No | |
| `dropoff_location_id` | string (UUID) or `null` | No | |
| `notes` | string or `null` | No | |

**Deliberately absent fields** (Roadmap PR7b — do not send these; they are rejected, not silently ignored, because `BorrowRequest` uses `model_config = {"extra": "forbid"}`):

- `borrower_name` — (amended by Owner Governance 2026-11-25 second set, D7: an optional ward contact name is planned for PR27; this paragraph describes the current API until then) no longer accepted or required; historical values from before this change remain visible read-only in `TransactionOut.borrower_name`.
- `due_at` — removed from the write path entirely (`knowledge/adr/ADR-005-transaction-model.md` decision 3); historical values remain exportable via the reporting service, not through this API.
- `quantity` — no longer accepted; defaults to `1` at the database level.

### Response — `201 Created` (`TransactionOut`)

```json
{
  "id": "uuid",
  "transaction_no": "TXN-...",
  "equipment": {
    "id": "uuid",
    "asset_number": "AST-1001",
    "equipment_name": "Infusion Pump",
    "status": "issued_to_ward"
  },
  "quantity": 1,
  "borrowed_at": "2026-07-21T10:00:00Z",
  "returned_at": null,
  "borrower_name": null,
  "ward_id": "uuid",
  "dispatch_type": "on_demand",
  "routine_round": null,
  "phone_number": null,
  "receipt_outcome": null,
  "legacy_condition_on_return": null,
  "status": "open",
  "notes": null
}
```

### Non-blocking dispatch (Roadmap PR31, Owner Governance D8)

Dispatch is no longer limited to `available_at_pool` equipment. The request accepts an optional `acknowledge_status_warning` (boolean, default `false`):

- `issued_to_ward` (already dispatched): without the flag -> `409 DISPATCH_STATUS_WARNING`. With it, in one database transaction the previous open transaction is closed by a conditional `UPDATE ... WHERE status = 'open'` (decided by row count, so two concurrent re-dispatches cannot both close it) with `close_reason = "closed by re-dispatch, receipt not recorded"`, then the new transaction is opened; equipment stays `issued_to_ward`. The closed row keeps `returned_at`, `receipt_outcome` and the receiving operator `NULL` (no receipt is fabricated), is audited (`redispatch_close`, entity = the previous transaction), and produces no receipt export event.
- `unavailable_defective`: without the flag -> `409 DISPATCH_STATUS_WARNING`. With it the dispatch proceeds, the new transaction has `dispatched_while_defective = true` (also in its `borrow` audit row) and equipment becomes `issued_to_ward`.
- `decommissioned`: always `409 EQUIPMENT_NOT_AVAILABLE`.

Optional `expected_open_transaction_id` ties the acknowledgement to the open transaction the operator was shown (from `dispatch-check` / the warning `details`); if it is not the equipment's current open transaction the request fails `409 DISPATCH_WARNING_STALE`. The equipment status write is conditional on the status that was validated (`409 EQUIPMENT_STATUS_CHANGED` if it changed concurrently, e.g. a manual decommission; all writes roll back). A re-dispatch's business time is never earlier than the closed transaction's. Receiving a transaction closed by re-dispatch returns `409 TRANSACTION_CLOSED_BY_REDISPATCH`.

`TransactionOut` gains read-only `close_reason` (nullable) and `dispatched_while_defective` (boolean).

**Pre-check:** `GET /api/v1/equipment/{id}/dispatch-check` (any authenticated role, read-only) returns `{equipment_id, status, warning, dispatchable, requires_acknowledgement, current_ward_id, current_ward_name, dispatched_at, open_transaction_id, open_transaction_no, checklist_kind}` (`checklist_kind` since PR28: `standard` | `cryo_cuff`) so a client can show the warning at scan time. `warning` is `null`, `already_dispatched`, `defective` or `decommissioned`.

### Ward contact name, checklist and expected status (Roadmap PR27/PR28)

`BorrowRequest` also accepts optional `ward_contact_name` (D7), `dispatch_checks` (D4/D10 accessory or Cryo-Cuff checklist, whose `cuffs` counts become outstanding cuffs, D11) and `expected_status` (a confirmation for a status that has since changed fails `409 DISPATCH_WARNING_STALE`). `TransactionOut` gains `dispatch_contact_name`, `receipt_contact_name`, `checklist_kind`, `dispatch_checks`, `receipt_checks`. Full contract, the ward-first batch endpoint (`POST /transactions/dispatch-batch`) and cuff tracking: `docs/api/ward-first-entry.md`.

### Errors

| Status | Code | Cause |
|---|---|---|
| `400` | `CHECKLIST_KIND_MISMATCH` | PR28: `dispatch_checks.kind` differs from the equipment's category checklist kind |
| `400` | `INVALID_INPUT` | `equipment_id` or `ward_id` is not a valid UUID; `ward_id` doesn't reference an existing ward (validated proactively, before any equipment-availability check); or (rare) a foreign key stopped existing in the narrow window between that check and the write |
| `404` | `EQUIPMENT_NOT_FOUND` | `equipment_id` doesn't resolve to an equipment row |
| `409` | `DISPATCH_STATUS_WARNING` | Roadmap PR31 (D8): equipment is `issued_to_ward` (already dispatched, receipt not recorded) or `unavailable_defective` and the request did not carry `acknowledge_status_warning: true`. `details` holds `warning` (`already_dispatched` / `defective`), `equipment_status`, `current_ward_id`, `current_ward_name`, `dispatched_at`, `open_transaction_id`, `open_transaction_no` so the UI can warn; nothing is written |
| `409` | `EQUIPMENT_NOT_AVAILABLE` | Equipment is `decommissioned` (never dispatchable, acknowledgement or not); a concurrent dispatch of the same equipment won the race (unique-index collision on `idx_tx_one_active_borrow`); or a re-dispatch lost the conditional close of the previous open transaction to a concurrent receipt/re-dispatch (rolled back, no side effects) |
| `422` | `VALIDATION_ERROR` | Missing required field, wrong type, an unrecognized field (`borrower_name`/`due_at`/`quantity`/anything else not in the schema), or a legacy `routine_round` supplied inconsistently with `dispatch_type` |
| `401` / `403` | `NOT_AUTHENTICATED` / `FORBIDDEN` | Missing/invalid token, or caller's role isn't `administrator`/`equipment_pool_staff` |

A bad `ward_id` reference is deliberately a `400 INVALID_INPUT`, not the `409 EQUIPMENT_NOT_AVAILABLE` conflict response — a missing ward is a client input error, not an equipment-availability conflict (see the comment in `borrow_service.borrow` referencing this repository's PR20 review round 1, finding MAJOR 3).

Full status/code reference: `docs/api/ERROR_CODES.md`.

## `GET /api/v1/borrow/active` — list active dispatches

Returns every `BorrowTransaction` currently `OPEN` (i.e. not yet received back), as a plain list of `TransactionOut` (not paginated).

**Auth:** Bearer token required, any authenticated role — a view/list surface (Roadmap PR10), no role restriction beyond authentication, matching `GET /transactions`'s own gate.

### Response — `200 OK`

```json
[
  { "...": "TransactionOut, same shape as POST /borrow's response" }
]
```

No query parameters are accepted.

## See also

- `docs/api/receipt.md` — the corresponding return/receipt endpoint that closes a dispatch
- `docs/api/transactions.md` — general transaction listing/lookup (includes both open and closed transactions)
- `docs/api/equipment.md` — how `equipment_id` is resolved before a dispatch is created
- `docs/api/master-data.md` — ward/department master data, including the optional contact `phone` the dispatch form can prefill `phone_number` from
