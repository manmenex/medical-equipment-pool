# Context

**Purpose:** Current project state — the most volatile document in the knowledge layer
**Authority:** Point-in-time status only. Does not restate rules or rationale — see `knowledge/PROJECT_MEMORY.md` for the stable snapshot this file assumes.
**Update trigger:** Every merged PR, and whenever a risk or outstanding item changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`3a1d30b4560f77867dfe36e925c1f3ef97d71596` — squash commit of the CI/AI-review-workflow infrastructure PR (GitHub PR #17), on branch `claude/medical-equipment-pool-0c7fz0`.

## Current PR

**Knowledge & Governance Foundation** (referred to as Roadmap PR18 in the task that created it) — branch `docs/pr18-knowledge-governance-foundation`. Documentation and governance only: adds this `knowledge/` AI-memory layer and the `docs/PROJECT_WORKFLOW.md`, `BUSINESS_RULES.md`, `DECISION_LOG.md`, `ROADMAP.md`, `REVIEW_CHECKLIST.md`, `KNOWN_LIMITATIONS.md` documents; trims `AGENTS.md` to reference them; adds two invariants to the pre-existing `docs/ARCHITECTURE_GUARDRAILS.md`. No application code, migration, API, frontend, test, or CI file changed. Status: Draft, pending review.

## Next planned PR

**Roadmap PR7 — Dispatch Record Model** (`OPEN`/`CLOSED` states, dispatch type, routine round, field cleanup) is the next Roadmap PR per `docs/audits/04-consolidated-implementation-plan.md` Part D and `docs/ROADMAP.md`, once this governance PR is merged.

## Outstanding work

- Roadmap PR7 through PR15 (dispatch record model, atomic receipt, ward correction, role consolidation, frontend terminology, inventory import, search/reporting, reliability/performance hardening, observability/schema hygiene) are planned and not started.
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
