# Roadmap

**Purpose:** Current-state snapshot of the Medical Equipment Pool Roadmap — what is merged, what is next, at the current baseline
**Authority:** Summary. `docs/audits/04-consolidated-implementation-plan.md` Part D remains authoritative for Roadmap PR scope, order, dependencies, and acceptance criteria. `docs/ROADMAP_STATUS.md` is superseded by this file (see the banner on that file).
**Update trigger:** A Roadmap PR merges, is added, is reordered, or the baseline changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`3a1d30b4560f77867dfe36e925c1f3ef97d71596` — squash commit of the CI/AI-review-workflow infrastructure PR (GitHub PR #17), on branch `claude/medical-equipment-pool-0c7fz0`.

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

Full rationale and review-fix history for PR5 through the CI infrastructure PR: `docs/DECISION_LOG.md`.

## In progress

| Roadmap PR | Title | Status |
|---|---|---|
| — (governance) | Knowledge & Governance Foundation (this PR) | Draft, pending review |

## Planned (not yet started)

Per `docs/audits/04-consolidated-implementation-plan.md` Part D, unchanged:

| Roadmap PR | Title |
|---|---|
| PR7 | Dispatch Record Model (OPEN/CLOSED, dispatch type, routine round, field cleanup) |
| PR8 | Atomic Single-Operation Equipment Receipt with concurrency guard |
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
