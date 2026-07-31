# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

Current baseline: `6ba2c666a11043d03669abdb65f966061dd02cfa` on
`claude/medical-equipment-pool-0c7fz0` — GitHub PR #71, the merged Roadmap
PR18A printing/export architecture design. It is based on GitHub PR #70
(`bc9e43b`, focused operator-options cursor-hygiene maintenance), GitHub PR
#69 (`9b2fc1a`, post-PR17 governance sync), and GitHub PR #68 (`d4aaf0f`,
Roadmap PR17 Slice 4). Roadmap PR17 (Operational Reports), Roadmap PR16
(Reporting Foundation), and Roadmap PR15B Schema Hygiene remain implemented.

## Current work

Roadmap PR18A is complete as a merged design document:
`docs/design/PR18_PRINTING_EXPORT_PLAN.md`. It is not runtime implementation.
No browser print UI, PDF generation, Excel generation, export routes, DTOs,
dependencies, migrations, API behavior, frontend behavior, or business rules
were implemented by PR #71.

## Next sequence

Roadmap PR17 (Operational Reports) is fully complete — Receive, Issue, and
Equipment Verify Checklist reports are all implemented, backend-owned for
eligibility/semantics/ordering, cursor-paginated, and Thai-first on the
frontend. Equipment Verify Checklist is a read-only, current-state Equipment
master-data snapshot (Owner Decision #1, resolved to interpretation A) — no
physical-verification workflow, no verification-event storage, no new
equipment lifecycle state. Roadmap PR18A design is merged. The next planned
implementation work is PR18B — the shared backend dataset and document model
slice for browser print/PDF/Excel output. PDF, Excel, and browser print are
not implemented yet.

1. PR18B — Shared backend dataset and document model.
2. PR18C — Browser print presentation.
3. PR18D — Backend PDF export.
4. PR18E — Excel `.xlsx` export.
5. PR18F — Post-implementation governance synchronization.
6. PR19 — Legacy Import Foundation.
7. PR20 — Equipment Master Import: BCM, Item Number, equipment attributes,
   existing hospital QR linkage, equipment duplicate detection, and
   equipment-record validation.
8. PR21 — AppSheet Receive and Issue history import: legacy BME-name
   preservation and user mapping, Ward normalization and mapping,
   transaction-row duplicate detection, and transaction source references.
9. PR22 — Validation and reconciliation: cross-import validation,
   reconciliation, source traceability verification, duplicate review, and
   unified legacy/new history validation.
10. PR23 — Cutover readiness.
11. PR24 — Go-live / deployment.

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
- PR18B must resolve or explicitly gate any behavior depending on PR18A's open
  Owner Decisions: export extent, branding configuration ownership, and maximum
  synchronous output size.
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
