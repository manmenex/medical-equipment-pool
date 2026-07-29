# Roadmap PR17 — Operational Reports: Design Proposal

**Status:** Design only. Nothing in this document has been implemented. No backend code, frontend code, Alembic migration, database schema change, or API modification was written to produce it.
**Repository:** Medical Equipment Pool. This is **not** MEMS and **not** Recall Monitor — no coupling to either system is introduced or assumed anywhere below.
**Baseline investigated:** `a572a7a81a4b57f0bce8e65990598b1b3f034c77` — squash commit of GitHub PR #62 (Roadmap PR16 governance sync), on branch `claude/medical-equipment-pool-0c7fz0`. Roadmap PR16 (Reporting Foundation, all four Implementation Slices) is fully merged at this baseline.
**Governing instruction:** DESIGN ONLY. Produce the minimum design documentation required for an independently reviewable PR17 Design PR. No implementation, no migration, no API change, no existing-file modification.

---

## 1. Objective

Design Roadmap PR17 — the first operational reporting package: **Receive Report**, **Issue Report**, and **Equipment Verify Checklist Report**. PR17 builds directly on the completed Reporting Foundation (Roadmap PR16): `business_date`/`shift` derivation, the `dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` computed fields on `TransactionOut`, and `GET /transactions`'s `business_date_from`/`business_date_to`/`shift`/`event` filters. This document treats all of that as authoritative and does not redesign any of it (§8).

These are **operational reports** for hospital staff doing daily work — not BI, not analytics, not a dashboard (§22, Out of Scope).

---

## 2. Current Foundation (Authoritative Inputs)

Documents and implementation areas inspected and treated as authoritative for this design, in the order consulted:

| Area | Source | What it established |
|---|---|---|
| Roadmap PR17 scope (authoritative) | `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 7 (`#### PR17 — Operational reports`) | Objective: "Provide Receive, Issue, and Equipment Verify Checklist reports, filterable by date and shift." Dependency: PR16. Acceptance criterion: "Each report uses the same reporting metadata and presents consistent date/shift filtering." PR18 (export/print output) is explicitly the *next* PR, not this one. |
| Reporting Foundation (must not be redesigned) | `docs/design/PR16_REPORTING_FOUNDATION_PLAN.md`, `backend/app/core/reporting_time.py`, `backend/app/models/transaction.py` (`dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` `@property`s), `backend/app/schemas/transaction.py` (`TransactionOut`), `backend/app/api/v1/transactions.py`, `backend/app/crud/transaction.py::search()` | `business_date`/`shift` are computed, never persisted, from `borrowed_at` (dispatch) or `returned_at` (receipt, `None` until received). `GET /transactions` already accepts `business_date_from`/`business_date_to`/`shift`/`event` (`dispatch`\|`receipt`, default `dispatch`) and filters against the *derived* value, not the raw timestamp. An open transaction under `event=receipt` is silently excluded (its `receipt_business_date`/`receipt_shift` are `NULL`) — not an error. This is the exact mechanism §6/§9 below reuse for the Receive and Issue reports. |
| Roadmap status/dependencies | `docs/ROADMAP.md` (Completed table, PR16 note, "Approved forward sequence"), `docs/ROADMAP_STATUS.md` | PR17 depends on PR16 (merged, `ac19505`/governance-synced at `a572a7a`); PR17 is the next planned item; PR18 (export/print) follows it. |
| Domain model / transaction lifecycle | `backend/app/models/transaction.py`, `docs/BUSINESS_RULES.md`, `knowledge/adr/ADR-005-transaction-model.md` | `BorrowTransaction.status` is exactly `OPEN`/`CLOSED` — no third state, no cancellation action anywhere in the codebase (confirmed by direct search across `app/models/transaction.py`, `app/services/borrow_service.py`, `app/api/v1/transactions.py`; zero matches for "cancel"). Receipt outcome is exactly `usable`/`defective` (`ReceiptOutcome`, Roadmap PR8B, `knowledge/adr/ADR-006-receipt-outcome-contract.md`). This closes §7's "cancelled operations" question below with a factual, not invented, answer: there is nothing to handle because the concept does not exist in this system. |
| Equipment master data | `backend/app/models/equipment.py`, `backend/app/models/master_data.py` | Four equipment states (`AVAILABLE_AT_POOL`/`ISSUED_TO_WARD`/`UNAVAILABLE_DEFECTIVE`/`DECOMMISSIONED`); `EquipmentCategory`, `Ward`, `Department`, `Location` master-data tables; `Equipment.brand`/`Equipment.model` (the spec's "manufacturer" maps onto the existing `brand` column — no new column is proposed, see §9); `Equipment.pm_due_date`/`cal_due_date` exist as columns but were deliberately removed from the dashboard summary (Roadmap PR13, `pm_due_soon`/`cal_due_soon`) as "MVP-irrelevant" — this design does **not** reintroduce them into any report (§9, §22) to stay clear of `AGENTS.md`'s "no PM/calibration/recall workflow" guardrail; a raw due-date column is data, but building any report around it risks being read as scheduling/workflow, so it is left out entirely rather than judged case-by-case. |
| Equipment Verify Checklist — **no existing definition anywhere** | Direct search: `docs/audits/03-hospital-equipment-pool-workflow-audit.md` (the original hospital workflow audit), `docs/HOSPITAL_DOMAIN_MODEL.md`, `docs/BUSINESS_RULES.md`, `docs/GLOSSARY.md` — zero matches for "verify" or "checklist" in any of them. The term appears **only** in `docs/audits/04-consolidated-implementation-plan.md`'s Group 7/Group 8 entries (as a report to build and as legacy history explicitly excluded from Version 1 migration) and in documents that simply repeat that plan's wording. No hospital business process behind "Equipment Verify Checklist" — what triggers it, who performs it, what is actually verified, what a completed vs. incomplete verification looks like — has ever been audited or confirmed anywhere in this repository. | This is the single most important finding of this design document. See §7 (Business Workflow), §8 (Canonical Definition), and **Owner Decision #1** (§18) — exactly the same "flag as a blocking Owner Decision rather than guess" discipline PR16 applied to the Day/Night shift boundary. |
| Authorization | `backend/app/api/v1/deps.py` | `VIEW_AND_REPORT_ROLES` (Administrator, Equipment Pool Staff, Read Only — all three) already gates the existing `/reports/export` endpoint. `GET /transactions` itself only requires `get_current_user` (any authenticated user), no report-specific gate. §14 recommends which of these two precedents PR17's new endpoints should follow. |
| Existing (pre-PR17) reporting capability | `backend/app/api/v1/reports.py`, `backend/app/services/report_service.py`, `frontend/src/pages/ReportsPage.tsx` (`/reports` route) | An unfiltered CSV/XLSX export of **all** transactions (capped at 50,000 rows, no date/shift/ward filter at all) already exists at `GET /reports/export`, plus a dispatch-trend bar chart on `/reports`. This predates PR16/PR17 and is **not** modified by this design — flagged as existing context PR17's own named reports are additive to, and PR18 (export) will eventually need to reconcile with, not something this design silently duplicates or removes (§9, §22). |
| Terminology discipline | `docs/GLOSSARY.md` | "Operator" = authenticated Equipment Pool staff member recording an action (`borrower_user_id` at dispatch, `received_by_user_id` at receipt) — reused directly as a filter concept (§9), not invented. "Shift Session" and "Standby Snapshot" are explicitly "Confirmed future," not this PR — this design does not touch either. |
| Frontend architecture | `frontend/src/pages/EquipmentDetailPage.tsx` (TanStack Query, `useSearchParams`-backed applied filter state, draft-vs-applied separation, `isLoading`/`isError` distinguished from a genuinely empty result), `frontend/src/App.tsx` (route table) | The exact filter-control and state-management pattern §11 below reuses, not redesigns. Existing routes: `/`, `/equipment`, `/equipment/:id`, `/scan`, `/borrow`, `/return`, `/reports`, `/admin`, `/settings` — no `/reports/*` sub-routing exists yet. |
| API/error conventions | `docs/api/ERROR_CODES.md`, `backend/app/schemas/common.py` (`Page[T]`, `ErrorResponse`) | Cursor pagination shape (`items`, `next_cursor`, `total`), `{detail, code, status}` error shape, `DomainError` subclass-per-condition pattern — reused directly (§10). |

---

## 3. Business Goal

Hospital staff need three specific, already-named operational reports for daily work — not a general-purpose report builder:

1. **Receive Report** — what equipment came back to the pool, when, and in what condition, during a given business day/shift.
2. **Issue Report** — what equipment left the pool, to which ward, when, during a given business day/shift.
3. **Equipment Verify Checklist Report** — see §7/§8/§18; this design recommends a narrow, data-only interpretation and flags the alternative as Owner Decision #1, rather than guessing.

None of these is a KPI dashboard, a trend chart, or a query builder. Each has a fixed, known shape (§8) driven by an existing, already-confirmed business fact — a dispatch event, a receipt event, or (recommended interpretation only) current equipment master data — filtered by the PR16 foundation's `business_date`/`shift`.

---

## 4. Design Philosophy

This document follows, and does not reverse, the required order:

```
Business workflow -> Business semantics -> Report definitions -> API -> Backend -> Frontend -> Implementation slices
```

Each section below is built only on what the previous section established. Where the workflow itself is not confirmed anywhere (Equipment Verify Checklist), the chain stops at that point and is flagged (§18) rather than continued on invented semantics — the same discipline PR16 applied when `docs/GLOSSARY.md` forbade inventing the Day/Night boundary.

---

## 5. Reporting Semantics (Reuse of PR16 — Not Redesigned)

Every report below reuses, unmodified:

- `Shift` (`DAY`/`NIGHT`) and the confirmed `_ShiftBoundaryPolicy` (Owner Decision #1 of PR16: 08:00/20:00 `Asia/Bangkok`, `business_date_anchor = shift_start_date`) — `backend/app/core/reporting_time.py`.
- `business_date_and_shift()` / `business_date_and_shift_sql()` — the one pure-Python/SQL-expression pair, never reimplemented per report.
- `dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` on `BorrowTransaction`/`TransactionOut` — a transaction's dispatch and receipt business_date/shift can legitimately differ (PR16 §5, §18 "Risk — dispatch vs. receipt business_date divergence"); PR16 explicitly deferred to PR17 the decision of *which* one each report reports against. This design resolves that deferred decision explicitly, per report, in §8:
  - **Issue Report reports the dispatch event** (`dispatch_business_date`/`dispatch_shift`, from `borrowed_at`).
  - **Receive Report reports the receipt event** (`receipt_business_date`/`receipt_shift`, from `returned_at`).
  - **Equipment Verify Checklist Report (recommended interpretation) reports neither** — it is not a transaction-event report at all (§8).
- `GET /transactions`'s existing `event=dispatch|receipt` basis and its NULL-propagation rule for an open transaction — this is precisely how §8's Receive Report canonical definition ("only closed transactions appear") is enforced, with zero new logic: an open transaction's `receipt_business_date`/`receipt_shift` are already `NULL` today, so a receipt-basis filtered query already excludes it (PR16 Slice 3, `backend/app/crud/transaction.py::search()`, confirmed by direct inspection).

No alternative semantics, no second date-bucketing implementation, and no business rule already decided by PR16 (the boundary times, `business_date_anchor`, `on_demand` classification) is revisited here.

---

## 6. Business Workflow

### 6.1 Receive Report

- **Purpose:** Show every equipment item received back into the pool during a selected business day/shift, with its condition, so Equipment Pool staff can confirm what came back and in what state.
- **Primary users:** Equipment Pool Staff (day-to-day operational review), Administrator (oversight), Read Only (view access) — the confirmed 3-role matrix (`docs/BUSINESS_RULES.md`), unchanged.
- **Trigger:** End of a shift or business day, or on demand, to review receipts.
- **Workflow:** Staff selects a business date range and, optionally, a shift, ward, and other filters (§9); the report lists matching receipt events; staff scans the list or prints it for a shift handover record.
- **Inputs:** Filter selections only (§9) — no data entry, no new write path (§14).
- **Outputs:** A filtered, ordered list of receive events (§8); on-screen only for PR17 (§12); print/export is PR18.
- **Completion criteria:** The list reflects exactly the receipt events matching the selected filters, with no omission or duplication, per §8's canonical definition.
- **Operational value:** Confirms receipt volume and condition mix (usable/defective) for a shift without manually scanning the full unfiltered transaction history.

### 6.2 Issue Report

- **Purpose:** Show every equipment item dispatched out of the pool during a selected business day/shift, and to which ward, so staff can confirm what left the pool.
- **Primary users:** Same three roles as §6.1.
- **Trigger:** Same as §6.1, applied to dispatches instead of receipts.
- **Workflow:** Same shape as §6.1, filtered by dispatch event instead of receipt event.
- **Inputs/Outputs/Completion criteria:** Same shape as §6.1, mirrored onto dispatch (§8).
- **Operational value:** Confirms dispatch volume, routine-round vs. on-demand mix, and destination-ward distribution for a shift.

### 6.3 Equipment Verify Checklist

- **Purpose:** **Not confirmed.** No source in this repository defines what "verifying" equipment means as a hospital process — see §2's finding and §18 Owner Decision #1. Two candidate purposes exist and are evaluated below rather than assumed.
- **Primary users:** Assumed the same three roles as §6.1/§6.2 unless the Owner Decision resolves otherwise (no evidence exists to assume a narrower audience).
- **Trigger, Workflow, Inputs, Outputs, Completion criteria, Operational value:** Depend entirely on which candidate interpretation (§8.3, §18) is confirmed. This document does not invent an answer for any of these — inventing a trigger or completion rule for a workflow that was never audited would repeat exactly the mistake PR16's design process was built to avoid.

**Candidate interpretations (both evaluated in full in §8.3):**

- **(A) Equipment master-data / status-history checklist (recommended for PR17's own scope).** "Verify" means confirming the pool's own equipment master list and current status are accurate and up to date — using data that already exists today (`Equipment`, `EquipmentStatusHistory`), with zero new write path, zero new workflow, and therefore fully designable and (later) implementable within PR17's own reports-only scope.
- **(B) A genuine physical-verification event workflow.** "Verify" means an operator physically confirms an equipment item's presence/condition at a point in time, which does not exist as a workflow anywhere in this system today (Roadmap PR12's inventory *import* is a one-time bulk data-correction operation, not a recurring verification event, and is unrelated). Building this would be a new recurring capture workflow — materially larger than "a report" — and is not scoped to PR17 by the authoritative source (`docs/audits/04-consolidated-implementation-plan.md`'s PR17 entry says "reports," not "workflow"). If this is what the Repository Owner actually wants, it is new, unscheduled Roadmap scope requiring its own design, analogous to how Shift Sessions and Standby Snapshots are "Confirmed future work" not yet assigned a Roadmap PR (`docs/ROADMAP.md`).

---

## 7. Canonical Report Definitions

This section is mandatory and precise, per this task's explicit requirement. Each rule below is either a direct, cited consequence of an already-confirmed system fact, or explicitly marked as depending on the unresolved Owner Decision (§18) — nothing here is a guess presented as a rule.

### 7.1 Receive Report

- **Exactly which transactions appear:** A `BorrowTransaction` row appears if and only if `returned_at IS NOT NULL` (i.e. `status = CLOSED`) **and** its `receipt_business_date`/`receipt_shift` (derived from `returned_at`, PR16 §7/§9) fall within the selected `business_date_from`/`business_date_to`/`shift` filter, combined with any other active filter (§9) via `AND`.
- **Exactly which transactions never appear:** Any `OPEN` transaction (`returned_at IS NULL`) — it has no receipt event yet, so it has no `receipt_business_date`/`receipt_shift` to match against (both are `NULL` on that row, per `BorrowTransaction.receipt_business_date`'s existing docstring), and a `NULL` value can never satisfy a non-`NULL` filter under ordinary SQL comparison semantics, exactly as PR16 Slice 3 already established and tested for `event=receipt`. This is not a special-case exclusion this design adds — it is the same NULL-propagation behavior already shipped.
- **Whether partially completed workflows appear:** No. A dispatched-but-not-yet-received transaction is, by definition, not receivable data — it belongs to the Issue Report (§7.2), not this one, until it is actually received.
- **Handling of cancelled operations:** Not applicable. This system has no cancellation action anywhere — confirmed by direct search of `app/models/transaction.py`, `app/services/borrow_service.py`, and `app/api/v1/transactions.py` (zero matches for "cancel"); every dispatch, once created, is either `OPEN` (awaiting receipt) or `CLOSED` (received). There is no third outcome to define a rule for.
- **Handling of defective equipment:** A `CLOSED` transaction with `receipt_outcome = defective` appears in the Receive Report exactly like a `usable` one — `receipt_outcome` is a **displayed column** (§9), never an exclusion criterion. The report's job is to show what came back and in what condition, not to filter out the condition staff most need to see.
- **Handling of future lifecycle extensions:** If a future Roadmap PR ever adds a third transaction state or a cancellation path, this report's canonical rule ("appears iff `returned_at IS NOT NULL`") is stable as long as `returned_at` remains the sole receipt-timestamp authority — flagged here so a future implementer does not need to re-derive this reasoning from scratch.

### 7.2 Issue Report

- **Exactly which transactions appear:** A `BorrowTransaction` row appears if and only if its `dispatch_business_date`/`dispatch_shift` (derived from `borrowed_at`, always present on every transaction) fall within the selected filter range, combined with any other active filter via `AND`. Both `OPEN` and `CLOSED` transactions appear — dispatch is a fact about the past regardless of whether the item has since been received.
- **Exactly which transactions never appear:** None are excluded by lifecycle status. A transaction is excluded only by not matching the selected filters (business date/shift range, ward, etc. — §9), never by its `status`.
- **How issued-but-not-returned equipment appears:** Normally, with `status = OPEN` and no receipt information — exactly as `TransactionOut` already represents it today (`returned_at`/`receipt_outcome` both `None`). No placeholder or synthetic "pending" row is invented.
- **How same-day issue/receive behaves:** A transaction dispatched and received on the same calendar day (or even the same shift) appears **once** in the Issue Report (on its dispatch event, if the dispatch date/shift matches the Issue Report's own filter) and, independently, **once** in the Receive Report (on its receipt event, if the receipt date/shift matches the Receive Report's own filter) — this is not double-counting, because the two reports are answering two different questions ("what left" vs. "what came back") against two independently derived date/shift bases, exactly the separation PR16 §8 already established (`event=dispatch` vs. `event=receipt` is "an explicit, closed, two-value basis," never merged).
- **Ordering rules:** Ascending by `dispatch_business_date`, then `shift` (`DAY` before `NIGHT`, matching the boundary policy's own day-then-night order), then `borrowed_at` — a chronological shift log, matching how staff would read a printed handover sheet (earliest event first). This is a UX/presentation recommendation, not a business rule — reversible without consequence, unlike §7.1/§7.2's inclusion rules above, which are cited facts.

### 7.3 Equipment Verify Checklist

This report has no confirmed source. Two full candidate definitions are given below so the design as a whole remains reviewable even though one open decision blocks final commitment (§18):

**(A) Equipment master-data / status-history checklist (recommended).**
- **Purpose:** A point-in-time listing of the pool's equipment master records and their current status, scoped by category/ward/status, so staff can visually confirm the equipment list itself is accurate and current.
- **Equipment selection rules:** All non-soft-deleted `Equipment` rows (`deleted_at IS NULL`, the existing filter every equipment query already applies) matching the selected filters (§9) — category, current status, ward/department ownership.
- **Verification scope / checklist scope:** Equipment identity fields (BCM Code, Asset Number, equipment name, category, brand/model) and current lifecycle status (`AVAILABLE_AT_POOL`/`ISSUED_TO_WARD`/`UNAVAILABLE_DEFECTIVE`/`DECOMMISSIONED`) as they exist **right now** — not a historical event log.
- **Verification completion rules:** None — there is no "verification" action to complete under this interpretation; the report is a read-only snapshot, not a task list. (If this reads as not really answering "verification" at all, that is precisely the signal that interpretation (B) may be what the Repository Owner actually means — see §18.)
- **Future extensibility:** If a genuine verification-event workflow (interpretation B) is later approved, this report can be extended (or superseded by a new one) once that workflow exists; nothing in this interpretation blocks that later addition.
- **Snapshot vs. realtime behaviour:** Realtime — reads current `Equipment` rows at request time, no caching, no materialized snapshot (matches PR16 §5's "reporting reads historical event facts... never current-state joins presented as if they were historical" principle, inverted correctly here since this report is explicitly about current state, not a historical event).
- **Incomplete verification behaviour:** Not applicable — there is no verification action, so there is no "incomplete" state to define.
- **Why this is not a transaction report:** Confirmed directly — it has no `business_date`/`shift`/dispatch/receipt basis at all; the only sense in which it is "date/shift filterable" (the PR17 acceptance criterion) is that it is *not* date/shift filterable in the same way as §7.1/§7.2, since it reports current state, not a historical event. This tension is called out explicitly in §18 rather than papered over.

**(B) Physical-verification event workflow.**
- **Purpose:** Confirm each equipment item's real-world presence/condition was physically checked by an operator at a specific business date/shift.
- **Equipment selection / verification scope / checklist scope / completion / extensibility / snapshot-vs-realtime / incomplete-verification rules:** All undefined — this interpretation requires a **new** data-capture event (an operator records "verified equipment X at time Y, condition Z"), which does not exist today and is not part of "Receive/Issue/Equipment Verify Checklist **reports**" as PR17 is scoped by the authoritative source (§2). Designing this workflow is out of scope for PR17's own reports-only mandate; if approved, it becomes its own Roadmap item.
- **Why it is not designed further here:** Per this task's explicit instruction not to invent business rules, and per PR16's own established precedent of flagging rather than guessing an undefined boundary.

---

## 8. Architecture Options and Recommendation

Design order followed throughout, mirroring PR16 §6: Business workflow (§6-§7) -> Domain/query model -> API -> Backend -> Frontend.

**Option A — Thin, purpose-named endpoints over the existing `transaction_crud.search()` query engine (recommended for Receive/Issue).** `GET /reports/receive` and `GET /reports/issue` are new, narrowly-scoped endpoints that call the *existing*, unmodified `transaction_crud.search()` with `event` pinned to `receipt`/`dispatch` respectively (never client-settable on these two endpoints — see §10) and return the existing `Page[TransactionOut]` shape. No new query logic, no new schema, no duplicated derivation.
*Trade-off:* the response shape carries every `TransactionOut` field (some irrelevant per report, e.g. `dispatch_type` on a Receive Report row), not a report-trimmed subset. Accepted: introducing report-specific slim schemas now would be premature schema proliferation for a shape the frontend can trivially select fields from; can be revisited if PR18's export format needs a narrower shape.

**Option B — One generic `/reports` query endpoint with a `report_type` parameter (considered, rejected).** Directly contradicts this task's explicit instruction ("Reject filters/endpoints that do not improve hospital workflow"; "no single unrestricted report query endpoint" was PR16's own explicit avoidance, §8) and would blur the "each report has one canonical definition" requirement (§7) into a single ambiguous surface.

**Option C — Duplicate `search()`'s query logic into three new report-specific CRUD functions (considered, rejected).** Directly produces the "duplicated query logic" this task explicitly instructs against; any future change to the `business_date`/`shift` derivation would then need three synchronized edits instead of one.

**For Equipment Verify Checklist (interpretation A only, §7.3):** a new, separate `equipment_crud`-layer query (not `transaction_crud`, since this report is not transaction-shaped) reusing the existing `Equipment.deleted_at.is_(None)` filter convention already used by every other equipment query (`backend/app/crud/equipment.py`) — see §10.

**Recommendation:** Option A for Receive/Issue; a narrow, equipment-domain-native query for Verify Checklist (interpretation A), pending §18.

---

## 9. Filtering

Each filter below is justified by an operational need already established in §6/§7, not included merely because it is technically available.

| Filter | Applies to | Why it exists |
|---|---|---|
| `business_date_from` / `business_date_to` | Receive, Issue | The PR17 acceptance criterion itself ("consistent date/shift filtering," `docs/audits/04-consolidated-implementation-plan.md`). Reuses PR16's existing parameter names verbatim — no renaming, no alias (§5). |
| `shift` | Receive, Issue | Same acceptance criterion; a shift handover report is the primary named use case (§6.1/§6.2). |
| `ward_id` | Receive, Issue | Already an existing `transaction_crud.search()` filter (PR13) — which ward received/dispatched equipment is a routine operational question, already answerable today for the unnamed transaction list; naming it onto the Receive/Issue reports is not a new capability. |
| `equipment_id` | Receive, Issue | Already existing — "show me this one item's receive/issue history" is a routine equipment-detail question. |
| `dispatch_type` / `routine_round` | Issue only | Already existing, dispatch-only concepts (§7.2) — no equivalent exists for receipt, so these are not offered on the Receive Report. |
| `operator` (`borrower_user_id` for Issue, `received_by_user_id` for Receive) | Receive, Issue | **New** filter, not previously exposed on `GET /transactions`. Justified directly by `docs/GLOSSARY.md`'s existing "Operator" concept (an authenticated Equipment Pool staff member recording an action) — "who processed this shift's receipts/issues" is a real shift-handover question, and the underlying column (`borrower_user_id`/`received_by_user_id`) already exists on `BorrowTransaction`. This is the one net-new backend filter this design proposes (§10) — everything else on Receive/Issue reuses an existing `search()` parameter unchanged. |
| `equipment_category_id` | Receive, Issue, Verify Checklist | **New** filter for Receive/Issue (requires joining `Equipment.category_id`, not currently part of `transaction_crud.search()`'s filter set — §10); already an existing filter for the plain equipment list (`GET /equipment`). "Show me infusion-pump receipts for this shift" is a plausible operational need once a hospital's equipment pool grows past a handful of categories. |
| `status` (equipment status) | Verify Checklist only | Interpretation A's report is inherently about current equipment status (§7.3); this is the report's primary axis, not a secondary filter. |

**Rejected filters** (per this task's explicit "reject filters that do not improve hospital workflow"):
- `manufacturer`/`model` — the spec's wording; this maps onto the existing `Equipment.brand`/`Equipment.model` columns. Not proposed as report filters: no audit or business document has ever confirmed hospital staff filter receive/issue activity by equipment brand/model day-to-day (unlike ward and category, which are load-bearing operational groupings already used elsewhere in this system — dashboards, existing filters). Can be added later with real evidence of need, exactly like PR14B's evidence-gated-index precedent.
- `pm_due_date`/`cal_due_date` proximity — explicitly excluded (§2) to stay clear of the "no PM/calibration workflow" guardrail; these columns exist but this design does not build any report around them.
- A free-text search box on any of the three reports — none of the three reports is a lookup tool (that is `GET /equipment/search-bcm`'s job, unmodified); a report answers "what happened/what exists in this scope," not "find one specific item."

---

## 10. API Design

Design only — no implementation.

### 10.1 `GET /api/v1/reports/receive`

| | |
|---|---|
| **Method/path** | `GET /api/v1/reports/receive` (new) |
| **Purpose** | Return the Receive Report per §7.1's canonical definition |
| **Permissions** | `VIEW_AND_REPORT_ROLES` (Administrator, Equipment Pool Staff, Read Only) — following the existing `/reports/export` precedent (`backend/app/api/v1/reports.py`), not the looser `get_current_user`-only gate `GET /transactions` itself uses, since this is a named *report* surface, matching the existing report-role convention exactly (§14). |
| **Request query params** | `business_date_from: date \| None`, `business_date_to: date \| None`, `shift: Shift \| None`, `ward_id: str \| None`, `equipment_id: str \| None`, `equipment_category_id: str \| None`, `operator_id: str \| None` (maps to `received_by_user_id`), `limit: int = 25 (le=200)`, `cursor: str \| None` — `event` is **not** exposed; internally pinned to `"receipt"` (§8) |
| **Validation rules** | `business_date_from > business_date_to` -> `400 INVALID_INPUT`, reusing the exact check already in `app/api/v1/transactions.py::list_transactions` (not a new implementation, a second call site of the same logic) |
| **Response schema** | `Page[TransactionOut]` — unchanged, reused verbatim (§8, Option A) |
| **Pagination** | Cursor-based, identical to `GET /transactions` (`(created_at DESC, id DESC)`) |
| **Sorting** | Per §7.2's recommended ordering (`dispatch_business_date`/`shift`/`borrowed_at` ascending) is a *display* concern the frontend can apply client-side to one already-paginated page, or a future backend `ORDER BY` change — **not** decided in this design as a hard requirement, since the existing cursor-pagination contract (`created_at DESC`) is what guarantees correct "load more" behavior; a conflicting `ORDER BY` would need its own evidence-gated design pass, flagged here as a Slice 2 implementation-time decision, not assumed |
| **Error responses** | `400 INVALID_INPUT` (reversed range), `401`, `403` (new — this endpoint's role gate), `422` (schema validation) |
| **Version compatibility** | New endpoint, no existing contract touched |

### 10.2 `GET /api/v1/reports/issue`

Identical shape to §10.1, with: `event` pinned to `"dispatch"`; `operator_id` maps to `borrower_user_id`; `dispatch_type`/`routine_round` query params added (§9, Issue-only); no `equipment_category_id` gap to fill differently — same new join as §10.1.

### 10.3 `GET /api/v1/reports/equipment-verify-checklist`

Pending §18's Owner Decision. If interpretation A (§7.3) is confirmed:

| | |
|---|---|
| **Method/path** | `GET /api/v1/reports/equipment-verify-checklist` (new) |
| **Purpose** | Return the current equipment master/status listing per §7.3(A) |
| **Permissions** | `VIEW_AND_REPORT_ROLES`, same rationale as §10.1 |
| **Request query params** | `equipment_category_id: str \| None`, `status: EquipmentStatus \| None`, `ward_id`/`department_id: str \| None` (via `Equipment.department_owner_id`), `limit`, `cursor` — deliberately **no** `business_date_from`/`business_date_to`/`shift` (§7.3(A)'s "why this is not a transaction report") |
| **Response schema** | A **new**, equipment-shaped schema (not `TransactionOut`) — reuses the existing `EquipmentOut`-equivalent response shape already returned by `GET /equipment` (no new fields invented) |
| **Pagination/Sorting** | Same cursor convention as `GET /equipment`, unchanged |
| **Error responses** | `401`, `403`, `422` — no reversed-range check applies (no date range on this endpoint) |

If interpretation B is confirmed instead, this endpoint (and everything under it) is void and replaced by whatever the new verification-event workflow's own design specifies — not something this document can specify without the resolved decision (§7.3(B), §18).

Avoided per instruction: no single unrestricted "report query" endpoint (§8, Option B rejected); no export/PDF/Excel/CSV endpoint (PR18 scope, §22).

---

## 11. Backend Architecture

- **Service layer:** A new `app/services/report_query_service.py` (or, if the Repository Owner prefers, functions living directly in `app/api/v1/reports.py` mirroring the existing thin-router pattern already used there) composes `transaction_crud.search()` calls for Receive/Issue — it does not reimplement filtering, pagination, or the `business_date`/`shift` derivation. This mirrors `app/services/borrow_service.py`'s existing role (orchestration over CRUD, not a parallel query engine).
- **Query layer reuse:** `transaction_crud.search()` gains exactly one new capability this design requires: an optional join to `Equipment` for `equipment_category_id` filtering (§9) — everything else it needs (`business_date_from`/`_to`/`shift`/`event`/`ward_id`/`equipment_id`/`dispatch_type`/`routine_round`) already exists unmodified. A second new, small addition: filtering by `borrower_user_id`/`received_by_user_id` (the `operator_id` filter, §9) — also additive to the existing filter-append pattern (`backend/app/crud/transaction.py::search()`'s `filters.append(...)` shape), not a redesign.
- **Report composition:** Each of the two report endpoints (§10.1/§10.2) is a thin FastAPI route calling one shared, parameterized `transaction_crud.search()` invocation with `event` pinned — no per-report duplicate query building.
- **Shared abstractions:** None beyond what already exists (`Page[T]`, `TransactionOut`, `search()`) — no new generic repository layer, per this task's explicit instruction to avoid abstractions that obscure query intent (the same instruction PR16 §9 already followed).
- **Verify Checklist (interpretation A):** A new, narrow `app/crud/equipment.py`-level query function (e.g. `list_for_verify_checklist(...)`), reusing the existing `Equipment.deleted_at.is_(None)` filter every equipment query already applies — not a new abstraction, an addition to an existing, already-conventional module.
- **Future extension strategy:** If PR18 needs export/print of these same three reports, it consumes these same endpoints' data (or a shared query function directly) rather than re-deriving report contents independently — flagged here so PR18's own design does not have to re-discover this dependency.

---

## 12. Frontend Workflow

Design only — no detailed UI.

- **Navigation:** New sub-routes under the existing `/reports` route: `/reports/receive`, `/reports/issue`, and (pending §18) `/reports/equipment-verify-checklist`. The existing `/reports` page (`ReportsPage.tsx`'s trend chart + unfiltered export, §2) is left untouched by this design — these are three additional, explicitly separate report screens, not a replacement.
- **Workflow:** Each report screen follows the exact `EquipmentDetailPage.tsx` filter pattern already established: `useSearchParams`-backed *applied* filter state (URL is the single source of truth, survives refresh/navigation, per this repository's already-proven pattern), draft-vs-applied separation with an explicit Apply/Clear action (not live-on-keystroke), TanStack Query for data fetching keyed on the applied filter values.
- **Thai-first terminology:** Report titles and filter labels follow the existing terminology (เบิก = issue/dispatch, รับคืน = receive, per Roadmap PR11's already-completed terminology pass) — no new English-first surface is introduced.
- **Mobile-first behaviour:** Reuses the existing responsive filter-row layout (label + `<select>`/date-`<input>`, large touch targets, minimal typing) already shipped in `EquipmentDetailPage.tsx`/Roadmap PR13's filters — not redesigned.
- **Loading/empty/error states:** Reused verbatim from the existing `isLoading`/`isError` pattern, distinguished from a genuinely empty, zero-row result (matching `EquipmentDetailPage.tsx`'s already-established, tested convention) — no new state machine.
- **Printing workflow:** See §13.
- **Future export workflow:** Not in scope (§22); PR18-dependent, exactly as the authoritative source scopes it.

No dashboard-heavy UI, no chart, no new component library (§22). Business logic (the shift/business-date derivation, the receipt-vs-dispatch event basis) is never computed in the frontend — every report screen only displays/filters values the backend already derived, matching PR16's own non-negotiable rule (§5).

---

## 13. Printing Strategy

Design/recommendation only — no implementation.

- **Screen rendering (in scope for PR17's own eventual implementation):** The report list, as already rendered for on-screen viewing (§12), is the print source — no separate print-specific data fetch or component tree.
- **Print layout:** A browser-native `@media print` CSS stylesheet applied to the same report screen — hides filter controls/navigation chrome, keeps only the report title, applied filter summary (so a printed page is self-describing — "Receive Report, 2026-07-29, Day shift" — without needing the on-screen context), and the data table/list. This is the cheapest possible print capability (no new library, no server-side rendering), consistent with this task's explicit "recommend architecture, do not implement" instruction and PR16's own precedent of picking the option that adds no new dependency when an existing one suffices.
- **Future PDF:** Server-side PDF generation (e.g. reusing `openpyxl`'s existing-dependency neighbor pattern — a vetted, already-approved-category library, not proposed by name here) is PR18 scope; this design takes no position on which library beyond noting one is not yet chosen or needed by PR17 itself.
- **Future Excel:** `openpyxl` already exists as a vetted dependency (`report_service.py`, §2) — PR18 can extend it to these named reports; not implemented here.
- **Future CSV:** Python's `csv` module, already used identically (`report_service.py`) — same note as Excel.

No PDF, Excel, or CSV implementation is produced by this document (§22).

---

## 14. Security

- **Authorization:** `VIEW_AND_REPORT_ROLES` for all three new report endpoints (§10) — chosen deliberately over `GET /transactions`'s looser `get_current_user`-only gate, because these are named *report* surfaces analogous to the existing `/reports/export` (which already requires `VIEW_AND_REPORT_ROLES`), not the general-purpose transaction list. This is a **stricter** gate than the data these endpoints expose already sits behind today (any authenticated user can already see the same rows via `GET /transactions`) — so it introduces no new information-exposure risk, only a slightly narrower reporting-surface convention consistent with the existing `/reports/export` precedent.
- **Visibility:** No new field is exposed beyond what `TransactionOut` (Receive/Issue) or the existing equipment response shape (Verify Checklist, interpretation A) already expose today — same non-invention-of-new-data principle PR16 §12 established.
- **Future RBAC compatibility:** No new role or capability tier is introduced; if a future Roadmap PR narrows or widens `VIEW_AND_REPORT_ROLES` itself, these three endpoints inherit that change automatically, having never defined their own bespoke tuple.
- **Audit considerations:** No new write path exists anywhere in this design (§11) — reads are not audited today (consistent with every existing read endpoint, PR16 §12), and this design does not change that.
- **Query parameter validation:** All new filters (`operator_id`, `equipment_category_id`, `status`) are ordinary typed FastAPI query parameters (UUID/enum), rejecting an invalid value with a standard `422` — no free-text injection surface, matching every existing filter's validation shape.

---

## 15. Performance

- **Expected data volume:** Unchanged from PR16's confirmed scale assumption (`docs/PROJECT_MEMORY.md`: "low hundreds of devices, thousands of transactions per year") — these three reports read the same tables PR16 already queries, at the same scale.
- **Query strategy:** Reuses the existing indexed `borrowed_at`/`returned_at` columns and the PR14B composite `(created_at DESC, id DESC)` pagination index — no new query shape beyond the two additive joins/filters noted in §11 (`Equipment.category_id`, `borrower_user_id`/`received_by_user_id`).
- **Pagination:** Unchanged cursor convention, `limit <= 200` per page, bounding response size regardless of filter breadth — identical to every existing paginated endpoint.
- **Indexes:** No new index is proposed pre-emptively. `borrower_user_id` and `received_by_user_id` are already foreign-key columns without a dedicated index today (confirmed by inspection of `backend/app/models/transaction.py`); whether the new `operator_id` filter needs one is an implementation-time question gated on real `EXPLAIN (ANALYZE, BUFFERS)` evidence, per PR14B's established evidentiary discipline — not assumed or pre-built here.
- **Future optimization:** Not needed at confirmed scale; flagged for the same future-evidence-gated review PR16 §13 already established for its own derivation expression.

---

## 16. Future Compatibility

This design must, and does, support future work without requiring a redesign of anything specified here:

- **Dashboard/BI/analytics:** These three reports return plain paginated JSON (§10) — a future dashboard/BI layer can consume the same endpoints or the same underlying `transaction_crud.search()`/equipment-query functions without any contract change here.
- **Scheduled reports/notifications:** A future scheduled-report job would call these same endpoints' underlying query functions on a timer — no redesign needed, since the query layer (§11) is already decoupled from the HTTP layer.
- **Export (PR18):** PR18 consumes the same report definitions (§7) and, most likely, the same underlying query functions (§11) to produce PDF/Excel/CSV — this design's endpoints already return exactly the row-level data PR18 would need to format.

---

## 17. Suggested Implementation Slices

Each slice is independently reviewable, matching the lettered-slice/numbered-slice precedent already established for PR7/PR8/PR9/PR14/PR15/PR16.

**Slice 1 — Backend report domain (query layer additions).**
- Scope: `transaction_crud.search()` gains the `equipment_category_id` join and `operator_id` (`borrower_user_id`/`received_by_user_id`, selected by the same `event` basis already governing which timestamp column is read) filter, per §9/§11. New equipment-domain query function for Verify Checklist (interpretation A only, gated on §18).
- Dependencies: None beyond the already-merged PR16 baseline; Verify Checklist sub-scope additionally depends on Owner Decision #1 (§18) being resolved, exactly as PR16 Slice 1 depended on its own Owner Decision #1 before it could begin.
- Why this boundary: isolates all new query logic from any HTTP-layer or frontend change, testable in isolation with PostgreSQL evidence (§15) before any endpoint exists to call it.

**Slice 2 — API.**
- Scope: `GET /reports/receive`, `GET /reports/issue`, and (if §18 resolves to interpretation A) `GET /reports/equipment-verify-checklist`, per §10. `VIEW_AND_REPORT_ROLES` gate, validation, error responses.
- Dependencies: Slice 1.
- Why this boundary: the API contract is independently reviewable against §7's canonical definitions before any frontend consumes it — mirrors PR16 Slice 3's own boundary (query engine before endpoint).

**Slice 3 — Frontend.**
- Scope: `/reports/receive`, `/reports/issue`, (`/reports/equipment-verify-checklist` if in scope) screens per §12 — filter controls, loading/empty/error states, on-screen table/list rendering. No printing yet.
- Dependencies: Slice 2.
- Why this boundary: mirrors PR16 Slice 4's own boundary (frontend strictly after the API contract it consumes is final).

**Slice 4 — Printing foundation.**
- Scope: The `@media print` stylesheet and filter-summary print header per §13, applied to the Slice 3 screens.
- Dependencies: Slice 3.
- Why this boundary: printing is a presentation-only concern layered onto already-working screens — isolating it keeps Slice 3 reviewable without also reviewing print-specific CSS, and keeps this slice trivially revertible if the Repository Owner wants a different print approach later.

**Slice 5 — Governance synchronization.**
- Scope: The standard post-merge governance sync (`docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `docs/DECISION_LOG.md`, `knowledge/CHANGE_HISTORY.md`) recording Slices 1-4 as merged, advancing the next planned item to Roadmap PR18 — following the exact same pattern used after every prior Roadmap PR in this repository (most recently PR16, GitHub PR #62).
- Dependencies: Slices 1-4 all merged.
- Why this boundary: per this repository's own established convention (confirmed by inspecting every prior design document — none touches roadmap/governance files itself; that happens only in the dedicated post-merge sync step, §20).

No slice combines database + broad API + frontend + printing + governance changes — each is a narrow, independently mergeable, independently testable unit.

---

## 18. Owner Decisions

**Owner Decision #1 — Equipment Verify Checklist definition (BLOCKING for Verify Checklist only, not for Receive/Issue).**

No hospital business process behind "Equipment Verify Checklist" is confirmed anywhere in this repository's authoritative documentation (§2, §7.3). This blocks Slice 1's Verify Checklist sub-scope (and everything downstream of it) exactly the way PR16's Day/Night boundary blocked its own Slice 1 until answered. The Repository Owner needs to choose between:

- **(A) Equipment master-data/status-history checklist** (§7.3(A)) — implementable within PR17's existing reports-only scope, no new workflow, ready to build once confirmed.
- **(B) A genuine physical-verification event workflow** (§7.3(B)) — new, unscheduled Roadmap scope requiring its own design (workflow, data model, migration), not something PR17's "reports" mandate covers; if chosen, PR17 should ship Receive/Issue only (Slices 1-5 above minus the Verify Checklist sub-scope) and Equipment Verify Checklist becomes a new, separately numbered future Roadmap item, mirroring how Shift Sessions/Standby Snapshots are tracked today (`docs/ROADMAP.md` "Confirmed future work").
- **(C) Defer entirely** — ship Receive/Issue only in PR17, explicitly leave Equipment Verify Checklist unscheduled pending further business-process discovery, revisiting the Roadmap PR17 acceptance criterion's own wording if needed.

This document recommends **(A)** as the option that satisfies PR17's literal acceptance criterion ("provide... Equipment Verify Checklist... reports") without inventing a new workflow, while flagging its own honesty gap (§7.3(A)'s "why this is not really 'verification'") plainly rather than silently.

**Owner Decision #2 — `operator_id` filter's role scope (non-blocking, low risk).** Should the `operator_id` filter (§9) be restricted to Administrator-only (a "who did this" audit-adjacent question) or left open to all `VIEW_AND_REPORT_ROLES` (an ordinary operational filter, like ward)? This design recommends leaving it open (same gate as every other filter on these endpoints) since it exposes no more information than `TransactionOut.borrower_name`/the existing per-transaction view already does today — flagged only so the Repository Owner can override if a stricter reading is preferred.

**Owner Decision #3 — Report-specific role gate (`VIEW_AND_REPORT_ROLES`) vs. `get_current_user`-only (non-blocking, low risk).** §14 recommends the stricter, existing `/reports/export` precedent. If the Repository Owner instead wants these three reports to match `GET /transactions`'s broader `get_current_user`-only gate (since the underlying data is already visible there), that is a one-line change to §10/§14, not a redesign.

---

## 19. Risks

| Risk | Category | Mitigation |
|---|---|---|
| Equipment Verify Checklist is built on an assumed interpretation that turns out to be wrong | Business | Owner Decision #1 (§18) is a hard blocker for that sub-scope only; Receive/Issue can ship independently and are not blocked by it (§17, Slice boundaries). |
| `equipment_category_id`/`operator_id` joins on `transaction_crud.search()` degrade query performance at a future, larger scale | Architecture/Performance | Evidence-gated per §15 (PR14B precedent) — not assumed, verified with real `EXPLAIN` output at implementation time before any index is added. |
| A future PR18 export format needs a report-specific response shape `TransactionOut` cannot cleanly provide | Architecture/Future migration | §8/§11 flagged this explicitly as an accepted, revisitable trade-off, not a silent gap — PR18's own design can introduce a slim schema then, informed by real export requirements rather than speculation now. |
| The existing, unfiltered `/reports/export`/`ReportsPage.tsx` surface (§2) becomes confusing to operate alongside three new named reports | Compatibility | Explicitly left untouched and unrenamed by this design (§8, §12); PR18 is the natural point to reconcile/replace it once it has to add export to the named reports anyway — flagged here, not silently deferred. |
| Printing via `@media print` renders inconsistently across browsers/devices in a hospital's actual environment | Operational | Deliberately the cheapest, most standard mechanism (§13) rather than a bespoke print renderer — lowest risk option available; a future PDF (PR18) removes browser-print variability entirely if this proves insufficient. |

**Non-risk, explicitly confirmed by this design's own scope check:** No new lifecycle state, no QR redesign, no MEMS/Recall Monitor coupling, no Analytics/BI surface, no export/PDF/Excel/CSV implementation, and no application/frontend/migration code was introduced by this document (§22, Final Validation).

---

## 20. Acceptance Criteria

**Business**
- Each of the three reports' canonical definition (§7) is implemented exactly as specified — no transaction silently included/excluded outside that definition.
- Restated from the authoritative source: "Each report uses the same reporting metadata and presents consistent date/shift filtering" (`docs/audits/04-consolidated-implementation-plan.md`, PR17 entry) — satisfied by Receive/Issue reusing PR16's `business_date`/`shift` unmodified (§5); Verify Checklist's relationship to this criterion is exactly what Owner Decision #1 (§18) must resolve.

**API**
- `GET /reports/receive`/`GET /reports/issue` match §10's full contract, including the pinned (non-client-settable) `event` basis and the reused `business_date_from > business_date_to` validation.
- No existing endpoint's contract (`GET /transactions`, `GET /reports/export`) changes in any respect.

**Backend**
- `transaction_crud.search()`'s two new filter capabilities (§11) are additive, tested in isolation, and do not alter existing filter behavior.
- No duplicated business-date/shift derivation logic exists anywhere in the new report query paths (§8, Option A).

**Frontend**
- The three new report screens (§12) follow the existing `EquipmentDetailPage.tsx` filter/state pattern exactly — same URL-backed applied-state mechanism, same loading/empty/error distinction.
- No business logic (date/shift/event-basis computation) exists in any new frontend code.

**Testing** (restated as a requirement for the eventual implementation PR, not satisfied by this design document itself)
- Backend: filter-combination tests for each new/reused parameter on each report endpoint; PostgreSQL evidence for the two new joins; the §7 canonical-definition edge cases (open transaction excluded from Receive, same-day issue/receive both appearing exactly once, defective receipt included, empty-result pages).
- Frontend: component tests per report screen mirroring `EquipmentDetailPage.test.tsx`'s existing coverage pattern (filter application, URL persistence, loading/empty/error states).

**Documentation**
- This design document itself, reviewed and approved, is the Slice 0 deliverable; §17 Slice 5 is the only point at which `docs/ROADMAP.md`/`docs/ROADMAP_STATUS.md`/`docs/DECISION_LOG.md`/`knowledge/CHANGE_HISTORY.md` are touched (§21).

**Operational acceptance**
- A shift handover can be conducted using only the Receive/Issue reports' on-screen output (with browser print, §13) without needing to fall back to the unfiltered `/reports/export` CSV/XLSX.

---

## 21. Out of Scope

Explicitly excluded from PR17 (and from this design document):

- BI, analytics, dashboards, KPI widgets.
- Scheduled reports, notifications, email delivery.
- PDF implementation, Excel implementation, CSV implementation (PR18).
- Offline mode.
- Recall Monitor, MEMS, or any coupling to either.
- Any change to the existing `/reports/export`/`ReportsPage.tsx` surface.
- Any change to Roadmap PR16's reporting foundation, derivation logic, or the `GET /transactions` contract.
- A genuine equipment physical-verification event workflow (§7.3(B)) — unless Owner Decision #1 (§18) explicitly assigns it here, in which case it becomes its own, separately scoped Roadmap item, not silently folded into PR17.
- PM/calibration scheduling or reminder functionality of any kind (`AGENTS.md`'s existing guardrail, §2).

---

## 22. Documentation

This document is the only file this design PR adds. Per this repository's established convention (confirmed by inspecting every prior design document — `docs/design/PR8_IMPLEMENTATION_PLAN.md`, `PR15B_SCHEMA_HYGIENE_PLAN.md`, `PR16_REPORTING_FOUNDATION_PLAN.md` — none of which touched roadmap/governance files themselves), this design PR does **not** update:

- `docs/ROADMAP.md`
- `docs/ROADMAP_STATUS.md`
- `docs/DECISION_LOG.md`
- `knowledge/CONTEXT.md`
- `knowledge/PROJECT_MEMORY.md`
- `knowledge/CHANGE_HISTORY.md`

Governance synchronization occurs only after implementation is complete (§17, Slice 5) — exactly as it did for PR16 (design PR #56 touched no governance file; the dedicated governance sync, GitHub PR #62, ran only after all four implementation slices merged).

---

## 23. Final Validation

Verified before this design document was finalized:

- [x] No implementation changed — `git status --short` on this branch shows exactly one new file, this document itself.
- [x] No migrations created.
- [x] No APIs modified — every endpoint in `backend/app/api/v1/transactions.py`, `backend/app/api/v1/reports.py`, and every other existing router is untouched; §10's endpoints are proposals only.
- [x] No frontend implementation changed — `frontend/src/pages/EquipmentDetailPage.tsx`, `ReportsPage.tsx`, `App.tsx`, and every other existing file are untouched; §12's screens are proposals only.
- [x] Design documents internally consistent — §7's canonical definitions are the single source every later section (§9 filters, §10 API, §11 backend, §17 slices, §20 acceptance criteria) is derived from, cross-referenced rather than restated independently.
- [x] PR16 assumptions preserved — §5 states explicitly which PR16 mechanisms are reused unmodified; nothing in this document redefines `business_date`, `shift`, the boundary policy, or the `event` basis.
- [x] Business workflow precedes architecture — §6/§7 (workflow, canonical definitions) are written and cited before §8 (architecture options) makes any technical recommendation, matching §4's required order.
- [x] Canonical report definitions exist — §7, for all three reports, including the two full candidate interpretations for Equipment Verify Checklist.
- [x] Owner decisions minimized — exactly one blocking decision (§18, Owner Decision #1), scoped to Equipment Verify Checklist only; two additional non-blocking decisions are flagged with a recommended default so they do not block Receive/Issue.
- [x] Implementation slices are independent — §17, each slice's own dependencies and boundary rationale stated explicitly; Verify Checklist's Owner-Decision dependency is isolated to Slice 1's own sub-scope, not the whole Slice 1.
- [x] No business rules changed — every existing dispatch/receipt/ward-correction/status-transition rule, and every PR16 reporting rule, is restated as reused (§5), never altered.

---

## 24. Deliverables

1. **Files changed:** `docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md` (this document) — the only file added or modified by this design PR.
2. **Design summary:** §1-§5.
3. **Business workflows:** §6.
4. **Canonical report definitions:** §7.
5. **API proposal:** §10.
6. **Backend architecture:** §11.
7. **Frontend workflow:** §12.
8. **Implementation slice plan:** §17.
9. **Risks:** §19.
10. **Remaining Owner Decisions:** §18 (one blocking — Equipment Verify Checklist definition; two non-blocking, each with a recommended default).
11. **Validation checklist:** §23.

*No production code was written or modified to produce this document. No migration was generated. No application file was modified. No reporting library was introduced. Every claim about existing code cites the specific file inspected (§2), not assumption.*
