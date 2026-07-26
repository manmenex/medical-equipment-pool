# Project Memory (AI Snapshot)

**Purpose:** Long-term AI memory — a single point-in-time snapshot a new session can read to reconstruct working context without replaying history
**Authority:** Summary snapshot. Every fact below cites its authoritative source; the source controls if this snapshot drifts out of date. Not the same file as [`../docs/PROJECT_MEMORY.md`](../docs/PROJECT_MEMORY.md) — that file is the dated chronological decision log, this file is a current-state summary. See also [`CONTEXT.md`](CONTEXT.md) for the more volatile "right now" details (current PR, outstanding work, risks).
**Update trigger:** Any fact below becomes stale — check this file at the start of major work, update it at the end
**Maintainer:** Documentation/Governance Engineer

## Project purpose

The Medical Equipment Pool is a browser/PWA system used by hospital Equipment Pool operators to dispatch pool equipment (primarily infusion pumps and select shared equipment) to a first receiving ward and record its receipt back. It replaces a prior AppSheet-based spreadsheet process. It is not a patient-tracking, cleaning, maintenance, calibration, recall, or hospital-wide asset-lifecycle system.

Source: `docs/PROJECT_PLAYBOOK.md` ("Project purpose and boundary"); `knowledge/adr/ADR-001-equipment-pool-scope.md`.

## Architecture summary

- **Backend:** Async FastAPI (`backend/app/`), layered API -> services -> CRUD -> models, SQLAlchemy 2.0 async, Alembic migrations.
- **Database:** PostgreSQL (`postgres:16-alpine` in CI/dev), accessed via `asyncpg`. SQLite is used only for the fast default test run and is not sufficient evidence for PostgreSQL-specific behavior.
- **Frontend:** React/TypeScript/Vite single-page app, built as a PWA (`vite-plugin-pwa`).
- **Deployment:** Must remain portable to a managed platform; no design assumes direct access to hospital-managed servers.
- **CI:** `.github/workflows/ci.yml` — backend non-PostgreSQL tests, backend PostgreSQL-marked tests (fail-closed preflight gate, see below), standalone Alembic upgrade validation, frontend build, whitespace check. Least-privilege (`contents: read`, `persist-credentials: false`).

Source: `docs/ARCHITECTURE_DECISIONS.md`; `docs/PROJECT_WORKFLOW.md`.

## Stable business rules

See `docs/BUSINESS_RULES.md` for the full list with citations. Summary:

- Exactly four equipment states: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`.
- Cleaning is a physical activity that may happen before or after receipt is recorded; it is never represented as a state and never needs a separate workflow. A usable receipt ends at `AVAILABLE_AT_POOL`; a defective receipt ends at `UNAVAILABLE_DEFECTIVE`.
- Dispatch and receipt (`backend/app/services/borrow_service.py`) are the only paths that move equipment through `ISSUED_TO_WARD`, and the only paths that open/close a transaction (`app.crud.transaction.create()`/`close()`); administrative status maintenance is a separate, narrower path. `BorrowTransaction.status` is exactly `TransactionStatus.OPEN`/`CLOSED` (Roadmap PR7's lifecycle slice) — see `docs/BUSINESS_RULES.md`.
- Concurrent receipt is guarded at the database level: `app.crud.transaction.close()` decides the sole winner among racing receipt requests solely by the affected-rowcount of a single conditional `UPDATE ... WHERE id = :id AND status = 'open'`, never by an application-level pre-check. Every losing request is rolled back before any business side effect runs (no equipment-status change, no status-history row, no audit row) — only the winner performs side effects, in the same transaction. Proven with deterministic PostgreSQL tests across a matrix of 1, 2, 5, 10, and 50 requests: the 1-request case verifies normal receipt behavior with no concurrency, the 2/5/10 cases synchronize the complete burst to force genuine contention, and the 50-request case synchronizes a bounded subset to prove conditional-`UPDATE` contention without exhausting the connection pool. Implemented as Roadmap PR8A (GitHub PR #26); see `docs/DECISION_LOG.md`.
- Every new dispatch requires `ward_id` and `dispatch_type` (`routine_round`/`on_demand`, `DispatchType`); `routine_round` (one of the four confirmed fixed times `06:00`/`11:00`/`15:00`/`21:00`) is required exactly for `routine_round` dispatches and forbidden for `on_demand` (Roadmap PR7 7b slice, merged GitHub PR #20). `borrower_name`/`due_at`/`quantity` are rejected outright by `BorrowRequest` (`extra="forbid"`); every existing historical value is preserved — see `docs/BUSINESS_RULES.md`.
- Decommissioning must pass through `UNAVAILABLE_DEFECTIVE`; `AVAILABLE_AT_POOL` cannot skip directly to `DECOMMISSIONED`.
- No patient tracking, no ward-to-ward transfer tracking, no MEMS/PM/calibration/recall workflow.
- A transaction's first recorded receiving ward is immutable except through the dedicated audited correction action (`POST /transactions/{id}/correct-ward`, `app.services.borrow_service.correct_ward`). Correction supports both `open` and `closed` transactions, is not ward-transfer tracking, and never alters equipment or transaction lifecycle state. Authorization is Administrator and Equipment Pool Staff (`app.api.v1.deps.WARD_CORRECTION_ROLES`), per Roadmap PR10's confirmed 3-role matrix — temporarily Administrator-only between PR9A and PR10. Implemented as Roadmap PR9 (PR9A backend, GitHub PR #33; PR9B frontend, GitHub PR #34); role widened by Roadmap PR10 (GitHub PR #36); see `docs/BUSINESS_RULES.md` and `docs/DECISION_LOG.md`.

## Stable identifiers

Exactly four, each with one fixed role — no substitution, no fifth identifier:

1. **Internal UUID** — relational primary key, never entered manually.
2. **BCM Code** — primary operator-facing identifier; the only manual-search identifier.
3. **Item No** — hospital QR-label identifier; QR lookup only; excluded from normal operator responses.
4. **Asset Number** — inventory metadata only; not searchable or scannable.

**"ME Code" is retired** and must not be used or reintroduced.

Source: `knowledge/adr/ADR-002-identifier-model.md` through `ADR-004`.

## Current workflow (requirement to merge)

```text
Requirement -> ChatGPT Architecture Review -> Claude Implementation -> Draft PR
  -> GitHub Actions CI -> Ready for review -> Codex Independent Review
  -> ChatGPT Project Governor Review -> Owner Approval -> Squash Merge
```

Claude writes code. Codex reviews code. ChatGPT governs architecture, roadmap, prompts, and review interpretation. The Owner makes business and merge decisions. No automatic merge; no Claude<->Codex repair loop; new commits invalidate prior review.

Source: `docs/PROJECT_WORKFLOW.md`.

## Current baseline

`7708190ebf08b7212b7a73ba831263b94434d1eb` (branch `claude/medical-equipment-pool-0c7fz0`, squash merge of Roadmap PR11, Frontend Terminology and Workflow UI Pass, GitHub PR #38), on top of the post-PR10-completion documentation-only governance sync (GitHub PR #37, squash SHA `66bdd547937b7741d53b16a98fe74280dee18273`), which sits on top of Roadmap PR10 (Role Model Consolidation, GitHub PR #36, squash SHA `53340f6d7d5c8cda685235411b60a57d2d033a7e`), which sits on top of Roadmap PR9's PR9B slice (frontend audited ward correction, GitHub PR #34, squash SHA `bfe8a42a55d738d3e591ce27145c7918186643ac`) as of this snapshot. Always confirm against `knowledge/CONTEXT.md` and `docs/ROADMAP.md`, which are updated more frequently than this file.

## Completed Roadmap

Roadmap PR1-PR6 merged (security/availability foundation, structured exceptions, audit logging framework, transaction-number sequence, equipment identifier model, four-state equipment model), plus the Knowledge Layer v2 governance PR, the CI/AI-review-workflow infrastructure PR, the Knowledge & Governance Foundation PR, and both slices of Roadmap PR7 (transaction lifecycle model `OPEN`/`CLOSED`, GitHub PR #19; dispatch type/routine round/required ward_id/field cleanup, GitHub PR #20). Roadmap PR7 is now fully merged. Since then, five process/documentation-only PRs merged (no Roadmap PR number assigned, no code/business-rule/schema change): post-merge governance sync (GitHub PR #21), Test Infrastructure Cleanup (GitHub PR #22), Developer Documentation (GitHub PR #23), the API & Error Catalog (GitHub PR #24), and a second post-merge governance sync after PR21-PR24 (GitHub PR #25). Roadmap PR8 was then split into three slices, following the same precedent as PR7: PR8A (the database-level concurrency guard) merged as GitHub PR #26; PR8B (condition-to-binary-outcome contract narrowing) merged in two coordinated parts, backend (GitHub PR #28) and frontend (GitHub PR #29), deployed together. A sixth documentation/governance PR, GitHub PR #30 (`4af6a4c623f24718f37241105c90425276e5ce7a`), synchronized documentation after PR8B and closed TD-006 before PR8C merged. PR8C (race-vs-repeat error-code distinction) merged as GitHub PR #31. **Roadmap PR8 (PR8A, PR8B, and PR8C) is now fully complete.** Full table with GitHub PR numbers and squash SHAs: `docs/ROADMAP.md`.

Roadmap PR9 was split into two slices, following the same precedent as PR7 and PR8: PR9A (backend, audited ward-correction endpoint, temporarily Administrator-only authorization) merged as GitHub PR #33; PR9B (frontend, admin-only ward-correction UI consuming PR9A's contract exactly, reachable for both OPEN and CLOSED transactions) merged as GitHub PR #34. **Roadmap PR9 (both slices) is now fully complete.** A documentation-only post-merge governance sync recording PR9's completion then merged as GitHub PR #35 (squash `bc1b163929a4d07290e56add1db8ad99c592e1a2`).

**Roadmap PR10 (Role Model Consolidation) is merged** (GitHub PR #36, squash `53340f6d7d5c8cda685235411b60a57d2d033a7e`), from branch `feature/pr10-role-consolidation`. It replaced the legacy 5-role model with the confirmed 3-role model (`administrator`/`equipment_pool_staff`/`read_only`), including a new Alembic migration (`0009_role_consolidation.py`) with a fail-closed manifest mechanism for the three legacy roles that had no confirmed equivalent. Three iterative Codex review rounds, completed before PR #36 was squash merged, hardened the migration's atomicity/audit/lossless-restoration/ownership guarantees — downgrade restores exact legacy role ids/permissions/user assignments from durable `role_migration_snapshots`/`user_role_migrations` provenance (never `legacy_role_name` alone) and deletes a confirmed-role row only when `confirmed_role_ownership` proves this migration created it. See `docs/DECISION_LOG.md` ("Roadmap PR10") and `docs/BUSINESS_RULES.md` ("Roles and the confirmed 3-role permission matrix") for full detail. A documentation-only governance sync (GitHub PR #37, squash `66bdd547937b7741d53b16a98fe74280dee18273`, mirroring the one after Roadmap PR9, GitHub PR #35) recorded PR10's completion.

**Roadmap PR11 (Frontend Terminology and Workflow UI Pass) is now merged** (GitHub PR #38, squash `7708190ebf08b7212b7a73ba831263b94434d1eb`), from branch `feature/pr11-frontend-terminology`, baseline `66bdd547937b7741d53b16a98fe74280dee18273`. It retired "ยืม"/"คืน" (borrow/return) as user-facing UI terminology everywhere it appeared — navigation, the dispatch/receipt forms, equipment-detail's CTA buttons and transaction history, and the dashboard/reports chart labels — replaced consistently by "เบิก"/"รับคืน" (issue/receive back). The ward field is relabeled with the Workflow Audit §7.1-required caption disclaiming real-time location tracking on the dispatch form, receipt form, and equipment-detail transaction history. Two iterative Codex review rounds, completed before PR #38 was squash merged, closed a test-coverage gap: the first added the previously-missing `BorrowPage.test.tsx` and an end-to-end `DispatchReceiptWorkflow.test.tsx`; the second required that workflow test be rewritten around one shared, mutable mock store so the equipment-status transitions it asserts are actually caused by the mocked `createBorrow`/`createReturn` implementations, not hand-fed per step. No backend, API, database, migration, or RBAC change — frontend-only, exactly as scoped. See `docs/DECISION_LOG.md` ("Roadmap PR11") for full detail. This documentation-only governance sync (mirroring the ones after Roadmap PR9 and Roadmap PR10) records PR11's completion and advances the "Current baseline" above. Roadmap PR12 (Inventory Import) is now the next planned item; PR13 through PR15 remain planned and not yet started — see `docs/ROADMAP.md`. The original, pre-split PR8 design document (`docs/design/PR8_IMPLEMENTATION_PLAN.md`, uncommitted, design-only) is what PR8A implemented Option A from and what PR8C's race-vs-repeat distinction was already anticipated in (Section 6); it remains untracked.

**Governance note:** GitHub PR #40 ("Dashboard & Equipment Status," a frontend-only Dashboard/quick-actions redesign) is **not** Roadmap PR12, despite its originating task description's "PR12" label. A dedicated Governance PR classified it as an unnumbered Post-PR11 Frontend Dashboard UX Follow-up instead, after two independent Codex reviews (review `4781262010` — initial review, identified PR40-H1; review `4781273707` — follow-up review, blocker remained) blocked it from merging under that conflicting identity. Roadmap PR12 (Inventory Import) and Roadmap PR13 are both unchanged by this decision. See `docs/DECISION_LOG.md` ("Governance — GitHub PR #40 classification") and `docs/ROADMAP.md` ("Non-Roadmap work in flight").

## Current AI responsibilities

| Role | Responsibility |
|---|---|
| Claude | Implementation on an assigned, bounded task |
| Codex | Independent implementation review |
| ChatGPT | Architecture/roadmap governance, both before implementation and after Codex's review |

See `docs/PROJECT_WORKFLOW.md` for the full pipeline and `docs/REVIEW_CHECKLIST.md` for the shared review checklist.

## Never-change rules (do not implement without an approved Governance PR)

- Do not add a fifth equipment identifier or a fifth equipment state.
- Do not add a cleaning state, cleaning-complete action, or cleaning workflow.
- Do not add patient tracking (name, HN/MRN, bed number, named borrower).
- Do not add ward-to-ward transfer tracking.
- Do not bypass dispatch/receipt services to change equipment status.
- Do not edit merged migration history casually.
- Do not implement a later Roadmap PR ahead of its assigned order.
- Do not merge automatically, and do not run a Claude<->Codex auto-repair loop.

Full list with rationale: `docs/ARCHITECTURE_GUARDRAILS.md`.

## Current limitations

- The GitHub connector can return `403 Resource not accessible by integration` when submitting a formal Pull Request Review (not a silent downgrade). Preferred fallback: a formal `COMMENTED` review submitted through an authenticated browser session (this does satisfy review evidence). Last resort only: a PR Conversation comment, which is an incomplete status report and never counts as completed review evidence by itself.
- No branch-protection rule yet requires CI to pass before merge; enforced by process discipline instead.

Full detail and workarounds: `docs/KNOWN_LIMITATIONS.md`.
