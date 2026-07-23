# Roadmap

**Purpose:** Current-state snapshot of the Medical Equipment Pool Roadmap — what is merged, what is next, at the current baseline
**Authority:** Summary. `docs/audits/04-consolidated-implementation-plan.md` Part D remains authoritative for Roadmap PR scope, order, dependencies, and acceptance criteria. `docs/ROADMAP_STATUS.md` is superseded by this file (see the banner on that file).
**Update trigger:** A Roadmap PR merges, is added, is reordered, or the baseline changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`4820dbaa683f4cb80732406892b7708d2e242d85` — squash commit of Roadmap PR8A, Atomic Receipt Concurrency Guard (GitHub PR #26), on branch `claude/medical-equipment-pool-0c7fz0`.

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

Full rationale and review-fix history for PR5 through PR8 (PR8A slice): `docs/DECISION_LOG.md`. PR21-PR25 (GitHub PR numbers) are process/documentation-only additions with no code, business-rule, or schema change — no `DECISION_LOG.md` entry was needed for them. PR8A (GitHub PR #26) is different: it is a production code change (though not a business-rule, schema, or API-contract change) and does have a `DECISION_LOG.md` entry.

**PR7 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR7 entry recommended splitting into a 7a (lifecycle model) and 7b (`dispatch_type`/`routine_round`/ward-required/field-cleanup) slice "if the reviewing team prefers smaller units." PR7 (7a slice) shipped `TransactionStatus` (`OPEN`/`CLOSED`), the `create()`/`close()` mutator split, `legacy_status` preservation, and disabling the deprecated `due_at`-driven overdue-notification scheduler job (Codex PR7a review round 1, BLOCKER — see `docs/DECISION_LOG.md`). PR7 (7b slice) completed PR7's remaining scope: `dispatch_type` (`routine_round`/`on_demand`), `routine_round` (the four confirmed fixed times), a required `ward_id` for every new dispatch (application-layer enforced), and removing `borrower_name`/`due_at`/`quantity` from the active write path while preserving every existing historical value as read-only history — plus, after Codex round 1 review, `BorrowRequest` now rejects unknown request fields outright, an invalid `ward_id` is classified as a distinct 400 `INVALID_INPUT` rather than the equipment-conflict 409, and the migration 0008 test suite was rewritten to exercise a genuinely reconstructed pre-migration production schema. Roadmap PR7 (both slices) is now fully merged. Concurrent-receipt protection (two simultaneous receipts racing on the same OPEN transaction) was **not** part of either slice — that gap is closed by Roadmap PR8A below.

**PR8 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR8 entry ("Atomic Single-Operation Equipment Receipt with concurrency guard") was split into **three** slices during implementation planning (`docs/design/PR8_IMPLEMENTATION_PLAN.md`, design-only, uncommitted; the original PR7a/PR7b-style two-slice split was refined to three once PR8B's own scope proved to have two independent, separately-shippable halves — see the Codex review recorded in `docs/DECISION_LOG.md` "Roadmap PR8 (PR8B slice)"). **PR8A** (this table's entry, GitHub PR #26) is the database-level concurrency guard only: `app.crud.transaction.close()` now performs a single conditional `UPDATE ... WHERE id = :id AND status = 'open'`, deciding the winner by affected-row count, so exactly one concurrent receipt request succeeds and every loser rolls back before any business side effect — proven with deterministic PostgreSQL tests forcing genuine contention across bursts of 1, 2, 5, 10, and 50 requests. No API contract, schema, or frontend change. **PR8B** (in progress — Draft, pending review; see "In progress" below) narrows the `condition` field to the confirmed binary `receipt_outcome` (`usable`/`defective`) contract. **PR8C** (see "Planned" below, not started) is the remaining, separately-named scope: a distinguishable race-loss-vs-genuine-repeat error message/code — both causes currently share `409 TRANSACTION_ALREADY_RETURNED` and will continue to until PR8C lands (`knowledge/adr/ADR-006-receipt-outcome-contract.md`). **Roadmap PR8 is not fully complete until PR8A, PR8B, AND PR8C all merge — do not describe PR8 as done until then.** See `docs/DECISION_LOG.md` ("Roadmap PR8 (PR8A slice)", "Roadmap PR8 (PR8B slice)").

## In progress

**PR8 (PR8B slice)** — Receipt outcome contract narrowing (`receipt_outcome`: `usable`/`defective`, replacing `condition`). Draft, pending review — no GitHub PR number or squash SHA yet. See `docs/DECISION_LOG.md` ("Roadmap PR8 (PR8B slice)") and `knowledge/adr/ADR-006-receipt-outcome-contract.md`. Backend contract only — the frontend is not yet updated to match (`docs/TECH_DEBT.md` TD-006; the backend and frontend must be released together, ADR-006 Decision 1). The race-vs-repeat error-message distinction is out of this slice's scope entirely — see PR8C below.

## Planned (not yet started)

Per `docs/audits/04-consolidated-implementation-plan.md` Part D:

| Roadmap PR | Title |
|---|---|
| PR8 (PR8C slice) | Race-loss-vs-genuine-repeat receipt rejection: distinguishable error message/code |
| PR9 | Ward Correction Action (audited) |
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
