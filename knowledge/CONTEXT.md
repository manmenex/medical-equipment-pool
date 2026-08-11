# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

Current baseline: `04f5bf5c76b51744981d1cc8072c074e604224e9` on
`claude/medical-equipment-pool-0c7fz0` — the real squash-merge SHA of
GitHub PR #80, Roadmap PR19B (Legacy Import Frontend Skeleton). PR19B's
final independently reviewed feature-branch head was
`5edf1bfd8de7013eb74f300193456c9e5c0f0332` (**APPROVE**, CI green 6/6) —
**that reviewed head is not the baseline**; the squash commit actually
landed on the base branch, `04f5bf5c...`, is. With PR19B merged, both
slices of Roadmap PR19 — PR19A (backend: PR19A1 #84, PR19A2 #85, PR19A3
#86, all merged) and PR19B (frontend skeleton: #80, merged) — are
complete. **Roadmap PR19 (Legacy Import Foundation, backend + frontend
skeleton) is now fully complete.** See `docs/DECISION_LOG.md` ("Roadmap
PR19B merged: Exception Record closed; Roadmap PR19 fully complete") for
the closure record.

This baseline follows `7f13a1e85e9b6a4828170c4b12bc2be27b15de39` — GitHub
PR #86, the Roadmap PR19A3 implementation (Dry-run, Execution, Recovery,
Retention), which follows GitHub PR #85 (`7e5e6f2d`, Roadmap PR19A2,
Validation Foundation) and GitHub PR #84 (`7d589860`, Roadmap PR19A1,
Schema / Session / Source Foundation), both based on GitHub PR #83
(`38a21e8c`, the architecture-approved PR19A design), which in turn is
based on `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` — GitHub PR #79, the
documentation-only PR18F governance synchronization recording Roadmap
PR18's completion — which follows GitHub PR #78 (`5d8cf7d`, the merged
Roadmap PR18E Excel `.xlsx` export implementation), GitHub PR #77
(`bc274e6`, the PR18D backend PDF export), GitHub PR #76 (`beedc4d`, the
documentation-only governance sync after PR18C), GitHub PR #75
(`e919a2a`, the PR18C Browser Print implementation), GitHub PR #74
(`4da1ebc`, the documentation-only governance sync after PR18B), GitHub PR
#73 (`c72929b`, the PR18B backend export foundation), GitHub PR #72
(`e1b358a`, the post-PR18A governance synchronization), and GitHub PR #71
(`6ba2c66`, the approved PR18A architecture design). Roadmap PR17
(Operational Reports), Roadmap PR16 (Reporting Foundation), and Roadmap
PR15B Schema Hygiene remain implemented.

Roadmap PR19 was approved (`docs/DECISION_LOG.md`, 2026-08-03 entry) as an
independent-scope **PR19A** (backend) / **PR19B** (frontend skeleton)
split — not a shared implementation baseline. **PR19A's architecture
design merged as GitHub PR #83** (squash SHA
`38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`); its implementation slices
**all merged**: PR19A1 (schema, session/source lifecycle, CAS) as GitHub
PR #84, squash SHA `7d58986095c4df6a425dc9cfd8298851eee86c17`; PR19A2
(validation foundation) as GitHub PR #85, squash SHA
`7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`; PR19A3 (dry-run, execution,
recovery, retention) as GitHub PR #86, squash SHA
`7f13a1e85e9b6a4828170c4b12bc2be27b15de39`. **PR19B has since merged too:**
after three independent-review rounds (reconciliation head
`71dc97df583f60c3e9f8bccbbcb2e72b0b7307d5` REQUEST CHANGES on PR80-H1/H2;
fix head `6139bd4abd44c0a4ac07bf6ac63bf1b897dad653` REQUEST CHANGES on
remaining finding PR80-H1R; final head
`5edf1bfd8de7013eb74f300193456c9e5c0f0332` APPROVE, CI 6/6), PR19B merged
as GitHub PR #80, squash SHA `04f5bf5c76b51744981d1cc8072c074e604224e9`.
**Both PR19A and PR19B are complete; Roadmap PR19 as a whole is now fully
complete.** No concrete legacy dataset import (Equipment Master, Receive
History, Issue History) is implemented by either slice; that remains
future Roadmap PR20/PR21 scope, not yet started. GitHub PR #81, an earlier
unsplit PR19A candidate, was closed without merging, superseded by
PR19A1/PR19A2/PR19A3.

## Current work

Roadmap PR18A is complete as the merged architecture design in
`docs/design/PR18_PRINTING_EXPORT_PLAN.md`. Roadmap PR18B is also merged: the
repository now contains the shared output-neutral export document model,
bounded builders for all three PR17 reports, and internal
`GET /reports/{report_id}/print-data`. Roadmap PR18C, PR18D, and PR18E are
merged as well: Browser Print, backend PDF export, and backend Excel `.xlsx`
export are all available for Receive Report, Issue Report, and Equipment
Verify Checklist through dedicated adapters over that same foundation.
**Roadmap PR18 (Printing and Export) is now fully complete.** The
documentation-only PR18F synchronization recorded that completion; it
changed no runtime behavior. Roadmap PR19 has since also fully completed —
PR19A (backend, GitHub PR #83/#84/#85/#86) and PR19B (frontend skeleton,
GitHub PR #80, squash SHA `04f5bf5c76b51744981d1cc8072c074e604224e9`) are
both merged. This post-PR19B governance synchronization records that
completion, closes the Exception Record governing the PR19A/PR19B split,
and establishes `04f5bf5c...` as the current baseline; it likewise changes
no runtime behavior — no backend, frontend, migration, or CI file is
touched by this documentation-only sync.

## Next sequence

Roadmap PR17 (Operational Reports) is fully complete — Receive, Issue, and
Equipment Verify Checklist reports are all implemented, backend-owned for
eligibility/semantics/ordering, cursor-paginated, and Thai-first on the
frontend. Equipment Verify Checklist is a read-only, current-state Equipment
master-data snapshot (Owner Decision #1, resolved to interpretation A) — no
physical-verification workflow, no verification-event storage, no new
equipment lifecycle state. **Roadmap PR18 (design, backend foundation,
Browser Print, backend PDF export, and Excel `.xlsx` export) is fully
complete.** Roadmap PR19, approved (2026-08-03, `docs/DECISION_LOG.md`) as
a parallel split — **PR19A** (Legacy Import Foundation, backend) and
**PR19B** (Legacy Import Frontend Skeleton, a frontend-only
workflow-review prototype with no real upload, parsing, validation,
dry-run, or import execution) — is now **fully complete on both halves**:
PR19A's architecture design merged as GitHub PR #83, all three of its
implementation slices merged — PR19A1 (GitHub PR #84), PR19A2 (GitHub PR
#85), PR19A3 (GitHub PR #86) — and PR19B merged as GitHub PR #80 (squash
SHA `04f5bf5c76b51744981d1cc8072c074e604224e9`) after three
independent-review rounds resolved findings PR80-H1, PR80-H2, and
PR80-H1R, with the final reviewed head
(`5edf1bfd8de7013eb74f300193456c9e5c0f0332`) receiving APPROVE and CI
green (6/6). **Roadmap PR19 (Legacy Import Foundation, backend + frontend
skeleton) is now fully complete.** No concrete legacy dataset import
(Equipment Master, Receive History, Issue History) is implemented by
either slice — that remains future Roadmap PR20/PR21 scope, not yet
started. GitHub PR #81, an earlier unsplit PR19A candidate, was closed
without merging. PR20 depends on PR19A only, not PR19B
(`docs/audits/04-consolidated-implementation-plan.md`); a separate,
still-unresolved question of relative sequencing between PR19B and PR20
was left TBD pending an Owner Decision while PR19B was provisional and
remains open — this governance sync does not resolve it or start PR20.

1. PR19A — Legacy Import Foundation (backend) — **complete.**
2. PR19B — Legacy Import Frontend Skeleton (workflow-review prototype
   only) — **complete, merged as GitHub PR #80.**
3. PR20 — Equipment Master Import: BCM, Item Number, equipment attributes,
   existing hospital QR linkage, equipment duplicate detection, and
   equipment-record validation. **Not started** — the next planned
   Roadmap item.
4. PR21 — AppSheet Receive and Issue history import: legacy BME-name
   preservation and user mapping, Ward normalization and mapping,
   transaction-row duplicate detection, and transaction source references.
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
  mappings; PR20 must define Equipment Master matching/validation; PR21 must
  define transaction BME-name/user and Ward mappings; PR22 must define
  cross-import validation and reconciliation ownership; PR23 must define
  cutover evidence. PR19B's category labels are a UI preview only and do not
  resolve any of this.
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
  is closed.** A separate, still-unresolved question of relative sequencing
  between PR19B and PR20 was left TBD pending an Owner Decision while
  PR19B was provisional and remains open; PR20 has only ever depended on
  PR19A, so PR19B's merge does not change PR20's own readiness, and this
  governance sync does not resolve the sequencing question or start PR20.
  GitHub PR #81, an earlier unsplit PR19A candidate, was closed without
  merging, superseded by PR19A1/PR19A2/PR19A3.
- Broader PR15 metrics/tracing/dashboards/aggregation/alerting work is still
  unscheduled.

## Related documents

- `docs/ROADMAP.md` — detailed order and scope.
- `docs/ROADMAP_STATUS.md` — concise status dashboard.
- `docs/DOCUMENTATION_AUDIT.md` — full documentation inventory.
- `knowledge/PROJECT_MEMORY.md` — stable current-state orientation.
- `knowledge/CHANGE_HISTORY.md` — conceptual history.
