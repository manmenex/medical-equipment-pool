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
  roles. Existing hospital Item Number QR codes are preserved. Asset Number is
  optional (unique when present, never fabricated; Governance 2026-10-21).
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
depend on SQLite test behavior or direct access to hospital-managed servers (the department host is
Owner-designated, not run by hospital IT).
Production runs on an Owner-designated department host under Docker,
reachable through Cloudflare Tunnel + Access (Governance 2026-10-13).

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
document from enabling Print.

PR18D implements backend PDF export as a synchronous WeasyPrint adapter
(`report_pdf_service.render_pdf`), consuming the same `ExportDocument` and
its own merged, backend-only Noto Sans Thai TTF assets (WeasyPrint 69.0 does
not reliably render the frontend's split `.woff2` unicode-range files, so the
backend renderer uses a separate merged font, approved by the Repository
Owner). PDF generation is bounded: `render_pdf_bounded` enforces a
concurrency limit and one total timeout covering both queue wait and active
rendering, with renderer-lifetime (not request-lifetime) concurrency
accounting, and the production Docker image is smoke-tested in CI. PR18E
implements backend Excel `.xlsx` export as a synchronous `openpyxl` adapter
(`report_xlsx_service.build_workbook_sync`, no new dependency — `openpyxl`
was already used for `.xlsx` import parsing and the legacy exporter), with
the same bounded-admission-control shape as PDF (`build_workbook_bounded`,
lighter constants than PDF since `openpyxl` has none of WeasyPrint's native
font-shaping/layout cost) and formula-injection protection centralized
through one write helper (`_write_cell`) that every worksheet string —
report rows and the metadata/filter block alike — passes through
unconditionally. Browser Print, PDF, and Excel are independent adapters over
the same `ExportDocument`; none reconstructs report rules, and none
introduced a database migration.

Sources: `docs/PROJECT_PLAYBOOK.md`, `docs/ARCHITECTURE_GUARDRAILS.md`,
`docs/ARCHITECTURE_DECISIONS.md`.

## Current baseline and Roadmap

Live status (baseline SHA, merged PRs, what is next) is owned by
[`docs/ROADMAP.md`](../docs/ROADMAP.md) and is deliberately not repeated here.
Durable facts as of the post-#150 state:

- Roadmap PR1-PR23 are complete (core workflow, four-state model, reports,
  printing/export, legacy import and reconciliation, cutover readiness).
- PR24 (deployment) is in progress. Code/tooling and local Windows Staging/UAT
  operation are evidenced
  (`docs/evidence/PR24D_LOCAL_STAGING_WINDOWS_VALIDATION.md`). PR24E (UAT),
  PR24F (Pilot) and PR24G (Go-Live) are not started. No Production Go decision
  has been authorized; only the Repository Owner authorizes Production.
- Production decision (Governance, 2026-10-13, `docs/DECISION_LOG.md`):
  Production runs on an Owner-designated department host (Windows 11 Pro,
  Docker), not managed cloud. The earlier managed-Staging plan is superseded;
  the system must stay managed-platform portable.
- Stage 1 (PR25A-E, in `docs/ROADMAP.md`): off-host Google Drive backup,
  read-only export API for Nsmart Realtime, Cloudflare Tunnel + Access, then
  offline operation (design PR25D, implementation PR25E). Stage 2 (read-only
  PM/CAL and Repair dashboards sourced from N Smart) is a confirmed direction
  needing its own Governance PR. Stage 3 (replacing N Smart) is out of scope.
- Workflow (2026-10-13, `docs/PROJECT_WORKFLOW.md`): an Orchestrator plans,
  Sonnet implementers build, an Opus reviewer approves the exact green head
  SHA, and the Orchestrator squash-merges and reports to the Owner. Codex and
  ChatGPT are no longer part of the project. CI runs backend tests in
  parallel shards.
- Security baseline now includes self-service password change, a temporary
  first-login password enforced by the backend, and account lockout (#144,
  #148). Backups run hourly with tiered retention (#143); the RPO <= 1h target
  is not yet proven end to end.

Roadmap numbers and GitHub PR numbers are independent. Legacy migration is
mandatory before Go-live.

PR18A Owner Decisions #1 and #3 are resolved and implemented by PR18B: export
covers every row matching the active filters up to the 5,000-row synchronous
bound, never only the visible cursor page. Owner Decision #2, branding
configuration ownership, remains open for the first future slice that depends
on it.

Sources: `docs/ROADMAP.md`,
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
- Use `docs/ROADMAP.md` for current status and `docs/OVERVIEW.md` for a non-technical summary.
