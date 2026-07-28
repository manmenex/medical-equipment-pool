# Roadmap Status

**Purpose:** Concise live status dashboard.
**Authority:** Status summary only. [`ROADMAP.md`](ROADMAP.md) and
[`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md)
control detailed ordering, scope, dependencies, and acceptance criteria.
**Update trigger:** A Roadmap item, design, implementation, or baseline changes.

## Current baseline

`4b0d422` — GitHub PR #52, the approved documentation-only design for Roadmap
PR15B Schema Hygiene. PR15A is implemented; PR15B implementation has not
started.

Roadmap numbering and GitHub PR numbering are independent. In particular,
GitHub PR #18 was the Knowledge & Governance Foundation; it was not Roadmap
PR18.

## Current and planned sequence

| Order | Roadmap item | Status |
|---|---|---|
| 1 | PR15B — Schema Hygiene implementation | Design approved; implementation not started |
| 2 | PR16 — Reporting Foundation and transaction reporting metadata | Planned |
| 3 | PR17 — Operational reports | Planned |
| 4 | PR18 — PDF/Excel export and print-ready Hard Copy templates | Planned |
| 5 | PR19 — Legacy Import Foundation | Planned |
| 6 | PR20 — Equipment Master Import | Planned |
| 7 | PR21 — Legacy Receive and Issue History Import | Planned |
| 8 | PR22 — Legacy Data Validation and Reconciliation | Planned |
| 9 | PR23 — Cutover Readiness | Planned |
| 10 | PR24 — Go-live / deployment | Planned; blocked by PR19–PR23 |

The documentation audit and Roadmap consistency work is an unnumbered
governance change between the approved PR15B design and subsequent
implementation. It does not consume or renumber a Roadmap PR.

## Scope guardrails for the planned sequence

- Reporting distinguishes the actual transaction timestamp, `business_date`,
  and `shift`. `shift` is operational/reporting metadata, not an equipment
  lifecycle state. Do not create separate Day and Night transaction tables.
- Reports cover Receive, Issue, and Equipment Verify Checklist, filterable by
  date and shift, with PDF, Excel, and print-ready hard-copy output.
- Version 1 legacy history migration includes only the AppSheet equipment
  receive-data and equipment issue-data sheets. Equipment Verify Checklist
  history is excluded unless a later approved decision changes the scope.
- Migration covers Equipment Master and supports BCM and Item Number matching,
  existing hospital QR codes, BME-name preservation/later user mapping, Ward
  normalization, duplicate detection, source traceability, import validation,
  reconciliation, and unified display of old and new history.
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
