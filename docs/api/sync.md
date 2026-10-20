# Sync API

**Purpose:** Request/response contract for `POST /api/v1/sync/operations`, the idempotent batch endpoint through which dispatch and receipt operations (recorded online or offline) reach the server.
**Authority:** Documents current behavior in `backend/app/api/v1/sync.py`, `backend/app/schemas/sync.py`, `backend/app/services/sync_service.py`, `backend/app/crud/client_operation.py`. Design source: `docs/design/PR25D_OFFLINE_OPERATION_PLAN.md` sections 6 and 9.
**Update trigger:** The endpoint's envelope, result codes, or ledger behavior changes.
**Maintainer:** Repository Owner

> **Scope (Roadmap PR25E slice B2).** Dispatch and receipt only. Adoption of another user's operations (B2c) is not part of this slice (the conflict review endpoints are slice B4, below); `verify`, `snapshot`, `status`, and `stats` are documented below (slice B3). Business time (slice B2b): `occurred_at_local + clock_offset_ms` (missing offset = 0), clamped per design section 11 and stored as `borrowed_at`/`returned_at` and the ledger `occurred_at`; `time_flag` is one of `clamped_future` (later than server receipt time + 2 min -> receipt time), `too_old` (older than first receipt - 7 days: NOT applied and NOT clamped; stored as a `conflict` with code `OP_TOO_OLD`, no transaction, no export event, unclamped adjusted time kept in the ledger `occurred_at` for review, Owner decision D9), `before_dispatch` (receipt earlier than its dispatch -> dispatch time), `before_last_receipt` (dispatch earlier than the equipment's latest `returned_at` -> that time). Bounds are strict (exactly 7 days is still applied) and measured against the server's first receipt of the `op_id`, not the retry time. Ops flagged other than `too_old` are still applied. Online `/borrow` and `/return` keep server time.

## `POST /api/v1/sync/operations`

**Roles:** Administrator, Equipment Pool Staff (same as `POST /borrow` and `POST /return/{id}`). Read Only gets `403`; no token gets `401`. Both are whole-request errors.

Body: `{ "operations": [ ... ] }`, 1 to 25 operations, each at most 8 KB serialized. All objects are strict (unknown fields are a `422` for the whole request; the envelope cannot carry equipment or transaction status).

| Field | Notes |
|---|---|
| `op_id` | UUID v4, the idempotency key. For a dispatch it is also the new transaction's id. |
| `device_id` | UUID v4. `(device_id, device_seq)` is unique across all operations. |
| `device_seq` | Integer >= 0. Within a batch, operations are processed per device in ascending `device_seq`. |
| `user_id` | The operator the client believes keyed the operation. Must equal the token user, otherwise `OP_USER_MISMATCH`, unless `adopt` is true. |
| `adopt`, `original_user_id` | Optional (slice B2c, Owner decision D4). `adopt: true` requires `original_user_id` equal to `user_id`; `original_user_id` without `adopt` is `422`. See "Adoption" below. |
| `snapshot_age_s` | Optional integer >= 0: seconds since the device's last successful snapshot when the op was keyed. The server sets the ledger's `stale_context` when it exceeds 4 hours (14400 s); the flag never blocks an op (design 9.8). |
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
* The audit actor is the token user; `borrower_user_id` / `received_by_user_id` is the operation's user (the same person unless adopted). Audit `after_data` additionally carries `op_id`, `device_id`, `device_seq`.
* Every applied operation produces exactly one `export_events` row, written last in the same transaction (`docs/api/export.md`). `duplicate`, `conflict`, `rejected`, and `retry_later` produce none.
* `POST /borrow` and `POST /return/{id}` are unchanged.

### Adoption (slice B2c)

Another Administrator or Equipment Pool Staff user may send a stranded user's operations from the same device by setting `adopt: true` and `original_user_id` (design 8.3). The server accepts a token user different from `user_id` only when `adopt` is true and `original_user_id` is an existing user holding an Equipment Pool role (active state is not checked, so a departed operator's ops can still be sent) other than the token user; otherwise `OP_USER_MISMATCH` (nothing written, nothing revealed). `read_only` callers get `403` as for any operation. The original operator stays the recorded operator (`borrower_user_id` / `received_by_user_id`, ledger `user_id`); the ledger gets `submitted_by_user_id` = adopter and `adopted_at`. Audit actor and equipment status-history actor are the adopter; the `borrow`/`return` audit `after_data` carries `adopted: true`, `original_user_id`, `submitted_by_user_id`, and one `sync_adopt` audit entry (entity `client_operation`, entity id = op id) is written in the same transaction per applied adopted op. Idempotency is unchanged: replaying an adopted `op_id` (by an adopter naming the same original, or by the original operator) returns `duplicate`. **Fresh login (slice S5b).** An adopted op is accepted only if the adopter's access token was created by a password login (JWT `auth_time` claim: the time of the last PASSWORD login; `/auth/refresh` copies it unchanged and never renews it) within the last 15 minutes; otherwise the op is `rejected` with `ADOPT_REAUTH_REQUIRED` and nothing is written (a missing `auth_time` fails closed). Non-adopt ops are unaffected. The client re-prompts for the password via the normal login endpoint. The token issue time is recorded as `auth_time` in the `sync_adopt` audit `after_data`. The `sync_adopt` audit is written **per applied adopted op** (deviation from the design's per-batch entry); an adopted op that ends in `conflict` or `rejected` has the ledger `submitted_by_user_id` / `adopted_at` but no `sync_adopt` audit row. A deactivated original user's ops can still be adopted (only existence and an Equipment Pool role are checked). Adopting a `pending` ledger row created by the original user is allowed and completes it as adopted.

## `POST /api/v1/sync/verify` (slice B3)

**Roles:** Administrator, Equipment Pool Staff. Body (strict): `{ "op_ids": [uuid, ...] }`, 1 to 1000 ids (`422` outside that range). Response `200`: `{ "checked": n, "unknown_op_ids": [...] }` where `checked` is the number of distinct ids and `unknown_op_ids` lists, in request order, those for which the **caller** has no ledger row. Only the caller's own operations (original operator or submitter) count as known, so another user's `op_id` is reported as unknown, exactly like an id the server never saw; nothing about other users' operations is revealed. The client re-sends unknown journal entries through `POST /sync/operations` (restore recovery, design section 10). Each call writes one counts-only audit row (`sync_verify`, `{checked, unknown}`, no ids).

## `GET /api/v1/sync/snapshot` (slice B3)

**Roles:** Administrator, Equipment Pool Staff, Read Only. Query: `section` (required: `equipment`, `wards`, `departments`, `locations`, `open_transactions`; otherwise `400 INVALID_INPUT`), `cursor` (opaque, from `next_cursor`; malformed is `400 INVALID_INPUT`), `limit` (1 to 500, default 200). Response: `{ section, items, next_cursor, etag, server_time }`; `next_cursor` is `null` on the last page. Ordering is deterministic: `(updated_at, id)` for equipment, `(borrowed_at, id)` for open transactions, `id` for the other sections. Soft-deleted equipment is excluded.

Each row is built from a fixed allow-list (information boundary, `knowledge/architecture/api-information-boundaries.md`; Item No excluded per ADR-004 and Owner decision D1; Asset Number, serial number, QR value and other identifiers are never included):

| Section | Fields |
|---|---|
| `equipment` | `id`, `bcm_code`, `equipment_name`, `category_id`, `category_name`, `status` |
| `wards` | `id`, `code`, `name`, `department_id`, `phone` |
| `departments` | `id`, `code`, `name`, `phone` |
| `locations` | `id`, `name`, `type` |
| `open_transactions` | `id`, `equipment_id`, `ward_id`, `borrowed_at` |

Paging guarantees: pages are not a point-in-time view, and a full scan is eventually consistent. Clients must upsert by `id` (equipment may appear twice if it changes mid-scan). `open_transactions` is ordered by `borrowed_at`, so a row backdated by a sync operation mid-scan can be missed until the next full refresh.

Cheap refresh: every response carries an `ETag` (hash of the page content, excluding `server_time`) and `Cache-Control: private, no-cache`. A request with a matching `If-None-Match` receives `304` with no body.

## `GET /api/v1/sync/status` (slice B3)

**Roles:** Administrator only. Counts for the last 48 hours: `ops_by_status` (all five ledger statuses), `resent_attempts` (sum of `attempt_count - 1`, a flaky-link signal), `time_flag_ops`, `unresolved_conflicts` and `oldest_unresolved_conflict_age_s` (all time; `null` when none), `verify_calls` and `verify_calls_with_unknown` (a spike means a restore happened). No payload bodies or ids.

## `GET /api/v1/sync/stats` (slice B3)

**Roles:** Administrator only. Query `from`, `to` (ISO datetimes; defaults: last 30 days; `from` must precede `to`; range at most 366 days; otherwise `400 INVALID_INPUT`). Operations are selected by `received_at`. Response: `volume` (`total_ops`, `by_status`, `recorded_offline` = received more than 120 s after `occurred_at`, `conflicts`, `conflicts_per_1000_ops`, `resolution_time_s` median and p90, `truncated` if more than 200,000 rows) and `clock_skew` (histograms of absolute `clock_offset_ms`, `offset_age_s` and receive lag, `time_flag_ops`, `time_flag_share`, `time_flag_counts`). Receive lag and `recorded_offline` are measured against the stored, clamped business time (`occurred_at`), so `too_old` rows (which store the unclamped time) show their full lag. Aggregates only: no `payload`, `op_id`, device, user, equipment or ward identifiers. The collision statistics and CSV export belong to slice B4b/D1.

## Conflict review (slice B4)

**Roles:** Administrator and Equipment Pool Staff; Read Only `403`, no token `401`. The `FORBIDDEN` result-code class (user permissions) is administrator-only: staff do not see those rows in the list, and detail/dismiss/apply-now return `403 SYNC_REVIEW_ADMIN_ONLY`. Listing and opening are not audited.

### `GET /api/v1/sync/conflicts`

Reviewable rows: `conflict`, plus `pending` rows whose 48 h dependency window has run out (`first_seen_at` older than 48 h). Query: `status` (`unresolved` default = both; `conflict`; `pending`; `resolved`; otherwise `400 INVALID_INPUT`), `result_code`, `op_type`, `operator_id`, `stale_context`, `device_id`, `received_from`, `received_to`, `limit` (1 to 100, default 50), `offset`. Order: `stale_context` first, then `received_at` ascending, then `op_id`. Response `{ total, limit, offset, items }`; each item: `op_id`, `op_type`, `status`, `result_code`, `admin_only`, `stale_context`, `time_flag`, `device_id`, `received_at`, `first_seen_at`, `occurred_at`, `attempt_count`, `operator` and `submitted_by` (`{id, full_name}`; the latter only when it differs), `equipment` (`id`, `bcm_code`, `equipment_name`, `status` only; never Item No or Asset Number), `ward_name`, `transaction_id`, `receipt_outcome`, `resolution`, `dismiss_reason`, `resolved_by`, `resolved_at`. The raw payload, payload hash and email addresses are never returned.

### `GET /api/v1/sync/conflicts/{op_id}`

The item plus `payload_summary` (dispatch: `dispatch_type`, `routine_round`, `notes`; receipt: `transaction_id`, `receipt_outcome`, `notes`), `resolution_note`, and an advisory `apply_now_possible` / `apply_now_blocker` (the lifecycle precondition evaluated now). Applied, rejected and not-yet-expired pending rows are `404`.

### `POST /api/v1/sync/conflicts/{op_id}/dismiss`

Body (strict): `{ "reason": "already_recorded" | "duplicate_physical_entry" | "not_real" | "handled_elsewhere", "note"?: string (max 500) }`; the reason is required (`422`). One conditional UPDATE (`conflict`/expired `pending` to `resolved`, `resolution=dismissed`, `resolution_note` = `reason` or `reason: note`) plus one `sync_conflict_resolved` audit entry (actor = resolver; `after_data` has original operator, device, original op id), atomically. No business change and no export event. Response `{ op_id, status, resolution, resolved_by, resolved_at }`.

### `POST /api/v1/sync/conflicts/{op_id}/apply-now`

No body (any request body is ignored). Re-runs the stored payload through `borrow_service.borrow` / `return_equipment` as a **new** operation: fresh `op_id` for the new ledger row (for a dispatch the transaction id is the ORIGINAL op id, so offline receipts that reference it resolve), a synthetic `device_id` with `device_seq` 0, `actor_user_id` = resolver (audit actor, status-history actor, `submitted_by_user_id`), recorded operator = the original operator (`borrower_user_id` / `received_by_user_id`, `original_user_id` in audit). Business time is the resolution time, except for an `OP_TOO_OLD` item, where the stored (unclamped) `occurred_at` is used (the resolver confirms that time; a receipt still never precedes its dispatch and a dispatch never precedes the equipment's latest receipt). In the same transaction: new `applied` ledger row (`result_code=RESOLVER_APPLIED`), the original becomes `resolved` / `applied_as` (`resolution_note` = new op id, `transaction_id` = the transaction), one `sync_conflict_resolved` audit entry, and exactly one export event. Response adds `new_op_id`, `transaction_id`.

Failure modes: the precondition no longer holds (`409 SYNC_APPLY_FAILED`): nothing is applied, the item stays `conflict`, `result_code` is refreshed (never for the administrator-only class) and `resolution_note` records `apply_failed:<CODE>`. Already resolved/applied, or lost to a concurrent resolver (`409 SYNC_OP_NOT_RESOLVABLE`): of two simultaneous resolvers exactly one wins; the loser's business write is rolled back.

Held dependents: holds are client-side (design 9.1 item 3); there is no server hold state. Once the original row is `resolved` the client sends its held follow-up ops, validated normally. Per-equipment timelines, Apply sequence and collision statistics are slice B4b (next section).

## Timeline, Apply sequence and collision statistics (slice B4b)

Owner decisions D7 (human-confirmed sequencing) and D8: **`SYNC_AUTO_SEQUENCE` is not enabled and no auto-sequencing code exists**; the statistics below are the evidence for the post-pilot decision. Nothing here applies anything without a resolver's explicit request.

### `GET /api/v1/sync/equipment/{equipment_id}/timeline`

**Roles:** Administrator, Equipment Pool Staff (Read Only `403`, no token `401`, unknown equipment `404`). Rows of the `FORBIDDEN` class are returned to administrators only. Response `{ equipment {id, bcm_code, equipment_name, status}, server_time, events }`. `events` merges (a) committed transactions for the equipment (a `dispatch` event at `borrowed_at`, a `receipt` event at `returned_at`; last 7 days plus any open one; `source: "transaction"`, never selectable) with (b) the equipment's reviewable ledger ops (`conflict`, expired `pending`; `source: "op"`, `selectable: true`; the equipment of a receipt comes from its target transaction, or from the reviewable dispatch that will create it). Order: `at` (the ledger `occurred_at`, falling back to `received_at`), committed history first on ties; within one device the ops are re-ordered by `device_seq`, which overrides time. Each event carries `band_s` (uncertainty, 30 s + 1 min per hour since the device clock offset was measured; 0 for committed events) and `order_uncertain` (true when its band overlaps another event's from a different source/device). Op events also carry `op_id`, `status`, `result_code`, `admin_only`, `stale_context`, `time_flag`, `device_id`, `device_seq`, `operator`, `ward_name`, `receipt_outcome`. No payload, Item No or Asset Number.

### `POST /api/v1/sync/equipment/{equipment_id}/apply-sequence`

**Roles:** as above. Body (strict): `{ "op_ids": [uuid, ...] (1 to 25, ordered), "dry_run"?: bool }`. The resolver confirms the order; the server applies it as given.

Whole-request validation happens before any write: an unknown id `404`; a repeated id, or an op that belongs to another equipment `400 INVALID_INPUT`; an op not open for review (already applied/resolved) `409 SYNC_OP_NOT_RESOLVABLE`; an administrator-only op for staff `403 SYNC_REVIEW_ADMIN_ONLY` (nothing applied).

* `dry_run: true`: an advisory lifecycle simulation (equipment availability and the target transaction, carried forward step by step); writes nothing. Returns `{ dry_run, steps, failed, remaining }`.
* Otherwise each op runs through exactly the Apply now path (`borrow_service.borrow` / `return_equipment`) as **its own transaction**, in the given order, and the run **stops at the first failure** (design 9.7 point 4: not all-or-nothing, because the services own their commit boundaries and each applied op is a true, individually valid event). Per op: new `applied` ledger row, original `resolved` / `applied_as`, one `sync_conflict_resolved` audit entry (actor = resolver, `original_user_id` = recorded operator), exactly one export event; a dispatch's transaction id is the original `op_id`, so a later receipt in the same sequence resolves. Business time is the resolution time, as for Apply now (`OP_TOO_OLD` ops keep the confirmed stored time), so sequence-applied ops count at resolution time in later reporting (PR16 `business_date`/`shift`). Ops from one device must be listed in `device_seq` order (`400` otherwise); deleted equipment is `404`; an unexpected error after a success returns the partial `steps` with `failed.code = INTERNAL_ERROR`. The timeline response carries `truncated` (the newest 2,000 reviewable rows were scanned).
* Response `200 { dry_run:false, steps:[{op_id, ok:true, new_op_id, transaction_id}], failed:{op_id, ok:false, code, message}|null, remaining:[op_id...] }`. When the **first** op fails nothing was applied and the Apply now error is returned unchanged (`409 SYNC_APPLY_FAILED` or `409 SYNC_OP_NOT_RESOLVABLE`); a failure after at least one success is a `200` with `failed` set. The failed op stays in review with `apply_failed:<CODE>`; later ops are untouched.
* Idempotent under double submit: the per-op conditional UPDATE decides the winner, so each op is applied at most once; a repeat (or the loser of two simultaneous submissions) gets `409 SYNC_OP_NOT_RESOLVABLE` and writes nothing.

### `GET /api/v1/sync/collisions/stats`

**Roles:** Administrator only. Query `from`, `to` (defaults: last 30 days; `from` before `to`; at most 366 days; otherwise `400`). Operations that conflicted (still `conflict`, or since `resolved`) received in range: `total_conflicts`, `by_result_code`, `by_status`, `by_day`, `truncated` (more than 50,000 rows), and `groups`: `equipment_with_multiple_conflicts`, `cross_device`, `by_outcome` (`open`, `same` = all applied in corrected-time order, `different`, `dismissed_only`, `mixed`), `agreement_rate` (`same` / (`same` + `different`)) and `would_have_auto_sequenced` (`conditions_met` = cross-device, no `stale_context`, no overlapping bands; of those `resolved_same_order`, `resolved_differently`, `agreement_rate`). Groups are derived at query time from the ledger (per equipment); the stored `collision_group_id` / proposal columns are not populated by this slice. Aggregates only.

### `GET /api/v1/sync/collisions/export`

**Roles:** Administrator only; same `from`/`to`. `text/csv` attachment (UTF-8 with BOM, `Cache-Control: no-store`) with columns `op_id, op_type, status, result_code, resolution, bcm_code, ward, operator, resolved_by, occurred_at, received_at, resolved_at, device_id, stale_context, time_flag`. No payload, notes or patient data (none exists); cells that start with a formula character are prefixed with `'`.

## Envelope versioning and app updates (slice S6)

Design: `docs/design/PR25D_OFFLINE_OPERATION_PLAN.md` section 13.3.

Each operation may carry `envelope_version` (integer, optional, default `1`). A missing field means version 1, so operations queued on a device before S6 are accepted unchanged. The server supports `MIN_SUPPORTED_ENVELOPE_VERSION` (1) through `CURRENT_ENVELOPE_VERSION` (1), defined in `backend/app/schemas/sync.py`. The check covers the whole request before anything is processed or written; one bad operation rejects the batch.

| Condition | HTTP | `code` | Client behaviour |
|---|---|---|---|
| version below the minimum supported | `426` | `CLIENT_TOO_OLD` | Queue untouched (rows return to `pending`); the app shows "update required" and stops sending until reloaded. |
| version above the current | `400` | `ENVELOPE_VERSION_UNSUPPORTED` | Queue untouched; backs off and retries (a newer frontend reached an older backend: deploy-order mistake). |

Rules for future envelope changes: additive only; raise `CURRENT_ENVELOPE_VERSION` in the release that adds a field; keep the previous version in range for at least one release; raise `MIN_SUPPORTED_ENVELOPE_VERSION` only when the old contract is dropped, which turns stale clients into `CLIENT_TOO_OLD` instead of silent misbehaviour. The client constant is `ENVELOPE_VERSION` in `frontend/src/offline/localOps.ts`.

Client update behaviour: the PWA uses `registerType: "prompt"`. A new service worker waits; the operator sees "มีเวอร์ชันใหม่" and taps update. The reload is refused while any outbox row is `pending`/`sending`/`held` (any user on the device), a dispatch/receipt form is dirty, or the sync worker is mid-send. IndexedDB (`mep-offline`) is upgraded in place by forward-only migrations (`MIGRATIONS` in `offlineStore.ts`); a database newer than the app yields `STORE_TOO_NEW` and is never touched. Deploy order: backend first, then frontend (`docs/runbooks/PR24_STAGING_DEPLOYMENT_RUNBOOK.md`, section 12).
