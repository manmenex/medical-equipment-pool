# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

Current baseline: `e919a2af8cc7ca11ab72bee274cb70e76c27ce8a` on
`claude/medical-equipment-pool-0c7fz0` — GitHub PR #75, the merged Roadmap
PR18C Browser Print implementation. It follows GitHub PR #73 (`c72929b`, the
PR18B backend export foundation), GitHub PR #72 (`e1b358a`, the post-PR18A
governance synchronization), and GitHub PR #71 (`6ba2c66`, the approved PR18A
architecture design). Roadmap PR17 (Operational Reports), Roadmap PR16
(Reporting Foundation), and Roadmap PR15B Schema Hygiene remain implemented.

## Current work

Roadmap PR18A is complete as the merged architecture design in
`docs/design/PR18_PRINTING_EXPORT_PLAN.md`. Roadmap PR18B is also merged: the
repository now contains the shared output-neutral export document model,
bounded builders for all three PR17 reports, and internal
`GET /reports/{report_id}/print-data`. Roadmap PR18C is merged as well:
Browser Print is available for Receive Report, Issue Report, and Equipment
Verify Checklist through a dedicated Thai-first presentation over that same
foundation. PR18 remains incomplete. No PDF or Excel generation exists yet.

## Next sequence

Roadmap PR17 (Operational Reports) is fully complete — Receive, Issue, and
Equipment Verify Checklist reports are all implemented, backend-owned for
eligibility/semantics/ordering, cursor-paginated, and Thai-first on the
frontend. Equipment Verify Checklist is a read-only, current-state Equipment
master-data snapshot (Owner Decision #1, resolved to interpretation A) — no
physical-verification workflow, no verification-event storage, no new
equipment lifecycle state. Roadmap PR18A design, PR18B backend foundation, and
PR18C Browser Print are merged. The next planned implementation work is PR18D
Backend PDF Export. PDF and Excel are not implemented yet.

1. PR18D — Backend PDF export.
2. PR18E — Excel `.xlsx` export.
3. PR18F — Post-implementation governance synchronization.
4. PR19 — Legacy Import Foundation.
5. PR20 — Equipment Master Import: BCM, Item Number, equipment attributes,
   existing hospital QR linkage, equipment duplicate detection, and
   equipment-record validation.
6. PR21 — AppSheet Receive and Issue history import: legacy BME-name
   preservation and user mapping, Ward normalization and mapping,
   transaction-row duplicate detection, and transaction source references.
7. PR22 — Validation and reconciliation: cross-import validation,
   reconciliation, source traceability verification, duplicate review, and
   unified legacy/new history validation.
8. PR23 — Cutover readiness.
9. PR24 — Go-live / deployment.

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
- PR18D must select and validate a production-compatible PDF renderer and Thai
  font/deployment strategy without moving report semantics out of the backend.
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
