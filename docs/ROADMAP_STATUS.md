# Roadmap Status

**Purpose:** Concise live status dashboard.
**Authority:** Status summary only. [`ROADMAP.md`](ROADMAP.md) and
[`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md)
control detailed ordering, scope, dependencies, and acceptance criteria.
**Update trigger:** A Roadmap item, design, implementation, or baseline changes.

## Current baseline

`ac19505` — squash commit of GitHub PR #61, the Roadmap PR16 (Slice 4)
Reporting Foundation frontend filter controls implementation, incl. the
PR61-H1 review fix. PR15A and PR15B are both implemented — both of Roadmap
PR15's scheduled slices are complete. Application metrics, tracing,
dashboards, log aggregation, and alerting remain open Roadmap PR15 scope,
not scheduled to any slice, pending a future slice or an explicit governance
decision to remove them. Roadmap PR16 (Reporting Foundation, all four
Implementation Slices — GitHub PR #58, #59, #60, #61) is now fully
complete. PR17 is the next planned item.

Roadmap numbering and GitHub PR numbering are independent. In particular,
GitHub PR #18 was the Knowledge & Governance Foundation; it was not Roadmap
PR18.

## Current and planned sequence

| Order | Roadmap item | Status |
|---|---|---|
| 1 | PR17 — Operational reports | Planned; next |
| 2 | PR18 — PDF/Excel export and print-ready Hard Copy templates | Planned |
| 3 | PR19 — Legacy Import Foundation | Planned |
| 4 | PR20 — Equipment Master Import | Planned |
| 5 | PR21 — Legacy Receive and Issue History Import | Planned |
| 6 | PR22 — Legacy Data Validation and Reconciliation | Planned |
| 7 | PR23 — Cutover Readiness | Planned |
| 8 | PR24 — Go-live / deployment | Planned; blocked by PR19–PR23 |

Roadmap PR15B (Schema Hygiene implementation, GitHub PR #54), the
documentation audit and Roadmap consistency work that preceded it
(GitHub PR #53, unnumbered governance change), and Roadmap PR16 (Reporting
Foundation, all four Implementation Slices — GitHub PR #58, #59, #60, #61)
are all complete and have moved off this table — see `docs/ROADMAP.md`'s
Completed table for the full historical record.

## Scope guardrails for the planned sequence

- Reporting distinguishes the actual transaction timestamp, `business_date`,
  and `shift`. `shift` is operational/reporting metadata, not an equipment
  lifecycle state. Do not create separate Day and Night transaction tables.
- Reports cover Receive, Issue, and Equipment Verify Checklist, filterable by
  date and shift, with PDF, Excel, and print-ready hard-copy output.
- Version 1 legacy history migration includes only the AppSheet equipment
  receive-data and equipment issue-data sheets. Equipment Verify Checklist
  history is excluded unless a later approved decision changes the scope.
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
