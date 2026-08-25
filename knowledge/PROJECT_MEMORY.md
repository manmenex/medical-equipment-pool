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

Current baseline: `22ec7a25d686b0cd37d2a366172cb31a49eebff8` — the real
squash-merge SHA of GitHub PR #123, "PR23 Owner Decision Closure,"
squash-merged on top of `7ca9c87b4c525a1835403dac5d08e6e1be79d33b`
(GitHub PR #122, PR23A). **Roadmap PR22 (Legacy Data Validation and
Reconciliation) is now fully complete; Roadmap PR23 (Cutover
Readiness)'s first slice, PR23A (Architecture & Operational Design), is
merged; and the PR23 Owner Decision Closure round is also merged** —
the Repository Owner has approved all six PR23 Owner Decisions
(OD-PR23-1 through OD-PR23-6) per Recommendation, with an explicit
Owner clarification for OD-PR23-5's Pilot Ward
selection/duration/exit-criteria rules, releasing the fail-closed
PR23B+ implementation-authorization gate. **PR23B (Cutover Readiness
Evidence Foundation) implementation is now in progress, not yet
merged** — an additive backend-only persistence foundation
(`CutoverReadinessRun` model, migration `0021_cutover_readiness`, CRUD,
minimal Administrator-only API) implementing OD-PR23-6's approved
persisted-evidence model, with no readiness-gate evaluation, Go/No-Go
logic, or frontend — see the "Roadmap PR22" paragraph below for full
slice-by-slice detail.

`7ca9c87b4c525a1835403dac5d08e6e1be79d33b` — the real squash-merge SHA
of GitHub PR #122, the Roadmap PR23A implementation (Architecture &
Operational Design) — is now historical, superseded by the PR23 Owner
Decision Closure round's merge (GitHub PR #123) culminating in the
baseline above.

`527ffc48966d7e5cda16a869f0ae464de8b7512a` — the real squash-merge SHA
of GitHub PR #121, the Roadmap PR22G implementation (Governance
Close-out) — is now historical, superseded by the chain above.

`d64d50d09cdf8ed7ddc1f5116b38805dfcbc7810` — the real squash-merge SHA
of GitHub PR #110, the Roadmap PR21E implementation (Legacy History
Frontend Real Integration) — is now historical, superseded by the chain
of PR22/PR23 merges culminating in the baseline above. PR21E's final
independently reviewed feature-branch head was
`8c2b1dacac9996b7a4cab89ff70b6939471ef164` (zero review threads, zero
findings of any kind — a genuine absence of findings, not an accepted
P2 — CI green 6/6) — that reviewed head was not itself the baseline;
the squash commit actually landed on the base branch, `d64d50d...`, was.
**Every Roadmap PR21 implementation slice is merged — Roadmap PR21
(Legacy Receive and Issue History Import) is fully complete.** Roadmap
PR19 and PR20 remain fully complete, unaffected by PR21's completion;
PR19B's mock Receive/Issue workflow has been fully removed by PR21E.
See "Roadmap PR21" below for full detail.

That baseline follows `7f13a1e85e9b6a4828170c4b12bc2be27b15de39` — GitHub
PR #86, the Roadmap PR19A3 implementation (Dry-run, Execution, Recovery,
Retention), following GitHub PR #85 (`7e5e6f2d`, PR19A2, Validation
Foundation) and GitHub PR #84 (`7d589860`, PR19A1, Schema / Session /
Source Foundation), both based on GitHub PR #83 (`38a21e8c`, the
architecture-approved PR19A design), which is itself based on
`729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` — GitHub PR #79, the
documentation-only PR18F governance synchronization recording Roadmap
PR18's completion, squash SHA `729d1aa`, on top of GitHub PR #78
(`5d8cf7d`, Roadmap PR18E Excel `.xlsx` export), GitHub PR #77 (`bc274e6`,
PR18D backend PDF export), GitHub PR #76 (`beedc4d`, the documentation-only
governance sync after PR18C), GitHub PR #75 (`e919a2a`, PR18C Browser
Print), GitHub PR #74 (`4da1ebc`, the documentation-only governance sync
after PR18B), GitHub PR #73 (`c72929b`, PR18B backend export foundation),
GitHub PR #72 (`e1b358a`, post-PR18A governance synchronization), and
GitHub PR #71 (`6ba2c66`, the approved PR18A architecture design). None of
PR18C, PR18D, PR18E, PR19B, or the interleaved governance-sync PRs (#72,
#74, #76, #79) introduced a migration or equipment lifecycle change.

Equipment Verify Checklist means a read-only, current-state Equipment
master-data snapshot (Owner Decision #1, resolved to interpretation A) — not
a physical-verification workflow. It records no verification time, result,
operator, condition, pass/fail state, or reconciliation outcome, and
introduces no new equipment lifecycle state. Physical verification remains
out of scope, unscheduled future work.

Roadmap PR17 remains complete. **Roadmap PR18 (PR18A design, PR18B backend
export foundation, PR18C Browser Print, PR18D backend PDF export, and PR18E
Excel `.xlsx` export) is now fully complete** — Browser Print, PDF, and Excel
are all implemented for all three PR17 report families. Roadmap PR19,
approved (2026-08-03, `docs/DECISION_LOG.md`) as an independent-scope
split — **PR19A** (backend import framework) and **PR19B** (frontend-only
workflow-review skeleton — no real upload, parsing, validation, dry-run, or
import execution; its category labels preview PR20/PR21 scope only) —
"Independent-scope" means neither slice is stacked on, or blocked by, the
other's unmerged branch; it does not mean they share one implementation
baseline. **PR19A's architecture design merged as GitHub PR #83** (squash
SHA `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`), and all three of PR19A's
own implementation slices merged too: PR19A1 (schema, session/source
lifecycle, CAS) as GitHub PR #84, squash SHA
`7d58986095c4df6a425dc9cfd8298851eee86c17`; PR19A2 (validation foundation)
as GitHub PR #85, squash SHA `7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`;
PR19A3 (dry-run, execution, recovery, retention) as GitHub PR #86, squash
SHA `7f13a1e85e9b6a4828170c4b12bc2be27b15de39`. **PR19A (Legacy Import
Foundation, backend) is fully complete.** **PR19B has since merged too:**
after three independent-review rounds on GitHub PR #80 (reconciliation head
`71dc97df583f60c3e9f8bccbbcb2e72b0b7307d5` REQUEST CHANGES on findings
PR80-H1/H2; fix head `6139bd4abd44c0a4ac07bf6ac63bf1b897dad653` REQUEST
CHANGES on remaining finding PR80-H1R; final reviewed head
`5edf1bfd8de7013eb74f300193456c9e5c0f0332` **APPROVE**, CI green 6/6),
PR19B merged with real squash-merge SHA
`04f5bf5c76b51744981d1cc8072c074e604224e9` — historical for current-state
purposes (superseded by `2743af8...`, PR20F's own baseline at the time,
itself since superseded by `d64d50d...`, PR21E, the current baseline;
see "Current baseline and Roadmap" above). GitHub PR #81, an earlier
unsplit PR19A candidate, was closed without merging, superseded by
PR19A1/PR19A2/PR19A3. **Both PR19A and PR19B are now complete; Roadmap
PR19 (Legacy Import Foundation, backend + frontend skeleton) as a whole is
now fully complete**, and the Exception Record governing this split
(`docs/DECISION_LOG.md`) is closed. This split was an explicit,
Owner-approved exception to this repository's usual
design-document-first slice precedent, since at the time of approval no
PR19 design document existed.

**Roadmap PR20 (Equipment Master Import) has since also fully completed**
— all six implementation slices merged: PR20A (source artifact
infrastructure, GitHub PR #90), PR20B (`Equipment.version`
optimistic-concurrency column, GitHub PR #91), PR20C (parse/normalize/
validate adapter, GitHub PR #93), PR20D (persisted immutable
`DryRunPlan`, GitHub PR #94), PR20E (execute — CREATE/UPDATE mutation,
GitHub PR #95), and PR20F (real frontend API integration, GitHub PR #96)
— plus the architecture-approved design (GitHub PR #89) and two
documentation-only governance syncs (GitHub PR #88, #92) interleaved
between them.

**Roadmap PR21 (Legacy Receive and Issue History Import) has since also
fully completed** — every implementation slice merged: PR21-Foundation
(generic dry-run-plan provider + fail-closed retention hook, GitHub PR
#100), PR21A (`LegacyEquipmentEvent` schema/provenance foundation,
GitHub PR #103), PR21B (canonical Issue parser, GitHub PR #104), PR21C
(canonical Receive parser, GitHub PR #105), PR21D1 (Combined Canonical
Adapter + Source Admission, GitHub PR #107), PR21D2 (Historical Event
Execution, GitHub PR #108), PR21E0 (Legacy Import Operator API Surface —
migration-authority approval API + PR21-specific dry-run-plan HTTP
routes, GitHub PR #109), and PR21E (real frontend integration, replacing
the PR19B mock Receive/Issue workflow entirely, GitHub PR #110) — plus
the architecture-approved design (GitHub PR #98, Source Evidence Update
GitHub PR #99) and three Owner Decision Closure rounds (GitHub PR #101,
#102, #106), which resolved all seven PR21 V1 Owner Decisions
(OD-PR21-0 through OD-PR21-6), including excluding the SDC sheets from
V1 by explicit Owner decision. PR21 delivers one combined
`legacy_transaction_history` workbook/session (never two separate
Receive/Issue imports); each accepted row becomes an independent
`ISSUE`/`RECEIVE` `LegacyEquipmentEvent`, Issue↔Receive pairing
deferred to PR22-or-later; historical import never mutates current
Equipment status/location. **Roadmap PR22 (Legacy Data Validation and
Reconciliation) — architecture design, all seven Owner Decisions
(OD-PR22-1 through OD-PR22-7), every implementation slice
(PR22B–PR22F: schema/run-snapshot foundation, deterministic analysis
engine, finding review/disposition API, sign-off + concurrency/audit,
frontend integration), and governance close-out (PR22G) — is now fully
implemented, merged, and complete.** Roadmap PR23 (Cutover Readiness)'s
first slice, PR23A (Architecture & Operational Design), is also merged
(GitHub PR #122), and the PR23 Owner Decision Closure round is also
merged (GitHub PR #123). Current authoritative baseline:
`22ec7a25d686b0cd37d2a366172cb31a49eebff8` (GitHub PR #123, PR23 Owner
Decision Closure, squash-merged on top of `7ca9c87b...`, GitHub PR
#122, PR23A). **All six PR23 Owner Decisions PR23A identified
(OD-PR23-1 through OD-PR23-6) are Owner-approved per Recommendation**,
releasing the fail-closed PR23B+ implementation-authorization gate.
**Current Roadmap work is PR23B (Cutover Readiness Evidence
Foundation): implementation in progress, not yet merged** — an
additive backend-only persistence foundation implementing OD-PR23-6,
with no readiness-gate evaluation, Go/No-Go logic, or frontend.
The remaining Roadmap-numbered items are:

- PR22: legacy data validation and reconciliation — **complete**
  (PR22A–PR22G, GitHub PR #112/#115/#116/#117/#118/#119/#120/#121, all
  merged);
- PR23: cutover readiness — **PR23A (Architecture & Operational Design)
  COMPLETE / MERGED** (GitHub PR #122); **PR23 Owner Decision Closure
  COMPLETE / MERGED** (all six OD-PR23-1 through OD-PR23-6
  Owner-approved, GitHub PR #123, current baseline); **PR23B (Cutover
  Readiness Evidence Foundation) implementation IN PROGRESS, not yet
  merged**;
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
