# Business Rules

**Purpose:** Compact, current-state summary of approved Medical Equipment Pool business rules, for fast AI/human onboarding
**Authority:** Summary only. Each rule cites its authoritative source; the cited source controls in case of any apparent conflict with this file. This file does not add, relax, or reinterpret a rule.
**Update trigger:** A rule below is confirmed changed by an approved ADR, `docs/ARCHITECTURE_DECISIONS.md` entry, or Governance PR
**Maintainer:** Architecture Owner

Only approved, confirmed rules are listed here. Do not add a rule that has not been confirmed through the sources below.

## Four Equipment States

Equipment has exactly four states: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`. No fifth state (in particular, no cleaning-related state) exists.

- Source: `docs/HOSPITAL_DOMAIN_MODEL.md` ("Confirmed workflow"); `docs/audits/04-consolidated-implementation-plan.md` Part A; implemented by migration `0006_equipment_state_model.py` and `backend/app/models/equipment.py`.

## Cleaning is not tracked

Cleaning is a physical operational activity, not a digital one. It may occur before or after the receipt record is entered — the system does not require or assume any particular order. Cleaning is not represented as an equipment state and does not require a separate cleaning workflow: there is no cleaning state, cleaning-complete action, or cleaning-status field. Equipment receipt is one atomic digital operation with a binary outcome — a usable receipt ends at `AVAILABLE_AT_POOL`; a defective receipt ends at `UNAVAILABLE_DEFECTIVE`.

- Printed form exception (D17, Owner Governance 2026-11-26): the daily printed forms end with the verbatim paper "Equipment Verify Checklist" (FI-CES-BCM-PO-001/2) listing devices received in the shift, with every check cell (Cleaner included) printed blank for hand completion. The system records nothing from it. D23 (2026-11-27) amends this: rows are pre-printed with ✓ in Cleaner, Function Test, Run Test, Battery Check and Pass (✓ in Fail instead of Pass when the receipt outcome was defective), as a printed template only; staff correct the paper by hand.
- Source: `docs/ARCHITECTURE_DECISIONS.md` ("No cleaning workflow"); `AGENTS.md` (Domain Guardrails); `docs/audits/04-consolidated-implementation-plan.md` Part B.1. The binary outcome itself is now the request/response contract's own `receipt_outcome` field (Roadmap PR8B, `knowledge/adr/ADR-006-receipt-outcome-contract.md`), not only an internal mapping.

## UUID is relational identity

The internal UUID is the permanent relational primary key for an equipment record. It is never entered manually by an operator and is the only identifier borrow/return records reference. It does not change even if BCM Code, Item No, or Asset Number are later corrected or reassigned.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/business-rules/equipment-pool.md`.

## BCM is the manual identifier

BCM Code is the primary operator-facing identifier and the only identifier accepted by manual equipment search. It is unique across all equipment; uniqueness and search matching are enforced on its canonical persisted form.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/adr/ADR-003-bcm-manual-search.md`; `knowledge/architecture/identifiers.md`.

## Asset Number is optional inventory metadata

Asset Number is the hospital-assigned inventory number. **It is optional** (Governance 2026-10-21, Owner decision): equipment may be created and may exist without one. When present it is unique across all equipment and non-blank. It is never fabricated or derived — not generated, not a placeholder, and in particular never copied from Asset ID (`asset_id` remains its own optional column, "not renamed, reused, or merged", Roadmap PR12 Part E). A blank value supplied on create is stored as no value. Displays show "-" when it is absent; an XLSX export leaves the cell empty and a CSV export writes an empty string. It is still not a QR identifier and not a manual-search identifier. The four-identifier model is unchanged.

- Source: `knowledge/adr/ADR-002-identifier-model.md` (amended 2026-10-21); `docs/DECISION_LOG.md` (Governance 2026-10-21); migration `backend/alembic/versions/0029_asset_number_optional.py`.

## Item No is internal QR lookup only

Item No is the identifier encoded in the hospital's existing QR labels. It is used only for exact QR lookup, is unavailable as a manual-search identifier, and is absent from normal operator-facing response contracts — it may appear only in explicitly restricted administrative/import contexts.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/adr/ADR-004-hospital-item-no-qr.md`; `knowledge/architecture/api-information-boundaries.md`.

**Demo/loan exception (Owner Governance 2026-11-26, D14):** for `equipment_source` demo/loan devices only, the BCM Code field holds the manufacturer Serial Number; see "Demo/loan equipment" below. The identifier count and roles are unchanged.

**"ME Code" is retired.** It does not name any current or planned identifier; any document or task still using it means BCM Code or Item No and should be corrected. **Sole exception (Owner Governance 2026-11-25, third set, D12):** see "Cryo-Cuff checklist, cuff tracking, printed-form label, access" below.

## Dispatch/Return owns transaction lifecycle

**Amended by Owner Governance 2026-11-25, second set (D8):** dispatch no longer requires `available_at_pool`; the dispatch service gains two transitions, `UNAVAILABLE_DEFECTIVE -> ISSUED_TO_WARD` (dispatch while defective: operator confirmation, audited, flag recorded on the transaction; no separate return-to-service permission is needed for this path, which D8 explicitly amends) and `ISSUED_TO_WARD -> ISSUED_TO_WARD` (re-dispatch closes the previous open transaction with reason "closed by re-dispatch, receipt not recorded" and opens a new one); afterwards the equipment is `ISSUED_TO_WARD` and its later receipt is the normal atomic usable/defective receipt; `DECOMMISSIONED` is never dispatchable. See "Dispatch availability, ward contact name, shift attribution" below (re-dispatch closes the prior open transaction; defective dispatch allowed and flagged; decommissioned blocked).

Dispatch and receipt (`backend/app/services/borrow_service.py`) are the only paths that move equipment through `ISSUED_TO_WARD`, and the only paths that open (`app.crud.transaction.create()`) or close (`app.crud.transaction.close()`) a transaction — administrative/manual equipment-status maintenance is a separate, narrower transition set that never originates or targets `ISSUED_TO_WARD` and never touches transaction status at all.

**Amended by Owner Governance 2026-11-27 (D28):** a third transaction status `voided` exists for corrections (see "Entry-error prevention and correction" below); equipment states are unchanged.

`BorrowTransaction.status` is `TransactionStatus.OPEN` / `TransactionStatus.CLOSED`, plus `VOIDED` for D28 corrections only (`backend/app/models/transaction.py`; Roadmap PR7; `knowledge/adr/ADR-005-transaction-model.md`), matching `docs/HOSPITAL_DOMAIN_MODEL.md`'s confirmed `OPEN`/`CLOSED` workflow. An overdue (`due_at` passed) transaction remains `OPEN` — the approved MVP business model has no due-date/overdue workflow at all, not a status value and not a notification. The `due_at`-driven overdue notification job (`app.worker.scheduler.check_overdue_returns`) has been removed and is not registered with the scheduler (Codex PR7a review round 1, BLOCKER: the job re-notified on every hourly tick with no de-duplication) — see `knowledge/adr/ADR-005-transaction-model.md` decision 3.

**Amended by Owner Governance 2026-11-25 (D2):** `dispatch_type` and `routine_round` are removed from data entry; new dispatches no longer carry them (the columns become nullable and historical values are preserved read-only, never erased or backfilled), so the requirement below that every dispatch carry them no longer applies to new dispatches. Reporting groups by the PR16 `business_date`/`shift` (Day/Night) derived from the event time. Source: `docs/DECISION_LOG.md` (2026-11-25).

**Amended by Owner Governance 2026-11-25, second set (D7):** an optional free-text ward contact name may again be recorded at dispatch and receipt (see "Dispatch availability, ward contact name, shift attribution" below); the statements here that `borrower_name` is rejected describe the PR7 state until PR27 ships.

**Roadmap PR7 (7b slice), merged (GitHub PR #20):** every new dispatch (`app.schemas.transaction.BorrowRequest`) must carry a `ward_id` and a `dispatch_type` (`routine_round` or `on_demand`, `backend/app/models/transaction.py`'s `DispatchType`); a `routine_round` (one of the four confirmed fixed times `06:00`/`11:00`/`15:00`/`21:00`, `RoutineRound`) is required exactly when `dispatch_type == routine_round` and forbidden for `on_demand`. `BorrowRequest` rejects any unrecognized field outright (`extra="forbid"`), so `borrower_name`, `due_at`, and `quantity` are not merely unaccepted but actively rejected with a 422; `due_at` is also removed from `TransactionOut`. Every existing historical value for all three fields is preserved as read-only history, never erased or backfilled — `borrower_name` remains visible in `TransactionOut`; `due_at`/`quantity` remain queryable via `app.services.report_service`'s export, which reads them directly from the ORM row. An existing row's `ward_id`/`dispatch_type`/`routine_round` are never fabricated for historical data — left `NULL`. `ward_id` is validated proactively (400 `INVALID_INPUT` if it does not reference an existing ward), distinct from the 409 concurrency response used when the same equipment is dispatched twice.

- Source: `backend/app/models/transaction.py`; `backend/app/schemas/transaction.py`; `backend/app/services/borrow_service.py`; `backend/app/crud/transaction.py`; `backend/alembic/versions/0008_dispatch_fields.py`; `docs/HOSPITAL_DOMAIN_MODEL.md`; `knowledge/adr/ADR-005-transaction-model.md`; `docs/audits/04-consolidated-implementation-plan.md` Part D (PR7).

## Roles and the confirmed 3-role permission matrix (Roadmap PR10)

**Merged as of the current baseline above** (GitHub PR #36, squash `53340f6d7d5c8cda685235411b60a57d2d033a7e`) — this section documents the live, active rule. The legacy 5-role model (`admin`, `biomedical_engineer`, `ward_nurse`, `transport_staff`, `viewer`) is replaced everywhere a role is persisted or checked by exactly three confirmed roles:

| Role | Capability |
|---|---|
| `administrator` | Everything below, plus: equipment master-data create/update/delete; reactivate defective equipment; decommission equipment; department/ward/location/category master-data create; user and role management; audit-log reads. |
| `equipment_pool_staff` | Dispatch, receipt, ward correction, marking equipment defective; view/search/report surfaces. |
| `read_only` | View/search/report surfaces only — no write capability of any kind. |

`equipment_pool_staff` and `read_only` may both view every list/search surface (equipment, transactions, active borrows, master data) and export reports — a capability tier already available pre-PR10, preserved rather than narrowed. `backend/app/api/v1/deps.py` defines the canonical, centralized capability groups (`EQUIPMENT_POOL_OPERATION_ROLES`, `ADMINISTRATOR_ONLY_ROLES`, `VIEW_AND_REPORT_ROLES`, `WARD_CORRECTION_ROLES`) that every endpoint's role gate references — never an inline ad hoc role tuple. `frontend/src/hooks/useAuth.ts` mirrors this matrix exactly as a centralized capability layer (`canCorrectTransactionWard`, `canMarkEquipmentDefective`, `canManageEquipmentMasterData`, `canReactivateEquipment`, `canDecommissionEquipment`, `canManageUsers`, `canDispatchOrReceiveEquipment`); this is a usability-only gate, never a security boundary — the backend remains solely authoritative.

**Migration mechanism (`backend/alembic/versions/0009_role_consolidation.py`):** `admin` → `administrator` and `viewer` → `read_only` are remapped automatically (confirmed, evidence-backed equivalents). `biomedical_engineer`, `ward_nurse`, and `transport_staff` have no confirmed equivalent and are never auto-mapped — if any user holds one of these roles, the migration requires an explicit `MEP_PR10_ROLE_MAPPING` environment variable (a JSON array of `{employee_code, target_role}` objects covering every such user) and aborts with a `RuntimeError` naming the unresolved accounts if the manifest is missing, incomplete, or invalid. The migration is fully reversible: every user's pre-migration role name is captured in a new `users.legacy_role_name` column before any rewrite, as human-readable provenance only. The actual downgrade mechanism is three durable migration tables: `user_role_migrations` (each user's exact legacy and migrated role ids), `role_migration_snapshots` (every legacy role's exact pre-upgrade id/name/permissions), and `confirmed_role_ownership` (whether each confirmed role already existed before upgrade or was created by it). `downgrade()` preflights for missing/inconsistent provenance and post-upgrade role divergence before any write, then restores every legacy role to its exact original id and permissions, restores every user to their exact original role id, writes downgrade audit provenance, and deletes a confirmed-role row only when ownership provenance proves this migration created it — a role name alone is never sufficient to restore or delete anything. A `ck_roles_name_confirmed` CHECK constraint then restricts `roles.name` to exactly the 3 confirmed values, defense in depth alongside the application-layer gate.

- Source: `docs/archive/audits/03-hospital-equipment-pool-workflow-audit.md` §10 ("Role and Permission Review"); `docs/audits/04-consolidated-implementation-plan.md` Part D (PR10); `backend/app/models/user.py`; `backend/app/api/v1/deps.py`; `backend/alembic/versions/0009_role_consolidation.py`; `frontend/src/hooks/useAuth.ts`; `docs/DECISION_LOG.md` ("Roadmap PR10").

## Ward correction is audited, not a transfer

A transaction's first recorded receiving ward is normally immutable after dispatch. It may only be changed through one narrow, purpose-built action, `POST /transactions/{transaction_id}/correct-ward` (`app.services.borrow_service.correct_ward`) — never a generic transaction PATCH. This is correction of historical operational data, not ward-to-ward transfer tracking or current-location tracking; no such concept exists anywhere in this system. The action works identically whether the transaction is `open` or `closed` — no lifecycle-status precondition applies, and no equipment or transaction lifecycle state, `dispatch_type`/`routine_round`, or business-event timestamp is read or written. A same-ward submission is rejected as a no-op (`409 WARD_CORRECTION_NOOP`); a concurrent stale-read loss is rejected distinctly (`409 WARD_CORRECTION_CONFLICT`), decided by the same conditional-`UPDATE`-by-affected-rowcount shape Roadmap PR8A established for the receipt-close guard. Every successful correction writes exactly one audit entry, atomic with the ward change.

Authorization is `administrator` and `equipment_pool_staff` (`app.api.v1.deps.WARD_CORRECTION_ROLES`), per Roadmap PR10's confirmed 3-role matrix (see "Roles and the confirmed 3-role permission matrix" above) — `read_only` is denied with `403`. This was temporarily restricted to `admin` only between PR9A's merge and PR10's merge, since the then-current 5-role model had no confirmed, evidence-backed equivalent of "Equipment Pool Staff." The frontend mirrors this as a usability-only gate (`frontend/src/hooks/useAuth.ts`'s `canCorrectTransactionWard`); the backend remains the sole authorization boundary regardless of frontend visibility.

- Source: `backend/app/services/borrow_service.py`; `backend/app/crud/transaction.py`; `backend/app/api/v1/transactions.py`; `backend/app/api/v1/deps.py`; `frontend/src/components/WardCorrectionAction.tsx`; `frontend/src/components/WardCorrectionDialog.tsx`; `docs/api/transactions.md`; Roadmap PR9 (PR9A backend, GitHub PR #33; PR9B frontend, GitHub PR #34) — see `docs/DECISION_LOG.md`.

## Decommission requires AVAILABLE -> UNAVAILABLE_DEFECTIVE -> DECOMMISSIONED

`AVAILABLE_AT_POOL` has no direct transition to `DECOMMISSIONED`. Equipment must first be marked `UNAVAILABLE_DEFECTIVE`; only `UNAVAILABLE_DEFECTIVE` may transition to `DECOMMISSIONED`. `DECOMMISSIONED` is terminal with no outgoing transition.

- Source: `backend/app/models/equipment.py` (manual-maintenance transition table); confirmed as a review finding during Roadmap PR6 (see `docs/DECISION_LOG.md`).


## Patient HN on dispatch (Owner Governance 2026-11-25)

Equipment Pool staff MAY record a patient HN (hospital number) on a dispatch. This narrowly amends the former "no patient tracking" rule; no other patient field (name, bed, etc.) exists and there is no patient-tracking workflow. Mandatory safeguards: HN is stored only in the database, encrypted at rest at the application level (key from the host `.env`, never in the repo, logs, or clear-text backups); masked by default in every UI view and revealed only by an explicit "แสดง HN" click by an authenticated user; every reveal is audited (who/when/which transaction, never the HN value); HN never appears in any printed report, PDF, Excel export, CSV, read-only export API, log, notification, or the legacy sheet sync/import (which keep dropping/skipping HN); no search by HN unless separately approved. **Add later (Owner Governance 2026-11-26, D15):** an HN may also be added afterwards to an existing open dispatch, audited, under every safeguard in this section. The Owner accepts PDPA responsibility; hospital legal/IT review is recommended; the retention policy is a future decision.

**HN to the N Smart keying tool (Owner Governance 2026-11-27, D29):** a single, narrow exception to "HN never appears in the read-only export API". The export API may include the decrypted HN of a dispatch only under all of the following conditions:
- the caller uses an export key created with the explicit `hn` scope;
- the request comes from a source IP on the administrator-configured allowlist (the host running the N Smart keying tool); requests through the public Tailscale Funnel never receive HN;
- the transport is TLS or the same host;
- each response that contains HN writes one audit entry (key, count of HN values, time; never the values);
- HN is never logged or cached by this system.

Every other export, report, print, log, notification and the legacy sheet sync stay HN-free. HN still never travels to the sheet. Keys without the `hn` scope behave exactly as before. The external tool is responsible for protecting HN it receives (local storage, logs). This system still never calls N Smart.

- Source: `docs/DECISION_LOG.md` (2026-11-25; 2026-11-27 D29).

## Dispatch/receipt entry flow and accessory checks (Owner Governance 2026-11-25)

- Ward first: select the ward, then scan/enter one or more equipment for that ward in one submission, for both dispatch and receipt. Each equipment is still its own transaction; dispatch/receipt services still own the lifecycle; receipt stays an atomic usable/defective outcome per equipment.
- Per equipment, at dispatch and at receipt, three yes/no condition checks: screen not cracked (ตัวเครื่องหน้าจอไม่แตกร้าว), charger cable OK (สายชาร์จไม่ขาด), pole clamp present/OK (Pole Clamp ไม่แตกหัก). These are recorded condition facts only: not a cleaning state and not a new equipment state.
- A daily shift report (by ward group, equipment type, operator; Day vs Night; dispatch/receipt counts) and printable daily forms are planned; HN never appears in them.

- Source: `docs/DECISION_LOG.md` (2026-11-25).

## Dispatch availability, ward contact name, shift attribution (Owner Governance 2026-11-25, second set)

- **Dispatch is not blocked by equipment status (D8; amends the rule that dispatch requires `available_at_pool`):** the UI shows what is wrong and the operator confirms. (a) Equipment already dispatched: the dispatch service atomically closes the previous open transaction with a flag/reason "closed by re-dispatch, receipt not recorded" (audited) and opens the new one. (b) `unavailable_defective`: dispatch is allowed; the transaction records it was dispatched while marked defective (audited). (c) `decommissioned`: still blocked. Dispatch/receipt services still own the lifecycle; the four states are unchanged; no cleaning state.
- **Ward contact name (D7; amends the PR7 removal of `borrower_name`; the sheet sync currently does not import ward-side person names, a rule that lives in `backend/app/services/legacy_sheet_sync/runner.py` and keeps applying until PR27, which will map the sheet's ward user column ("ผู้ส่งเครื่องยืม (User)"/"ชื่อ (User)") into the ward contact name; Owner Governance 2026-11-26 D21 confirms this mapping for new synced rows, and D22 adds an optional display-only BME keyer label for sheet-synced rows printed on the daily forms):** at dispatch and receipt the operator may record an optional free-text name of the ward staff who received/sent the equipment, one value per submission applied to each equipment's transaction. Ward staff remain non-users (no accounts, no login). Never a patient name; may appear in reports and the monitor page.
- **Receipt from a different ward (Owner UX answer):** accepted with no warning; only the first receiving ward is recorded and there is no transfer tracking. HN is one optional field per equipment; accessory checks default to checked/normal.
- **Shift attribution for reporting (D6; amends PR16 Owner Decision #1 for REPORTING ONLY):** a configurable +/-N minutes (default 60; 0 = strict clock cut) around 08:00 and 20:00. Events in the window are attributed to the shift the keying Equipment Pool user predominantly worked that business day (the shift holding most of that user's events outside the window); ties or no other events fall back to the clock rule. Stored timestamps never change and the `business_date`/`shift` used for list filters is unchanged; the daily shift report (PR30) uses the attributed shift. Attribution is computed at report time only (nothing is stored), and the business day used for it is the PR16 `business_date` (shift-start anchored, `backend/app/core/reporting_time.py`).
- **Monitor page (D9):** dispatch/receipt submissions grouped by date with drill-down; never shows HN unmasked.

- Source: `docs/DECISION_LOG.md` (2026-11-25, second set).

## Cryo-Cuff checklist, cuff tracking, printed-form label, access (Owner Governance 2026-11-25, third set)

- **Cryo-Cuff checklist (D10; amends D4 for this one equipment type only):** Cryo-Cuff dispatch and receipt use a 6-item checklist exactly matching the paper form "แบบบันทึกการรับรับ-ส่ง Cryo-Cuff": (1) ตัวเครื่อง x1 (ไม่แตกหัก เสียหาย); (2) สายชาร์จ x1; (3) ฝาปิดตัวเครื่อง แบบมีสายชาร์จ x1; (4) ฝาปิดตัวเครื่อง แบบไม่มีสายชาร์จ x1; (5) สายท่อน้ำและ O-Ring x1 (O-Ring บริเวณปลาย Hose ทั้งสองข้าง); (6) Cuff (สภาพสมบูรณ์ ไม่มีฉีกขาด) in four types, Back/Hip/Rib, Knee, Shoulder, Ankle, each with a count. Each item is normal/abnormal. All other equipment keeps the three D4 checks. Reports map Cryo-Cuff items 1/2/3 into the same three report columns as other equipment (screen/body, charger, clamp); items 4-6 are stored but not in the daily report. How Cryo-Cuff equipment is identified (equipment category) is decided in implementation from existing master data. The system does not print the Cryo-Cuff form.
- **Cuff tracking (D11):** cuffs are counted per type; there are no individual cuff IDs. At receipt the operator may receive the device only (cuffs wet or not returned). Outstanding cuffs (type, count, ward = the transaction's first ward) are tracked and shown on the Monitor page and in reports until received. A later "receive cuffs" step (scan the same device, tick the returned cuffs) clears them. The device may be dispatched again while its cuffs are outstanding; the outstanding cuffs stay attributed to the earlier ward/transaction. Cuffs are accessories, not equipment: no equipment state, not part of the four states, and no cleaning state.
- **Printed daily form label (D12; narrow exception to "ME Code is retired"):** the printed daily form must match the company's official form exactly, including the column header "ME.Code", which shows the BCM Code value. This is allowed only as a verbatim printed-form column label. ME Code is NOT an identifier anywhere in the system, data model, API or other UI, which keep "BCM Code". Revisit when the company changes the form.
- **Access (D13):** all Equipment Pool staff (normal operators) can use the Monitor page and the "แสดง HN" reveal; every reveal is audited per D1.

- Source: `docs/DECISION_LOG.md` (2026-11-25, third set).

## Demo/loan equipment (Owner Governance 2026-11-26, D14)

- Administrators may register demo/loaned devices (same models/categories as pool devices) with `equipment_source` = `demo` | `loan` (pool devices = `pool`), owner company (vendor) name, optional due-back date, and per-device accessory presence (has charger, has clamp). Batch registration: shared fields plus one row per serial number (paste from Excel supported).
- **Identifier amendment (narrow):** for `demo`/`loan` devices ONLY, the BCM Code field holds the manufacturer Serial Number. The four-identifier model is unchanged (identifier count and roles unchanged); only the value semantics of the BCM Code field differ for these sources. Pool devices keep real BCM Codes. **D27 (Owner Governance 2026-11-27):** for a `loan` device borrowed from another hospital that labels it with its own asset code (e.g. Khon Kaen "BKN…"), the BCM Code field holds that lending hospital's asset code exactly as staff scan/type it in the legacy sheet, and the manufacturer serial, when known, goes in the Serial Number field. BCM Code uniqueness applies across pool and demo/loan devices alike, so a serial cannot collide with a real BCM Code.
- Demo/loan devices use the normal dispatch/receipt flows and checklists, with no special UI text. They are EXCLUDED from the read-only export API consumed by the external N Smart tool (no MEMS integration change). Dashboard counts include them with a source filter (all/pool/demo/loan). Badges "DEMO"/"ยืม" appear in scan rows, the Monitor page and reports.
- **Return to owner ("คืนผู้ให้ยืม")** is an administrator action in equipment management, not in dispatch/receipt. Implemented as a `returned_to_owner` flag (timestamp, actor, audited) settable only while the device is `AVAILABLE_AT_POOL`; the device leaves active lists/counts/pickers and cannot be dispatched (block enforced in the dispatch service); history is kept. No reversal is defined: return to owner is irreversible unless separately approved. No fifth equipment state: exactly four states remain, and there is no cleaning state.

- Source: `docs/DECISION_LOG.md` (2026-11-26); `knowledge/adr/ADR-002-identifier-model.md` (amended 2026-11-26).

## Standby rule, add HN later, standby summary (Owner Governance 2026-11-26, D15, D16)

- **Standby (D15):** an open dispatch without HN is Standby at that ward; with HN it is in use for a patient. Pool staff may add an HN later to an existing open dispatch (audited; every HN safeguard above applies), converting it from Standby to in use. Dispatch is never blocked for an incomplete set (device + charger + clamp).
- **Standby summary page (D16; brings "Standby Snapshots" forward, narrowly):** selectable cut-off, Night summary at 08:00 or Day summary at 20:00; only infusion pump and pneumatic pump are shown. Infusion pump: Standby per ward (open dispatches without HN at the cut-off, using PR30 ward short labels); BME stock = devices, chargers and clamps at pool (computed from dispatch/receipt accessory checks against a staff-entered baseline); Ready (พร้อมใช้งาน) = min(devices, chargers, clamps). Pneumatic pump: in use = all devices currently out (open dispatches), plus returned today. Every number is editable by pool staff; system and edited values are both stored and edits audited. A "Copy text" output reproduces the Owner's LINE message; the PR30 daily Excel "Stand By" column is filled from this summary. D25 (2026-11-27): edits change only the LINE text; the Excel "Stand By" column uses the system-computed values. Charger/clamp stock counts are approximate (manual correction expected). HN is never shown in the summary beyond the has-HN/no-HN distinction.

- Source: `docs/DECISION_LOG.md` (2026-11-26).

## Entry-error prevention and correction (Owner Governance 2026-11-27, D28)

- **Layer 1, prevention (UI only):** when a scanned device's current state contradicts the open page (a device still out at a ward on the dispatch page, or a device at the pool on the receipt page), the UI offers a one-tap switch to the other action. A device scanned twice in one batch is flagged immediately. There is **no** warning when the returning ward differs from the dispatch ward (Owner, 2026-11-27): devices move between wards and only the first receiving ward is recorded.
- **Layer 2, undo:** within **2 minutes** after saving a dispatch, or **30 seconds** after saving a receipt (Owner 2026-11-27: matched to the external N Smart tool's send delays). To make this race-free, the read-only export API **withholds each dispatch/receipt event until its undo window has passed**, so an undone entry is never exposed and never reaches N Smart; an undo therefore emits no export event at all, the operator who saved a dispatch or receipt may undo it with one tap. Undo is a void (below) with the system reason "เลิกทำ", and like every void it writes its own audit entry.
- **Layer 3, audited corrections**, from the equipment history, each with a mandatory reason and one audit entry atomic with the change:
  - **Void (ยกเลิกรายการ):** the transaction becomes `voided`, a third transaction status. Equipment states stay exactly four, and void is never an equipment state. The device returns to the state it had before the voided event: voiding a dispatch restores the pre-dispatch state, and if that dispatch closed an earlier transaction by re-dispatch, that transaction reopens. Voiding a receipt reopens the transaction and puts the device back to `ISSUED_TO_WARD`. Voided rows stay in history, shown struck through, and are excluded from every report, the Standby summary, the daily Excel and every export except the read-only export API, which carries them with status `voided`.
  - **Change device (เปลี่ยนเครื่อง):** voids the transaction on the wrong device and records the same event (same time, ward, keyer label, contact name, checks; HN carried over encrypted, never displayed) on the correct device through the normal dispatch/receipt services.
  - **Switch action (สลับงาน):** a dispatch that should have been a receipt is voided and the receipt is recorded with the original time. A receipt that should have been a dispatch is voided and the dispatch is recorded with the original time.
  - **Ward:** the existing audited ward correction is unchanged.
- **Restore source:** at each dispatch the service stores the device's prior equipment state, and the transaction it closed by D8 re-dispatch if any, on the new transaction. A receipt already stores its outcome. Void restores from those stored fields. A legacy row without them restores a voided dispatch to `AVAILABLE_AT_POOL`.
- **State guard:** a correction or undo is refused, and nothing changes, if the device's current state is no longer the state that event produced (for example, an administrator moved it to maintenance afterwards). An administrator must resolve that first.
- **Change device** is atomic: the correct device must pass the normal dispatch/receipt rules (for example, it cannot be on another open transaction unless the D8 re-dispatch rules allow it). If any step fails, nothing changes.
- **Switch action details:** dispatch→receipt is offered only when the device had an open transaction before the wrong dispatch. That transaction is reopened and closed by a receipt at the original time, and the operator picks usable or defective in the dialog (default usable). receipt→dispatch voids the receipt (its transaction reopens), then records the dispatch at the original time to the ward chosen in the dialog. That dispatch follows D8, so the reopened transaction is closed as a re-dispatch.
- **Undo** follows the same state guard and latest-transaction rule, but is not limited by the end of the shift. Its window is 2 minutes from saving a dispatch, or 30 seconds from saving a receipt, for the operator who saved.
- **Export API and HN:** the read-only export API includes the `voided` status value so external readers learn about the void. For a correction made after the undo window, the entry may already be in N Smart, so the export API also emits **compensating events** for the external tool to re-key: a voided dispatch yields a correction `receipt` event (the device is received back first, as usual), and a voided receipt yields a correction `dispatch` event. The corrected event (for example, the dispatch on the right device or to the right ward) follows as a normal event. Correction events are marked as such and never carry HN. Every other report excludes voided rows. A voided dispatch's HN stays encrypted and masked, and a reveal is audited as usual. Change device moves the HN server-side to the new transaction and clears it from the voided row. The HN never travels through the client.
- **Scope and permission:** only the device's **latest** transaction may be voided, re-assigned or switched, so the state restore is unambiguous. Equipment Pool staff may correct their own entries within the same shift (PR16 business date + shift). After that, only an administrator may. All corrections go through the dispatch/receipt services, never through manual status maintenance.
- Source: `docs/DECISION_LOG.md` (2026-11-27, D28).

## Related documents

| Concern | Document |
|---|---|
| Full domain workflow narrative and terminology | `docs/HOSPITAL_DOMAIN_MODEL.md` |
| Architecture invariants that protect these rules | `docs/ARCHITECTURE_GUARDRAILS.md` |
| Per-decision rationale and history | `docs/DECISION_LOG.md`, `docs/ARCHITECTURE_DECISIONS.md` |
| Identifier/QR architecture detail | `knowledge/adr/ADR-002` through `ADR-004`, `knowledge/architecture/` |
| Transaction lifecycle decision | `knowledge/adr/ADR-005-transaction-model.md` |
| Domain entity structural reference | `docs/DOMAIN_MODEL.md` |
| Preferred terminology | `docs/GLOSSARY.md`, `knowledge/glossary.md` |

## Daily report rows, sheet-sync duplicates and bulk dismiss (Owner Governance 2026-11-26, D18-D20)

- **Per-ward rows (D18):** the daily Excel and the Standby summary show one row per ward (Ward 7A and Ward 7B are separate), grouped and ordered by the Owner's layout. Wards are never merged. D24 (2026-11-27) refines this: rows carry the legacy layout labels, and ward names the Owner confirms are the same place (alias list) share one row; different places are still never merged.
- **Sheet-sync duplicate receipts (D19):** on the Legacy Sheet Sync path only, a receipt row whose transaction is already closed by a receipt for the same equipment and ward within a short business-time window is skipped as already received, not filed as a conflict. App clients keep `TRANSACTION_ALREADY_RETURNED`.
- **Bulk dismiss (D20):** an administrator may dismiss all open sync conflicts from the Legacy Sheet Sync device in one action; each dismissal is individually audited through the existing dismiss service; nothing is applied.
