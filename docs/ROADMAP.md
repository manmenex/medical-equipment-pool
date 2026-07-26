# Roadmap

**Purpose:** Current-state snapshot of the Medical Equipment Pool Roadmap — what is merged, what is next, at the current baseline
**Authority:** Summary. `docs/audits/04-consolidated-implementation-plan.md` Part D remains authoritative for Roadmap PR scope, order, dependencies, and acceptance criteria. `docs/ROADMAP_STATUS.md` is superseded by this file (see the banner on that file).
**Update trigger:** A Roadmap PR merges, is added, is reordered, or the baseline changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`93b6f948a7f6eb60f084fa61966191b5ba13c098` — squash commit of GitHub PR #40 ("Dashboard & Equipment Status," an unnumbered Post-PR11 Frontend Dashboard UX Follow-up — **not** Roadmap PR12; see the Completed table below), on branch `claude/medical-equipment-pool-0c7fz0`. This sits on top of `9de050c04174f0d1be1e82f363db3224e5bfa371` (Governance PR #41, the documentation-only decision that classified GitHub PR #40 as unnumbered), which sits on top of `7708190ebf08b7212b7a73ba831263b94434d1eb` (squash commit of Roadmap PR11, Frontend Terminology and Workflow UI Pass, GitHub PR #38), which sits on top of `66bdd547937b7741d53b16a98fe74280dee18273` (documentation-only post-merge governance sync recording Roadmap PR10's completion, GitHub PR #37), which sits on top of `53340f6d7d5c8cda685235411b60a57d2d033a7e` (Roadmap PR10, Role Model Consolidation, GitHub PR #36), which sits on top of `bfe8a42a55d738d3e591ce27145c7918186643ac` (Roadmap PR9B, frontend audited ward correction for OPEN/CLOSED transaction records, GitHub PR #34), which sits on top of `9cef8411f067b14dd417d3dcd1335567cb669868` (Roadmap PR9A, backend audited ward correction, GitHub PR #33). **Roadmap PR8 (all three slices), Roadmap PR9 (both slices — PR9A, PR9B), Roadmap PR10, and Roadmap PR11 are now fully complete. Roadmap PR12 (Inventory Import) has not started — GitHub PR #40 above is unnumbered, non-Roadmap work and does not advance it.**

## Numbering note

**Roadmap PR number** (this file, `docs/audits/04-consolidated-implementation-plan.md`) and **GitHub PR number** (this repository's PR counter) are different sequences — see `docs/DECISION_LOG.md`'s "Numbering note" for the full explanation and a worked example. This file uses Roadmap PR numbers except where a row is explicitly infrastructure/governance work that was never assigned one.

## Completed

| Roadmap PR | Title | GitHub PR | Squash SHA |
|---|---|---|---|
| PR1 | Production Security and Availability Foundation | #2 | `25b460d` |
| PR2 | Structured Exception Handling | #5 | `14b4174` |
| PR3 | Audit Logging Framework | (merged via feature/pr3-audit-logging) | `0f2ef51` |
| PR4 | Transaction-Number Generation (global PostgreSQL sequence) | #13 | `7bcaa4a` |
| — (governance) | Knowledge Layer v2 — identifier/QR architecture and authority hierarchy | #15 | `89b1f1e` |
| PR5 | Equipment Master identifier model, BCM manual search, hospital Item-No QR identification | #14 | `099f0b8` |
| PR6 | Equipment State Model Migration (4 states) | #16 | `9994c27` |
| — (infrastructure) | GitHub Actions CI and AI review workflow | #17 | `3a1d30b` |
| — (governance) | Knowledge & Governance Foundation | #18 | `f4146b3` |
| PR7 (7a slice) | Transaction lifecycle model (OPEN/CLOSED) | #19 | `4041cd2` |
| PR7 (7b slice) | Transaction fields: dispatch type, routine round, required ward_id, borrower_name/due_at/quantity write-path removal | #20 | `d0e888f` |
| — (governance) | Post-merge governance sync after Roadmap PR7b (GitHub PR #20) | #21 | `0ed6598` |
| — (infrastructure) | Test Infrastructure Cleanup — consolidated duplicated test helpers into `tests/conftest.py`, no behavior change | #22 | `06a736c` |
| — (documentation) | Developer Documentation (`docs/development/`: SETUP, TESTING, MIGRATIONS, CODE_REVIEW, CONTRIBUTING) | #23 | `2e403fb` |
| — (documentation) | API & Error Catalog (`docs/api/`: ERROR_CODES, dispatch, receipt, equipment, transactions) | #24 | `f6f7c2a` |
| — (governance) | Post-merge governance sync after PR21-PR24 | #25 | `a308515` |
| PR8 (PR8A slice) | Atomic receipt concurrency guard — PostgreSQL conditional `UPDATE` + affected-rowcount winner guard | #26 | `4820dba` |
| PR8 (PR8B slice, backend) | Receipt outcome contract narrowing — `receipt_outcome` (`usable`/`defective`) replaces `condition` | #28 | `da4d76a` |
| PR8 (PR8B slice, frontend) | Frontend adoption of `receipt_outcome`; deployed together with the backend slice above | #29 | `d3e027b` |
| — (documentation) | Post-merge documentation sync after Roadmap PR8B (TD-006 closed, ADR-006/DECISION_LOG/ROADMAP updated) | #30 | `4af6a4c` |
| PR8 (PR8C slice) | Race-loss-vs-genuine-repeat receipt rejection — distinguishable `TRANSACTION_ALREADY_RETURNED`/`RECEIPT_RACE_LOST` codes, both HTTP 409 | #31 | `f923f0a` |
| — (documentation) | Documentation-only follow-up recording Roadmap PR8's completion (PR8A/PR8B/PR8C) | #32 | `94a14b8` |
| PR9 (PR9A slice) | Audited ward correction (backend) — `POST /transactions/{id}/correct-ward`, temporarily Administrator-only | #33 | `9cef841` |
| PR9 (PR9B slice) | Frontend audited ward correction for OPEN/CLOSED transaction records | #34 | `bfe8a42` |
| — (governance) | Post-merge governance sync after Roadmap PR9 | #35 | `bc1b163` |
| PR10 | Role Model Consolidation — legacy 5-role model replaced by the confirmed 3-role model (`administrator`, `equipment_pool_staff`, `read_only`) | #36 | `53340f6` |
| — (governance) | Post-merge governance sync after Roadmap PR10 | #37 | `66bdd54` |
| PR11 | Frontend Terminology and Workflow UI Pass — retired "ยืม"/"คืน" (borrow/return) UI terminology, converged on "เบิก"/"รับคืน" (issue/receive back) | #38 | `7708190` |
| — (governance) | Post-merge governance sync after Roadmap PR11 | #39 | `2944210` |
| — (governance) | Governance — classified GitHub PR #40 as an unnumbered Post-PR11 Frontend Dashboard UX Follow-up (not Roadmap PR12) | #41 | `9de050c` |
| — (frontend) | Dashboard & Equipment Status — operational lifecycle-status counts, permission-gated quick actions, loading/empty/error states, `/scan` quick-lookup destination; unnumbered, not Roadmap PR12 | #40 | `93b6f94` |

Full rationale and review-fix history for PR5 through PR11: `docs/DECISION_LOG.md`. PR21, PR22-PR25, PR30/PR32, PR35, and PR37 (GitHub PR numbers) are process/documentation-only additions with no code, business-rule, or schema change — no `DECISION_LOG.md` entry was needed for them. PR8A/PR8B/PR8C/PR9A/PR9B/PR10/PR11 (GitHub PR #26, #28, #29, #31, #33, #34, #36, #38) are different: they are production code changes; PR10, PR11, and both PR9 entries now have a `docs/DECISION_LOG.md` entry (see the PR9, PR10, and PR11 notes below).

**PR7 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR7 entry recommended splitting into a 7a (lifecycle model) and 7b (`dispatch_type`/`routine_round`/ward-required/field-cleanup) slice "if the reviewing team prefers smaller units." PR7 (7a slice) shipped `TransactionStatus` (`OPEN`/`CLOSED`), the `create()`/`close()` mutator split, `legacy_status` preservation, and disabling the deprecated `due_at`-driven overdue-notification scheduler job (Codex PR7a review round 1, BLOCKER — see `docs/DECISION_LOG.md`). PR7 (7b slice) completed PR7's remaining scope: `dispatch_type` (`routine_round`/`on_demand`), `routine_round` (the four confirmed fixed times), a required `ward_id` for every new dispatch (application-layer enforced), and removing `borrower_name`/`due_at`/`quantity` from the active write path while preserving every existing historical value as read-only history — plus, after Codex round 1 review, `BorrowRequest` now rejects unknown request fields outright, an invalid `ward_id` is classified as a distinct 400 `INVALID_INPUT` rather than the equipment-conflict 409, and the migration 0008 test suite was rewritten to exercise a genuinely reconstructed pre-migration production schema. Roadmap PR7 (both slices) is now fully merged. Concurrent-receipt protection (two simultaneous receipts racing on the same OPEN transaction) was **not** part of either slice — that gap is closed by Roadmap PR8A below.

**PR8 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR8 entry ("Atomic Single-Operation Equipment Receipt with concurrency guard") was split into **three** slices during implementation planning (`docs/design/PR8_IMPLEMENTATION_PLAN.md`, design-only, uncommitted; the original PR7a/PR7b-style two-slice split was refined to three once PR8B's own scope proved to have two independent, separately-shippable halves — see the Codex review recorded in `docs/DECISION_LOG.md` "Roadmap PR8 (PR8B slice)"). **PR8A** (GitHub PR #26) is the database-level concurrency guard: `app.crud.transaction.close()` performs a single conditional `UPDATE ... WHERE id = :id AND status = 'open'`, deciding the winner by affected-row count, so exactly one concurrent receipt request succeeds and every loser rolls back before any business side effect — proven with deterministic PostgreSQL tests across a matrix of 1, 2, 5, 10, and 50 requests: the 1-request case verifies normal receipt behavior with no concurrency, the 2/5/10 cases synchronize the complete burst to force genuine contention, and the 50-request case synchronizes a bounded subset to prove conditional-`UPDATE` contention without exhausting the connection pool. No API contract, schema, or frontend change. **PR8B** (GitHub PR #28 backend + #29 frontend, deployed together) narrows the `condition` field to the confirmed binary `receipt_outcome` (`usable`/`defective`) contract, backend and frontend. `docs/TECH_DEBT.md` TD-006, which tracked the frontend/backend gap between the two PR8B slices, is `Closed`. **PR8C** (GitHub PR #31) distinguishes the two causes of a losing receipt request by machine-readable code — `TRANSACTION_ALREADY_RETURNED` (the transaction was already closed when the request evaluated current state) versus `RECEIPT_RACE_LOST` (the request observed an open transaction but lost the conditional-update race) — both still `409 Conflict`; `RECEIPT_RACE_LOST`'s wording deliberately attributes the outcome to another *request*, not another person, since the backend has no basis to identify who sent the winning request. The frontend branches on the response's `code` field, never on free-text `detail`. No lifecycle, schema, migration, or request-contract change; `receipt_outcome: "usable" | "defective"` is unchanged. PostgreSQL integration coverage verifies exactly one winner, documented 409 codes for every loser, and (via a synchronized barrier subset) that the conditional-update race is genuinely exercised, with zero silent test skips. **Roadmap PR8 (PR8A, PR8B, and PR8C) is now fully complete.** See `docs/DECISION_LOG.md` ("Roadmap PR8 (PR8A slice)", "Roadmap PR8 (PR8B slice)", "Roadmap PR8 (PR8C slice)").

**PR9 note:** `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §7 ("Ward Recording Rules") identified an unimplemented gap: no endpoint existed to correct a transaction's recorded destination ward, an audited correction of historical data — deliberately **not** ward-transfer or current-location tracking, which remains out of scope. Following the same lettered-slice precedent as PR7/PR8, this was split into two, both now merged: **PR9A** (backend, GitHub PR #33) added `POST /transactions/{id}/correct-ward` — a narrow, purpose-built action (never a generic transaction PATCH), a conditional-`UPDATE`-decided-by-affected-rowcount concurrency guard mirroring PR8A's shape, and exactly one audited entry per success, atomic with the ward change. Works identically for an `open` or `closed` transaction. Authorization was temporarily restricted to `admin` only (`app.api.v1.deps.WARD_CORRECTION_ROLES`) at the time PR9A merged — the then-current 5-role model had no confirmed, evidence-backed equivalent of the "Equipment Pool Staff" role (docs/audits/03-hospital-equipment-pool-workflow-audit.md §10). This temporary rule is superseded by Roadmap PR10's confirmed 3-role matrix (see the PR10 note below): ward correction is now available to `administrator` and `equipment_pool_staff`. **PR9B** (frontend, GitHub PR #34) added a minimal ward-correction dialog reachable from both the receipt screen (`ReturnPage.tsx`, an OPEN transaction) and equipment detail's transaction history (`EquipmentDetailPage.tsx`, OPEN or CLOSED, matching PR9A's own lack of a lifecycle-status precondition), correction actions always keyed by the transaction's actual UUID, mirroring the same temporary admin-only visibility as a usability-only gate (the backend remains authoritative). No lifecycle, schema, migration, or receipt/dispatch contract change in either slice. **Roadmap PR9 is fully complete.** See `docs/DECISION_LOG.md` ("Roadmap PR9 — Audited ward correction (PR9A/PR9B slices)").

**PR10 note:** `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §10 ("Role and Permission Review") recommended collapsing the legacy 5-role model (`admin`, `biomedical_engineer`, `ward_nurse`, `transport_staff`, `viewer`) to the confirmed 3-role model — `administrator`, `equipment_pool_staff`, `read_only` — everywhere a role is persisted, checked, displayed, or seeded. GitHub PR #36 implemented this: canonical backend role constants and centralized capability groups, a fail-closed `MEP_PR10_ROLE_MAPPING` manifest mechanism for any legacy role with no confirmed automatic equivalent, a `ck_roles_name_confirmed` CHECK constraint, and a closed 3-value `Role` type/capability layer on the frontend. Three iterative Codex review rounds, completed before PR #36 was squash merged, hardened the migration itself (`backend/alembic/versions/0009_role_consolidation.py`): atomic audit provenance for both upgrade and downgrade, fail-closed manifest validation restricted to genuinely ambiguous accounts, lossless downgrade restoring exact legacy role IDs/permissions/user assignments (via durable `role_migration_snapshots`/`user_role_migrations` provenance tables, not `legacy_role_name` alone), and confirmed-role ownership provenance (`confirmed_role_ownership`) so downgrade never deletes a pre-existing confirmed-role row. See `docs/BUSINESS_RULES.md` ("Roles and the confirmed 3-role permission matrix") for the full capability-by-capability matrix and `docs/DECISION_LOG.md` ("Roadmap PR10") for the full migration mechanism and design rationale. **Roadmap PR10 is now fully complete.** Ward correction's temporary Administrator-only rule (Roadmap PR9A) is superseded by the confirmed matrix (Administrator + Equipment Pool Staff) — see the updated PR9 note above.

**PR11 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's PR11 entry called for "the full user-facing terminology change and the new dispatch/receipt UI shape in one coordinated pass." GitHub PR #38 implemented this: "ยืม"/"คืน" (borrow/return) is retired everywhere it was visible in the UI — navigation, the dispatch (`BorrowPage.tsx`) and receipt (`ReturnPage.tsx`) forms, `EquipmentDetailPage.tsx`'s CTA buttons and transaction history, and the dashboard/reports chart labels — replaced consistently by "เบิก"/"รับคืน" (issue/receive back). The ward field (dispatch form, receipt form, and equipment-detail transaction history) is relabeled "หอผู้ป่วยที่รับเครื่อง (บันทึก ณ วันที่เบิก)" with a caption disclaiming real-time location tracking, satisfying the Workflow Audit §7.1 acceptance criterion. Three independent Codex reviews on Draft PR #38, each on a new exact head before PR #38 was squash merged, hardened the required test coverage: **Review `4781057781`** (finding PR11-M1) found no `BorrowPage` component tests existed at all, and no test exercised the dispatch → receipt workflow — fixed by adding `BorrowPage.test.tsx` (dispatch-form component tests: terminology, ward label/disclaimer, on-demand/routine_round payloads, validation gating, loading/empty states, API error states) and a `DispatchReceiptWorkflow.test.tsx` end-to-end test. **Review `4781138180`** (findings PR11-M1R and PR11-M2) required that workflow test be rewritten around one shared, mutable mock store so the equipment-status transitions it asserts (available → issued → available) are actually caused by the mocked `createBorrow`/`createReturn` implementations rather than hand-fed per step, and required the PR description be refreshed to match the final diff. **Review `4781151810`** recorded APPROVE with no remaining findings. No backend, API, database, migration, RBAC, or business-rule change — this PR is frontend-only, exactly as scoped; internal route paths (`/borrow`, `/return`) and service/function names (`createBorrow`, `listActiveBorrows`, etc.) were intentionally left unchanged. See `docs/DECISION_LOG.md` ("Roadmap PR11") for full detail. **Roadmap PR11 is now fully complete.**

## Planned (not yet started)

Per `docs/audits/04-consolidated-implementation-plan.md` Part D:

| Roadmap PR | Title |
|---|---|
| PR12 | Inventory Import |
| PR13 | Search, History, and Reporting Adjustments |
| PR14 | Reliability and Performance Hardening |
| PR15 | Observability and Schema Hygiene |

**PR14 above is Reliability and Performance Hardening — it is not related to GitHub PR #14 (which implemented Roadmap PR5).** See the numbering note.

**GitHub PR #40 note:** GitHub PR #40 ("Dashboard & Equipment Status") is now merged and recorded in the Completed table above as an unnumbered "— (frontend)" row. It does **not** implement Roadmap PR12 — its originating task description used "PR12" as an informal label, which conflicted with this file's Roadmap PR12 (Inventory Import). Governance PR #41 (see `docs/DECISION_LOG.md`, "Governance — GitHub PR #40 classification") resolved that conflict by classifying it as an unnumbered Post-PR11 Frontend Dashboard UX Follow-up, the same category this file already uses for infrastructure/governance/documentation work that was never assigned a Roadmap PR number. Roadmap PR12 (Inventory Import) and Roadmap PR13 (Search, History, and Reporting Adjustments) are both unchanged by this decision or by GitHub PR #40's merge — neither their scope, number, nor ordering was touched. **Roadmap PR12 (Inventory Import) is the next planned item and has not started.**

## Confirmed future work (not scheduled to a Roadmap PR)

- **Shift Sessions** — flexible DAY/NIGHT sessions replacing hard-coded routine-round times.
- **Standby Snapshots** — Day/Night department-level equipment-count reports.
- **Managed deployment** — production must not assume direct access to hospital-managed servers.

Detail and rationale: `AGENTS.md` ("Confirmed Future Workflow Direction"), `docs/ARCHITECTURE_DECISIONS.md`.

## Related documents

| Concern | Document |
|---|---|
| Full scope, ordering, dependencies, acceptance criteria per PR | `docs/audits/04-consolidated-implementation-plan.md` |
| Per-decision rationale for PR5 onward | `docs/DECISION_LOG.md` |
| Per-decision rationale for PR1 through Governance Pack v1.0 | `docs/PROJECT_MEMORY.md` |
| Current-state AI-memory snapshot | `knowledge/PROJECT_MEMORY.md` |
| Right-now state (current PR, outstanding work, risks) | `knowledge/CONTEXT.md` |
| Domain entity structural reference | `docs/DOMAIN_MODEL.md` |
| Transaction lifecycle decision (PR7, both slices) | `knowledge/adr/ADR-005-transaction-model.md` |
