# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`4b0d422` on `claude/medical-equipment-pool-0c7fz0` — GitHub PR #52, the
approved documentation-only PR15B Schema Hygiene design. PR15A Observability is
implemented. PR15B implementation has not started.

## Current work

This documentation-only audit aligns the active Roadmap, status dashboard,
implementation plan, architecture decisions, and knowledge snapshots. It
changes no application code, migration, schema, API behavior, frontend
behavior, or business rule.

## Next sequence

1. PR15B — Schema Hygiene implementation.
2. PR16 — Reporting Foundation: actual timestamp, `business_date`, `shift`.
3. PR17 — Receive, Issue, and Equipment Verify Checklist reports.
4. PR18 — PDF, Excel, and print-ready Hard Copy output.
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
- PR16 must define exact shift values and `business_date` rollover rules.
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
