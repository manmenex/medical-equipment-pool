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

PR18B adds one canonical, output-neutral `ExportDocument` model for all three
PR17 report families. Stable report identities, export metadata, deterministic
typed columns/rows, and schema invariants are centralized in that model.
Receive, Issue, and Equipment Verify Checklist builders reuse the existing
PR17 report semantics and bounded full-filtered query paths; export is not a
second reporting engine. Internal `GET /reports/{report_id}/print-data` maps
the model to a separate API DTO, enforces each report's supported filters, and
returns human-readable applied-filter metadata. Operator names resolve only
within the same transaction-referenced historical-operator information
boundary as `/report-options/operators`. Browser Print, PDF, and Excel remain
separate output adapters.

PR18C implements Browser Print as one dedicated Thai-first frontend adapter
over PR18B's `ExportDocument`/`print-data` foundation for Receive, Issue, and
Equipment Verify Checklist. It renders the backend-provided bounded full
filtered dataset, columns, ordering, metadata, and information boundaries
without reconstructing report rules on the frontend. Print requests remove
only pagination keys (`cursor` and `limit`); other declared filter parameters
remain available for backend validation. Required Noto Sans Thai weights 400
and 700 are checked independently and fail closed when a weight or the Font
Loading API is unavailable. A completed readiness result is accepted only for
the current document identity, preventing an asynchronous result from a stale
document from enabling Print. PDF and Excel remain separate adapters.

Sources: `docs/PROJECT_PLAYBOOK.md`, `docs/ARCHITECTURE_GUARDRAILS.md`,
`docs/ARCHITECTURE_DECISIONS.md`.

## Current baseline and Roadmap

Current baseline: `e919a2af8cc7ca11ab72bee274cb70e76c27ce8a`.
Roadmap PR18C merged as GitHub PR #75, squash SHA `e919a2a`, on top of GitHub
PR #73 (`c72929b`, PR18B backend export foundation), GitHub PR #72 (`e1b358a`,
post-PR18A governance synchronization), and GitHub PR #71 (`6ba2c66`, the
approved PR18A architecture design). PR18C implements Browser Print only. It
introduced no migration or equipment lifecycle change and does not implement
PDF or Excel output.

Equipment Verify Checklist means a read-only, current-state Equipment
master-data snapshot (Owner Decision #1, resolved to interpretation A) — not
a physical-verification workflow. It records no verification time, result,
operator, condition, pass/fail state, or reconciliation outcome, and
introduces no new equipment lifecycle state. Physical verification remains
out of scope, unscheduled future work.

Roadmap PR17 remains complete. Roadmap PR18A design, PR18B backend export
foundation, and PR18C Browser Print are merged; Roadmap PR18 remains
incomplete. The next planned implementation work is PR18D Backend PDF Export.
PDF and Excel output are **not implemented yet**. The remaining approved
sequence is:

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

PR18A Owner Decisions #1 and #3 are resolved and implemented by PR18B: export
covers every row matching the active filters up to the 5,000-row synchronous
bound, never only the visible cursor page. Owner Decision #2, branding
configuration ownership, remains open for the first future slice that depends
on it.

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
