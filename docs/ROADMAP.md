# Roadmap

**Purpose:** Current-state snapshot of the Medical Equipment Pool Roadmap — what is merged, what is next, at the current baseline
**Authority:** Summary. `docs/audits/04-consolidated-implementation-plan.md` Part D remains authoritative for Roadmap PR scope, order, dependencies, and acceptance criteria. `docs/ROADMAP_STATUS.md` is superseded by this file (see the banner on that file).
**Update trigger:** A Roadmap PR merges, is added, is reordered, or the baseline changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`f4146b380f2fe182516db386de328c2633f72a5f` — squash commit of the Knowledge & Governance Foundation PR (GitHub PR #18), on branch `claude/medical-equipment-pool-0c7fz0`.

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

Full rationale and review-fix history for PR5 through the Knowledge & Governance Foundation PR: `docs/DECISION_LOG.md`.

## In progress

| Roadmap PR | Title | Status |
|---|---|---|
| PR7 (7a slice) | Transaction lifecycle model (OPEN/CLOSED) | Draft, pending review — see below |

**PR7 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR7 entry recommends splitting into a 7a (lifecycle model) and 7b (`dispatch_type`/`routine_round`/ward-required/field-cleanup) slice "if the reviewing team prefers smaller units." The row above is the 7a slice only — `TransactionStatus` (`OPEN`/`CLOSED`), the `create()`/`close()` mutator split, `legacy_status` preservation, and disabling the deprecated `due_at`-driven overdue-notification scheduler job (Codex PR7a review round 1, BLOCKER — see `docs/DECISION_LOG.md`). It does **not** implement `dispatch_type`, `routine_round`, a required `ward_id`, or removal of `borrower_name`/`due_at`; those remain planned below as PR7's remaining scope. Concurrent-receipt protection (two simultaneous receipts racing on the same OPEN transaction) is explicitly **not** in this slice — it stays Roadmap PR8's responsibility. See `knowledge/adr/ADR-005-transaction-model.md` and `docs/DECISION_LOG.md`.

## Planned (not yet started)

Per `docs/audits/04-consolidated-implementation-plan.md` Part D, except PR7's lifecycle slice noted above as in progress:

| Roadmap PR | Title |
|---|---|
| PR7 (7b slice) | Transaction fields: dispatch type, routine round, required ward_id, borrower_name/due_at removal |
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
| Domain entity structural reference | `docs/DOMAIN_MODEL.md` |
| Transaction lifecycle decision (PR7 7a slice) | `knowledge/adr/ADR-005-transaction-model.md` |
