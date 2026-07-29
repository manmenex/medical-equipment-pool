# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

Current baseline: `ac19505d9d0a102dcbec7bdfd4d1855554f1cf81` on
`claude/medical-equipment-pool-0c7fz0` — Roadmap PR16 (Reporting Foundation)
completed through GitHub PR #61, squash SHA `ac19505` (GitHub PR #58 `e8ef4da`,
#59 `bd4a02b`, #60 `6a28d73`, #61 `ac19505`). Roadmap PR15B Schema Hygiene
(GitHub PR #54) and both scheduled Roadmap PR15 slices remain implemented.

## Current work

GitHub PR #62 is a documentation/governance post-merge baseline sync for
Roadmap PR16 (all four Implementation Slices). It is not a Roadmap
implementation PR and changes no application code, migration, schema, API
behavior, frontend behavior, or business rule.

## Next sequence

Roadmap PR16 (Reporting Foundation) is fully complete — `business_date`/
`shift` are computed (never persisted) and `GET /transactions` plus
`EquipmentDetailPage.tsx` both support `business_date_from`/`business_date_to`/
`shift`/`event` filtering. The next planned work is Roadmap PR17 — Receive,
Issue, and Equipment Verify Checklist reports.

1. PR17 — Receive, Issue, and Equipment Verify Checklist reports.
2. PR18 — PDF, Excel, and print-ready Hard Copy output.
3. PR19 — Legacy Import Foundation.
4. PR20 — Equipment Master Import: BCM, Item Number, equipment attributes,
   existing hospital QR linkage, equipment duplicate detection, and
   equipment-record validation.
5. PR21 — AppSheet Receive and Issue history import: legacy BME-name
   preservation and user mapping, Ward normalization and mapping,
   transaction-row duplicate detection, and transaction source references.
6. PR22 — Validation and reconciliation: cross-import validation,
   reconciliation, source traceability verification, duplicate review, and
   unified legacy/new history validation.
7. PR23 — Cutover readiness.
8. PR24 — Go-live / deployment.

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
