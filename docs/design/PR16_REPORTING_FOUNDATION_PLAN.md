# Roadmap PR16 — Reporting Foundation: Design Proposal

**Status:** Design only. Nothing in this document has been implemented. No backend code, frontend code, Alembic migration, or database schema change was written to produce it.
**Repository:** Medical Equipment Pool. This is **not** MEMS and **not** Recall Monitor — no coupling to either system is introduced or assumed anywhere below.
**Baseline investigated:** `6f66d76` — squash commit of GitHub PR #54 (Roadmap PR15B, Schema Hygiene), on branch `feature/pr16-reporting-foundation`.
**Governing instruction:** DESIGN ONLY. Produce the minimum design documentation required for an independently reviewable PR16 Design PR.
**Review round 1:** GitHub PR #56, review `4799462477` (COMMENTED / substantive REQUEST CHANGES, exact head `e56061c`), found three blocking defects (PR16-H1, PR16-H2, PR16-H3) and one non-blocking factual error (PR16-M1). All four are corrected below; each correction is marked inline with its finding ID.

---

## 1. Executive Summary

Roadmap PR16 is scoped, per the authoritative source (`docs/audits/04-consolidated-implementation-plan.md` Part D, Group 7), to exactly one objective: **establish reporting foundations and distinguish the actual transaction timestamp, `business_date`, and `shift`** — not to build the operational reports themselves (that is PR17), and not to build export/print output (that is PR18). PR16's own acceptance criterion is narrow and precise: *"New reporting data can be filtered by `business_date` and `shift` without losing the actual event timestamp."*

This document proposes: (1) a single, backend-only, versioned derivation of `business_date`/`shift` from a transaction's existing authoritative UTC timestamp, exposed as computed (non-persisted) values; (2) the smallest possible extension of the *already-merged* `GET /transactions` endpoint to filter and expose them; (3) explicit non-invention of the one confirmed-missing business rule (the exact Day/Night boundary time), flagged as a blocking Owner Decision rather than guessed. No new endpoint, no new report, no export capability, no dashboard, no migration, and no new lifecycle state or workflow are introduced. PR17 (Receive/Issue/Equipment Verify Checklist reports) and PR18 (PDF/Excel/Hard Copy export) remain untouched, dependent, future work.

---

## 2. Authoritative Inputs

Documents and implementation areas inspected and treated as authoritative for this design, in the order consulted:

| Area | Source | What it established |
|---|---|---|
| Roadmap PR16 scope (authoritative) | `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 7 (`#### PR16 — Reporting foundation`, `#### PR17`, `#### PR18`) | PR16 = foundation only; PR17 = the actual reports; PR18 = export. Explicit acceptance criterion for PR16 quoted above. |
| Roadmap status/dependencies | `docs/ROADMAP.md` (Completed table, PR15 note, "Approved forward sequence," "Confirmed future work") and `docs/ROADMAP_STATUS.md` | PR16 depends on PR15B (merged, `6f66d76`); PR16 is the next planned item; `business_date`/`shift` "in one model" is the approved PR16 direction, explicitly distinguished from the deferred "Shift Sessions" workflow. |
| Domain model / confirmed vs. future work | `docs/HOSPITAL_DOMAIN_MODEL.md` §"Planned reporting shift metadata," §"Future Standby Snapshots" | Day/Night are values in one model, not separate tables; a richer Shift Session workflow and Standby Snapshots are explicitly **not** PR16. |
| Terminology discipline | `docs/GLOSSARY.md` (Shift Session, `DAY`/`NIGHT`, Standby Snapshot rows) | `DAY`/`NIGHT` labeled "Confirmed future" with the explicit instruction **"Do not invent fixed boundaries."** See §3 for how this is reconciled with `HOSPITAL_DOMAIN_MODEL.md` above — this is the one material tension this document found. |
| Timezone policy (must not change) | `docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md` (approved, GitHub PR #52), as implemented in GitHub PR #54 | All business timestamps are UTC `timestamptz`; Option A (type + callable fix only, no `server_default` convergence). This design changes nothing about that policy — see §11. |
| Business rules | `docs/BUSINESS_RULES.md` | Ward-correction, receipt-outcome, and RBAC precedents this design reuses rather than reinvents. |
| Equipment soft-delete (confirmed existing, added per review round 1 / PR16-M1) | `backend/app/crud/equipment.py::soft_delete()`, `backend/app/models/mixins.py::deleted_at` | A technical equipment soft-delete path already exists (`deleted_at` `timestamptz`, every equipment lookup filters `deleted_at.is_(None)`) — corrects the prior draft's factual error; see §11. |
| Equipment/transaction domain model | `backend/app/models/transaction.py`, `backend/app/models/master_data.py`, `backend/app/models/user.py`, `backend/app/models/mixins.py` | `BorrowTransaction` fields (`borrowed_at`, `returned_at`, `dispatch_type`, `routine_round`, `ward_id`, `status`); `Ward`/`Department`; 3-role model; `UTCDateTime`'s fail-closed UTC-only write invariant (Roadmap PR15B). Confirmed the `receipt_outcome`/`legacy_condition_on_return` `@property` pattern (computed, non-column API fields backed by a real column) as an existing, reusable precedent. |
| Authorization | `backend/app/api/v1/deps.py` | Centralized capability groups (`VIEW_AND_REPORT_ROLES` — all 3 roles already have view/export access; `EQUIPMENT_POOL_OPERATION_ROLES`; `ADMINISTRATOR_ONLY_ROLES`); existing `PaginationParams` (cursor, limit 1–200). |
| Existing pagination/filtering convention | `backend/app/api/v1/transactions.py`, `backend/app/crud/transaction.py::search()`, `backend/app/schemas/common.py::Page` | Cursor pagination on `(created_at DESC, id DESC)`; API-boundary validation of `from_date`/`to_date` ordering *before* reaching the CRUD layer; `datetime.combine(date, time.min/max)` for inclusive day-range bounds (never `date + timedelta(days=1)`, which overflows at `date.max` — Roadmap PR13/PR45 fix). This is the exact convention PR16 must extend, not replace. |
| Existing (pre-PR16) reporting capability | `backend/app/api/v1/reports.py`, `backend/app/services/report_service.py`, `frontend/src/pages/ReportsPage.tsx` | An unfiltered CSV/XLSX export of all transactions (capped at 50,000 rows) already exists, gated to `VIEW_AND_REPORT_ROLES`, using `csv`/`openpyxl` (already-vetted dependencies — no new library is proposed anywhere in this document). This predates the Group 7 PR16–18 sequence and is **not** modified by this design; it is documented here only as existing context and a known, out-of-scope latent gap (see §12). |
| API/error conventions | `docs/api/ERROR_CODES.md`, `backend/app/schemas/common.py::ErrorResponse` | Status-code table, `DomainError` subclass-per-condition pattern, `{detail, code, status}` error shape. |
| Frontend architecture | `frontend/src/pages/EquipmentDetailPage.tsx` (existing dispatch-type/routine-round/date-range filter block, added Roadmap PR13), `frontend/src/pages/ReportsPage.tsx`, `frontend/src/services/api.ts` | TanStack Query, Thai-first labels, label+`<select>`/date-`<input>` filter pattern, filter values embedded in the query key, existing loading/error-state handling — all reused, not redesigned. |

A separate Codex documentation audit is understood to be occurring in parallel (per this task's own instruction). No material contradiction was found between this document and that audit's likely scope (it is documentation-only); the one material contradiction found is internal to the existing documentation set and is resolved (not silently) in §3 below.

---

## 3. The One Material Contradiction Found, and How It Is Resolved

`docs/GLOSSARY.md` instructs, for the `DAY`/`NIGHT` term: *"Do not invent fixed boundaries."* `docs/HOSPITAL_DOMAIN_MODEL.md` states PR16 "will distinguish... `business_date`; and `shift`... Day and Night are values in one model." Read together with `docs/ROADMAP.md`'s "Confirmed future work" entry ("the approved PR16 direction is transaction reporting metadata (`business_date` and `shift`) in one model, not separate Day/Night tables or a new equipment lifecycle state. Any future session workflow would require its own approval"), the reconciled reading this document adopts is:

- **PR16 does own** introducing the `shift` classification concept itself (a `Day`/`Night` domain value) and the `business_date` concept, in one data model — this is explicitly "the approved PR16 direction," not an invention.
- **PR16 does not own**, and this document does **not** invent, the exact clock-time boundary(ies) that separate `Day` from `Night`, nor the derivation rule for a dispatch that is not tied to one of the four confirmed `RoutineRound` values (`on_demand` dispatches). Nothing in any authoritative document states these boundaries. Inventing them here would be exactly the "invent fixed boundaries" GLOSSARY.md forbids.

This was marked as **Open Owner Decision #1** (§18) and a hard implementation blocker; it has since been **resolved** by the Repository Owner and recorded in `docs/DECISION_LOG.md` ("Roadmap PR16 — Owner Decision #1") — see §18 for the confirmed values.

---

## 4. Business Objective

"Reporting Foundation" means: **one backend-owned, single-source-of-truth derivation that classifies any existing transaction event by calendar `business_date` and `shift`, without discarding or duplicating the real event timestamp**, so that PR17's future reports (and any other current or future consumer) can filter and group by business day/shift consistently, instead of each future report re-implementing its own ad hoc date-bucketing logic.

This is explicitly **not**: analytics, BI, a dashboard redesign, an arbitrary report builder, general-purpose export infrastructure, or anything coupled to MEMS or Recall Monitor. It prioritizes: (a) the narrow, confirmed operational need (PR17's three named reports will need consistent date/shift filtering), and (b) long-term extensibility in the cheapest possible way — one shared derivation function, not a schema commitment that would be expensive to change later (see §6, Architecture Options).

---

## 5. Business Workflow Analysis

**Who runs reports:** Per the existing, unmodified `VIEW_AND_REPORT_ROLES` gate (all three confirmed roles — Administrator, Equipment Pool Staff, Read Only — already have view/export access to the pre-existing report surface), all three roles may view/filter reporting data. PR16 introduces no new role or permission tier. Actually *running* a named report (Receive/Issue/Equipment Verify Checklist) is PR17 scope; PR16's own "workflow" is narrower: enabling the existing transaction list to be filtered by business day/shift.

**Operational questions PR16's foundation must make answerable (for PR17 to actually answer):**
- "Show me everything dispatched/received on business day X."
- "Show me everything dispatched/received during the Day (or Night) shift on business day X."
- Both without losing the ability to see the exact timestamp an event actually occurred (audit/traceability requirement already established for every other timestamped record in this system).

**Required filters (foundation-level, i.e. what `GET /transactions` must support after PR16):** `business_date_from`, `business_date_to` (inclusive), `shift` (optional, single value), `event` (`dispatch`/`receipt`, defaults to `dispatch` — see §8, corrected per PR16-H2) — additive to the existing `ward_id`/`equipment_id`/`status`/`dispatch_type`/`routine_round`/`from_date`/`to_date` filters, combined with `AND` exactly as today.

**Report date/time semantics:** See §11. The authoritative event timestamp for a *dispatch* record is `borrowed_at`; for a *receipt* record it is `returned_at`. A transaction has at most one dispatch business_date/shift and, once closed, a separate receipt business_date/shift — these may fall on different business days or shifts (an equipment item dispatched late in a Night shift may be received the next Day shift). This document does not collapse the two into one "the" business_date for a transaction; PR17 will choose per report which timestamp it reports against (an Issue report reports dispatch; a Receive report reports receipt), consistent with `dispatch_type`/`routine_round` already being dispatch-only concepts on this same row.

**Permission boundaries:** Unchanged — `VIEW_AND_REPORT_ROLES` for read/filter access. No new write path exists; `business_date`/`shift` are never accepted as request input, only derived and returned (see §9 — this closes off an entire class of validation/tampering concern by construction).

**Expected result sizes:** Matches the existing `GET /transactions` cursor-paginated contract — `limit` capped at 200 per page (existing `PaginationParams`/`Query(le=200)` convention), no artificial new cap on the `business_date_from`/`business_date_to` range width, consistent with how `from_date`/`to_date` already behave. Confirmed system scale (`docs/PROJECT_MEMORY.md`: "low hundreds of devices, thousands of transactions per year") gives no evidence of a real query-plan problem from a wide date range — introducing one now would repeat the exact mistake PR14B's evidence-gating discipline was built to prevent (see §14).

**Viewed vs. exported:** PR16 produces filterable, viewable data only (via the existing JSON `GET /transactions` response). It does not touch the pre-existing `/reports/export` endpoint and does not add a new export capability — that remains PR18-dependent, gated on PR17 existing first.

**Current state vs. historical transaction distinction:** `business_date`/`shift` are properties of a **transaction event**, computed once from that event's own timestamp — they must never be confused with, or computed from, an equipment row's *current* lifecycle status (`AVAILABLE_AT_POOL`/`ISSUED_TO_WARD`/`UNAVAILABLE_DEFECTIVE`/`DECOMMISSIONED`) or its *current* location. This mirrors the separation already established between `DashboardPage.tsx` (current counts) and `EquipmentDetailPage.tsx`'s transaction history (per-event records) — reporting reads historical event facts, never current-state joins presented as if they were historical.

**Assumptions made where roadmap detail is insufficient** (none of these invent a business rule; each is either a direct restatement of an existing, confirmed fact or a value the Repository Owner has since confirmed via Owner Decision #1, §18):
1. The hospital's civil-day/shift boundary is evaluated in Thailand's single, DST-free timezone (`Asia/Bangkok`, UTC+7) — an uncontested geographic fact for this deployment (Thai-first UI, `"th-TH"` locale already used for display), not a new business-rule invention. This is distinct from, and was resolved separately by, Owner Decision #1 (the clock-time boundary *within* that timezone).
2. A `Shift` domain has exactly two values, `DAY` and `NIGHT`, per `docs/HOSPITAL_DOMAIN_MODEL.md` — no third value is introduced.
3. Owner Decision #1 has been answered (§18); this document's §7 now specifies the derivation with the confirmed boundary-policy values, not a placeholder.

---

## 6. Architecture Options and Recommendation

Design order followed throughout: Business Workflow → Domain/query model → API → Frontend → Deployment/performance.

**Option A — Query-time derivation (recommended).** `business_date`/`shift` are computed, never stored: one pure Python function (for unit tests and any Python-side consumer) and one equivalent SQLAlchemy expression (for use inside `select()`/`WHERE` so filtering happens in PostgreSQL, not by loading all rows into Python) both derive from the existing `borrowed_at`/`returned_at` `timestamptz` columns. No migration, no new column, no backfill, no risk of the derived value drifting out of sync with the timestamp it comes from.
*Trade-off:* recomputed on every query. At this system's confirmed scale (thousands of transactions/year), this is not a measurable cost — and per PR14B's own established precedent, index/perf work here is not justified without `EXPLAIN (ANALYZE, BUFFERS)` evidence of an actual problem, which does not exist.

**Option B — Persisted columns (considered, rejected for this PR).** Add `business_date`/`shift` columns to `borrow_transactions`, populated at write time and backfilled via migration for historical rows.
*Trade-off:* requires a migration + backfill logic now, and — critically — creates a permanent data-drift risk if the shift-boundary policy is ever revised later (every historical row's stored `shift` would then silently misrepresent the *current* policy, exactly the class of risk Roadmap PR15B's verify-and-no-op design was built to eliminate for schema state). Rejected for the foundation; could be revisited later purely as a read-side optimization, itself gated on real query-plan evidence, never on assumption.

**Option C — Frontend-computed shift/business_date (considered, rejected outright).** Directly contradicts this task's explicit instruction ("Reporting queries must not place business rules in the frontend") and would fragment the single source of truth PR17 depends on into as many implementations as there are frontend call sites. Not adopted.

**Recommendation: Option A.** One backend module owns the derivation; the database is queried through it, never reimplemented per caller.

---

## 7. Domain and Query Boundaries

New module: `backend/app/core/reporting_time.py` (naming mirrors the existing `app/core/` convention — `log_context.py`, `logging.py`, `security.py` — a small, named, single-purpose module, not a generic "utils" dumping ground).

- `class Shift(str, enum.Enum): DAY = "day"; NIGHT = "night"` — mirrors the existing `(str, enum.Enum)` + `values_callable` shape already used by `TransactionStatus`/`DispatchType`/`RoutineRound`, for consistency, even though this one never backs a database column (same non-column precedent as `ReceiptOutcome`).
- **(Corrected per PR16-H3; values confirmed per Owner Decision #1 — see §18.)** A single named policy point for the boundary, but **not** a single hour constant — one hour cannot represent a Day/Night policy, since a policy needs both transitions and an explicit rule for which business_date an overnight shift's post-midnight instants belong to. The Repository Owner has confirmed the following values (recorded in `docs/DECISION_LOG.md`, "Roadmap PR16 — Owner Decision #1"):
  ```python
  @dataclass(frozen=True)
  class _ShiftBoundaryPolicy:
      day_start_local: time       # Night -> Day transition
      night_start_local: time     # Day -> Night transition
      business_date_anchor: Literal["shift_start_date", "instant_calendar_date"]
      # "shift_start_date": every instant in a shift takes the calendar date the
      # shift *started* on (a Night shift starting 2026-07-28 20:00 and running
      # past midnight is entirely business_date 2026-07-28).
      # "instant_calendar_date": business_date is simply the Asia/Bangkok
      # calendar date of the instant itself (a post-midnight Night instant is
      # business_date = the next day).
      # These two rules disagree for exactly the post-midnight portion of an
      # overnight shift -- the anchor is therefore not cosmetic and was an
      # explicit owner decision, not a default.
  _SHIFT_BOUNDARY_POLICY = _ShiftBoundaryPolicy(
      day_start_local=time(8, 0),        # Day shift: 08:00-19:59:59.999999 Asia/Bangkok
      night_start_local=time(20, 0),     # Night shift: 20:00-07:59:59.999999 Asia/Bangkok
      business_date_anchor="shift_start_date",
  )
  ```
  A single total function `classify(ts_local: datetime) -> tuple[date, Shift]` derived from this policy covers all 24 hours of the day (both the Night→Day and Day→Night transitions), not one boundary hour — kept in exactly one named place so a future confirmed change to the policy is a one-object edit, not a multi-file hunt.
- `def business_date_and_shift(ts: datetime) -> tuple[date, Shift]:` — the pure-Python reference implementation. Takes an aware UTC `datetime` (matching `UTCDateTime`'s existing contract — see §11), converts to `Asia/Bangkok`, and applies `_SHIFT_BOUNDARY_POLICY.classify(...)` above.
- `def business_date_and_shift_sql(column) -> tuple[ColumnElement, ColumnElement]:` — the SQLAlchemy-expression twin, built from the identical boundary constant, for use inside `crud/transaction.py`'s `select()`/`WHERE` clauses. Both implementations are tested against each other (see §15) so they can never silently diverge.
- **On-demand classification (confirmed per Owner Decision #1):** a `dispatch_type = on_demand` transaction (not tied to one of the four confirmed `RoutineRound` values) is classified purely by `borrowed_at`'s Bangkok clock time against `_SHIFT_BOUNDARY_POLICY`, identically to a `RoutineRound`-tied dispatch — no special-case branch exists in `classify()` for `on_demand`.
- No repository abstraction, no generic query builder, and no materialized view are introduced — deliberately, per this task's explicit list of things to avoid. The query boundary is exactly the existing `app/crud/transaction.py::search()` function, extended with four more optional filter parameters (`business_date_from`, `business_date_to`, `shift`, `event` — corrected per PR16-H2), exactly as Roadmap PR13 already extended it with `dispatch_type`/`routine_round`/`from_date`/`to_date`.

---

## 8. API Contract

**No new endpoint.** The existing, already-versioned `GET /api/v1/transactions` (`backend/app/api/v1/transactions.py`) is extended.

| | |
|---|---|
| **Method/path** | `GET /api/v1/transactions` (unchanged path) |
| **Purpose** | Adds business-day/shift filtering to the existing transaction list/history query |
| **Permissions** | Unchanged — any authenticated user (`get_current_user`), matching every other read on this endpoint today; reporting-specific role gating is unnecessary since transaction history is already universally readable |
| **New query parameters** | `business_date_from: date \| None`, `business_date_to: date \| None`, `shift: Shift \| None`, `event: Literal["dispatch", "receipt"] = "dispatch"` (all optional except `event`'s default, additive, combined with `AND`) |
| **Validation rules** | `business_date_from > business_date_to` → `400 INVALID_INPUT`, validated at the API boundary before reaching `search()` — a **new** check, distinct from (not reusing) the existing `from_date > to_date` check, since `business_date_from`/`_to` are compared against the derived `business_date` value, not the raw `borrowed_at`/`returned_at` timestamp. An unrecognized `shift` or `event` value → `422` (standard FastAPI/Pydantic enum/Literal validation, no custom code needed — same as `dispatch_type`/`routine_round` today). |
| **Response schema** | `TransactionOut` gains two new **read-only, computed** fields: `dispatch_business_date: str \| None`, `dispatch_shift: Shift \| None` (derived from `borrowed_at`) and `receipt_business_date: str \| None`, `receipt_shift: Shift \| None` (derived from `returned_at`, `None` until received) — named per-direction (not one ambiguous `business_date`) per §5's dispatch-vs-receipt distinction. **(Corrected per PR16-H2.)** `business_date_from`/`_to`/`shift` filter against **whichever** column pair the new `event` parameter selects: `event=dispatch` (the default) filters `dispatch_business_date`/`dispatch_shift`; `event=receipt` filters `receipt_business_date`/`receipt_shift`. This is an explicit, closed, two-value basis — not a generic report-query parameter — so PR17's Receive report can filter by receipt metadata through this same foundation instead of requiring a second filtering contract. **Open-transaction rule:** when `event=receipt`, a transaction with `returned_at IS NULL` has `receipt_business_date`/`receipt_shift = NULL` and therefore never satisfies a non-null `business_date_from`/`_to`/`shift` filter — it is silently excluded from receipt-basis results, not treated as an error, exactly as a `NULL` column value already behaves against any other `WHERE` predicate in this codebase. **(Corrected per PR16-H1.)** In both cases the predicate compares the **derived** `business_date` expression (§7's SQL twin) directly against `business_date_from`/`_to` — it does not reuse `datetime.combine`-based bounding against the raw `borrowed_at`/`returned_at` column (see §11); that remains exclusively how the existing, separate `from_date`/`to_date` raw-timestamp filters work. |
| **Pagination model** | Unchanged — existing cursor pagination on `(created_at DESC, id DESC)`, `Page[TransactionOut]` |
| **Sorting** | Unchanged |
| **Error responses** | `400 INVALID_INPUT` (reversed business-date range), `401`, `403` (unchanged existing cases), `422` (schema validation) — no new error code needed |
| **Performance considerations** | The SQL-expression twin (§7) must be sargable enough for PostgreSQL to use the existing `ix_borrow_transactions_created_at_id`/`borrowed_at`-indexed lookups where possible; whether the now-confirmed boundary expression (§18) is index-friendly is evaluated at implementation time against real `EXPLAIN` evidence (PR14B precedent), not assumed here |

Avoided per instruction: no single unrestricted "report query" endpoint is introduced anywhere in this design.

---

## 9. Backend Design

- **Application use case:** "list/filter transactions by business date and shift" — already the existing `search()` use case, extended, not a new one.
- **Query service:** `app/crud/transaction.py::search()` gains four parameters (`business_date_from`, `business_date_to`, `shift`, `event`). **(Corrected per PR16-H1/H2.)** `event` selects which computed column pair (`dispatch_business_date`/`dispatch_shift` or `receipt_business_date`/`receipt_shift`) the SQL-expression twin from §7 is evaluated against; the resulting predicate compares that derived value directly to `business_date_from`/`_to`/`shift` and is appended to the existing `filters.append(...)` list — same shape as every other filter already there, but built from the derived expression, not from `datetime.combine`-based bounding of the raw column (that combine logic remains exclusive to the existing, untouched `from_date`/`to_date` filters).
- **Repository/query boundary:** None beyond the existing CRUD module — no new abstraction layer, per explicit instruction to avoid "generic repositories that obscure query intent."
- **Pydantic schemas:** `TransactionOut` (`app/schemas/transaction.py`) gains the four computed fields from §8, resolved from two new `@property`s on `BorrowTransaction` (`app/models/transaction.py`) — `dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` — mirroring the exact existing `receipt_outcome`/`legacy_condition_on_return` computed-property pattern already on that model (§2). `business_date`/`shift` are **never** accepted as request input on any schema — read-only, derived, by construction (closes the entire "tampering with a business fact" class of concern before it exists).
- **SQLAlchemy query strategy:** Extend the existing `select(BorrowTransaction)...where(and_(*filters))` shape; no new joins, no new table.
- **Authorization enforcement:** Unchanged (`get_current_user`, matching this endpoint's existing gate).
- **Centralized validation/error handling:** Reuses the existing `InvalidInputError` (`app/core/exceptions.py`) and the existing API-boundary-validates-before-CRUD pattern.
- **Index usage:** No new index is proposed. The derivation reads from `borrowed_at`, already indexed (`index=True` on the column, plus the PR14B composite `(created_at DESC, id DESC)` index for pagination ordering) — evaluated against real evidence at implementation time if the boundary expression turns out not to be index-friendly, not assumed now (see §14).
- **Maximum date range/page size:** No new cap — existing `limit ≤ 200` per page already bounds response size and memory regardless of the business-date range's width (§5).
- **Streaming/bounded-memory behavior:** Not applicable — PR16 introduces no export path.

---

## 10. Frontend Design

**No new page.** **(Corrected per PR16-H1 — the prior draft incorrectly claimed the existing `from_date`/`to_date` raw-timestamp pickers are visually equivalent to business-date filtering; they are not, since `Asia/Bangkok` is UTC+7 and a UTC calendar day does not align to a Bangkok business day, before the shift-boundary policy is even applied.)** `EquipmentDetailPage.tsx`'s existing transaction-history filter block (dispatch_type/routine_round/from_date/to_date, added Roadmap PR13) is left entirely unchanged and continues to filter on the raw `borrowed_at`/`returned_at` timestamps exactly as today. Two new, explicitly separate controls are added alongside it: a `business_date_from`/`business_date_to` date-range pair, and a `shift` `<select>` (ค่ากะ: กลางวัน / กลางคืน — "Day"/"Night") — both following the identical label+`<select>`/date-`<input>` pattern, Thai-first, same styling classes, same disabled/enabled interaction rules already established for the existing filters, but sent to the API as their own named query parameters (`business_date_from`, `business_date_to`, `shift`, `event=dispatch` implied by this page's dispatch-oriented context — see §8), never merged with or substituted for `from_date`/`to_date`. This keeps the two filter concepts (raw event time vs. derived business day/shift) visually and semantically distinct, per the reviewer's required correction, at the cost of two more controls in the filter block — an acceptable, explicit trade-off for a foundation PR, not a UI-clutter shortcut.

- **Entry point to reporting:** Unchanged — the existing `EquipmentDetailPage.tsx` transaction-history section. PR16 introduces no new entry point; PR17 will add its own report-specific pages.
- **Filter workflow:** Extend the existing `useState`/TanStack Query key pattern with the three new `business_date_from`/`business_date_to`/`shift` values, identical mechanism to the four filters already there.
- **Loading/empty/error states:** Reused verbatim from the existing implementation — no new state machine.
- **Pagination:** Unchanged (existing cursor-based "load more").
- **Export interaction:** Not in scope for PR16 (see §5, §8).
- **Narrow-screen behavior:** Reuses the existing responsive filter-row layout already shipped in Roadmap PR13/PR11 (mobile-first, large touch targets, low typing — a `<select>`, not free text).

No dashboard-heavy UI, no chart, no new component library is introduced. Business logic (the shift/business-date derivation) is never computed in the frontend — it only ever displays/filters on values the backend already computed and returned.

---

## 11. Data and Time Semantics

- **Authoritative timestamps:** `borrowed_at` (dispatch event) and `returned_at` (receipt event, nullable until receipt) — both already `timestamptz` (Roadmap PR15B, GitHub PR #54). No other timestamp is treated as authoritative for this derivation.
- **UTC storage/serialization:** Unchanged. Every value read by `business_date_and_shift()` is already a UTC-aware `datetime` per `UTCDateTime`'s existing, unmodified contract (fail-closed on a non-UTC aware value at bind time — Roadmap PR15B). This design adds a *read-side, display/report-oriented* conversion to `Asia/Bangkok` for classification purposes only — it does not change what is stored, and does not touch `UTCDateTime` itself.
- **User-facing timezone behavior:** Unchanged from the existing frontend convention (`new Date(...)` + `.toLocaleString("th-TH")`, browser-local display). The new `dispatch_business_date`/`dispatch_shift` fields are pre-derived server-side in `Asia/Bangkok` terms specifically (not the browser's local timezone, which this application has no server-side knowledge of) — this is a deliberate, explicit design point: a hospital "business day" is a property of the hospital's own operating timezone, not of whichever browser happens to be viewing the report.
- **Inclusive/exclusive date boundaries:** **(Corrected per PR16-H1.)** `business_date_from`/`business_date_to` are both inclusive, but the bound is enforced by comparing them **directly against the derived `business_date` value** (a calendar `date`, produced by §7's SQL twin) — `business_date_expr BETWEEN business_date_from AND business_date_to`. This is a date-to-date comparison, not a timestamp range, so `datetime.combine(date, time.min/max)` does **not** apply to it and is not part of this filter's implementation. `datetime.combine(date, time.min/max)` remains exactly as it is today, but exclusively for the existing, separate, unmodified `from_date`/`to_date` raw-timestamp filters (Roadmap PR13/PR45) — the two boundary mechanisms must not be conflated, which is the defect this correction removes.
- **Business-date rollover / anchor:** Which calendar date an overnight (Night) shift's post-midnight instants are assigned to is governed by `_ShiftBoundaryPolicy.business_date_anchor` (§7) — confirmed as `"shift_start_date"` by Owner Decision #1 (§18): a Night shift starting at 20:00 and running past midnight is entirely one business_date, not split across two.
- **Open-ended ranges:** Either bound may be omitted independently, matching existing `from_date`/`to_date` behavior.
- **Stable ordering for equal timestamps:** Unchanged — existing `(created_at DESC, id DESC)` tie-break, untouched by this design (the new fields are filter/display-only, never part of the sort key).
- **Historical vs. current status:** See §5 — `business_date`/`shift` are per-event, never derived from or mixed with an equipment row's current lifecycle state.
- **Soft-deleted/decommissioned equipment:** **(Corrected per PR16-M1 — the prior draft incorrectly stated no equipment soft delete exists.)** A technical equipment soft-delete path already exists today: `backend/app/crud/equipment.py::soft_delete()` sets the `deleted_at` `timestamptz` column (`backend/app/models/mixins.py`), and every existing equipment lookup/list query filters `Equipment.deleted_at.is_(None)`. This is distinct from, and does not resolve, any separate deferred business/workflow decision about *user-facing* equipment deletion (`docs/ROADMAP.md` "Confirmed future work") — this document takes no position on that deferred decision. What this design does confirm: `BorrowTransaction` rows are never soft-deleted themselves and carry their own `equipment_id`, independent of whether the referenced `Equipment` row is later soft-deleted or `DECOMMISSIONED` — so a transaction's `dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` remain fully derivable and reportable regardless of the current state of the equipment it references. The transaction-query path added by this design does not join through, or apply, `Equipment.deleted_at.is_(None)`.
- **This design does not modify the approved PR15B timezone policy** in any respect — `UTCDateTime`, the five converted columns, and `due_at`'s deliberate exclusion are all unchanged.

---

## 12. Authorization and Security

- **Access permissions:** Unchanged (`get_current_user` for the extended `GET /transactions`; no new role tier needed — `business_date`/`shift` are exposed at exactly the same authorization boundary the underlying transaction fields already sit behind).
- **Least privilege:** No new data is exposed beyond what `borrowed_at`/`returned_at` already expose today (in `TransactionOut`) — `business_date`/`shift` are a *re-expression* of existing, already-visible timestamps, not new personal or operational data.
- **Staff/ward information exposure:** Unaffected — no new field touches `borrower_name`, ward, or user identity.
- **Query parameter validation:** `business_date_from`/`_to` are ordinary FastAPI `date` query params (same validation machinery as existing `from_date`/`to_date`); `shift` is a closed enum, rejecting any value outside `{day, night}` with a standard `422` — no free-text injection surface.
- **Excessive data extraction / DoS from broad ranges:** No new risk — pagination (`limit ≤ 200`) already bounds every response regardless of date-range width; no export path is introduced by PR16 for an unbounded range to feed.
- **CSV formula injection:** Not applicable to PR16 itself (no export path is introduced). Noted for completeness: the **pre-existing**, out-of-scope `report_service.py` export already writes free-text fields (e.g. `borrower_name`) into CSV/XLSX without formula-prefix escaping (`=`, `+`, `-`, `@`) — a latent gap that predates PR16 and is explicitly **not** fixed by this design; it is flagged here as relevant context PR18 (export) must address when it introduces any export of business_date/shift-bearing data, not something PR16 is required to touch.
- **Auditability:** No new write path exists (§9), so no new audit-event requirement is introduced — reads are not audited today (consistent with every existing read endpoint) and this design does not change that.
- **DoS from broad date ranges/unbounded exports:** See above — bounded by existing pagination; no export introduced.
- **Personal data:** No new personal data field is added.

---

## 13. Performance and Scalability

At confirmed real-world scale ("low hundreds of devices, thousands of transactions per year," `docs/PROJECT_MEMORY.md`), a per-row timezone-conversion-and-compare expression evaluated during an already-indexed, already-paginated query is not expected to introduce a measurable regression. No index change is proposed pre-emptively. If implementation-time `EXPLAIN (ANALYZE, BUFFERS)` evidence (the same evidentiary bar PR14B established) shows the boundary expression defeats the existing `borrowed_at`/composite indexes, that would be evaluated and, if needed, proposed as its own follow-up — not assumed or pre-built here.

---

## 14. Database and Index Assessment

- **Migrations required by this design:** **None.** `business_date`/`shift` are computed, not stored (§6, Option A).
- **Existing indexes sufficient?** Likely yes for this system's confirmed scale; not re-verified with new `EXPLAIN` evidence in this design-only document — flagged as an implementation-time task (§16, Slice 1), not assumed.
- **Backward compatibility:** Fully additive — every new response field is optional/nullable, every new query parameter is optional. No existing client behavior changes.
- **Rollback expectations:** A pure code revert (no migration to reverse).
- **Fresh-install/upgraded-database convergence:** Not applicable — no schema changes, so both paths are trivially identical by construction (no verify-and-no-op logic is needed here, unlike PR15B's migrations).
- **Interaction with PR15B schema hygiene:** None beyond reading the already-`timestamptz` `borrowed_at`/`returned_at` columns PR15B produced — no interaction with the `0012`–`0014` migrations' own logic.

---

## 15. Testing Matrix

| Area | Coverage |
|---|---|
| Backend unit — `reporting_time.py` | `business_date_and_shift()` pure function: **(Corrected per PR16-H3)** both shift transitions (08:00 Night→Day and 20:00 Day→Night, per Owner Decision #1), the midnight instant itself, business-date rollover instants confirming `shift_start_date` anchoring, `on_demand`-dispatch classification (no `RoutineRound` to anchor to), `Asia/Bangkok` conversion correctness for a UTC instant, deterministic for a fixed instant |
| Backend unit — SQL/Python parity | **(Corrected per PR16-H3)** A property-style test asserting the SQL-expression twin and the pure-Python function agree for a representative sample of timestamps, explicitly including both shift transitions, midnight, and business-date-rollover instants (prevents the two implementations from silently diverging — this is the single most important test this design requires) |
| API integration | `GET /transactions` with each new filter individually and combined with existing filters (`ward_id`, `dispatch_type`, `from_date`/`to_date`); reversed `business_date_from`/`_to` → `400`; invalid `shift` or `event` value → `422` |
| API integration — dispatch/receipt event basis (PR16-H2) | The same transaction is found via `event=dispatch` business_date/shift filters, and, once closed, independently via `event=receipt` filters; an **open** transaction (`returned_at IS NULL`) must not match any non-null `event=receipt` filter |
| API/UI — business-date boundary correctness (PR16-H1) | A dispatch row constructed near a UTC-calendar-day boundary but on the *same* Bangkok business day, and a row constructed near the Bangkok business-date rollover instant, must produce identical `business_date_from`/`_to` filter results via both the API and the new frontend controls — i.e. filtering by `business_date_from`/`_to` must never be satisfied merely by the raw `from_date`/`to_date` UTC-calendar-day filters, and the two must be asserted as distinct in at least one test case |
| PostgreSQL query tests | The SQL-expression twin evaluated against a real PostgreSQL 16 instance (not SQLite) with rows constructed near both shift transitions and the business-date rollover instant, confirming the derived `business_date`/`shift` match the pure-Python reference for the same rows |
| Authorization | Existing `GET /transactions` auth tests extended with the new params — no new role boundary to test since none was introduced |
| Timezone/date-boundary | Explicit tests for a transaction dispatched just before vs. just after the boundary (once confirmed), and for the Asia/Bangkok/UTC offset crossing a UTC calendar-day boundary |
| Pagination stability | Confirm the new filters do not alter existing cursor-pagination behavior/ordering |
| Empty results | A `business_date_from`/`_to` range matching no rows returns an empty `Page`, not an error |
| Large datasets | Not a new concern — existing pagination already bounds this; no new test class needed beyond what PR14B already established |
| Export security | Not applicable — no export path introduced by PR16 |
| Frontend | Component test for the new `business_date_from`/`business_date_to`/`shift` filter controls, asserting they are sent as their own query parameters and never merged with `from_date`/`to_date` (mirroring the existing `EquipmentDetailPage.test.tsx` coverage pattern for `dispatchTypeFilter`/`routineRoundFilter`) |

---

## 16. Implementation Slices

**Slice 1 — Backend derivation module (`app/core/reporting_time.py`) + tests.**
- Scope: `Shift` enum, the pure function, the SQL-expression twin, the SQL/Python parity test, unit tests for Asia/Bangkok conversion. **(Corrected per PR16-H3.)** The boundary policy implemented must be the full `_ShiftBoundaryPolicy` shape (§7: both transition times plus `business_date_anchor`), not a single hour constant.
- Dependencies: **None remaining.** Owner Decision #1 is resolved (§18, `docs/DECISION_LOG.md`) — this slice may now begin.
- Files/layers: `backend/app/core/reporting_time.py` (new), `backend/tests/test_reporting_time.py` (new).
- Acceptance criteria: pure function and SQL twin agree on every test case, including both shift transitions, midnight, business-date rollover, and `on_demand` classification; both correctly classify a representative set of known UTC instants into (business_date, shift).
- Test gate: unit tests green, no PostgreSQL dependency required for this slice alone.
- Explicitly deferred: everything in Slices 2–3.

**Slice 2 — `BorrowTransaction` computed properties + `TransactionOut` schema fields.**
- Scope: `dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` `@property`s on the ORM model; corresponding read-only `TransactionOut` fields.
- Dependencies: Slice 1.
- Files/layers: `backend/app/models/transaction.py`, `backend/app/schemas/transaction.py`.
- Acceptance criteria: `GET /transactions/{id}` and `GET /transactions` both surface all four new fields correctly for both open and closed transactions (receipt fields `None` until received).
- Test gate: existing transaction schema/API tests extended and green; no existing field's behavior changes.
- Explicitly deferred: filtering (Slice 3).

**Slice 3 — `GET /transactions` filter extension.**
- Scope: `business_date_from`/`business_date_to`/`shift`/`event` query parameters, API-boundary validation (reversed-range → `400`, comparing against the derived `business_date` value — not the existing `from_date`/`to_date` check), `search()` extension using the SQL-expression twin against whichever column pair `event` selects. **(Corrected per PR16-H1/H2.)**
- Dependencies: Slices 1–2.
- Files/layers: `backend/app/api/v1/transactions.py`, `backend/app/crud/transaction.py`.
- Acceptance criteria: matches §8's full contract, including the `event=dispatch|receipt` basis and the open-transaction exclusion rule; PR16's own Roadmap acceptance criterion ("New reporting data can be filtered by `business_date` and `shift` without losing the actual event timestamp") is met end to end for both dispatch and receipt events.
- Test gate: full API integration + PostgreSQL query test suite (§15) green, including the PR16-H1/H2 regression tests.
- Explicitly deferred: any new report endpoint (PR17), any export (PR18), any frontend page beyond the filter controls below.

**Slice 4 — Frontend filter controls.**
- Scope: **(Corrected per PR16-H1.)** the `business_date_from`/`business_date_to` date-range pair and the `shift` `<select>` added to `EquipmentDetailPage.tsx`'s existing filter block, as three new, explicitly separate controls — never reusing or relabeling the existing `from_date`/`to_date` controls (§10).
- Dependencies: Slice 3.
- Files/layers: `frontend/src/pages/EquipmentDetailPage.tsx`, its existing test file, `frontend/src/types/index.ts` (new field types).
- Acceptance criteria: the new controls behave identically in structure to the existing four filters, are sent as their own query parameters, and are never conflated with `from_date`/`to_date` in either UI presentation or the outgoing request; loading/empty/error states unchanged.
- Test gate: component test green, existing `EquipmentDetailPage.test.tsx` suite unaffected.
- Explicitly deferred: any new page, any dashboard/report visualization.

No slice combines database + broad API + frontend + export + documentation changes — each is a narrow, independently mergeable, independently testable unit, matching the lettered-slice precedent already established for PR7/PR8/PR9/PR14/PR15.

---

## 17. Rollback and Compatibility

Every slice above is a plain code revert with no migration to reverse (§14). No slice changes an existing response field's meaning or an existing request parameter's behavior — all changes are additive. A revert of any slice leaves the system in exactly its pre-PR16 state.

---

## 18. Risks and Open Questions

**Owner Decision #1 — RESOLVED.** The exact Day/Night shift boundary policy in `Asia/Bangkok` local time was not confirmed anywhere in this repository's authoritative documentation at the time this design was first proposed, and `docs/GLOSSARY.md` explicitly instructs against inventing one; this originally blocked Slice 1 (and therefore everything downstream). The Repository Owner has since confirmed the full `_ShiftBoundaryPolicy` (§7), recorded in `docs/DECISION_LOG.md` ("Roadmap PR16 — Owner Decision #1"):
- (a) Night→Day transition (Day shift start): **08:00** `Asia/Bangkok`.
- (b) Day→Night transition (Night shift start): **20:00** `Asia/Bangkok`.
- (c) `business_date_anchor`: **`shift_start_date`** — an overnight Night shift's post-midnight instants take the shift's *start* date, not their own calendar date.
- (d) `on_demand` dispatch classification: purely a function of `borrowed_at`'s Bangkok clock time against (a)/(b), identically to a `RoutineRound`-tied dispatch — no special-case rule.

Slice 1 may now proceed with these confirmed values (§16).

**Risk — dispatch vs. receipt business_date divergence:** A transaction's dispatch and receipt business_date/shift can legitimately differ (§5, §8). This is presented as a fact of the domain, not a defect, but PR17's report design must explicitly decide, per report, which one it reports against — flagged here so that decision is not made implicitly or inconsistently across the three PR17 reports.

**Risk — future persisted-column revisit:** If a future PR ever proposes persisting `business_date`/`shift` as real columns (Option B, §6) for performance reasons, that PR must re-verify the boundary policy hasn't changed since Slice 1, or it will bake in a snapshot of a policy that PostgreSQL's `verify-and-no-op` discipline (PR15B) would otherwise have kept live. Documented so it is not silently reintroduced later.

**Non-risk, explicitly confirmed by this design's own scope check:** No new lifecycle state, no QR redesign, no MEMS/Recall Monitor coupling, no Analytics/BI surface, and no implementation code/migration were introduced by this document (§19).

---

## 19. Acceptance Criteria

Restated from the authoritative source, unchanged: **"New reporting data can be filtered by `business_date` and `shift` without losing the actual event timestamp"** (`docs/audits/04-consolidated-implementation-plan.md`, PR16 entry). Concretely, once implemented per §16: `GET /transactions` accepts `business_date_from`/`business_date_to`/`shift`, filters correctly against them, and every returned `TransactionOut` row still carries its original `borrowed_at`/`returned_at` timestamps unchanged, alongside the newly derived, clearly-named business-date/shift fields.

---

## 20. Roadmap Impact

This document did not update `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `docs/DECISION_LOG.md`, or `knowledge/CHANGE_HISTORY.md` at the time it was first proposed (GitHub PR #56) — per this repository's established convention (confirmed by inspecting every prior design document in `docs/design/`, none of which touched roadmap files themselves; roadmap files are updated only in the post-merge governance-sync step, after an implementation PR actually merges, exactly as was done for Roadmap PR15B). **This has since changed for `docs/DECISION_LOG.md` only:** GitHub PR #57 explicitly recorded the Repository Owner's answer to Open Owner Decision #1 as a new `docs/DECISION_LOG.md` entry ("Roadmap PR16 — Owner Decision #1"), and updated this design document (§7, §18, and their cross-references) to replace the previous placeholder boundary-policy values with the confirmed ones. PR #57 contains no implementation code and no database migration — it is a documentation-only correction recording a business decision, not an implementation PR, and `docs/ROADMAP.md`/`docs/ROADMAP_STATUS.md`/`knowledge/CHANGE_HISTORY.md` remain untouched, still reserved for the post-merge governance sync after PR16 implementation actually merges. Planning impact for the Repository Owner to note when this design is reviewed:

- PR16's scope, as designed here, is narrower than "reporting" colloquially suggests — it does not produce a single new user-visible report screen. This is intentional and matches the authoritative Group 7 split (PR16 foundation → PR17 reports → PR18 export); flagging it explicitly so reviewers do not expect PR17-shaped deliverables from a PR16 implementation PR.
- Owner Decision #1 is resolved (§18); implementation Slice 1 may now begin.
- No change to the PR17/PR18 dependency chain, sequencing, or acceptance criteria already recorded in `docs/ROADMAP.md`/`docs/audits/04-consolidated-implementation-plan.md`.

---

*No production code was written or modified to produce this document. No migration was generated. No application file was modified. No reporting library was introduced. Every claim about existing code cites the specific file inspected (§2), not assumption.*
