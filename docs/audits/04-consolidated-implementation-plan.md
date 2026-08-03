# Consolidated MVP Implementation Plan — Medical Equipment Pool

**Role:** Principal Software Architect / Technical Lead
**Purpose:** Reconcile the three prior audits into a single, prioritized, buildable implementation plan against the hospital's now-confirmed requirements.
**Constraint honored:** No application code, configuration, or migration files were written or modified in producing this plan. This is planning documentation only.

---

## 0. Document Status & Source Note

This plan synthesizes findings from:

- `docs/audits/01-database-schema-audit.md` — present. The schema/database review this plan draws on (normalization, foreign-key consistency, missing/composite indexes, nullable-field review, enum-usage review, naming consistency, cascade rules, constraints, and performance findings) is cited below by its real section numbers (§1 Normalization, §2 FK Consistency, §3 Missing Indexes, §4 Composite Indexes, §5 Nullable Fields, §6 Enum Usage, §7 Naming Consistency, §8 Cascade Rules, §9 Constraints, §10 Performance Issues). Every "Schema Audit" citation in this revision has been checked against that file directly. Two citation errors from the prior version of this plan are corrected here: content about the equipment identifier model/identifier separation and about search behavior was previously mis-cited as "Schema Audit §8"/"§8.4" (Cascade Rules) — that content actually lives in **Workflow Audit §8** ("Inventory Import and Identifier Review," which has its own subsection 8.4, "Search behavior") and is now cited correctly throughout.
- `docs/audits/02-backend-architecture-audit.md` — present, cited by finding number (e.g. "Backend Audit 14.1").
- `docs/audits/03-hospital-equipment-pool-workflow-audit.md` — present, cited by section/finding (e.g. "Workflow Audit §6.1", "Workflow Audit M5", "Workflow Audit §8.4").

Where the hospital's now-confirmed requirements (this task's input) change, supersede, or resolve an open question from any of the three audits, that is stated explicitly in §8.1 below. **The confirmed requirements are the source of truth wherever they conflict with an earlier audit's recommendation.**

---

## Executive Summary

The three audits converged on a consistent picture: the underlying engineering (async FastAPI, PostgreSQL, the borrow-side concurrency guard, the layered architecture) is sound, but the domain model was built for a generic "person-to-person equipment loan" system, not the hospital's actual pool-to-ward dispatch/receipt operation. The hospital's confirmation now resolves nearly every open workflow question the audits flagged as an assumption — most importantly, it **simplifies** the design in several places where the workflow audit had over-engineered a solution (a two-step return/cleaning process) that the hospital does not want.

Five findings are Critical and gate any operational pilot, independent of the workflow clarifications: the double-receipt race, the dashboard connection leak, the insecure default JWT secret, the missing audit trail for user/role management, and (newly elevated by the confirmed four-times-daily routine-round pattern) the transaction-number race. Everything else in this plan is sequenced around landing those five safely first, then rebuilding the domain model (identifiers, states, dispatch/receipt workflow) on top of a stable foundation, then the supporting UI/import/reporting work.

This plan proposes **15 pull requests** in six dependency-ordered groups (the five phases named in the task input's §8.4, plus a Post-Pilot Hardening group for the reconciled-down P2/P3 items), a migration strategy for every schema change, a full inventory-import design, a concurrency-focused test matrix, Given/When/Then acceptance criteria for every MVP workflow, and four go-live gates (Development, UAT, Pilot, Production). This revision formalizes PR3 as the reusable audit-logging framework required by later roadmap work, including current authentication and mutation coverage, safe request context, an additive audit migration, an authorized bounded read path, and PostgreSQL-backed migration/transaction evidence. It also corrects the transaction-number migration strategy described in PR4 below; PR5's identifier migration strategy is governed by `knowledge/adr/ADR-002-identifier-model.md` and the active contract in Part D, not restated here.

---

## Part A — Confirmed Requirements Baseline (Summary)

The full confirmed requirements are the input to this task and are not reproduced verbatim here. The table below captures the decisions that most directly change prior audit recommendations, for quick reference throughout this document.

| Area | Confirmed decision |
|---|---|
| Scope | Equipment Pool only (primarily infusion pumps + select shared equipment). No MEMS, patient tracking, HN/MRN, bed tracking, ward-to-ward transfer tracking, PM, calibration, recall, cleaning-workflow tracking, or hospital-wide asset lifecycle. |
| Primary identifier | BCM Code (= source `ID CODE`, e.g. `BCM02719`), confirmed — not an assumption. Unique, the only manual-search identifier, canonical form defined in `knowledge/architecture/identifiers.md` (case-insensitive identity, leading zeros preserved). Distinct from the internal UUID PK, Item No (the separate hospital-QR-only identifier), Asset Number, and Serial Number — see `knowledge/adr/ADR-002-identifier-model.md`. |
| Roles | Exactly 3: Administrator, Equipment Pool Staff, Read-Only/Supervisor. No ward users, no named borrowers. |
| Dispatch types | Exactly 2: `ROUTINE_ROUND` (06:00/11:00/15:00/21:00) and `ON_DEMAND`. This fixed-round design is confirmed for MVP (PR7); flexible DAY/NIGHT Shift Sessions are a confirmed future direction, not yet scheduled to a PR — see `AGENTS.md` and `docs/ROADMAP_STATUS.md`. |
| Ward recording | First receiving ward/department only, required, immutable except via an audited correction action. No later-transfer tracking. |
| Return/receipt | **One atomic operation**, not two. Outcome is binary: **usable** (→ `AVAILABLE_AT_POOL`) or **defective** (→ `UNAVAILABLE_DEFECTIVE`). No `PENDING_CLEANING`, no `CLEANING`, no separate cleaning-confirmation step. |
| Equipment states | Exactly 4: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`. |
| Transaction states | Exactly 2: `OPEN`, `CLOSED`. No `overdue`, no `due_at` in the active workflow. |
| Borrower/loan concepts | Removed entirely. No `borrower_name` requirement, no due dates, no overdue state. |

---

## Part B — Reconciliation of Prior Audit Findings (§8.1)

### B.1 — The single most important reconciliation: cleaning workflow is fully superseded

**Workflow Audit §4.1, §4.2, §6.1** recommended a 5-state equipment model (including a merged `PENDING_CLEANING`/`CLEANING` state) and a **two-step** return process ("Return Received" then "Cleaning Confirmed"), reasoning that splitting the operation was the only way to structurally prevent cleaning-bypass.

**This recommendation is explicitly superseded and must not be implemented.** The hospital has confirmed:
- The application does not model cleaning at all — cleaning is a physical process that may happen before or after the digital entry, and the software only records one outcome.
- The equipment state model is 4 states, not 5 — `PENDING_CLEANING` does not exist.
- The return/receipt operation is **one** atomic action with a binary outcome (usable/defective), not two actions.

**Why this is not a regression of the underlying safety concern:** the workflow audit's real goal was preventing equipment from silently becoming available without anyone taking responsibility for its condition. That goal is fully satisfied by the confirmed design — every receipt still requires an explicit, authenticated, timestamped outcome decision (usable or defective) — it simply does not require *two* digital steps to get there. The concurrency risk the two-step design was also trying to mitigate (a second, uncoordinated confirmation silently overwriting the first) is **fully addressed by fixing Backend Audit Finding 14.1 directly** (concurrency-safe single receipt), which this plan treats as the actual fix, not the two-step split.

Every other reference to `PENDING_CLEANING`, `CLEANING`, "Cleaning Confirmed," or "Ready for Dispatch" anywhere in Workflow Audit `03` is likewise superseded and excluded from this plan.

### B.2 — Full topic-by-topic reconciliation

| Topic | Prior finding(s) | Confirmed requirement | Reconciliation outcome |
|---|---|---|---|
| **Borrow vs. Dispatch terminology** | Workflow Audit §3 (recommendation, not yet confirmed) | Confirmed: dispatch/issue/receipt terminology | **Confirmed, adopted as a requirement.** Internal route paths (`/borrow`, `/return`) may stay unchanged for MVP to limit blast radius (see PR7 rationale) — only display terminology, model/field naming for *new* fields, and documentation must use Dispatch/Receiving Ward/Routine Round/On-Demand/Return to Pool. |
| **Borrower name removal** | Workflow Audit M1 (Critical); Backend Audit did not flag this (out of its scope) | Confirmed: remove entirely, no person-name replacement | **Confirmed.** Elevated from "recommendation" to "requirement" — no change in urgency (already Critical). |
| **Receiving Ward becoming required** | Workflow Audit M1, §5.1 | Confirmed: required field | **Confirmed**, same severity as above (they are the same defect from two angles — a wrongly-optional field and a wrongly-required field, fixed together in one PR). |
| **`due_at` / overdue removal** | Backend Audit 14.2 (Critical — permanently blocks return once triggered), Workflow Audit M2/M3 | Confirmed: remove from active workflow; disable scheduler; handle existing `overdue` rows explicitly in migration; if "long outstanding" tracking is wanted later, compute read-only from dispatch time | **Confirmed and clarified.** The confirmed requirement adds migration precision the audits didn't have (explicit handling of existing `overdue` rows) — this raises the migration-design bar (see §9) but does not change the Critical severity of the underlying defect. |
| **Cleaning workflow states/actions** | Workflow Audit §4.1/§4.2/§6.1 (recommended 2-step process) | Confirmed: no cleaning workflow; 1 atomic receipt; 4-state model | **Superseded — see B.1.** The workflow audit's recommendation is retired, not carried forward. |
| **Single receipt operation** | (new, not previously specified this way) | Confirmed | **New confirmed requirement**, directly shapes PR7. |
| **Receipt outcome: usable or defective** | Backend Audit 9.1 (recommended constraining `condition` to a 5-value `Literal` including `pm`/`calibration`) | Confirmed: binary outcome only | **Backend Audit 9.1's specific sub-recommendation (5-value Literal) is superseded** by a 2-value outcome enum. The *general* point of Finding 9.1 (constrain input validation, don't leave it to a bare `ValueError`) is still correct and still applies — just to a 2-value enum instead of 5. |
| **Quantity field relevance** | Backend Audit W.1 (Medium — recommended adding `Field(gt=0)`) | Confirmed: one equipment scan/selection identifies exactly one physical device | **Backend Audit W.1's fix is superseded.** Validating `quantity > 0` is the wrong fix for a field that shouldn't exist in this workflow at all — one dispatch scan/selection is inherently one physical device. Recommend **removing `quantity` from the dispatch write path** for MVP (server-side implicit 1), not validating it. |
| **Role model reduction** | Workflow Audit §10 (recommendation: 3 roles) | Confirmed: exactly 3 roles, with a specific permission matrix | **Confirmed**, and the confirmed permission matrix is more detailed than the workflow audit's version (e.g., it explicitly gives Equipment Pool Staff the ability to mark equipment defective, which the current code restricts to `admin`/`biomedical_engineer`). PR9 must implement the *confirmed* matrix, not the workflow audit's earlier draft, where they differ. |
| **Inventory import priority** | Workflow Audit gap table (High, MVP) and Workflow Audit §8 (identifier separation, prerequisite); Schema Audit §9.2 (case/whitespace-sensitive business-key uniqueness, directly relevant to equipment-identifier normalization — `knowledge/architecture/identifiers.md`) | Confirmed: required for MVP, with a detailed field mapping | **Confirmed as MVP-required.** Sequenced after identifier work (PR5) and the dedicated audit-logging PR (PR3, since imports must be audited) — see PR12. |
| **Commit-boundary refactor timing** | Backend Audit 6.1 (Medium — no live bug today, structural risk) | Not addressed by confirmed requirements (out of scope of hospital's business input, purely an engineering-quality item) | **Timing clarified: P2, not P0/P1.** The confirmed atomic-receipt requirement (§5) is satisfiable using the *existing* per-function manual-commit pattern (the same pattern that already correctly makes dispatch atomic today, and the same pattern the new audit-logging PR uses) — it does not require the broader `get_db()` refactor first. Deferred to hardening (PR14), not a blocker for any MVP PR. |
| **Exact `COUNT(*)` priority for realistic hospital data volume** | Backend Audit 5.2 (High, framed against 500,000+ equipment / 2,000,000+ transactions) | Confirmed scope: "selected" devices, "primarily infusion pumps and some other shared equipment" — an Equipment Pool fleet, not a hospital-wide asset register | **Severity lowered from High to Medium/P2 for this MVP.** The original framing assumed the broader, since-abandoned hospital-wide asset-management scale. At Equipment-Pool scale (order of magnitude: low hundreds of devices, thousands of transactions per year — **estimate, needs hospital confirmation**, see §14), an exact `COUNT(*)` is not a meaningful performance risk. The fix remains correct and cheap and is kept in the backlog (PR14) but is explicitly not a pilot blocker. |
| **JWT role claim vs. database role lookup** | Backend Audit 2.1 (Medium, framed against "100+ concurrent users") | Confirmed scope: Equipment Pool staff only use the system — a small, bounded user population (estimate: single-digit to low-double-digit concurrent users at any of the four daily round times) | **Severity/priority lowered to P3.** Same reasoning as above — the optimization is still correct but immaterial at this user scale. Not a blocker at any gate. |
| **Dashboard SSE connection exhaustion** | Backend Audit 17.1/15.2/8.1 (Critical) | Not addressed by confirmed requirements directly, but the explicit P0 grouping in the task input (§8.4 "Security and Availability Foundation") places it alongside the JWT guard | **Severity held at Critical, placement confirmed P0.** Even at small user scale, this is an *architectural* bug (unbounded session lifetime), not a scale-dependent one — a single wall-mounted dashboard left open indefinitely is enough to eventually contribute to pool pressure, and the fix is cheap. No downgrade. |
| **JWT secret production guard** | Backend Audit 10.1 (Critical) | Not scope-dependent | **Unchanged, Critical, P0.** A full authentication bypass is Critical regardless of user count or business scope. |
| **Concurrent return protection** | Backend Audit 14.1 (Critical) | Confirmed single-operation receipt design | **Unchanged severity, but the fix surface is simplified.** Under the now-confirmed single-operation receipt model, only *one* transition needs a concurrency guard (`ISSUED_TO_WARD → CLOSED`), not the two the workflow audit's superseded two-step design would have required. This is a net reduction in implementation complexity from what Workflow Audit §9 anticipated. |
| **Transaction number generation** | Backend Audit 14.3 (High); Workflow Audit §9 (elevated priority given 4×-daily round bursts) | Confirmed: exactly 4 fixed routine-round times, all dispatches for a round plausibly submitted in a tight window | **Severity raised to Critical/P0 for this plan.** The confirmed fixed-round schedule is close to a worst-case trigger for this exact race (many concurrent dispatches, same clock time, four times daily, every day) — this is elevated beyond both prior audits' independent assessments now that the real operating pattern is confirmed, not assumed. |
| **Audit logging coverage** | Backend Audit 12.1 (Critical, user/role) + 12.2 (High, auth events + master data) + 20.2's request-correlation prerequisite + Workflow Audit gap table (duplicate citation of the same gap) | Confirmed requirement explicitly lists user creation, role changes, activation/deactivation, password reset, ward correction, and inventory import as required audit events | **Duplicate finding merged.** Severity held at Critical (driven by the user/role-management sub-case). **Assigned to PR3 as a reusable framework, not call-site-only work:** one canonical writer, current auth/user/master/equipment coverage, actor/subject semantics, recursive redaction, basic request/correlation context, additive migration, admin-only bounded reads, and PostgreSQL-backed evidence. Later endpoints such as Ward Correction (PR9), Role Model Consolidation (PR10), and Inventory Import (PR12) depend on this framework and add their own events when those capabilities exist. Broad production observability remains PR15. |

### B.3 — Findings unaffected by the confirmed requirements (carried forward unchanged)

These remain valid, are not touched by the business-workflow confirmation, and keep their original severity and audit citation:

- Schema Audit — no `ondelete` policy on any FK (High); `users` table has no soft-delete despite ~9 FK-referencing tables (High); no `CHECK` constraints anywhere (High, grouped); case/whitespace-sensitive business-key uniqueness (Medium) — **directly relevant now to BCM Code and Item No** (`knowledge/architecture/identifiers.md`), see §9; mixed index-naming convention (High); documented partial indexes never implemented (High).
- Backend Audit — no optimistic locking anywhere (High, root enabler of 14.1); unhandled `IntegrityError` across create endpoints (High); synchronous bcrypt/openpyxl/qrcode blocking the event loop (High); N+1 in scheduler notification jobs (High); all Redis errors silently swallowed with no logging (High, with the refresh-token-revocation instance specifically Critical-adjacent per 10.3); no login rate limiting (High); inconsistent error envelope (High); PATCH cannot clear fields to null (Medium); no request-level structured logging (Medium).

### B.4 — Recommendations that must **not** be implemented

Per the confirmed requirements and this reconciliation:

- `PENDING_CLEANING`, `CLEANING` equipment states (superseded, B.1).
- "Cleaning Confirmed" / "Ready for Dispatch" as a separate operation or endpoint (superseded, B.1).
- A 5-value `condition` `Literal` for return outcome (superseded by 2-value usable/defective).
- `Field(gt=0)` validation on `quantity` (superseded — field should be removed from the dispatch write path, not validated).
- A 5-state equipment model (superseded — 4 states only).
- Any ward-transfer-tracking feature (out of scope, unchanged).
- Any MEMS, PM, calibration, or recall feature (out of scope, unchanged).

---

## Part C — Prioritized Backlog (§8.2)

| # | Item | Prior finding(s) | Priority | Justification |
|---|---|---|---|---|
| 1 | Production JWT secret guard | Backend Audit 10.1 (Critical) | **P0** | Full auth bypass if unset; zero business-logic dependency, ship first. |
| 2 | Dashboard SSE connection/session leak | Backend Audit 17.1/15.2/8.1 (Critical) | **P0** | Can exhaust the connection pool and hang the entire API; architectural, not scale-dependent. |
| 3 | Unhandled `IntegrityError`/`ValueError` on create/receipt paths | Backend Audit 9.1 (High) | **P0** | Every duplicate-ME-Code registration and every malformed receipt-outcome value will hit this in normal pilot operation, not an edge case. |
| 4 | Reusable audit logging framework and current endpoint coverage | Backend Audit 12.1 (Critical) + 12.2 (High) + 20.2 (request-correlation prerequisite) | **P0** | Establishes the canonical write/read path and safe request context on which all later required audit events depend. **Assigned to PR3.** |
| 5 | Concurrent double-receipt protection | Backend Audit 14.1 (Critical) | **P0** | Confirmed single-atomic-receipt design still needs this; silently losing a "defective" report is a patient-safety-adjacent risk. |
| 6 | Transaction-number race | Backend Audit 14.3 (High → raised, B.2) | **P0** | Elevated given confirmed 4×-daily concurrent-round pattern. |
| 7 | Dedicated BCM Code / Item No fields + identifier separation | Workflow Audit §8 (identifier separation, confirmed as MVP-required); Schema Audit §9.2 (case/whitespace-sensitive uniqueness, directly relevant to identifier normalization — `knowledge/architecture/identifiers.md`) | **P0** | Every other MVP workflow item (dispatch, receipt, search, import) depends on BCM Code and Item No existing as real, distinct fields first — populated via ordinary equipment-record maintenance and the future inventory import (Roadmap PR12), not a mechanical backfill or spreadsheet reconciliation (see PR5, `knowledge/adr/ADR-002-identifier-model.md`). |
| 8 | Equipment state model (4 states) | Workflow Audit §4 (superseded 5-state version), confirmed §6 | **P0** | Dispatch-eligibility and defective/decommissioned blocking depend on this being correct before any workflow PR lands. |
| 9 | Borrower-name removal / Receiving Ward requirement | Workflow Audit M1 (Critical) | **P1** | Depends on #7/#8 landing first (shared schema/service layer); blocks UAT, not the technical pilot foundation. |
| 10 | Routine Round / On-Demand dispatch types | Confirmed requirement §4 | **P1** | Core MVP workflow, depends on #7–#9. |
| 11 | Single equipment receipt workflow (usable/defective) | Confirmed requirement §5, supersedes Workflow Audit §6 | **P1** | Core MVP workflow; depends on #5 (concurrency guard) and #8 (state model) landing first. |
| 12 | Disable `due_at` / overdue | Backend Audit 14.2 (Critical), confirmed §7 | **P1** | Must land before or alongside #11 so the receipt path is never blocked by a stale overdue transition during UAT. |
| 13 | Role and permission changes (3-role model) | Workflow Audit §10, confirmed §3 | **P1** | Needed for UAT to reflect real operating permissions; depends on #4 (audit logging) so role changes are themselves audited from day one. |
| 14 | Ward correction with audit | Workflow Audit §7, confirmed §4 | **P1** | Required MVP capability; depends on #9 and #4. |
| 15 | Search and history (BCM Code manual search per `knowledge/adr/ADR-003-bcm-manual-search.md`; dispatch-type/round-aware) | Workflow Audit §8.4 ("Search behavior"), confirmed §4/§11 | **P1** | Needed for UAT; depends on #7 and #10. |
| 16 | Frontend terminology (Dispatch/Receiving Ward/Routine Round/On-Demand/Return to Pool) | Workflow Audit §3, confirmed | **P1** | Must land alongside #9–#11 so UAT users never see stale "Borrow"/"Borrower"/"Due Date" language. |
| 17 | Inventory import | Confirmed requirement §2/§10 | **P1** | Required for MVP; depends on #7 (target schema must exist first). |
| 18 | Concurrency tests (dispatch burst, receipt race) | Backend Audit 14.1/14.3, confirmed §11 | **P0/P1 split** | Tests for #5/#6 ship with those PRs (P0); the full routine-round-burst load scenario is validated at Pilot Readiness (P1/gate item, §13). |
| 19 | Migration tests | §9 of this plan | **P0/P1 split** | Each migration's own verification query ships with its PR; a full end-to-end migration rehearsal against a production-like copy is a Pilot Readiness gate item. |
| 20 | Audit coverage tests | Confirmed requirement §12 | **P1** | Ships with #4/#13/#14/#17, consolidated verification at UAT gate. |
| 21 | Commit-boundary centralization | Backend Audit 6.1 (Medium) | **P2** | Reconciled down from a naive "urgent refactor" read — see B.2. |
| 22 | Exact `COUNT(*)` removal | Backend Audit 5.2 (High → P2 for this scale) | **P2** | Reconciled down — see B.2. |
| 23 | JWT-claim-based authorization | Backend Audit 2.1 (Medium → P3 for this scale) | **P3** | Reconciled down — see B.2. |
| 24 | N+1 in scheduler notification jobs | Backend Audit 16.1 (High) | **P2** | Background-job-only impact, not user-facing; real but not pilot-blocking. |
| 25 | PATCH cannot clear fields to null | Backend Audit 4.1 (Medium) | **P2** | Affects equipment master-data editing quality of life, not correctness of the dispatch/receipt workflow. |
| 26 | General Redis error logging (non-security instances) | Backend Audit 20.1 (High, security-relevant instance is P0 via #4-adjacent work) | **P2** | The refresh-token-revocation instance is folded into P0 item #1's security-hardening PR; the general cache-miss logging gap is P2. |
| 27 | Broad production observability | Backend Audit 20.2 (Medium), after PR3's basic request/correlation context | **P2** | PR3 owns only the IDs and request metadata needed for trustworthy audit rows. Cross-service structured logging, metrics, tracing, alerting, aggregation, dashboards, and production observability infrastructure remain PR15. |
| 28 | Schema hygiene: `ondelete` policies, `users` soft-delete, `CHECK` constraints, index naming | Schema Audit (High, several) | **P2/P3** | Real, but none are triggered by the MVP's actual write patterns during a small pilot; scheduled as deliberate hardening after pilot, not before. |
| — | MEMS, patient tracking, PM, calibration, recall, ward-transfer tracking, cleaning workflow | All three audits (excluded) | **Out of Scope** | Explicitly excluded by the confirmed requirements; not scheduled at any priority. |

**No Critical finding from any audit was downgraded below P0/P1 solely because it originated outside another audit's narrower scope** — the two items that were reconciled downward (`COUNT(*)`, JWT-claim optimization) were **High/Medium**, not Critical, and were reconciled based on the confirmed *business scope* (a bounded Equipment Pool, not a hospital-wide system), not on which audit happened to raise them.

---

## Part D — Pull Request Plan (§8.3 / §8.4)

15 PRs, grouped into six dependency-ordered phases (the five groups named in the task input's §8.4, plus a Post-Pilot Hardening group this plan adds for the reconciled-down P2/P3 items) — improved further where the reconciliation in Part B required it, most notably that the workflow-group PRs are simpler than originally anticipated because the two-step receipt design was dropped. PR3 establishes the Audit Logging Framework immediately after exception handling; later roadmap PRs consume that framework without reopening its core design.

### Group 1 — Security and Availability Foundation

#### PR1 — Production security guardrails
- **Objective:** Close the two Critical, scope-independent security/availability gaps before any other work lands.
- **Included findings:** Backend Audit 10.1 (Critical), 17.1/15.2/8.1 (Critical), 20.1's security-relevant instance (10.3, High).
- **Expected files/modules:** `app/core/config.py` (startup validation), `app/main.py` or a new startup-check module, `app/api/v1/dashboard.py` (session-per-poll-iteration fix), `app/core/redis.py` (add logging to `is_refresh_token_valid`'s fail-open path).
- **Database migration impact:** None.
- **API contract impact:** None (internal hardening; SSE endpoint's external behavior is unchanged, only its resource lifecycle).
- **Frontend impact:** None.
- **Test requirements:** Startup test asserting the app refuses to boot in `production` mode with the default JWT secret; SSE test asserting a connection is released back to the pool between polls (or equivalent — e.g., a test that opens N+1 SSE connections where N = pool size and asserts the N+1th ordinary request still succeeds); log-assertion test for the Redis fail-open path.
- **Acceptance criteria:** App refuses to start in production with the default secret; a held-open dashboard tab does not prevent other requests from acquiring a DB connection; Redis outages during refresh-token validation are logged.
- **Dependencies:** None — first PR.
- **Rollback strategy:** Revert; no data or schema touched, fully reversible by redeploying the prior image.
- **Risk level:** Low (additive checks and a resource-lifecycle fix, no behavior change on the happy path).

#### PR2 — Exception handling for duplicate keys and invalid input
- **Objective:** Replace unhandled `IntegrityError`/`ValueError` with clean, contract-consistent error responses.
- **Included findings:** Backend Audit 9.1 (High), 1.1 (High, error-envelope consistency).
- **Expected files/modules:** `app/main.py` (new exception handler for `IntegrityError`), `app/core/exceptions.py` (activate the already-defined but unused `DuplicateError`), `app/api/v1/users.py` and `app/api/v1/master_data.py` (replace raw `HTTPException` with `DomainError` subclasses).
- **Database migration impact:** None.
- **API contract impact:** Error response shape becomes consistent (`{detail, code, status}`) across all create/duplicate-key scenarios; response *status codes* for these cases change from 500 to 409 (a behavior fix, not a breaking contract change for well-behaved clients).
- **Frontend impact:** None required (the existing `apiErrorMessage()` helper already expects the corrected shape); optional follow-up to surface the new `code` values in UI copy.
- **Test requirements:** Duplicate BCM Code / Item No / employee code / department code registration each return 409 with the standard envelope; malformed receipt-outcome value returns 400/422, not 500.
- **Acceptance criteria:** No duplicate-key or malformed-input scenario produces an unhandled 500 anywhere in the API.
- **Dependencies:** None (independent of PR1, can land in parallel).
- **Rollback strategy:** Revert; no data impact.
- **Risk level:** Low.

#### PR3 — Audit Logging Framework
- **Objective:** Establish one permanent, reusable audit framework for all later roadmap PRs: one canonical audit-write path, consistent action/entity taxonomy, trustworthy actor/subject attribution, unconditional sensitive-data protection, and the minimum request context and read surface needed to investigate an event.
- **Included findings:** Backend Audit 12.1 (Critical, user/role management unaudited), 12.2 (High, authentication events and master-data mutations unaudited), and the request-correlation prerequisite from 20.2. Coverage in PR3 is limited to capabilities that exist now: authentication endpoints; User create/update; current Department/Ward/Location/Category create endpoints; and the existing Equipment create/update/status-change/delete audit calls consolidated onto the canonical writer.
- **Canonical write path:** All in-scope business mutations use one reusable helper that accepts explicit plain-data snapshots and writes through the caller's existing `AsyncSession`; no parallel per-module writer and no ORM object serialization into JSON. Later roadmap PRs must reuse this helper.
- **Actor versus subject:** `actor_user_id`/the audit row's user reference identifies the authenticated user who performed the action. The affected user or other entity is the subject and is identified separately by `entity_type`/`entity_id` and safe before/after data. Every login failure has a null actor; when an account is known it may be recorded only as the subject. When a submitted identifier is unknown, the subject `entity_id` also remains null. An unknown submitted identifier is never stored raw, never stored as a deterministic unkeyed hash, and is never persisted in any enumerable or correlatable representation. A keyed HMAC may be considered only through a separately approved secret-management and retention design; Roadmap PR3 neither requires nor introduces keyed HMAC.
- **Authentication events:** Audit login success, login failure, logout, successful refresh, and password changes/resets through existing endpoints. Login-failure events must persist even though authentication fails and the normal request path would otherwise roll back. Authentication audit delivery may use a documented isolated/best-effort transaction strategy so an audit outage does not prevent legitimate authentication, but failure behavior must be explicit and tested. This exception does not weaken mandatory business-mutation atomicity.
- **Sensitive-data rule:** A centralized, recursive, case-insensitive redaction function runs unconditionally on all before/after payloads, including nested dicts/lists. It must cover password/passwd, hashes and current/new password variants, secret/client secret, access/refresh token, JWT, API keys, authorization headers, cookies, and private keys. Call-site omission is not an accepted control.
- **Request context:** Establish one request ID and correlation ID per HTTP request, propagate them to response headers and audit rows, and safely allow `None` outside HTTP requests. Client-supplied IDs are accepted only when they match a conservative allowlist and are 1–64 characters; invalid or oversized values are replaced with generated IDs and never persisted. Persist only bounded, sanitized User-Agent data. Record client IP from the directly connected peer unless and until an explicit trusted-proxy configuration exists; do not trust forwarding headers by default.
- **Atomicity requirement:** Mandatory business mutations and their audit row use the same `AsyncSession` and transaction. The canonical audit helper flushes but never independently commits; the caller commits once after both writes. An audit-write failure rolls the business mutation back, and a business failure creates no audit event. Existing dispatch/receipt calls are not redesigned here. Authentication failure persistence follows the explicit exception above.
- **Database migration impact:** Additive audit migration only, preserving existing audit rows while adding the bounded request/correlation columns and only focused indexes justified by audit queries, without editing or recreating `0001`, dropping tables, or adding unrelated constraints. Upgrade and downgrade must work on PostgreSQL. Because `0001_initial.py` creates from current ORM metadata, a fresh database may already contain the new columns before the PR3 revision runs; PR3's migration must be idempotent/tolerant of that behavior, while a pre-PR3 database must upgrade and downgrade cleanly.
- **Audit read API:** The existing audit-log read endpoint remains Administrator-only. Reads must have a hard maximum page size, deterministic ordering (for example `created_at DESC, id DESC`), and bounded pagination; no unbounded full-table response is allowed.
- **Duplicate-event rule:** Each in-scope action writes exactly one audit event. Consolidation must remove/avoid parallel writers; client retries remain distinct requests unless a later idempotency mechanism says otherwise. Tests must distinguish legitimate retries from duplicate rows caused by two audit paths.
- **Test requirements:** Unit and API tests cover the canonical writer, actor/subject semantics, recursive redaction, failed-login identifier non-persistence and non-enumerability, valid/invalid/oversized request IDs, bounded User-Agent/IP handling, read authorization and pagination, exactly-one-event coverage, mandatory atomic rollback, and login-failure persistence. PostgreSQL-backed tests must exercise transaction/savepoint behavior and the real Alembic upgrade → downgrade → upgrade path, including both fresh-database and pre-PR3 starting states.
- **Acceptance criteria:** All current in-scope events are attributable without confusing actor and subject; secrets and unknown failed-login identifiers cannot reach audit storage in raw, deterministic-unkeyed-hash, enumerable, or correlatable form; mandatory mutations and audit writes are atomic; failed logins remain auditable; request metadata is bounded and validated; audit reads are Administrator-only and bounded/deterministic; migration round trips pass on PostgreSQL; and every action produces exactly one event.
- **Explicit exclusions:** PR3 does not add missing Role CRUD, User DELETE, or master-data UPDATE/DELETE endpoints. It does not implement transaction-number generation, the equipment identifier model, equipment-state redesign, dispatch/receipt redesign, Shift Sessions, DAY/NIGHT or Standby work, inventory import, frontend/reporting, broad observability, mandatory CI, deployment, or unrelated refactoring.
- **Dependencies:** PR2 (uses the corrected exception/error-envelope foundation).
- **Rollback strategy:** Revert application changes and downgrade only the additive PR3 migration; no existing business table or historical audit row is rewritten.
- **Risk level:** Medium (security-sensitive cross-cutting behavior and migration semantics; bounded by narrow endpoint scope and PostgreSQL-backed evidence).

### Group 2 — Concurrency and Data Integrity

#### PR4 — Transaction-number generation: global sequence, explicit format
- **Objective:** Replace the racy `COUNT + LIKE` transaction-number generator with a single global, concurrency-safe PostgreSQL sequence, and state the resulting number format explicitly. The prior version of this plan incorrectly implied a sequence could be reset daily while keeping the `TX-YYYYMMDD-NNNN` format identical — a normal PostgreSQL sequence does not do this, and that implication is corrected here.
- **Included findings:** Backend Audit 14.3 (raised to Critical/P0, B.2).
- **Chosen strategy (preferred, per this correction):** One global `SEQUENCE` (`transaction_no_seq`). No daily-reset requirement has been confirmed by the hospital, so this plan does not assume one.
  - **Final transaction-number format:** `TX-{YYYYMMDD}-{seq}`, where `{YYYYMMDD}` is the calendar date of creation (cosmetic/human-readable only — it plays no role in uniqueness) and `{seq}` is the raw, zero-padded value from `nextval('transaction_no_seq')`. **The numeric portion is globally monotonic and never resets** — e.g. `TX-20260716-000042` may be followed the next day by `TX-20260717-000043`, not `TX-20260717-000001`. Uniqueness is guaranteed entirely by the sequence, never by the date prefix.
  - **Fallback, only if a daily-reset requirement is later confirmed:** a `transaction_number_counters` table keyed by date, incremented atomically via `INSERT ... ON CONFLICT (date) DO UPDATE SET counter = transaction_number_counters.counter + 1 RETURNING counter` — race-free without a scheduler resetting a shared sequence. **Not implemented now**, documented only so the decision is traceable if the requirement changes.
- **Expected files/modules:** `app/crud/transaction.py` (`generate_transaction_no`, rewritten around `nextval('transaction_no_seq')`), new Alembic migration (out of scope to author here; shape specified in Part E).
- **Database migration impact:** Additive — new `SEQUENCE transaction_no_seq`; existing `transaction_no` values are untouched and remain valid; no backfill needed. See Part E.
- **API contract impact:** None — the display format is visually similar to today's, though the numeric portion's meaning changes (global monotonic value, not a same-day count); documented so downstream consumers aren't surprised the suffix doesn't restart daily.
- **Frontend impact:** None.
- **Test requirements:** Concurrent-dispatch test asserting N simultaneous dispatch requests (simulating a routine-round burst) each receive a unique transaction number with zero collisions; an explicit test asserting the numeric suffix is **not** reset across a simulated day boundary; a rollback-safety test confirming a freshly-recreated sequence (disaster-recovery scenario) is seeded above the highest historical suffix.
- **Acceptance criteria:** No two transactions ever share a number under concurrent load, including across simulated day boundaries; generation is O(1), not O(n); the non-resetting format is documented for hospital staff.
- **Dependencies:** None.
- **Rollback strategy:** Revert application code; the sequence can remain harmlessly unused or be dropped in a follow-up migration — if ever recreated, it must be seeded above the highest already-used suffix to avoid colliding with historical values.
- **Risk level:** Low-Medium (touches every dispatch creation path; must be load-tested before merge; the non-reset behavior must be communicated to hospital staff before pilot).

#### PR5 — Equipment Master identifiers, BCM manual search, and hospital Item-No QR identification

> **Governance status:** this entry's architecture was resolved by a
> dedicated Governance PR after an earlier draft of this section (which
> specified a distinct "ME Code" identifier) proved contradictory with a
> later-confirmed design. That earlier text is retained only in
> **Appendix Z (Historical — Superseded PR5 Requirements)** at the end of
> this document; it is not an active requirement and must not be
> implemented. The active contract below is authoritative.

- **Objective:** Give equipment the identifier model, manual-search behavior, and QR identification defined by `knowledge/adr/ADR-002-identifier-model.md`, `ADR-003-bcm-manual-search.md`, and `ADR-004-hospital-item-no-qr.md`, and their elaborating documents in `knowledge/architecture/` and `knowledge/business-rules/`. This roadmap entry states scope, sequencing, and acceptance evidence; the architecture itself is defined in those documents and is not restated here — see them for identifier roles, canonicalization, search behavior, QR resolution, and API information boundaries.
- **Included findings:** Workflow Audit §8 (identifier-model gap, field mapping — now resolved per ADR-002 rather than left open), Schema Audit §9.2 (case/whitespace-sensitive business-key uniqueness — directly applicable to the canonicalization rules in `knowledge/architecture/identifiers.md`), confirmed requirements §2.
- **Scope:** Equipment Master identifier support for BCM Code, Item No, and Asset Number (ADR-002); BCM-Code-only manual search (ADR-003); exact hospital Item-No QR lookup (ADR-004); canonical identifier writes applied identically at create and update (`knowledge/architecture/identifiers.md`); the operator-facing API information boundary, in particular that Item No is never returned by an operator-facing response (`knowledge/architecture/api-information-boundaries.md`); required migration and regression evidence.
- **Database migration impact:** Additive columns for BCM Code and Item No, nullable until populated (no mechanical backfill from `asset_number` or any other existing column), canonicalized and uniquely constrained on their canonical form per `knowledge/architecture/identifiers.md`. Population comes from ordinary equipment-record maintenance now and from the future inventory import (Roadmap PR12) once scoped.
- **API contract impact:** Equipment Master endpoints gain BCM Code; a manual-search surface matching BCM Code only, returning the minimal disclosure ADR-003 defines; a QR-resolution surface matching Item No only by exact match. Item No is reachable only through an explicitly restricted administrative/import contract, never through an operator-facing one (`knowledge/architecture/api-information-boundaries.md`).
- **Frontend impact:** Equipment selection offers QR scan (primary) and BCM manual search (fallback), per `knowledge/business-rules/equipment-selection.md` and `borrow-return-selection.md`; neither path exposes Item No to the operator.
- **Test requirements:** canonicalization round-trip for BCM Code and Item No (case, whitespace, leading zeros), applied identically to create and update, not create-only; duplicate rejection on the canonical form, not only byte-identical input; BCM search behavior matching ADR-003 (partial match, prefix-optional, exact-first ranking, bounded, minimal disclosure); QR resolution matching ADR-004, including a real distinction between a malformed scan and a well-formed-but-unmatched Item No; a test proving Item No is absent from every operator-facing response, including after a manual-search selection; migration upgrade/downgrade evidence.
- **Acceptance criteria:** implementation matches `knowledge/adr/ADR-002`, `ADR-003`, `ADR-004`, and their elaborating architecture/business-rules documents; no identifier is entered, searched, or exposed outside the role ADR-002 assigns it; no ME-Code-based requirement from Appendix Z is implemented.
- **Dependencies:** None beyond PR1–PR4. Implementation depends on this architecture being resolved (this Governance PR) before it proceeds toward merge; an implementation attempt opened before that resolution must be reconciled against it first.
- **Rollback strategy:** New columns can be dropped without affecting existing `asset_number`-based functionality if reverted before any downstream PR depends on them; after real BCM Code/Item No data has been written, a forward fix is preferred over a destructive downgrade.
- **Risk level:** Medium — schema and API-contract change touching the primary operator-facing identifier. Resolving the architecture through a dedicated Governance PR (this entry) removes the ambiguity risk the prior, contradictory draft carried; remaining risk is ordinary implementation risk.

#### PR6 — Equipment state model migration (4 states)
- **Objective:** Collapse the current 8-value `EquipmentStatus` enum to the confirmed 4-state model, with legacy values preserved for audit/history purposes.
- **Included findings:** Workflow Audit §4 (superseded 5-state proposal), confirmed requirements §6; Schema Audit §6 (enum-usage findings — no DB-level constraint on status today).
- **Expected files/modules:** `app/models/equipment.py` (`EquipmentStatus` enum), `app/crud/equipment.py` (`change_status`, dispatch-eligibility check), `app/services/borrow_service.py` (dispatch-eligibility check — currently `!= AVAILABLE`, must be preserved/re-verified against the new enum).
- **Database migration impact:** Data remap of existing `equipment.status` values into the 4 confirmed values, **with the original value preserved in a new `legacy_status` column** (see Part E for the exact per-value mapping). **Owner-confirmed decision (supersedes this section's prior draft language): legacy `cleaning` maps directly to `AVAILABLE_AT_POOL`, not `UNAVAILABLE_DEFECTIVE`.** Cleaning is performed as part of equipment collection/receipt, not a separately tracked state (see `AGENTS.md`); a `cleaning` row already represents a device that was collected, cleaned, and checked, i.e. exactly the state `AVAILABLE_AT_POOL` describes. This requires no manual review, no dispatch-blocking classification, and no additional staff sign-off.
- **API contract impact:** `EquipmentStatus` enum values change; this is a breaking contract change for any client hardcoding the old 8 values — coordinated with frontend in PR11.
- **Frontend impact:** Status badges/labels updated to the 4 new values (full UI rename lands in PR11; this PR can ship with minimal placeholder labels if sequencing requires it). A `legacy_status='cleaning'` row displays as ordinary `AVAILABLE_AT_POOL` equipment — no defect badge, no migration-review warning, and no distinguishing treatment relative to any other `AVAILABLE_AT_POOL` row.
- **Test requirements:** Mapping-correctness test per legacy value; dispatch-block test for each non-`AVAILABLE_AT_POOL` state including the new `DECOMMISSIONED`; invalid-transition rejection tests per Workflow Audit §4.4's table.
- **Acceptance criteria:** Only `AVAILABLE_AT_POOL` equipment can be dispatched; `DECOMMISSIONED` is terminal (no normal-workflow exit); every legacy status value has an explicit, documented mapping, including `cleaning` → `AVAILABLE_AT_POOL`.
- **Dependencies:** None (independent of PR5, though both touch `app/models/equipment.py` and should be sequenced to avoid merge conflicts — recommend PR5 lands first).
- **Rollback strategy:** `legacy_status` column preserves full reversibility of the data remap; application code revert restores the old enum's behavior against `legacy_status`.
- **Risk level:** Medium (data remap across an owner-confirmed mapping table, including `cleaning` → `AVAILABLE_AT_POOL`; no open product ambiguity remains).

### Group 3 — Domain Model Foundation

#### PR7 — Dispatch record model: OPEN/CLOSED, dispatch type, routine round, field cleanup
- **Objective:** Rename transaction states to `OPEN`/`CLOSED`, add `dispatch_type` and `routine_round`, make `ward_id` required, remove the `borrower_name` requirement, remove `due_at`/overdue from the active write path, remove `quantity` from the dispatch write path. The fixed-round enum here is an intentional MVP simplification, not a permanent design choice — the confirmed future Shift Session direction (see `AGENTS.md`) builds on top of the `dispatch_type`/round concept rather than requiring this PR to be reworked; PR7's own scope does not change to accommodate it.
- **Included findings:** Workflow Audit M1/M2/M3/M8 (Critical/High), confirmed requirements §4/§7, Backend Audit 14.2 (Critical), Backend Audit W.1 (superseded, B.2).
- **Expected files/modules:** `app/models/transaction.py` (status rename, new `dispatch_type`/`routine_round` columns, `borrower_name` made nullable, `quantity` dropped from write path or hardcoded), `app/schemas/transaction.py` (`BorrowRequest` contract change), `app/services/borrow_service.py` (`due_at`/overdue logic removed), `app/worker/scheduler.py` (`check_overdue_returns` job disabled/removed).
- **Database migration impact:** New `dispatch_type`/`routine_round` columns; `borrower_name` becomes nullable going forward (existing values preserved for history, per §9); existing `overdue` rows explicitly reviewed and converted to `OPEN` or `CLOSED` based on actual return data (§9); `ward_id` becomes required for *new* rows only (existing null `ward_id` rows are flagged, not auto-assigned — §9).
- **API contract impact:** `BorrowRequest` no longer accepts/requires `borrower_name`; requires `ward_id`; gains `dispatch_type` (required) and `routine_round` (required only when `dispatch_type == ROUTINE_ROUND`); `due_at` removed from the request/response contract.
- **Frontend impact:** `BorrowPage.tsx` loses the borrower-name field, gains ward (now required, not optional), dispatch-type selector, and routine-round selector (shown conditionally).
- **Test requirements:** Schema-validation tests for the new required/optional field combinations; scheduler-disabled verification test; a test explicitly confirming no dispatch can be created without a ward.
- **Acceptance criteria:** Matches confirmed requirements §4 and §12 ("Routine Dispatch"/"On-Demand Dispatch" acceptance criteria) exactly.
- **Dependencies:** PR6 (shares the transaction↔equipment status-transition logic touched by both).
- **Rollback strategy:** New columns are additive and can be ignored by a reverted application version; `borrower_name`/`ward_id` nullability changes are non-destructive in either direction.
- **Risk level:** Medium (the most field-heavy PR in the plan; recommend splitting further into 7a — status rename + due_at/overdue removal, and 7b — dispatch_type/routine_round/ward-required/quantity-removal — if the reviewing team prefers smaller units; presented here as one PR given the plan is now at 15 total, the upper end of the target 8–15 range).

### Group 4 — MVP Workflow

#### PR8 — Atomic single-operation equipment receipt with concurrency guard
- **Objective:** Replace the 5-option `condition`-based return with the confirmed single atomic receipt operation and a binary usable/defective outcome, with a database-level guard against double-receipt.
- **Included findings:** Backend Audit 14.1 (Critical), confirmed requirements §5 (supersedes Workflow Audit §6's two-step design per B.1).
- **Expected files/modules:** `app/services/borrow_service.py` (`return_equipment` rewritten around a 2-value outcome and a conditional-update/locking guard), `app/schemas/transaction.py` (`ReturnRequest.condition` → `outcome: usable | defective`), `app/api/v1/borrow.py`.
- **Database migration impact:** None new beyond PR6/PR7's columns; adds the concurrency-guard mechanism itself (a conditional `UPDATE ... WHERE status = 'OPEN'` checked against affected-row-count, or an optimistic-locking version column — mechanism choice deferred to implementation, either satisfies the requirement).
- **API contract impact:** `POST /return/{id}` (or a renamed equivalent) now accepts `outcome: "usable" | "defective"` instead of the 5-value `condition`.
- **Frontend impact:** `ReturnPage.tsx` simplified to a single-step form with a two-choice outcome selector, no condition radio group.
- **Test requirements:** The full concurrent-receipt matrix from §11 below (two simultaneous receipts on the same dispatch → exactly one succeeds; receipt with no OPEN dispatch is rejected; receipt of already-`DECOMMISSIONED` equipment cannot occur since it can never be `ISSUED_TO_WARD` in the first place — verified as a defense-in-depth test, not just a logical inference).
- **Acceptance criteria:** Matches confirmed requirements §5 and §12 ("Receipt") exactly.
- **Dependencies:** PR6, PR7 (needs the 4-state model and OPEN/CLOSED transaction model in place first).
- **Rollback strategy:** Revert; the OPEN/CLOSED and 4-state models from PR6/PR7 remain valid and usable by the prior (superseded) return logic if a true rollback is needed, though the concurrency defect would return with it — recommend forward-fix over rollback for this specific PR given the severity of what it fixes.
- **Risk level:** Medium-High (the most safety-critical PR in the plan; requires the concurrency test matrix to pass before merge, not just after).

#### PR9 — Ward correction action
- **Objective:** Add the confirmed audited "correct an incorrectly recorded receiving ward" capability.
- **Included findings:** Workflow Audit §7, confirmed requirements §4.
- **Expected files/modules:** New endpoint in `app/api/v1/borrow.py` (or a dedicated module), `app/crud/transaction.py` (a narrow, purpose-built update — not a generic PATCH), `app/crud/audit.py` (before/after ward capture).
- **Database migration impact:** None (uses existing `ward_id`, `audit_logs`).
- **API contract impact:** New endpoint, e.g. `POST /transactions/{id}/correct-ward`.
- **Frontend impact:** New correction action, gated to Administrator + Equipment Pool Staff per the confirmed permission matrix, requiring a mandatory reason/note.
- **Test requirements:** Authorization test (Read-Only cannot correct); audit-entry test (before/after ward captured, actor captured, following the PR3 convention); immutability test (no *other* path can alter `ward_id` on an existing transaction).
- **Acceptance criteria:** A ward correction is possible only through this action, only by authorized roles, and always produces exactly one audit entry.
- **Dependencies:** PR7 (needs `ward_id` semantics finalized), **PR3 (audit logging — ward correction's audit entry must follow the same actor/action/target/before-after convention established there)**.
- **Rollback strategy:** Revert; fully additive, no destructive schema change.
- **Risk level:** Low.

#### PR10 — Role model consolidation (3 roles)
- **Objective:** Replace the current 5-role model with the confirmed 3-role model and permission matrix.
- **Included findings:** Workflow Audit §10, confirmed requirements §3.
- **Expected files/modules:** `app/models/user.py` (role constants), `app/api/v1/deps.py` (every `require_roles(...)` call site updated to the confirmed matrix), seed/role data, every endpoint currently gated by `ward_nurse`/`transport_staff`/`biomedical_engineer`.
- **Database migration impact:** Role seed-data change; **existing user-to-role assignments require a manual mapping decision per real account** (flagged explicitly — this is not a mechanical migration, see Part E and §14). Role reassignments must themselves be audited (per PR3).
- **API contract impact:** Permission-check behavior changes across most mutating endpoints (mechanical, not structural).
- **Frontend impact:** Role-based UI gating (nav items, buttons) updated to the 3-role model.
- **Test requirements:** Full RBAC matrix test — every capability in the confirmed permission table (§3 of the input) exercised against all 3 roles, asserting both the allowed and the explicitly-denied cases (e.g., Equipment Pool Staff must be denied user management and reactivation-from-defective).
- **Acceptance criteria:** Matches the confirmed permission matrix exactly, including every "Must not" line item; every role assignment/reassignment produces an audit entry.
- **Dependencies:** PR2 (uses the corrected `DomainError`/403 pattern), **PR3 (role changes must be audited)**, PR5/PR9's endpoints for permission wiring.
- **Rollback strategy:** Revert; role *names* can be reverted independently of role *assignments* if a staged rollout is preferred (e.g., add new roles alongside old ones before removing the old ones — recommended approach, see Part E).
- **Risk level:** Medium (touches authorization on nearly every endpoint — mechanical but broad; must be covered by the full RBAC test matrix before merge).

### Group 5 — Data and User Interface

#### PR11 — Frontend terminology and workflow UI pass
- **Objective:** Land the full user-facing terminology change and the new dispatch/receipt UI shape in one coordinated pass.
- **Included findings:** Workflow Audit §3, §7.1 (UI labeling), confirmed requirements throughout.
- **Expected files/modules:** `frontend/src/pages/BorrowPage.tsx` → dispatch UI, `frontend/src/pages/ReturnPage.tsx` → receipt UI, `frontend/src/pages/EquipmentDetailPage.tsx` (ward-label caption per Workflow Audit §7.1), status badge components, navigation labels.
- **Database migration impact:** None.
- **API contract impact:** None (consumes PR6–PR8's already-shipped API contracts).
- **Frontend impact:** The primary deliverable of this PR.
- **Test requirements:** Component tests for the new dispatch/receipt forms; an end-to-end workflow test (dispatch → receipt) using only the new terminology and fields.
- **Acceptance criteria:** No "Borrow," "Borrower," "Due Date," "Overdue," or "Loan" terminology remains visible anywhere in the UI; the ward field carries the confirmed caption disclaiming real-time-location tracking.
- **Dependencies:** PR7, PR8, PR10 (consumes all three APIs).
- **Rollback strategy:** Frontend-only revert; backend contracts are unaffected either direction.
- **Risk level:** Low-Medium (UI-only, but user-facing — recommend a UAT dry-run before merge given it's the surface pilot users will judge the system by).

#### PR12 — Inventory import
- **Objective:** Build the confirmed inventory import workflow (see full design in §10).
- **Included findings:** Confirmed requirements §2/§10.
- **Expected files/modules:** New `app/services/import_service.py`, new `app/api/v1/import.py` (upload/preview/commit endpoints), `app/crud/equipment.py` (bulk-aware update path).
- **Database migration impact:** None beyond PR5's columns.
- **API contract impact:** New endpoints only, no existing-contract changes.
- **Frontend impact:** New Administrator-only import UI (upload → preview → confirm).
- **Test requirements:** The full import test matrix from §11 below.
- **Acceptance criteria:** Matches §10's design in full, including preview-before-commit, per-row success/failure reporting, and exactly one audit entry per import batch (per PR3's convention).
- **Dependencies:** PR5 (target schema must exist), **PR3 (import must produce an audit record per the confirmed requirement)**.
- **Rollback strategy:** Revert; import is an additive capability with no effect on existing data unless explicitly run.
- **Risk level:** Medium (data-quality risk is the primary concern, mitigated by mandatory preview and per-row validation — see §10).
- **Implementation note (added during PR12's independent review, GitHub PR #43):** Inventory Import **updates existing equipment only**, matched by canonical BCM Code — it does not create new equipment records. A row whose BCM Code does not match an existing record is rejected during preview (and again, independently, at commit) with a message directing the operator to create that equipment first through the standard Equipment Master workflow, then re-import the file to update it. This is a scoping decision made because `equipment.asset_number` is `NOT NULL`/`UNIQUE` real, hospital-assigned inventory metadata (see `knowledge/adr/ADR-002-identifier-model.md`) that the import source spreadsheet has no column for, and that the import workflow must never generate, derive, or synthesize. **This is deferred follow-up scope, not a permanent prohibition on bulk creation** — a future Roadmap item may add create-from-import once it first defines the real hospital Asset Number assignment workflow (hospital-assigned values, a nullable-provisional-record model, or another authoritative approach), deciding through a dedicated ADR if the identifier model itself needs to change. §10 below is retained as originally written (including its "update existing" design, F.3) as the historical record of the pre-implementation plan; this note is the authoritative statement of what actually shipped.

#### PR13 — Search, history, and reporting adjustments
- **Objective:** Finalize BCM-Code-first search/scan priority (`knowledge/adr/ADR-003-bcm-manual-search.md`), dispatch-type/round-aware history filtering, and remove MVP-irrelevant dashboard/report elements (PM/CAL widgets, overdue indicators) in favor of a read-only "days since dispatch" indicator.
- **Included findings:** Workflow Audit §8.4 ("Search behavior"), confirmed requirements §11/§12 (History/Search acceptance criteria).
- **Expected files/modules:** `app/crud/equipment.py`/`app/crud/transaction.py` (search/filter additions), `app/services/dashboard_service.py` (remove PM/CAL/overdue widgets, add computed duration), frontend `DashboardPage.tsx`/`EquipmentListPage.tsx`.
- **Database migration impact:** None.
- **API contract impact:** New/adjusted query parameters (`dispatch_type`, `routine_round` filters on history); dashboard response shape simplified.
- **Frontend impact:** Search/history/dashboard UI updated accordingly.
- **Test requirements:** Search-behavior tests (BCM Code partial matching with exact match ranked first, per `knowledge/adr/ADR-003-bcm-manual-search.md`); filter-correctness tests for dispatch type/round/date range.
- **Acceptance criteria:** History is filterable and searchable per confirmed requirements §12 ("History Search").
- **Dependencies:** PR5, PR7.
- **Rollback strategy:** Revert; read-only surface, no data risk.
- **Risk level:** Low.
- **Implementation note (added during PR13's implementation):** BCM-Code-first search/scan priority was already fully implemented by Roadmap PR5 (`app/crud/equipment.py`'s `search_bcm`) and verified against every `knowledge/adr/ADR-003-bcm-manual-search.md` requirement (partial/prefix-optional matching, exact-match-first ranking, bounded results, minimal-disclosure suggestions, empty/short-query handling) with existing test coverage in `backend/tests/test_equipment.py` — no new search code was needed. What this PR actually adds: (1) `dispatch_type`/`routine_round`/`from_date`/`to_date` filters on `GET /transactions` (`app/crud/transaction.py`'s `search()`, `app/api/v1/transactions.py`), combinable with the existing `ward_id`/`equipment_id`/`status` filters; (2) `pm_due_soon`/`cal_due_soon` removed from `DashboardSummary` (`app/schemas/dashboard.py`, `app/services/dashboard_service.py`) since `DashboardPage.tsx` (post-PR40) never rendered them; (3) a read-only "days since dispatch" indicator, computed client-side from `borrowed_at` and shown only for OPEN transactions, plus dispatch-type/round distinguishability in the history list (Part H's on-demand-vs-routine acceptance criterion) — both added to `EquipmentDetailPage.tsx`'s existing per-equipment transaction history (the dashboard itself carries no per-transaction history surface after PR40, so this lives there instead of `DashboardPage.tsx`), alongside the new filter controls.

### Group 6 — Post-Pilot Hardening (P2/P3)

#### PR14 — Reliability and performance hardening
- **Objective:** Land the reconciled-down-to-P2 items as one batch: commit-boundary centralization, `COUNT(*)` removal, N+1 fix in scheduler notifications, PATCH null-clearing fix.
- **Included findings:** Backend Audit 6.1, 5.2, 16.1, 4.1 (all Medium/High but P2 per B.2/Part C).
- **Expected files/modules:** `app/db/session.py`, `app/crud/equipment.py`/`transaction.py`, `app/worker/scheduler.py`, `app/crud/equipment.py`/`user.py`.
- **Database migration impact:** None.
- **API contract impact:** Pagination response shape may drop the exact `total` field (coordinated frontend change) if that specific sub-item is included.
- **Frontend impact:** Minor (pagination "N results" label logic if `total` semantics change).
- **Test requirements:** Regression suite re-run; new tests for null-clearing PATCH semantics.
- **Acceptance criteria:** No regression in existing test suite; each hardening item's own acceptance criterion from the originating audit is met.
- **Dependencies:** All prior PRs, PR1–PR13 (this is deliberately last — pure hardening on a stable base).
- **Rollback strategy:** Revert; no data impact.
- **Risk level:** Low.

#### PR15 — Observability and schema hygiene
- **Objective:** Build broad production observability on PR3's basic request/correlation foundation, plus general (non-security-critical) Redis error logging and deferred schema hygiene (`ondelete` policies, `users` soft-delete, `CHECK` constraints, index-naming standardization).
- **Included findings:** Backend Audit 20.1 (general instances), 20.2; Schema Audit (several, P2/P3 per Part C item 28).
- **Expected files/modules:** Structured application logging and cross-service correlation, `app/core/redis.py`, metrics/tracing/alerting and log-aggregation integrations where selected, operational dashboards, and a new migration for `ondelete`/`CHECK`/index-naming changes.
- **Boundary from PR3:** PR3 owns only the validated request/correlation IDs and bounded request metadata needed by audit records. PR15 owns structured cross-service correlation, metrics, tracing, alerting, centralized log aggregation, dashboards, and any production CI or infrastructure assigned to observability. It must reuse PR3's IDs rather than create a second request-context mechanism.
- **Database migration impact:** Constraint additions (see §9 for the general approach — validate-before-enforce).
- **API contract impact:** None.
- **Frontend impact:** None.
- **Test requirements:** Log-format tests; constraint-violation tests for each new `CHECK`.
- **Acceptance criteria:** Matches each originating finding's own suggested fix.
- **Dependencies:** All prior PRs in the original PR1–PR15 sequence. Later
  approved reporting, legacy migration, cutover, and Go-live work follows
  below.
- **Rollback strategy:** Revert; constraints can be dropped independently if they surface unexpected legacy-data violations.
- **Risk level:** Low-Medium (constraint additions always carry some risk of surfacing previously-silent bad data — mitigated by validating before enforcing, per §9's general rule).

### Group 7 — Reporting and operational metadata

#### PR16 — Reporting foundation
- **Objective:** Establish reporting foundations and distinguish the actual
  transaction timestamp, `business_date`, and `shift`.
- **Data-model boundary:** `shift` is operational/reporting metadata, not an
  equipment lifecycle state. Day and Night are values in one model; do not
  create separate tables for them.
- **Dependencies:** PR15B.
- **Acceptance criteria:** New reporting data can be filtered by
  `business_date` and `shift` without losing the actual event timestamp.

#### PR17 — Operational reports
- **Objective:** Provide Receive, Issue, and Equipment Verify Checklist
  reports, filterable by date and shift.
- **Dependencies:** PR16.
- **Acceptance criteria:** Each report uses the same reporting metadata and
  presents consistent date/shift filtering.

#### PR18 — Reporting output
- **Objective:** Add PDF export, Excel export, and print-ready Hard Copy
  templates for the PR17 reports.
- **Dependencies:** PR17.
- **Acceptance criteria:** All three report families can be exported and
  printed without changing transaction or lifecycle business rules.

### Group 8 — Legacy migration and cutover

**Roadmap PR19 split (approved 2026-08-03, see `docs/DECISION_LOG.md`
"Roadmap PR19 approved split: PR19A (backend) / PR19B (frontend
skeleton)"):** PR19 is delivered as two parallel implementation slices from
the same merged baseline, both governed by the shared objective/boundary
below. This is an explicit, Owner-approved exception to this repository's
usual design-document-first slice precedent — no PR19 design document
exists. Neither slice is complete or implemented as of the split decision.

#### PR19A — Legacy Import Foundation (backend)
- **Objective:** Provide a staged, validation-first, traceable import framework.
- **Boundary:** This is separate from PR12's update-only inventory import and
  must not redesign the hospital QR system.
- **Dependencies:** Current implementation through PR18.

#### PR19B — Legacy Import Frontend Skeleton
- **Objective:** Provide a frontend-only, mock-data UI prototype of the
  future import workflow (session list, create flow, validation summary,
  row-level issues, dry-run summary, disabled confirm, result summary) for
  early hospital-user workflow, terminology, navigation, and responsive-
  layout review, ahead of PR19A's real backend contract.
- **Boundary:** No file upload to a backend, no Excel/CSV parsing, no
  validation or dry-run execution, no import execution, no database or
  migration change. Its Equipment Master / Receive History / Issue History
  category labels are preview labels pulled forward from PR20/PR21 scope
  for review purposes only — not an implemented capability, and not an
  approval of PR20 or PR21's own design.
- **Dependencies:** Current implementation through PR18 (developed in
  parallel with PR19A, not stacked on it; contracts are realigned once
  PR19A's real API is approved).

#### PR20 — Equipment Master Import
- **Objective:** Import Equipment Master data using BCM and Item Number
  matching, including equipment attributes and existing hospital QR linkage.
  Detect equipment duplicates and validate equipment records.
- **Boundary:** Legacy BME names and Ward values belong to transaction history
  and are handled by PR21, not this Equipment Master import.
- **Dependencies:** PR19A (the backend import framework; PR19B is a frontend
  preview only and is not a dependency).

#### PR21 — Legacy Receive and Issue History Import
- **Objective:** Import the AppSheet equipment receive-data and equipment
  issue-data sheets; preserve legacy BME names for later user mapping;
  normalize and map Ward values; detect duplicate transaction rows; and retain
  transaction source references.
- **Version 1 boundary:** These are the only transaction-history sheets in the
  initial migration. Equipment Verify Checklist history is not required unless
  a later approved decision explicitly adds it.
- **Dependencies:** PR19A, PR20.

#### PR22 — Legacy Data Validation and Reconciliation
- **Objective:** Perform cross-import validation and reconciliation, verify
  source traceability, review duplicates, and validate the unified display of
  legacy and new transaction history before Go-live.
- **Dependencies:** PR20, PR21.

#### PR23 — Cutover Readiness
- **Objective:** Rehearse migration, obtain reconciliation sign-off, and close
  operational readiness gaps.
- **Dependencies:** PR22.

#### PR24 — Go-live / deployment
- **Objective:** Perform approved production deployment and cutover.
- **Dependencies:** PR23. Legacy migration and reconciliation are mandatory
  before this work begins.

---

## Part E — Migration Strategy (§9)

**General rule applied throughout:** every migration below is additive-first (new columns/objects alongside old ones), with removal of anything old deferred to a later, separate cleanup migration once the new path has been running successfully through at least the Pilot phase. No migration in this plan drops a column or deletes rows.

| Migration step | Pre-migration validation | Backfill rule | Ambiguous-data handling | Constraint timing | Verification query | Rollback | Zero-downtime? |
|---|---|---|---|---|---|---|---|
| **Add `bcm_code`, `item_no` (nullable)** | Confirm the canonical persisted form for each (case rule, prefix rule, leading-zero handling) in `knowledge/architecture/identifiers.md` before any writes. | None — both added empty. **No mechanical backfill from `asset_number` or any assumed format pattern; a single example (`BCM02719`) does not establish the complete valid format set.** | N/A at this step. | Columns added nullable only; `UNIQUE` on each deferred to the steps below. Neither column ever gets a `NOT NULL` constraint — see below. | `SELECT count(*) FROM equipment WHERE bcm_code IS NULL` and the equivalent for `item_no` (expect full count immediately after this step). | Drop columns (no data loss elsewhere). | Yes. |
| **Add `UNIQUE` on `bcm_code` (canonical form)** | `SELECT bcm_code, count(*) FROM equipment WHERE bcm_code IS NOT NULL GROUP BY bcm_code HAVING count(*) > 1` must return zero rows. | N/A | Any duplicate surfaced above is resolved by hospital review before this step proceeds. | Added once the query above returns zero rows. | Same query, expect 0. | Drop constraint. | Yes (`CREATE UNIQUE INDEX CONCURRENTLY` in Postgres avoids a long lock). |
| **Add `UNIQUE` on `item_no` (canonical form)** | `SELECT item_no, count(*) FROM equipment WHERE item_no IS NOT NULL GROUP BY item_no HAVING count(*) > 1` must return zero rows. | N/A | Any duplicate surfaced above is resolved by hospital review before this step proceeds. | Added once the query above returns zero rows. | Same query, expect 0. | Drop constraint. | Yes (`CREATE UNIQUE INDEX CONCURRENTLY` in Postgres avoids a long lock). |
| **Populate `bcm_code` / `item_no`** | N/A — not a schema-migration step. | No reconciliation pass against any spreadsheet and no mechanical backfill from `asset_number`. Values are populated through ordinary equipment-record maintenance (create/edit) and, later, the future inventory import (Roadmap PR12) — see `knowledge/adr/ADR-002-identifier-model.md`. | Records without a value simply remain `NULL` until populated by one of the two paths above; there is no dispatch-blocking or eligibility-scoping tied to their absence, and no DB-level `NOT NULL` is ever added for either column. | N/A | N/A | N/A | N/A |
| **`bcm_code` / `item_no` distinct from `asset_number`** | N/A (all columns coexist by design). | N/A | Document explicitly that `asset_number` remains a separate, retained metadata field (per `knowledge/adr/ADR-002-identifier-model.md`) — not renamed, reused, or merged into either identifier column. | N/A | N/A | Trivial — no destructive change made. | Yes. |
| **Add `transaction_no_seq` (global sequence)** | None required — purely additive, no existing data touched. | N/A — existing `transaction_no` values are untouched and remain valid; the sequence only governs values generated going forward. | N/A | Not a constraint; created once, used by all subsequent transaction-number generation (PR4). | `SELECT last_value FROM transaction_no_seq` sanity-checked after creation; post-deployment, confirm no collision between any historical `transaction_no` and any newly-generated one. | Sequence can be dropped; if ever recreated, must be seeded above the highest historical suffix already in use. | Yes. |
| **Add Asset ID** | None required (new, optional metadata). | Populated only via inventory import (PR12), not mechanically backfilled from existing columns (no reliable source today). | N/A — left `NULL` for pre-existing records until/unless a future import supplies them. | Nullable; uniqueness pending hospital confirmation (see §14) — distinct from Item No, which is unique per `knowledge/adr/ADR-002-identifier-model.md` and already constrained above. | N/A | Drop column. | Yes. |
| **Preserve Serial Number** | Already correctly modeled (Schema Audit, positive finding) — no change needed. | N/A | N/A | Unchanged. | N/A | N/A | N/A |
| **Preserve raw source Asset Status** | N/A | N/A | N/A | New `raw_source_status` column, nullable. **As implemented (PR12, GitHub PR #43, review `4782986913` non-blocking comment 1):** Roadmap PR12 is update-only, so a successful import populates this column on the existing, BCM-Code-matched equipment row it updates — not on a newly-created row (there is no create path). A row that has never been touched by a successful import remains `NULL` (it has no "source" status to preserve). The value stored is the exact source-cell text, verbatim (leading/trailing/internal whitespace, casing) — never the normalized copy used only for the Asset Status mapping lookup. | N/A | Drop column. | Yes. |
| **Map equipment statuses to the 4 confirmed states** | Enumerate every distinct `status` value currently in the table before writing the mapping (do not assume the full enum's 8 values are all actually in use). | Direct mapping for every legacy value, all owner-confirmed (Roadmap PR6): `available → AVAILABLE_AT_POOL`, `borrowed → ISSUED_TO_WARD`, `cleaning → AVAILABLE_AT_POOL`, `out_of_service → UNAVAILABLE_DEFECTIVE`, `lost → UNAVAILABLE_DEFECTIVE`, `pm → UNAVAILABLE_DEFECTIVE`, `calibration → UNAVAILABLE_DEFECTIVE`, `repair → UNAVAILABLE_DEFECTIVE` — **with the original value preserved in `legacy_status` for every remapped row**. | **`cleaning → AVAILABLE_AT_POOL` is the owner-confirmed target, not `UNAVAILABLE_DEFECTIVE` and not a pending-review classification** (this supersedes this row's prior draft language). Cleaning is performed as part of equipment collection/receipt, not a separately tracked state (`AGENTS.md`); a `cleaning` row already represents a device that was collected, cleaned, and checked, i.e. exactly the state `AVAILABLE_AT_POOL` describes. No manual physical-inspection sign-off, no dispatch-blocking classification, and no UI distinction from any other `AVAILABLE_AT_POOL` row is required — `legacy_status='cleaning'` is ordinary historical/rollback metadata only. | Add `legacy_status` column first (nullable); populate it as part of the same migration that remaps `status`; do not enforce a `CHECK` on the new 4-value domain until the remap is verified complete. | `SELECT status, count(*) FROM equipment GROUP BY status` before and after, cross-checked against the documented mapping table for every distinct pre-migration value. | `legacy_status` allows full reconstruction of pre-migration state; the remap itself can be reversed by copying `legacy_status` back to `status`. | Requires a maintenance window or careful batching if the equipment table is large enough that a single-transaction `UPDATE` would lock for a noticeable period — **at the confirmed MVP scale (low hundreds of devices), this is expected to be sub-second and safe without a window**, but should be verified against actual row counts before the pilot's migration is run. |
| **Map transaction `borrowed → OPEN`, `returned → CLOSED`** | Enumerate distinct existing `status` values. | Direct mapping for `borrowed`/`returned`. | N/A (no ambiguity for these two values). | Same additive-then-constrain approach as above. | Row-count cross-check pre/post. | Reversible via a documented reverse-mapping. | Yes, expected low risk at confirmed data volume. |
| **Handle existing `overdue` rows** | Enumerate all rows currently `status = 'overdue'`. | **Not a direct rename.** Each `overdue` row must be evaluated against its actual `returned_at`: if `returned_at IS NOT NULL`, it was in fact returned at some point and should become `CLOSED`; if `returned_at IS NULL`, it is still genuinely open and should become `OPEN` (with its `due_at`/overdue history simply discontinued going forward, not acted upon further). | None of this is inferable purely from `status` alone — this step explicitly requires the join against `returned_at` described above, not a lookup table. | Add the mapping logic as an explicit migration step with its own verification query (below), run **before** the general `borrowed`/`returned` rename so `overdue` rows aren't accidentally left unmapped by a rename that only expects two source values. | `SELECT count(*) FROM borrow_transactions WHERE status = 'overdue' AND returned_at IS NOT NULL` (should become `CLOSED`) vs. `... AND returned_at IS NULL` (should become `OPEN`) — both counts should sum to the total `overdue` row count with no remainder. | Reversible via the same `legacy_status`-style preservation approach. | Yes, expected low risk at confirmed transaction volume. |
| **Handle existing `borrower_name` data** | None required — field simply becomes optional going forward. | No backfill needed; existing values are preserved as-is (read-only history), not migrated or cleared. | N/A | Relax `NOT NULL` constraint on `borrower_name` (or leave as-is if already nullable at the DB level with only application-layer enforcement — confirm actual current constraint before writing the migration). | N/A | Trivial (loosening a constraint is safely reversible). | Yes. |
| **Make `ward_id` required (new rows)** | **Enumerate existing rows with `ward_id IS NULL` before adding any constraint.** | **Do not backfill a null `ward_id` with any arbitrary/default ward.** Per the confirmed requirement's own explicit instruction, this must not happen. | Existing null-`ward_id` rows are left as historical exceptions, explicitly flagged in a migration report for hospital review, and the `NOT NULL` constraint is scoped to apply **only to new rows going forward** (e.g., via application-layer enforcement plus a `CHECK` that only fires for rows created after a cutover timestamp, or simply application-layer enforcement without a DB-level `NOT NULL` if legacy nulls must remain queryable without special-casing). | Application-layer enforcement lands with PR7; a DB-level constraint (if pursued) is deferred to PR14 once the legacy-null population is confirmed fully reviewed. | `SELECT count(*) FROM borrow_transactions WHERE ward_id IS NULL` (report this count to the hospital before finalizing the approach). | N/A (no destructive action taken). | Yes. |
| **Add `dispatch_type`, `routine_round`** | None required (new, additive). | Existing historical dispatches have no reliable source for this distinction — left `NULL`/an explicit `LEGACY_UNKNOWN` sentinel value, not guessed. | Document that historical data predating this migration cannot be retroactively classified as routine vs. on-demand. | Nullable for existing rows; required (application-layer) for new rows going forward. | N/A | Drop columns. | Yes. |
| **Preserve existing transaction/audit history** | N/A — no existing history is deleted or altered beyond the status remaps described above, which are themselves fully reversible via `legacy_status`. | N/A | N/A | N/A | Row-count parity check before/after every migration in this plan (total rows in, total rows out, for every table touched). | N/A | N/A |

---

## Part F — Inventory Import Plan (§10)

> **Scope note:** Import is Roadmap PR12, not yet scoped as an active
> Governance PR. This section's row-validation identifiers below use the
> accepted BCM Code / Item No model (`knowledge/adr/ADR-002-identifier-model.md`)
> so that the plan is internally consistent; the import workflow's stage
> sequencing and file-handling behavior are otherwise unchanged and remain
> subject to full scoping when PR12 is taken up.

### F.1 Workflow stages

1. **File upload & validation** — accept the hospital's existing spreadsheet structure; validate file type/encoding before any parsing.
2. **Header validation** — confirm the expected source columns (Item No., ID CODE, Asset ID, Equipment Name, Manufacturer, Model, Serial Number, Location, Receive Date, Register Date, Purchase Year, Asset Status) are present; reject the file outright (with a clear message) if required headers are missing, rather than attempting a partial/guessed mapping.
3. **Row parsing & validation** (per row, not fail-fast for the whole file):
   - BCM Code (from `ID CODE`): required; text-typed (never numeric-parsed, preserving leading zeros); missing → row flagged as failed.
   - Duplicate BCM Code **within the uploaded file itself**: flagged as failed for all but the first occurrence (or all occurrences, product decision — recommend flagging all duplicates within a file as failed, forcing the source file to be corrected, since silently picking "the first one" risks picking the wrong record).
   - Duplicate BCM Code **already present in the database**: not a failure by default — routed to "update existing" handling (see F.3) only when the operator has explicitly selected update mode; otherwise flagged as a skip with a clear reason.
   - BCM Code **with no match in the database at all**: **as implemented (see PR12's implementation note in Part D above), always a per-row failure — Inventory Import does not create new equipment.** The failure reason directs the operator to create the equipment through the standard Equipment Master workflow first, then re-import this file to update it. Deferred follow-up scope, not a permanent prohibition on future bulk creation.
   - Item No. (from the `Item No.` source column): text-typed, case and leading zeros preserved exactly as sourced (per `knowledge/architecture/identifiers.md`); validated for file-internal and database duplicates the same way as BCM Code above.
   - Asset ID / Serial Number duplicate checks: validated against existing database values where those fields are expected to be unique (Serial Number, confirmed unique already; Asset ID uniqueness pending hospital confirmation, §14) — flagged, not silently overwritten.
   - Asset Status: raw value preserved verbatim into `raw_source_status`; mapped into the target 4-state model only through the explicit, approved mapping table (illustrative version below, **pending confirmation of real source values**, §14); an unrecognized status value is a per-row failure, not a guess.
4. **Preview** — the full parsed, validated result set (successes and failures, with reasons) is shown to the Administrator **before any database write occurs**. Nothing commits at parse time.
5. **Commit** — only rows marked as valid in the preview are written, in a single import batch; failed rows are never partially written.
6. **Per-row result report** — a downloadable/viewable summary: N succeeded, M failed (with per-row reason), K skipped (existing BCM Code or Item No, no update-mode selected).
7. **Audit record** — one `audit_logs` entry for the import batch itself (who ran it, when, filename, row counts), consistent with the confirmed requirement that imports must be audited.

### F.2 Illustrative Asset Status mapping (pending confirmation — §14)

| Source value (assumed) | Target |
|---|---|
| Active / In Use / In Service | `AVAILABLE_AT_POOL` |
| Defective / Faulty / Under Repair | `UNAVAILABLE_DEFECTIVE` |
| Decommissioned / Disposed / Written Off | `DECOMMISSIONED` |
| *(anything unrecognized)* | Row fails validation; not guessed. |

### F.3 "Update existing" mode

Off by default. When explicitly enabled by the Administrator for a given import run: a row whose BCM Code or Item No matches an existing record updates that record's metadata fields (Asset ID, Manufacturer, Model, dates) but **never** silently changes `status`/`legacy_status` through the import path — status changes always go through the normal dispatch/receipt/defective/decommission actions, keeping the import path scoped to master-data fields only. This avoids the import feature becoming a backdoor around the state-machine's transition rules.

> **Implementation note (PR12, GitHub PR #43):** as implemented, Inventory Import is update-only in every run — there is no off/on toggle, because there is no create path for an "off" mode to select instead (see Part D's PR12 implementation note above). The `update_existing` request field is retained for API compatibility, but the backend rejects an explicit `false` with a clear error rather than silently accepting a request that could never do anything (no create path, and no in-DB match to skip either, if the intent was ever "create-or-skip"). The frontend never offers a control to request anything else. The master-data field set and never-touches-`status`/`legacy_status` guarantee described above are otherwise unchanged and still apply to every successful row.

### F.4 Partial success behavior

An import batch is never all-or-nothing. Valid rows commit; invalid/duplicate rows are reported and excluded; the operator can correct the source file and re-import only the corrected rows. **As implemented (PR12, GitHub PR #43):** a row whose BCM Code has no match in the database is always a per-row failure (see F.1 step 3), not a skip — re-import after creating the missing equipment through the standard Equipment Master workflow will then match and update it.

---

## Part G — Testing Plan (§11)

### G.1 Dispatch concurrency

| Scenario | Expected result |
|---|---|
| Two simultaneous dispatch requests for the same equipment | Exactly one succeeds; the other receives a clear "not available" rejection (existing `idx_tx_one_active_borrow`-equivalent guard, keyed on the internal equipment identity, carried forward under the renamed model per PR6/PR7). |
| Many simultaneous dispatches during one simulated routine round (e.g. 50–200 concurrent requests, distinct equipment) | All succeed; no two share a transaction number (PR4). |
| Transaction-number uniqueness under concurrent load | Explicit assertion, not just an absence-of-error check. |
| Retry after client timeout | A retried dispatch for equipment that already succeeded is naturally rejected by the same-equipment guard (no duplicate created); documented as relying on this existing mechanism rather than a dedicated idempotency key for MVP (Idempotency-Key remains P2/deferred per the workflow audit's finding). |
| Duplicate scan submission (e.g., double-tap) | Same as above — naturally rejected by the state check, verified explicitly as a test, not assumed. |

### G.2 Receipt concurrency

| Scenario | Expected result |
|---|---|
| Two simultaneous receipt requests for the same OPEN dispatch | Exactly one succeeds. |
| The second receipt request | Rejected with a clear, non-misleading error (explicitly **not** the current code's misleading "already returned" message when the real cause is a race — verified as its own test case). |
| Second request cannot overwrite outcome/`returned_at`/`returned_by_user_id`/equipment status/status history/audit log of the first | Each of these six is asserted independently after a simulated race, not just "the transaction ended up closed." |
| Receipt when no OPEN dispatch exists for the given equipment | Clear rejection, no side effects. |
| Receipt of the wrong transaction | Not reachable given the one-open-dispatch-per-equipment invariant, but tested defensively (attempt to close a transaction ID that is not the equipment's current open one). |
| Receipt outcome `usable` | Equipment → `AVAILABLE_AT_POOL`. |
| Receipt outcome `defective` | Equipment → `UNAVAILABLE_DEFECTIVE`. |
| Receipt of equipment that is (somehow) `DECOMMISSIONED` | Must not reactivate it — defense-in-depth test, since this equipment should never have reached `ISSUED_TO_WARD` in the first place; test both the dispatch-time block and, redundantly, that the receipt path itself has no code path that could reactivate a decommissioned item. |

### G.3 Permissions

- Equipment Pool Staff can dispatch and receive.
- Read-Only/Supervisor cannot dispatch, receive, or perform any write action, but can view/export.
- The retired ward-side roles (`ward_nurse`, `transport_staff`) cannot perform any transaction under the new model (explicit negative test, ensuring the role-consolidation migration didn't leave a back door).
- Only Administrator can manage users.
- Ward correction requires Administrator or Equipment Pool Staff **and** always produces exactly one audit entry — tested together, not separately, since the requirement is conjunctive.

### G.4 Import

- Missing BCM Code → row fails.
- Duplicate BCM Code within one file → flagged, not silently deduplicated.
- BCM Code already in database, update mode on → metadata updated, status untouched.
- **As implemented (PR12, GitHub PR #43):** BCM Code with no match in the database at all → row fails, no equipment created, regardless of `update_existing` — Inventory Import does not create new equipment (deferred follow-up scope, not a permanent prohibition; see Part D's PR12 implementation note).
- **As implemented:** an explicit `update_existing=false` request is rejected outright (400) with a clear message before any row is parsed, rather than silently accepted into a batch where nothing could ever succeed (there is no create path for it to select, and no per-row "skip" outcome is reachable either).
- **As implemented:** `raw_source_status` preserves the exact source-cell text (leading/trailing/internal whitespace, casing) — a separately normalized copy is used only for the Asset Status mapping lookup, never persisted.
- Leading-zero preservation round-trip.
- Invalid/unrecognized source status → row fails, not guessed.
- Duplicate Serial Number → flagged.
- Partial row failure within an otherwise-valid file → valid rows still commit.
- Preview does not write to the database under any circumstance.
- Import produces exactly one audit log entry per batch, correctly attributed.

### G.5 General

- Unit tests for every service-layer state-transition function (dispatch, receipt, defect-marking, ward correction) covering every valid and invalid transition from Workflow Audit §4.4's table.
- API integration tests for every endpoint's success and error-response shape (post-PR2, verifying the consistent `{detail, code, status}` envelope).
- Database constraint tests for every new/changed constraint from Part E.
- Migration tests: each migration step in Part E gets a rehearsal against a representative dataset (including at least one row in every legacy state requiring special handling — `cleaning` (owner-confirmed direct mapping to `AVAILABLE_AT_POOL`, Roadmap PR6), `overdue` with and without `returned_at`, null `ward_id`) with its stated verification query re-run post-migration.
- Frontend workflow tests: full dispatch→receipt cycle using only new terminology (PR11); import UI happy-path and validation-failure paths (PR12).

---

## Part H — Acceptance Criteria (§12)

*(Given/When/Then, one set per confirmed workflow area — kept to the essential MVP-defining criteria; the full exhaustive list lives in the corresponding PRs' own acceptance-criteria fields in Part D.)*

**BCM Code (manual search — `knowledge/adr/ADR-003-bcm-manual-search.md`)**
- Given equipment with a registered BCM Code, when an operator types it (in full or in part, with or without the "BCM" prefix), then the system returns a bounded suggestion list with an exact match ranked first.
- Given no BCM Code matches the input, then the suggestion list is empty, not an error and not the full equipment set.
- Given a BCM Code with leading zeros, when stored and later retrieved, then the leading zeros are unchanged.
- Given an attempt to register a duplicate BCM Code (on its canonical form — `knowledge/architecture/identifiers.md`), when submitted, then it is rejected with a 409, not a 500.

**Item No (QR resolution — `knowledge/adr/ADR-004-hospital-item-no-qr.md`)**
- Given equipment with a registered Item No, when its hospital QR label is scanned, then the system resolves the equipment via exact match.
- Given an unrecognized Item No, when scanned, then a clear "not found" response is returned and no transaction is created.
- Given a malformed scan, then a clearly distinct "malformed" response is returned — never conflated with "not found."
- Given an Item No, when stored and later retrieved, then its case and leading zeros are preserved exactly as scanned.
- Given an attempt to register a duplicate Item No (on its canonical form), when submitted, then it is rejected with a 409, not a 500.

**Routine Dispatch**
- Given a dispatch is being recorded with `dispatch_type = ROUTINE_ROUND`, when a round value is selected, then only 06:00/11:00/15:00/21:00 are valid.
- Given `dispatch_type = ROUTINE_ROUND`, when no round is selected, then the request is rejected.
- Given a dispatch request, when no `ward_id` is supplied, then the request is rejected.
- Given a dispatch request, when no `borrower_name` is supplied, then the request succeeds (this field is no longer required or accepted).
- Given equipment not in `AVAILABLE_AT_POOL`, when a dispatch is attempted, then it is rejected regardless of dispatch type.

**On-Demand Dispatch**
- Given `dispatch_type = ON_DEMAND`, when submitted without a round value, then the request succeeds.
- Given an on-demand dispatch, when a `notes` field is supplied, then no patient-identifying content is required or implied by the UI, and the field accepts free text without format constraints tying it to a patient.
- Given a completed on-demand dispatch, when viewed in history, then it is distinguishable from routine dispatches.

**Receipt**
- Given equipment in `ISSUED_TO_WARD`, when a receipt is recorded with outcome `usable`, then the dispatch becomes `CLOSED` and the equipment becomes `AVAILABLE_AT_POOL`, atomically with the status-history and audit-log writes.
- Given equipment in `ISSUED_TO_WARD`, when a receipt is recorded with outcome `defective`, then the dispatch becomes `CLOSED` and the equipment becomes `UNAVAILABLE_DEFECTIVE`, atomically.
- Given a dispatch already `CLOSED`, when a second receipt is attempted, then it is rejected with a clear, accurate error.
- Given two concurrent receipt attempts on the same `OPEN` dispatch, then exactly one succeeds.
- Given a receipt is being recorded, when the operation completes, then `returned_at` reflects server time (not client-supplied) and `returned_by_user_id` reflects the authenticated actor.

**Ward Recording**
- Given equipment is dispatched to Ward A, when later real-world movement occurs (outside the Pool's knowledge), then the system continues to show Ward A, unchanged.
- Given a UI view of a dispatch record, when the receiving ward is displayed, then it is labeled in a way that does not imply real-time physical location.
- Given a ward-correction request, when submitted by an authorized role with a reason, then the ward updates and exactly one audit entry is created; when submitted by an unauthorized role, then it is rejected.

**Audit**
- Given any of: dispatch, receipt, defective marking, ward correction, equipment master-data edit, user creation, role change, activation/deactivation, password reset, or inventory import — when the action occurs, then a corresponding audit entry is created capturing who, what, and when, with no exceptions.

---

## Part I — Final Go-Live Gates (§13)

### Development Readiness
- Confirmed domain model in place (4 equipment states, 2 transaction states, BCM Code as primary operator-facing identifier — `knowledge/adr/ADR-002-identifier-model.md`) — PR5–PR8 merged.
- Migration design for every schema change reviewed and approved (Part E), including the owner-confirmed `cleaning → AVAILABLE_AT_POOL` mapping (Roadmap PR6 — no manual-review rule applies) and the `ward_id`-null handling policy.
- PR sequence (Part D) agreed by the engineering team.
- Test strategy (Part G) agreed.
- No unresolved Critical business assumption remains open (cross-check against §14 below before declaring this gate passed).

### UAT Readiness
- BCM Code / Item No import available and exercised against a real (or realistic) sample of the hospital's inventory file.
- Routine dispatch and on-demand dispatch both operational end-to-end.
- Receipt (usable/defective) operational end-to-end.
- Duplicate/concurrent protection verified for both dispatch and receipt (Part G.1/G.2 passing).
- Role permissions match the confirmed matrix exactly (Part G.3 passing).
- Audit coverage verified for every event listed in Part H's "Audit" acceptance criteria.
- Search and history operational, BCM-Code-first (`knowledge/adr/ADR-003-bcm-manual-search.md`).
- Frontend terminology reviewed and approved by hospital stakeholders (no "Borrow"/"Borrower"/"Due Date" language remaining).
- Test data imported successfully via PR12's import workflow.

### Pilot Readiness
All P0 findings from Part C resolved, specifically:
- JWT secret production guard verified (app refuses to boot insecurely).
- Dashboard connection leak resolved (PR1) — verified under a sustained-open-dashboard-tab test, or the feature is temporarily disabled if the fix is not yet merged.
- Concurrent dispatch and receipt tests (Part G.1/G.2) passing, including the simulated routine-round burst scenario at realistic pilot volume.
- Transaction-number race resolved and load-tested.
- Error handling verified — no unhandled 500s for duplicate-key or malformed-input scenarios.
- User and role audit logging verified.
- Backup procedure documented (database backup/restore, not addressed by these audits directly — flagged as an operational prerequisite, see §14).
- Pilot users trained on the new terminology/workflow.
- Rollback plan documented for each migration in Part E.
- No patient-identifiable fields present anywhere in the workflow (verified by explicit review of every form field and every notes/free-text field's UI guidance).

### Production Readiness
- Version 1 legacy migration completed for Equipment Master and the AppSheet
  equipment receive-data and equipment issue-data sheets.
- Legacy import reconciliation signed off; old and new transaction history is
  presented as one unified history.
- BCM and Item Number matching, existing hospital QR-code preservation,
  BME-name preservation/later mapping, Ward normalization, duplicate
  detection, source traceability, and import validation verified.
- Backup and restore verified (not just documented — actually rehearsed).
- Secure environment configuration confirmed (production secrets, not defaults, across JWT and any other credentials).
- Full audit coverage confirmed in production configuration.
- Monitoring/structured logging in place (PR15).
- Error handling verified in production-representative conditions.
- Concurrency protections verified under production-representative load.
- User permissions matrix verified against the real production user roster.
- All migrations from Part E verified against the actual production data (not just a test dataset) — with particular attention to the `overdue`-row manual-review item, which must be fully resolved by real hospital staff before production cutover, not deferred. (The `cleaning`-status mapping requires no manual review — see Roadmap PR6's owner-confirmed `cleaning → AVAILABLE_AT_POOL` decision.)
- Inventory reconciliation complete (imported data matches the hospital's authoritative inventory count).
- UAT sign-off obtained.
- Pilot sign-off obtained.
- Support and recovery process documented (who to contact, how to roll back, how to restore from backup).

---

## 14. Open Questions and Unresolved Items

These require hospital/product confirmation before or during implementation; none of them block starting the P0 work in Part D, but several block specific later PRs as noted.

1. **Realistic data-volume estimate.** This plan assumes "low hundreds of equipment records, low-thousands of transactions per year" based on the confirmed scope description ("selected devices, primarily infusion pumps"). This assumption directly drove the downgrade of the `COUNT(*)` and JWT-claim findings to P2/P3 (Part B.2). If the actual fleet size is materially larger, those two items should be re-elevated — recommend confirming an approximate device count before Pilot Readiness.
2. **Asset ID uniqueness.** Confirmed requirements state Asset ID is a separate identifier but do not state whether it is unique hospital-wide. Affects PR5's constraint design and PR12's duplicate-detection rules.
3. **Source `Location` field meaning.** Still unconfirmed (carried from Workflow Audit A3) — must not be conflated with `ward_id`.
4. **Actual distinct source `Asset Status` values.** The mapping in Part F.2 is illustrative only; the real value set must be obtained from an inventory export before PR12's mapping table is finalized.
5. **Resolved, no longer open (Roadmap PR10).** This item asked for a named decision-owner for existing-user-to-new-role mapping (which real staff become Administrator vs. Equipment Pool Staff vs. Read-Only) before PR10 merges. Resolved by inspection: this repository's own database state (seed script and every test fixture) was confirmed to hold zero users on any ambiguous legacy role at merge time, so the manual-mapping decision never had a real account to apply to. `backend/alembic/versions/0009_role_consolidation.py`'s fail-closed `MEP_PR10_ROLE_MAPPING` manifest mechanism still exists and still requires an explicit, reviewed mapping for a real deployment where such accounts exist (see `docs/DECISION_LOG.md`, "Roadmap PR10" — "Stop-condition research").
6. **Resolved, no longer open (Roadmap PR6).** The prior version of this item asked for a manual-review/sign-off process for `cleaning`-status equipment ahead of a proposed temporary `UNAVAILABLE_DEFECTIVE` migration classification. That approach is superseded: the repository owner has confirmed `cleaning → AVAILABLE_AT_POOL` as the direct migration target (cleaning is performed as part of equipment collection/receipt, not a separately tracked state — see `AGENTS.md` and Part E's mapping-table row above). No manual review, sign-off, or physical-inspection process is required for this mapping.
7. **Backup/restore procedure.** Referenced as a Pilot/Production gate requirement but not designed by any of the three audits or this plan — needs a separate, dedicated infrastructure task.
8. **Whether internal route paths (`/borrow`, `/return`) should eventually be renamed to `/dispatch`, `/receive`** for full consistency, or intentionally left as internal implementation detail permanently. PR7/PR11 recommend leaving them unchanged for MVP to reduce blast radius — revisit as a deliberate, separate decision post-pilot if full consistency is later desired.
9. **Resolved, no longer open (PR5).** The prior version of this item asked for an "eligible for Equipment Pool operation" definition to scope a `NOT NULL` constraint under the reconciliation-based ME Code strategy. That strategy is superseded (see PR5's active entry in Part D and Appendix Z) — BCM Code and Item No are nullable until populated, with no eligibility-scoped `NOT NULL` constraint and no application-layer dispatch-block tied to their presence. Nothing remains open here.
10. **Resolved, no longer open (PR5).** The prior version of this item asked for a best-available reconciliation key to backfill `me_code` against the hospital's spreadsheet. That reconciliation approach is superseded (see PR5's active entry in Part D and Appendix Z) — there is no backfill/reconciliation step; identifiers are populated through ordinary equipment-record maintenance and the future inventory import (Roadmap PR12).
11. **Daily-reset requirement for transaction numbers (PR4).** This plan explicitly does not assume one was confirmed and proceeds with a globally monotonic sequence instead. If the hospital later confirms an actual operational need for the numeric suffix to restart daily, the fallback per-date-counter design noted in PR4 should be implemented instead — this is not currently planned.

**Note — distinct from the open questions above:** reporting shift metadata is
now scheduled in PR16–PR18 and legacy migration/cutover in PR19–PR24. Standby
Snapshots and any richer Shift Session workflow remain separate future work.
See `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, and
`docs/ARCHITECTURE_DECISIONS.md`.

---

## Compliance with Stated Constraints

No application code was written or modified. No migration files were created. No application configuration was modified. No feature was implemented. No MEMS, patient tracking, HN/MRN, bed tracking, ward-to-ward movement tracking, cleaning workflow, `PENDING_CLEANING`, "Cleaning Confirmed," "Ready for Dispatch," PM, calibration, recall, or full maintenance workflow was introduced anywhere in this plan. All findings and recommendations are traced to the three source audits or to the confirmed hospital requirements provided as input to this task; no requirement was invented beyond those two sources.

---

## Appendix Z — Historical: Superseded PR5 Requirements (ME Code)

**This appendix is historical only. Nothing below is an active
requirement.** It is retained for context on how PR5's scope changed, not
as a specification to implement. The active PR5 contract is Part D's PR5
entry, governed by `knowledge/adr/ADR-002-identifier-model.md`,
`ADR-003-bcm-manual-search.md`, and `ADR-004-hospital-item-no-qr.md`.

An earlier draft of this plan specified PR5 around a distinct "ME Code"
identifier, reconciled against the hospital's authoritative inventory
spreadsheet, with a dispatch-eligibility rule gated on a non-null ME
Code. That design is superseded — not merely annotated — by the
Governance PR that resolved `knowledge/adr/ADR-002` through `ADR-004`.
None of the following are active:

- A separate `me_code` field distinct from BCM Code and Item No.
- Exact-match lookup keyed on ME Code.
- Reconciliation of existing records against an authoritative spreadsheet
  to determine each record's ME Code.
- An "eligible for Equipment Pool operation" scoped `NOT NULL` constraint
  on ME Code, or an application-layer dispatch-block keyed on a null ME
  Code.
- Any test, acceptance criterion, or API/frontend behavior described
  under the original PR5 draft that assumed the above.

The superseding design (BCM Code as the operator-facing identifier,
Item No as the QR-only identifier, both nullable-until-populated with no
eligibility-gated constraint or dispatch-block) is documented once, in
the Knowledge Layer ADRs referenced above — it is not restated here.
