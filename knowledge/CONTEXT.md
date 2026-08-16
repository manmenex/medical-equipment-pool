# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

Current baseline: `2743af849702ef551927b9c362421df08c80b5d9` on
`claude/medical-equipment-pool-0c7fz0` — the real squash-merge SHA of
GitHub PR #96, Roadmap PR20F (Equipment Master Frontend Real API
Integration). PR20F's final independently reviewed feature-branch head was
`38c6d33c15ed13929392d0736b9accda0886fa2e` (independent incremental review:
no blocking/non-blocking finding remaining, CI green 6/6 on that exact
head) — **that reviewed head is not the baseline**; the squash commit
actually landed on the base branch, `2743af8...`, is. With PR20F merged,
**Roadmap PR20 (Equipment Master Import) is now fully complete** —
PR20A through PR20F, all six implementation slices, are merged. See
`docs/DECISION_LOG.md` ("Roadmap PR20 complete: PR20A–PR20F merged") for
the closure record.

This baseline follows `698c34d9c280b2ca2ea4f299bd186517c9fb26a8` — GitHub
PR #95, Roadmap PR20E (execute() — CREATE/UPDATE mutation), which follows
GitHub PR #94 (`c72baa1`, Roadmap PR20D, persisted immutable DryRunPlan),
GitHub PR #93 (`1d04672`, Roadmap PR20C, parse/normalize/validate
adapter), GitHub PR #92 (`120319a`, the documentation-only PR20 Owner
Decisions OD-1–OD-4 resolution), GitHub PR #91 (`bd47701`, Roadmap PR20B,
`Equipment.version` optimistic-concurrency column), GitHub PR #90
(`1de3db1`, Roadmap PR20A, source artifact infrastructure), GitHub PR #89
(`9c2342a`, the architecture-approved PR20 design,
`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`), and GitHub PR #88
(`e3156bf`, the documentation-only governance sync recording Roadmap
PR19's completion), which in turn is based on `04f5bf5c76b51744981d1cc8072c074e604224e9`
— GitHub PR #80, the Roadmap PR19B implementation (Legacy Import Frontend
Skeleton), now historical for current-state purposes. **Both slices of
Roadmap PR19 (PR19A backend, PR19B frontend skeleton) remain fully
complete**, unaffected by PR20's completion. Roadmap PR17 (Operational
Reports), Roadmap PR16 (Reporting Foundation), and Roadmap PR15B Schema
Hygiene remain implemented.

Roadmap PR20 (Equipment Master Import) delivers the legacy Equipment
Master import workflow end-to-end: source artifact registration/upload
(PR20A), `Equipment.version` optimistic concurrency (PR20B), authoritative
XLSX parse/normalize/validate (PR20C, per Owner Decisions OD-1–OD-4, all
RESOLVED), persisted immutable `DryRunPlan` generation and confirmation
(PR20D), confirmed-plan execution with CREATE/UPDATE mutation and full
concurrency/fencing/recovery protection (PR20E), and real operator-facing
frontend integration replacing the PR19B mock workflow (PR20F). **PR20
does not implement Receive History import, Issue History import, PR21, MEMS,
or Recall Monitor** — those remain future Roadmap PR21+ scope, not started
by PR20's completion. See `docs/DECISION_LOG.md` ("Roadmap PR20 complete:
PR20A–PR20F merged") for the full slice-by-slice record.

## Current work

Roadmap PR20 (Equipment Master Import) is now fully complete — PR20A
(source artifact infrastructure, GitHub PR #90), PR20B (`Equipment.version`,
GitHub PR #91), PR20C (parse/normalize/validate, GitHub PR #93), PR20D
(persisted DryRunPlan, GitHub PR #94), PR20E (execute, GitHub PR #95), and
PR20F (frontend real API integration, GitHub PR #96) are all merged. This
post-PR20 governance synchronization records that completion and
establishes `2743af8...` as the current baseline; it changes no runtime
behavior — no backend, frontend, migration, or CI file is touched by this
documentation-only sync.

## Next sequence

Roadmap PR19 (Legacy Import Foundation, backend + frontend skeleton) and
Roadmap PR20 (Equipment Master Import) are both now fully complete.
**Roadmap PR21 (Legacy Receive and Issue History Import) is the next
planned Roadmap item, not started** — per
`docs/audits/04-consolidated-implementation-plan.md` Part D, PR21 depends
on PR19A and PR20 (both now satisfied) and covers: importing the AppSheet
equipment receive-data and equipment issue-data sheets; preserving legacy
BME names for later user mapping; normalizing and mapping Ward values;
detecting duplicate transaction rows; and retaining transaction source
references. PR20 does not implement any part of PR21's scope — Equipment
Master import (BCM, Item Number, equipment attributes, hospital QR
linkage, equipment duplicate detection, equipment-record validation) is
PR20's own, separate, now-complete scope.

1. PR19A — Legacy Import Foundation (backend) — **complete.**
2. PR19B — Legacy Import Frontend Skeleton — **complete, merged as GitHub
   PR #80.**
3. PR20 — Equipment Master Import (PR20A–PR20F) — **complete**, merged as
   GitHub PR #90/#91/#93/#94/#95/#96 (design GitHub PR #89; governance
   syncs GitHub PR #88/#92).
4. PR21 — AppSheet Receive and Issue history import: legacy BME-name
   preservation and user mapping, Ward normalization and mapping,
   transaction-row duplicate detection, and transaction source references.
   **Not started** — the next planned Roadmap item.
5. PR22 — Validation and reconciliation: cross-import validation,
   reconciliation, source traceability verification, duplicate review, and
   unified legacy/new history validation.
6. PR23 — Cutover readiness.
7. PR24 — Go-live / deployment.

Legacy migration and reconciliation are mandatory before PR24.

## Current scope boundaries

- Product: Medical Equipment Pool, not MEMS or Recall Monitor.
- States: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`,
  `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`; cleaning is not a state.
- Shift: reporting/operational metadata in one model, not separate Day/Night
  tables and not a lifecycle state.
- Version 1 legacy history: equipment receive-data and equipment issue-data
  sheets only; Equipment Verify Checklist history excluded.
- QR: preserve existing hospital QR codes; do not redesign the QR system.
- Rules: backend/service/API authorities own business behavior; frontend gates
  are usability only.

## Current risks and unresolved design details

- Branch protection is not enabled; required CI remains a documented manual
  merge gate.
- The default branch still has a temporary `claude/*` name.
- PR18A Owner Decisions #1 and #3 are resolved and implemented by PR18B: all
  matching filtered rows are included up to the 5,000-row synchronous bound.
  **Owner Decision #2 (branding configuration ownership) remains open** — no
  PR18 output format (Browser Print, PDF, or Excel) resolved it; every format
  uses the same interim neutral fallback, and it must be resolved before any
  future work depends on real hospital branding.
- PR19A's design (GitHub PR #83) defines the import framework and source
  mappings; **PR20's own design (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`,
  GitHub PR #89) has since defined Equipment Master matching/validation in
  full — Owner Decisions OD-1 (source schema), OD-2 (create/update field
  policy), OD-3 (BCM/Item Number identity policy), and OD-4 (CREATE Asset
  Number policy) are all RESOLVED and implemented (PR20A–PR20F, all
  merged).** PR21 must still define transaction BME-name/user and Ward
  mappings; PR22 must define cross-import validation and reconciliation
  ownership; PR23 must define cutover evidence. PR19B's category labels
  were a UI preview only and did not resolve any of this — PR20's own
  implementation is what actually resolved it.
- PR19's approved PR19A/PR19B split (`docs/DECISION_LOG.md`, 2026-08-03) was
  an explicit Owner-approved exception to this repository's usual
  design-document-first slice precedent, since at the time no PR19 design
  document existed. PR19A's architecture design merged (GitHub PR #83), and
  all three of PR19A's own implementation slices have since merged too —
  PR19A1 (GitHub PR #84), PR19A2 (GitHub PR #85), PR19A3 (GitHub PR #86).
  **PR19A is fully complete.** PR19B's types/mock client were realigned to
  PR19A's authoritative contract, independently reviewed across three
  rounds (findings PR80-H1, PR80-H2, PR80-H1R, all resolved), and merged as
  GitHub PR #80 (squash SHA `04f5bf5c76b51744981d1cc8072c074e604224e9`).
  **PR19B is fully complete; Roadmap PR19 as a whole is now fully complete,
  and the Exception Record governing this split (`docs/DECISION_LOG.md`)
  is closed.** Before PR19B merged, a separate question of relative work
  sequencing (never a hard dependency — PR20 has only ever depended on
  PR19A) between PR19B and PR20 had not been fixed by an Owner Decision;
  PR19B has since merged, which settles which of the two came first
  without a new Owner Decision. **PR20 has since also fully completed
  (PR20A–PR20F, GitHub PR #90/#91/#93/#94/#95/#96) — Roadmap PR21 (Legacy
  Receive and Issue History Import) is now the next planned Roadmap item,
  not started.** GitHub PR #81, an earlier unsplit PR19A candidate,
  was closed without merging, superseded by PR19A1/PR19A2/PR19A3.
- Broader PR15 metrics/tracing/dashboards/aggregation/alerting work is still
  unscheduled.

## Related documents

- `docs/ROADMAP.md` — detailed order and scope.
- `docs/ROADMAP_STATUS.md` — concise status dashboard.
- `docs/DOCUMENTATION_AUDIT.md` — full documentation inventory.
- `knowledge/PROJECT_MEMORY.md` — stable current-state orientation.
- `knowledge/CHANGE_HISTORY.md` — conceptual history.
