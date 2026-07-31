# Roadmap Status

**Purpose:** Concise live status dashboard.
**Authority:** Status summary only. [`ROADMAP.md`](ROADMAP.md) and
[`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md)
control detailed ordering, scope, dependencies, and acceptance criteria.
**Update trigger:** A Roadmap item, design, implementation, or baseline changes.

## Current baseline

`6ba2c666a11043d03669abdb65f966061dd02cfa` — squash commit of GitHub PR
#71, the approved Roadmap PR18A printing/export architecture design. GitHub PR
#70 (`bc9e43b`) previously closed the operator-options cursor-hygiene
maintenance gap. GitHub PR #69 (`9b2fc1a`) completed the post-PR17 governance
synchronization. PR #71 added documentation only: no PR18 route, DTO,
dependency, PDF, Excel, browser-print UI, API behavior, or database schema was
implemented. PR15A and PR15B are both implemented — both of Roadmap PR15's
scheduled slices are complete.
Application metrics, tracing, dashboards, log aggregation, and alerting
remain open Roadmap PR15 scope, not scheduled to any slice, pending a
future slice or an explicit governance decision to remove them. Roadmap
PR16 (Reporting Foundation, all four Implementation Slices — GitHub PR #58,
#59, #60, #61) and Roadmap PR17 (Operational Reports, design GitHub PR #63
plus all four Implementation Slices — GitHub PR #65, #66, #67, #68) are now
fully complete. Roadmap PR18A printing/export architecture is merged and
approved as documentation-only design work. No PR18 runtime implementation
exists yet; PR18B is the next implementation slice.

Roadmap numbering and GitHub PR numbering are independent. In particular,
GitHub PR #18 was the Knowledge & Governance Foundation; it was not Roadmap
PR18.

## Current and planned sequence

| Order | Roadmap item | Status |
|---|---|---|
| 1 | PR18B — Shared backend dataset and document model | Next implementation; no output format implemented yet |
| 2 | PR18C — Browser print presentation | Planned; blocked by PR18B |
| 3 | PR18D — Backend PDF export | Planned; blocked by PR18B |
| 4 | PR18E — Excel `.xlsx` export | Planned; blocked by PR18B |
| 5 | PR18F — Post-implementation governance synchronization | Planned after all approved PR18 output slices merge |
| 6 | PR19 — Legacy Import Foundation | Planned |
| 7 | PR20 — Equipment Master Import | Planned |
| 8 | PR21 — Legacy Receive and Issue History Import | Planned |
| 9 | PR22 — Legacy Data Validation and Reconciliation | Planned |
| 10 | PR23 — Cutover Readiness | Planned |
| 11 | PR24 — Go-live / deployment | Planned; blocked by PR19–PR23 |

Roadmap PR15B (Schema Hygiene implementation, GitHub PR #54), the
documentation audit and Roadmap consistency work that preceded it
(GitHub PR #53, unnumbered governance change), Roadmap PR16 (Reporting
Foundation, all four Implementation Slices — GitHub PR #58, #59, #60, #61),
and Roadmap PR17 (Operational Reports, design GitHub PR #63 plus all four
Implementation Slices — GitHub PR #65, #66, #67, #68) are all complete and
have moved off this table. Roadmap PR18A design (GitHub PR #71) is also
merged, but Roadmap PR18 implementation remains on this table beginning with
PR18B — see `docs/ROADMAP.md`'s Completed table for the full historical
record.

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
