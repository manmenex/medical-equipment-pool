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

Current baseline: `4b0d422` (GitHub PR #52, approved PR15B design). PR15A is
implemented; PR15B implementation is next.

The approved sequence after PR15B is:

- PR16–PR18: reporting foundation, `business_date`/`shift`, operational
  reports, PDF/Excel/Hard Copy output;
- PR19–PR22: legacy import foundation, Equipment Master, AppSheet Receive/Issue
  history, validation and reconciliation;
- PR23: cutover readiness;
- PR24: Go-live / deployment.

Roadmap numbers and GitHub PR numbers are independent. Legacy migration is
mandatory before Go-live.

Sources: `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`,
`docs/audits/04-consolidated-implementation-plan.md`.

## Reporting and migration boundaries

Reporting distinguishes actual transaction time, `business_date`, and `shift`
in one model. Shift is not a lifecycle state and does not create separate
Day/Night tables.

Version 1 legacy migration includes Equipment Master plus only the AppSheet
equipment receive-data and equipment issue-data history sheets. Equipment
Verify Checklist history is excluded. Import must preserve source traceability,
existing QR codes, and BME names for later mapping; normalize Ward values;
detect duplicates; validate and reconcile before Go-live; and show old and new
transaction history together.

## Working references

- Start with `docs/PROJECT_PLAYBOOK.md`.
- Use `knowledge/CONTEXT.md` for volatile current state.
- Use `knowledge/CHANGE_HISTORY.md` and `docs/DECISION_LOG.md` for history.
- Use `docs/DOCUMENTATION_AUDIT.md` for the documentation inventory.
