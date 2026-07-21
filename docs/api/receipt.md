# Receipt API

**Purpose:** Request/response contract for recording the receipt (return) of previously dispatched equipment.
**Authority:** Documents current behavior in `backend/app/api/v1/borrow.py`, `backend/app/schemas/transaction.py`, and `backend/app/services/borrow_service.py`. Not a design proposal.
**Update trigger:** The receipt endpoint's request/response shape, validation, or error behavior changes.
**Maintainer:** Repository Owner

> **Scope note:** This is the **current, pre-PR8** receipt contract — a `condition` string chosen from a fixed set. It is not the atomic single-operation, binary usable/defective receipt design under consideration for a future Roadmap PR (`docs/design/PR8_IMPLEMENTATION_PLAN.md`); this document describes only what exists in code today.

## `POST /api/v1/return/{transaction_id}` — record a receipt

Closes an open borrow transaction and moves the equipment to the status implied by the reported `condition`, atomically.

**Auth:** Bearer token required. Allowed roles: `admin`, `ward_nurse`, `transport_staff`, `biomedical_engineer`.

### Path parameter

| Parameter | Type | Notes |
|---|---|---|
| `transaction_id` | UUID | The `BorrowTransaction.id` to close (as returned by `POST /borrow`, or found via `GET /transactions`) |

### Request body (`ReturnRequest`)

```json
{
  "condition": "available",
  "notes": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `condition` | string | Yes | One of `available`, `pm`, `calibration`, `repair` (see below). Any other value is rejected as `400 INVALID_INPUT`, not silently accepted. |
| `notes` | string or `null` | No | |

**`"cleaning"` is deliberately not a valid value** (Roadmap PR6 / owner-confirmed cleaning retirement): cleaning happens as part of collecting/receiving equipment, not as a distinct return outcome — see `AGENTS.md`. Passing `"cleaning"` is rejected the same as any other unrecognized condition.

### Condition → resulting equipment status (`RETURN_CONDITION_TO_STATUS`, `backend/app/services/borrow_service.py`)

| `condition` | Resulting `EquipmentStatus` |
|---|---|
| `available` | `available_at_pool` |
| `pm` | `unavailable_defective` |
| `calibration` | `unavailable_defective` |
| `repair` | `unavailable_defective` |

`pm`, `calibration`, and `repair` all map to the same `unavailable_defective` status under the current 4-state equipment model (`docs/HOSPITAL_DOMAIN_MODEL.md`) — there is no more granular "why unavailable" status. Each blocks the equipment from being dispatched again until an authorized status change moves it back to `available_at_pool`.

### Response — `200 OK` (`TransactionOut`)

Same shape as `POST /borrow`'s response (see `docs/api/dispatch.md`), with the closed transaction's fields updated: `status: "closed"`, `returned_at` set, `condition_on_return` set to the submitted `condition`.

### Errors

| Status | Code | Cause |
|---|---|---|
| `400` | `INVALID_INPUT` | `condition` is not one of `available`/`pm`/`calibration`/`repair` |
| `404` | `TRANSACTION_NOT_FOUND` | `transaction_id` doesn't resolve to a transaction |
| `404` | `EQUIPMENT_NOT_FOUND` | (Defensive case) the transaction's linked equipment row is gone |
| `409` | `TRANSACTION_ALREADY_RETURNED` | The transaction's `status` is already `closed` |
| `422` | `VALIDATION_ERROR` | `transaction_id` path parameter isn't a valid UUID (FastAPI-typed path parameter — this is a `422`, not the `400` a plain-string query/body UUID would get; see `docs/api/ERROR_CODES.md`) |
| `401` / `403` | `NOT_AUTHENTICATED` / `FORBIDDEN` | Missing/invalid token, or caller's role isn't `admin`/`ward_nurse`/`transport_staff`/`biomedical_engineer` |

Full status/code reference: `docs/api/ERROR_CODES.md`.

## See also

- `docs/api/dispatch.md` — the corresponding dispatch endpoint that opens a transaction
- `docs/api/transactions.md` — general transaction listing/lookup
- `docs/api/equipment.md` — equipment status values and the manual-lifecycle status endpoint (a separate, non-receipt code path)
