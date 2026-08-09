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

Current baseline: `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` — GitHub PR #79,
the documentation-only PR18F governance synchronization recording Roadmap
PR18's completion, squash SHA `729d1aa`, on top of GitHub PR #78 (`5d8cf7d`,
Roadmap PR18E Excel `.xlsx` export), GitHub
PR #77 (`bc274e6`, PR18D backend PDF export), GitHub PR #76 (`beedc4d`, the
documentation-only governance sync after PR18C), GitHub PR #75 (`e919a2a`,
PR18C Browser Print), GitHub PR #74 (`4da1ebc`, the documentation-only
governance sync after PR18B), GitHub PR #73 (`c72929b`, PR18B backend export
foundation), GitHub PR #72 (`e1b358a`, post-PR18A governance
synchronization), and GitHub PR #71 (`6ba2c66`, the approved PR18A
architecture design). None of PR18C, PR18D, PR18E, or the interleaved
governance-sync PRs (#72, #74, #76, #79) introduced a migration or equipment
lifecycle change.

Equipment Verify Checklist means a read-only, current-state Equipment
master-data snapshot (Owner Decision #1, resolved to interpretation A) — not
a physical-verification workflow. It records no verification time, result,
operator, condition, pass/fail state, or reconciliation outcome, and
introduces no new equipment lifecycle state. Physical verification remains
out of scope, unscheduled future work.

Roadmap PR17 remains complete. **Roadmap PR18 (PR18A design, PR18B backend
export foundation, PR18C Browser Print, PR18D backend PDF export, and PR18E
Excel `.xlsx` export) is now fully complete** — Browser Print, PDF, and Excel
are all implemented for all three PR17 report families. The next planned
implementation work is Roadmap PR19, approved (2026-08-03,
`docs/DECISION_LOG.md`) as an independent-scope split: **PR19A** (backend
import framework) and **PR19B** (frontend-only workflow-review skeleton — no
real upload, parsing, validation, dry-run, or import execution; its category
labels preview PR20/PR21 scope only). "Independent-scope" means neither
slice is stacked on, or blocked by, the other's unmerged branch — it does
not mean they share one implementation baseline. PR19B is Draft PR #80,
branched from this baseline (`729d1aa...`), open and pending independent
review. **PR19A's architecture design has since merged as GitHub PR #83**
(squash SHA `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`), also branched from
`729d1aa...` in parallel. **PR19A1** (schema, session/source lifecycle,
CAS) is in progress on Draft PR #84
(`feature/pr19a1-legacy-import-schema`), open and not merged or complete;
**PR19A2** and **PR19A3** have not started. The base branch's actual
current tip is `38a21e8...`. **Neither PR19A's implementation nor PR19B is
complete.** This split is an
explicit, Owner-approved exception to this repository's usual
design-document-first slice precedent, since at the time of approval no
PR19 design document existed. The remaining approved sequence is:

- PR19A/PR19B: legacy import foundation and its frontend workflow-review
  skeleton;
- PR20–PR22: Equipment Master, AppSheet Receive/Issue history, validation and
  reconciliation;
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
