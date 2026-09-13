# Business Workflow Review — Medical Equipment Pool

**Reviewer role:** Hospital Information System Architect / Biomedical Equipment Pool Workflow Analyst
**Scope:** Compare the *implemented* system against the *actual* Equipment Pool operating model (routine rounds, on-demand requests, first-ward recording, collect→clean→return-to-pool). No code changed. No MEMS/patient-tracking/PM/calibration/recall scope introduced.
**Method:** Every claim below is traced to a specific file/function, re-verified against the current source this session (not carried over from memory).

---

## 0. Assumptions and Unresolved Questions (stated up front, referenced throughout)

| # | Assumption / Open Question | Why it matters |
|---|---|---|
| A1 | `ID CODE` (e.g. `BCM02719`) is the hospital's **ME Code** — this is the prompt's own stated assumption, not confirmed by the hospital. | Determines which inventory column becomes the primary search/scan key. Must be confirmed before import mapping is finalized. |
| A2 | `Item No.` is a row/line number within a particular inventory export, **not** a globally unique identifier across the whole fleet. | Determines whether `Item No.` can ever be used as a lookup key (recommendation below assumes it cannot). |
| A3 | The source inventory's `Location` field means "the equipment's home/routine-allocation ward," not "current physical location." | If wrong, this field could be conflated with the transactional `ward_id` this review recommends keeping separate. |
| A4 | Source `Asset Status` values (Active/Defective/Decommissioned or similar) are not enumerated anywhere in the supplied material. | The status-mapping table in §8 is illustrative only and must be validated against the real distinct values before import is built. |
| A5 | "Recorded-by user" for a dispatch/return is always an **Equipment Pool staff member**, never ward staff, since wards only telephone in requests. | Shapes the role model in §10 — the system does not need ward-side user accounts for the MVP workflow described. |
| A6 | The four-round cadence (06:00/11:00/15:00/21:00) is a fixed, hospital-wide schedule that does not vary by ward or equipment type. | Shapes whether "round" should be a simple fixed enum (assumed here) or a configurable schedule (out of scope if A6 holds). |
| A7 | "Return and cleaning workflow complete" (task 6) does not specify whether recording-return and confirming-cleaning are meant to be one system action or two — the source workflow describes them as sequential *physical* steps, not necessarily sequential *digital* steps. | §6 resolves this with an explicit recommendation and states the reasoning, since the prompt asks the reviewer to decide. |

---

## 1. Current Workflow Reconstruction

| Workflow area | What the code actually does | Evidence |
|---|---|---|
| **Equipment registration** | Single-record creation only, via `POST /equipment`. No bulk import/CSV/inventory-load feature exists anywhere in the codebase (verified by grep — no import/upload endpoint of any kind). `qr_code_value` is auto-derived from `asset_number` at creation time. | `app/api/v1/equipment.py:123-147` (`create_equipment`), `app/services/qr_service.py` (`build_qr_value`), `app/schemas/equipment.py:8-22` (`EquipmentCreate`) |
| **Borrow/dispatch** | `POST /borrow` requires a **named individual borrower** (`borrower_name`, required, min length 1). `ward_id` is **optional**. No concept of "dispatch round" or "on-demand" exists — there is one undifferentiated dispatch action. Checks `equipment.status == AVAILABLE` before allowing dispatch. | `app/api/v1/borrow.py:23-48`, `app/services/borrow_service.py:28-99` (`borrow`), `app/schemas/transaction.py:8-19` (`BorrowRequest`) |
| **Return** | `POST /return/{transaction_id}` requires the returning staff member to pick a `condition` from five options (`available`, `cleaning`, `pm`, `calibration`, `repair`) — **all five are treated as equally-weighted, one-step choices**. Choosing `available` immediately flips equipment status to `AVAILABLE`, with no separate cleaning-confirmation step. | `app/api/v1/borrow.py:58-76`, `app/services/borrow_service.py:102-152` (`return_equipment`), `RETURN_CONDITION_TO_STATUS` dict |
| **Cleaning** | Modeled as **one status value** (`EquipmentStatus.CLEANING`) among eight, chosen at return time. No dedicated "cleaning complete" action or endpoint exists. Once in `CLEANING`, the only way back to `AVAILABLE` is the generic, admin/biomedical-engineer-only manual status-change endpoint — there is no purpose-built "confirm ready" workflow. | `app/models/equipment.py:16-27` (`EquipmentStatus`), `app/api/v1/equipment.py:180-208` (`change_equipment_status`) |
| **Ward handling** | `ward_id` (FK to `Ward`) is recorded once, optionally, at borrow time. Separately, `Equipment.current_location_id` (FK to a generic `Location` table) exists on the equipment record itself, and `pickup_location_id`/`dropoff_location_id` (also FK to `Location`) exist on the transaction — **three different "where" representations coexist** for what the real workflow needs to be one clearly-scoped concept. No transaction field is ever updated after creation (no PATCH path touches `BorrowTransaction`), so "first ward only" holds today, but only by omission, not by design. | `app/models/transaction.py:27-44` (`ward_id`, `pickup_location_id`, `dropoff_location_id`), `app/models/equipment.py:43` (`current_location_id`) |
| **Transaction status** | Three-state model: `"borrowed"` → `"returned"`, plus a third `"overdue"` state set by a background job. | `app/models/transaction.py:10-12` (`TX_STATUS_BORROWED/RETURNED/OVERDUE`) |
| **Overdue handling** | Hourly cron job flips `status` to `"overdue"` if `due_at` (optional, never populated by any UI flow) is set and has passed. Notifies Admin/Biomedical Engineer roles. | `app/worker/scheduler.py:74-97` (`check_overdue_returns`) |
| **Scheduling** | Two APScheduler cron jobs: daily 06:00 PM/CAL-due check, hourly overdue check. **Neither corresponds to the hospital's actual four fixed dispatch rounds (06:00/11:00/15:00/21:00)** — these are unrelated background maintenance-reminder jobs, not a dispatch-round concept. | `app/worker/scheduler.py:100-108` (`start_scheduler`) |
| **Audit trail** | Two mechanisms: `equipment_status_history` (per-equipment status transitions) and `audit_logs` (generic action/entity/before-after/IP/user-agent). Written only from `equipment.py` and `borrow_service.py` — **not** from `auth.py`, `users.py`, or `master_data.py` (confirmed in the prior backend audit, Finding 12.1/12.2, still applicable). | `app/crud/audit.py`, `app/models/audit.py` |
| **Permissions** | RBAC via `require_roles()`, five roles: `admin`, `biomedical_engineer`, `ward_nurse`, `transport_staff`, `viewer`. Borrow/return permitted to `admin` + `ward_nurse` + `transport_staff` (+ `biomedical_engineer` for return only). This role set assumes **ward-side staff** perform borrow/return actions themselves — see §10 for why this doesn't match the described workflow. | `app/api/v1/deps.py:46-57`, `app/models/user.py:15-19` (`ALL_ROLES`) |

---

## 2. Workflow Mismatch Analysis

| # | Assumed by current code | Actual workflow | Verdict | Severity |
|---|---|---|---|---|
| M1 | A **named individual borrower is required** (`borrower_name`, `Field(min_length=1)`, and the frontend marks it `required`). | Equipment is dispatched to a **ward/department**, not to a named person. There is no "borrower" in this workflow at all. | **Confirmed mismatch.** This is the single most consequential finding in this review: today, Equipment Pool staff cannot submit a dispatch without typing *something* into a person-name field. In practice this forces either a meaningless placeholder value (corrupting the field's meaning and any future reporting on it) or, worse, staff typing a **patient's name** to satisfy the form — which would silently introduce patient-identifiable data into a system this review is explicitly instructed to keep free of it. | **Critical** |
| M2 | A **due date is required for normal operation** — not literally required by the schema (nullable), but the *overdue* subsystem is built around it existing. | No due-date concept exists; equipment simply stays out until a routine collection round retrieves it. | Schema-level: not a blocking mismatch (field is optional). Behavioral: the *existence* of a whole scheduled job built around this field being populated is a wasted/inapplicable feature for this workflow. | Medium |
| M3 | **"Overdue" is a first-class, actively-computed part of the normal transaction lifecycle** (hourly job, dedicated status value, notification). | No such state exists in the real workflow. | **Confirmed mismatch**, and a dangerous one: the prior backend audit (Finding 14.2, Critical) proved that if `due_at` is ever populated for any reason, the overdue transition **permanently blocks the return of that item** through the normal API. Removing/never-populating `due_at` today only avoids the trigger condition — it does not remove the defect from the code. | **Critical** |
| M4 | Every later ward transfer is tracked. | The system does **not** track transfers at all — no transfer endpoint or concept exists. | This one actually **aligns** with the desired behavior, but only by *absence of a feature*, not by *deliberate protection*. Nothing stops a future change from adding ward-transfer tracking by mistake (e.g., a well-intentioned "update ward" PATCH). | Medium (fragile correctness, not a live bug) |
| M5 | **Return immediately makes equipment available.** | Return must pass through collection → arrival → cleaning → recording, and only *then* becomes available. | **Confirmed mismatch.** `POST /return/{transaction_id}` allows staff to select `condition=available` directly, in one step, with no enforced cleaning gate. This is the second most operationally significant finding. | **Critical** |
| M6 | Borrow and dispatch are treated as equivalent, single, symmetric client actions. | Dispatch is a pool-staff-initiated, ward-directed action with two distinct sub-types (routine round vs. on-demand) that the current model doesn't distinguish. | Largely a terminology/data-model gap rather than a logic error — see §3/§5. | Medium |
| M7 | The destination ward may be silently overwritten. | The original destination must remain historically fixed unless explicitly and auditably corrected. | **Not currently a live bug** (no edit path exists for `ward_id` on an existing transaction), but there is also **no legitimate correction path** — a real data-entry mistake by pool staff has no sanctioned fix today. This is a missing capability, not a wrong assumption already in the code. | High (gap, not defect) |
| M8 | Scheduled rounds are the same thing as due dates. | Rounds are fixed dispatch/collection windows (06:00/11:00/15:00/21:00); due dates are a per-loan deadline concept that doesn't exist here. | **Confirmed mismatch by omission** — no "round" concept exists anywhere in the schema; the only time-based automation present is the due-date/overdue mechanism, which models the wrong thing entirely. | High |
| M9 | Cleaning can be bypassed. | Cleaning must occur before equipment re-enters the available pool, with no exception. | **Confirmed** — same root cause as M5. | **Critical** |
| M10 | Defective equipment can be dispatched. | Must be blocked. | **Not a mismatch — verified correct today.** `borrow_service.borrow()` only permits dispatch when `equipment.status == EquipmentStatus.AVAILABLE`; any other status (including the closest current analogues to "defective," `REPAIR`/`OUT_OF_SERVICE`) is already rejected with `EquipmentNotAvailableError`. This logic is sound and should be preserved unchanged through the terminology/state-model migration recommended below. | **Positive finding — no action needed** |

---

## 3. Recommended Domain Terminology

| Current Term | Recommended Term | Reason | Migration Impact |
|---|---|---|---|
| Borrow / `BorrowTransaction` | **Dispatch** / `DispatchRecord` (or keep table name, rename display labels only) | "Borrow" implies a person-to-person loan; this is a pool-to-ward issuance. | Medium — table/model rename touches every layer (models, schemas, API, frontend); a **display-label-only** rename (keep internal names, change UI copy + docs) is lower-risk and can ship first. |
| Borrower / `borrower_name` | **Remove.** Do not replace with any person-name field. | No individual borrower exists in this workflow; retaining any required person-name field re-creates Finding M1 and risks patient-data leakage. | Low-Medium — requires making `ward_id`/`department_id` required in its place (see §5), and a data-migration decision for any historical rows already populated with placeholder names. |
| Loan | *(not used as a literal term in code today, but implied by "borrow"/"borrower"/"due date")* — replace conceptually with **Dispatch Record**. | Consistency with the rename above. | None beyond the rename itself. |
| Due Date (`due_at`) | **Remove from the MVP-facing workflow.** Do not rename — retire from the dispatch/return UI and stop populating it. | No due-date concept exists in the real operation; keeping it "just in case" is what let Finding 14.2 (Critical) exist undetected. | Low — the column can remain in the schema unused (no destructive migration required), but the API/UI surface that lets a client set it should be removed, and the overdue scheduler job should be disabled. |
| Overdue | **Remove for MVP.** No replacement concept needed. | Same reasoning as above; if "equipment has been out unusually long" is ever wanted as an operational signal, it should be a **computed/derived** indicator (e.g., "days since dispatch"), never a stored state that gates return eligibility. | Low — disable the scheduled job and stop surfacing the status; do not delete the column (cheap to leave dormant). |
| Return | **Return to Pool** (or keep "Return," qualify in UI copy) | "Return" alone is ambiguous given the multi-step collect→clean→ready process; "Return to Pool" clarifies this isn't "returned to the ward" or "returned to the patient." | Low — labeling change only if the two-step model (§6) makes the distinction clear through separate action names instead. |
| Transaction status `"borrowed"` | **`ISSUED`** (or `DISPATCHED`) | Matches renamed workflow. | Medium — enum value rename touches DB check/constraint, API contract, frontend status badges. |
| Transaction status `"returned"` | **`CLOSED`** or split into two states reflecting the two-step return (§4/§6) | Matches renamed workflow and the recommended two-operation return model. | Medium — same as above. |
| Transaction status `"overdue"` | **Remove** | See above. | Low. |
| `pickup_location_id` / `dropoff_location_id` | **Reconsider necessity; likely remove for MVP** in favor of the single `ward_id`/`department_id` pair. | These add a third "where" concept on top of `ward_id` and `equipment.current_location_id`, none of which the real workflow asks for. One clearly-scoped "receiving ward/department" field is sufficient. | Low-Medium — dropping unused columns from the write path is low risk; a full schema removal is a later-phase cleanup. |
| `equipment.current_location_id` (Location) | **Rename/relabel or remove from user-facing views for MVP.** | Its name ("current location") implies live tracking the system does not do (§7). If retained internally, it must never be displayed as "current location" without a caveat. | Low if UI-copy-only; Medium if the column itself is repurposed. |
| N/A (new concept) | **Receiving Ward** (required field, replaces the role `borrower_name` played) | Names what the real workflow actually needs recorded. | New required field — see §5. |
| N/A (new concept) | **Routine Round** / **On-Demand Request** (dispatch type) | Names the two dispatch types the real workflow distinguishes; currently absent entirely. | New field — see §5. |
| N/A (new concept) | **Pending Cleaning** / **Ready for Dispatch** (equipment states) | Names the two-step return outcome recommended in §4/§6. | New states — see §4. |

---

## 4. State Machine Review

### 4.1 Evaluation of the proposed 6-state model

The proposed model (`AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `RETURNED_PENDING_CLEANING`, `CLEANING`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`) is **not accepted as-is**. Specifically:

- **`RETURNED_PENDING_CLEANING` and `CLEANING` should be merged into one state for MVP.** The stated workflow does not require the system to distinguish "physically back but not yet started cleaning" from "actively being cleaned" — nobody needs to query that distinction operationally, and splitting it adds a transition, a permission check, and a test case for no workflow benefit. Recommend a single `PENDING_CLEANING` (or `RETURNED_PENDING_CLEANING`) state covering both. Revisit only if a later phase wants cleaning-turnaround-time as a KPI.
- **`UNAVAILABLE_DEFECTIVE` and `DECOMMISSIONED` are both justified and should be kept** — they map directly to the explicit MVP requirement "Blocking Defective and Decommissioned equipment from dispatch," and today's code already enforces the *shape* of this correctly (only `AVAILABLE`-equivalent status permits dispatch — §2, M10).

### 4.2 Recommended minimum equipment state model (5 states)

| State | Meaning | Allowed entry from | Allowed exit to | Who may transition | Dispatch permitted? | MVP? |
|---|---|---|---|---|---|---|
| **AVAILABLE_AT_POOL** | At the pool, ready to be issued. | `PENDING_CLEANING` (via cleaning confirmation); `UNAVAILABLE_DEFECTIVE` (via repair confirmation, if repair tracking exists); new registration. | `ISSUED_TO_WARD` (dispatch); `UNAVAILABLE_DEFECTIVE` (fault discovered while sitting at pool). | System (on cleaning confirm); Equipment Pool Staff / Administrator (mark defective). | **Yes** | Yes |
| **ISSUED_TO_WARD** | Currently dispatched; first destination ward recorded. | `AVAILABLE_AT_POOL` (dispatch). | `PENDING_CLEANING` (collection/return recorded). | Equipment Pool Staff (dispatch, return). | **No** | Yes |
| **PENDING_CLEANING** | Physically back at the pool; not yet confirmed ready for reuse. | `ISSUED_TO_WARD` (return recorded). | `AVAILABLE_AT_POOL` (cleaning confirmed — ready); `UNAVAILABLE_DEFECTIVE` (fault discovered during cleaning/inspection). | Equipment Pool Staff (confirm cleaning); Equipment Pool Staff / Administrator (mark defective). | **No** | Yes |
| **UNAVAILABLE_DEFECTIVE** | Known faulty; withheld from the pool. | `AVAILABLE_AT_POOL`, `PENDING_CLEANING`, `ISSUED_TO_WARD` (on discovery) — **not** a normal-workflow exit, an exception path from any state where a fault can be discovered. | `AVAILABLE_AT_POOL` (repaired and returned to service — outside this MVP's scope if full repair-tracking isn't built, but the *state transition itself* should exist even if repair workflow detail doesn't); `DECOMMISSIONED` (written off). | Equipment Pool Staff / Administrator / Biomedical Engineer. | **No** | Yes |
| **DECOMMISSIONED** | Permanently retired; terminal state. | `UNAVAILABLE_DEFECTIVE` (written off); direct registration-time entry (for already-retired legacy inventory rows being imported for record-keeping only). | *(none — terminal)* | Administrator only. | **No** | Yes |

### 4.3 Transaction (dispatch record) state model

Recommend collapsing the current three transaction states to **two** for MVP:

| State | Meaning | MVP? |
|---|---|---|
| **OPEN** | Dispatched, not yet returned. | Yes |
| **CLOSED** | Returned to pool and recorded (cleaning status tracked separately on the *equipment* record, not the transaction). | Yes |

Drop `"overdue"` entirely from the transaction state machine for MVP (§2 M3, §3). If "this item has been out a long time" is wanted as an operational signal later, implement it as a **read-only computed value** (e.g., `days_since_dispatch`) displayed in a report — never as a stored status that a return-eligibility check can be gated on, which is exactly the mechanism that produced the Critical bug in the prior backend audit.

### 4.4 Invalid transitions that must be rejected

| Attempted transition | Why it must be rejected |
|---|---|
| `AVAILABLE_AT_POOL` → `ISSUED_TO_WARD` when the underlying equipment is `UNAVAILABLE_DEFECTIVE` or `DECOMMISSIONED` | Defective/decommissioned equipment must never be dispatched (already correctly enforced today — §2 M10 — must be preserved through migration). |
| `ISSUED_TO_WARD` → `AVAILABLE_AT_POOL` directly, skipping `PENDING_CLEANING` | This is the cleaning-bypass defect (§2 M5/M9) — must become structurally impossible, not just discouraged. |
| `PENDING_CLEANING` → `ISSUED_TO_WARD` (dispatching before cleaning is confirmed) | Equipment must not leave the pool again until cleaning is confirmed. |
| Second `ISSUED_TO_WARD` transition while already `ISSUED_TO_WARD` | Duplicate dispatch — already correctly blocked today by `idx_tx_one_active_borrow` (schema audit, positive finding); must be preserved. |
| Second `PENDING_CLEANING`→`AVAILABLE_AT_POOL` confirmation on an item already `AVAILABLE_AT_POOL` | Duplicate cleaning-confirmation — **not currently guarded**; this is the new-risk surface introduced by splitting return into two steps (see §6, §9). |
| `DECOMMISSIONED` → anything other than staying `DECOMMISSIONED` | Terminal state; any reactivation must be an explicit, separately-authorized, audited exception process, not a normal transition — recommend treating any such need as Out of Scope for MVP rather than building a "reactivate" transition casually. |

---

## 5. Dispatch Workflow Review

### 5.1 Routine Round Dispatch — minimum required data

| Field | Required? | Currently supported? | Evidence |
|---|---|---|---|
| Round designation (06:00 / 11:00 / 15:00 / 21:00) | **Yes** | **No** — no field exists. | N/A — gap |
| Receiving ward | **Yes** | Present but **optional** (`ward_id: str \| None`) — must become required. | `app/schemas/transaction.py:12` |
| ME Code | **Yes** | Not present as a distinct field — `asset_number` is used ambiguously in its place (§8). | `app/schemas/transaction.py:9-10` (`equipment_qr`/`equipment_id`) |
| Recorded-by user | **Yes** | Present (the authenticated actor is captured as `borrower_user_id`, misleadingly named). | `app/api/v1/borrow.py:35` |
| Dispatch timestamp | **Yes** | Present, server-set. | `app/models/transaction.py:30` (`borrowed_at`) |

**Not required:** a named individual borrower (§2 M1) — remove.

### 5.2 On-Demand Dispatch — minimum required data

| Field | Required? | Currently supported? |
|---|---|---|
| Requesting ward/department | **Yes** | Same field as above would serve this role, but there's no distinction today between "routinely allocated" and "on-demand requested." |
| Request timestamp (when the ward phoned in) | **Not required for MVP** — recommend deferring. | Not supported. Adds real-world value only if the pool wants to measure call-to-dispatch response time; not essential to prevent any of the named risks (duplicate dispatch, defective dispatch, ward-recording accuracy). Treat as Later Phase. |
| Dispatch timestamp | **Yes** | Present. |
| ME Code | **Yes** | See §5.1. |
| Recorded-by user | **Yes** | Present. |
| Optional request note (e.g., "OPD Heart requested via phone, requested by [role/name of caller if known]") | **Optional, free text, no patient identifiers** | Present (`notes`), reasonable to reuse as-is. |

**Explicitly excluded per instructions:** no patient name, MRN, or bed number should ever be captured in any dispatch field — the free-text `notes` field should carry an explicit UI hint against entering patient-identifiable information, since it's the one field most likely to be misused for that purpose once `borrower_name` is removed.

### 5.3 The minimal combined dispatch-type field

Recommend one new required field: **dispatch type** — `ROUTINE_ROUND` or `ON_DEMAND` — plus, when `ROUTINE_ROUND`, a required **round designation** (one of the four fixed times). This is the single piece of new schema needed to represent both dispatch types described in the source workflow; everything else (ward, ME Code, recorded-by, timestamp) is either already present or already identified above.

---

## 6. Return and Cleaning Workflow Review

### 6.1 Recommended sequence

Given the ambiguity noted in **A7**, and given that "Equipment marked available before cleaning is completed" is explicitly named as a risk the review must assess, the recommendation is:

**Two separate digital operations, both simple, both fast:**

1. **Return Received** — Equipment Pool staff records that the item physically arrived back at the pool (collected from ward → arrived at pool are treated as one combined real-world event for MVP purposes; the system does not need to model "collected" and "arrived" as two separate digital steps, since both happen before the item is in the pool staff's hands to log anything). Transitions `ISSUED_TO_WARD` → `PENDING_CLEANING`.
2. **Cleaning Confirmed / Ready for Dispatch** — A distinct action, performed after physical cleaning, transitions `PENDING_CLEANING` → `AVAILABLE_AT_POOL`.

**Why not one combined operation:** collapsing "return received" and "ready for dispatch" into a single button is exactly what today's system does (`condition=available` in one step), and it is exactly what produces the cleaning-bypass risk (§2 M5/M9). Two operations make the bypass **structurally impossible** rather than dependent on staff discipline under time pressure — which matters most during the four daily collection rounds when staff are moving fast.

**Why not a fully "configurable" (site-configurable one-vs-two-step) design:** configurability here would let cleaning-bypass silently re-appear via a settings toggle, which contradicts the stated non-negotiable requirement that cleaning cannot be bypassed. Recommend hard-coding two steps for MVP; do not expose a "combine into one step" configuration option.

### 6.2 Explicit risk assessment

| Risk | Assessment | Evidence / Reasoning |
|---|---|---|
| **Duplicate return** | **Confirmed unresolved risk**, carried forward from the prior backend audit. | Backend Audit Finding 14.1 (Critical) — no DB-level guard on the return path, unlike dispatch. Applies directly and unchanged to the renamed "Return Received" step. |
| **Concurrent return** | Same finding — a race, not a sequencing issue. | Backend Audit Finding 14.1. |
| **Return of equipment with no open dispatch** | **Reasonably handled today.** | The frontend resolves the specific open transaction via `findActiveTransaction()` before allowing return input, and surfaces a clear "no open loan found" message if none exists (`ReturnPage.tsx`). Recommend keeping this pattern, but formalizing it as a dedicated backend lookup rather than a client-side filter over the full active-transaction list (currently `listActiveBorrows()` returns *all* open items and the frontend filters in JavaScript — inefficient at scale, not a correctness bug today given the one-open-dispatch-per-equipment guarantee already holds). |
| **Return to the wrong transaction** | **Low risk today**, but worth preserving deliberately. | Because only one open dispatch per equipment can exist at a time (enforced by `idx_tx_one_active_borrow`), there is at most one valid candidate transaction per equipment — "wrong transaction" isn't structurally possible today as long as that invariant holds. This must be explicitly re-verified once the return flow is split into two steps (§9). |
| **Cleaning bypass** | **Confirmed, must fix.** | §2 M5/M9. Resolved by the two-step model in §6.1, **provided** the new "Cleaning Confirmed" step gets the same duplicate/concurrency protection as any other state transition (see §9). |
| **Equipment marked available before cleaning completed** | Same root cause as cleaning bypass. | Same fix. |

---

## 7. Ward Recording Rules

| Rule | Current state | Recommendation |
|---|---|---|
| Original destination remains historically preserved | **True today only by omission** — no edit path exists for `ward_id` on an existing transaction. Not an explicit, declared guarantee. | Make immutability explicit: the standard update path must never be able to touch a dispatch record's ward; any change must go through a distinct, named "Correct Destination" action (see next row), never a generic field edit. |
| Subsequent patient transfers are not modeled | **True today, correctly** — no transfer feature exists. | Keep it this way **by explicit design decision**, documented, so a future contributor doesn't "helpfully" add ward-transfer tracking as a natural-seeming extension of the ward field that already exists. |
| Current location not falsely presented as real-time physical location | **Not currently addressed — a real gap.** | The equipment record's `current_location_id` field name literally claims to represent "current location," but nothing keeps it synchronized with dispatch activity, and it is a *third*, separate concept from the transaction's `ward_id`. This is actively misleading as currently named/modeled. |
| Correction of an incorrectly selected ward is audited | **Not implemented.** No endpoint exists to correct a transaction's recorded ward. | Add a narrow, role-gated (Administrator or Equipment Pool Staff, per §10), fully-audited "Correct Destination Ward" action — distinct from any general edit capability, writing a clear before/after audit entry every time it's used. |
| Historical transactions remain immutable except through controlled correction | **Currently: fully immutable via total absence of any edit path** (an accidental, blunt version of the right idea) — but this also means there is **no recourse** for a genuine staff data-entry mistake today, other than a direct database edit outside the application (which is worse — unaudited). | Replace "immutable by omission" with "immutable except via the one audited correction action" above. |

### 7.1 Recommended UI labeling

Avoid any label implying real-time tracking. Recommended copy:

- Field label: **"Receiving Ward (recorded at dispatch)"** — not "Ward," not "Location," not "Current Location."
- Detail-view caption under the ward field: *"This reflects where the equipment was first sent. The Equipment Pool does not track the patient's or equipment's later movement between wards."*
- Rename or hide `equipment.current_location_id`'s "current location" label wherever it currently appears in the frontend, since it is not kept live and is a different concept from the per-dispatch ward field (§3, §8).

---

## 8. Inventory Import and Identifier Review

### 8.1 The central finding

The current schema has exactly **two** identifier-shaped columns on `Equipment` — `asset_number` (unique, required) and `serial_number` (unique, nullable) — against the hospital's **four** distinct real-world identifiers (ME Code/ID CODE, Item No., Asset ID, Serial Number). Today's `asset_number` column is functioning *as if* it were the ME Code (it drives the QR payload and the primary uniqueness constraint — `app/services/qr_service.py`, `app/models/equipment.py:33`), but its **name** suggests it was intended to represent Asset ID. This naming collision must be resolved before any import mapping is built, or ME Code, Asset ID, and Item No. will end up silently conflated into one field.

### 8.2 Recommended field mapping (all pending confirmation per A1–A4)

| Source inventory field | Recommended schema treatment | Uniqueness | Nullable | Notes |
|---|---|---|---|---|
| ID CODE (assumed = ME Code) | **New, dedicated column** — becomes the primary user-facing search/scan key. | Unique, required, indexed | No | Must be stored as `VARCHAR`, never numeric (leading-zero preservation — e.g. a code beginning `00...`); compared case-normalized (recommend uppercase-on-write) to prevent `BCM02719` vs `bcm02719` being treated as different devices — this exact risk was already flagged generically in the prior schema audit (Finding 9.2) and applies directly here. |
| Item No. | New column, plain metadata. | **Not unique** (per assumption A2 — likely a sheet line number) | Yes | Do not use for lookup or dispatch. |
| Asset ID | New column, distinct from ME Code. | Unique if genuinely hospital-wide unique (needs confirmation); otherwise plain metadata. | Yes, pending confirmation | Today's `asset_number` should **not** continue silently standing in for this — rename/repurpose is needed to avoid ongoing confusion (§3). |
| Serial Number | **Already correctly modeled** — no change needed. | Unique, nullable | Yes | Positive finding, unchanged. |
| Equipment Name | Already modeled (`equipment_name`). | Not unique | No | No change. |
| Manufacturer | Schema currently has `brand`, not `manufacturer` — naming mismatch. | N/A | Yes | Recommend renaming/aliasing for import-mapping clarity; low severity, cosmetic. |
| Model | Already modeled (`model`). | N/A | Yes | No change. |
| Location (source) | **Do not conflate with `ward_id`.** Meaning must be confirmed (A3) before deciding whether this maps to "home/routine ward" (a new, distinct field) or is simply informational metadata not used by the dispatch workflow at all. | N/A | Yes | High-risk conflation point if mis-mapped — flagged explicitly. |
| Receive Date / Register Date / Purchase Year | New plain metadata columns (date/year types). | N/A | Yes | Not used by the dispatch/return workflow; needed only to satisfy the MVP's "import using existing inventory fields" requirement as pure record-keeping. |
| Asset Status (source) | Mapped to the target 5-state equipment model (§4), **with the original raw source value preserved alongside** the mapped value so nothing is silently lost on import. | N/A | No (import should reject rows with unmappable status rather than guessing) | Actual source values are unknown (A4) — the mapping table below is illustrative only. |

### 8.3 Illustrative status mapping (pending A4 confirmation)

| Source `Asset Status` (assumed examples) | Target MVP state |
|---|---|
| Active / In Use / In Service | `AVAILABLE_AT_POOL` (if not currently dispatched) |
| Defective / Faulty / Under Repair | `UNAVAILABLE_DEFECTIVE` |
| Decommissioned / Disposed / Written Off | `DECOMMISSIONED` |
| *(anything unrecognized)* | **Reject the row / flag for manual review** — do not guess. |

### 8.4 Search behavior

The existing search implementation (`equipment_crud.search()`, `ILIKE` partial match across `asset_number`/`serial_number`/`equipment_name`/`qr_code_value`) is a reasonable foundation. Recommend: ME Code scan/search should resolve via an **exact-match** lookup (mirroring the existing, correctly-designed `get_by_qr()` pattern, which already does an exact lookup — `app/crud/equipment.py:18-22`), re-pointed at the new dedicated ME Code column rather than `asset_number`. Free-text search across name/other identifiers can remain fuzzy for the general equipment list.

### 8.5 Import validation (net-new capability — none exists today)

Recommend, for MVP: reject rows with a missing or duplicate ME Code; on ME Code collision with an already-registered device, require an explicit "update existing record" mode rather than silently overwriting; produce a per-row success/failure report rather than an all-or-nothing import. These are process recommendations, not implementation detail — no code is proposed here.

---

## 9. Data Integrity and Concurrency

Directly relating each required control to the prior two audits, per the task instruction:

| Control | Status | Relation to prior audits |
|---|---|---|
| Only one open dispatch per equipment item | **Already satisfied.** | Database Audit §4.5 (positive finding) — `idx_tx_one_active_borrow` partial unique index. Carries forward correctly under the renamed "dispatch" workflow with no change needed. |
| Equipment cannot be dispatched concurrently twice | **Already satisfied.** | Same control as above; also independently confirmed safe in the Backend Audit's concurrency analysis. |
| Equipment cannot be returned concurrently twice | **Not satisfied — Critical, unresolved.** | Backend Audit Finding 14.1 (Critical, double-return race). **Now more consequential**, because §6 recommends splitting return into two steps — both new steps (Return Received, Cleaning Confirmed) need this same class of protection, or the risk simply moves rather than disappears. |
| Defective or decommissioned equipment cannot be dispatched | **Already satisfied.** | §2 M10 (positive finding). Must be explicitly preserved as the state model migrates from 8 statuses to the recommended 5 (§4) — the underlying rule ("only the pool-ready state permits dispatch") must not be lost in the rename. |
| Dispatch, status change, and audit log committed atomically | **Already satisfied.** | Backend Audit — the "Borrow succeeds but Audit fails" hypothesis was explicitly checked and disproven; all three writes share one commit boundary. |
| Return, cleaning/status change, and audit log committed atomically | **Satisfied for today's single-step return; must be re-verified for the recommended two-step return.** | New analysis: each of the two new steps needs its own atomic commit (return-received + audit; cleaning-confirmed + audit), **and** the sequence itself needs a guard against "cleaning confirmed" being callable on an item that was never marked "return received" (an analogous check to the existing `tx.status != TX_STATUS_BORROWED` guard, but for the new intermediate state). |
| Retry requests do not create duplicate transactions | **Partially satisfied.** | Backend Audit's Business Workflow analysis — same-equipment retries are naturally blocked by the equipment-status check (a happy accident of the state design, not a deliberate idempotency mechanism), but the documented `Idempotency-Key` header is unimplemented. Relevant here because phone-based on-demand requests, taken under time pressure, are a realistic retry scenario. |
| Transaction numbers are concurrency-safe | **Not satisfied — High, unresolved, and newly elevated in urgency.** | Backend Audit Finding 14.3 (`COUNT`+`LIKE` race in `generate_transaction_no()`). The real operating pattern described in this review — **many simultaneous dispatches at the same four fixed clock times, four times a day** — is close to a worst-case trigger condition for exactly this bug. This review elevates its practical priority (see §13). |

---

## 10. Role and Permission Review

The current five-role model (`admin`, `biomedical_engineer`, `ward_nurse`, `transport_staff`, `viewer`) assumes ward-side staff use the system directly to borrow/return equipment themselves. Per the described workflow (wards only telephone requests; all system interaction — dispatch, collection, cleaning confirmation — is performed by **Equipment Pool staff**), this role model does not match. Recommend collapsing to the three roles the prompt itself proposes:

| Capability | Administrator | Equipment Pool Staff | Read-Only / Supervisor |
|---|---|---|---|
| Import or register equipment | ✅ | ❌ (or ✅ if the pool self-manages its own master data day-to-day — assumption-dependent, lean toward Admin-only for MVP to keep the identifier/import rules in §8 tightly controlled) | ❌ |
| Dispatch equipment (routine + on-demand) | ✅ | ✅ | ❌ |
| Receive returns | ✅ | ✅ | ❌ |
| Confirm cleaning/readiness | ✅ | ✅ | ❌ |
| Correct a destination ward | ✅ | ✅ (with mandatory audit note) | ❌ |
| Mark equipment defective | ✅ | ✅ | ❌ |
| Reactivate equipment (out of `UNAVAILABLE_DEFECTIVE`) | ✅ | ❌ (recommend Admin-only gate for MVP, given no repair-tracking workflow exists to substantiate the decision) | ❌ |
| View history | ✅ | ✅ | ✅ |
| Export reports | ✅ | ✅ | ✅ |
| Manage users | ✅ | ❌ | ❌ |

**Note:** `biomedical_engineer`, `ward_nurse`, and `transport_staff` as currently coded have no clear place in this workflow as described — they should be considered **out of scope for this MVP's role model** (they may be legitimate roles in a *different* part of a broader hospital system, but nothing in the described Equipment Pool workflow calls for ward-initiated actions). This is a recommendation to simplify, not a claim that these roles are wrong in general.

---

## 11. MVP Gap Analysis

| Feature | Current Implementation | Required Workflow | Gap | Severity | MVP / Later | Recommended Action |
|---|---|---|---|---|---|---|
| Named borrower | Required field, free text | No borrower concept | Field exists and is required where it shouldn't | Critical | MVP | Remove requirement; do not replace with any person-name field |
| Receiving ward | Optional | Required, primary data point | Wrong cardinality | Critical | MVP | Make required |
| Dispatch type (routine/on-demand) | Not modeled | Two distinct types required | Missing entirely | High | MVP | Add dispatch-type field |
| Round designation (06/11/15/21) | Not modeled | Required for routine dispatches | Missing entirely | High | MVP | Add round field (fixed enum) |
| ME Code as distinct identifier | Not modeled — conflated with `asset_number` | Required, primary scan/search key, distinct from Item No./Asset ID/Serial Number | Identifier model is incomplete | Critical | MVP | Add dedicated ME Code column; resolve naming collision with `asset_number` |
| Cleaning enforcement before availability | Bypassable in one step | Mandatory, no exceptions | Structural gap | Critical | MVP | Two-step return model (§6) |
| Return concurrency safety | No DB-level guard | Must prevent duplicate/concurrent return | Confirmed unresolved defect | Critical | MVP | Apply equivalent of the borrow-side unique-index/locking pattern |
| Overdue mechanism | Active, first-class | Not part of the workflow at all | Actively harmful (blocks legitimate returns) | Critical | MVP (removal is MVP-blocking) | Disable scheduler job; remove `due_at`/overdue from API surface |
| Ward-correction workflow | Not implemented | Required, audited | Missing capability | High | MVP | Add narrow, audited correction action |
| Ward-immutability guarantee | Accidental (no edit path exists) | Explicit, declared guarantee | Fragile, not enforced by design | Medium | MVP | Formalize as a stated invariant; ensure no future generic edit path can touch it |
| "Current location" labeling | Misleading (`current_location_id` implies live tracking) | Must not imply real-time location | Mislabeled field | Medium | MVP (labeling) / Later (data model cleanup) | Relabel UI; consider removing/repurposing field |
| Duplicate `pickup_location_id`/`dropoff_location_id`/`ward_id`/`current_location_id` concepts | Four overlapping "where" fields | One clear "receiving ward" concept | Data-model redundancy/confusion | Medium | Later phase (cleanup) | Simplify to one field for MVP writes; formal schema cleanup later |
| Inventory import/registration by existing fields | Not implemented at all — single-record creation only | Required for MVP | Missing entirely | High | MVP | Build import/registration using the field mapping in §8 |
| Transaction-number concurrency safety | Racy `COUNT`+`LIKE` pattern | Must be safe under 4x-daily concurrent-round bursts | Confirmed unresolved defect | High | MVP | Replace with a proper sequence (carried from Backend Audit 14.3, elevated priority) |
| Audit trail completeness for user/role management | Not audited at all | Required per stated compliance posture | Confirmed gap (carried from Backend Audit 12.1) | Critical | MVP | Add audit logging to user-management endpoints |
| Role model (ward-initiated actions) | 5 roles assuming ward-side system use | 3 roles, pool-staff-driven | Mismatch | Medium | MVP | Adopt the 3-role model in §10 |
| Request timestamp for on-demand calls | Not supported | Optional, not essential | Minor gap | Low | Later phase | Defer |
| Idempotency-Key support | Documented, not implemented | Useful for phone/manual retry safety | Documented-but-missing feature | Medium | Later phase | Defer; equipment-status check already provides partial protection |
| PM/Calibration statuses in equipment state model | Present (`pm`, `calibration` statuses) | Explicitly out of scope for this MVP | Scope creep beyond stated MVP | Low | Later phase / out of scope | Hide from Equipment Pool workflow UI; do not build against them for this MVP |

---

## 12. Acceptance Criteria (MVP)

Written as testable Given/When/Then statements.

**Dispatch by ME Code**
- Given a piece of equipment registered with a valid ME Code, when Equipment Pool staff scans or enters that ME Code, then the system resolves the correct equipment record via an exact match.
- Given an unrecognized ME Code, when scanned/entered, then the system returns a clear "equipment not found" response and does not create a dispatch record.

**Routine round selection**
- Given a dispatch is being recorded, when the staff member selects a round, then only the four fixed values (06:00, 11:00, 15:00, 21:00) are selectable — no free-text or arbitrary time is accepted for a routine dispatch.

**On-demand request**
- Given a ward without a routinely allocated device calls in, when staff records the dispatch as on-demand, then no round selection is required, and the dispatch is distinguishable from routine dispatches in history/reporting.

**First ward recording**
- Given equipment is dispatched to Ward A, when the same equipment is later (hypothetically) moved to Ward B by clinical staff outside the Equipment Pool's knowledge, then the system continues to show Ward A as the recorded destination — no field anywhere is silently updated to Ward B.

**Duplicate dispatch prevention**
- Given equipment is already in `ISSUED_TO_WARD` state, when a second dispatch is attempted for the same equipment, then the system rejects it with a clear "not available" response and no second dispatch record is created.
- Given two dispatch requests for the same equipment arrive concurrently, when both are processed, then exactly one succeeds and one is rejected — never both succeeding.

**Defective equipment block**
- Given equipment is in `UNAVAILABLE_DEFECTIVE` or `DECOMMISSIONED` state, when a dispatch is attempted, then it is rejected regardless of round type or requesting ward.

**Return processing**
- Given equipment is `ISSUED_TO_WARD`, when Equipment Pool staff records "Return Received," then the equipment transitions to `PENDING_CLEANING` and is **not** yet available for dispatch.

**Duplicate return prevention**
- Given a "Return Received" has already been recorded for a dispatch, when a second "Return Received" is attempted for the same dispatch, then it is rejected.
- Given two "Return Received" or two "Cleaning Confirmed" actions are submitted concurrently for the same equipment, then exactly one succeeds.

**Cleaning/readiness control**
- Given equipment is `PENDING_CLEANING`, when a dispatch is attempted, then it is rejected — equipment cannot be issued directly out of `PENDING_CLEANING`.
- Given equipment is `PENDING_CLEANING`, when "Cleaning Confirmed" is recorded, then the equipment transitions to `AVAILABLE_AT_POOL` and only then becomes dispatchable.

**Audit trail**
- Given any dispatch, return, cleaning confirmation, ward correction, defective marking, or user/role change occurs, then a corresponding audit record is created capturing who, what, and when, with no exceptions across any of these action types.

**History search**
- Given a completed dispatch/return cycle, when searching by ME Code, ward, or date range, then the full transaction history (dispatch type, round, ward, timestamps, recorded-by, return timestamp, cleaning-confirmation timestamp) is retrievable.

**Concurrent requests**
- Given the four daily routine rounds create simultaneous multi-equipment dispatch bursts, when many dispatches are submitted within the same short window, then no two dispatch records share the same transaction/reference number, and no dispatch is silently dropped or duplicated.

---

## 13. Final Priority Plan

### P0 — Must fix before any operational pilot

| Item | Files/Modules | DB Impact | API Impact | Frontend Impact | Test Impact | Audit Dependency |
|---|---|---|---|---|---|---|
| Fix double-return race | `app/services/borrow_service.py`, `app/models/transaction.py` | Additive (version column or conditional-update logic) | `POST /return/{id}` behavior change | Return flow error handling | New concurrency test | Backend Audit Finding 14.1 (Critical) |
| Remove overdue mechanism from active use | `app/worker/scheduler.py`, `app/services/borrow_service.py` (return-eligibility check) | None required (leave `due_at` dormant) | Stop accepting/surfacing `due_at`/overdue in relevant endpoints | Remove overdue UI, if any | Update/remove overdue tests | Backend Audit Finding 14.2 (Critical) |
| Remove required `borrower_name`; make `ward_id` required | `app/schemas/transaction.py`, `app/services/borrow_service.py`, `app/api/v1/borrow.py`, `frontend/src/pages/BorrowPage.tsx` | None (field already exists) | `BorrowRequest` contract change | Form field changes | Update borrow tests | This review, §2 M1 |
| Fix `generate_transaction_no()` race | `app/crud/transaction.py` | Additive (DB sequence) | None (internal only) | None | New concurrency test | Backend Audit Finding 14.3 (High → elevated to P0 given the 4x-daily concurrent-round pattern this review confirms is real) |
| Add audit logging to user/role management | `app/api/v1/users.py` | None | None (internal write only) | None | New audit-coverage test | Backend Audit Finding 12.1 (Critical) |
| Add ME Code as a distinct, unique, required identifier | `app/models/equipment.py`, `app/schemas/equipment.py`, `app/crud/equipment.py`, `app/services/qr_service.py` | New column + migration + backfill | `Equipment` schema change | Search/scan UI re-pointed | Update equipment CRUD tests | Database Audit (identifier findings), this review §8 |

### P1 — Must complete for MVP

| Item | Files/Modules | DB Impact | API Impact | Frontend Impact | Test Impact | Audit Dependency |
|---|---|---|---|---|---|---|
| Split return into "Return Received" + "Cleaning Confirmed" | `app/services/borrow_service.py`, `app/api/v1/borrow.py` | Possible new equipment state column values | Two new/changed endpoints | Two-step return UI | New workflow tests | This review §6; depends on P0 return-race fix being generalized to both new steps |
| Add dispatch type (routine/on-demand) + round designation | `app/models/transaction.py`, `app/schemas/transaction.py` | New columns | `BorrowRequest` contract change | Dispatch-type/round selector UI | New tests | This review §5 |
| Reduce equipment state model to the recommended 5 states, remapped | `app/models/equipment.py` | Enum/constraint changes | Status-related endpoints | Status badges/labels | Update all status-dependent tests | This review §4; Database Audit enum-usage findings |
| Add ward-correction action (audited) | `app/api/v1/borrow.py` or new endpoint, `app/crud/transaction.py` | None | New endpoint | New admin/staff UI action | New tests | This review §7 |
| Relabel "current location"/ward fields in UI | `frontend/src/pages/EquipmentDetailPage.tsx`, related components | None | None | Copy changes only | None | This review §7 |
| Build inventory import/registration | New module(s) under `app/services/`, `app/api/v1/` | New columns (Item No., Asset ID, Manufacturer alias, dates) + import logic | New import endpoint | New import UI | New import tests | This review §8 (pending A1–A4 confirmation) |
| Adopt 3-role MVP model | `app/models/user.py`, `app/api/v1/deps.py`, seed/role data | Role data change | Permission checks per §10 | Role-dependent UI | Update RBAC tests | This review §10 |
| Fix unhandled `IntegrityError`/`ValueError` on create/return paths | `app/api/v1/equipment.py`, `users.py`, `master_data.py`, `borrow_service.py` | None | Error-response shape fix | Error message handling | New error-path tests | Backend Audit Finding 9.1 (High) — directly relevant given duplicate-ME-Code registration attempts will be common |

### P2 — Useful after MVP stabilization

| Item | Notes |
|---|---|
| Request timestamp for on-demand calls | Deferred per §5.2 — nice-to-have audit granularity, not workflow-blocking. |
| `Idempotency-Key` support for offline/retry safety | Documented but unimplemented; equipment-status check already provides partial protection. |
| Data-model cleanup: consolidate `ward_id`/`pickup_location_id`/`dropoff_location_id`/`equipment.current_location_id` | Functional gap is closed at the UI/labeling level in P1; full schema consolidation is a larger, lower-urgency migration. |
| Fix N+1 query in scheduler notification jobs, dashboard `COUNT(*)` cost, connection-pool/SSE session-lifetime issue | Carried from Backend Audit §5.2, §16.1, §17.1 — real, but not specific to the workflow-correctness scope of this review; still recommended before any high-concurrency pilot. |
| Reactivation-from-defective workflow detail | Only the state *transition* is recommended for MVP (§4); the surrounding repair-confirmation process detail is Later Phase. |

### Out of Scope (explicitly excluded for this phase, per instructions)

- MEMS integration
- Patient tracking, bed tracking
- Tracking ward-to-ward transfers after first dispatch
- Full maintenance management (PM)
- Full calibration management
- Recall management
- Hospital-wide asset lifecycle management
- Any reactivation-of-decommissioned-equipment workflow beyond the bare state transition
- Any per-ward or per-equipment-type configurability of the round schedule (assumption A6 — flagged, not built)

---

No code, migrations, or configuration were modified as part of this review. All findings above are traced to specific source locations verified this session; items marked as assumptions (A1–A7) require hospital confirmation before implementation planning proceeds.
