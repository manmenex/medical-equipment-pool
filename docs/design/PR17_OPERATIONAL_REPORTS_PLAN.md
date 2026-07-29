# Roadmap PR17 — Operational Reports: Design Proposal

**Status:** Design only. Nothing in this document has been implemented. No backend code, frontend code, Alembic migration, database schema change, or API modification was written to produce it.
**Repository:** Medical Equipment Pool. This is **not** MEMS and **not** Recall Monitor — no coupling to either system is introduced or assumed anywhere below.
**Baseline investigated:** `a572a7a81a4b57f0bce8e65990598b1b3f034c77` — squash commit of GitHub PR #62 (Roadmap PR16 governance sync), on branch `claude/medical-equipment-pool-0c7fz0`. Roadmap PR16 (Reporting Foundation, all four Implementation Slices) is fully merged at this baseline.
**Governing instruction:** DESIGN ONLY. Produce the minimum design documentation required for an independently reviewable PR17 Design PR. No implementation, no migration, no API change, no existing-file modification.

---

## 1. Objective

Design Roadmap PR17 — the first operational reporting package: **Receive Report**, **Issue Report**, and **Equipment Verify Checklist Report**. PR17 builds directly on the completed Reporting Foundation (Roadmap PR16): `business_date`/`shift` derivation, the `dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` computed fields on `TransactionOut`, and `GET /transactions`'s `business_date_from`/`business_date_to`/`shift`/`event` filters. This document treats all of that as authoritative and does not redesign any of it (§8).

These are **operational reports** for hospital staff doing daily work — not BI, not analytics, not a dashboard (§21, Out of Scope).

---

## 2. Current Foundation (Authoritative Inputs)

Documents and implementation areas inspected and treated as authoritative for this design, in the order consulted:

| Area | Source | What it established |
|---|---|---|
| Roadmap PR17 scope (authoritative) | `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 7 (`#### PR17 — Operational reports`) | Objective: "Provide Receive, Issue, and Equipment Verify Checklist reports, filterable by date and shift." Dependency: PR16. Acceptance criterion: "Each report uses the same reporting metadata and presents consistent date/shift filtering." PR18 (export/print output) is explicitly the *next* PR, not this one. |
| Reporting Foundation (must not be redesigned) | `docs/design/PR16_REPORTING_FOUNDATION_PLAN.md`, `backend/app/core/reporting_time.py`, `backend/app/models/transaction.py` (`dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` `@property`s), `backend/app/schemas/transaction.py` (`TransactionOut`), `backend/app/api/v1/transactions.py`, `backend/app/crud/transaction.py::search()` | `business_date`/`shift` are computed, never persisted, from `borrowed_at` (dispatch) or `returned_at` (receipt, `None` until received). `GET /transactions` already accepts `business_date_from`/`business_date_to`/`shift`/`event` (`dispatch`\|`receipt`, default `dispatch`) and filters against the *derived* value, not the raw timestamp. An open transaction under `event=receipt` is silently excluded (its `receipt_business_date`/`receipt_shift` are `NULL`) — not an error. This is the exact mechanism §6/§9 below reuse for the Receive and Issue reports. |
| Roadmap status/dependencies | `docs/ROADMAP.md` (Completed table, PR16 note, "Approved forward sequence"), `docs/ROADMAP_STATUS.md` | PR17 depends on PR16 (merged, `ac19505`/governance-synced at `a572a7a`); PR17 is the next planned item; PR18 (export/print) follows it. |
| Domain model / transaction lifecycle | `backend/app/models/transaction.py`, `docs/BUSINESS_RULES.md`, `knowledge/adr/ADR-005-transaction-model.md` | `BorrowTransaction.status` is exactly `OPEN`/`CLOSED` — no third state, no cancellation action anywhere in the codebase (confirmed by direct search across `app/models/transaction.py`, `app/services/borrow_service.py`, `app/api/v1/transactions.py`; zero matches for "cancel"). Receipt outcome is exactly `usable`/`defective` (`ReceiptOutcome`, Roadmap PR8B, `knowledge/adr/ADR-006-receipt-outcome-contract.md`). This closes §7's "cancelled operations" question below with a factual, not invented, answer: there is nothing to handle because the concept does not exist in this system. |
| Equipment master data | `backend/app/models/equipment.py`, `backend/app/models/master_data.py` | Four equipment states (`AVAILABLE_AT_POOL`/`ISSUED_TO_WARD`/`UNAVAILABLE_DEFECTIVE`/`DECOMMISSIONED`); `EquipmentCategory`, `Ward`, `Department`, `Location` master-data tables; `Equipment.brand`/`Equipment.model` (the spec's "manufacturer" maps onto the existing `brand` column — no new column is proposed, see §9); `Equipment.pm_due_date`/`cal_due_date` exist as columns but were deliberately removed from the dashboard summary (Roadmap PR13, `pm_due_soon`/`cal_due_soon`) as "MVP-irrelevant" — this design does **not** reintroduce them into any report (§9, §21) to stay clear of `AGENTS.md`'s "no PM/calibration/recall workflow" guardrail; a raw due-date column is data, but building any report around it risks being read as scheduling/workflow, so it is left out entirely rather than judged case-by-case. |
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
- `GET /transactions`'s existing `event=dispatch|receipt` basis. **Correction (review finding PR17-H1):** the NULL-propagation exclusion of an open transaction only happens *inside* the conditional branch `transaction_crud.search()` already guards with `if business_date_from is not None or business_date_to is not None or shift is not None` (confirmed by direct inspection of `backend/app/crud/transaction.py::search()`) — so a Receive Report request with **no** business-date/shift filter at all (only, say, a `ward_id` or `operator_id` filter, or no filter whatsoever) would never enter that branch and would therefore return OPEN transactions too, violating §7.1's canonical rule. Reusing PR16's `event` basis alone does **not**, by itself, guarantee the Receive Report's exclusion rule. §8/§11 below correct this: the Receive Report's own query composition adds an **unconditional** `BorrowTransaction.returned_at IS NOT NULL` predicate, independent of whether any business-date/shift filter is present.

No alternative semantics, no second date-bucketing implementation, and no business rule already decided by PR16 (the boundary times, `business_date_anchor`, `on_demand` classification) is revisited here.

---

## 6. Business Workflow

### 6.1 Receive Report

- **Purpose:** Show every equipment item received back into the pool during a selected business day/shift, with its condition, so Equipment Pool staff can confirm what came back and in what state.
- **Primary users:** Equipment Pool Staff (day-to-day operational review), Administrator (oversight), Read Only (view access) — the confirmed 3-role matrix (`docs/BUSINESS_RULES.md`), unchanged.
- **Trigger:** End of a shift or business day, or on demand, to review receipts.
- **Workflow:** Staff selects a business date range and, optionally, a shift, ward, operator, and other filters (§9); the report lists matching receipt events; staff reviews the on-screen list for a shift handover (printing is Roadmap PR18, §13).
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
- **Exactly which transactions never appear:** Any `OPEN` transaction (`returned_at IS NULL`). **Corrected per review finding (minor, incremental review `4804643991`):** the prior wording here claimed this exclusion was "not a special-case exclusion this design adds — it is the same NULL-propagation behavior already shipped." That is no longer accurate and directly contradicted the corrected enforcement rule below — it is superseded, not restated. PR16 Slice 3's NULL-propagation (an `OPEN` row's `receipt_business_date`/`receipt_shift` are `NULL`, so they can never satisfy a non-`NULL` `business_date`/`shift` filter) is real, but only ever activates *when* a `business_date`/`shift` filter is present — it is not, by itself, a general "OPEN is always excluded" guarantee (this was exactly review finding PR17-H1). The Receive Report's actual, always-on exclusion is the **new**, unconditional `require_receipt` predicate this design adds (see the bullet below and §8/§11) — a genuine addition to `transaction_crud.search()`, not a restatement of pre-existing behavior.
- **Whether partially completed workflows appear:** No. A dispatched-but-not-yet-received transaction is, by definition, not receivable data — it belongs to the Issue Report (§7.2), not this one, until it is actually received.
- **Handling of cancelled operations:** Not applicable. This system has no cancellation action anywhere — confirmed by direct search of `app/models/transaction.py`, `app/services/borrow_service.py`, and `app/api/v1/transactions.py` (zero matches for "cancel"); every dispatch, once created, is either `OPEN` (awaiting receipt) or `CLOSED` (received). There is no third outcome to define a rule for.
- **Handling of defective equipment:** A `CLOSED` transaction with `receipt_outcome = defective` appears in the Receive Report exactly like a `usable` one — `receipt_outcome` is a **displayed column** (§9), never an exclusion criterion. The report's job is to show what came back and in what condition, not to filter out the condition staff most need to see.
- **Handling of future lifecycle extensions:** If a future Roadmap PR ever adds a third transaction state or a cancellation path, this report's canonical rule ("appears iff `returned_at IS NOT NULL`") is stable as long as `returned_at` remains the sole receipt-timestamp authority — flagged here so a future implementer does not need to re-derive this reasoning from scratch.
- **Enforcement is unconditional, not filter-dependent (review finding PR17-H1):** The `returned_at IS NOT NULL` predicate above is applied by the Receive Report's own query composition regardless of which other filters are present — it is never contingent on `business_date_from`/`business_date_to`/`shift` being supplied. The following cases must all resolve per this same, single rule (restated as explicit acceptance criteria in §20):
  1. `event=receipt` with no date/shift filters at all -> only `CLOSED` (`returned_at IS NOT NULL`) transactions appear.
  2. `event=receipt` with `business_date_from`/`business_date_to` set -> same exclusion, further narrowed by the date range.
  3. `event=receipt` with `shift` set -> same exclusion, further narrowed by shift.
  4. An `OPEN` transaction (`returned_at = NULL`) -> never appears, in any of the above three cases.
  5. A `CLOSED` transaction with a valid `returned_at` -> appears whenever it otherwise matches the active filters, in any of the above three cases.

### 7.2 Issue Report

- **Exactly which transactions appear:** A `BorrowTransaction` row appears if and only if its `dispatch_business_date`/`dispatch_shift` (derived from `borrowed_at`, always present on every transaction) fall within the selected filter range, combined with any other active filter via `AND`. Both `OPEN` and `CLOSED` transactions appear — dispatch is a fact about the past regardless of whether the item has since been received.
- **Exactly which transactions never appear:** None are excluded by lifecycle status. A transaction is excluded only by not matching the selected filters (business date/shift range, ward, etc. — §9), never by its `status`.
- **How issued-but-not-returned equipment appears:** Normally, with `status = OPEN` and no receipt information — exactly as `TransactionOut` already represents it today (`returned_at`/`receipt_outcome` both `None`). No placeholder or synthetic "pending" row is invented.
- **How same-day issue/receive behaves:** A transaction dispatched and received on the same calendar day (or even the same shift) appears **once** in the Issue Report (on its dispatch event, if the dispatch date/shift matches the Issue Report's own filter) and, independently, **once** in the Receive Report (on its receipt event, if the receipt date/shift matches the Receive Report's own filter) — this is not double-counting, because the two reports are answering two different questions ("what left" vs. "what came back") against two independently derived date/shift bases, exactly the separation PR16 §8 already established (`event=dispatch` vs. `event=receipt` is "an explicit, closed, two-value basis," never merged).
- **Ordering rules (corrected per review finding PR17-H3):** The existing cursor-pagination contract (`created_at DESC, id DESC`, unchanged from `GET /transactions`) is the report's canonical ordering — **not** an ascending business-date/shift order. Per-page client-side sorting was considered in the prior draft of this document and is rejected: sorting one already-fetched page cannot produce a globally correct order, since each subsequent "load more" page is a different cursor window that would be sorted independently of the pages before it, producing a report whose overall row order does not correspond to any single, consistent sequence. If a future need for chronological (earliest-first) report ordering is confirmed, it must be implemented as a genuine backend `ORDER BY` change with a cursor derived from that same new ordering (its own Slice-1-level query change, its own PostgreSQL evidence, and its own regression tests for duplicate/missing-row safety) — not a frontend sort. This design does not propose that change now, absent a confirmed operational need beyond "would be nicer to read top-to-bottom" (§9's own "reject filters/features that do not improve hospital workflow" standard applies equally here).

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

**Option A — Thin, purpose-named endpoints over the existing `transaction_crud.search()` query engine, composing a report-only response DTO (recommended for Receive/Issue; canonical wording corrected per review findings PR17-H1/PR17-H5).** `GET /reports/receive` and `GET /reports/issue` are new, narrowly-scoped endpoints that both reuse `transaction_crud.search()` for their shared query, filtering, and cursor-pagination behavior (`event` pinned to `receipt`/`dispatch` respectively, never client-settable on these two endpoints — see §10), and both compose their rows into `ReportTransactionOut` (§10.1, §10.2, §11's Architecture layering) — **not** the existing `TransactionOut`. Every field `TransactionOut` already has is present unchanged (`ReportTransactionOut` extends it), plus two report-only additions, `dispatch_operator_display_name`/`receipt_operator_display_name`. Both endpoints return `Page[ReportTransactionOut]`. `TransactionOut` itself is never modified, and `GET /transactions`/`GET /transactions/{id}` continue returning `TransactionOut` exactly as they do today — this design changes neither.
Pinning `event` alone is *not* sufficient for the Receive Report's own inclusion rule (§7.1): `search()` must gain one small, additive capability: an internal-only `require_receipt: bool = False` parameter that, when `True` (set only by the Receive Report's own call site, never exposed as a client-settable query parameter), unconditionally appends `BorrowTransaction.returned_at.is_not(None)` to the filter list, independent of whether `business_date_from`/`business_date_to`/`shift` are supplied. This is the smallest possible fix: one new keyword-only parameter and one new unconditional filter append, not a parallel query path, not a change to any existing caller's behavior (`GET /transactions` itself never sets `require_receipt`, so its own behavior is byte-for-byte unchanged).
*Trade-off:* `ReportTransactionOut` carries every `TransactionOut` field (some irrelevant per report, e.g. `dispatch_type` on a Receive Report row), not a report-trimmed subset. Accepted: a further-trimmed, report-specific slim schema now would be premature schema proliferation for a shape the frontend can trivially select fields from; can be revisited if PR18's export format needs a narrower shape (§19 — that future schema, if ever introduced, is its own new type, not a change to `TransactionOut`).

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
| `operator_id` (`borrower_user_id` for Issue, `received_by_user_id` for Receive) | Receive, Issue | **New** filter, not previously exposed on `GET /transactions`. Justified directly by `docs/GLOSSARY.md`'s existing "Operator" concept (an authenticated Equipment Pool staff member recording an action) — "who processed this shift's receipts/issues" is a real shift-handover question, and the underlying column already exists on `BorrowTransaction`. **Corrected per review finding PR17-M1:** a filter is only usable if the frontend has an authorized way to obtain valid operator options — the existing `GET /users` is Administrator-only (`backend/app/api/v1/users.py`, `require_roles(ROLE_ADMINISTRATOR)`), which Equipment Pool Staff and Read Only (both allowed to view these reports, §14) cannot call. §10.4 defines a new, minimal, report-scoped lookup endpoint (`GET /report-options/operators`) instead of widening `GET /users` or requiring users to type a raw UUID. **Further corrected per incremental review finding PR17-M1R:** §10.4's lookup is bounded to users actually referenced by `borrower_user_id`/`received_by_user_id` in real transaction history — never every `User` row — so it is genuinely an operator list, not an account directory. |
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
| **Request query params** | `business_date_from: date \| None`, `business_date_to: date \| None`, `shift: Shift \| None`, `ward_id: str \| None`, `equipment_id: str \| None`, `equipment_category_id: str \| None`, `operator_id: str \| None` (maps to `received_by_user_id`), `limit: int = 25 (le=200)`, `cursor: str \| None` — `event` is **not** exposed; internally pinned to `"receipt"`, and `require_receipt=True` is always set internally (§8, corrected per PR17-H1) — the caller cannot opt out of either |
| **Validation rules** | `business_date_from > business_date_to` -> `400 INVALID_INPUT`, reusing the exact check already in `app/api/v1/transactions.py::list_transactions` (not a new implementation, a second call site of the same logic) |
| **Response schema** | `Page[ReportTransactionOut]` — **corrected per review finding PR17-H5** (not `Page[TransactionOut]`; §8 explains why). `ReportTransactionOut` extends `TransactionOut` unchanged, plus two new, report-only, read-only fields: `dispatch_operator_display_name: str \| None` and `receipt_operator_display_name: str \| None`, resolved from the same bounded operator identity source as §10.4. The Receive Report's rows always have `receipt_operator_display_name` populated (every row it returns is `CLOSED`, §7.1) and `dispatch_operator_display_name` populated whenever `borrower_user_id` was recorded. `GET /transactions`/`GET /transactions/{id}` are unaffected — they continue returning `TransactionOut` exactly as today, with no operator field. |
| **Pagination** | Cursor-based, identical to `GET /transactions` (`(created_at DESC, id DESC)`) — the sole ordering basis (see Sorting row) |
| **Sorting** | **Corrected per review finding PR17-H3.** Backend-only, identical to `GET /transactions`'s existing `(created_at DESC, id DESC)` contract — no alternative ordering is introduced by this endpoint. The frontend must render pages in the order returned and must never re-sort a fetched page client-side (§7.2, §12); doing so would silently desynchronize the on-screen order from the cursor that produced it across "load more" pages. |
| **Error responses** | `400 INVALID_INPUT` (reversed range), `401`, `403` (new — this endpoint's role gate), `422` (schema validation) |
| **Version compatibility** | New endpoint, no existing contract touched |

### 10.2 `GET /api/v1/reports/issue`

Identical shape to §10.1 (including the corrected Sorting row, §10.1/§7.2/§12), with: `event` pinned to `"dispatch"`; `require_receipt` is not applicable here (`dispatch_business_date` is always present, per §7.2 — there is no equivalent NULL-exclusion gap for dispatch); `operator_id` maps to `borrower_user_id`; `dispatch_type`/`routine_round` query params added (§9, Issue-only); no `equipment_category_id` gap to fill differently — same new join as §10.1.

### 10.3 `GET /api/v1/reports/equipment-verify-checklist`

Pending §18's Owner Decision. If interpretation A (§7.3) is confirmed:

| | |
|---|---|
| **Method/path** | `GET /api/v1/reports/equipment-verify-checklist` (new) |
| **Purpose** | Return the current equipment master/status listing per §7.3(A) |
| **Permissions** | `VIEW_AND_REPORT_ROLES`, same rationale as §10.1 |
| **Request query params** | `equipment_category_id: str \| None`, `status: EquipmentStatus \| None`, `department_id: str \| None` (maps to the existing `Equipment.department_owner_id` FK) — **corrected per review minor finding:** `ward_id` is removed from this endpoint; `Equipment` has no direct Ward relationship (only `Equipment.department_owner_id` -> `Department`, and `Equipment.current_location_id` -> `Location` — neither is a Ward), and inventing a ward-level filter here would misrepresent a fact this system does not track. A future Equipment-to-Ward relationship, if ever confirmed, would need its own design, not a filter added here on an assumption. `limit`, `cursor` |
| **Response schema** | A **new**, equipment-shaped schema (not `TransactionOut`) — reuses the existing `EquipmentOut`-equivalent response shape already returned by `GET /equipment` (no new fields invented) |
| **Pagination/Sorting** | Same cursor convention as `GET /equipment`, unchanged |
| **Error responses** | `401`, `403`, `422` — no reversed-range check applies (no date range on this endpoint) |

If interpretation B is confirmed instead, this endpoint (and everything under it) is void and replaced by whatever the new verification-event workflow's own design specifies — not something this document can specify without the resolved decision (§7.3(B), §18).

### 10.4 `GET /api/v1/report-options/operators` (new; corrected per review findings PR17-M1, then PR17-M1R)

**Second correction (incremental review `4804643991`).** The prior revision of this endpoint returned every `User` row — the review found this was not actually an "operator" list at all: it included Read Only accounts, Administrators who have never dispatched or received anything, and any dormant account, none of which can legitimately appear as the actor on a Receive/Issue report row. Returning the full user roster to report-viewing roles is a real, unjustified account-directory exposure, not a narrower view of already-visible data (`TransactionOut` today exposes neither `borrower_user_id` nor `received_by_user_id` nor any operator name — this endpoint is genuinely new information, addressed explicitly in the Privacy / authorization rationale row below). This endpoint is **not a user directory** — it is corrected to return only identities that can legitimately appear as report operators.

| | |
|---|---|
| **Method/path** | `GET /api/v1/report-options/operators` (new) |
| **Purpose** | Return only the operators that can legitimately appear on a Receive/Issue report row, to populate the `operator_id` filter's `<select>` (§9) — a bounded, report-scoped lookup, not user management and not a general account directory. |
| **Source / population rule** | The response is exactly the set of **distinct `User` rows referenced by `BorrowTransaction.borrower_user_id` or `BorrowTransaction.received_by_user_id`, at least once, across all transactions** — `SELECT DISTINCT` over the union of both columns, joined to `User`, `NULL` values contributing nothing to the set (a transaction with no recorded operator, if any exists, simply contributes no entry). This is a real behavioral difference from the previous revision, not a smaller view of the same query: a Read Only account, an Administrator who has never performed a dispatch/receipt, or any other account with zero recorded operator activity is never returned, **regardless of role**, because role membership is not the inclusion test — actual transaction-history reference is. A newly hired Equipment Pool Staff member with zero recorded actions does not yet appear; this is accepted, not a bug — filtering by an operator with no history simply returns an empty report, exactly like filtering by any other value with no matches. |
| **Dispatch/receipt/both semantics** | One flat, unioned list, not two separate dispatch-only/receipt-only lists — usable directly by both the Issue Report's `operator_id` (`borrower_user_id`) filter and the Receive Report's `operator_id` (`received_by_user_id`) filter. An operator who has only ever dispatched (never received), selected on the Receive Report's filter, legitimately produces an empty result — not an error, not a hidden option — consistent with how every other filter combination with no matches already behaves in this system. |
| **Authorization** | `VIEW_AND_REPORT_ROLES` (Administrator, Equipment Pool Staff, Read Only) — the same gate as the report endpoints themselves (§10.1/§10.2/§14), deliberately not `ADMINISTRATOR_ONLY_ROLES` (which gates the existing `GET /users`, `backend/app/api/v1/users.py`). |
| **Response fields** | `id: str` (the stable identifier — `User.id`, never `employee_code`/`email`), `display_name: str` (`User.full_name` — already this hospital's real per-operator name; no separate Thai/English name pair exists on `User` today, so no fallback logic is invented beyond returning the one name field that exists), `is_active: bool` (`User.is_active`). **Deliberately excluded:** `employee_code`, `email`, `phone`, `role`, `password_hash`/any authentication metadata, `last_login_at`, and every other `User` column beyond the three above — none of which this filter needs, all of which `UserOut` (the Administrator-only shape, `backend/app/schemas/master_data.py`) already includes and this endpoint must not leak. |
| **Active/inactive behavior** | Both active and inactive *operators* (per the Source row above — never all users) are returned — `User` rows are never deleted, only deactivated (`is_active`, `backend/app/models/user.py`; no `deleted_at`/soft-delete column exists on `User`, confirmed by inspection), so a deactivated operator who has real transaction history remains fully resolvable by `id` for filtering historical reports. `is_active` is returned so the frontend can label a deactivated operator distinctly (§12) — the backend does not hide or filter them out of the bounded set. |
| **Search behavior** | Optional `q: str \| None` (bounded length, e.g. `max_length=100`, mirroring `GET /equipment/search-bcm`'s existing `q` convention), case-insensitive substring match on `full_name`, applied only within the bounded operator set above — never a search over the full user roster. |
| **Pagination (corrected per PR17-M1R — "unpaginated/unbounded" was a real gap, not adequately justified by system-wide transaction-scale evidence which says nothing about roster size)** | Real cursor pagination, matching this system's standard convention: `limit: int = 100 (le=200)`, `cursor: str \| None`. Ordered `full_name ASC, id ASC` (a stable alphabetical order, not `created_at` — appropriate for a name-driven `<select>`, distinct from the reports' own chronological cursor order, §10.1/§10.2) rather than left unbounded on an unproven roster-size assumption. |
| **Stable identifier** | `User.id` (UUID) — the same identifier `borrower_user_id`/`received_by_user_id` already store; never `employee_code` or `email`, consistent with this system's existing "internal UUID is the only relational reference" convention (`docs/BUSINESS_RULES.md`). |
| **Historical operators no longer active** | Remain resolvable (see Active/inactive behavior row above) — this preserves historical report readability ("who processed this shift's receipts six months ago" must still show a real name, not a broken/blank reference) without granting a deactivated account any new capability; this endpoint is read-only and grants no action of any kind. |
| **Error responses** | `401`, `403`, `422` (invalid `q` length) |
| **Privacy / authorization rationale (expanded per PR17-M1R — "no new information-exposure risk" was not an accurate claim and is withdrawn)** | This endpoint is a **genuine, deliberate expansion** of what Equipment Pool Staff and Read Only can see: today, no endpoint exposes any operator's identity for a dispatch or receipt event at all (`TransactionOut` carries no `borrower_user_id`/`received_by_user_id`-derived field). Justification, stated explicitly rather than assumed: (1) bounded strictly to real, historically-recorded Equipment Pool operators (Source row above), never the full account directory; (2) only a name, stable ID, and active flag — no contact information, role, or authentication metadata; (3) directly serves the cited, confirmed operational need (§6.1/§6.2 — "who processed this shift's receipts/issues," a real shift-handover question) rather than being exposed speculatively; (4) `docs/GLOSSARY.md` already defines "Operator" as a work-attribution concept for this exact class of action, so associating a name with an Equipment Pool dispatch/receipt is not a new *category* of fact this system tracks, only a newly-surfaced *view* of it via the reporting surface. Separately: `VIEW_AND_REPORT_ROLES` and `GET /transactions`'s `get_current_user`-only gate are, in this system's confirmed 3-role model, equivalent audiences in practice (every authenticated user holds exactly one of Administrator/Equipment Pool Staff/Read Only, and all three are already `VIEW_AND_REPORT_ROLES` members) — a moot point in any case for the two new operator-display-name fields (§8, §10.1, §11, corrected per PR17-H5), since they live on the report-only `ReportTransactionOut` schema, never on `TransactionOut`/`GET /transactions` at all. |

Avoided per instruction: no single unrestricted "report query" endpoint (§8, Option B rejected); no export/PDF/Excel/CSV endpoint (PR18 scope, §21); no widening of the existing Administrator-only `GET /users` endpoint; no full-user-directory exposure (corrected per PR17-M1R).

---

## 11. Backend Architecture

- **Service layer:** A new `app/services/report_query_service.py` (or, if the Repository Owner prefers, functions living directly in `app/api/v1/reports.py` mirroring the existing thin-router pattern already used there) composes `transaction_crud.search()` calls for Receive/Issue — it does not reimplement filtering, pagination, or the `business_date`/`shift` derivation. This mirrors `app/services/borrow_service.py`'s existing role (orchestration over CRUD, not a parallel query engine).
- **Query layer reuse:** `transaction_crud.search()` gains three new, additive capabilities this design requires — none change any existing caller's behavior: (1) an optional join to `Equipment` for `equipment_category_id` filtering (§9); (2) filtering by `borrower_user_id`/`received_by_user_id` (the `operator_id` filter, §9), additive to the existing `filters.append(...)` pattern; (3) **corrected per review finding PR17-H1:** a keyword-only `require_receipt: bool = False` parameter that, when `True`, unconditionally appends `BorrowTransaction.returned_at.is_not(None)` to `filters` — independent of the existing `if business_date_from is not None or business_date_to is not None or shift is not None` guard that gates the `business_date`/`shift` derivation itself. Only the Receive Report's own call site ever sets `require_receipt=True`; `GET /transactions` and the Issue Report never set it, so their behavior is unchanged byte-for-byte.
- **Report composition:** Each of the two report endpoints (§10.1/§10.2) is a thin FastAPI route calling one shared, parameterized `transaction_crud.search()` invocation with `event` pinned (and, for Receive only, `require_receipt=True`) — no per-report duplicate query building.
- **Operator lookup (§10.4, corrected per review finding PR17-M1, then narrowed per PR17-M1R):** A new, narrow `app/crud/user.py`-level query function (e.g. `list_operators(...)`) returning `id`/`full_name`/`is_active` for exactly the `User` rows that appear as `DISTINCT borrower_user_id` or `DISTINCT received_by_user_id` in `borrow_transactions` — a `SELECT DISTINCT` over the union of both FK columns, joined to `User`, cursor-paginated (`limit`/`cursor`, ordered `full_name ASC, id ASC`) per §10.4 — **not** every `User` row, and **not** unpaginated. No role/employee_code/email/phone/password fields, unlike the existing Administrator-only `UserOut` (`backend/app/schemas/master_data.py`).
- **Operator display on report rows (§8, §10.1, §11, corrected per review finding PR17-H5, superseding PR17-M1R's `TransactionOut`-extension approach):** `BorrowTransaction` gains two new relationships, `borrower_user: Mapped["User | None"] = relationship()` (via the existing `borrower_user_id` FK) and `received_by_user: Mapped["User | None"] = relationship()` (via the existing `received_by_user_id` FK) — neither exists on the model today. `transaction_crud.search()` extends its existing `selectinload(BorrowTransaction.equipment)` call with `selectinload(BorrowTransaction.borrower_user)`/`.received_by_user` (the identical eager-loading pattern already used for `equipment`, not a new one), and two new `@property`s on `BorrowTransaction` — `dispatch_operator_display_name`/`receipt_operator_display_name`, returning `self.borrower_user.full_name if self.borrower_user else None` (and the receipt equivalent) — mirror the existing `dispatch_business_date`/`receipt_business_date` computed-property pattern PR16 already established. **These two `@property`s feed `ReportTransactionOut` only (§10.1), never `TransactionOut`** — `TransactionOut`'s own field list (`app/schemas/transaction.py`) is not edited by this design; the ORM computed properties existing on the model is harmless on its own (matching the existing precedent that `receipt_outcome`/`dispatch_business_date` are model-level properties independent of which schema chooses to read them), but only `ReportTransactionOut` actually reads these two new ones.

**Architecture layering (new, per review finding PR17-H5 — "document clearly").**

```
Transaction domain (BorrowTransaction, existing)
        |
        v
Shared TransactionOut (existing PR16/PR17-unmodified schema
        |                 -- used by GET /transactions, GET /transactions/{id})
        v
Report composition (transaction_crud.search(), event pinned,
        |             require_receipt for Receive -- §8, §11)
        v
Report-specific DTO: ReportTransactionOut
        |             (extends TransactionOut + dispatch/receipt
        |              operator_display_name -- report-only fields)
        v
Report endpoints: GET /reports/receive, GET /reports/issue
        |             (§10.1, §10.2 -- Page[ReportTransactionOut])
```

Presentation/reporting-only concerns (the two operator-display fields) are introduced strictly at the DTO layer, one level below the shared `TransactionOut` contract, and are consumed only by the two report endpoints at the bottom of this chain — they never leak upward into `TransactionOut` or into `GET /transactions`'s existing contract.
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
- **Operator selection (corrected per review finding PR17-M1):** A `<select>` populated from `GET /report-options/operators` (§10.4) — the same label+`<select>` pattern as every other filter on this screen, not a free-text/UUID-entry field. Inactive operators remain selectable/resolvable for historical filtering (§10.4) but are visually distinguished (e.g. an "(ไม่ใช้งานแล้ว)"/"inactive" suffix on the option label) so staff are not confused into thinking a deactivated account is still an active operator.
- **Order preservation (corrected per review finding PR17-H3):** The frontend renders each fetched page in exactly the order the backend returned it (§10.1's Sorting row) and never re-sorts a page, or the accumulated set of pages, client-side — "load more" strictly appends the next backend-ordered page.
- **Printing workflow:** Not in PR17 (§13, §21) — deferred to Roadmap PR18 in full.
- **Future export workflow:** Not in scope (§21); PR18-dependent, exactly as the authoritative source scopes it.

No dashboard-heavy UI, no chart, no new component library (§21). Business logic (the shift/business-date derivation, the receipt-vs-dispatch event basis) is never computed in the frontend — every report screen only displays/filters values the backend already derived, matching PR16's own non-negotiable rule (§5).

---

## 13. Printing (Deferred to Roadmap PR18)

**Corrected per review finding PR17-H2.** The authoritative source (`docs/audits/04-consolidated-implementation-plan.md`, §2) assigns "PDF export, Excel export, and print-ready Hard Copy templates" to Roadmap PR18, not PR17 — and that includes browser-native print styling, not only a PDF library. The prior draft of this document incorrectly proposed a `@media print` stylesheet, a print-specific filter-summary header, and a dedicated implementation slice for PR17 itself; all of that is removed.

PR17's own scope, restated: on-screen operational reports only (§12). This design takes exactly one, minimal position for PR18's benefit, without implementing anything now: **the report definitions (§7) and API responses (§10) do not preclude a future print/export layer** — every report returns already-paginated, already-filtered JSON data (§10) that a future PR18 design can format for print, PDF, Excel, or CSV without requiring PR17's own endpoints, query functions, or on-screen components to change. That is the full extent of what this document says about printing; it defines no print rendering, no browser print workflow, no PDF generation, no print-specific API endpoint, and no print-specific frontend component (§21).

---

## 14. Security

- **Authorization:** `VIEW_AND_REPORT_ROLES` for all three new report endpoints (§10) and for the new `GET /report-options/operators` lookup (§10.4, corrected per review findings PR17-M1/PR17-M1R) — chosen deliberately over `GET /transactions`'s looser `get_current_user`-only gate, because these are named *report* surfaces analogous to the existing `/reports/export` (which already requires `VIEW_AND_REPORT_ROLES`), not the general-purpose transaction list. In this system's confirmed 3-role model, `VIEW_AND_REPORT_ROLES` and `get_current_user` are equivalent audiences in practice (every authenticated user holds exactly one of the three roles, all three are `VIEW_AND_REPORT_ROLES` members) — the choice is a naming/surface convention, not a real access restriction. `GET /report-options/operators` is deliberately **not** gated by `ADMINISTRATOR_ONLY_ROLES` (unlike `GET /users`) — Equipment Pool Staff and Read Only, both authorized to view these reports, need this lookup to use the `operator_id` filter at all (§9).
- **Visibility (corrected per review finding PR17-M1R, mechanism further corrected per PR17-H5 — the prior claim of "no new information-exposure risk" was inaccurate and is withdrawn):** `ReportTransactionOut` (§8, §10.1, §11 — **not** `TransactionOut`, corrected per PR17-H5) gains two genuinely new fields (`dispatch_operator_display_name`/`receipt_operator_display_name`), and `GET /report-options/operators` (§10.4) is a genuinely new lookup surface — today, no endpoint exposes any operator's identity for a dispatch or receipt event at all. Both are scoped strictly to the two new report endpoints (`GET /reports/receive`/`GET /reports/issue`); `TransactionOut` and `GET /transactions`/`GET /transactions/{id}` are unaffected and expose nothing new. This is a deliberate, bounded expansion of the *reporting surface specifically*, not an oversight and not a general-purpose contract change: see §10.4's "Privacy / authorization rationale" row for the full justification (bounded to real recorded operators only, name/id/active-flag only, serves the cited §6.1/§6.2 operational need, consistent with `docs/GLOSSARY.md`'s existing "Operator" concept). The existing equipment response shape (Verify Checklist, interpretation A) still introduces no new field, unchanged from the prior revision.
- **Future RBAC compatibility:** No new role or capability tier is introduced; if a future Roadmap PR narrows or widens `VIEW_AND_REPORT_ROLES` itself, these three endpoints inherit that change automatically, having never defined their own bespoke tuple.
- **Audit considerations:** No new write path exists anywhere in this design (§11) — reads are not audited today (consistent with every existing read endpoint, PR16 §12), and this design does not change that.
- **Query parameter validation:** All new filters (`operator_id`, `equipment_category_id`, `status`) are ordinary typed FastAPI query parameters (UUID/enum), rejecting an invalid value with a standard `422` — no free-text injection surface, matching every existing filter's validation shape.

---

## 15. Performance

- **Expected data volume:** Unchanged from PR16's confirmed scale assumption (`docs/PROJECT_MEMORY.md`: "low hundreds of devices, thousands of transactions per year") — these three reports read the same tables PR16 already queries, at the same scale.
- **Query strategy:** Reuses the PR14B composite `(created_at DESC, id DESC)` pagination index for ordering (§7.2/§10.1). **Corrected per review minor finding:** `borrowed_at` is indexed (`index=True`, `backend/app/models/transaction.py`); `returned_at` is **not** — the prior draft incorrectly claimed both were. The new `require_receipt` predicate (§8/§11) and the `event=receipt`/`business_date`/`shift` filters read `returned_at` without a dedicated index today. A raw-column index would not necessarily help the derived `business_date`/`shift` expressions in any case (PR16 §13's own point: a derived expression is not automatically served by an index on the underlying raw column) — real `EXPLAIN` evidence, not an assumption, decides whether any index is needed (see Indexes row below).
- **Pagination:** Unchanged cursor convention, `limit <= 200` per page, bounding response size regardless of filter breadth — identical to every existing paginated endpoint.
- **Indexes:** No new index is proposed pre-emptively. `borrower_user_id` and `received_by_user_id` are already foreign-key columns without a dedicated index today (confirmed by inspection of `backend/app/models/transaction.py`); whether the new `operator_id` filter needs one is an implementation-time question gated on real `EXPLAIN (ANALYZE, BUFFERS)` evidence, per PR14B's established evidentiary discipline — not assumed or pre-built here.
- **Future optimization:** Not needed at confirmed scale; flagged for the same future-evidence-gated review PR16 §13 already established for its own derivation expression.

---

## 16. Future Compatibility

This design must, and does, support future work without requiring a redesign of anything specified here:

- **Dashboard/BI/analytics:** These three reports return plain paginated JSON (§10) — a future dashboard/BI layer can consume the same endpoints or the same underlying `transaction_crud.search()`/equipment-query functions without any contract change here.
- **Scheduled reports/notifications:** A future scheduled-report job would call these same endpoints' underlying query functions on a timer — no redesign needed, since the query layer (§11) is already decoupled from the HTTP layer.
- **Export (PR18):** PR18 consumes the same report definitions (§7) and, most likely, the same underlying query functions (§11) to produce PDF/Excel/CSV — this design's endpoints already return exactly the row-level data PR18 would need to format.
- **Printing (PR18):** Same as Export above — PR18's print/Hard Copy design consumes PR17's report definitions and query functions; PR17 defines no print rendering itself (§13).

---

## 17. Suggested Implementation Slices

**Revised per review findings PR17-H2 (no printing slice in PR17) and PR17-M1 (operator lookup path).** Each slice is independently reviewable, matching the lettered-slice/numbered-slice precedent already established for PR7/PR8/PR9/PR14/PR15/PR16.

**Slice 1 — Report Domain and Query Semantics.**
- Scope: `transaction_crud.search()` gains, additively: the `equipment_category_id` join (§9/§11), the `operator_id` filter (§9/§11), and the `require_receipt` unconditional-predicate parameter (§8/§11, corrected per PR17-H1) that enforces §7.1's Receive Report canonical rule regardless of which other filters are present. Canonical Receive Report rules (§7.1) and Issue Report rules (§7.2), including the completed-receipt exclusion logic and the confirmed backend-only deterministic ordering (§7.2/§10.1, corrected per PR17-H3). No shared reporting-query abstraction beyond what already exists (§11).
- Dependencies: None beyond the already-merged PR16 baseline.
- Why this boundary: isolates all new query logic from any HTTP-layer or frontend change, testable in isolation with PostgreSQL evidence (§15) before any endpoint exists to call it — including dedicated regression tests for the five PR17-H1 scenarios (§7.1) and for cursor-pagination correctness (no duplicate/missing rows, deterministic tie-break) under the confirmed ordering (§7.2).

**Slice 2 — Report APIs and Lookup Options.**
- Scope: `GET /reports/receive`, `GET /reports/issue` (§10.1/§10.2), and `GET /report-options/operators` (§10.4, corrected per PR17-M1) — `VIEW_AND_REPORT_ROLES` gate on all three, validation, error responses, pagination.
- Dependencies: Slice 1.
- Why this boundary: the API contract (including the operator-lookup path the frontend needs before it can offer the `operator_id` filter at all) is independently reviewable against §7's canonical definitions before any frontend consumes it — mirrors PR16 Slice 3's own boundary (query engine before endpoint).

**Slice 3 — Frontend Report Controls and Results.**
- Scope: `/reports/receive`, `/reports/issue` screens per §12 — Thai-first navigation and labels, business-date/shift/ward/category/operator filter controls (operator populated from Slice 2's new lookup endpoint), loading/empty/error states, on-screen result rendering that strictly preserves backend order (§7.2/§10.1/§12, corrected per PR17-H3). No printing (§13).
- Dependencies: Slice 2.
- Why this boundary: mirrors PR16 Slice 4's own boundary (frontend strictly after the API contract it consumes is final).

**Slice 4 — Equipment Verify Checklist.**
- Scope: `GET /reports/equipment-verify-checklist` (§10.3) and its frontend screen, **only** if Owner Decision #1 (§18) has been resolved to interpretation A by then. If Owner Decision #1 remains unresolved when Slices 1-3 are ready to ship, this slice is explicitly **blocked/deferred** — Receive and Issue ship without it, and this slice is picked up as its own separately-approved follow-up once the decision is made. No policy is invented to unblock it early.
- Dependencies: Slices 1-3 (for the shared report-page pattern) and Owner Decision #1 (§18).
- Why this boundary: isolates the one genuinely undecided report from the two fully-specified ones, so Owner Decision #1 (§18) blocks only this slice, never Receive/Issue (§18's own "not blocking for Receive/Issue" framing, unchanged).

**Final Slice — Governance Synchronization (corrected per review finding PR17-H4).**
- Scope: The standard post-merge governance sync (`docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `docs/DECISION_LOG.md`, `knowledge/CONTEXT.md`, `knowledge/PROJECT_MEMORY.md`, `knowledge/CHANGE_HISTORY.md` — all six current-state documents, matching the completed Roadmap PR16 sync's actual final scope, GitHub PR #62) recording Roadmap PR17 as complete, advancing the next planned item to Roadmap PR18.
- **This Final Slice may only run once the *entire* authoritative PR17 scope — Receive, Issue, and Equipment Verify Checklist (`docs/audits/04-consolidated-implementation-plan.md`'s PR17 entry, §2) — is resolved, not merely once Slices 1-3 are done.** Concretely, exactly one of the following must be true before this slice runs:
  1. Owner Decision #1 (§18) resolves to interpretation A, **and** Slice 4 (Equipment Verify Checklist) has merged; or
  2. Owner Decision #1 (§18) resolves to interpretation B or C, **and** a separate, explicitly Repository-Owner-approved governance decision formally amends Roadmap PR17's active scope to exclude Equipment Verify Checklist, recording the omitted or redirected workflow as its own, distinctly tracked future item (mirroring how Shift Sessions/Standby Snapshots are tracked today, `docs/ROADMAP.md` "Confirmed future work") — not silently dropped.
- **If neither condition holds:** Slices 1-3 remain individually mergeable on their own usual merits (they do not require Owner Decision #1 to be resolved, §18) — but this Final Slice does not run, no governance-sync PR is opened claiming "Roadmap PR17 complete," and the Roadmap's "next planned item" is **not** advanced to PR18. The Roadmap baseline instead reflects exactly what has actually merged (e.g. "Roadmap PR17 in progress — Receive/Issue slices merged; Equipment Verify Checklist blocked on Owner Decision #1"), never a claim of completion the authoritative scope does not support.
- Dependencies: All of Receive, Issue, and Equipment Verify Checklist resolved per the two conditions above — not merely "all approved slices merged."
- Why this boundary: per this repository's own established convention (confirmed by inspecting every prior design document — none touches roadmap/governance files itself; that happens only in the dedicated post-merge sync step, §22) — and, per this correction, governance completion must track the Roadmap's actual authoritative scope, never a partial subset dressed up as the whole.

No slice combines database + broad API + frontend + governance changes, and **no slice in this plan implements printing** (§13, §21) — printing remains entirely Roadmap PR18.

---

## 18. Owner Decisions

**Three fix rounds — review `4804227912` (PR17-H1/H2/H3, PR17-M1), incremental review `4804643991` (PR17-M1R, PR17-H4, a §7.1 wording contradiction), and independent review `4804810876` (PR17-H5 — operator display fields moved off the shared `TransactionOut` schema onto a new report-only `ReportTransactionOut`) — have now been resolved. Owner Decision #1 below is explicitly preserved, unresolved, and unaltered across all three rounds — not addressed, guessed, or narrowed, per this task's explicit instruction in each round.**

**Owner Decision #1 — Equipment Verify Checklist definition (BLOCKING for Verify Checklist only, not for Receive/Issue).**

No hospital business process behind "Equipment Verify Checklist" is confirmed anywhere in this repository's authoritative documentation (§2, §7.3). This blocks Slice 1's Verify Checklist sub-scope (and everything downstream of it) exactly the way PR16's Day/Night boundary blocked its own Slice 1 until answered. The Repository Owner needs to choose between:

- **(A) Equipment master-data/status-history checklist** (§7.3(A)) — implementable within PR17's existing reports-only scope, no new workflow, ready to build once confirmed.
- **(B) A genuine physical-verification event workflow** (§7.3(B)) — new, unscheduled Roadmap scope requiring its own design (workflow, data model, migration), not something PR17's "reports" mandate covers; if chosen, PR17 should ship Receive/Issue only (Slices 1-5 above minus the Verify Checklist sub-scope) and Equipment Verify Checklist becomes a new, separately numbered future Roadmap item, mirroring how Shift Sessions/Standby Snapshots are tracked today (`docs/ROADMAP.md` "Confirmed future work").
- **(C) Defer entirely** — ship Receive/Issue only in PR17, explicitly leave Equipment Verify Checklist unscheduled pending further business-process discovery, revisiting the Roadmap PR17 acceptance criterion's own wording if needed.

This document recommends **(A)** as the option that satisfies PR17's literal acceptance criterion ("provide... Equipment Verify Checklist... reports") without inventing a new workflow, while flagging its own honesty gap (§7.3(A)'s "why this is not really 'verification'") plainly rather than silently.

**Owner Decision #2 — `operator_id` filter and operator-display role scope (non-blocking, low risk; rationale corrected per review finding PR17-M1R).** Should the `operator_id` filter and the new operator display names (§9, §10.4, §14) be restricted to Administrator-only (a "who did this" audit-adjacent question) or left open to all `VIEW_AND_REPORT_ROLES` (an ordinary operational filter, like ward)? **Correction:** this is a genuinely new information exposure (§14's "Visibility" bullet), not — as the prior revision incorrectly claimed — already-visible data. This design still recommends leaving it open to all `VIEW_AND_REPORT_ROLES`, on the corrected grounds stated in §10.4's Privacy / authorization rationale row (bounded to real recorded operators, minimal fields, justified by the cited shift-handover need) — flagged so the Repository Owner can override with a stricter (e.g. Administrator-only) reading if preferred, now with the accurate picture of what is actually being exposed.

**Owner Decision #3 — Report-specific role gate (`VIEW_AND_REPORT_ROLES`) vs. `get_current_user`-only (non-blocking, low risk).** §14 recommends the stricter, existing `/reports/export` precedent. If the Repository Owner instead wants these three reports to match `GET /transactions`'s broader `get_current_user`-only gate (since the underlying data is already visible there), that is a one-line change to §10/§14, not a redesign.

---

## 19. Risks

| Risk | Category | Mitigation |
|---|---|---|
| Equipment Verify Checklist is built on an assumed interpretation that turns out to be wrong | Business | Owner Decision #1 (§18) is a hard blocker for that sub-scope only; Receive/Issue can ship independently and are not blocked by it (§17, Slice boundaries). |
| `equipment_category_id`/`operator_id` joins, and the new unconditional `require_receipt` predicate, on `transaction_crud.search()` degrade query performance at a future, larger scale | Architecture/Performance | Evidence-gated per §15 (PR14B precedent) — not assumed, verified with real `EXPLAIN` output at implementation time before any index is added. |
| A future PR18 export format needs a leaner or differently-shaped response than `ReportTransactionOut` provides | Architecture/Future migration | §8/§11 flagged this explicitly as an accepted, revisitable trade-off, not a silent gap — PR18's own design can introduce its own export-specific slim DTO/schema then, informed by real export requirements rather than speculation now. That future schema is a new type, same as `ReportTransactionOut` was for PR17 — PR18 has no need to, and must not, modify the existing `TransactionOut` contract merely because reporting/export needs exist. |
| The existing, unfiltered `/reports/export`/`ReportsPage.tsx` surface (§2) becomes confusing to operate alongside three new named reports | Compatibility | Explicitly left untouched and unrenamed by this design (§8, §12); PR18 is the natural point to reconcile/replace it once it has to add export to the named reports anyway — flagged here, not silently deferred. |
| A newly hired or newly assigned operator cannot be filtered-by on Receive/Issue reports until they have at least one recorded dispatch or receipt (§10.4's Source / population rule, corrected per PR17-M1R) | Operational | Accepted, not a defect — the bounded operator list is deliberately history-driven, not role-driven, to avoid re-introducing the "expose the whole roster" problem this correction fixes; filtering by a not-yet-active operator is simply unavailable until their first recorded action, at which point they appear automatically. |
| A future, larger operator roster makes the now-paginated `GET /report-options/operators` (§10.4) response awkward to browse in a single `<select>` | UX/Future | The endpoint is genuinely paginated (§10.4, corrected per PR17-M1R) — a future frontend revision can add incremental search/scroll if the bounded operator set ever grows large enough to need it; not assumed a problem now. |

**Confirmed resolved by this fix round (review `4804227912`):** PR17-H1 (Receive Report's `returned_at IS NOT NULL` exclusion is now unconditional, §7.1/§8/§11), PR17-H2 (no printing implementation or slice remains in PR17, §13/§17/§21), PR17-H3 (ordering is backend-only, matching the existing cursor contract, §7.2/§10.1/§12), and PR17-M1 (the `operator_id` filter now has a real, role-appropriate lookup path, §10.4).

**Confirmed resolved by this second fix round (incremental review `4804643991`):** PR17-M1R (the operator lookup is now bounded to real, historically-recorded operators — never the full `User` roster — is genuinely paginated, and its PII exposure is explicitly documented and justified rather than claimed to be risk-free, §10.4/§14/§18 Owner Decision #2), PR17-H4 (governance completion now explicitly requires the entire authoritative PR17 scope — Receive, Issue, *and* Equipment Verify Checklist — not merely Slices 1-3, §17 Final Slice), and the §7.1 wording contradiction (the corrected, unconditional `require_receipt` enforcement no longer coexists with a sentence describing it as "not a special-case exclusion," §7.1).

**Non-risk, explicitly confirmed by this design's own scope check:** No new lifecycle state, no QR redesign, no MEMS/Recall Monitor coupling, no Analytics/BI surface, no export/PDF/Excel/CSV implementation, no printing implementation, and no application/frontend/migration code was introduced by this document (§23, Final Validation).

---

## 20. Acceptance Criteria

**Business**
- Each of the three reports' canonical definition (§7) is implemented exactly as specified — no transaction silently included/excluded outside that definition.
- Restated from the authoritative source: "Each report uses the same reporting metadata and presents consistent date/shift filtering" (`docs/audits/04-consolidated-implementation-plan.md`, PR17 entry) — satisfied by Receive/Issue reusing PR16's `business_date`/`shift` unmodified (§5); Verify Checklist's relationship to this criterion is exactly what Owner Decision #1 (§18) must resolve.

**Receipt semantics (corrected per review finding PR17-H1)**
- OPEN transactions never appear in the Receive Report, under any combination of filters, including no filter at all.
- Receipt eligibility (`returned_at IS NOT NULL`) does not depend on the presence of `business_date_from`/`business_date_to`/`shift` — it is enforced unconditionally (§7.1, §8, §11).
- Only records with a valid, completed receipt event (a non-null `returned_at`) are included; a `CLOSED` transaction with `receipt_outcome = defective` is included exactly like `usable` (§7.1).

**API**
- `GET /reports/receive`/`GET /reports/issue` match §10's full contract, including the pinned (non-client-settable) `event` basis, the always-on `require_receipt` predicate for Receive (§8, §10.1), and the reused `business_date_from > business_date_to` validation.
- No existing endpoint's contract (`GET /transactions`, `GET /transactions/{id}`, `GET /reports/export`, `GET /users`) changes in any respect.
- `GET /reports/receive` and `GET /reports/issue` return `Page[ReportTransactionOut]`, never `Page[TransactionOut]` (corrected per review finding PR17-H5, §8, §10.1, §10.2).

**API/schema boundary (new, per review finding PR17-H5)**
- `TransactionOut` (`app/schemas/transaction.py`) is not modified by this design — every field it has today, it still has, unchanged, and no field is added or removed.
- `GET /transactions` and `GET /transactions/{id}` remain fully backward compatible — their response bodies are byte-for-byte identical to today's, with no operator field of any kind.
- `dispatch_operator_display_name`/`receipt_operator_display_name` exist only on `ReportTransactionOut`, and are returned only by `GET /reports/receive`/`GET /reports/issue` — never by any other endpoint.
- No reporting-presentation field (operator display name, or any future report-only field) is added to `TransactionOut` or to any other shared, non-report-specific schema.

**Backend**
- `transaction_crud.search()`'s new filter/predicate capabilities (§11) are additive, tested in isolation, and do not alter existing filter behavior or any existing caller's results.
- No duplicated business-date/shift derivation logic exists anywhere in the new report query paths (§8, Option A).

**Pagination and sorting (corrected per review finding PR17-H3)**
- The backend is the only source of report ordering — `(created_at DESC, id DESC)`, identical to `GET /transactions`; no alternative `ORDER BY` is introduced by this design.
- The frontend preserves and never re-sorts the returned order, on a single page or across accumulated "load more" pages (§12).
- Cursor pagination produces no duplicate and no missing records across pages, verified by dedicated regression tests (§17, Slice 1).
- Ordering is deterministic when timestamps are equal, via the existing `id DESC` tie-break — unchanged from `GET /transactions`.

**Operator lookup (corrected per review finding PR17-M1, then bounded per PR17-M1R)**
- Equipment Pool Staff can successfully call `GET /report-options/operators` (§10.4) and populate the `operator_id` filter.
- Read Only users can do the same.
- A user with no role at all (unauthenticated, or a role outside `VIEW_AND_REPORT_ROLES`) is rejected with `401`/`403`.
- The response never includes `employee_code`, `email`, `phone`, `role`, or any authentication-related field.
- An operator who has since become inactive remains present, correctly labeled `is_active: false`, and resolvable for historical report filtering (§10.4).
- **Unrelated users never appear:** a `User` row with zero recorded `borrower_user_id`/`received_by_user_id` references — including a Read Only account, or an Administrator who has never dispatched/received — is never returned by `GET /report-options/operators` (§10.4).
- **Report roles cannot enumerate all accounts:** the response is always bounded to the distinct-operator set (§10.4's Source / population rule), never the full `User` table, regardless of `q` or pagination parameters.
- **Historical operators remain available:** an operator who has since become inactive, or whose role has changed, remains listed and resolvable by `id` as long as their transaction-history reference still exists (§10.4).
- **Information exposure is limited to operational needs:** only `id`/`display_name`/`is_active` are returned, and the exposure is justified against the cited §6.1/§6.2 operational need, not assumed (§10.4's Privacy / authorization rationale row, §14).
- Report rows (`ReportTransactionOut`, corrected per PR17-H5, §8/§10.1/§11) correctly show `dispatch_operator_display_name`/`receipt_operator_display_name` for every row where the corresponding user FK is set, and `None` where it is not — `TransactionOut`/`GET /transactions` rows show neither field, since they are not part of that schema.

**Governance completion (new, per review finding PR17-H4)**
- The Final Slice (§17) never runs, and no governance-sync PR claiming "Roadmap PR17 complete" is opened, unless every one of Receive, Issue, and Equipment Verify Checklist is resolved per §17's Final Slice's two explicit conditions.
- Slices 1-3 (Receive/Issue) remain independently mergeable regardless of Owner Decision #1's (§18) status — their mergeability is unaffected by this criterion.
- If Owner Decision #1 remains unresolved when Slices 1-3 are ready, the Roadmap correctly reflects "PR17 in progress," never "PR17 complete" or "next item is PR18."

**Scope control (corrected per review finding PR17-H2)**
- No printing implementation exists anywhere in PR17 — no `@media print` stylesheet, no print-specific component, no print-specific endpoint.
- No PDF, Excel, or CSV implementation is included.
- Future printing/export is explicitly and only deferred to Roadmap PR18 (§13, §21).

**Frontend**
- The report screens (§12) follow the existing `EquipmentDetailPage.tsx` filter/state pattern exactly — same URL-backed applied-state mechanism, same loading/empty/error distinction.
- No business logic (date/shift/event-basis computation, or result ordering) exists in any new frontend code.

**Testing** (restated as a requirement for the eventual implementation PR, not satisfied by this design document itself)
- Backend: filter-combination tests for each new/reused parameter on each report endpoint; PostgreSQL evidence for the new joins/predicate; the §7.1 five explicit Receive Report scenarios (event=receipt with no date filters, with date filters, with shift filter, an OPEN transaction excluded in every case, a completed transaction with valid `returned_at` included in every case); same-day issue/receive both appearing exactly once; defective receipt included; empty-result pages; cursor-pagination duplicate/missing-row and deterministic-tie-break regression tests (§17, Slice 1).
- Operator lookup: authorized-role success, unauthorized-role rejection, inactive-operator inclusion, no sensitive field present in the response (§10.4).
- **API/schema boundary (new, per review finding PR17-H5):** an explicit negative test asserting `GET /transactions` and `GET /transactions/{id}` response bodies contain neither `dispatch_operator_display_name` nor `receipt_operator_display_name` (nor any other new field), both before and after the report endpoints are implemented; a positive test confirming `GET /reports/receive`/`GET /reports/issue` responses do include both fields, correctly populated.
- Frontend: component tests per report screen mirroring `EquipmentDetailPage.test.tsx`'s existing coverage pattern (filter application including operator selection, URL persistence, loading/empty/error states, backend-order preservation across "load more").

**Documentation**
- This design document itself, reviewed and approved, is the Slice 0 deliverable; §17's Final Slice is the only point at which `docs/ROADMAP.md`/`docs/ROADMAP_STATUS.md`/`docs/DECISION_LOG.md`/`knowledge/CONTEXT.md`/`knowledge/PROJECT_MEMORY.md`/`knowledge/CHANGE_HISTORY.md` are touched — and, per the corrected Governance completion criteria above, only once every one of Receive, Issue, and Equipment Verify Checklist is resolved (§17, §22).

**Operational acceptance**
- A shift handover can be conducted using only the Receive/Issue reports' on-screen output without needing to fall back to the unfiltered `/reports/export` CSV/XLSX. Printing itself is not part of this acceptance criterion (§13) — it is Roadmap PR18 scope.

---

## 21. Out of Scope

Explicitly excluded from PR17 (and from this design document):

- **Printing implementation of any kind, including browser-native print styling (`@media print`), a print-specific filter-summary header, or any other print-ready presentation (corrected per review finding PR17-H2)** — Roadmap PR18 owns all of "PDF export, Excel export, and print-ready Hard Copy templates" (`docs/audits/04-consolidated-implementation-plan.md`), and this document defines no part of it, not even a browser-CSS-only version (§13).
- BI, analytics, dashboards, KPI widgets.
- Scheduled reports, notifications, email delivery.
- PDF implementation, Excel implementation, CSV implementation (PR18).
- Offline mode.
- Recall Monitor, MEMS, or any coupling to either.
- Any change to the existing `/reports/export`/`ReportsPage.tsx` surface.
- Any change to Roadmap PR16's reporting foundation, derivation logic, or the `GET /transactions` contract.
- **Any modification to the shared `TransactionOut` schema, or to `GET /transactions`/`GET /transactions/{id}`'s response contract, of any kind (corrected per review finding PR17-H5)** — operator display names are a report-only presentation concern, added exclusively to the new `ReportTransactionOut` schema (§8, §10.1, §11) consumed only by `GET /reports/receive`/`GET /reports/issue`; they never leak into the shared transaction schema or its existing, general-purpose endpoints.
- Any change to the existing, Administrator-only `GET /users` endpoint — the new `GET /report-options/operators` (§10.4) is additive, not a widening of it.
- **A full user-directory/account-listing surface of any kind (corrected per review finding PR17-M1R)** — `GET /report-options/operators` (§10.4) returns only the bounded, distinct-operator set actually referenced by transaction history, never every `User` row; this document defines no endpoint that enumerates all accounts to a non-Administrator role.
- Any client-side/frontend re-ordering of report results (§7.2, §10.1, §12).
- **Declaring Roadmap PR17 complete, or advancing the Roadmap's "next planned item" to PR18, while Equipment Verify Checklist remains unresolved (corrected per review finding PR17-H4)** — §17's Final Slice may only run once every one of Receive, Issue, and Equipment Verify Checklist is resolved per its two explicit conditions; Slices 1-3 merging on their own is not, by itself, "PR17 complete."
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

Governance synchronization occurs only after implementation is complete — and, per the correction in §17's Final Slice (review finding PR17-H4), "complete" means every one of Receive, Issue, and Equipment Verify Checklist is resolved, not merely Slices 1-3 — exactly as it did for PR16 (design PR #56 touched no governance file; the dedicated governance sync, GitHub PR #62, ran only after all four implementation slices merged).

---

## 23. Final Validation

Verified before this third revision was finalized (independent review `4804810876`, finding PR17-H5):

- [x] Only design documentation changed — `git status --short` on this branch shows exactly one modified file, this document itself; no other file exists in the diff.
- [x] No source code changed.
- [x] No test code changed.
- [x] No migrations changed.
- [x] No API implementation changed — every endpoint in `backend/app/api/v1/transactions.py`, `backend/app/api/v1/reports.py`, `backend/app/api/v1/users.py`, and every other existing router is untouched; §10's endpoints are proposals only.
- [x] No governance completion files changed — `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `docs/DECISION_LOG.md`, `knowledge/CONTEXT.md`, `knowledge/PROJECT_MEMORY.md`, `knowledge/CHANGE_HISTORY.md` are all untouched (§22).
- [x] `TransactionOut` is unchanged — verified by re-reading every remaining reference to it (§1, §2, §5, §6.2, §8, §10.1, §10.3, §11, §14, §16, §18, §19, §21): none propose adding, removing, or modifying any of its fields; the two operator-display fields now live exclusively on the new `ReportTransactionOut` (§8, §10.1, §11).
- [x] Existing transaction APIs remain backward compatible — §20's new "API/schema boundary" criteria block and §21's new Out of Scope bullet both state explicitly that `GET /transactions`/`GET /transactions/{id}` response bodies are byte-for-byte unchanged; §20's Testing block now requires an explicit negative test proving it.
- [x] Report endpoints expose operator display names through the report schema only — §10.1/§10.2 state `Page[ReportTransactionOut]`, not `Page[TransactionOut]`; §11's new Architecture layering diagram shows the fields introduced strictly at the report-DTO layer, below the shared schema.
- [x] No reporting presentation field leaks into shared transaction DTOs — confirmed across §8 (Option A), §10.1 (Response schema row), §11 (Operator display bullet + Architecture diagram), §14 (Visibility bullet), §20 (API/schema boundary criteria), and §21 (new Out of Scope bullet); all six now consistently describe `ReportTransactionOut` as the sole location of these fields.
- [x] Design documents internally consistent — every reference to the operator-display mechanism across the whole document was re-swept (`grep` for `TransactionOut`, `dispatch_operator_display_name`, `receipt_operator_display_name`) and updated to the corrected `ReportTransactionOut` mechanism; no stray sentence still describes extending `TransactionOut` itself.
- [x] Owner Decision #1 (§18) remains open — unaltered content across all three fix rounds.
- [x] Printing remains deferred to PR18 — unaffected by this round's changes.
- [x] `git diff --check` passes — no whitespace errors.
- [x] All prior-round findings (PR17-H1/H2/H3/M1, PR17-M1R/H4, the §7.1 wording contradiction) remain resolved and unregressed by this round's edits.

---

## 24. Deliverables

1. **Files changed:** `docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md` (this document) — the only file modified by this third incremental fix.
2. **Revised schema diagram (§11, new "Architecture layering" subsection):**
   ```
   Transaction domain (BorrowTransaction, existing)
           |
           v
   Shared TransactionOut (existing PR16/PR17-unmodified schema
           |                 -- used by GET /transactions, GET /transactions/{id})
           v
   Report composition (transaction_crud.search(), event pinned,
           |             require_receipt for Receive -- §8, §11)
           v
   Report-specific DTO: ReportTransactionOut
           |             (extends TransactionOut + dispatch/receipt
           |              operator_display_name -- report-only fields)
           v
   Report endpoints: GET /reports/receive, GET /reports/issue
                 (§10.1, §10.2 -- Page[ReportTransactionOut])
   ```
   Presentation/reporting-only fields are introduced strictly at the DTO layer, one level below the shared `TransactionOut` contract, and consumed only by the two report endpoints at the bottom of the chain.
3. **Updated API contract (§10.1, §10.2):** `GET /reports/receive`/`GET /reports/issue` now explicitly return `Page[ReportTransactionOut]`, not `Page[TransactionOut]`. `GET /transactions`/`GET /transactions/{id}` (unchanged, still `TransactionOut`) are called out explicitly as unaffected in both the Response schema rows and the new §20 API/schema boundary criteria.
4. **Confirmation `TransactionOut` is unchanged:** confirmed — `app/schemas/transaction.py`'s `TransactionOut` gains no field; the two operator-display fields exist only on the new, report-only `ReportTransactionOut`, which extends it (inherits its fields, adds two more) without modifying it. §23's checklist verifies every remaining reference in the document is consistent with this.
5. **Findings resolved:** PR17-H5 -> §8 (Option A trade-off), §10.1 (Response schema row), §11 (Operator display bullet + new Architecture layering diagram), §14 (Visibility bullet), §20 (new API/schema boundary criteria + Testing addition), §21 (new Out of Scope bullet), §23, §24.
6. **Validation results:** §23.
7. **New head SHA:** recorded in the PR's own commit/push metadata (outside this document's scope to self-report).

*No production code was written or modified to produce this revision. No migration was generated. No application file was modified. No reporting library was introduced. Every claim about existing code cites the specific file inspected (§2), and the additional citations from prior rounds — `backend/app/api/v1/master_data.py::list_wards`, `backend/app/api/v1/users.py`, `backend/app/schemas/master_data.py::UserOut`, `backend/app/models/user.py` — not assumption.*
