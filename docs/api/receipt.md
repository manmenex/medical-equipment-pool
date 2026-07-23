# Receipt API

**Purpose:** Request/response contract for recording the receipt (return) of previously dispatched equipment.
**Authority:** Documents current behavior in `backend/app/api/v1/borrow.py`, `backend/app/schemas/transaction.py`, and `backend/app/services/borrow_service.py`. Not a design proposal.
**Update trigger:** The receipt endpoint's request/response shape, validation, or error behavior changes.
**Maintainer:** Repository Owner

> **Scope note:** This is the **frozen, canonical, post-PR8B** receipt contract (Roadmap PR8, PR8B slice — see `docs/DECISION_LOG.md` and `knowledge/adr/ADR-006-receipt-outcome-contract.md`). It replaces the pre-PR8B four-value `condition` string contract entirely — no compatibility alias was kept. This document does **not** cover a distinguishable race-vs-genuine-repeat error message: that is Roadmap PR8's separately-named **PR8C slice**, not started (see ADR-006's "Not decided here"). **Roadmap PR8 is not complete until PR8A, PR8B, and PR8C all merge.**

## `POST /api/v1/return/{transaction_id}` — record a receipt

Closes an open borrow transaction and moves the equipment to the status implied by the reported `receipt_outcome`, atomically. Exactly one concurrent receipt request for the same transaction succeeds (Roadmap PR8A's database-level concurrency guard); every loser produces zero side effects and receives `409 TRANSACTION_ALREADY_RETURNED` — the same response a genuine sequential repeat receives (see `docs/DECISION_LOG.md` "Roadmap PR8 (PR8A slice)").

**Auth:** Bearer token required. Allowed roles: `admin`, `ward_nurse`, `transport_staff`, `biomedical_engineer`.

### Path parameter

| Parameter | Type | Notes |
|---|---|---|
| `transaction_id` | UUID | The `BorrowTransaction.id` to close (as returned by `POST /borrow`, or found via `GET /transactions`) |

### Request body (`ReturnRequest`)

```json
{
  "receipt_outcome": "usable",
  "notes": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `receipt_outcome` | `"usable"` \| `"defective"` | Yes | The single business term for the receipt's outcome (`docs/HOSPITAL_DOMAIN_MODEL.md`'s confirmed workflow vocabulary: "receipt outcome: usable" / "receipt outcome: defective"). A typed enum, not a free-form string — any other value is rejected as `422 VALIDATION_ERROR` before this endpoint's code ever runs (see Errors below), not a `400`. |
| `notes` | string or `null` | No | |

**The backend alone maps `receipt_outcome` to an `EquipmentStatus`** (`RECEIPT_OUTCOME_TO_STATUS`, `backend/app/services/borrow_service.py`) — the frontend must never submit an equipment lifecycle state (`available_at_pool`/`unavailable_defective`) directly; it submits only the business outcome, and the backend alone decides the resulting state. See `knowledge/adr/ADR-006-receipt-outcome-contract.md` for why.

**No compatibility layer.** `ReturnRequest` uses `model_config = {"extra": "forbid"}` (the same technique `BorrowRequest` established in Roadmap PR7b): a caller still sending the pre-PR8B `condition` field gets a hard `422` (unrecognized field), never a silently-ignored or silently-accepted one. `"cleaning"` was never a valid value under the old contract either (Roadmap PR6 / owner-confirmed cleaning retirement) and remains impossible to express under the new one — cleaning happens as part of collecting/receiving equipment (`AGENTS.md`), never a distinct receipt outcome.

### `receipt_outcome` → resulting equipment status (`RECEIPT_OUTCOME_TO_STATUS`, `backend/app/services/borrow_service.py`)

| `receipt_outcome` | Resulting `EquipmentStatus` |
|---|---|
| `usable` | `available_at_pool` |
| `defective` | `unavailable_defective` |

This is a total mapping over `ReceiptOutcome`'s two members — there is no "unknown outcome" case left to handle at the service layer; Pydantic/FastAPI's request validation already rejects anything else before the service runs.

### Response — `200 OK` (`TransactionOut`)

Same shape as `POST /borrow`'s response (see `docs/api/dispatch.md`), with the closed transaction's fields updated: `status: "closed"`, `returned_at` set, `receipt_outcome` set to the submitted value.

```json
{
  "id": "uuid",
  "transaction_no": "TXN-...",
  "equipment": {
    "id": "uuid",
    "asset_number": "AST-1001",
    "equipment_name": "Infusion Pump",
    "status": "available_at_pool"
  },
  "quantity": 1,
  "borrowed_at": "2026-07-21T10:00:00Z",
  "returned_at": "2026-07-21T14:00:00Z",
  "borrower_name": null,
  "ward_id": "uuid",
  "dispatch_type": "on_demand",
  "routine_round": null,
  "phone_number": null,
  "receipt_outcome": "usable",
  "legacy_condition_on_return": null,
  "status": "closed",
  "notes": null
}
```

**The response is exactly as binary as the request.** `TransactionOut.receipt_outcome` is a real, strictly-typed `ReceiptOutcome | None` enum field (emitted in the OpenAPI schema as an enum reference, not an unconstrained string) — it is **never** one of the pre-PR8B legacy strings (`available`/`pm`/`calibration`/`repair`). It is `null` both for a transaction not yet received and for one received **before** Roadmap PR8B existed. A transaction's genuine pre-PR8B legacy value is instead readable, unmodified, through a separate field, `legacy_condition_on_return` (`string | null`) — mutually exclusive with `receipt_outcome`: exactly one of the two is non-null for any received transaction, and both are `null` for a transaction not yet received. Neither field ever translates or backfills a legacy value into the new domain, matching how Roadmap PR7b preserved `borrower_name`/`due_at`/`quantity` and how `BorrowTransaction.legacy_status` keeps history in a distinct field rather than blending it into `status`.

Example of a **pre-PR8B** transaction's response (received before this contract existed):

```json
{
  "...": "...",
  "receipt_outcome": null,
  "legacy_condition_on_return": "pm",
  "status": "closed"
}
```

### Errors

| Status | Code | Cause |
|---|---|---|
| `404` | `TRANSACTION_NOT_FOUND` | `transaction_id` doesn't resolve to a transaction |
| `404` | `EQUIPMENT_NOT_FOUND` | (Defensive case) the transaction's linked equipment row is gone |
| `409` | `TRANSACTION_ALREADY_RETURNED` | The transaction's `status` is already `closed` — either a genuine repeat request, or this request lost a concurrent receipt race (Roadmap PR8A); both causes currently share this one response, see the scope note above |
| `422` | `VALIDATION_ERROR` | `receipt_outcome` is missing, not one of `usable`/`defective`, or the request includes an unrecognized field (e.g. the retired `condition`); or `transaction_id` path parameter isn't a valid UUID (FastAPI-typed path parameter — this is a `422`, not the `400` a plain-string query/body UUID would get; see `docs/api/ERROR_CODES.md`) |
| `401` / `403` | `NOT_AUTHENTICATED` / `FORBIDDEN` | Missing/invalid token, or caller's role isn't `admin`/`ward_nurse`/`transport_staff`/`biomedical_engineer` |

Full status/code reference: `docs/api/ERROR_CODES.md`.

## Current deployed state: frontend and backend both adopt `receipt_outcome`

The frontend and backend halves of Roadmap PR8B are both merged and were deployed together, per the coordinated-release requirement below — backend PR #28 (squash SHA `da4d76a640548e5a1d38ff3d7690695f950c85fe`) and frontend PR #29 (squash SHA `d3e027b5a4ee7d99b38dfd0d263dc460c74eb5c5`). `docs/TECH_DEBT.md` TD-006, which tracked this gap, is now `Closed`.

The current active request contract is:

```json
{
  "receipt_outcome": "usable"
}
```

Allowed values: `usable`, `defective`. The retired `condition` field is no longer accepted — `ReturnRequest` uses `model_config = {"extra": "forbid"}`, so a caller still sending it gets a hard `422` (see Errors above), never a silently-ignored one. **The backend alone maps `receipt_outcome` to an equipment lifecycle state; the frontend must never send a lifecycle state** (`available_at_pool`/`unavailable_defective`) directly — see the request body section above and `knowledge/adr/ADR-006-receipt-outcome-contract.md`.

This endpoint's only client is this project's own frontend (`docs/ARCHITECTURE_DECISIONS.md` "Browser-first application" — no native app, no known external/third-party integration); no compatibility layer was kept. A transaction received **before** Roadmap PR8B existed keeps its original value readable, unmodified, through the separate `legacy_condition_on_return` field described above — that legacy historical data is not translated or backfilled into `receipt_outcome`. Current (post-PR8B) transactions use `receipt_outcome`.

## See also

- `docs/api/dispatch.md` — the corresponding dispatch endpoint that opens a transaction
- `docs/api/transactions.md` — general transaction listing/lookup
- `docs/api/equipment.md` — equipment status values and the manual-lifecycle status endpoint (a separate, non-receipt code path)
- `knowledge/adr/ADR-006-receipt-outcome-contract.md` — why this contract exposes a business outcome instead of lifecycle states
