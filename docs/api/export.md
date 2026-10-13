# Export API

**Purpose:** Read-only feed of dispatch and receipt events for an external consumer (Nsmart Realtime), plus the administrator endpoints that manage the consumer's key.
**Authority:** Documents current behavior in `backend/app/api/v1/export.py`, `backend/app/api/v1/export_keys.py`, `backend/app/services/export_service.py` and migration `0025_export_events`. Not a design proposal.
**Update trigger:** The event shape, cursor semantics, key handling, or limits change.
**Maintainer:** Repository Owner

> **Boundary.** This system never calls N Smart or the consumer. The consumer polls this API and keys into N Smart itself (Governance 2026-10-13, `docs/DECISION_LOG.md`). The payload contains no patient data and no HN — none exists in this system.

## Authentication

A dedicated machine key, separate from human logins.

- Header: `X-API-Key: mepx_...` on every request. **Not** `Authorization: Bearer`.
- Only `GET /api/v1/export/events` and `GET /api/v1/export/cursor` accept it. It is rejected (`401`) everywhere else, including as a bearer token.
- Human JWTs (any role) are rejected (`401`) on `/export/*`. Administrators manage keys; they do not poll with them.
- Missing, unknown and revoked keys return the same `401 NOT_AUTHENTICATED` with `WWW-Authenticate: ApiKey`.
- Keys are 256-bit random values, stored only as a SHA-256 digest, shown once at creation. Revocation takes effect on the next request.

### Managing keys (Administrator only, normal bearer login)

| Method / path | Purpose |
|---|---|
| `POST /api/v1/export-keys` `{"name": "Nsmart Realtime"}` | Create. `201`; the response contains `key` — **the only time it is visible**. |
| `GET /api/v1/export-keys` | List: `id`, `name`, `key_prefix`, `created_at`, `revoked_at`, `last_used_at` (updated at most every 5 min). |
| `POST /api/v1/export-keys/{id}/revoke` | Revoke (idempotent). `404 RESOURCE_NOT_FOUND` for an unknown id. |

Create and revoke are audit-logged (entity `export_api_key`, never the key). To rotate: create a second key, switch the consumer, revoke the first.

## `GET /api/v1/export/events`

| Query | Default | Notes |
|---|---|---|
| `after` | `0` | `seq` of the last event the consumer has processed. `0` = from the beginning of history. |
| `limit` | `100` | `1`–`500`; outside that range is `422 VALIDATION_ERROR`. |

Events are ordered by `seq` ascending — a total, deterministic order. The same `after`/`limit` returns the same events with the same `event_id`s.

```json
{
  "events": [
    {
      "seq": 41,
      "event_id": "0b7e1c52-6f5c-4c0e-9f1e-6b8d2a9d3c11",
      "event_type": "dispatch",
      "event_time": "2026-10-13T06:02:11.532+00:00",
      "transaction_id": "5d1d6c0e-...",
      "transaction_no": "TX-20261013-0007",
      "equipment": {"id": "9a3b...", "bcm_code": "BCM0123", "name": "Infusion Pump", "category": "Pumps"},
      "ward": {"id": "c41f...", "code": "ICU1", "name": "Intensive Care Unit 1"},
      "dispatch_type": "routine_round",
      "routine_round": "06:00",
      "receipt_outcome": null,
      "operator_name": "Somchai P."
    }
  ],
  "next_cursor": 41,
  "has_more": false
}
```

| Field | Meaning |
|---|---|
| `seq` | The cursor position of this event. |
| `event_id` | Stable UUID, unique per event, never reused or changed. **The consumer's dedupe key.** |
| `event_type` | `dispatch` (issued to a ward) or `receipt` (returned). |
| `event_time` | When it happened (`borrowed_at` / `returned_at`), UTC. |
| `transaction_id`, `transaction_no` | Groups a dispatch with its receipt. |
| `equipment` | Opaque `id`, `bcm_code` (may be null for unmigrated rows), `name`, `category`. |
| `ward` | `id`, `code`, `name` as of the response (null only on pre-PR7b history). |
| `dispatch_type`, `routine_round` | From the dispatch; `null` on unclassified history. |
| `receipt_outcome` | `usable` / `defective` on `receipt` events; `null` on `dispatch` and on pre-PR8B receipts with a legacy condition. |
| `operator_name` | Display name of the Equipment Pool staff member who recorded this event. |

**Deliberately absent:** Item No, Asset Number, serial number, notes, phone, borrower name, anything patient-related (`knowledge/architecture/api-information-boundaries.md`). This is an explicit allow-list in `export_service._serialize`; adding a field is a contract change.

Paging: if `has_more` is true, call again immediately with `after=next_cursor`; otherwise wait for the next poll. `next_cursor` equals the request's `after` on an empty page, so it is always safe to store.

Errors: `401 NOT_AUTHENTICATED`; `409 EXPORT_CURSOR_AHEAD` (`after` is beyond the newest event — see "Restores"); `422 VALIDATION_ERROR`.

## `GET /api/v1/export/cursor` — choosing a starting point

| Query | Result |
|---|---|
| *(none)* | `{"cursor": N}` — the newest event. Poll with `after=N` to receive only events recorded from now on ("start from now"). |
| `at=<ISO-8601 instant>` | The cursor from which every event with `event_time >= at` follows (naive values are UTC). May include an event or two just before `at`; never skips one. |
| (use `after=0`) | Full history, oldest first. |

History that existed when `0025_export_events` ran was backfilled in chronological order (every dispatch, and every receipt of a closed transaction).

## Cursor semantics — why it cannot skip a committed event

Polling by timestamp, or by a database sequence/IDENTITY value, is unsafe: values are handed out when a transaction *starts writing*, not when it *commits*. A transaction can take value 10, stall, and commit after value 11 has been committed and polled; a consumer that advanced past 11 never sees 10.

Here `seq` is assigned from a single counter row (`export_event_counter`) with `UPDATE ... SET last_seq = last_seq + 1 RETURNING last_seq`, as the **last write** of the dispatch/receipt transaction. PostgreSQL holds that row lock until the transaction commits or rolls back, so:

1. Transactions are serialized on the counter: seq N+1 can only be assigned after the transaction holding N has committed or rolled back.
2. A rollback also reverts the counter, so there are **no gaps**.
3. PostgreSQL publishes a commit before releasing its locks, so any snapshot that can see N+1 can also see N.

The committed events visible to a reader are therefore always the gap-free prefix `1..K`; `WHERE seq > :after ORDER BY seq` can never skip one, and no "safety lag" window is needed. Verified against real PostgreSQL in `backend/tests/test_pr25b_postgres.py`. The cost is that dispatch/receipt commits briefly queue behind each other — negligible at hospital-pool volume.

Other properties:

- A **receipt on an old transaction** is a new event at the head (new `seq`, new `event_id`, same `transaction_id`); it never rewrites the old dispatch event.
- Delivery is **at-least-once** from the consumer's point of view if it crashes between processing and saving its cursor. It must dedupe on `event_id`.
- `ward`, `equipment.name` and operator names are read when the page is served. A later ward correction (PR9A) does **not** emit a new event; a consumer that has already processed the dispatch keeps the ward it saw.

## How Nsmart Realtime should poll

1. **First run only:** `GET /export/cursor` (from now) or `?at=...`, or use `0` to replay history. Save the value as `cursor`.
2. **Every ~30 s:** `GET /export/events?after={cursor}&limit=100`.
3. For each event in order: if `event_id` was already processed, skip; otherwise process it (key into N Smart), then record `event_id`.
4. Save `cursor = next_cursor` *after* the page is processed. If `has_more`, repeat from step 2 immediately.
5. Group by `transaction_id` for per-dispatch grouping; `receipt_outcome` tells usable/defective.
6. On `401`, stop and alert (key revoked or wrong). On `409 EXPORT_CURSOR_AHEAD`, stop and alert — see below. On network errors or `5xx`, retry with the same `cursor`.

```bash
curl -s -H "X-API-Key: $MEP_EXPORT_KEY" "https://<host>/api/v1/export/events?after=0&limit=100"
```

### Restores

If the database is restored from backup, events recorded after the backup are gone and `seq` values will be reused. A consumer whose cursor is beyond the restored head gets `409 EXPORT_CURSOR_AHEAD`. A consumer whose cursor is within the restored range cannot detect the rewind from the cursor alone; after any restore, an operator must decide whether to re-seed the consumer (`GET /export/cursor?at=<time of backup>`) and reconcile in N Smart.
