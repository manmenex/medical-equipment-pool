# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

Current baseline: `c72929ba4649fd75d1f81e4630b4e4feb3d136be` on
`claude/medical-equipment-pool-0c7fz0` — GitHub PR #73, the merged Roadmap
PR18B backend export foundation. It follows GitHub PR #72 (`e1b358a`, the
post-PR18A governance synchronization) and GitHub PR #71 (`6ba2c66`, the
approved PR18A architecture design). Roadmap PR17 (Operational Reports),
Roadmap PR16 (Reporting Foundation), and Roadmap PR15B Schema Hygiene remain
implemented.

## Current work

Roadmap PR18A is complete as the merged architecture design in
`docs/design/PR18_PRINTING_EXPORT_PLAN.md`. Roadmap PR18B is also merged: the
repository now contains the shared output-neutral export document model,
bounded builders for all three PR17 reports, and internal
`GET /reports/{report_id}/print-data`. PR18 remains incomplete. No Browser
Print UI, PDF generation, or Excel generation exists yet.

## Next sequence

Roadmap PR17 (Operational Reports) is fully complete — Receive, Issue, and
Equipment Verify Checklist reports are all implemented, backend-owned for
eligibility/semantics/ordering, cursor-paginated, and Thai-first on the
frontend. Equipment Verify Checklist is a read-only, current-state Equipment
master-data snapshot (Owner Decision #1, resolved to interpretation A) — no
physical-verification workflow, no verification-event storage, no new
equipment lifecycle state. Roadmap PR18A design and PR18B backend foundation
are merged. The next planned implementation work is PR18C Browser Print. PDF,
Excel, and Browser Print are not implemented yet.

1. PR18C — Browser print presentation.
2. PR18D — Backend PDF export.
3. PR18E — Excel `.xlsx` export.
4. PR18F — Post-implementation governance synchronization.
5. PR19 — Legacy Import Foundation.
6. PR20 — Equipment Master Import: BCM, Item Number, equipment attributes,
   existing hospital QR linkage, equipment duplicate detection, and
   equipment-record validation.
7. PR21 — AppSheet Receive and Issue history import: legacy BME-name
   preservation and user mapping, Ward normalization and mapping,
   transaction-row duplicate detection, and transaction source references.
8. PR22 — Validation and reconciliation: cross-import validation,
   reconciliation, source traceability verification, duplicate review, and
   unified legacy/new history validation.
9. PR23 — Cutover readiness.
10. PR24 — Go-live / deployment.

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
  Owner Decision #2 (branding configuration ownership) remains open and must
  be resolved before a future slice depends on it.
- PR18C must provide the approved Thai-capable browser-print presentation
  without moving report filtering, ordering, or other business semantics into
  the frontend.
- PR19 must define the import framework and source mappings; PR20 must define
  Equipment Master matching/validation; PR21 must define transaction
  BME-name/user and Ward mappings; PR22 must define cross-import validation
  and reconciliation ownership; PR23 must define cutover evidence.
- Broader PR15 metrics/tracing/dashboards/aggregation/alerting work is still
  unscheduled.

## Related documents

- `docs/ROADMAP.md` — detailed order and scope.
- `docs/ROADMAP_STATUS.md` — concise status dashboard.
- `docs/DOCUMENTATION_AUDIT.md` — full documentation inventory.
- `knowledge/PROJECT_MEMORY.md` — stable current-state orientation.
- `knowledge/CHANGE_HISTORY.md` — conceptual history.
