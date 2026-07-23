# Roadmap

**Purpose:** Current-state snapshot of the Medical Equipment Pool Roadmap — what is merged, what is next, at the current baseline
**Authority:** Summary. `docs/audits/04-consolidated-implementation-plan.md` Part D remains authoritative for Roadmap PR scope, order, dependencies, and acceptance criteria. `docs/ROADMAP_STATUS.md` is superseded by this file (see the banner on that file).
**Update trigger:** A Roadmap PR merges, is added, is reordered, or the baseline changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`f923f0aec8aa79fb4c33d2c1b0c05c08a057fe17` — squash commit of Roadmap PR8C (GitHub PR #31, race-loss-vs-genuine-repeat receipt rejection), on branch `claude/medical-equipment-pool-0c7fz0`. This sits on top of `4af6a4c623f24718f37241105c90425276e5ce7a` (post-PR8B documentation sync, GitHub PR #30), which sits on top of `d3e027b5a4ee7d99b38dfd0d263dc460c74eb5c5` (PR8B's frontend slice, GitHub PR #29) and `da4d76a640548e5a1d38ff3d7690695f950c85fe` (PR8B's backend slice, GitHub PR #28), which sit on top of `4820dbaa683f4cb80732406892b7708d2e242d85` (Roadmap PR8A, GitHub PR #26). **Roadmap PR8 (all three slices — PR8A, PR8B, PR8C) is now fully complete.**

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

Full rationale and review-fix history for PR5 through PR9 (PR9A slice): `docs/DECISION_LOG.md`. PR21, PR22-PR25, and PR30/PR32 (GitHub PR numbers) are process/documentation-only additions with no code, business-rule, or schema change — no `DECISION_LOG.md` entry was needed for them. PR8A/PR8B/PR8C/PR9A (GitHub PR #26, #28, #29, #31, #33) are different: they are production code changes; PR9A's `docs/DECISION_LOG.md` entry is still pending as of this snapshot (see the PR9 note below) and should be added in a future governance sync.

**PR7 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR7 entry recommended splitting into a 7a (lifecycle model) and 7b (`dispatch_type`/`routine_round`/ward-required/field-cleanup) slice "if the reviewing team prefers smaller units." PR7 (7a slice) shipped `TransactionStatus` (`OPEN`/`CLOSED`), the `create()`/`close()` mutator split, `legacy_status` preservation, and disabling the deprecated `due_at`-driven overdue-notification scheduler job (Codex PR7a review round 1, BLOCKER — see `docs/DECISION_LOG.md`). PR7 (7b slice) completed PR7's remaining scope: `dispatch_type` (`routine_round`/`on_demand`), `routine_round` (the four confirmed fixed times), a required `ward_id` for every new dispatch (application-layer enforced), and removing `borrower_name`/`due_at`/`quantity` from the active write path while preserving every existing historical value as read-only history — plus, after Codex round 1 review, `BorrowRequest` now rejects unknown request fields outright, an invalid `ward_id` is classified as a distinct 400 `INVALID_INPUT` rather than the equipment-conflict 409, and the migration 0008 test suite was rewritten to exercise a genuinely reconstructed pre-migration production schema. Roadmap PR7 (both slices) is now fully merged. Concurrent-receipt protection (two simultaneous receipts racing on the same OPEN transaction) was **not** part of either slice — that gap is closed by Roadmap PR8A below.

**PR8 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR8 entry ("Atomic Single-Operation Equipment Receipt with concurrency guard") was split into **three** slices during implementation planning (`docs/design/PR8_IMPLEMENTATION_PLAN.md`, design-only, uncommitted; the original PR7a/PR7b-style two-slice split was refined to three once PR8B's own scope proved to have two independent, separately-shippable halves — see the Codex review recorded in `docs/DECISION_LOG.md` "Roadmap PR8 (PR8B slice)"). **PR8A** (GitHub PR #26) is the database-level concurrency guard: `app.crud.transaction.close()` performs a single conditional `UPDATE ... WHERE id = :id AND status = 'open'`, deciding the winner by affected-row count, so exactly one concurrent receipt request succeeds and every loser rolls back before any business side effect — proven with deterministic PostgreSQL tests across a matrix of 1, 2, 5, 10, and 50 requests: the 1-request case verifies normal receipt behavior with no concurrency, the 2/5/10 cases synchronize the complete burst to force genuine contention, and the 50-request case synchronizes a bounded subset to prove conditional-`UPDATE` contention without exhausting the connection pool. No API contract, schema, or frontend change. **PR8B** (GitHub PR #28 backend + #29 frontend, deployed together) narrows the `condition` field to the confirmed binary `receipt_outcome` (`usable`/`defective`) contract, backend and frontend. `docs/TECH_DEBT.md` TD-006, which tracked the frontend/backend gap between the two PR8B slices, is `Closed`. **PR8C** (GitHub PR #31) distinguishes the two causes of a losing receipt request by machine-readable code — `TRANSACTION_ALREADY_RETURNED` (the transaction was already closed when the request evaluated current state) versus `RECEIPT_RACE_LOST` (the request observed an open transaction but lost the conditional-update race) — both still `409 Conflict`; `RECEIPT_RACE_LOST`'s wording deliberately attributes the outcome to another *request*, not another person, since the backend has no basis to identify who sent the winning request. The frontend branches on the response's `code` field, never on free-text `detail`. No lifecycle, schema, migration, or request-contract change; `receipt_outcome: "usable" | "defective"` is unchanged. PostgreSQL integration coverage verifies exactly one winner, documented 409 codes for every loser, and (via a synchronized barrier subset) that the conditional-update race is genuinely exercised, with zero silent test skips. **Roadmap PR8 (PR8A, PR8B, and PR8C) is now fully complete.** See `docs/DECISION_LOG.md` ("Roadmap PR8 (PR8A slice)", "Roadmap PR8 (PR8B slice)", "Roadmap PR8 (PR8C slice)").

**PR9 note:** `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §7 ("Ward Recording Rules") identified an unimplemented gap: no endpoint existed to correct a transaction's recorded destination ward, an audited correction of historical data — deliberately **not** ward-transfer or current-location tracking, which remains out of scope. Following the same lettered-slice precedent as PR7/PR8, this was split into two: **PR9A** (backend, GitHub PR #33) added `POST /transactions/{id}/correct-ward` — a narrow, purpose-built action (never a generic transaction PATCH), a conditional-`UPDATE`-decided-by-affected-rowcount concurrency guard mirroring PR8A's shape, and exactly one audited entry per success, atomic with the ward change. Authorization is temporarily restricted to `admin` only (`app.api.v1.deps.WARD_CORRECTION_ROLES`) — the current 5-role model has no confirmed, evidence-backed equivalent of the future "Equipment Pool Staff" role (docs/audits/03-hospital-equipment-pool-workflow-audit.md §10), so every other current role is denied pending Roadmap PR10's Role Model Consolidation. **PR9B** (frontend) is in progress (see "In progress" above) — a minimal ward-correction dialog on the receipt screen, mirroring the same temporary admin-only visibility as a usability-only gate (the backend remains authoritative). No lifecycle, schema, migration, or receipt/dispatch contract change in either slice. **Roadmap PR9 is not complete until both slices merge.**

## In progress

**PR9 (PR9B slice) — Frontend ward correction.** A minimal, mobile-first UI (`frontend/src/pages/ReturnPage.tsx`, `frontend/src/components/WardCorrectionDialog.tsx`) consuming PR9A's merged backend contract exactly, gated to the current Administrator-only temporary visibility (`frontend/src/hooks/useAuth.ts`'s `canCorrectTransactionWard`, mirroring `app.api.v1.deps.WARD_CORRECTION_ROLES`). Not yet merged as of this snapshot. **Roadmap PR9 is not complete until this slice merges too.**

## Planned (not yet started)

Per `docs/audits/04-consolidated-implementation-plan.md` Part D:

| Roadmap PR | Title |
|---|---|
| PR10 | Role Model Consolidation (3 roles) |
| PR11 | Frontend Terminology and Workflow UI Pass |
| PR12 | Inventory Import |
| PR13 | Search, History, and Reporting Adjustments |
| PR14 | Reliability and Performance Hardening |
| PR15 | Observability and Schema Hygiene |

**PR14 above is Reliability and Performance Hardening — it is not related to GitHub PR #14 (which implemented Roadmap PR5).** See the numbering note.

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
