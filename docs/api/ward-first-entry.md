# Ward-First Entry API (batch, contact name, checklists, cuffs)

**Purpose:** Backend API contract for Roadmap PR27/PR28 — ward-first multi-equipment dispatch and receipt (D3), the optional ward contact name (D7), accessory and Cryo-Cuff checklists (D4/D10) and Cryo-Cuff cuff tracking (D11). The frontend (a separate PR) consumes this contract.
**Authority:** Documents behavior in `backend/app/api/v1/transactions.py`, `backend/app/api/v1/cuffs.py`, `backend/app/api/v1/borrow.py`, `backend/app/schemas/{batch,checklist,transaction}.py`, `backend/app/services/{batch,borrow,cuff,checklist}_service.py` and migration `0031_contact_checklists_cuffs`. Decisions: `docs/DECISION_LOG.md` 2026-11-25 (D3, D4, D7, D10, D11).
**Update trigger:** Any request/response shape or error behavior below changes.
**Maintainer:** Repository Owner

**Roles (every endpoint here):** `administrator`, `equipment_pool_staff` (`EQUIPMENT_POOL_OPERATION_ROLES`). Read Only gets `403`, no token `401`. Ward staff are not users.

**Out of scope here:** the daily shift report (PR30), the Monitor UI. Patient HN (Roadmap PR29) is described in section 8 below. The read-only export API (`/export/events`) is unchanged and does not expose the contact name or checks.

## 1. Ward contact name (D7)

Optional free text naming the ward staff member who received (dispatch) or handed back (receipt) the equipment. Never required, never a patient name.

- Request field `ward_contact_name` (string or `null`): trimmed; blank/whitespace becomes `null`; max **100** characters and no control characters, otherwise `422` (never silently truncated).
- Dispatch stores it as `dispatch_contact_name`; receipt as `receipt_contact_name` (one value per submission, applied to every equipment's transaction in a batch).
- Returned in `TransactionOut` (and therefore `/transactions`, `/reports/receive`, `/reports/issue`), the Monitor events (section 7), the PR17 export documents (a single "ผู้ใช้หอผู้ป่วย" column holding the dispatch-side name on the issue report and the receipt-side name on the receive report) and the legacy CSV/XLSX export (two columns).
- Application logs never contain it; audit rows for cuff receipts do (it is the only place that value is kept for `receive-cuffs`).

## 2. Checklists (D4, D10)

### 2.1 Which checklist applies

`equipment_categories.checklist_kind` (`'standard'` default | `'cryo_cuff'`) is explicit master data:

- Migration 0031 backfills `'cryo_cuff'` for categories whose name contains `cryo` (case-insensitive); `POST /categories` applies the same default when `checklist_kind` is omitted (and accepts an explicit value); `PATCH /categories/{id}` `{ "checklist_kind": "standard" | "cryo_cuff" }` (administrator only, audited) edits it. `CategoryOut` now includes `checklist_kind`.
- Equipment without a category uses `standard`.
- `GET /equipment/{id}/dispatch-check` now also returns `checklist_kind` so the client knows which form to show.
- Each transaction snapshots its kind at dispatch (`TransactionOut.checklist_kind`; `null` for historical rows, which fall back to the equipment's current category at receipt). Editing a category never reinterprets stored checks.

### 2.2 Wire shapes (discriminated by `kind`)

```json
{ "kind": "standard", "screen_ok": true, "charger_ok": true, "clamp_ok": true }
```

```json
{
  "kind": "cryo_cuff",
  "body_ok": true, "charger_ok": true, "lid_with_charger_ok": true,
  "lid_without_charger_ok": true, "hose_oring_ok": true, "cuff_ok": true,
  "cuffs": { "back_hip_rib": 0, "knee": 0, "shoulder": 0, "ankle": 0 }
}
```

- `kind` is required. Omitted booleans inside a submitted object default to `true` (checked/normal); omitted `cuffs` types default to `0`. Booleans are strict (`"yes"`/`1` are `422`); cuff counts are integers `0..99`; unknown fields are `422`.
- **Omitting the whole checks object stores `NULL` = not recorded.**
- A `kind` that does not match the equipment's kind: `400 CHECKLIST_KIND_MISMATCH` (`details: {expected_kind, received_kind}`), nothing written.
- Request field names: `dispatch_checks` on `POST /borrow` (and the sync dispatch body), `receipt_checks` on `POST /return/{id}` (and the sync receipt body), `checks` on batch items. Stored in `borrow_transactions.dispatch_checks` / `receipt_checks` (JSONB) and returned in `TransactionOut` as `dispatch_checks` / `receipt_checks` (same shapes).

### 2.3 Report column mapping (for PR30)

`app.schemas.checklist.report_columns(checks)` yields the three report columns: `standard` → screen=`screen_ok`, charger=`charger_ok`, clamp=`clamp_ok`; `cryo_cuff` → screen=`body_ok`, charger=`charger_ok`, clamp=`lid_with_charger_ok`. Items 4-6 (`lid_without_charger_ok`, `hose_oring_ok`, `cuff_ok`) and the cuff counts are stored but not in the daily report. A not-recorded checklist maps to `null`/`null`/`null`.

## 3. Single dispatch / receipt additions

`POST /borrow` (`BorrowRequest`) gains: `ward_contact_name`, `dispatch_checks`, and **`expected_status`** (equipment status enum). If given and the equipment's status differs now, the dispatch is refused `409 DISPATCH_WARNING_STALE` (`details.expected_status` set) — a warning confirmation can no longer apply to equipment whose status changed meanwhile. Decommissioned equipment still fails `EQUIPMENT_NOT_AVAILABLE` first.

`POST /return/{transaction_id}` (`ReturnRequest`) gains: `ward_contact_name`, `receipt_checks`, `cuffs_returned` (`{back_hip_rib, knee, shoulder, ankle}`, Cryo-Cuff only). Cuffs handed back with the device are, in order of precedence: `cuffs_returned`, else a `cryo_cuff` `receipt_checks.cuffs`, else none (**device-only receipt**). The stored `receipt_checks.cuffs` always equals the counts actually applied. More than outstanding for any type: `409 CUFF_RETURN_EXCEEDS_OUTSTANDING` and the whole receipt is refused (transaction stays open, no side effects).

## 4. Cuff tracking (D11)

Cuffs are accessories attributed to the dispatch transaction (and so its ward, following any PR9A ward correction); they have **no equipment state** (still exactly four equipment states, no cleaning state).

- At dispatch, a `cryo_cuff` checklist's `cuffs` counts are recorded as **issued** (`transaction_cuffs`, one row per transaction and type with `issued_count > 0`). Outstanding = issued − returned per type; DB CHECKs make `returned > issued` or a negative balance impossible; returns use a conditional `UPDATE ... WHERE returned + n <= issued`, so concurrent receipts cannot over-return.
- The device may be dispatched again while cuffs are outstanding (re-dispatch, D8): the earlier transaction is closed by re-dispatch and its cuffs stay outstanding against it and its ward.
- Every cuff movement writes an audit row: action `cuff_issue` (`after_data.cuffs_issued`) and `cuff_return` (`after_data.cuffs_returned`, `source` = `receipt` | `receive_cuffs`, and `ward_contact_name` for `receive_cuffs`).

### `POST /api/v1/transactions/{transaction_id}/receive-cuffs`

Body: `{ "cuffs": { "knee": 1, ... }, "ward_contact_name": null }` (strict; at least one cuff, each type `0..99`).

Allowed only when the transaction is `closed` (device received, or closed by re-dispatch). All-or-nothing across types; never exceeds outstanding. `200`:

```json
{ "transaction_id": "uuid", "transaction_no": "TX-...",
  "cuffs_issued": {"back_hip_rib":2,"knee":2,"shoulder":0,"ankle":1},
  "cuffs_returned": {"back_hip_rib":1,"knee":2,"shoulder":0,"ankle":0},
  "cuffs_outstanding": {"back_hip_rib":1,"knee":0,"shoulder":0,"ankle":1} }
```

Errors: `404 TRANSACTION_NOT_FOUND`; `400 INVALID_INPUT` (all counts zero); `409 CUFF_RECEIVE_NOT_ALLOWED` (device still out — record cuffs with the device receipt instead); `409 CUFF_RETURN_EXCEEDS_OUTSTANDING` (`details.exceeded` = `{type: {requested, outstanding}}`); `422` validation. This endpoint is online-only (not an offline-sync op type).

### `GET /api/v1/cuffs/outstanding?ward_id=`

Outstanding cuffs grouped by the transaction's ward (optional `ward_id` filter; bad UUID `400`):

```json
{ "total_outstanding": 3,
  "items": [ { "ward_id": "uuid", "ward_name": "Ward Alpha",
    "cuffs": {"back_hip_rib":2,"knee":1,"shoulder":0,"ankle":0}, "total": 3,
    "transactions": [ { "transaction_id": "uuid", "transaction_no": "TX-...", "equipment_id": "uuid",
      "bcm_code": "BCM-1", "equipment_name": "Dev", "dispatched_at": "2026-11-25T10:00:00Z",
      "device_received": false, "cuffs": {"back_hip_rib":2,"knee":1,"shoulder":0,"ankle":0} } ] } ] }
```

## 5. Batch endpoints (D3)

One submission = one ward + N equipment. Every item is its own transaction processed by the ordinary `borrow` / `return_equipment` services, **each in its own database transaction** (commit on success, rollback on failure), so a failing item never affects the others. The response is `200` with a per-item result even if every item failed; only a malformed request is `422`, and a shared `ward_id` that does not exist is `400 INVALID_INPUT` for the whole request (nothing written). Items are processed in order; max **50** items; duplicates within one request are `422`.

### `POST /api/v1/transactions/dispatch-batch`

```json
{
  "ward_id": "uuid", "ward_contact_name": "Khun Somsri", "phone": "1234", "note": "…",
  "items": [
    { "equipment_id": "uuid", "checks": { "kind": "standard" },
      "acknowledge_status_warning": false, "expected_open_transaction_id": null, "expected_status": null }
  ]
}
```

`phone` (max 20) → `phone_number`, `note` → `notes`, `ward_contact_name` → `dispatch_contact_name` on every transaction. No dispatch type / round. Item `checks` is the dispatch checklist; item `hn` (optional, Roadmap PR29) is that equipment's own HN.

### `POST /api/v1/transactions/receipt-batch`

```json
{
  "ward_id": "uuid-or-null", "ward_contact_name": "Khun Malee", "note": "…",
  "items": [
    { "transaction_id": "uuid", "receipt_outcome": "usable", "checks": null, "cuffs_returned": null },
    { "equipment_id": "uuid", "receipt_outcome": "defective", "checks": { "kind": "cryo_cuff" }, "cuffs_returned": { "knee": 1 } }
  ]
}
```

Each item gives exactly one of `transaction_id` or `equipment_id` (the equipment's open transaction; none → per-item `TRANSACTION_NOT_FOUND`). `ward_id` is informational: receiving equipment dispatched to another ward is accepted with **no warning**, and only the first (dispatch) ward is recorded — no transfer tracking. `receipt_outcome` is `usable` | `defective` (atomic per item).

### Response (both)

```json
{ "total": 3, "succeeded": 2, "failed": 1,
  "results": [
    { "index": 0, "ok": true, "equipment_id": "uuid", "transaction_id": "uuid", "transaction_no": "TX-…",
      "cuffs_outstanding": null, "error": null },
    { "index": 1, "ok": false, "equipment_id": "uuid", "transaction_id": null, "transaction_no": null,
      "cuffs_outstanding": null,
      "error": { "code": "DISPATCH_STATUS_WARNING", "message": "…", "status": 409, "details": { "warning": "defective" } } }
  ] }
```

`error.code` is any single-request error code (`docs/api/ERROR_CODES.md`), e.g. `EQUIPMENT_NOT_FOUND`, `EQUIPMENT_NOT_AVAILABLE`, `DISPATCH_STATUS_WARNING` (re-send that item alone with `acknowledge_status_warning` + `expected_status`), `DISPATCH_WARNING_STALE`, `CHECKLIST_KIND_MISMATCH`, `TRANSACTION_NOT_FOUND`, `TRANSACTION_ALREADY_RETURNED`, `CUFF_RETURN_EXCEEDS_OUTSTANDING`, or `INTERNAL_ERROR` (unexpected; logged, no details). `cuffs_outstanding` is the transaction's remaining cuffs (`null` when none were ever issued).

## 6. Offline sync (`POST /sync/operations`)

Batches are **not** a sync op type: a queued ward-first submission is sent as N ordinary single `dispatch` / `receipt` operations (one per equipment, sharing the same `ward_contact_name`). The sync `dispatch` body (= `BorrowRequest`) and `receipt` body (= `ReturnRequest` + `transaction_id`) now carry `ward_contact_name`, `dispatch_checks` / `receipt_checks`, `expected_status` and `cuffs_returned` exactly as in section 3. The new keys are left out of the stored/hashed business payload when unset, so the payload hash of an op queued before this change is unchanged (a retry is still a `duplicate`, not `OP_ID_REUSED`). `CHECKLIST_KIND_MISMATCH` and `CUFF_RETURN_EXCEEDS_OUTSTANDING` land in the existing conflict/review path; malformed fields are a whole-request `422`. `receive-cuffs` is not queued offline.

## 7. Monitor events (`GET /monitor/events`)

Each event gains: `ward_contact_name` (the event side's name), `checklist_kind`, `checks` (the event side's checklist), `cuffs_outstanding` (counts still outstanding for the transaction, `null` if none were issued). The `q` search also matches the event side's contact name.

## 8. Errors added

| Status | Code | Cause |
|---|---|---|
| 400 | `CHECKLIST_KIND_MISMATCH` | submitted checklist `kind` differs from the equipment's / transaction's kind |
| 409 | `CUFF_RETURN_EXCEEDS_OUTSTANDING` | more cuffs of a type than outstanding (receipt, `receive-cuffs`, or a concurrent loser) |
| 409 | `CUFF_RECEIVE_NOT_ALLOWED` | `receive-cuffs` on a transaction whose device is still out |
| 409 | `DISPATCH_WARNING_STALE` | also: `expected_status` no longer matches the equipment's status |

## Persistence summary (migration `0031_contact_checklists_cuffs`)

`borrow_transactions`: `dispatch_contact_name`, `receipt_contact_name` VARCHAR(100) NULL; `checklist_kind` VARCHAR(20) NULL (CHECK `standard`/`cryo_cuff`); `dispatch_checks`, `receipt_checks` JSONB NULL. `equipment_categories.checklist_kind` VARCHAR(20) NOT NULL DEFAULT `'standard'` (CHECK). New table `transaction_cuffs` (`transaction_id` FK RESTRICT, `cuff_type`, `issued_count > 0`, `0 <= returned_count <= issued_count`, unique per transaction+type). Additive, no backfill other than the category default.

## 8. Patient HN (Roadmap PR29, Owner Governance 2026-11-25 D1)

* **Write:** an optional `hn` string on `POST /borrow`, on each `POST /transactions/dispatch-batch` item (HN is per equipment, never per slip) and on a sync `dispatch` op. Trimmed; blank = none; otherwise 1-20 characters of letters, digits, `-` and `/`, else `422` (the message never echoes the value). Receipt bodies do not accept it.
* **Storage:** Fernet token (`cryptography`) in `borrow_transactions.hn_ciphertext` using `HN_ENCRYPTION_KEY` from the host `.env` (comma-separated keys allowed for rotation: first encrypts, all decrypt). `has_hn` (boolean) records that one exists.
* **Read:** every transaction response (`TransactionOut`, report rows, monitor events) carries only `has_hn`. The HN is returned by exactly one endpoint, `POST /transactions/{id}/reveal-hn` (Administrator and Equipment Pool Staff; Read Only `403`): `200 {"hn": "..."}` with `Cache-Control: no-store`. Each successful reveal writes one `hn_reveal` audit row (actor, `borrow_transaction` + id, time; never the value). `404 HN_NOT_RECORDED` when the transaction has none.
* **No key / wrong key:** a dispatch carrying an `hn` is refused `503 HN_UNAVAILABLE` and nothing is written; dispatches without `hn` are unaffected; reveal answers `503 HN_UNAVAILABLE` (no audit row). Losing the key makes stored HNs permanently unreadable.
* **Never present in:** logs (a defensive `hn=`/`'hn':` scrubber is in `JsonFormatter`), audit before/after (`hn`/`hn_ciphertext` keys are masked; `borrow` audit stores only `has_hn`), reports/print/PDF/Excel/CSV, `/export/events`, notifications, sync review/timeline/CSV, error messages, database backups (ciphertext only). Not searchable.
