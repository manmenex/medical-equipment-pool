# Context

**Purpose:** Current project state — the most volatile document in the knowledge layer
**Authority:** Point-in-time status only. Does not restate rules or rationale — see `knowledge/PROJECT_MEMORY.md` for the stable snapshot this file assumes.
**Update trigger:** Every merged PR, and whenever a risk or outstanding item changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`f4146b380f2fe182516db386de328c2633f72a5f` — squash commit of the Knowledge & Governance Foundation PR (GitHub PR #18), on branch `claude/medical-equipment-pool-0c7fz0`.

## Current PR

**Roadmap PR7 — Transaction lifecycle model (7a slice)** — branch `feature/pr7-transaction-model`. Introduces `TransactionStatus` (`OPEN`/`CLOSED`) replacing the three-value `borrowed`/`returned`/`overdue` field, a `close()` repository function as the sole closer (mirroring `create()` as the sole opener), a `legacy_status` preservation column, and migration `0007_transaction_lifecycle.py`. The `due_at`-driven hourly overdue-notification scheduler job is fully disabled (removed, not deduplicated) — Codex PR7a review round 1 (BLOCKER) found it re-notified every OPEN overdue transaction on every tick with no de-duplication; the approved MVP business model has no due-date/overdue workflow at all. Does not touch `dispatch_type`, `routine_round`, `ward_id`-required, `borrower_name`/`due_at` removal, or the Equipment Status model. See `knowledge/adr/ADR-005-transaction-model.md`, `docs/DOMAIN_MODEL.md`, and `docs/DECISION_LOG.md`. Status: Draft, pending review, after one Codex REQUEST_CHANGES round.

## Next planned PR

**Roadmap PR7's remaining scope (7b slice)** — `dispatch_type`, `routine_round`, making `ward_id` required, and removing `borrower_name`/`due_at` from the write path — per `docs/audits/04-consolidated-implementation-plan.md` Part D and `docs/ROADMAP.md`, once this PR is merged. After that, Roadmap PR8 (Atomic Single-Operation Equipment Receipt).

## Outstanding work

- Roadmap PR7's remaining scope (7b slice, see above), and PR8 through PR15 (atomic receipt, ward correction, role consolidation, frontend terminology, inventory import, search/reporting, reliability/performance hardening, observability/schema hygiene) are planned and not started.
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
