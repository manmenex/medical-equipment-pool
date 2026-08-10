# Roadmap Status

**Purpose:** Concise live status dashboard.
**Authority:** Status summary only. [`ROADMAP.md`](ROADMAP.md) and
[`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md)
control detailed ordering, scope, dependencies, and acceptance criteria.
**Update trigger:** A Roadmap item, design, implementation, or baseline changes.

## Current baseline

`7f13a1e85e9b6a4828170c4b12bc2be27b15de39` — squash commit of GitHub PR
#86, the Roadmap PR19A3 implementation (Dry-run, Execution, Recovery,
Retention). It follows GitHub PR #85 (`7e5e6f2d`, Roadmap PR19A2 —
Validation Foundation) and GitHub PR #84 (`7d589860`, Roadmap PR19A1 —
Schema / Session / Source Foundation), both based on GitHub PR #83
(`38a21e8c`, the architecture-approved PR19A design). **All three of
PR19A's implementation slices are merged — Roadmap PR19A (Legacy Import
Foundation, backend) is now fully complete.** See "Roadmap PR19 split"
below for the full detail and for PR19B's still-open status. The older
baseline narrative immediately below (`729d1aa...`, PR18F) is retained as
provenance for Roadmap PR18 and earlier.

`729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` — squash commit of GitHub PR #79,
the documentation-only PR18F governance synchronization recording Roadmap
PR18's completion. It follows GitHub PR #78 (`5d8cf7d`, the merged Roadmap
PR18E Excel `.xlsx` export implementation), GitHub PR #77 (`bc274e6`, PR18D
backend PDF export), GitHub PR #76 (`beedc4d`,
the documentation-only governance sync after PR18C), GitHub PR #75
(`e919a2a`, PR18C Browser Print), GitHub PR #74 (`4da1ebc`, the
documentation-only governance sync after PR18B), GitHub PR #73 (`c72929b`,
PR18B backend export foundation), GitHub PR #72 (`e1b358a`, post-PR18A
governance synchronization), and GitHub PR #71 (`6ba2c66`, approved PR18A
architecture design). PR18E added the backend Excel adapter (openpyxl, no new
dependency) for all three PR17 reports over PR18B's bounded foundation, with
workbook-wide formula-injection protection and bounded concurrency/admission
control. It added no migration or equipment lifecycle change. PR15A and PR15B
are both implemented
— both of Roadmap PR15's scheduled slices are complete.
Application metrics, tracing, dashboards, log aggregation, and alerting
remain open Roadmap PR15 scope, not scheduled to any slice, pending a
future slice or an explicit governance decision to remove them. Roadmap
PR16 (Reporting Foundation, all four Implementation Slices — GitHub PR #58,
#59, #60, #61) and Roadmap PR17 (Operational Reports, design GitHub PR #63
plus all four Implementation Slices — GitHub PR #65, #66, #67, #68) are now
fully complete. **Roadmap PR18 (printing/export architecture, backend export
foundation, Browser Print, backend PDF export, and Excel `.xlsx` export — GitHub
PR #71, #73, #75, #77, #78, with governance-sync PRs #72, #74, #76, #79 interleaved
between/after them) is now fully complete.** Owner Decision #2 (branding
configuration ownership) remains open.

**Roadmap PR19 split (approved 2026-08-03):** Roadmap PR19 is delivered as
two independent-scope slices — **PR19A** (backend import framework) and
**PR19B** (frontend-only workflow-review skeleton, no real import) — per
`docs/DECISION_LOG.md` ("Roadmap PR19 approved split: PR19A (backend) /
PR19B (frontend skeleton)") — an explicit, Owner-approved exception, since
at the time of approval no PR19 design document existed. "Parallel"
describes scope/dependency independence only, not a shared implementation
baseline. **PR19A's architecture design merged as GitHub PR #83** (squash
SHA `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`, `docs/design/
PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`), branched directly from
`729d1aa...`; its implementation slices PR19A1/PR19A2/PR19A3 (design §25)
have since **all merged**: PR19A1 (schema, session/source lifecycle, CAS)
as GitHub PR #84, squash SHA `7d58986095c4df6a425dc9cfd8298851eee86c17`;
PR19A2 (validation foundation) as GitHub PR #85, squash SHA
`7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`; PR19A3 (dry-run, execution,
recovery, retention) as GitHub PR #86, squash SHA
`7f13a1e85e9b6a4828170c4b12bc2be27b15de39`. **PR19A (Legacy Import
Foundation, backend) is now fully complete** — the current authoritative
base-branch tip. No concrete legacy dataset import (Equipment Master,
Receive History, Issue History) is implemented by PR19A; that remains
future Roadmap PR20/PR21 scope. PR19B remains Draft PR #80
(`feature/pr19b-import-frontend-skeleton`), branched from `729d1aa...`
(the latest approved baseline when its branch was created), open and not
yet independently reviewed; it must be reconciled against PR19A's
now-merged authoritative contract before its own Exception Record can
close (`docs/DECISION_LOG.md`). GitHub PR #81, an earlier unsplit PR19A
candidate, was closed without merging, superseded by PR19A1/PR19A2/PR19A3.
**PR19A's implementation is complete; PR19B is not; Roadmap PR19 as a
whole is therefore not yet complete.**

Roadmap numbering and GitHub PR numbering are independent. In particular,
GitHub PR #18 was the Knowledge & Governance Foundation; it was not Roadmap
PR18.

## Current and planned sequence

| Order | Roadmap item | Status |
|---|---|---|
| 1 | PR19B — Legacy Import Frontend Skeleton (workflow-review prototype, no real import) | Draft PR #80 open, not merged; requires reconciliation against PR19A's now-merged contract (`docs/DECISION_LOG.md` Exception Record) before it can be accepted |
| 2 | PR20 — Equipment Master Import | Planned; sequencing relative to PR19B reconciliation/closure is a governance question, not yet an Owner Decision |
| 3 | PR21 — Legacy Receive and Issue History Import | Planned |
| 4 | PR22 — Legacy Data Validation and Reconciliation | Planned |
| 5 | PR23 — Cutover Readiness | Planned |
| 6 | PR24 — Go-live / deployment | Planned; blocked by PR19–PR23 |

Roadmap PR15B (Schema Hygiene implementation, GitHub PR #54), the
documentation audit and Roadmap consistency work that preceded it
(GitHub PR #53, unnumbered governance change), Roadmap PR16 (Reporting
Foundation, all four Implementation Slices — GitHub PR #58, #59, #60, #61),
and Roadmap PR17 (Operational Reports, design GitHub PR #63 plus all four
Implementation Slices — GitHub PR #65, #66, #67, #68) are all complete and
have moved off this table. **Roadmap PR18 (Printing and Export) is also now
fully complete and has moved off this table:** PR18A design (GitHub PR #71),
its governance sync (GitHub PR #72), PR18B backend export foundation (GitHub
PR #73), a governance sync recording PR18B's completion (GitHub PR #74),
PR18C Browser Print (GitHub PR #75), a governance sync recording PR18C's
completion (GitHub PR #76), PR18D backend PDF export (GitHub PR #77), and
PR18E Excel `.xlsx` export (GitHub PR #78) are all merged — see
`docs/ROADMAP.md`'s Completed table for the full historical record.
**Roadmap PR19A (Legacy Import Foundation, backend) is also now fully
complete and has moved off this table:** the architecture design (GitHub
PR #83) and its three implementation slices PR19A1 (GitHub PR #84), PR19A2
(GitHub PR #85), and PR19A3 (GitHub PR #86) are all merged — see
`docs/DECISION_LOG.md` ("Roadmap PR19A complete: PR19A1 + PR19A2 + PR19A3
merged") for the full slice-by-slice record. This table now begins with
PR19B, the only remaining unmerged part of the Roadmap PR19 split.

## Scope guardrails for the planned sequence

- Reporting distinguishes the actual transaction timestamp, `business_date`,
  and `shift`. `shift` is operational/reporting metadata, not an equipment
  lifecycle state. Do not create separate Day and Night transaction tables.
- Reports cover Receive, Issue, and Equipment Verify Checklist, filterable by
  date and shift, with PDF, Excel, and print-ready hard-copy output.
- Version 1 legacy history migration includes only the AppSheet equipment
  receive-data and equipment issue-data sheets. Equipment Verify Checklist
  history is excluded unless a later approved decision changes the scope.
- PR19B is a frontend-only workflow-review skeleton: no file upload, no
  parsing, no validation/dry-run/import execution, no database change. Its
  Equipment Master/Receive/Issue History category labels preview PR20/PR21
  scope and are not an implemented capability.
- PR20 Equipment Master Import covers BCM, Item Number, equipment attributes,
  existing hospital QR linkage, equipment duplicate detection, and
  equipment-record validation. It does not own transaction BME or Ward data.
- PR21 Legacy Receive and Issue History Import covers Receive and Issue
  history, legacy BME-name preservation and user mapping, Ward normalization
  and mapping, transaction-row duplicate detection, and transaction source
  references.
- PR22 Legacy Data Validation and Reconciliation covers cross-import
  validation, reconciliation, source traceability verification, duplicate
  review, and unified legacy/new history validation.
- Legacy migration occurs before Go-live and does not redesign or replace
  existing hospital QR codes.
- The only equipment lifecycle states remain `AVAILABLE_AT_POOL`,
  `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, and `DECOMMISSIONED`. Cleaning is
  not a state.

## Unscheduled confirmed work

- Standby Snapshots remain separate future work.
- Broader PR15 observability items (metrics, tracing, dashboards, centralized
  aggregation, and alerting) remain open until assigned to a focused slice or
  removed by an explicit governance decision.
- Create-from-import deferred from PR12 remains separate from the approved
  legacy migration sequence above.
