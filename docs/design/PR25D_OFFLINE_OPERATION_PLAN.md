# PR25D — Offline Operation Design

**Purpose:** Design (no code) for letting Equipment Pool staff keep dispatching and receiving equipment while the department server is unreachable, and for syncing safely afterwards.
**Status:** Owner questions answered 2026-10-13 (section 18). **The Owner's answers authorize starting PR25E per the slice plan (section 20) once this document is merged.** Merging this PR is the trigger; no further approval step is needed for the slices listed, but any change to a decision in section 18 returns to the Owner.
**Approval:** the Owner decisions in section 18 are the recorded approval of this design (2026-10-13). `DECISION_LOG.md` and `ROADMAP.md` are updated by the PR25E docs slice (D1), not by this PR.
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

**หมายเหตุ export (PR25B):** ผู้บริโภค API (Nsmart Realtime) ต้องอ่านตาม cursor (`seq`) เสมอ ห้ามเรียงตามเวลา เพราะรายการที่ส่งทีหลังจากโหมดออฟไลน์อาจมีเวลาเหตุการณ์ย้อนหลัง และระบบจะสร้าง export event หนึ่งรายการต่อหนึ่งรายการที่บันทึกสำเร็จเท่านั้น

**คำตอบของ Owner (2026-10-13) ที่ปรับเข้าแบบแล้ว (ดูหัวข้อ 18)**
- ออฟไลน์ค้นหาด้วย **BCM Code เท่านั้น** สแกน QR ใช้เฉพาะตอนออนไลน์ (ADR-004 ไม่เปลี่ยน)
- **เบอร์โทร (ตัดสินใจแล้ว):** เพิ่มฟิลด์เบอร์โทรใน master data ของวอร์ด/แผนก (ปัจจุบันยังไม่มีในโค้ด) แล้วให้ฟอร์มจ่ายเครื่องกรอก `phone_number` อัตโนมัติจากวอร์ดที่เลือก ทั้งออนไลน์และออฟไลน์ (จากข้อมูลวอร์ดที่แคชไว้) และยังแก้ไขได้เหมือนเดิม ทำเป็น slice เล็กแยก (B0 + S0) ก่อนฟอร์มออฟไลน์ มีประโยชน์ตอนออนไลน์ด้วย
- ผู้ตัดสิน conflict คือ Equipment Pool staff และ Administrator
- **เครื่องใช้ร่วมกัน (เปลี่ยนแบบ):** ผู้ใช้อื่นที่เป็น Pool staff/Administrator สามารถ **"รับช่วง" (adopt)** รายการค้างของคนที่ไม่กลับมาแล้วส่งต่อได้ ต้องกดยืนยันชัดเจน ต้องออนไลน์และล็อกอินสด และมี audit ทั้งผู้ทำเดิมและผู้รับช่วง ผู้ทำเดิมยังคงเป็นผู้บันทึกของรายการ
- ขีดจำกัด 500 รายการ/เครื่อง, ย้อนเวลาไม่เกิน 7 วัน, journal 48 ชม., ใช้ screen lock ของเครื่อง: ตกลง
- **รับคืนอ้างด้วย transaction_id เท่านั้น** และเพิ่มการป้องกัน 2 กรณี: (ก) สลับเครื่องในวอร์ด (รับคืนแล้วจ่ายซ้ำทันที) (ข) ออฟไลน์นานหลายเครื่องคีย์ไม่ตรงกัน: ระบบสร้าง **Timeline** ของเครื่องมือชิ้นนั้นตามเวลาที่ปรับนาฬิกาแล้ว ให้คนตรวจดู และมีปุ่ม "ใช้ทั้งลำดับ" ที่ผ่านการตรวจแล้วเท่านั้น ไม่ apply เองโดยลำพังใน v1 (Owner ยืนยัน: **ยังไม่เปิด SYNC_AUTO_SEQUENCE** จะตัดสินใหม่หลัง pilot จากสถิติที่ระบบเก็บตั้งแต่วันแรก ได้แก่ จำนวน conflict ข้ามเครื่องต่อเครื่องมือ, กี่รายการที่ลำดับตามเวลาที่ปรับแล้วถูกต้องตาม lifecycle, กี่รายการที่คนตัดสินตามลำดับนั้น/ต่างจากนั้น, และการกระจายของนาฬิกาคลาดเคลื่อน) พร้อมแจ้งเตือนเมื่อข้อมูลในเครื่องเก่ากว่า **4 ชั่วโมง** (Owner ยืนยันแล้ว) และให้รายการเหล่านั้นถูกจัดลำดับความสำคัญในการตรวจ
- **คำตอบของ Owner อนุญาตให้เริ่ม PR25E ตามแผน slice ได้ทันทีเมื่อเอกสารนี้ merge**

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
| Equipment responses deliberately **exclude Item No**; QR resolution is server-side `POST /equipment/resolve-qr` | `schemas/equipment.py`; ADR-002/004 | Offline QR scan cannot work without shipping Item No to devices (Owner decision D1: offline is BCM-only). |
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
| Dispatch (`routine_round` or `on_demand`) | Yes | Same fields as online: equipment, ward, dispatch type, routine round, optional department/location ids, `phone_number` and notes. `phone_number` is auto-filled from the selected ward and stays editable, exactly as online (section 3.4). |
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

Not cached: Item No, Asset Number, user lists, user phone numbers (the ward and department phones in section 3.4 are cached), audit log, reports, history. Item No is excluded by ADR-002/004 (see D1 for QR).

Snapshot refresh: after login, then every 15 min while online, plus on every successful reconnect, via a new bounded paginated endpoint (section 6.5). Staleness is displayed, never hidden. The device also applies its **own pending operations** on top of the snapshot locally (a device with a pending dispatch of X shows X as "dispatched (not yet synced)"), which blocks the same operator from double-dispatching X offline.

### 3.4 `phone_number` auto-fill from ward master data (Owner decision D2, decided)

**Today (code check):** `phone_number` is an optional free-text column on `borrow_transactions` (`String(20)`), accepted by `BorrowRequest` and typed by hand in `BorrowPage.tsx` (`useState("")`, no prefill). `Ward` has only `code`, `name`, `department_id`; `Department` has only `code`, `name`. No ward or department phone exists in master data and nothing fills the field. The `phone` fields in `schemas/master_data.py` belong to users.

**Decided:** add a phone to ward and department master data, and auto-fill the dispatch form's `phone_number` from the selected ward, online and offline, still editable as today. This is useful online too, so it ships as its own small slice (B0 backend, S0 frontend, section 20) before the offline forms slice, which then relies on it.

Design:
- **Data:** nullable `phone` (`String(20)`, same cap as `borrow_transactions.phone_number`) on `wards` and on `departments`, by an additive Alembic revision (nullable, no backfill, upgrade/downgrade tested). Ward phone is the primary source. Department phone is a fallback: if the selected ward has no phone, use its department's phone. (The Owner said "ward/department"; ward-then-department fallback is this design's reading and is cheap to simplify to ward-only.)
- **API:** `WardOut`, `WardCreate`, `DepartmentOut`, `DepartmentCreate` gain optional `phone`. Admin-only create/update follows the existing master-data gates. Per the guardrails no update/delete endpoints are invented solely for this; if ward/department update endpoints do not exist today, the admin form sets the phone at create time and the slice states honestly that editing an existing ward's phone needs the master-data update path to exist (check in B0; if absent, raise it as a flagged prerequisite instead of adding a generic endpoint silently).
- **Dispatch form:** on ward selection, `phone_number` is set from the ward (or department fallback) when the field has not been edited by the operator; later ward changes re-fill only if the operator has not typed their own value. The field stays editable and optional. The submitted value is whatever is in the field, so server behaviour (`BorrowRequest`) is unchanged.
- **Offline:** the reference snapshot (`ref_wards`, `ref_departments`) carries the phones; the same prefill runs from the cache. The staleness label on the snapshot applies; a changed ward phone reaches devices at the next snapshot refresh.
- **Privacy:** these are department/ward contact numbers, not patient or personal data. They sit in the snapshot on devices, which section 12 already treats as equipment-and-organisation data under the OS-screen-lock control.
- **Not in scope:** no per-user phone use, no validation beyond the existing length cap, no change to `borrow_transactions`.

### 3.3 Equipment identification offline

Offline identification is **manual BCM Code search against the cached list** (ADR-003 semantics: BCM is the only manual-search identifier; matching uses the canonical persisted form, so the snapshot must carry the canonical form of each BCM Code and the client must match against it using the same canonicalisation rule as the server; PR25E confirms the exact rule in the BCM search code). QR scanning is **online only** (Owner decision D1); ADR-004 is unchanged and no Item No data ever reaches a device.

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
| `GET /api/v1/sync/conflicts` | Paginated review list, filter by status. | `equipment_pool_staff`, `administrator` (D3) |
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

One additive Alembic revision (the next free revision after `0025_export_events`, whatever number that is when B1 is written; additive-first, tested for upgrade and downgrade, per guardrails).

| Column | Type | Notes |
|---|---|---|
| `op_id` | UUID, PK | idempotency key |
| `device_id` | UUID, not null | |
| `device_seq` | bigint, not null | `UNIQUE (device_id, device_seq)` |
| `user_id` | FK `users.id`, not null | original operator (token user, or `original_user_id` for an adopted op) |
| `submitted_by_user_id`, `adopted_at` | FK `users.id` null / timestamptz null | adopter, see section 8.3 |
| `stale_context` | bool | device snapshot older than the staleness threshold when keyed (section 9.8) |
| `op_type` | `dispatch` / `receipt` | |
| `payload_hash` | text | SHA-256 of canonical JSON of the business payload; detects `op_id` reuse with different content |
| `transaction_id` | FK `borrow_transactions.id`, nullable | set when applied; for receipt, the target |
| `status` | `pending` (retry_later only, **non-terminal**) / `applied` / `conflict` / `rejected` / `resolved` | Terminal statuses are `applied`, `conflict`, `rejected`, `resolved`. `resolved` = a human closed a conflict. A `pending` row means "seen, not yet executed" and is always re-executed. |
| `result_code` | text | e.g. `EQUIPMENT_NOT_AVAILABLE`, `TRANSACTION_ALREADY_RETURNED`, `RECEIPT_RACE_LOST`, `INVALID_INPUT`, `FORBIDDEN` |
| `occurred_at` | timestamptz | adjusted business time actually used (section 11) |
| `occurred_at_local`, `clock_offset_ms` | | as sent, for audit |
| `first_seen_at` | timestamptz | server time the op was first received; also stored for `retry_later` (ledger row status `pending`) so the 48 h cutoff is server-measured |
| `time_flag` | text null | `clamped_future`, `clamped_old`, `before_dispatch`, `before_last_receipt` |
| `received_at` | timestamptz default now | server clock |
| `attempt_count` | int | |
| `payload` | JSONB | stored only for non-applied ops (needed for review); applied ops keep it too for 48 h-gap forensics. No patient data exists in the payload by construction |
| `resolved_by`, `resolved_at`, `resolution`, `resolution_note` | | review outcome |

No new equipment state, no new transaction state: `BorrowTransaction.status` stays exactly `OPEN`/`CLOSED` (ADR-005), equipment stays at four states. `client_operations.status` is bookkeeping about a *request*, not a lifecycle state.

### 6.3 Idempotent create, concretely

For each op the sync service:

1. Checks the token user, then looks up `op_id`. Order matters:
   - Found, and the token user is neither its `user_id` nor its `submitted_by_user_id` (adoption, section 8.3) → `rejected`, `OP_USER_MISMATCH`, **without** revealing the stored result or `transaction_id` (this check precedes every other check so another user replaying an `op_id` learns nothing).
   - Found `applied`/`resolved` with the same `payload_hash` → return `duplicate` with the original `transaction_id` (client marks it acked).
   - Found with a different `payload_hash` → `rejected`, `OP_ID_REUSED` (client bug; never silently accepted).
   - Found `pending` → **not a duplicate**: re-execute the op (step 2 variant below). A `pending` row never produces `duplicate`.
   - Found `conflict`/`rejected` → return the stored result without re-running (re-send is a no-op until a human acts).
2. Not found, or found `pending` → call `borrow_service.borrow(...)` or `return_equipment(...)` with a new optional `client_op` argument. Inside the service, **before its existing `db.commit()`**, the ledger row is written with `flush` in the same session: for a not-found op, an `INSERT` with `status=applied`; for a `pending` op, an `UPDATE ... SET status='applied', transaction_id=..., occurred_at=... WHERE op_id=:id AND status='pending'`, decided by affected-row count (the same conditional-update shape as the PR8A receipt guard). If the UPDATE affects 0 rows, another request already moved the row: the session rolls back, the ledger is re-read and the stored terminal result is returned (`duplicate` if `applied`/`resolved`). Concurrent retries of the same `pending` op therefore cannot both win. Business write and ledger row commit or roll back together (the atomic-audit pattern the guardrails require). No new commit boundary is introduced.
   - **Write order inside the service (PR25B).** `borrow()` and `return_equipment()` now call `export_service.record_event(...)` immediately before `db.commit()`; it takes the export counter's row lock, which is what keeps the export cursor in commit order, so it **must remain the last write**. The ledger INSERT/UPDATE therefore goes **before** `record_event`: business writes, audit, ledger row, then `record_event`, then the existing commit.
   - **Export guarantee.** Each applied op produces exactly one export event, in the same transaction as its ledger row. Duplicate sends return before the service is called and emit nothing. `retry_later`, `conflict` and `rejected` paths change no business state and emit nothing. Adopted ops and resolver-applied ops (Apply now, Apply sequence) emit one event each, through the normal services, never directly.
   - A `retry_later` outcome (section 9.1 item 4) writes the `pending` row by `INSERT ... ON CONFLICT DO NOTHING` (or leaves the existing `pending` row, keeping its original `first_seen_at`) and bumps `attempt_count`; it commits no business change.
3. For dispatch, the transaction is created with `id = op_id`. Two concurrent sends of the same op can collide on the transaction PK, on the ledger PK, or on `idx_tx_one_active_borrow`. `borrow()` currently converts **every** `IntegrityError` at flush into `EQUIPMENT_NOT_AVAILABLE` or `INVALID_INPUT` (the `except IntegrityError` block in `borrow_service.py`), so a duplicate-send collision looks like a domain conflict. It must not be trusted as one until step 4 has checked the ledger.
4. On **any** domain error (`EquipmentNotAvailableError`, `TransactionAlreadyReturnedError`, `ReceiptRaceLostError`, `InvalidInputError`, `EquipmentNotFoundError`, `TransactionNotFoundError`) the sync layer does not assume the service rolled back (errors raised before the flush, such as equipment not found or not available, never reach the service's own `rollback()`). It: (a) explicitly `rollback()`s the session; (b) re-reads the ledger by `op_id`; if a row in a **terminal** status exists (`applied`/`resolved`, the winner's row, or an already stored `conflict`/`rejected`) it returns the stored result per step 1's rules (`duplicate` only for `applied`/`resolved`); a `pending` row is not terminal; (c) otherwise (no row, or only a `pending` row) it writes the `conflict`/`rejected` outcome, via `INSERT ... ON CONFLICT DO NOTHING` for a missing row or `UPDATE ... WHERE op_id=:id AND status='pending'` for a `pending` one, in a **separate small transaction**, and re-reads by `op_id`, returning whatever row is stored (so a racing winner always beats a loser's conflict row). That write has no lifecycle effect.

A receipt whose target transaction is already `CLOSED` **by this same `op_id`** is a `duplicate` (step 1 catches it). If it is `CLOSED` by a different receipt, it is a genuine conflict (section 9.3), which is the existing `TRANSACTION_ALREADY_RETURNED` / `RECEIPT_RACE_LOST` distinction.

### 6.4 Other server changes

- `crud.transaction.create()` accepts an optional explicit `id` and optional business `borrowed_at`; `close()` accepts an optional business `returned_at`. Both default to current behaviour, so online paths are untouched.
- Audit: the existing `borrow` / `return` audit rows continue. Add the `op_id`, `device_id` and `device_seq` to the audit `after_data` for sync-originated rows (uses the existing redaction and bounded-field rules).
- `transaction_no` is still generated by the sequence at replay time. It is not shown as a key anywhere in the offline UI. After a restore, numbers issued in the lost window may be reissued to different transactions; this is harmless because the UUID is the identity (Owner: UUIDs suffice).
- Staleness (section 9.8): the envelope carries `snapshot_age_s`; the server sets `stale_context`.
- **Export consumers and replayed time.** The export event time of a replayed op is its (possibly backdated) business time, while export order follows the commit counter (`seq`). A consumer such as Nsmart Realtime must therefore page strictly by cursor (`seq`), never by event time, and must not assume event times are non-decreasing. A replayed op can legitimately appear with an event time hours or days older than events already delivered. (`docs/api/export.md` already requires cursor paging; the PR25E docs slice D1 adds a note there that offline-recorded events can carry older event times, and that choosing a start point by `at=` is for starting positions only.)
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

Every `outbox` and `journal` row carries `user_id`. The UI and the sync worker only ever show or send the logged-in user's rows. Another user logging in on the same device cannot see, edit or cancel them, and they are never silently sent or attributed to the new user. The only path by which another user can send them is the explicit, audited **adoption** action in section 8.3.

### 8.2 Logout

- Online logout with pending ops: the client first tries to flush; if it cannot, it warns: "You have N unsynced items. They stay on this device and will send when you next log in here, or when another pool staff member adopts them." The operator can proceed.
- Logout never deletes pending ops or conflict items (losing them would lose real equipment movements).
- Logout **does** wipe the reference caches, the `mep-api-cache` Cache Storage, React Query cache, `mep-auth` localStorage (token and profile), and the service-worker-held API responses (section 12.2).
- Journal entries survive logout until 48 h from ack (needed for restore recovery), but remain private to their user.

### 8.3 Shared-device rules and adoption (Owner decision D4)

- By default a user's unsynced ops are sent only when that user logs in again on that device.
- Stranding is reduced two ways: the app blocks online logout until the user's outbox is empty (normally seconds), and other pool staff can **adopt** whatever is left so the process continues without the original operator.
- The operator can still "discard" their own pending ops (confirmation required; written to the local journal as `discarded`). Discard is local-only.

**Adoption design**

| Aspect | Rule |
|---|---|
| Who may adopt | `equipment_pool_staff` or `administrator`. Never `read_only`. |
| Preconditions | Adopter is logged in on that device with a **fresh online login** (server-verified token issued within the last 15 minutes, else the app asks for the password again) and the server is reachable. Never possible offline, never automatic. |
| Explicit action | The sync screen shows "N items left by other users on this device". The adopter opens "Review items from other users"; only here are other users' rows displayed (BCM Code, ward, entry time, operator name, type). The adopter selects items and confirms: "You are sending N items entered by <names>. They stay recorded under the original operator; your name is recorded as the sender." No pre-checked boxes, no adoption on login. |
| Recorded operator | **The original operator.** `borrower_user_id` / `received_by_user_id`, report operator names (PR17) and PR16 counts keep the person who physically did the work, which is the business fact. The adopter is recorded as sender in the ledger and audit. Rejected alternative: attribute to the adopter, which would falsely show the adopter handled the equipment. |
| Envelope | Adds `original_user_id` and `adopt: true`. The server accepts a token user different from `original_user_id` **only** when `adopt` is true, the token user holds an Equipment Pool role, and `original_user_id` is an existing user who holds one. Otherwise `OP_USER_MISMATCH`. |
| Ledger | `client_operations.user_id` stays the original operator. New columns `submitted_by_user_id` (adopter; equals `user_id` for normal ops) and `adopted_at`. |
| Audit and actor | **The audit row's actor (`audit_logs.user_id`) is always the user whose token submitted the operation** (the adopter here, the resolver in section 9.6/9.7), never the original operator, consistent with ADR-0001's separation of actor from subject. The original operator is the **recorded operator**: `borrower_user_id` / `received_by_user_id` on the transaction, and `original_user_id` in the audit `after_data`. One `sync_adopt` audit entry per adopted batch (action `sync_adopt`, entity `client_operation`): actor = adopter; `after_data` lists original operator(s), `device_id`, op ids, count, fresh-login time. The normal `borrow`/`return` audit rows for each adopted op have actor = adopter and carry `adopted: true`, `original_user_id`, `submitted_by_user_id` in `after_data`. Both names are visible in the audit log. |
| Service change required | Today `borrow()` / `return_equipment()` use one user for three roles: recorded operator, audit actor, and equipment status-history `changed_by_user_id`. They gain a separate `actor_user_id` argument (defaulting to the operator, so every online call and existing test is unchanged). Audit `user_id` and status-history `changed_by_user_id` use the actor; `borrower_user_id` / `received_by_user_id` use the recorded operator. This is slice **B2** (the refactor with its no-behaviour-change tests), used by B2c (adoption) and B4/B4b (resolution). |
| Trust boundary | The server cannot prove the original operator created the op (offline devices hold no credentials to sign with). The control is: trusted pool staff, explicit action, full audit, and every op still passes the normal lifecycle services. |
| Replay safety | Idempotency is unchanged (`op_id`). Section 6.3 step 1 allows replay only by the original user or the recorded `submitted_by_user_id`; anyone else gets `OP_USER_MISMATCH` with no data. |
| Restore recovery | The adopter can run "Check other users' recent entries (48 h)", which sends `verify` for the other users' journal and re-queues unknown ones for adoption. |
| Conflicts on adopted ops | Appear in the review list with both names, and on the original operator's sync screen at next login ("sent by <adopter>"). |

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
4. **Receipt before dispatch (post-restore only).** Device B only holds a receipt for a transaction id it learned from the server snapshot or created itself; it never sees device A's unsynced offline dispatch UUID. So an unknown `transaction_id` arises in practice only after a restore, when the dispatch was lost with the backup and will be replayed from a journal. A receipt with an unknown `transaction_id`, whose `first_seen_at` (server time of the first receipt of that `op_id`, never client time) is within the last 48 h, returns `retry_later: DEPENDENCY_MISSING` (no ledger conflict row). The client retries it on later rounds, because the dispatch is about to be replayed from a journal. After 48 h it becomes `conflict: TRANSACTION_NOT_FOUND`.

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

- **Who:** `equipment_pool_staff` and `administrator` can view the list and resolve; `read_only` cannot see it (Owner decision D3; the `FORBIDDEN` class stays administrator-only because it concerns user permissions).
- **Where:** a "Needs review" page and a count badge in the header for those roles. The operator who originated an op also sees their own conflict items on the sync screen (read-only, with the reason) so they know their entry did not apply.
- **Resolution actions** (exactly two in v1):
  1. **Dismiss** with a reason code (`already_recorded`, `duplicate_physical_entry`, `not_real`, `handled_elsewhere`) and an optional note. Meaning: no further system change is needed. Ledger `status=resolved`, `resolution=dismissed`.
  2. **Apply now** (enabled only when the lifecycle precondition holds now). The server re-runs the *same payload* through `borrow_service` / `return_equipment` as a **new** operation with a fresh `op_id`, current time, attributed to the resolver, and links it to the original (`resolution=applied_as`, `resolution_note` with the new `op_id`). The original operator is preserved in the ledger and the audit entry. Business time for the new record is the resolution time, flagged as such, never back-dated silently.
- **Not allowed:** editing a conflicting payload, force-closing, force-opening, or changing equipment status from the review screen. Corrections use the existing, separately authorised screens (ward correction, mark defective, reactivate).
- **Audit:** every resolution writes one audit entry through the existing audit writer in the same session (action `sync_conflict_resolved`, entity `client_operation`, before/after: status, resolution, resolver, original user, device_id, original `op_id`, new `op_id`), atomic with the ledger update. Opening and listing are not audited (read paths), consistent with the rest of the system.
- **Nothing expires:** conflict items stay until a human resolves them. The admin dashboard shows the age of the oldest unresolved item.

---

### 9.7 Same-equipment collisions: timeline, in-ward swaps, long offline periods (Owner decision D7)

Receipt stays by `transaction_id` only (D7); the scenarios the Owner raised are handled by what the review does with it.

**Scenario (a), in-ward swap.** Device A receives X (transaction T1) and immediately re-dispatches X to the same ward (T2) while offline, because the pool is short. Meanwhile device B (online or offline) also acts on T1, for example another person receives X, or sees T1 open in a stale cache and dispatches/receives again. Typical results at replay: B's receipt of T1 loses (`TRANSACTION_ALREADY_RETURNED` / `RECEIPT_RACE_LOST`), or A's receipt loses and A's follow-up dispatch of X is held behind it.

**Scenario (b), long offline.** Two devices both offline for hours key receipts and dispatches on the same equipment with no snapshot updates in between, so each is internally consistent but they disagree with each other.

**Mechanism**

1. **Per-equipment timeline.** For any conflict on equipment X the server builds a timeline of: (i) committed transactions for X in the last 7 days (their `borrowed_at`/`returned_at`, ward, outcome, operator, device if offline-originated), and (ii) all non-applied ledger ops for X (conflict, rejected, pending). Events are ordered by **corrected event time** (`occurred_at`, section 11). Within one device, `device_seq` always overrides time. Each event shows an uncertainty band, `± (30 s + 1 min per hour since that device's clock offset was measured)`. Events whose bands overlap are labelled "order uncertain". Each event also shows `stale_context` and any `time_flag`.
2. **Review screen** shows this timeline above the Dismiss / Apply now actions, with the plain-language reading: "T1 was closed usable by Somchai at 10:05 (device A). Receipt from device B at 10:06 has the same outcome: likely the same physical receipt entered twice." For receipts the screen also states whether the conflicting outcome equals the committed one (same outcome: likely duplicate, mismatch usable/defective: needs a decision).
3. **Held dependents are released by Dismiss.** If a receipt conflicts as `already_recorded` with the same outcome, dismissing it releases the held follow-up dispatch of X on that device (the Owner's swap case), which is then sent and validated normally. If the outcome differs, the resolver decides first (and uses the normal defective/reactivate screens for any correction).
4. **"Apply sequence" action.** When several non-applied ops for X exist, the server dry-runs them against the current committed state in corrected-time order (with `device_seq` constraints) using the lifecycle rules, without writing. If the whole sequence is lifecycle-valid the screen offers one confirm button. **Decision: not all-or-nothing.** On confirm, each op runs as its **own** transaction through the normal services (each with its own ledger row, audit entries and lifecycle checks), in corrected-time order, and the run **stops at the first failure**, leaving that op and the rest in review with the failure shown. Reason: the dry run is advisory and the state can change between the dry run and each step (another device may sync); one big transaction would span several service commits the services do not allow (they own their commit boundaries; guardrail against moving them casually), and a partial prefix is still a set of true, individually valid events, never a half-applied one. The audit actor and recorded operator follow section 8.3 (actor = the resolver whose token submitted it; recorded operator = the original operator). If the dry run finds any op would fail, no button appears and the resolver handles ops individually. It never rewrites already-committed history; if committed records themselves are out of true order, correction uses the existing screens.

**Is there a strictly safe automatic path? Decision: not in v1.**

An automatic path would have to apply ops in corrected-time order without a human. Candidate safe conditions: all ops from one equipment pending together, the full sequence lifecycle-valid, no op `stale_context`, every device's offset measured within 15 minutes before keying, no overlapping uncertainty bands, at most 4 ops, and no unresolved conflict on X. Even then:
- a valid sequence is not necessarily the true one: with the physical item in one place, two lifecycle-valid orders can exist (receive then dispatch versus dispatch then receive of a different cycle) and only clocks distinguish them, while clocks are exactly what cannot be trusted across devices (9.2);
- the Owner's rule "never silently resolve" would be weakened to "silently resolve when conditions look safe", and the error would land in PR16 shift counts and operator attribution without anyone noticing.
So v1 ships human-confirmed sequencing only (point 4). **Owner decision D8 (2026-10-13): `SYNC_AUTO_SEQUENCE` is not enabled in v1 and will be re-decided after the pilot based on the statistics in section 16.1.** The setting is specified here only so the evidence can be judged against its exact conditions; no code for auto-applying a sequence is written in PR25E. If the Owner later enables it, it needs the conditions above, an audit entry per auto-applied sequence (action `sync_auto_sequence`, listing every op id and the evidence), a visible "auto-applied" badge in the review list and on operators' sync screens, and its own implementation PR.

### 9.8 Staleness warning (N = 4 hours)

- The device tracks `snapshot_age` (time since the last successful snapshot) and `offline_for` (time since the server was last reachable).
- If either exceeds **N = 4 hours** (proposed: it is shorter than a 12-hour shift and about the gap between routine rounds at 06:00, 11:00, 15:00 and 21:00; the constant is configurable and reviewable at pilot), then before the operator keys the first dispatch or receipt in the session a full-screen warning appears: "This device has not synced for N hours. Equipment status shown may be out of date. Entries may need review." The operator must acknowledge to continue; the banner stays on the entry form afterwards.
- Every op keyed in that state carries `snapshot_age_s` in its envelope; the server sets `stale_context = true` when it exceeds N hours (the server, not the client, decides, and the threshold is server-side).
- `stale_context` ops are shown with a badge, sorted first in the review list, and counted separately in `GET /sync/status`. They are still applied through the normal path when there is no conflict; the flag changes review priority and timeline labelling only. It never blocks entry (work must continue).

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

1 hour of backup gap plus detection delay, plus a weekend-sized buffer for rarely used devices opened once a day or two. Journal entries are small (a few hundred bytes). The window is a constant, confirmed by the Owner (D5).

---

## 11. Clock skew and business time

- The server clock is the authority for `received_at` (`created_at`).
- Business time (`borrowed_at`, `returned_at`, which drive PR16 `business_date` and `shift`) should reflect when the operator acted, not when the replay arrived. Otherwise a night-shift dispatch replayed next morning is filed under the day shift.
- Every successful API response gives the client the server's `Date` header; the client stores `offset = serverTime - localTime` with its measurement time. Each op stores `occurred_at_local` and the offset in force at that moment.
- Server computes `occurred_at = occurred_at_local + clock_offset_ms`, then applies guards:
  - If later than `received_at + 2 min` → clamp to `received_at`, `time_flag=clamped_future`.
  - If older than `received_at - 7 days` → clamp to `received_at`, `time_flag=clamped_old`.
  - A receipt earlier than its dispatch `borrowed_at` → clamp to the dispatch time, `time_flag=before_dispatch`.
  - A dispatch earlier than the same equipment's latest `returned_at` → clamp to that `returned_at`, `time_flag=before_last_receipt`. Without this, a backdated dispatch (up to 7 days) overlaps the previous usage interval and distorts PR16 `business_date`/`shift` counts.
- Flagged ops are applied normally (the operator did act) but appear in a "time adjusted" filter on the review list and in the admin status page. They never block.
- The device clock is never used to *order* anything (9.2). A device whose clock was wrong and never contacted the server since being fixed produces a bad offset; the guards above bound the damage to the flagged window.
- Display: the pending badge shows the local entry time; the confirmed record later shows the adjusted time.

---

## 12. Security and privacy

### 12.1 Data at rest on personal phones

- What is stored: UUIDs, BCM Codes, equipment names, ward names, `op` payloads (ward, round, notes), the logged-in user's profile and token (already persisted today in `localStorage`). No patient data exists in the system, and the Owner accepted the equipment-data-only risk profile (Decision Log 2026-10-13).
- Notes are free text. The offline form shows the same hint as the online form: do not enter patient names or HN. A length cap (the existing `notes` bound) applies.
- Minimum data: the snapshot contains only fields already in operator-facing responses (section 3.2), no Item No, no Asset Number, no user list.
- No app-level encryption in v1: a key cannot be derived without a password check that offline mode deliberately lacks. Protection relies on the OS screen lock and the browser sandbox. Recommend (operational, not code) that personal phones used for this app keep a screen lock; this is a hospital IT policy item for the Owner (D6).
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
| 9 | First user never returns to the shared device | Their unsynced ops stranded until adopted | Forced flush before online logout; another pool staff or administrator can adopt the remaining items (section 8.3) |
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
| 24 | Two users on one shared device dispatch the same equipment offline | Possible duplicate pending entry | The local double-entry guard is per device, not per user: it blocks with a generic "this item already has a pending entry on this device" message and shows nothing of the other user's rows (8.1 holds); the server would reject the second anyway |

---

## 16. Observability

- **Server structured logs** (PR15A context): one line per op with `op_id`, `device_id`, `device_seq`, `user_id`, `op_type`, `result`, `code`, `latency_ms`, `lag_s` (`received_at - occurred_at`). `correlation_id` for sync requests is the first `op_id` of the batch.
- **Ledger as the source of truth** for counts; `GET /sync/status` returns: ops by status/result in the last 48 h, number and age of unresolved conflicts, number of `duplicate` results (health signal for flaky links), number of `time_flag` ops, `verify` calls that returned unknown ids (**a spike means a restore happened or a device re-sent after losing server state**).
- **Admin dashboard tile:** unresolved conflicts count, oldest age; red when older than 24 h.
- **Client diagnostics panel** (in the sync screen): device id, schema version, queue depth by state, oldest pending age, last successful sync, last error code, snapshot age. A "copy diagnostics" button copies counts and codes only (no payload bodies) for support.
- **Alerts** are the Owner's existing means (no new alerting stack). The runbook gets a daily checklist line: "open Needs review and the sync status".

### 16.1 Pilot statistics for the auto-sequencing decision (D8)

Collected from the first day of use, aggregates only, no payload bodies, no patient data (none exists). Stored as columns on `client_operations` (written when the conflict is detected and when it is resolved) so no extra table is needed; exposed by an administrator-only `GET /sync/stats?from=&to=` that returns counts and histograms, plus a CSV export for the pilot review.

| Statistic | Definition | Captured from |
|---|---|---|
| Cross-device conflicts per equipment | Number of conflict groups (all non-applied ops on one equipment within a 24 h window that involve at least two `device_id`s, or one device against a committed transaction from another), and a per-equipment distribution (how many equipment had 1, 2, 3+ groups) | `device_id`, `transaction_id`, equipment id at detection; new column `collision_group_id` |
| Lifecycle-valid corrected-time order | Of those groups, how many had a dry-run in corrected-time order (section 9.7 point 4) that was lifecycle-valid at detection, split by: all ops fresh vs any `stale_context`, overlapping uncertainty bands vs separated | Dry-run result stored at detection: `order_valid_at_detection`, `proposed_sequence` (op ids in order), `bands_overlap`, `stale_context` |
| Resolved in that same order vs differently | For groups with a valid proposal: resolved exactly as proposed (same ops applied in the same order, rest dismissed as proposed) vs resolved differently (different order, an op the proposal would apply was dismissed, or an op it would have kept was applied) vs resolved by dismissal only | Compared at resolution time; stored `resolution_matches_proposal` (`same` / `different` / `dismissed_only`) and resolver id |
| Agreement rate | `same` / (`same` + `different`) among valid-proposal groups, overall and for the subset that meets the specified auto conditions (the number that matters for D8) | Derived |
| Clock-skew distribution | Histogram of `clock_offset_ms` and of `offset_age_s` (age of the offset measurement at keying; new column), and of `received_at - occurred_at` lag, per device class if known; share of ops with `time_flag`; share of op pairs with overlapping uncertainty bands | Ledger columns `clock_offset_ms`, `offset_age_s`, `time_flag`, `occurred_at` |
| Volume context | Total ops, ops recorded offline (lag over 2 min), conflicts per 1000 ops, resolution time (median, 90th percentile) | Ledger |

Suggested reading, for the Owner to adjust: the decision is credible only with enough groups (the pilot report states the count; a few dozen groups or fewer is not evidence), and an auto path is worth considering only if the agreement rate among groups meeting the auto conditions is very high and the cases where it was `different` are understood. The Owner sets the thresholds; PR25E only guarantees the data exists.

Implementation placement: the extra columns (`collision_group_id`, `order_valid_at_detection`, `proposed_sequence`, `bands_overlap`, `offset_age_s`, `resolution_matches_proposal`) are part of the B1 migration; detection and storage of the proposal are in B4b (it owns the dry-run); `GET /sync/stats` is in B3 for the volume and skew parts and extended in B4b for the collision parts.

---

## 17. Test strategy

Backend (pytest; PostgreSQL-marked tests for concurrency evidence, SQLite not claimed as PostgreSQL evidence):

1. Idempotent dispatch: same `op_id` twice sequentially and concurrently (two sessions) → one transaction, one audit row, and the concurrent loser gets `duplicate`, **never** `EQUIPMENT_NOT_AVAILABLE`/`INVALID_INPUT` and never a conflict row (cover PK clash, `idx_tx_one_active_borrow` clash, and errors raised before flush); another user replaying the `op_id` gets `OP_USER_MISMATCH` with no `transaction_id` leaked; ledger row atomic with the business write (kill the commit and assert neither exists).
2. Idempotent receipt: same `op_id` → `duplicate`; different `op_id` on a closed transaction → `TRANSACTION_ALREADY_RETURNED` conflict row; concurrent receipts → exactly one wins, loser `RECEIPT_RACE_LOST`.
3. `op_id` reuse with different payload → `OP_ID_REUSED`; token user ≠ envelope user → `OP_USER_MISMATCH`; role removed → `FORBIDDEN`.
4. Dispatch conflict matrix (section 9.4): each cause produces the right code, no equipment or transaction mutation, and a ledger row with the payload.
5. The sync endpoint cannot change equipment status or transaction status in any way other than through the services (assert the envelope schema rejects extras; assert `RECEIPT_OUTCOME_TO_STATUS` is the only mapping used).
6. `verify`: unknown/known id sets; bounded size; restore simulation (apply ops, delete ledger and business rows to model a backup, replay journal → state rebuilt, duplicates dedupe).
7. Dependency handling: receipt before dispatch → `retry_later`; after 48 h → conflict.
8. Business-time guards: future, old, before-dispatch clamps, and a backdated dispatch predating the equipment's latest `returned_at` is clamped (`before_last_receipt`) so usage intervals never overlap; PR16 `business_date`/`shift` computed from adjusted time.
9. Resolution: dismiss, apply-now preconditions, audit entry atomic with ledger update, role gates, `read_only` denied.
10. Migration: additive upgrade/downgrade tests for `client_operations`; existing `POST /borrow` and `/return` tests unchanged and still green.
11a. In-ward swap: A receives T1 then re-dispatches X (T2) offline; B's receipt of T1 arrives first and wins. A's receipt conflicts, A's dispatch is held; the timeline shows both; Dismiss as same-outcome duplicate releases A's dispatch, which applies as T2; a different-outcome case (usable vs defective) requires an explicit resolver choice and does not release the dispatch until resolved.
11b. Long-offline cross-device: devices A and B both offline for more than N hours key receipts and dispatches on the same equipment from stale caches; replay in either arrival order produces no history rewrite, correct conflict rows, a timeline ordered by corrected time with `device_seq` overriding time within a device, "order uncertain" for overlapping bands, and a skewed device clock does not change which op wins (arrival and lifecycle decide).
11c. Apply sequence: a lifecycle-valid sequence runs each op as its own transaction in corrected-time order, one ledger row and audit entries per op, stopping at the first failure (inject a failure on op 2 of 3: op 1 stays applied and audited, ops 2 and 3 stay in review with the reason); an invalid dry run offers no action; already-committed rows are never modified; audit actor is the resolver and `borrower_user_id`/`received_by_user_id` is the original operator for every applied op.
11h. Pilot statistics: two devices conflicting on one equipment produce one `collision_group_id`; the stored proposal and `order_valid_at_detection` match the dry-run; resolving via Apply sequence records `same`, resolving in another order or dismissing a proposed op records `different`, dismissal only records `dismissed_only`; `GET /sync/stats` counts, agreement rate and skew histograms are correct on a seeded dataset and are administrator-only; no payload bodies appear in the output.
11i. Export events: a duplicate or retried op, including `pending` → `applied`, yields exactly one `export_events` row; `conflict`, `rejected`, `retry_later` and `duplicate` results yield none; an adopted op and an Apply now / Apply sequence op each yield exactly one event; the ledger row and the export event commit or roll back together (inject a failure after the ledger write: neither exists); `record_event` is still the last write before commit (assert order in the service test); a replayed backdated op appears at a later `seq` with an older event time, and cursor paging by `seq` delivers it.
11g. Pending ledger rows: receipt → `retry_later` (ledger `pending`, `first_seen_at` kept) → the dispatch replays → the receipt retried is applied **exactly once** (the `pending` row is updated to `applied`, never duplicated, never returned as `duplicate`); two concurrent retries of the same `pending` op → one applies, the other returns the stored `applied` result as `duplicate`; a `pending` op past 48 h from `first_seen_at` becomes `conflict: TRANSACTION_NOT_FOUND` (via the conditional UPDATE); a `pending` row is never returned as `duplicate`.
11d. Staleness: `snapshot_age_s` above N sets `stale_context`; flagged ops sort first and are counted; ops are still applied normally when valid; the flag never blocks.
11e. Adoption: adopt requires `adopt: true`, a pool role and a fresh login; original operator stays `borrower_user_id`/`received_by_user_id` while the audit rows' actor (`audit_logs.user_id`) and the equipment status-history `changed_by_user_id` are the adopter, and `original_user_id` is in `after_data`; the online (non-adopt) path is unchanged with actor = operator; `submitted_by_user_id`, `sync_adopt` audit and `adopted` markers are written atomically; a non-adopt token mismatch gets `OP_USER_MISMATCH`; a `read_only` user is denied; adopting an already-applied op returns `duplicate`.
11f. Phone: ward phone and department fallback prefill the field online and from the offline cache; the operator can overwrite it and the typed value is what is sent; a ward with no phone and no department phone leaves it empty; the snapshot contract includes ward/department phone and still no Item No/Asset Number/user fields.
11. Snapshot: pagination determinism, bounded sizes, no Item No/Asset Number/user fields (contract test).

Frontend (Vitest + fake-indexeddb):

12. Outbox write is atomic with `device_seq`; per-user isolation (user B never sees/sends user A's rows); logout wipe keeps outbox/journal, clears refs and tokens.
13. Sync loop: ordering by `device_seq`, `held` dependency logic, backoff, Web Lock single-flight, unreachable detection (network error, timeout, 502/503/504, HTML/redirect response), no logout on refresh network error, re-auth prompt on refresh 401.
14. Journal: 48 h purge, verify then re-queue of unknown ids, duplicate result handling.
15. IDB upgrade tests from each prior version; `CLIENT_TOO_OLD` keeps queue.
16. UI: staleness warning requires acknowledgement and persists as a banner; adopt flow shows other users' rows only inside the adopt screen with explicit confirmation and no pre-checked boxes; review timeline rendering; badges, stale labels, saved-vs-recorded wording, conflict notice, review page actions.

End-to-end / manual evidence (reported honestly as such, not as CI):

17. Playwright or manual drill (include an in-ward swap drill and a two-device long-offline drill): stop the backend container, perform dispatch and receipts on two browser profiles, restart, verify results; drill a restore-from-backup using the runbook plus journal replay; test on a real Android phone and iPhone with the installed PWA.
18. Evidence classes follow `docs/PROJECT_WORKFLOW.md`: local drills are labelled local rehearsal, not UAT.

---

## 18. Owner decisions (2026-10-13)

The Owner answered the open questions of the earlier draft. This section is the record. **These answers authorize starting PR25E per the slice plan in section 20 once this document is merged.**

| # | Decision | Where applied |
|---|---|---|
| D1 | Offline QR: agreed. v1 offline identification is BCM Code search only; QR scanning is online only; ADR-004 unchanged. | 3.3 |
| D2 | `phone_number`: **decided yes.** Add a phone to ward and department master data; the dispatch form auto-fills `phone_number` from the selected ward (department fallback), online and offline from the cached snapshot; still editable. Code check had shown no such field exists today. Own small slice (B0, S0) before the offline forms slice; useful online too. | 3.4, 20 |
| D3 | Conflicts are resolved by Equipment Pool staff and Administrator (`FORBIDDEN` class: Administrator only). | 9.6 |
| D4 | Shared devices: **changed.** Another authenticated Equipment Pool staff or Administrator may adopt and send a stranded user's pending operations; explicit, confirmed, online, fresh login, original operator stays the recorded operator, adopter recorded as sender, fully audited. | 8.3, 6.2, 6.3 |
| D5 | Limits agreed: 500 pending ops per device, 7-day maximum back-dating, 48-hour journal. | 10, 11, 15 |
| D6 | OS screen lock is the only at-rest control on personal phones; no app-level PIN or encryption in v1. | 12.1 |
| D8 | `SYNC_AUTO_SEQUENCE` is **not enabled in v1**. It will be re-decided after the pilot from collected statistics; PR25E collects them from day one. No auto-resolution of any kind ships. | 9.7, 16.1 |
| D7 | Receipt by `transaction_id` only, agreed, with added protection for in-ward swaps and long-offline cross-device cases: per-equipment timeline, human-confirmed "Apply sequence", no automatic resolution in v1, 4-hour staleness warning and `stale_context` review priority. | 9.7, 9.8 |

Items the Owner did not raise keep the draft defaults and are treated as accepted for implementation, revisitable at pilot:

| # | Default | Note |
|---|---|---|
| X1 | UUID-only identity; `transaction_no` hidden in the offline UI and possibly reissued after a restore. | Owner input: UUIDs suffice. |
| X2 | Unsynced items older than 24 hours show a red badge only; no notification to an Administrator. | Revisit at pilot. |
| X3 | No dedicated "a restore happened" notice; `verify` detects within 15 minutes. | Optional runbook wording. |
| X4 | Staleness threshold N = 4 hours: **confirmed by the Owner.** Remains a configurable constant. | 9.8 |

**Still open for the Owner:** nothing blocks PR25E. One decision is scheduled: whether to enable automatic sequencing, after the pilot (D8, section 16.1).

---

## 19. Explicit non-goals

- No new equipment state, no new transaction state, no cleaning state, no change to the four identifiers (guardrails).
- No offline administrative or master-data operations; no offline reports.
- No automatic conflict resolution, no last-writer-wins, no timestamp-based arbitration, no CRDTs.
- No ward-to-ward transfer tracking, no patient data, no HN, no MEMS/N Smart call or dependency.
- No offline login or password check; no app-level encryption or PIN in v1.
- No multi-device real-time sync or peer-to-peer sync between devices.
- No Item No or Asset Number on devices (D1).
- No background-sync-while-closed (not reliable on iOS); sync runs when the app is open.
- No automatic conflict resolution of any kind in v1; `SYNC_AUTO_SEQUENCE` is not implemented and not enabled (D8), only its evidence is collected.
- No other new master-data fields beyond the ward/department phone in section 3.4.
- No standby server, no change to PR25A backup design or to the PR25B export API, no Cloudflare work (PR25C) beyond handling its login redirect.
- No Shift Session or Standby Snapshot work (confirmed future work, not this PR); no change to PR16 derivation logic beyond feeding it the adjusted business time.
- No change to the existing `POST /borrow` / `POST /return/{id}` contracts.
- This PR changes no application code and no Roadmap or Decision Log text.

---

## 20. Slice plan for PR25E

Each slice is one small, independently reviewable PR with its own tests. Order matters. S1 and S2 can run in parallel (different files); S3 depends on S1; backend slices B1 to B3 are strictly ordered. B0 and S0 (phone auto-fill) are independent of the offline work, ship first, and may run in parallel with B1 and S1/S2.

| Slice | Content | Depends on | Proves (acceptance tests) |
|---|---|---|---|
| **B0** | Ward and department `phone` columns (additive nullable migration), master-data schemas/API/tests; flags if update path is missing | none | Migration upgrade/downgrade; schema round-trip; role gates; existing master-data tests green |
| **S0** | Admin master-data form fields for phone; dispatch form auto-fills `phone_number` from the selected ward (department fallback), editable; works online with no offline code | B0 | Vitest prefill/edit/overwrite cases; manual check; shippable on its own |
| **B1** | `client_operations` migration and model (including the section 16.1 statistics columns); `crud.transaction.create/close` accept explicit `id` and business time; no endpoint yet | none | Migration upgrade/downgrade; existing tests green; explicit-id create works |
| **B2** | `POST /sync/operations` for dispatch and receipt: envelope schema, ledger-in-service atomicity, idempotency including `pending` re-execution (ledger write placed before `record_event`), conflict/rejected rows, error codes, role/user checks; audit enrichment; `actor_user_id` split in `borrow()`/`return_equipment()` (default = operator, no online behaviour change) | B1 | Test items 1 to 5, 7, 11g, 11i |
| **B2b** | Business-time handling: clock-offset adjustment, future/old/before-dispatch/before-last-receipt clamps, `time_flag`, PR16 integration | B2 | Test item 8 |
| **B2c** | Adoption support: `original_user_id`/`adopt` envelope fields, `submitted_by_user_id`/`adopted_at` columns, `sync_adopt` audit (using B2's `actor_user_id`), stale_context flag | B2 | Test items 11d, 11e |
| **B3** | `POST /sync/verify`, `GET /sync/snapshot` (bounded cursor), `GET /sync/status`, `GET /sync/stats` (volume and clock-skew statistics, section 16.1) | B2 | Test items 6, 11, 11h |
| **B4** | Conflict list and resolve endpoints (dismiss, apply-now), audit on resolve, role gates; held-dependent release | B2 | Test item 9 |
| **B4b** | Per-equipment timeline endpoint and dry-run "Apply sequence"; collision-group detection and proposal storage; `resolution_matches_proposal` at resolution; collision part of `GET /sync/stats` | B4, B2b | Test items 11a to 11c, 11h |
| **S1** | Frontend: auth/offline hardening only — stop logging out on refresh network errors; unreachable detection helper; `navigateFallbackDenylist`; logout wipe including Cache Storage and React Query | none | Tests item 13 (no-logout-on-network-error), wipe tests; shell loads offline in a manual drill |
| **S2** | Frontend: IndexedDB layer (`meta`, `outbox`, `journal`, refs), versioned upgrades, per-user isolation, `device_id`/`device_seq`, hard cap; no UI | none | Test items 12, 15 |
| **S3** | Frontend: sync worker (ordering, hold logic, backoff, Web Lock, token refresh and re-auth, verify and journal replay, clock offset) against B2/B3 | B2, B3, S1, S2 | Test items 13, 14 |
| **S4** | Frontend: dispatch and receipt forms moved onto the outbox path (online and offline), reusing S0's prefill against the cached ward snapshot; the `mep-api-cache` runtime rule is removed in this same PR that introduces the IndexedDB snapshot, so there is no window without a reference cache; reference snapshot cache, BCM offline search, local double-entry guard, pending badge, connection chip, stale labels, sync screen | S3, S0 | Test item 16; manual two-profile drill |
| **S5** | Frontend: Needs review page with timeline and Apply sequence, header badge, conflict notices, discard-own-item | B4b, S4 | Test item 16; role visibility |
| **S5b** | Frontend: adopt flow ("items from other users", confirmation, fresh-login prompt), staleness warning | B2c, S5 | Test items 11e, 16 |
| **S6** | PWA update strategy: `registerType: "prompt"`, update notice, `CLIENT_TOO_OLD` handling, install prompt, `storage.persist()` | S4 | Update-during-pending-ops test |
| **D1** | Docs and runbook updates: restore runbook additions (Needs review, master-data re-entry), operator quick guide (Thai), `docs/api/` pages for sync endpoints, `ROADMAP`/`DECISION_LOG`/knowledge updates as the workflow requires | all | Docs review |
| **E1** | Evidence drill (no code): outage drill, restore-and-replay drill, real phones; recorded with the correct evidence class | all | Owner-visible report |

The Owner decides after B2 and S4 whether to continue to the later slices or run a pilot with the first four.
