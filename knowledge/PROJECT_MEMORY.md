# Project Memory (AI Snapshot)

**Purpose:** Stable current-state orientation for a new session
**Authority:** Summary only; linked authorities control if this snapshot drifts
**Update trigger:** A stable scope, architecture, or Roadmap fact changes
**Maintainer:** Documentation/Governance Engineer

## Project purpose and boundary

Medical Equipment Pool is a browser/PWA system for Equipment Pool operators to
issue pool equipment to the first receiving ward and record receipt back. It
replaces an AppSheet spreadsheet process. It is not MEMS, Recall Monitor,
patient/bed tracking, ward-to-ward location tracking, cleaning, PM,
calibration, or a hospital-wide asset-lifecycle system.

Sources: `AGENTS.md`, `docs/BUSINESS_RULES.md`,
`knowledge/adr/ADR-001-equipment-pool-scope.md`.

## Stable domain rules

- Equipment states are exactly `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`,
  `UNAVAILABLE_DEFECTIVE`, and `DECOMMISSIONED`.
- Cleaning is a physical activity, not a lifecycle state or workflow.
- Transactions are `OPEN` or `CLOSED`.
- Receipt uses a binary `usable` / `defective` outcome; backend services map
  the outcome to equipment state.
- BCM Code, Item Number, hospital Asset Number, and internal UUID have distinct
  roles. Existing hospital Item Number QR codes are preserved.
- The first receiving ward is recorded; later physical movements are not
  tracked.
- The backend is authoritative for business rules and authorization.

Sources: `docs/BUSINESS_RULES.md`, `docs/HOSPITAL_DOMAIN_MODEL.md`,
`knowledge/adr/ADR-002-identifier-model.md`,
`knowledge/adr/ADR-005-transaction-model.md`,
`knowledge/adr/ADR-006-receipt-outcome-contract.md`.

## Architecture

React/TypeScript PWA frontend, FastAPI backend, PostgreSQL system of record,
async SQLAlchemy, and Alembic migrations. Audit records use the canonical audit
writer and validated request/correlation context. Production behavior must not
depend on SQLite test behavior or direct access to hospital-managed servers.

Sources: `docs/PROJECT_PLAYBOOK.md`, `docs/ARCHITECTURE_GUARDRAILS.md`,
`docs/ARCHITECTURE_DECISIONS.md`.

## Current baseline and Roadmap

Current baseline: `6ba2c666a11043d03669abdb65f966061dd02cfa`.
Roadmap PR18A (Printing and Export Architecture design) merged as GitHub PR
#71, squash SHA `6ba2c66`, on top of GitHub PR #70 (`bc9e43b`, focused
operator-options cursor-hygiene maintenance) and GitHub PR #69 (`9b2fc1a`,
post-PR17 governance sync). Roadmap PR18A is a design-only approval: no browser
print UI, PDF generation, Excel generation, export routes, DTOs, dependencies,
migrations, API behavior, frontend behavior, or business rules were
implemented.

Equipment Verify Checklist means a read-only, current-state Equipment
master-data snapshot (Owner Decision #1, resolved to interpretation A) — not
a physical-verification workflow. It records no verification time, result,
operator, condition, pass/fail state, or reconciliation outcome, and
introduces no new equipment lifecycle state. Physical verification remains
out of scope, unscheduled future work.

Roadmap PR17 remains complete. The next planned implementation work is PR18B
— the shared backend dataset and document model slice from the approved PR18A
design (`docs/design/PR18_PRINTING_EXPORT_PLAN.md`). PDF, Excel, and browser
print output are **not implemented yet**. The approved sequence is:

- PR18B: shared backend dataset and document model;
- PR18C: browser print presentation;
- PR18D: backend PDF export;
- PR18E: Excel `.xlsx` export;
- PR18F: post-implementation governance synchronization after all approved
  PR18 output slices merge;
- PR19–PR22: legacy import foundation, Equipment Master, AppSheet Receive/Issue
  history, validation and reconciliation;
- PR23: cutover readiness;
- PR24: Go-live / deployment.

Roadmap numbers and GitHub PR numbers are independent. Legacy migration is
mandatory before Go-live.

PR18A leaves three Owner Decisions open before dependent implementation can
merge: export extent, branding configuration ownership, and maximum synchronous
output size.

Sources: `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`,
`docs/audits/04-consolidated-implementation-plan.md`.

## Reporting and migration boundaries

Reporting distinguishes actual transaction time, `business_date`, and `shift`
in one model. Shift is not a lifecycle state and does not create separate
Day/Night tables.

Version 1 legacy migration includes Equipment Master plus only the AppSheet
equipment receive-data and equipment issue-data history sheets. Equipment
Verify Checklist history is excluded. PR20 imports BCM, Item Number, equipment
attributes, and existing hospital QR linkage, with equipment duplicate
detection and equipment-record validation. PR21 imports Receive and Issue
history, preserves legacy BME names for later user mapping, normalizes and maps
Ward values, detects duplicate transaction rows, and retains transaction source
references. PR22 performs cross-import validation, reconciliation, source
traceability verification, duplicate review, and unified legacy/new history
validation before Go-live.

## Working references

- Start with `docs/PROJECT_PLAYBOOK.md`.
- Use `knowledge/CONTEXT.md` for volatile current state.
- Use `knowledge/CHANGE_HISTORY.md` and `docs/DECISION_LOG.md` for history.
- Use `docs/DOCUMENTATION_AUDIT.md` for the documentation inventory.
