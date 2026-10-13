# PR25D — Offline Operation Design

**Purpose:** Design (no code) for letting Equipment Pool staff keep dispatching and receiving equipment while the department server is unreachable, and for syncing safely afterwards.
**Status:** Draft for Owner approval. PR25E (implementation) does not start until the Owner approves this document and answers the open questions in section 18.
**Scope of this PR:** this file only. It does not edit `ROADMAP.md`, `DECISION_LOG.md`, ADRs, or any code.
**Governing sources:** `AGENTS.md`; `docs/BUSINESS_RULES.md`; `docs/ARCHITECTURE_GUARDRAILS.md`; `knowledge/adr/ADR-002` to `ADR-006`; `docs/DECISION_LOG.md` (2026-10-13, "Local Production on the department host"); `docs/ROADMAP.md` ("Stage 1", PR25A to PR25E).

---

## 0. สรุปภาษาไทย (Thai summary)

**เป้าหมาย:** เมื่อเซิร์ฟเวอร์ (PC ของแผนก) ล่มหรือเชื่อมต่อไม่ได้ เจ้าหน้าที่ Equipment Pool ยังบันทึก "จ่ายเครื่อง" และ "รับคืน (ใช้ได้ / ชำรุด)" ต่อได้ แล้วระบบส่งข้อมูลเข้าเซิร์ฟเวอร์เองเมื่อเชื่อมต่อได้อีกครั้ง

**แนวคิดหลัก**
1. ทุกการกระทำ (dispatch / receipt) สร้าง **UUID ฝั่งเครื่องผู้ใช้** เป็นกุญแจกันซ้ำ (idempotency key) ส่งซ้ำกี่ครั้งเซิร์ฟเวอร์ก็บันทึกครั้งเดียว แก้ปัญหา "ตั๋วซ้ำ" แบบ AppSheet ที่เกิดจากเครื่องที่ยังไม่ sync ไปคำนวณเลขถัดไปจากข้อมูลเก่า (ไม่ต้องมีเลขตั๋วอ่านง่าย)
2. ระหว่างออฟไลน์ ทุกการกระทำเข้าคิวใน IndexedDB แยกตามผู้ใช้ เมื่อกลับมาออนไลน์ ระบบส่งตามลำดับของเครื่องนั้น (หมายเลขลำดับต่อเครื่อง) ไม่ใช้นาฬิกาเทียบข้ามเครื่อง เพราะนาฬิกาแต่ละเครื่องไม่ตรงกัน
3. เซิร์ฟเวอร์ตรวจทุกรายการผ่าน service เดิม (`borrow_service`) เหมือนการกดบนหน้าจอปกติ ไม่มีทางลัด ถ้าขัดกับสถานะปัจจุบัน (เช่น เครื่องถูกจ่ายไปแล้ว) จะ **ไม่แก้ให้อัตโนมัติ** แต่ส่งเข้า **รายการรอตรวจสอบโดยคน** (Conflict Review) เจ้าหน้าที่ Pool หรือ Administrator เป็นคนตัดสิน และมีบันทึก audit
4. เครื่องผู้ใช้เก็บ **journal 48 ชั่วโมง** ของทุกรายการที่ส่งสำเร็จ หลังกู้เซิร์ฟเวอร์จาก backup (ที่อาจสูญหายได้สูงสุดประมาณ 1 ชั่วโมง) เครื่องจะถามเซิร์ฟเวอร์ว่า "รายการนี้มีไหม" แล้วส่งเฉพาะที่หายไปซ้ำ โดยใช้ UUID กันซ้ำ
5. หน้าแอปโหลดได้แม้เซิร์ฟเวอร์ล่ม เพราะเป็น PWA ที่ติดตั้งแล้ว (service worker เก็บไฟล์หน้าเว็บไว้)
6. ข้อมูลที่เก็บในเครื่องมีเท่าที่จำเป็น (รหัส BCM, ชื่อเครื่อง, วอร์ด, สถานะล่าสุด) และล้างเมื่อ logout ส่วนรายการที่ยังไม่ sync จะไม่ถูกลบ

**ข้อจำกัดสำคัญที่ Owner ต้องตัดสินใจ (ดูหัวข้อ 18):** การสแกน QR ออฟไลน์ต้องมีตาราง Item No ในเครื่อง ซึ่งขัดกับ ADR-004 (Item No ห้ามอยู่ใน response ปกติ) ข้อเสนอเริ่มต้นคือ **ออฟไลน์ใช้การค้นหา BCM Code เท่านั้น** และเลื่อน QR ออฟไลน์ไว้จนกว่าจะแก้ ADR-004

---

## 1. Goals, constraints, inputs

### 1.1 Owner inputs (recorded 2026-10-13)

- Devices: personal phones, department tablets, department PCs. Shared devices exist.
- Server: a single department PC running Docker. Hourly backups (Drive upload is PR25A). **No standby machine.**
- The person who dispatches a device normally keys it, so true conflicts are rare.
- The AppSheet pain: unsynced clients generated **duplicate ticket keys from stale local data**.
- No human-readable ticket number is needed; UUIDs are enough.
- Work must continue when the server is down; sync on reconnect in a sensible order. Options are welcome.

### 1.2 Design goals

1. Never lose an operation the operator saw as accepted on their device.
2. Never create a duplicate transaction, however many times an operation is re-sent.
3. Never bypass the dispatch/receipt services; the server remains the only judge of lifecycle validity.
4. Never auto-resolve a lifecycle conflict.
5. Recover the up-to-1-hour backup gap from client journals.
6. Stay inside every guardrail in `AGENTS.md` (four identifiers, four states, no cleaning state, no patient data, no ward-to-ward tracking, no MEMS dependency).

### 1.3 What the code looks like today (grounding)

| Fact | Where | Consequence for this design |
|---|---|---|
| Dispatch is `borrow_service.borrow()`; it validates equipment is exactly `AVAILABLE_AT_POOL`, validates `ward_id`, draws `transaction_no` from a Postgres sequence, creates the transaction, moves equipment to `ISSUED_TO_WARD`, writes audit, then **commits inside the service** | `backend/app/services/borrow_service.py` | The idempotency ledger row must be written inside the same session before that commit (section 6.3), not by a wrapper after it. |
| Receipt is `return_equipment()` keyed by server-assigned `transaction_id`; conditional `UPDATE ... WHERE status='open'` is the race guard; loser gets `RECEIPT_RACE_LOST`, repeat gets `TRANSACTION_ALREADY_RETURNED` (both 409) | same file; ADR-006; PR8A/PR8C | These 409 codes already express most conflicts. A replayed receipt with the same op UUID must be recognised as "already applied", not as a repeat. |
| `BorrowRequest` / `ReturnRequest` use `extra="forbid"` | `backend/app/schemas/transaction.py` | Idempotency fields cannot be tacked onto the existing bodies; a new envelope is needed (section 6.1). |
| `borrowed_at` / `returned_at` are set by the server at write time; PR16 derives `business_date` and `shift` from them | `models/transaction.py`; `core/reporting_time.py` | A dispatch replayed hours later would be filed under the wrong shift unless the true event time is carried (section 11). |
| Transaction PK is `UUIDPKMixin` (`uuid4` default); `transaction_no` is a separate server sequence value | `models/mixins.py`; `crud/transaction.py` | A client-chosen UUID can become the transaction PK. `transaction_no` stays server-assigned and is simply not used by offline clients. |
| `idx_tx_one_active_borrow` (unique on `equipment_id` where `status='open'`) | `models/transaction.py` | The database already guarantees at most one open transaction per equipment, even under replay races. |
| Equipment responses deliberately **exclude Item No**; QR resolution is server-side `POST /equipment/resolve-qr` | `schemas/equipment.py`; ADR-002/004 | Offline QR scan cannot work without shipping Item No to devices (open question Q1). |
| Access token lifetime 15 min; refresh token 7 days in an httpOnly cookie | `core/config.py`; `api/v1/auth.py` | A device offline for hours always has an expired access token; replay needs a refresh first (section 8.4). |
| Frontend persists `accessToken` and `user` to `localStorage` key `mep-auth` | `frontend/src/store/authStore.ts` | Existing behaviour; wipe-on-logout must cover it (section 12). |
| `api.ts` response interceptor calls `logout()` whenever `/auth/refresh` fails, **including on a network error** | `frontend/src/services/api.ts` | Offline, the first expired token would log the operator out and discard the session. Must change to log out only on a real 401/403 from refresh (slice S1). |
| `vite-plugin-pwa` with `registerType: "autoUpdate"`; precache of `js/css/html/svg/png/ico`; one runtime rule: `NetworkFirst` for `/api/v1/(equipment\|dashboard)`, 3 s timeout, **5-minute max age**, 500 entries; no explicit `navigateFallbackDenylist` | `frontend/vite.config.ts` | The shell is already precached, so it can load offline. The API cache is too short-lived to serve as an offline reference store, is not user-scoped, and survives logout. Replace it with an explicit IndexedDB reference cache. |
| nginx serves `/sw.js` with `Cache-Control: no-cache`, `/assets/` immutable, SPA fallback to `index.html` | `frontend/nginx.conf` | Correct for update checks; keep. |
| No IndexedDB, Dexie, or Workbox background-sync code exists | `frontend/package.json` | Greenfield; the queue is custom (section 7). |

---

## 2. Options considered (summary)

| # | Option | Verdict |
|---|---|---|
| A | **Client-generated UUID per operation + IndexedDB outbox + server idempotency ledger + human conflict review** | **Chosen.** Directly answers the AppSheet duplicate-key failure and matches the Owner's decisions. |
| B | Workbox Background Sync (replay failed `fetch` requests by the service worker) | Rejected as the primary mechanism. Not available on iOS Safari; replays raw requests with no per-user binding, no ordering control, no conflict visibility. May be used later purely as a "wake up and try the outbox" nudge where supported (non-goal for v1). |
| C | CRDT / local-first database sync (PouchDB, etc.) | Rejected. Equipment state is a small state machine owned by server services; merging replicas would bypass `borrow_service` and violate "never bypass the lifecycle services". |
| D | Ordering by wall-clock timestamps across devices | Rejected (section 9.2). |
| E | A second server or warm standby so downtime never happens | Out of scope (Owner: no standby machine). Offline mode is the chosen mitigation. |
| F | Paper fallback only | Remains the last resort when the offline queue is unusable (section 15), not the plan. |

---

## 3. Offline scope

### 3.1 Operations that work offline (write)

| Operation | Offline? | Notes |
|---|---|---|
| Dispatch (`routine_round` or `on_demand`) | Yes | Same fields as online: equipment, ward, dispatch type, routine round, optional department/location ids and notes. |
| Receipt, outcome `usable` | Yes | Atomic, one step. Backend maps to `AVAILABLE_AT_POOL`. Cleaning is never asked or recorded. |
| Receipt, outcome `defective` | Yes | Backend maps to `UNAVAILABLE_DEFECTIVE`. |
| Everything else (ward correction, mark defective, reactivate, decommission, master data, users, imports, reports, audit views, cutover pages) | **No**, online only | These are administrative or review actions where stale local state is risky. They show "needs connection". |

The offline client sends only the business inputs (`receipt_outcome`, never an equipment status), preserving ADR-006 decision 3.

### 3.2 Read-only offline data (cached reference snapshot)

| Data | Used for | Fields cached (minimum) | Staleness shown |
|---|---|---|---|
| Equipment list | Pick equipment by BCM Code | `id` (UUID), `bcm_code`, display name, category name, last-known status | "as of HH:MM" per snapshot, and an amber badge if older than 12 h |
| Wards | Ward picker for dispatch | `id`, name | same |
| Departments, locations | Optional dispatch fields | `id`, name | same |
| Open transactions | Offline receipt | `transaction id`, `equipment id`, `ward id`, `borrowed_at` | same |
| Round times / dispatch types | Constants | static in the app bundle | n/a |

Not cached: Item No, Asset Number, user lists, phone numbers of others, audit log, reports, history. Item No is excluded by ADR-002/004 (see Q1 for QR).

Snapshot refresh: after login, then every 15 min while online, plus on every successful reconnect, via a new bounded paginated endpoint (section 6.5). Staleness is displayed, never hidden. The device also applies its **own pending operations** on top of the snapshot locally (a device with a pending dispatch of X shows X as "dispatched (not yet synced)"), which blocks the same operator from double-dispatching X offline.

### 3.3 Equipment identification offline

Offline identification is **manual BCM Code search against the cached list** (ADR-003 semantics: BCM is the only manual-search identifier; matching uses the canonical persisted form, so the snapshot must carry the canonical form of each BCM Code and the client must match against it using the same canonicalisation rule as the server; PR25E confirms the exact rule in the BCM search code). QR scanning offline is **not in v1** unless the Owner approves an ADR-004 change (Q1, options in section 18).

---

## 4. Principles that follow from the guardrails

1. **Server is the only judge.** The client queue records "what the operator did and believed"; it never decides lifecycle validity. Replay calls `borrow_service.borrow()` and `return_equipment()` unchanged in their business rules.
2. **No bypass of status maintenance.** There is no sync endpoint that sets an equipment status or closes a transaction directly. The sync layer is a thin envelope around the two services.
3. **Identity is bound to the operator.** An operation is attributed to the user who keyed it (`borrower_user_id` / `received_by_user_id`), never to whoever happens to be logged in when it replays.
4. **Idempotent by construction.** Re-sending is always safe.
5. **Humans resolve conflicts.** Machines detect and record them.

---

## 5. Identity and sequencing model

| Concept | Definition | Created by | Persisted |
|---|---|---|---|
| `op_id` | UUID v4 per operation, created when the operator taps Confirm, before any network call | Client | Client outbox + server ledger |
| `device_id` | UUID v4 per browser profile / installed PWA, created on first run (not a hardware ID) | Client | Client `meta` store + server ledger |
| `device_seq` | Per-device monotonic integer, incremented in the same IndexedDB transaction that stores the operation | Client | Client + server ledger |
| `user_id` | Authenticated operator that keyed the operation | Client records it; **server takes it from the token and rejects a mismatch** | Both |
| `occurred_at_local` + `clock_offset_ms` | Device clock reading at keying and the device's last known offset from server time (section 11) | Client | Both |

Rules:

- For a **dispatch**, `op_id` is also the new transaction's primary key (`borrow_transactions.id = op_id`). This is what lets an offline receipt refer to an offline dispatch before the server has ever seen it (the receipt carries `transaction_id = dispatch op_id`). The server accepts a client-chosen id only through the sync endpoint and only if it is a well-formed UUID v4 not already used.
- For a **receipt**, `op_id` is distinct; the receipt targets `transaction_id`.
- Clearing site data produces a new `device_id` and restarts `device_seq`. Nothing collides because identity is the UUID, not a counter derived from stale server state (the AppSheet failure mode).

---

## 6. Server-side changes (what PR25E must add)

### 6.1 API surface

One new router `backend/app/api/v1/sync.py`. Existing `POST /borrow` and `POST /return/{id}` stay unchanged for non-offline callers and tests; the new UI uses the sync endpoints for **all** dispatch and receipt traffic (online too), so online and offline exercise the same code path.

| Endpoint | Purpose | Roles |
|---|---|---|
| `POST /api/v1/sync/operations` | Submit an ordered batch (max 25 ops, each max 8 KB). Returns one result per op. | `EQUIPMENT_POOL_OPERATION_ROLES` |
| `POST /api/v1/sync/verify` | Send the `op_id`s from the 48 h journal; returns those the server does not know (restore recovery, section 10). Max 1000 ids. | same |
| `GET /api/v1/sync/snapshot` | Cursor-paginated reference snapshot (equipment, wards, departments, locations, open transactions) with a `server_time` field. Bounded page size. | `VIEW_AND_REPORT_ROLES` |
| `GET /api/v1/sync/conflicts` | Paginated review list, filter by status. | `equipment_pool_staff`, `administrator` (Q4) |
| `POST /api/v1/sync/conflicts/{op_id}/resolve` | Resolve one item (section 9.6). | same |
| `GET /api/v1/sync/status` | Counts by status for the last 48 h, oldest unresolved conflict age. | `administrator` |

Operation envelope (strict, `extra="forbid"`):

```text
{ op_id, device_id, device_seq, op_type: "dispatch" | "receipt",
  occurred_at_local, clock_offset_ms,
  dispatch: { ...exactly the BorrowRequest fields... }      // when op_type=dispatch
  receipt:  { transaction_id, receipt_outcome, notes }      // when op_type=receipt
}
```

The inner objects reuse the existing Pydantic models so field validation (`routine_round` consistency, no `due_at`/`borrower_name`/`quantity`, binary `receipt_outcome`) is not duplicated.

Per-op result:

```text
{ op_id, result: "applied" | "duplicate" | "retry_later" | "conflict" | "rejected",
  code: <stable machine code, e.g. EQUIPMENT_NOT_AVAILABLE>, transaction_id?, message }
```

HTTP status for the batch is 200 if the batch was processed, even when individual ops conflict; transport-level problems use normal 4xx/5xx. Each op runs in its **own** database transaction.

### 6.2 New table `client_operations` (the idempotency ledger and review list)

One additive Alembic revision (next after `0024_login_lockout`; additive-first, tested for upgrade and downgrade, per guardrails).

| Column | Type | Notes |
|---|---|---|
| `op_id` | UUID, PK | idempotency key |
| `device_id` | UUID, not null | |
| `device_seq` | bigint, not null | `UNIQUE (device_id, device_seq)` |
| `user_id` | FK `users.id`, not null | from token |
| `op_type` | `dispatch` / `receipt` | |
| `payload_hash` | text | SHA-256 of canonical JSON of the business payload; detects `op_id` reuse with different content |
| `transaction_id` | FK `borrow_transactions.id`, nullable | set when applied; for receipt, the target |
| `status` | `applied` / `conflict` / `rejected` / `resolved` | `resolved` = a human closed a conflict |
| `result_code` | text | e.g. `EQUIPMENT_NOT_AVAILABLE`, `TRANSACTION_ALREADY_RETURNED`, `RECEIPT_RACE_LOST`, `INVALID_INPUT`, `FORBIDDEN` |
| `occurred_at` | timestamptz | adjusted business time actually used (section 11) |
| `occurred_at_local`, `clock_offset_ms` | | as sent, for audit |
| `time_flag` | text null | `clamped_future`, `clamped_old`, `before_dispatch` |
| `received_at` | timestamptz default now | server clock |
| `attempt_count` | int | |
| `payload` | JSONB | stored only for non-applied ops (needed for review); applied ops keep it too for 48 h-gap forensics. No patient data exists in the payload by construction |
| `resolved_by`, `resolved_at`, `resolution`, `resolution_note` | | review outcome |

No new equipment state, no new transaction state: `BorrowTransaction.status` stays exactly `OPEN`/`CLOSED` (ADR-005), equipment stays at four states. `client_operations.status` is bookkeeping about a *request*, not a lifecycle state.

### 6.3 Idempotent create, concretely

For each op the sync service:

1. Looks up `op_id`.
   - Found `applied`/`resolved` with the same `payload_hash` and same `user_id` → return `duplicate` with the original `transaction_id` (HTTP-level success; client marks it acked).
   - Found with different `payload_hash` → `rejected`, `OP_ID_REUSED` (client bug; never silently accepted).
   - Found `conflict`/`rejected` → return the stored result without re-running (re-send is a no-op until a human acts).
   - Different `user_id` than the token → `rejected`, `OP_USER_MISMATCH`.
2. Not found → call `borrow_service.borrow(...)` or `return_equipment(...)` with a new optional `client_op` argument. Inside the service, **before its existing `db.commit()`**, the ledger row (`status=applied`) is inserted with `flush`, in the same session. Business write and ledger row therefore commit or roll back together, which is the same atomic-audit pattern the guardrails require. No new commit boundary is introduced.
3. For dispatch, the transaction is created with `id = op_id`. A concurrent duplicate insert of `op_id` loses on the PK, the session rolls back, and the loser re-reads the ledger and returns `duplicate`.
4. On a domain error (`EquipmentNotAvailableError`, `TransactionAlreadyReturnedError`, `ReceiptRaceLostError`, `InvalidInputError`, `EquipmentNotFoundError`, `TransactionNotFoundError`), the service has already rolled back its own work; the sync layer then writes the ledger row with `status=conflict` or `rejected` in a **separate small transaction**. That write has no lifecycle effect and cannot be confused with a lifecycle change.

A receipt whose target transaction is already `CLOSED` **by this same `op_id`** is a `duplicate` (step 1 catches it). If it is `CLOSED` by a different receipt, it is a genuine conflict (section 9.3), which is the existing `TRANSACTION_ALREADY_RETURNED` / `RECEIPT_RACE_LOST` distinction.

### 6.4 Other server changes

- `crud.transaction.create()` accepts an optional explicit `id` and optional business `borrowed_at`; `close()` accepts an optional business `returned_at`. Both default to current behaviour, so online paths are untouched.
- Audit: the existing `borrow` / `return` audit rows continue. Add the `op_id`, `device_id` and `device_seq` to the audit `after_data` for sync-originated rows (uses the existing redaction and bounded-field rules).
- `transaction_no` is still generated by the sequence at replay time. It is not shown as a key anywhere in the offline UI. After a restore, numbers issued in the lost window may be reissued to different transactions; this is harmless because the UUID is the identity (Owner: UUIDs suffice).
- Reports and the PR25B export API: they should expose `op_id`-independent UUIDs only; add a boolean `recorded_offline` (derived from `received_at - occurred_at` beyond a threshold, or from ledger presence) to the export later if the consumer wants it. Not required for v1.

### 6.5 Snapshot endpoint rules

Bounded page size, deterministic ordering by `(updated_at, id)` with a cursor (guardrail: no unbounded or nondeterministic reads). It returns only fields already allowed in operator-facing responses.

---

## 7. Client architecture

### 7.1 Storage: IndexedDB database `mep-offline` (versioned, with explicit upgrade functions)

| Store | Key | Content |
|---|---|---|
| `meta` | name | `device_id`, `device_seq` counter, schema version, last snapshot time, `clock_offset_ms` + measured-at |
| `outbox` | `op_id` | full envelope, `user_id`, `state` (`pending`, `sending`, `held`, `conflict`, `rejected`), attempt count, last error code, `blocked_by` |
| `journal` | `op_id` | envelope + server result + `acked_at`; entries older than 48 h from `acked_at` are purged |
| `ref_equipment`, `ref_wards`, `ref_departments`, `ref_locations`, `ref_open_tx` | id | snapshot data |

A small hand-written wrapper (or the `idb` library, pinned) is enough; no sync framework. The wrapper owns schema versioning so a PWA update can never open a newer-shaped database with older code.

### 7.2 Single write path

Every dispatch/receipt, online or offline, is: (1) validate form locally, (2) in one IndexedDB transaction assign `device_seq`, write to `outbox` (state `pending`), (3) show "Saved" immediately, (4) the sync worker (in the page, not the service worker) sends it. Online, the round trip finishes in under a second and the operator sees the real server result. Using one path means the offline path is exercised constantly, not only during outages.

### 7.3 Detecting "server unreachable"

Not `navigator.onLine` alone (it lies on captive Wi-Fi and with Cloudflare Access). The sync worker treats these as unreachable: network error, request timeout (8 s), HTTP 502/503/504 (nginx up, backend down), and a non-JSON/redirect response to an API call (Cloudflare Access login page, PR25C). It never treats 4xx domain errors as unreachable. A timeout is the dangerous case (the server may have committed), which is exactly why the `op_id` exists.

### 7.4 Sync loop

Triggers: app start, login, `online` event, visibility change, every 30 s while pending ops exist and the server was last unreachable (exponential backoff capped at 2 min), and after each new op. One loop per device (a Web Locks API lock `mep-sync` prevents two tabs sending the same queue). Steps: refresh token if needed (section 8.4) → send `verify` if due (section 10) → send pending ops of the **current user** in `device_seq` order in batches of 25 → apply per-op results → refresh snapshot.

---

## 8. Users, shared devices, authentication

### 8.1 Per-user queues

Every `outbox` and `journal` row carries `user_id`. The UI and the sync worker only ever show or send the logged-in user's rows. Another user logging in on the same device cannot see, send, edit or cancel them, and they are not attributed to the new user.

### 8.2 Logout

- Online logout with pending ops: the client first tries to flush; if it cannot, it warns: "You have N unsynced items. They stay on this device and will send when you next log in here." The operator can proceed.
- Logout never deletes pending ops or conflict items (losing them would lose real equipment movements).
- Logout **does** wipe the reference caches, the `mep-api-cache` Cache Storage, React Query cache, `mep-auth` localStorage (token and profile), and the service-worker-held API responses (section 12.2).
- Journal entries survive logout until 48 h from ack (needed for restore recovery), but remain private to their user.

### 8.3 Shared-device rules

- A user's unsynced ops on a shared device are only sent when that user logs in again on that device. Shown to that user at next login as a banner.
- If the user never returns, those ops are stranded. Mitigation: before logout on a shared device while online, the app blocks until the outbox is empty (it can be empty in seconds), so stranding only occurs if the server was down at logout. Residual risk in section 15; adoption by another user is a non-goal (Q5).
- The operator can choose "discard this unsynced item" for their own pending ops (confirmation required; written to the local journal as `discarded` so the action is explainable). Discard is local-only; nothing is sent to the server for an op the server never saw.

### 8.4 Token expiry while offline

- Offline use of the app does not require a valid access token: identity for local actions is the locally persisted session of the last login. The app does **not** log the user out because a refresh failed on a network error (change in `api.ts`, slice S1).
- A cold start with no persisted session cannot log in offline. There is no offline password check, by design (non-goal), so a device that was logged out cannot be used offline until it connects once.
- Replay needs a valid token: the sync worker calls `/auth/refresh` (httpOnly cookie, 7-day lifetime) first. If refresh returns 401 (cookie expired, user disabled, password changed), the worker stops, keeps the queue, and prompts for **re-authentication as the same user**. If a different user logs in, the queue stays locked to its original user (8.1).
- A user who is `must_change_password` (backend returns `PASSWORD_CHANGE_REQUIRED`) is sent to the change-password page first; ops remain queued.
- The server validates, at replay, that the token's user equals the op's `user_id` and still holds an Equipment Pool role. A user disabled or demoted while offline gets `rejected: FORBIDDEN` for each op, which goes to the review list for an Administrator (it is a real record of physical movements that someone must still reconcile).
- Cloudflare Access (PR25C) has its own session expiry, separate from the app login. The sync worker must recognise the Access login redirect as "unreachable (auth required)", keep the queue, and tell the operator to open the app in a normal tab to re-authenticate. Called out because it will happen on personal phones.

---

## 9. Replay order, validation, conflicts

### 9.1 Replay order

1. **Within one device: strictly by `device_seq`.** That order is the true causal order of what one operator did on one device.
2. **Across devices: no global order.** Each device sends its own queue when it can; the server applies whatever arrives, each op validated against the state at that moment.
3. **Dependencies on the same equipment.** If an op ends in `conflict`/`rejected`, later ops in the same queue that touch the same `equipment_id` (or target the same `transaction_id`) become `held` with `blocked_by = <op_id>`; the client does not send them. Unrelated ops continue. The server does not depend on this hold (its own lifecycle checks would also reject an inconsistent follow-up); the hold is to avoid compounding noise and to make the review list read as a story.
4. **Receipt before dispatch (cross-device or post-restore).** A receipt whose `transaction_id` is unknown to the server, and whose `occurred_at` is within the last 48 h, returns `retry_later: DEPENDENCY_MISSING` (no ledger conflict row). The client retries it on later rounds, because the dispatch may be on another device that has not synced yet or is about to be replayed after a restore. After 48 h it becomes `conflict: TRANSACTION_NOT_FOUND`.

### 9.2 Why not wall-clock across devices

Phone and tablet clocks are set by hand or by networks that drift by seconds to minutes, can be wrong by hours, and cannot establish happens-before between two people who never talked to the server. Example: device A (clock 2 min fast) receipts X at real 10:03 and logs 10:05; device B (clock 2 min slow) dispatches X at real 10:04 and logs 10:02. Sorting by timestamp would replay B before A and produce a wrong history that looks legitimate. The lifecycle state machine plus within-device sequence is a stronger and honest basis; cross-device oddities are surfaced to a human instead of guessed. Wall-clock is used only for the *recorded business time* of an event (section 11), never for ordering.

### 9.3 Validation: always through the normal services

For each op the sync layer calls the same service function an online request uses, with the same checks: equipment exists and is exactly `AVAILABLE_AT_POOL` for dispatch; ward exists; transaction exists and is `OPEN` for receipt; role gate; the unique-open-transaction index. Nothing is relaxed for offline-origin ops.

### 9.4 What a conflict looks like

| Situation at replay | Result code | Typical real-world cause | Suggested human action |
|---|---|---|---|
| Dispatch: equipment not `AVAILABLE_AT_POOL` (already `ISSUED_TO_WARD`) | `EQUIPMENT_NOT_AVAILABLE` | Two people dispatched the same item; or the offline cache was stale; or a restore replayed in a different order | Find the physical location; Dismiss the loser, or fix the other record through normal screens |
| Dispatch: equipment `UNAVAILABLE_DEFECTIVE` / `DECOMMISSIONED` | `EQUIPMENT_NOT_AVAILABLE` | Marked defective online while the device was offline | Decide whether the item was actually dispatched; Dismiss or re-dispatch after reactivation |
| Dispatch: `ward_id` no longer exists | `INVALID_INPUT` | Ward removed, or created only in the lost backup window | Administrator maps to the right ward; Apply now |
| Dispatch: equipment not found | `EQUIPMENT_NOT_FOUND` | Equipment created only in the lost backup window | Re-create master data, then Apply now |
| Receipt: transaction already `CLOSED` by a different receipt | `TRANSACTION_ALREADY_RETURNED` | Two people received the same item | Compare outcomes; if they differ (usable vs defective), the Administrator decides the truth and uses the normal defective/reactivate screens |
| Receipt: lost the close race | `RECEIPT_RACE_LOST` | Concurrent receipt on another device | Same as above |
| Receipt: transaction unknown after 48 h | `TRANSACTION_NOT_FOUND` | Dispatch never reached the server | Locate dispatch record; Dismiss or re-key |
| Any op: user disabled or role removed | `FORBIDDEN` | See section 8.4 | Administrator reviews and re-keys under their own identity if the movement was real |
| Any op: `op_id` reused with different content | `OP_ID_REUSED` | Client bug | Escalate; bug report |

A conflicting op is **not applied at all** (the service rolled back). It is a ledger row with the full payload, user, device and times, waiting for a human.

### 9.5 Idempotent duplicates are not conflicts

Re-sending an already applied `op_id` returns `duplicate` silently. The operator never sees a notice for it. This covers: response lost after commit, tab closed mid-send, timeout then retry, and the 48 h journal replay after a restore when the restored database happens to already contain the op.

### 9.6 Review list: who resolves, how, audit

- **Who:** `equipment_pool_staff` and `administrator` can view the list and resolve; `read_only` cannot see it (Q4: the Owner may prefer administrator-only for `FORBIDDEN` items; the draft proposes that the `FORBIDDEN` class is administrator-only because it concerns user permissions).
- **Where:** a "Needs review" page and a count badge in the header for those roles. The operator who originated an op also sees their own conflict items on the sync screen (read-only, with the reason) so they know their entry did not apply.
- **Resolution actions** (exactly two in v1):
  1. **Dismiss** with a reason code (`already_recorded`, `duplicate_physical_entry`, `not_real`, `handled_elsewhere`) and an optional note. Meaning: no further system change is needed. Ledger `status=resolved`, `resolution=dismissed`.
  2. **Apply now** (enabled only when the lifecycle precondition holds now). The server re-runs the *same payload* through `borrow_service` / `return_equipment` as a **new** operation with a fresh `op_id`, current time, attributed to the resolver, and links it to the original (`resolution=applied_as`, `resolution_note` with the new `op_id`). The original operator is preserved in the ledger and the audit entry. Business time for the new record is the resolution time, flagged as such, never back-dated silently.
- **Not allowed:** editing a conflicting payload, force-closing, force-opening, or changing equipment status from the review screen. Corrections use the existing, separately authorised screens (ward correction, mark defective, reactivate).
- **Audit:** every resolution writes one audit entry through the existing audit writer in the same session (action `sync_conflict_resolved`, entity `client_operation`, before/after: status, resolution, resolver, original user, device_id, original `op_id`, new `op_id`), atomic with the ledger update. Opening and listing are not audited (read paths), consistent with the rest of the system.
- **Nothing expires:** conflict items stay until a human resolves them. The admin dashboard shows the age of the oldest unresolved item.

---

## 10. 48-hour journal and restore recovery

### 10.1 Problem

Backups are hourly. If the server PC dies, the restored database misses up to about one hour of committed operations that the operators had already seen succeed. There is no standby. Clients are the only other copy.

### 10.2 Mechanism

1. Every operation, once the server acks it (`applied` or `duplicate`), stays in the device `journal` for 48 h from ack, with its full envelope. Operations that have not been acked stay in the `outbox` regardless of age.
2. `POST /sync/verify` sends the `op_id`s of journal entries (max 1000, newest first). The server answers with the ids it has no ledger row for.
3. Verify runs: after every reconnect following an unreachable period; at login; and at most every 15 min while online. So a restore is detected within 15 min even if no client ever saw an outage.
4. For each unknown id, the client moves the journal entry back into the `outbox` as `pending` with `replay_reason=restore_recovery`, preserving its original `device_seq`, and sends it through the normal path. The server's dedupe means ops the restored database did already contain return `duplicate`.
5. Replay of recovered ops follows section 9 unchanged. They are validated by the lifecycle services against the **restored** state, not trusted blindly.

### 10.3 What the recovery cannot and does not claim

- Only devices whose journal still holds the op can recover it. A device whose browser data was cleared, that was reset, or whose user never logs in again (shared device) loses that op's copy (residual risk, section 15).
- Admin-side changes inside the lost window (new equipment, wards, users, edits) are **not** recoverable by this mechanism. Ops that depend on them fail validation and go to review (`EQUIPMENT_NOT_FOUND`, `INVALID_INPUT`). The restore runbook (`docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md`) should add a step: "after restore, ask operators to open the app, then check Needs review; re-enter master data created in the last hour".
- Transaction numbers issued in the lost window may be issued again to different transactions. Harmless: UUID is identity.
- Ordering during recovery: ops come from several devices in arbitrary order; section 9.1 item 4 covers a receipt arriving before its dispatch. Remaining oddities (for example another operator re-dispatched the same item during the outage on a paper note) land in review.

### 10.4 Retention rationale for 48 hours

1 hour of backup gap plus detection delay, plus a weekend-sized buffer for rarely used devices opened once a day or two. Journal entries are small (a few hundred bytes). The window is a constant, reviewable by the Owner (Q8).

---

## 11. Clock skew and business time

- The server clock is the authority for `received_at` (`created_at`).
- Business time (`borrowed_at`, `returned_at`, which drive PR16 `business_date` and `shift`) should reflect when the operator acted, not when the replay arrived. Otherwise a night-shift dispatch replayed next morning is filed under the day shift.
- Every successful API response gives the client the server's `Date` header; the client stores `offset = serverTime - localTime` with its measurement time. Each op stores `occurred_at_local` and the offset in force at that moment.
- Server computes `occurred_at = occurred_at_local + clock_offset_ms`, then applies guards:
  - If later than `received_at + 2 min` → clamp to `received_at`, `time_flag=clamped_future`.
  - If older than `received_at - 7 days` → clamp to `received_at`, `time_flag=clamped_old`.
  - A receipt earlier than its dispatch `borrowed_at` → clamp to the dispatch time, `time_flag=before_dispatch`.
- Flagged ops are applied normally (the operator did act) but appear in a "time adjusted" filter on the review list and in the admin status page. They never block.
- The device clock is never used to *order* anything (9.2). A device whose clock was wrong and never contacted the server since being fixed produces a bad offset; the guards above bound the damage to the flagged window.
- Display: the pending badge shows the local entry time; the confirmed record later shows the adjusted time.

---

## 12. Security and privacy

### 12.1 Data at rest on personal phones

- What is stored: UUIDs, BCM Codes, equipment names, ward names, `op` payloads (ward, round, notes), the logged-in user's profile and token (already persisted today in `localStorage`). No patient data exists in the system, and the Owner accepted the equipment-data-only risk profile (Decision Log 2026-10-13).
- Notes are free text. The offline form shows the same hint as the online form: do not enter patient names or HN. A length cap (the existing `notes` bound) applies.
- Minimum data: the snapshot contains only fields already in operator-facing responses (section 3.2), no Item No, no Asset Number, no user list.
- No app-level encryption in v1: a key cannot be derived without a password check that offline mode deliberately lacks. Protection relies on the OS screen lock and the browser sandbox. Recommend (operational, not code) that personal phones used for this app keep a screen lock; this is a hospital IT policy item for the Owner (Q9).
- The access token in `localStorage` is existing behaviour. Moving to memory-only is a separate hardening item; this design records it and does not depend on it.

### 12.2 Wipe on logout

Logout clears: `localStorage['mep-auth']`, React Query cache, all `ref_*` stores, Cache Storage entries for API calls (and the `mep-api-cache` rule is removed from `vite.config.ts` in favour of the IndexedDB snapshot, so API responses are not stored by the service worker at all), and it keeps only the user's own `outbox`/`journal` rows (section 8.2). A "Remove all data from this device" button (visible when the outbox is empty, or after explicit double confirmation when not) clears everything including `device_id`.

### 12.3 Server-side

- The sync endpoints use the existing JWT auth, role gates, `PASSWORD_CHANGE_REQUIRED` enforcement, and rate limits; batch size and payload size are capped; `device_id`/`op_id` are validated as UUIDs; unknown fields are rejected.
- A client cannot choose the acting user: the server uses the token's user and rejects a mismatch (`OP_USER_MISMATCH`).
- A client cannot set equipment status or transaction status; there is no such field in the envelope.
- Ledger payloads are redacted by the existing central redaction before any logging. Log lines carry `op_id`, `device_id`, `device_seq`, result code, never payload bodies.

---

## 13. App shell availability, service worker, updates

### 13.1 Loading the app when the server is down

- The app must be **installed** (Add to Home Screen / Install app). Installed PWAs have the most reliable storage retention (browsers may evict storage of ordinary tabs on iOS Safari after inactivity). The first-run screen on mobile prompts installation.
- Workbox precaches `js/css/html/svg/png/ico`; `index.html` is served from the precache for navigation requests. PR25E adds `navigateFallbackDenylist: [/^\/api\//]` so API paths are never answered with the HTML shell, and verifies the fallback with a test.
- Request `navigator.storage.persist()` at first login to ask the browser not to evict IndexedDB.
- A department PC browser tab works the same if opened once while the server is up. The Owner can pin the app as an installed PWA on department PCs (Chrome/Edge "Install").

### 13.2 What cannot work

- First-ever visit to the app while the server is down (nothing to load). Operators must install the app while the server is up.
- Login while offline (section 8.4).
- Screens that need live server data (reports, history, admin).

### 13.3 Update strategy

Current: `registerType: "autoUpdate"` activates a new service worker and may reload the page at any time. Offline-capable behaviour needs control over that:

- Switch to **prompt-style updates** (`registerType: "prompt"`) with a small in-app notice "New version ready — reload when convenient". The shell never reloads while a dispatch/receipt form is open or an op is in the `sending` state.
- A mandatory-update flag in the `sync/operations` response (`min_client_version`) lets the server refuse stale clients with a stable code `CLIENT_TOO_OLD` when the envelope contract changes. The queue is untouched; the operator is told to reload. This is the only way a stale offline client could otherwise send an envelope the server no longer understands.
- IndexedDB schema upgrades run before the sync loop starts and are tested from every previous version (slice S2 onwards). The outbox is forward-migrated, never dropped.
- Envelope changes are additive and versioned (`envelope_version`) so a new server accepts the previous version for at least one release.
- `nginx` keeps `/sw.js` as `no-cache` (already so) so update checks are not delayed.

---

## 14. UX (brief)

| Element | Behaviour |
|---|---|
| Connection indicator | Header chip: "Online", "Server unreachable — working offline", or "Sign-in needed to sync". |
| Pending badge | Count of unsynced items for the current user; amber when any is older than 1 h, red when older than 24 h (policy: nothing sits unsynced for days unnoticed). |
| Entry confirmation | After Confirm: "Saved on this device — not yet sent" (offline) or "Recorded" (server ack). Never says "Recorded" for an unsent op. |
| Stale data | "Equipment list as of 09:42" on pickers; amber after 12 h. |
| Sync screen | List of this user's pending, held, sent-today, and conflict items, each with entry time, equipment BCM Code, ward, and state. "Retry now" button. Local discard for own pending items. |
| Conflict notice | Toast and persistent badge when one of the operator's own ops conflicts: "This entry could not be applied: <plain-language reason>. Pool staff will review." Text from stable codes, not server free text. |
| Review page | Table with reason, equipment, user, device, entry time, adjusted time flag; actions Dismiss / Apply now with confirmation. |
| Language | Thai UI strings consistent with the existing app; codes remain English for support. |

---

## 15. Failure modes

| # | Failure | Effect | Handling |
|---|---|---|---|
| 1 | Server down for hours | No sync | Ops queue locally; badges show age; replay on recovery |
| 2 | Timeout after server committed | Client thinks it failed | Re-send; ledger returns `duplicate` |
| 3 | Same op sent twice concurrently (two tabs, or retry overlap) | Possible double insert | `op_id` PK and Web Lock; loser returns `duplicate` |
| 4 | Two devices dispatch the same equipment | Second loses | `EQUIPMENT_NOT_AVAILABLE` → review |
| 5 | Stale cache says AVAILABLE | Offline dispatch of an item that is out | Conflict at replay; UI shows cache age; local pending blocks same-device double entry |
| 6 | Two receipts of the same transaction | Second loses | `TRANSACTION_ALREADY_RETURNED` / `RECEIPT_RACE_LOST` → review |
| 7 | Refresh cookie expired during a long outage | Cannot sync | Queue kept; re-login as same user; no data loss |
| 8 | Different user logs in on a shared device | Must not send first user's ops | Queue is per-user and locked |
| 9 | First user never returns to the shared device | Their unsynced ops stranded | Forced flush before online logout; red badge after 24 h reaches that user next login; residual risk accepted for v1 (Q5) |
| 10 | Server restored from backup (up to ~1 h lost) | Missing committed ops | Journal verify and replay; unrecoverable only if no device still holds the op |
| 11 | Restore plus admin edits lost in the window | Replayed ops reference missing master data | `EQUIPMENT_NOT_FOUND` / `INVALID_INPUT` → review; runbook step to re-enter master data |
| 12 | Receipt arrives before its dispatch (other device or restore ordering) | Transient `TRANSACTION_NOT_FOUND` | `retry_later` up to 48 h, then conflict |
| 13 | Device clock wrong | Wrong business time | Offset correction and clamps; flagged |
| 14 | Browser data cleared / device reset | Local queue and journal lost | Unsynced ops lost (warn in training; paper fallback). New `device_id`, no collisions |
| 15 | iOS or browser evicts IndexedDB | Same as 14 | Installed PWA, `storage.persist()`, queue age badges to encourage syncing |
| 16 | PWA update with new schema while ops pending | Stuck or lost ops | Prompt-style updates, versioned IDB upgrades, `envelope_version`, `CLIENT_TOO_OLD` (queue preserved) |
| 17 | Cloudflare Access session expired | API returns login HTML or redirect | Detected as "unreachable (auth required)"; queue kept; re-auth prompt |
| 18 | Queue grows without bound | Storage exhaustion | Hard cap 500 pending ops per device; at cap, new offline entries are refused with "use paper and enter later" |
| 19 | Server disk full or DB error at replay | 5xx | Treated as unreachable; backoff; no ledger write; retry later |
| 20 | Malicious or buggy client sends forged `user_id` | Wrong attribution | Server ignores client user, uses token; mismatch rejected |
| 21 | Operator edits an already queued item | Divergence | Queued items are immutable; "discard" and re-enter instead |
| 22 | Replay of a very old op (> 7 days) | Time anomaly | Applied with `clamped_old`; flagged |
| 23 | Server host down and also the Drive backup stale | Beyond recovery of this feature | Out of scope; PR25A monitoring |
| 24 | Two users on one shared device dispatch the same equipment offline | Possible duplicate pending entry | The local double-entry guard is per device, not per user, so a shared tablet cannot hold two pending dispatches of the same item; the server would reject the second anyway |

---

## 16. Observability

- **Server structured logs** (PR15A context): one line per op with `op_id`, `device_id`, `device_seq`, `user_id`, `op_type`, `result`, `code`, `latency_ms`, `lag_s` (`received_at - occurred_at`). `correlation_id` for sync requests is the first `op_id` of the batch.
- **Ledger as the source of truth** for counts; `GET /sync/status` returns: ops by status/result in the last 48 h, number and age of unresolved conflicts, number of `duplicate` results (health signal for flaky links), number of `time_flag` ops, `verify` calls that returned unknown ids (**a spike means a restore happened or a device re-sent after losing server state**).
- **Admin dashboard tile:** unresolved conflicts count, oldest age; red when older than 24 h.
- **Client diagnostics panel** (in the sync screen): device id, schema version, queue depth by state, oldest pending age, last successful sync, last error code, snapshot age. A "copy diagnostics" button copies counts and codes only (no payload bodies) for support.
- **Alerts** are the Owner's existing means (no new alerting stack). The runbook gets a daily checklist line: "open Needs review and the sync status".

---

## 17. Test strategy

Backend (pytest; PostgreSQL-marked tests for concurrency evidence, SQLite not claimed as PostgreSQL evidence):

1. Idempotent dispatch: same `op_id` twice sequentially and concurrently (two sessions) → one transaction, one audit row, `duplicate` on the second; ledger row atomic with the business write (kill the commit and assert neither exists).
2. Idempotent receipt: same `op_id` → `duplicate`; different `op_id` on a closed transaction → `TRANSACTION_ALREADY_RETURNED` conflict row; concurrent receipts → exactly one wins, loser `RECEIPT_RACE_LOST`.
3. `op_id` reuse with different payload → `OP_ID_REUSED`; token user ≠ envelope user → `OP_USER_MISMATCH`; role removed → `FORBIDDEN`.
4. Dispatch conflict matrix (section 9.4): each cause produces the right code, no equipment or transaction mutation, and a ledger row with the payload.
5. The sync endpoint cannot change equipment status or transaction status in any way other than through the services (assert the envelope schema rejects extras; assert `RECEIPT_OUTCOME_TO_STATUS` is the only mapping used).
6. `verify`: unknown/known id sets; bounded size; restore simulation (apply ops, delete ledger and business rows to model a backup, replay journal → state rebuilt, duplicates dedupe).
7. Dependency handling: receipt before dispatch → `retry_later`; after 48 h → conflict.
8. Business-time guards: future, old, before-dispatch clamps; PR16 `business_date`/`shift` computed from adjusted time.
9. Resolution: dismiss, apply-now preconditions, audit entry atomic with ledger update, role gates, `read_only` denied.
10. Migration: additive upgrade/downgrade tests for `client_operations`; existing `POST /borrow` and `/return` tests unchanged and still green.
11. Snapshot: pagination determinism, bounded sizes, no Item No/Asset Number/user fields (contract test).

Frontend (Vitest + fake-indexeddb):

12. Outbox write is atomic with `device_seq`; per-user isolation (user B never sees/sends user A's rows); logout wipe keeps outbox/journal, clears refs and tokens.
13. Sync loop: ordering by `device_seq`, `held` dependency logic, backoff, Web Lock single-flight, unreachable detection (network error, timeout, 502/503/504, HTML/redirect response), no logout on refresh network error, re-auth prompt on refresh 401.
14. Journal: 48 h purge, verify then re-queue of unknown ids, duplicate result handling.
15. IDB upgrade tests from each prior version; `CLIENT_TOO_OLD` keeps queue.
16. UI: badges, stale labels, saved-vs-recorded wording, conflict notice, review page actions.

End-to-end / manual evidence (reported honestly as such, not as CI):

17. Playwright or manual drill: stop the backend container, perform dispatch and receipts on two browser profiles, restart, verify results; drill a restore-from-backup using the runbook plus journal replay; test on a real Android phone and iPhone with the installed PWA.
18. Evidence classes follow `docs/PROJECT_WORKFLOW.md`: local drills are labelled local rehearsal, not UAT.

---

## 18. Open questions for the Owner

(Q1 has a Thai note; the Thai summary in section 0 covers the rest)

| # | Question | Draft recommendation | Why it matters |
|---|---|---|---|
| **Q1** | **Offline QR scanning.** QR resolves Item No on the server, and ADR-004 keeps Item No out of operator responses. Choose: **(a)** offline identification by BCM Code search only (v1); **(b)** ship a one-way hashed Item No → UUID table to devices (needs an ADR-004 amendment; hashes of short codes are guessable, so this weakens the boundary); **(c)** let the operator scan offline, store the raw scanned text on the op, and resolve it on the server at replay (no confirmation on screen, wrong-item risk). | **(a)** for v1; decide (b) only after seeing real outage frequency | Biggest functional gap versus online. ออฟไลน์สแกน QR ได้หรือไม่ ขัด ADR-004 |
| Q2 | Is "UUIDs only, `transaction_no` hidden in the offline UI" acceptable, and are printed or remembered ticket numbers used anywhere today? | Yes | Numbers may change after a restore |
| Q3 | Which dispatch fields stay available offline? Draft keeps all online fields. `phone_number` is typed free text that would sit on phones. | Keep, with a notes/phone hint; or drop `phone_number` offline | Data at rest on personal phones |
| Q4 | Who resolves conflicts? Draft: Equipment Pool staff and Administrator; `FORBIDDEN` class Administrator only. | As drafted | Governance, accountability |
| Q5 | Shared devices: if a user leaves with unsynced ops and never returns, is stranding acceptable, or may a different pool staff/admin "adopt" them (recorded under their own name with the original user kept in the ledger)? | Accept stranding in v1; no adoption | Attribution vs data loss |
| Q6 | Offline hard cap: 500 pending ops per device and 7-day max business-time backdating. Reasonable? | Yes | Storage and report integrity |
| Q7 | Is a device-level red badge after 24 h unsynced enough, or should long-pending items notify an Administrator once the server is back? | Badge only (v1) | Operational follow-up |
| Q8 | Journal window 48 h: confirm, or lengthen (for example 72 h) to cover weekends? | 48 h as decided | Recovery coverage vs stored data |
| Q9 | Personal phones: is requiring an OS screen lock (and optionally a "remove data" button procedure when a phone is replaced) acceptable as the only at-rest control? App-level PIN/encryption is a non-goal in v1. | Yes | Hospital IT policy |
| Q10 | After a restore, should a runbook step mark that "restore happened" and show operators a notice ("some entries are being re-sent")? | Optional; verify already detects within 15 min | Operator reassurance |
| Q11 | Is "offline receipt for a transaction not in this device's cache" (dispatched elsewhere) acceptable as "record on paper and key later"? Alternative is receipt-by-equipment (server finds the open transaction), which risks closing the wrong dispatch (re-dispatched meanwhile). | Receipt by `transaction_id` only | Safety versus convenience |

---

## 19. Explicit non-goals

- No new equipment state, no new transaction state, no cleaning state, no change to the four identifiers (guardrails).
- No offline administrative or master-data operations; no offline reports.
- No automatic conflict resolution, no last-writer-wins, no timestamp-based arbitration, no CRDTs.
- No ward-to-ward transfer tracking, no patient data, no HN, no MEMS/N Smart call or dependency.
- No offline login or password check; no app-level encryption or PIN in v1.
- No multi-device real-time sync or peer-to-peer sync between devices.
- No Item No or Asset Number on devices (pending Q1).
- No background-sync-while-closed (not reliable on iOS); sync runs when the app is open.
- No standby server, no change to PR25A backup design or to the PR25B export API, no Cloudflare work (PR25C) beyond handling its login redirect.
- No Shift Session or Standby Snapshot work (confirmed future work, not this PR); no change to PR16 derivation logic beyond feeding it the adjusted business time.
- No change to the existing `POST /borrow` / `POST /return/{id}` contracts.
- This PR changes no application code and no Roadmap or Decision Log text.

---

## 20. Slice plan for PR25E

Each slice is one small, independently reviewable PR with its own tests. Order matters. S1 and S2 can run in parallel (different files); S3 depends on S1; backend slices B1 to B3 are strictly ordered.

| Slice | Content | Depends on | Proves (acceptance tests) |
|---|---|---|---|
| **B1** | `client_operations` migration and model; `crud.transaction.create/close` accept explicit `id` and business time; no endpoint yet | none | Migration upgrade/downgrade; existing tests green; explicit-id create works |
| **B2** | `POST /sync/operations` for dispatch and receipt: envelope schema, ledger-in-service atomicity, idempotency, conflict/rejected rows, error codes, role/user checks, time guards; audit enrichment | B1 | Test items 1 to 5, 7, 8 |
| **B3** | `POST /sync/verify`, `GET /sync/snapshot` (bounded cursor), `GET /sync/status` | B2 | Test items 6, 11 |
| **B4** | Conflict list and resolve endpoints (dismiss, apply-now), audit on resolve, role gates | B2 | Test item 9 |
| **S1** | Frontend: auth/offline hardening only — stop logging out on refresh network errors; unreachable detection helper; replace `mep-api-cache` rule; `navigateFallbackDenylist`; logout wipe including Cache Storage and React Query | none | Tests item 13 (no-logout-on-network-error), wipe tests; shell loads offline in a manual drill |
| **S2** | Frontend: IndexedDB layer (`meta`, `outbox`, `journal`, refs), versioned upgrades, per-user isolation, `device_id`/`device_seq`, hard cap; no UI | none | Test items 12, 15 |
| **S3** | Frontend: sync worker (ordering, hold logic, backoff, Web Lock, token refresh and re-auth, verify and journal replay, clock offset) against B2/B3 | B2, B3, S1, S2 | Test items 13, 14 |
| **S4** | Frontend: dispatch and receipt forms moved onto the outbox path (online and offline), reference snapshot cache, BCM offline search, local double-entry guard, pending badge, connection chip, stale labels, sync screen | S3 | Test item 16; manual two-profile drill |
| **S5** | Frontend: Needs review page and header badge, conflict notices, discard-own-item | B4, S4 | Test item 16; role visibility |
| **S6** | PWA update strategy: `registerType: "prompt"`, update notice, `CLIENT_TOO_OLD` handling, install prompt, `storage.persist()` | S4 | Update-during-pending-ops test |
| **D1** | Docs and runbook updates: restore runbook additions (Needs review, master-data re-entry), operator quick guide (Thai), `docs/api/` pages for sync endpoints, `ROADMAP`/`DECISION_LOG`/knowledge updates as the workflow requires | all | Docs review |
| **E1** | Evidence drill (no code): outage drill, restore-and-replay drill, real phones; recorded with the correct evidence class | all | Owner-visible report |

The Owner decides after B2 and S4 whether to continue to the later slices or run a pilot with the first four.
