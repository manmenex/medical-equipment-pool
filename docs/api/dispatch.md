# Dispatch API

**Purpose:** Request/response contract for dispatching pool-owned equipment to a ward.
**Authority:** Documents current behavior in `backend/app/api/v1/borrow.py`, `backend/app/schemas/transaction.py`, and `backend/app/services/borrow_service.py`. Not a design proposal.
**Update trigger:** The dispatch endpoint's request/response shape, validation, or error behavior changes.
**Maintainer:** Repository Owner

> **Naming note:** The domain term is **dispatch** (see `knowledge/adr/ADR-005-transaction-model.md`); the route path and Python module are still named `borrow` for historical reasons. Both terms refer to the same operation.

## `POST /api/v1/borrow` — create a dispatch

Creates a new borrow transaction and moves the selected equipment from `available_at_pool` to `issued_to_ward`, atomically.

**Auth:** Bearer token required. Allowed roles: `admin`, `ward_nurse`, `transport_staff`.

### Request body (`BorrowRequest`)

```json
{
  "equipment_id": "3f2b6b9e-...-uuid",
  "ward_id": "8a1c...-uuid",
  "dispatch_type": "on_demand",
  "routine_round": null,
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
| `dispatch_type` | `"routine_round"` \| `"on_demand"` | Yes | See `DispatchType` (`backend/app/models/transaction.py`). |
| `routine_round` | `"06:00"` \| `"11:00"` \| `"15:00"` \| `"21:00"` \| `null` | Conditional | **Required** when `dispatch_type == "routine_round"`; **must be omitted/null** when `dispatch_type == "on_demand"` — enforced by a `model_validator`, not just documentation. Fixed four-round MVP schedule (`RoutineRound`); see `docs/HOSPITAL_DOMAIN_MODEL.md` for why this isn't a free-form time. |
| `department_id` | string (UUID) or `null` | No | |
| `phone_number` | string or `null` | No | |
| `pickup_location_id` | string (UUID) or `null` | No | |
| `dropoff_location_id` | string (UUID) or `null` | No | |
| `notes` | string or `null` | No | |

**Deliberately absent fields** (Roadmap PR7b — do not send these; they are rejected, not silently ignored, because `BorrowRequest` uses `model_config = {"extra": "forbid"}`):

- `borrower_name` — no longer accepted or required; historical values from before this change remain visible read-only in `TransactionOut.borrower_name`.
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

### Errors

| Status | Code | Cause |
|---|---|---|
| `400` | `INVALID_INPUT` | `equipment_id` or `ward_id` is not a valid UUID; `ward_id` doesn't reference an existing ward (validated proactively, before any equipment-availability check); or (rare) a foreign key stopped existing in the narrow window between that check and the write |
| `404` | `EQUIPMENT_NOT_FOUND` | `equipment_id` doesn't resolve to an equipment row |
| `409` | `EQUIPMENT_NOT_AVAILABLE` | Equipment's current status is not `available_at_pool`, or a concurrent dispatch of the same equipment won the race (unique-index collision on `idx_tx_one_active_borrow`) |
| `422` | `VALIDATION_ERROR` | Missing required field, wrong type, an unrecognized field (`borrower_name`/`due_at`/`quantity`/anything else not in the schema), or `routine_round` present/absent inconsistently with `dispatch_type` |
| `401` / `403` | `NOT_AUTHENTICATED` / `FORBIDDEN` | Missing/invalid token, or caller's role isn't `admin`/`ward_nurse`/`transport_staff` |

A bad `ward_id` reference is deliberately a `400 INVALID_INPUT`, not the `409 EQUIPMENT_NOT_AVAILABLE` conflict response — a missing ward is a client input error, not an equipment-availability conflict (see the comment in `borrow_service.borrow` referencing this repository's PR20 review round 1, finding MAJOR 3).

Full status/code reference: `docs/api/ERROR_CODES.md`.

## `GET /api/v1/borrow/active` — list active dispatches

Returns every `BorrowTransaction` currently `OPEN` (i.e. not yet received back), as a plain list of `TransactionOut` (not paginated).

**Auth:** Bearer token required. Allowed roles: `admin`, `ward_nurse`, `transport_staff`, `biomedical_engineer`, `viewer`.

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
