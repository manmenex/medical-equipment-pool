# Context

**Purpose:** Current project state — the most volatile document in the knowledge layer
**Authority:** Point-in-time status only. Does not restate rules or rationale — see `knowledge/PROJECT_MEMORY.md` for the stable snapshot this file assumes.
**Update trigger:** Every merged PR, and whenever a risk or outstanding item changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`4041cd2aec412c94f730285d7ba4635e00b095bd` — squash commit of Roadmap PR7 (7a slice, Transaction lifecycle model), GitHub PR #19, on branch `claude/medical-equipment-pool-0c7fz0`.

## Current PR

**Roadmap PR7 (7b slice) — dispatch type, routine round, and write-path cleanup** — branch `feature/pr20-transaction-fields`. Completes Roadmap PR7's remaining scope: adds `DispatchType` (`routine_round`/`on_demand`) and `RoutineRound` (the four confirmed fixed times `06:00`/`11:00`/`15:00`/`21:00`) to `BorrowTransaction`; `BorrowRequest` now requires `ward_id` and `dispatch_type` for every new dispatch, requires `routine_round` exactly for `routine_round` dispatches, and no longer accepts `borrower_name`/`due_at`/`quantity`; `TransactionOut` drops `due_at` and makes `borrower_name` nullable. Migration `0008_dispatch_fields.py` adds the two new nullable columns, three CHECK constraints, and relaxes `borrower_name` to nullable at the database level — purely additive, no legacy-value remap, every existing historical value preserved unmodified. `ward_id`-required stays application-layer-only, never a database `NOT NULL`; no existing row is auto-assigned a ward or a dispatch classification. `frontend/src/pages/BorrowPage.tsx` gained a required ward selector and dispatch-type/conditional routine-round selectors, and lost its borrower-name input (minimum functional form change, not the Roadmap PR11 terminology redesign). See `knowledge/adr/ADR-005-transaction-model.md`, `docs/DOMAIN_MODEL.md`, and `docs/DECISION_LOG.md`. Status: Draft, pending review.

## Next planned PR

Roadmap PR8 (Atomic Single-Operation Equipment Receipt with concurrency guard), once this PR is merged — concurrent-receipt protection remains mandatory before pilot deployment and is not implemented by this PR.

## Outstanding work

- Roadmap PR8 through PR15 (atomic receipt, ward correction, role consolidation, frontend terminology, inventory import, search/reporting, reliability/performance hardening, observability/schema hygiene) are planned and not started.
- Confirmed future work not yet scheduled to a Roadmap PR: Shift Sessions, Standby Snapshots, managed-deployment target selection (`docs/ROADMAP.md`).
- `docs/TECH_DEBT.md` open items: TD-001 (equipment update/status `MissingGreenlet`), TD-002 (`0001_initial.py` uses current ORM metadata), TD-003 (CI now exists and fails closed, but branch protection requiring it is not enabled — partially resolved, needs re-assessment), TD-004 (naive `datetime.utcnow()`), TD-005 (temporary default/long-lived branch structure).

## Current risks

- **Branch protection is not enabled.** CI failing does not technically block a merge yet; the Repository Owner must manually re-verify CI status before every merge (`docs/KNOWN_LIMITATIONS.md`).
- **GitHub review-submission permission limitation.** Connector submission of a formal Pull Request Review can fail with `403 Resource not accessible by integration` (not a silent downgrade). Preferred fallback is a formal `COMMENTED` review submitted through an authenticated browser session, which does satisfy review evidence; a PR Conversation comment is only a last-resort, incomplete status report and never counts as completed review evidence by itself (`docs/KNOWN_LIMITATIONS.md`).
- **Default branch is still a temporary `claude/*` name**, not `main` (TD-005); repository-maintenance cutover is a separate, not-yet-executed operation (`docs/REPOSITORY_STRATEGY.md`).

## Related documents

| Concern | Document |
|---|---|
| Stable, less volatile snapshot | `knowledge/PROJECT_MEMORY.md` |
| Full roadmap detail | `docs/ROADMAP.md` |
| Conceptual change history | `knowledge/CHANGE_HISTORY.md` |
| Per-decision rationale | `docs/DECISION_LOG.md` |
