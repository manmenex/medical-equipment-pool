# Transactions API

**Purpose:** Request/response contract for read-only transaction listing/lookup.
**Authority:** Documents current behavior in `backend/app/api/v1/transactions.py`, `backend/app/crud/transaction.py`, and `backend/app/schemas/transaction.py`. Not a design proposal.
**Update trigger:** A transactions endpoint's request/response shape or error behavior changes.
**Maintainer:** Repository Owner

Base path: `/api/v1/transactions`. Both endpoints are read-only — transactions are created and closed exclusively through `docs/api/dispatch.md` (`POST /borrow`) and `docs/api/receipt.md` (`POST /return/{transaction_id}`).

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

## See also

- `docs/api/dispatch.md` — create a transaction (`POST /borrow`), list only open ones (`GET /borrow/active`)
- `docs/api/receipt.md` — close a transaction (`POST /return/{transaction_id}`)
