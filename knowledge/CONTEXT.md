# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

Current baseline: `c802d66c9d1e5395cd20591c451ebdc0cefbf7df` on
`claude/medical-equipment-pool-0c7fz0` — the real squash-merge SHA of
GitHub PR #113, the post-PR22A governance synchronization (documentation-
only), squash-merged on top of `c924d8ba2c8c5d933ea36ea3d488e2550615df40`
(GitHub PR #112, Roadmap PR22A — Legacy Data Validation and
Reconciliation Architecture, design only). PR #113's final independently
reviewed feature-branch head was
`ec02ced43d649c8c813a458762f110b13eb5ab7d` (independent Final Merge
Gate: zero review threads, zero comments, CI green 6/6 on that exact
head) — **that reviewed head is not the baseline**; the squash commit
actually landed on the base branch, `c802d66...`, is, independently
verified tree-identical to that reviewed head with sole parent
`c924d8b...` confirmed. This baseline advances even though PR #113 is
documentation-only, consistent with this repository's squash-baseline
discipline: the authoritative baseline tracks the exact commit landed on
the base branch, not only commits that touch runtime code.

**Roadmap PR22 (Legacy Data Validation and Reconciliation)'s
architecture design is merged (GitHub PR #112, folded into this
baseline), and all seven Owner Decisions (OD-PR22-1 through OD-PR22-7)
are now RESOLVED / OWNER APPROVED**, recorded by the PR22 Owner Decision
Closure round. PR22 implementation is **still not started** — every
PR22B-G slice becomes eligible only once the governance PR recording
this closure round itself merges; **the next planned step is PR22B**.

`d64d50d09cdf8ed7ddc1f5116b38805dfcbc7810` (GitHub PR #110, Roadmap
PR21E — Legacy History Frontend Real Integration) is now historical,
superseded first by `e07a36a...` (GitHub PR #111, PR21F), then
`c924d8b...` (GitHub PR #112, PR22A), and now by this baseline. With
PR21E merged, **Roadmap PR21 (Legacy Receive and Issue History Import)
is now fully complete** — every implementation slice (Foundation, A, B,
C, D1, D2, E0, E) is merged. See `docs/DECISION_LOG.md` ("Roadmap PR21
complete: PR21D1–PR21F merged") for the closure record.

This baseline follows `78eeea7827c53443f34de9e516573c2ed7c59581` (GitHub
PR #109, PR21E0 — Legacy Import Operator API Surface), `c4788de06bed9a13aa5ec981fb8e19c67bc5720b`
(GitHub PR #108, PR21D2 — Historical Event Execution),
`50b9e77269b238d95fb34b28d0bc223a369951e2` (GitHub PR #107, PR21D1 —
Combined Canonical Adapter + Source Admission), and the earlier PR21A/B/C
and design/Owner Decision chain — see `docs/ROADMAP.md`'s Completed table
for every squash SHA. That chain in turn follows
`2743af849702ef551927b9c362421df08c80b5d9` (GitHub PR #96, Roadmap PR20F —
Equipment Master Import complete) and `04f5bf5c76b51744981d1cc8072c074e604224e9`
(GitHub PR #80, PR19B — now historical: its mock workflow has been fully
removed by PR21E). **Roadmap PR19, PR20, and PR21 are all now fully
complete.** Roadmap PR17 (Operational Reports), Roadmap PR16 (Reporting
Foundation), and Roadmap PR15B Schema Hygiene remain implemented.

Roadmap PR21 (Legacy Receive and Issue History Import) delivers the legacy
transaction-history import workflow end-to-end, as one combined
`legacy_transaction_history` workbook/session (not two separate Receive/
Issue imports): the `LegacyEquipmentEvent` schema/provenance foundation
(PR21A), canonical Issue/Receive parsers (PR21B/PR21C, SDC sheets excluded
from V1 by explicit Owner decision), the combined adapter and PR21-specific
upload allowance (PR21D1), historical event execution — `ISSUE`/`RECEIVE`
events, never `BorrowTransaction` rows, never Equipment lifecycle mutation
(PR21D2), the Administrator-only migration-authority approval API and
PR21-specific dry-run-plan HTTP surface (PR21E0), and real operator-facing
frontend integration replacing the PR19B mock workflow (PR21E). **PR21
does not pair Issue and Receive events, does not implement MEMS or Recall
Monitor, and does not perform cross-import reconciliation** — pairing and
reconciliation are Roadmap PR22-or-later's own scope. See
`docs/DECISION_LOG.md` ("Roadmap PR21 complete: PR21D1–PR21F merged") for
the full slice-by-slice record.

## Current work

Roadmap PR21 (Legacy Receive and Issue History Import) is now fully
complete — implementation (PR21-Foundation #100, PR21A #103, PR21B #104,
PR21C #105, PR21D1 #107, PR21D2 #108, PR21E0 #109, PR21E #110) and
governance closure (PR21F, GitHub PR #111, squash SHA
`e07a36aa8482b7b97368a6adb9cfcc81c93d0ee0`) are both merged. **Roadmap
PR22 (Legacy Data Validation and Reconciliation)'s architecture design
has merged** — `docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md`,
GitHub PR #112 (PR22A, three independent-review fix rounds folded in:
Owner Decision numbering/cross-reference sweep; the new §9.J temporal
coverage boundary and OD-PR22-7; the sign-off-ambiguity resolution
blocking all final sign-off until OD-PR22-7 resolves), squash SHA
`c924d8ba2c8c5d933ea36ea3d488e2550615df40`, sole parent `e07a36a...`
(PR21F). The post-PR22A governance synchronization (GitHub PR #113) has
since also merged — squash SHA `c802d66c9d1e5395cd20591c451ebdc0cefbf7df`
(see "Current baseline" above), docs-only. **All seven Owner Decisions
(OD-PR22-1 through OD-PR22-7) are now RESOLVED / OWNER APPROVED**,
recorded in the design document's own §36 by the PR22 Owner Decision
Closure round (the Owner approved all seven per Recommendation). No
`backend/**`, `frontend/**`, `alembic/**`, or `tests/**` file was touched
by the design, the governance sync, or this closure round. **Current
work is now PR22B** — the first implementation slice, eligible once the
governance PR recording this closure round itself merges; no other
PR22B-G slice may begin ahead of its own ordinary implementation
dependencies (e.g. PR22C depends on PR22B, PR22E depends on PR22D).

## Next sequence

Roadmap PR19, PR20 (Equipment Master Import), and PR21 (Legacy Receive
and Issue History Import) are all now fully complete. **Roadmap PR22
(Legacy Data Validation and Reconciliation)'s architecture design has
merged and all seven Owner Decisions are resolved (GitHub PR #112);
implementation has not started** — per `docs/audits/04-consolidated-implementation-plan.md`
Part D, PR22 depends on PR20 and PR21 (both now satisfied) and covers:
cross-import validation, reconciliation, source traceability
verification, duplicate review, and unified legacy/new history
validation, including Issue↔Receive pairing (deliberately deferred by
PR21's own event-first architecture, and resolved as a design-time Owner
Decision — OD-PR22-1 — by this closure round, never silently finalized).

1. PR19A — Legacy Import Foundation (backend) — **complete.**
2. PR19B — Legacy Import Frontend Skeleton — **complete, merged as GitHub
   PR #80; its mock workflow has since been fully removed by PR21E.**
3. PR20 — Equipment Master Import (PR20A–PR20F) — **complete**, merged as
   GitHub PR #90/#91/#93/#94/#95/#96 (design GitHub PR #89; governance
   syncs GitHub PR #88/#92).
4. PR21 — Legacy Receive and Issue History Import (Foundation, A, B, C,
   D1, D2, E0, E) — **complete**, merged as GitHub PR
   #100/#103/#104/#105/#107/#108/#109/#110 (design GitHub PR #98/#99;
   Owner Decision Closure rounds GitHub PR #101/#102/#106).
5. PR22 — Validation and reconciliation: cross-import validation,
   reconciliation, source traceability verification, duplicate review, and
   unified legacy/new history validation. **Architecture design merged
   (GitHub PR #112), all seven Owner Decisions resolved; implementation
   not started** — the next planned Roadmap item; next eligible slice is
   PR22B.
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
  merged).** **PR21's own design
  (`docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`, GitHub
  PR #98/#99) has since defined transaction BME-name/user and Ward
  mappings, event identity, and the SDC exclusion in full — all seven
  Owner Decisions (OD-PR21-0 through OD-PR21-6) are RESOLVED and
  implemented (PR21-Foundation/A/B/C/D1/D2/E0/E, all merged).** **PR22's
  own design (`docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md`,
  GitHub PR #112) has since named, scoped, and — via the PR22 Owner
  Decision Closure round — resolved cross-import validation,
  reconciliation ownership, and Issue↔Receive pairing policy: all seven
  Owner Decisions (OD-PR22-1 through OD-PR22-7) are RESOLVED / OWNER
  APPROVED. PR22 implementation is still not started; the next eligible
  slice is PR22B, once the governance PR recording this closure round
  merges.** PR23 must define cutover evidence. PR19B's
  category labels were a UI preview only and did not resolve any of
  this — PR20's and PR21's own implementations are what actually resolved
  it.
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
  (PR20A–PR20F, GitHub PR #90/#91/#93/#94/#95/#96), and Roadmap PR21
  (Legacy Receive and Issue History Import) has since fully completed too
  (PR21-Foundation/A/B/C/D1/D2/E0/E, GitHub PR
  #100/#103/#104/#105/#107/#108/#109/#110) — PR19B's own mock Receive/
  Issue workflow has been removed entirely by PR21E, and Roadmap PR22
  (Legacy Data Validation and Reconciliation) is now the next planned
  Roadmap item, not started.** GitHub PR #81, an earlier unsplit PR19A
  candidate, was closed without merging, superseded by
  PR19A1/PR19A2/PR19A3.
- Broader PR15 metrics/tracing/dashboards/aggregation/alerting work is still
  unscheduled.

## Related documents

- `docs/ROADMAP.md` — detailed order and scope.
- `docs/ROADMAP_STATUS.md` — concise status dashboard.
- `docs/DOCUMENTATION_AUDIT.md` — full documentation inventory.
- `knowledge/PROJECT_MEMORY.md` — stable current-state orientation.
- `knowledge/CHANGE_HISTORY.md` — conceptual history.
