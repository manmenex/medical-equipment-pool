# Roadmap PR18A — Printing and Export Architecture

**Status:** Approved architecture design, merged as GitHub PR #71
(`6ba2c666a11043d03669abdb65f966061dd02cfa`). PR18B's backend export
foundation subsequently merged as GitHub PR #73
(`c72929ba4649fd75d1f81e4630b4e4feb3d136be`). PR18C Browser Print is next;
Browser Print, PDF, and Excel output are not implemented.
**Purpose:** Implementation design for Roadmap PR18. This document is
authoritative for the approved PR18A architecture, subject to the remaining
unresolved Owner Decision explicitly listed in §23.
**Authority:** This document is subordinate to `AGENTS.md`,
`docs/PROJECT_PLAYBOOK.md`, accepted architecture decisions, and the Roadmap
scope in `docs/audits/04-consolidated-implementation-plan.md`.
**Baseline investigated:** `bc9e43b120aa7d0c4cfa6471be577f92ea910214`
(GitHub PR #70, cursor-hygiene maintenance after Roadmap PR17 completion).
**Repository:** Medical Equipment Pool. This is not MEMS or Recall Monitor.
**Change type:** Documentation and governance only. No backend, frontend,
schema, migration, dependency, test, CI, deployment, API, or business-rule
implementation is included in PR18A.

---

## 1. Purpose and Business Value

Roadmap PR18 adds operational output formats to the three reports delivered by
Roadmap PR17:

- Receive Report;
- Issue Report; and
- Equipment Verify Checklist.

The hospital workflow is deliberately short and Thai-first:

1. Select one of the three reports.
2. Apply the report's existing PR17 filters.
3. Preview the backend-authoritative results.
4. Print through the browser, export PDF, or export Excel `.xlsx`.
5. Retain the generation context in the document: report identity, applied
   filters, generation time, generator, timezone, template version, and row
   count when available.

The objective is a low-effort operational handover and record-retention flow,
not a report builder. Operators must not have to recreate filters in a second
screen or understand cursor pagination to produce a complete document.

## 2. Scope

PR18 covers all three output types:

- browser print;
- PDF export; and
- Excel `.xlsx` export.

It covers all three PR17 report families:

- Receive Report;
- Issue Report; and
- Equipment Verify Checklist.

Every output must preserve the active report's existing filters, eligibility,
authorization, information boundary, and deterministic backend ordering.

## 3. Non-Goals

PR18 does not introduce:

- new report eligibility, filtering, date/shift, ordering, lifecycle, or
  authorization rules;
- analytics, BI, dashboards, KPIs, or an arbitrary report builder;
- MEMS or Recall Monitor integration;
- a physical equipment-verification workflow;
- verification-event storage, verified-at/by fields, pass/fail state,
  condition assessment, or reconciliation workflow;
- preventive maintenance, calibration, or recall workflow;
- legacy import or migration;
- offline export;
- scheduled, batch, or emailed exports;
- digital signatures in Version 1;
- new equipment lifecycle states;
- QR redesign or replacement;
- patient data; or
- changes to the existing dispatch, receipt, ward-correction, or equipment
  identity rules.

The only equipment lifecycle states remain
`AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, and
`DECOMMISSIONED`. Cleaning is not a lifecycle state.

## 4. Current PR17 Architecture

### 4.1 Implemented report surfaces

| Report | Endpoint | Canonical backend source | Response | Filters |
|---|---|---|---|---|
| Receive | `GET /reports/receive` | `report_query_service.search_receive_report()` -> `transaction_crud.search()` | `Page[ReportTransactionOut]` | business-date range, shift, ward, equipment, category, receipt operator |
| Issue | `GET /reports/issue` | `report_query_service.search_issue_report()` -> `transaction_crud.search()` | `Page[ReportTransactionOut]` | business-date range, shift, ward, equipment, category, dispatch operator; backend also supports dispatch type and routine round |
| Equipment Verify Checklist | `GET /reports/equipment-verify-checklist` | `equipment_crud.list_for_verify_checklist()` | `Page[EquipmentOut]` | equipment category, current status, owning department |

All three endpoints are gated by `VIEW_AND_REPORT_ROLES`: Administrator,
Equipment Pool Staff, and Read Only. Frontend visibility is only a usability
gate; backend authorization is authoritative.

### 4.2 Canonical semantics

Receive and Issue are backend-authoritative operational reports:

- Receive pins the receipt event basis and unconditionally requires
  `returned_at IS NOT NULL`; an OPEN transaction never appears.
- Issue pins the dispatch event basis; both OPEN and CLOSED transactions remain
  eligible because a dispatch remains a historical fact after receipt.
- Both reuse the single PR16 `business_date`/`shift` derivation and preserve
  actual timestamps.
- Both use backend ordering `(created_at DESC, id DESC)` with cursor pagination.
- `ReportTransactionOut` adds report-only operator display names without
  modifying the shared `TransactionOut` contract.

Equipment Verify Checklist is a read-only, real-time current-state equipment
snapshot:

- it is not a transaction/event report;
- it has no business-date or shift basis;
- it excludes soft-deleted equipment;
- it uses backend ordering `(created_at DESC, id DESC)`;
- it reuses `EquipmentOut`, which excludes `item_no`; and
- it is not a physical-verification task or completion workflow.

Current filtering, authorization, ordering, cursor validation, and API
information boundaries remain authoritative. Output adapters must not
reimplement or reinterpret any of them.

### 4.3 Existing legacy export

`GET /reports/export?format=xlsx|csv` predates PR16–PR18. It exports an
unfiltered, 50,000-row-capped transaction list through
`app.services.report_service`, with a legacy column set. It does not consume
the PR17 named-report query services or filter contracts.

PR18 must not extend this legacy endpoint into a second reporting engine.
Keeping it temporarily is a compatibility matter; replacement or retirement
is outside PR18A unless separately approved.

## 5. Target Architecture and Responsibilities

```text
Existing PR16/PR17 business rules and filter contracts
                         |
                         v
Canonical backend report query/application services
                         |
                         v
Full-result dataset builder
  - same eligibility and filters
  - same authorization boundary
  - same deterministic ordering
                         |
                         v
Internal output-neutral ReportDocument model
  - metadata
  - applied-filter summary
  - typed columns and rows
  - template/schema version
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
   Print-data API    PDF adapter    Excel adapter
          |              |              |
          v              v              v
 Dedicated React     application/   application/
 print view + CSS    pdf response    xlsx response
```

Responsibilities are explicit:

- **Existing report query layer:** owns eligibility, event basis,
  `business_date`/`shift`, filters, ordering, and information boundaries.
- **Dataset builder:** obtains all bounded rows matching the active filters
  without accepting or following a frontend cursor. It resolves approved
  display values on the backend and never changes eligibility.
- **Internal document model:** represents output-neutral data and generation
  metadata. It is not a public API contract.
- **Print-data adapter:** maps the internal model to a dedicated, versioned JSON
  response DTO for the frontend print view.
- **PDF adapter:** renders the internal model to `application/pdf`.
- **Excel adapter:** renders the internal model to
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- **Frontend:** selects the output, sends the already-applied filters, renders
  the print presentation, initiates downloads, and displays errors. It does not
  determine rows, recalculate fields, or reorder data.
- **Deployment configuration:** supplies branding values and licensed Thai
  font assets; application code supplies safe fallbacks.

The backend remains the single source of truth. PR18 is an output layer, not a
second reporting engine.

## 6. API Strategy

### 6.1 Options compared

| Criterion | Existing endpoint plus `format` parameter | Dedicated output endpoints |
|---|---|---|
| REST clarity | One URL has multiple unrelated response media types | Resource and representation are explicit |
| OpenAPI | Harder to document/test response schemas and media types precisely | Each route has one success media type and contract |
| Authorization | Easy to share one gate, but legacy behavior may be widened accidentally | Each output route declares the same report-view gate explicitly |
| Filter parity | Tempts reuse of the legacy unfiltered exporter | Can call the named report dataset builder directly |
| Pagination | Legacy endpoint has its own cap/query behavior | Export route can reject cursors and fetch all bounded matches |
| Testing | Branches inside one handler multiply combinations | Route/adapter tests remain format-specific |
| Future asynchronous export | A `format` switch becomes a job-type switch | Synchronous routes can later coexist with export-job resources |

### 6.2 Recommendation

Use dedicated output routes under the existing `/reports` namespace, keyed by
a stable report identity and one output representation. The approved route
shape is:

```text
GET /reports/{report_id}/print-data
GET /reports/{report_id}/exports/pdf
GET /reports/{report_id}/exports/xlsx
```

where `report_id` is a closed enum:

- `receive-report`;
- `issue-report`; and
- `equipment-verify-checklist`.

This follows the existing reports router while avoiding nine copy-pasted route
implementations: one typed route family dispatches to three named dataset
builders. PDF and Excel remain distinct endpoints so OpenAPI, media types,
tests, error behavior, caching headers, and future operational controls are
unambiguous.

The routes accept the same filters as the corresponding PR17 report. They do
not accept `cursor` or client-controlled ordering. Unsupported report
identities or formats are rejected through normal typed-route validation or a
structured repository error.

PR18A added no route or dependency. PR18B subsequently implemented only
`GET /reports/{report_id}/print-data`; the PDF and Excel routes remain future
PR18D and PR18E work.

## 7. Dataset and DTO Strategy

### 7.1 Options compared

**Reuse existing response DTOs directly.** This appears cheap but couples file
templates to cursor-page API DTOs and leaves output metadata, localized labels,
typed cells, and approved display-name resolution scattered across adapters.

**Dedicated public export DTOs.** This makes contracts explicit but risks
creating separate PDF and Excel schemas that drift from each other.

**Internal output-neutral document model.** One model contains metadata,
filters, stable columns, typed cell values, and ordered rows. Adapters transform
it without owning domain logic.

### 7.2 Recommendation

Use an internal output-neutral model, conceptually:

```text
ReportDocument
  identity
  display_name_th
  template_version
  generated_at
  generated_by
  timezone
  applied_filters[]
  row_count
  columns[]
  rows[]
```

The internal model is not an API contract. The browser-print adapter exposes a
separate `PrintDocumentOut` API DTO derived from it. PDF and Excel serialize the
internal model directly.

PR18B implemented this boundary as the output-neutral `ExportDocument` family
plus the separate `PrintDocumentOut` API DTO and an explicit one-way mapping.
`ExportDocument` enforces unique column keys, exact row/column key coverage,
declared semantic value types, metadata row-count consistency, and a
timezone-aware generation timestamp at construction time.

The dataset builder may reuse existing domain/query functions and shared
predicate construction, but must not call cursor-paginated HTTP endpoints in a
loop. It must have a backend-owned full-result path that uses the same
eligibility, filters, information boundary, and ordering.

Display values such as Ward, category, department, and operator names are
resolved on the backend for output. The frontend must not join master-data
lookups to construct authoritative export rows.

## 8. Export Scope, Pagination, and Limits

Owner Decision #1 approved **all rows matching the active filters**, not only
the currently visible cursor page. The browser preview may remain
cursor-paginated. Owner Decision #3 approved a 5,000-row synchronous bound for
the shared PR18B retrieval/print-data path; a later renderer may adopt a lower
format-specific bound when its cost requires one.

Accordingly:

- output requests repeat the active report filters;
- output requests never send a frontend cursor;
- the backend evaluates the full matching dataset in canonical order;
- the dataset is bounded by a synchronous per-format row limit;
- exceeding a limit fails before a partial file is returned;
- no adapter silently truncates rows; and
- the response communicates the structured limit error and safe next action.

The current legacy export's 50,000-row cap remains precedent only; it is not a
PR18 limit. PR18B implements the approved 5,000-row bound and rejects excess
rows with `422 EXPORT_TOO_LARGE`, never a partial document. PDF and `.xlsx`
may use stricter rendering-cost-driven limits while retaining clear user
messaging.

## 9. Browser Print

Browser print uses a dedicated presentation, not the interactive report table:

- A4 paper;
- Receive and Issue default to landscape because of their wider transaction
  columns;
- Equipment Verify Checklist defaults to portrait unless implementation-time
  layout evidence demonstrates clipping, in which case landscape is permitted
  without changing report semantics;
- Thai-first labels and filter summaries;
- generated time, generated by, timezone, report identity, and template
  version;
- repeated table headers using print CSS where supported;
- controlled page breaks and `break-inside: avoid` for rows where practical;
- interactive controls, navigation, loading UI, and action buttons hidden;
- no horizontal overflow or clipped required fields; and
- a clear empty-result presentation.

The print view obtains one bounded `PrintDocumentOut` from the backend and
renders it without filtering or sorting. It invokes the browser's native print
dialog only after data and fonts are ready.

Browser print cannot reliably control every browser/driver's page numbers,
headers, footers, margin substitutions, printer scaling, or color settings.
The design does not promise those capabilities. Users may need to disable the
browser's own header/footer option.

## 10. PDF Strategy

### 10.1 Options compared

| Option | Strengths | Risks |
|---|---|---|
| Frontend/browser-generated PDF | Reuses client rendering; little backend code | Device/browser variation, font availability, weak repeatability, memory pressure, difficult automated testing |
| Backend-generated PDF | Stable authorization, metadata, fonts, layout, and tests | Renderer/native dependencies, container size, CPU/memory cost |
| Hybrid | May share HTML/CSS concepts with browser print | Can blur ownership and still inherit browser/runtime variation |

### 10.2 Recommendation

Generate PDF on the backend from the canonical `ReportDocument` using a
server-controlled HTML/CSS-to-PDF renderer. This keeps authorization, complete
dataset selection, metadata, Thai font embedding, and output determinism under
one application boundary.

The browser print template and PDF template should share design tokens and
column definitions where practical, but the PDF is not captured from an
operator's browser. That distinction prevents workstation fonts, extensions,
browser versions, and print settings from changing the file.

PR18A does not select or add a library. PR18D must compare the renderer's Thai
shaping, font embedding, deterministic output, license, native packages,
security update path, container size, startup cost, and concurrency behavior
before adding a pinned dependency. The backend `python:3.12-slim` image
currently contains no PDF runtime, so deployment changes must be explicit and
tested.

## 11. Excel Strategy

Excel output is `.xlsx`, never CSV.

The backend Excel adapter uses the canonical `ReportDocument` and the existing
vetted `openpyxl` dependency. Each workbook contains:

- a metadata/header section with report display name and identity;
- applied-filter summary;
- generated timestamp, timezone, generated-by display name, template version,
  and row count;
- a stable, report-specific column order;
- a frozen table header row;
- autofilter over the data range;
- actual Excel date/time cell types, not preformatted ISO text;
- sensible widths and wrapping;
- Thai-first labels;
- no hidden unauthorized columns or worksheets;
- a safe workbook/sheet title;
- no macros, formulas from untrusted text, or external links; and
- an internal structure that can add multiple sheets later without changing
  report identity.

Cells whose text begins with spreadsheet formula prefixes (`=`, `+`, `-`,
`@`) must be written as literal text. This closes the formula-injection risk
already noted by the PR16 design for the legacy exporter.

For large files, PR18E should use an `openpyxl` write-only/streaming approach
where compatible with the required formatting.

## 12. Security and Information Boundaries

- Export authorization exactly matches report-view authorization:
  `VIEW_AND_REPORT_ROLES`.
- No new permission is introduced by PR18.
- Bulk print/export is nevertheless a new **extraction capability**: it lowers
  the effort needed to obtain a complete filtered dataset compared with
  cursor-by-cursor viewing. Authorization parity does not erase that
  operational and exfiltration risk.
- Keeping the existing three-role gate is justified because those roles are
  already authorized to traverse every row in the same report and the output
  does not widen its field boundary. Row limits, safe output-event logging,
  filename hardening, and unchanged field allow-lists control the new bulk
  surface.
- Backend authorization is evaluated before filter parsing, dataset work, or
  rendering.
- Frontend button visibility is usability only.
- Each output uses the same report-specific field allow-list as the approved
  PR17 surface.
- `item_no` remains excluded from operator-facing Equipment Verify Checklist
  output.
- A format's ability to contain additional columns is not permission to expose
  them.
- Patient data and unnecessary personal information never appear.
- Operator names are included only where PR17 already exposes them through
  `ReportTransactionOut`.
- Filenames, logs, errors, and metrics must not contain sensitive filter values
  or row data.
- Renderers must not fetch arbitrary remote URLs, execute untrusted script, or
  resolve user-supplied file paths.

## 13. Auditability and Document Metadata

Every generated representation includes:

- report identifier;
- Thai display name;
- output format;
- document template/schema version;
- generated timestamp;
- generated-by user display name and stable user identifier where permitted;
- active filters in a normalized, human-readable order;
- timezone (`Asia/Bangkok` for report display context);
- row count when known; and
- application release/build identifier when deployment exposes one safely.

This is document metadata, not persistent audit logging.

The repository does not currently require read/export audit events. PR18 does
not introduce a new persistent domain audit record without Owner approval;
that is a conscious Version 1 boundary and leaves persistent proof of every
download outside scope. Each implementation slice must still emit one safe,
structured operational output event with actor identifier, report identity,
format, outcome, duration, row count when known, and request/correlation
identifier. It must never log exported row data, generated bytes, filenames
containing user input, or sensitive filter values. These events must be
distinguishable from ordinary paginated report reads.

## 14. Print Identity and Versioning

Stable report identities are:

- `receive-report`;
- `issue-report`; and
- `equipment-verify-checklist`.

Identity is not derived from a filename or localized title.

Four versions remain distinct:

- **report identity:** which canonical PR17 report is represented;
- **document-template version:** output column/layout/metadata schema;
- **API version:** `/api/v1` contract version;
- **application release:** deployed software build.

Changing a Thai label or column layout may advance the document-template
version without changing report identity or API version. Changing report
eligibility is not a template change and is outside PR18.

## 15. Filename Convention

Filenames are deterministic, safe, and free of patient or unnecessary personal
data:

```text
{report-id}_{date-or-range}_{shift-or-all}_{generated-utc}.{extension}
```

Examples:

```text
receive-report_2026-07-31_day_20260731T031500Z.pdf
issue-report_2026-07-01-to-2026-07-31_all_20260731T031500Z.xlsx
equipment-verify-checklist_current_all_20260731T031500Z.pdf
```

Rules:

- ASCII lowercase report identity;
- ISO dates;
- UTC generation timestamp for uniqueness;
- safe characters `[a-z0-9._-]`;
- bounded length;
- no operator name, patient data, raw free-text filter, Ward name, or department
  name in the filename; and
- an ASCII fallback is always available even when the document title is Thai.

## 16. Branding and Configuration

Potential configurable values:

- hospital name;
- department/Equipment Pool name;
- logo;
- document title override; and
- footer text.

No hospital identity is hardcoded. Branding configuration source and ownership
are **Open Owner Decision #2** (§23).

Recommended fallback when configuration is absent:

- product-neutral Thai title;
- `Medical Equipment Pool` as a secondary system label;
- no logo;
- no fabricated hospital or department name; and
- a neutral footer containing report identity, template version, and generation
  time.

Configuration must be controlled by deployment/administration, not by request
query parameters. Logo content must be a trusted local/configured asset, never
an arbitrary URL supplied by an operator.

## 17. Thai Language and Fonts

- Thai labels are primary; English technical identifiers remain metadata.
- All formats use Unicode end to end.
- Dates/times display in the approved hospital timezone while retaining typed
  values in `.xlsx`.
- The current frontend font stack names `Noto Sans Thai` but does not bundle a
  Thai webfont. PR18C must close that deployment gap with an approved,
  self-hosted font asset rather than assume it exists on every hospital
  workstation.
- PDF must embed a licensed Thai-capable font so output does not depend on
  workstation fonts.
- Browser print uses a Thai-capable webfont with a documented fallback stack.
- Excel specifies a commonly available Thai-capable font but must remain
  readable when Excel substitutes another installed Unicode font.
- Font assets, licenses, container packages, and cache behavior are reviewed in
  the implementation slice.
- No font file is committed by PR18A.

## 18. Performance and Resource Limits

Version 1 exports are synchronous and bounded.

- Dataset retrieval must not materialize an unbounded result accidentally.
- The backend should iterate/chunk database rows while preserving canonical
  order.
- `.xlsx` should use write-only/streaming generation where compatible.
- PDF rendering may require a smaller limit because layout cost scales with
  pages and font shaping.
- A request exceeding a configured limit fails before rendering; it is never
  silently truncated.
- Rendering has explicit time, memory, and concurrency bounds.
- Client disconnect/cancellation should stop expensive work where supported.
- Generated files are response streams or bounded temporary artifacts with
  deterministic cleanup; they are not permanently stored by default.

Asynchronous job architecture, object storage, batch generation, scheduling,
and notifications are future-compatible but out of scope. A future job API can
reuse report identity, filters, template version, and the same document model.

## 19. Error Handling

Use the repository's structured error envelope and established authorization
ordering.

| Condition | Expected behavior |
|---|---|
| Invalid/reversed filters | Existing `400 INVALID_INPUT` or typed `422 VALIDATION_ERROR`, matching PR17 |
| Malformed preview cursor | Existing structured cursor behavior; output endpoints do not accept cursor |
| Unauthenticated/unauthorized | Existing `401`/`403`, before dataset/render work |
| Export limit exceeded | Dedicated structured client error; no partial file |
| Renderer failure | Safe `500 INTERNAL_ERROR`; details logged server-side without row/filter leakage |
| Unsupported report/format | Typed validation/not-found behavior; no generic format fallback |
| Empty result | Valid empty print/PDF/workbook with metadata and headers |
| Branding/font misconfiguration | Fail closed when output correctness would be compromised; otherwise documented neutral fallback |

PR18B introduced and documented `422 EXPORT_TOO_LARGE` for the shared bounded
dataset/print-data path. It rejects the request without returning a partial
document. Renderer-specific failures remain future adapter work.

## 20. Testing Strategy

### 20.1 Unit tests

- report identity and template-version mapping;
- normalized filter summary;
- filename generation and unsafe-character removal;
- deterministic metadata with fixed clock/user inputs;
- output-neutral model construction;
- format-specific row limits;
- Excel literal-text/formula-injection protection;
- Thai text and Unicode;
- valid empty document;
- renderer failure translation; and
- no unauthorized field in any report column definition.

### 20.2 Backend/API integration tests

- authorization parity for all three roles and unauthenticated/forbidden cases;
- filter parity between preview and output datasets;
- Receive eligibility, Issue eligibility, and Verify current-state semantics
  identical to PR17;
- deterministic ordering and no duplicate/missing rows across chunk boundaries;
- output ignores frontend cursor and includes all bounded matching rows;
- exact PDF media type, filename, and valid PDF signature/page parsing;
- valid `.xlsx` workbook, cell types, frozen header, autofilter, widths, Thai
  text, and stable columns;
- row-limit failure with no partial response;
- empty datasets produce valid output;
- renderer failure produces safe structured error;
- no `item_no` or other restricted field; and
- one safe operational output event per attempt, with no row data or sensitive
  filter values; and
- no persistent domain audit record unless separately approved.

### 20.3 Frontend tests

- output controls carry the current applied URL filters;
- buttons respect usability permissions while backend remains authoritative;
- print view hides interactive controls;
- A4 portrait/landscape print CSS per report;
- repeated headers/page-break declarations where browser-testable;
- loading, empty, error, retry, and popup-blocked behavior;
- print is invoked only after data/font readiness; and
- no client-side filtering, sorting, date/shift derivation, or cursor crawling.

Visual PDF/print fixtures should avoid byte-for-byte PDF comparison when
renderer metadata is inherently variable; assert normalized document structure
and render selected pages for layout review.

## 21. Future Compatibility

The architecture permits, but PR18 does not implement:

- additional operational reports;
- asynchronous export jobs;
- batch generation;
- scheduled/email exports;
- persistent document storage;
- document-verification QR;
- digital signatures;
- multi-sheet workbooks; and
- alternate approved branding profiles.

Future features must reuse the same report identity, backend semantics, and
document model. A document-verification QR is not the hospital equipment QR
system and would require separate design and approval.

## 22. Approved Implementation Slices and Status

### PR18B — Shared backend dataset and document model

**Status:** Merged as GitHub PR #73, squash SHA
`c72929ba4649fd75d1f81e4630b4e4feb3d136be`.

**Scope**

- stable report identities and template versions;
- canonical filter input types;
- full-result dataset builders reusing PR17 predicates/order;
- internal `ExportDocument` model and metadata;
- print-data response DTO;
- authorization parity and limits policy point.

**Dependencies**

- approved PR18A design;
- Owner Decisions #1 and #3 resolved for PR18B; Owner Decision #2 remains
  open and did not block this branding-neutral slice.

**Acceptance criteria**

- preview/output filter and authorization parity proven;
- no cursor accepted by output dataset path;
- no restricted fields;
- deterministic ordering/metadata;
- valid empty document; and
- no PDF, Excel, or frontend print implementation.

**Explicit non-goals**

- renderer dependency, workbook generation, print CSS, async jobs.

### PR18C — Browser print presentation

**Scope**

- dedicated print view consuming `PrintDocumentOut`;
- Thai-first A4 templates, per-report orientation, print CSS;
- metadata/filter summary and native print-dialog flow.

**Dependencies**

- PR18B.

**Acceptance criteria**

- complete bounded dataset, never visible page only;
- controls/navigation hidden;
- no clipped required columns in approved browser matrix;
- browser limitations documented; and
- frontend performs no business logic.

**Explicit non-goals**

- PDF generation, browser-controlled page numbering, scheduled printing.

### PR18D — Backend PDF export

**Scope**

- renderer evaluation and pinned dependency;
- backend PDF adapter;
- embedded licensed Thai font;
- deterministic template, media type, filename, limits, cleanup;
- container/deployment changes required by the selected renderer.

**Dependencies**

- PR18B; PR18C design tokens may be reused but the operator browser is not the
  PDF renderer.

**Acceptance criteria**

- valid repeatable PDF for all three reports;
- Thai shaping/font embedding verified;
- selected renderer and font install successfully in the production-equivalent
  container and CI environment;
- the backend imports and starts with the renderer installed, and CI performs
  at least one PDF smoke generation;
- authorization/filter/field parity;
- bounded resource behavior and safe failure.

**Explicit non-goals**

- client-generated PDF, digital signatures, persistent storage, async jobs.

### PR18E — Excel `.xlsx` export

**Scope**

- backend Excel adapter using existing `openpyxl`;
- metadata/filter block, stable typed columns, freeze panes, autofilter,
  widths, Thai labels, filename, limits, formula-injection protection.

**Dependencies**

- PR18B.

**Acceptance criteria**

- valid workbook for all three reports;
- stable column order and typed date/time cells;
- no CSV or unauthorized hidden data;
- bounded/streaming behavior and safe empty workbook.

**Explicit non-goals**

- import changes, macros, scheduled exports, BI workbook features.

### PR18F — Post-implementation governance synchronization

**Scope**

- after PR18B–PR18E and all approved decisions are merged, update Roadmap,
  status, decision/history, context, and memory documents;
- record the final merged baseline and next Roadmap item.

**Dependencies**

- every approved PR18 implementation slice complete.

**Acceptance criteria**

- Roadmap PR18 is marked done only after all committed output formats work for
  all three report families;
- documentation matches actual merged behavior;
- no runtime change in this final governance PR.

**Explicit non-goals**

- implementation fixes or early PR19 work.

## 23. Owner Decisions

Resolved and unresolved business/operational policy is recorded here so later
slices do not reopen or silently assume it.

### Owner Decision #1 — Export extent

**Resolved before PR18B:** Interpretation A — all rows matching the active
report filters, subject to the synchronous limit; never only the currently
visible cursor page. PR18B implements this through its backend-owned bounded
full-result retrieval path.

### Owner Decision #2 — Branding configuration ownership

**Open.**

Choose the authoritative source for hospital name, department name, logo, and
footer:

- deployment/environment-managed configuration (recommended for Version 1);
- Administrator-managed application settings; or
- no hospital branding in Version 1, using the neutral fallback.

No hospital identity may be assumed or hardcoded before this decision.

### Owner Decision #3 — Maximum synchronous output size

**Resolved before PR18B:** 5,000 rows for the shared full-result
dataset/print-data path, with `422 EXPORT_TOO_LARGE` and no partial document
when exceeded. PDF and `.xlsx` may adopt lower format-specific limits because
their rendering costs differ. The legacy 50,000-row exporter remains precedent
only, not a PR18 limit.

Not open:

- PDF and `.xlsx` are both committed Roadmap PR18 scope, not optional phases.
- Backend-generated PDF is an architecture recommendation, not a business
  decision.
- Physical verification remains out of scope by the resolved PR17 decision.

## 24. Deployment and Operations

- The frontend remains a static Nginx-served React application.
- The backend image is currently `python:3.12-slim` and has no PDF renderer or
  Thai font package; PR18D must document every added system/runtime dependency.
- Production must not assume direct access to hospital-managed servers.
- Branding/font assets are trusted deployment inputs with explicit licenses.
- Renderer health, timeout, concurrency, temporary-file cleanup, and memory
  bounds require deployment verification.
- No permanent document storage is required for synchronous Version 1.
- Rollback is slice-specific: print frontend revert, PDF adapter/dependency
  revert, or Excel adapter revert. PR18B's internal model must remain compatible
  with any already-merged adapter or be reverted with its dependants.

## 25. Acceptance Criteria for PR18 Implementation

Roadmap PR18 is complete only when:

- Receive, Issue, and Equipment Verify Checklist can each be browser-printed,
  exported as PDF, and exported as `.xlsx`;
- all output consumes the same PR17 report semantics and active filters;
- actual event timestamps, `business_date`, and `shift` remain distinct where
  applicable;
- output does not depend on frontend cursor pagination;
- authorization and information boundaries match report viewing;
- Thai text is readable in every format;
- documents include generation context and template version;
- resource limits and failures are explicit, with no silent truncation;
- no transaction, lifecycle, QR, or business rule changes; and
- final governance synchronization records the actual merged baseline.

## 26. PR18A Validation Boundary

PR18A creates and updates documentation only. It does not:

- add routes or DTOs;
- add PDF/font dependencies;
- change `openpyxl` behavior;
- add tests;
- change deployment files;
- change report eligibility, filters, ordering, pagination, authorization, or
  response fields;
- modify a migration or database schema; or
- mark Roadmap PR18 complete.
