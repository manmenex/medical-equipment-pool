# Sync API

**Purpose:** Request/response contract for `POST /api/v1/sync/operations`, the idempotent batch endpoint through which dispatch and receipt operations (recorded online or offline) reach the server.
**Authority:** Documents current behavior in `backend/app/api/v1/sync.py`, `backend/app/schemas/sync.py`, `backend/app/services/sync_service.py`, `backend/app/crud/client_operation.py`. Design source: `docs/design/PR25D_OFFLINE_OPERATION_PLAN.md` sections 6 and 9.
**Update trigger:** The endpoint's envelope, result codes, or ledger behavior changes.
**Maintainer:** Repository Owner

> **Scope (Roadmap PR25E slice B2).** Dispatch and receipt only. Adoption of another user's operations (B2c), `verify`, `snapshot`, `status`, and the conflict review endpoints (B3/B4) are not part of this slice. Business time (slice B2b): `occurred_at_local + clock_offset_ms` (missing offset = 0), clamped per design section 11 and stored as `borrowed_at`/`returned_at` and the ledger `occurred_at`; `time_flag` is one of `clamped_future` (later than server now + 2 min -> now), `clamped_old` (older than now - 7 days -> now), `before_dispatch` (receipt earlier than its dispatch -> dispatch time), `before_last_receipt` (dispatch earlier than the equipment's latest `returned_at` -> that time). Bounds are strict; flagged ops are still applied. Online `/borrow` and `/return` keep server time.

## `POST /api/v1/sync/operations`

**Roles:** Administrator, Equipment Pool Staff (same as `POST /borrow` and `POST /return/{id}`). Read Only gets `403`; no token gets `401`. Both are whole-request errors.

Body: `{ "operations": [ ... ] }`, 1 to 25 operations, each at most 8 KB serialized. All objects are strict (unknown fields are a `422` for the whole request; the envelope cannot carry equipment or transaction status).

| Field | Notes |
|---|---|
| `op_id` | UUID v4, the idempotency key. For a dispatch it is also the new transaction's id. |
| `device_id` | UUID v4. `(device_id, device_seq)` is unique across all operations. |
| `device_seq` | Integer >= 0. Within a batch, operations are processed per device in ascending `device_seq`. |
| `user_id` | The operator the client believes keyed the operation. Must equal the token user, otherwise `OP_USER_MISMATCH`. |
| `op_type` | `dispatch` (requires `dispatch`) or `receipt` (requires `receipt`). |
| `occurred_at_local`, `clock_offset_ms` | Business time input (see scope note); the device clock never orders anything. |
| `dispatch` | Exactly the `POST /borrow` body (`docs/api/dispatch.md`). |
| `receipt` | The `POST /return` body (`docs/api/receipt.md`) plus `transaction_id`. |

Response `200`: `{ "results": [ { "op_id", "result", "code", "transaction_id"?, "message" } ] }`, one per operation, in processing order (match by `op_id`). The batch is `200` even when individual operations conflict. Each operation runs in its own database transaction; an unexpected server error (`5xx`) leaves earlier operations committed and later ones untouched, and the client simply re-sends the whole batch (idempotent).

| `result` | `code` | Meaning |
|---|---|---|
| `applied` | `APPLIED` | Executed through the normal dispatch/receipt service; ledger row, business writes, audit entry, and exactly one export event committed atomically. |
| `duplicate` | `DUPLICATE` | The `op_id` was already applied (or resolved) with identical content; `transaction_id` is the original. Nothing written. |
| `conflict` | the domain code (`EQUIPMENT_NOT_AVAILABLE`, `EQUIPMENT_NOT_FOUND`, `INVALID_INPUT`, `TRANSACTION_ALREADY_RETURNED`, `RECEIPT_RACE_LOST`, `TRANSACTION_NOT_FOUND`) | Not applied; a `conflict` ledger row with the payload is stored for human review. Re-sending returns the same stored result without re-running. No business change, no export event. |
| `retry_later` | `DEPENDENCY_MISSING` | A receipt whose `transaction_id` is unknown, within 48 h of the server first seeing the `op_id`. A `pending` ledger row is kept (never a duplicate); retry later. After 48 h it becomes `conflict` / `TRANSACTION_NOT_FOUND`. |
| `rejected` | `OP_USER_MISMATCH` | The token user is not the operation's user. Checked before anything else; the response never reveals whether the `op_id` exists, its stored result, or its `transaction_id`. Nothing is written. |
| `rejected` | `OP_ID_REUSED` | The `op_id` exists with a different payload hash (client bug). |
| `rejected` | `DEVICE_SEQ_REUSED` | The `(device_id, device_seq)` pair belongs to a different `op_id` (client bug). |

Semantics worth knowing:

* Concurrent sends of the same `op_id` (two tabs, retry overlap) cannot double-apply: the loser receives `duplicate`, never a conflict. A `pending` operation retried concurrently applies exactly once.
* The audit actor is the token user; `borrower_user_id` / `received_by_user_id` is the operation's user (identical in this slice). Audit `after_data` additionally carries `op_id`, `device_id`, `device_seq`.
* Every applied operation produces exactly one `export_events` row, written last in the same transaction (`docs/api/export.md`). `duplicate`, `conflict`, `rejected`, and `retry_later` produce none.
* `POST /borrow` and `POST /return/{id}` are unchanged.
