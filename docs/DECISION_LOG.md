# Decision Log

**Purpose:** Concise, evidenced record of major decisions made from Roadmap PR5 through the CI/AI-review-workflow infrastructure PR, with rationale
**Authority:** Historical navigation; the source cited by each entry controls current policy. Continues `docs/PROJECT_MEMORY.md`, which covers Roadmap PR1 through Governance Pack v1.0 (the period immediately before this log begins).
**Update trigger:** Major decision made during a Roadmap or infrastructure PR's implementation or its review-fix rounds
**Maintainer:** Documentation/Governance Engineer

## 2026-07-28 — Documentation audit and post-PR18 Roadmap alignment

- **Decision:** Keep existing Roadmap PR1–PR15 numbering, use PR16–PR18 for
  reporting/shift/output, PR19–PR22 for legacy import and reconciliation, PR23
  for cutover readiness, and PR24 for Go-live/deployment.
- **Reason:** This preserves repository Roadmap numbering while honoring the
  required order that legacy migration and reconciliation precede Go-live.
  GitHub PR numbers remain a separate sequence.
- **Reporting contract:** Actual transaction timestamp, `business_date`, and
  `shift` are distinct. Shift is operational/reporting metadata; there are no
  separate Day/Night tables and shift is not an equipment lifecycle state.
- **Migration contract:** Version 1 imports Equipment Master plus only the
  AppSheet equipment receive-data and equipment issue-data history sheets.
  Equipment Verify Checklist history is excluded. Existing hospital QR codes
  are preserved. PR20 owns BCM, Item Number, equipment attributes, existing
  hospital QR linkage, equipment duplicate detection, and equipment-record
  validation. PR21 owns Receive/Issue history, legacy BME-name preservation
  and user mapping, Ward normalization and mapping, transaction-row duplicate
  detection, and transaction source references. PR22 owns cross-import
  validation, reconciliation, source traceability verification, duplicate
  review, and unified legacy/new history validation.
- **Source:** `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`,
  `docs/DOCUMENTATION_AUDIT.md`.
- **Status:** Approved documentation alignment; implementation not started.

## 2026-07-31 — Roadmap PR18A printing/export architecture design

- **Decision:** Approve `docs/design/PR18_PRINTING_EXPORT_PLAN.md` as the
  architecture design for Roadmap PR18's output layer. PR18 keeps the existing
  PR17 report semantics as the source of truth and adds output adapters around
  them: browser print, backend PDF export, and Excel `.xlsx` export. The design
  establishes an internal output-neutral `ReportDocument` model, a dedicated
  print-data API shape, backend-owned dataset construction, format-specific
  adapters, and explicit security/resource-limit review requirements for bulk
  output.
- **Open decisions:** PR18A does **not** resolve the Owner Decisions listed in
  the design: export extent, branding configuration ownership, and maximum
  synchronous output size. Any implementation behavior depending on those
  decisions must wait until they are resolved and recorded.
- **Scope boundary:** GitHub PR #71 is documentation-only. It does not implement
  browser print, PDF generation, Excel generation, routes, DTOs, dependencies,
  migrations, API behavior, frontend UI, or business-rule changes.
- **Review chronology:** PR #71 was reviewed in multiple Codex rounds. The
  final reviewed head `cdb7672588fa7e76fadcab3669148dbd75786fa8` resolved the
  original design blockers (browser-print data contract, bulk-export security
  treatment, PDF dependency/deployment criteria) and the later scope/metadata
  blockers (PR71-H3/H4). GitHub PR #71 was squash-merged as
  `6ba2c666a11043d03669abdb65f966061dd02cfa`.
- **Consequences:** Roadmap PR18A design is complete and merged. Roadmap PR18
  runtime implementation is **not** complete and has not begun in this entry.
  PR18B — the shared backend dataset and document model slice — is the next
  implementation step.

## 2026-07-31 — Roadmap PR18A Owner Decisions #1 and #3 (Export Extent and Row Limit)

- **Decision:** The Repository Owner confirms, before PR18B implementation began:
  - **Owner Decision #1 — Export extent:** Interpretation **A** — export/print
    output covers all rows matching the active report filters, bounded by a
    synchronous row limit, never only the currently visible cursor page.
  - **Owner Decision #3 — Maximum synchronous output size:** `5,000` rows,
    shared across every output format PR18B's own dataset-retrieval/print-data
    path serves. This is the evidenced, approved value — not the legacy
    exporter's 50,000-row cap, which the design (§8) explicitly names as
    precedent only, not pre-approval. It is scaled instead to this system's
    confirmed real-world operating scale (`docs/KNOWN_LIMITATIONS.md`: "low
    hundreds of devices, thousands of transactions per year"). A future
    format-specific slice (PR18D PDF, PR18E Excel) may adopt a stricter,
    rendering-cost-driven limit of its own; this value is not upgraded to a
    universal ceiling for those slices by this decision.
- **Owner Decision #2 — Branding configuration ownership:** Remains **unresolved** by this
  entry — it is out of scope for PR18B (branding is not part of PR18B's
  metadata surface) and is deferred to whichever future slice first needs it.
- **Context:** `docs/design/PR18_PRINTING_EXPORT_PLAN.md` §23 flagged all three
  Owner Decisions as blocking before any behavior depending on them could be
  implemented (§22 "PR18B... Dependencies: Owner Decisions #1-#3 resolved
  before behavior depending on them merges"). Decisions #1 and #3 directly
  gate PR18B's own full-result dataset builder and row-limit behavior;
  Decision #2 does not.
- **Source:** `docs/design/PR18_PRINTING_EXPORT_PLAN.md` §8/§18/§23. Recorded
  immediately before Roadmap PR18B (branch `feature/pr18b-export-foundation`,
  baseline `e1b358ac201812be84ce538360f2c2619dac3f0a`, GitHub PR #72's squash
  merge) began implementation.
- **Status:** Decided. Implemented by Roadmap PR18B (see the entry below).
- **Consequences:** PR18B's full-result dataset builder
  (`app.services.report_export_service._fetch_all_matching_rows`) and its
  `MAX_EXPORT_ROWS = 5000` constant directly implement these two decisions.
  Owner Decision #2 (branding) remains open and blocks no part of PR18B.

## Roadmap PR18B — Backend Export Foundation

- **Decision:** Implement the architecture-approved PR18A design's first
  implementation slice (`docs/design/PR18_PRINTING_EXPORT_PLAN.md` §22 "PR18B
  — Shared backend dataset and document model"): a backend-only, output-neutral
  export foundation for the three Roadmap PR17 report families, reusing their
  existing query functions and response DTOs unchanged. **This slice does not
  implement browser print, PDF export, or Excel export** — those remain
  PR18C/PR18D/PR18E, not started here.
- **What was built:**
  - `app/schemas/report_export.py`: `ReportIdentity` (the three stable report
    identities), the internal `ExportDocument`/`ExportMetadata`/`ExportColumn`/
    `ExportRow` model (design §7.2 — never a public API contract), and the
    versioned, API-facing `PrintDocumentOut` DTO the future PR18C browser-print
    adapter will consume, with an explicit `to_print_document_out()` mapping
    function keeping the two deliberately distinct.
  - `app/utils/export_filename.py`: the deterministic filename-stem generator
    (design §15), producing `{report-id}_{date-or-range}_{shift-or-all}_
    {generated-utc}` with no extension (the future renderer supplies that).
  - `app/services/report_export_service.py`: the backend-owned, bounded
    full-result dataset retrieval loop (`_fetch_all_matching_rows`, generic
    over `report_query_service.search_receive_report`/`search_issue_report`/
    `equipment_crud.list_for_verify_checklist`, called unchanged with the
    caller's filters); the three report-document builders (Receive, Issue,
    Equipment Verify Checklist); Thai-first column definitions matching the
    existing on-screen tables; master-data name resolution (ward/category/
    department) via one bounded batch query per lookup, never per row; and
    `MAX_EXPORT_ROWS = 5000` (Owner Decision #3, above).
  - `app/core/exceptions.py::ExportTooLargeError` (`EXPORT_TOO_LARGE`, `422`):
    raised when the full matching-row count exceeds `MAX_EXPORT_ROWS` —
    rejects outright, never truncates silently (design §8).
  - `GET /reports/{report_id}/print-data` (`app/api/v1/reports.py`): one typed
    route dispatching to the three builders, gated by the same
    `VIEW_AND_REPORT_ROLES` every existing report endpoint uses, accepting no
    `cursor` parameter and never following a client-supplied one. Returns
    `PrintDocumentOut`. Logs one safe, structured operational output event per
    attempt (`report_export_service.log_export_attempt`, extending
    `app.core.logging._EXTRA_FIELDS`) — document metadata only, never a
    persistent `audit_logs` row (design §13: PR18 does not introduce a new
    persistent domain audit record without Owner approval).
- **Explicit non-goals:** No browser-print UI, print CSS, PDF renderer/library,
  `.xlsx` renderer/dependency, CSV, asynchronous export jobs, persistent
  generated-file storage, digital signatures, hospital branding, or new
  permission — all confirmed absent from this diff.
- **Testing:** `backend/tests/test_pr18b_report_export.py` (filename
  generation, output-neutral document/metadata construction, row-limit
  behavior, authorization parity, filter/eligibility parity with the existing
  on-screen `GET /reports/receive`/`GET /reports/issue`, item_no exclusion, no
  persistent audit-log row, no transaction-state mutation);
  `backend/tests/test_postgres_integration.py` (PostgreSQL-backed proof that
  the full-result retrieval loop returns every matching row exactly once
  across real multi-page round trips, authorization parity, and row-limit
  rejection with no partial document).
- **Source:** `docs/design/PR18_PRINTING_EXPORT_PLAN.md` §5-§8, §13-§15, §18,
  §22; the Owner Decision entry immediately above. Branch
  `feature/pr18b-export-foundation`, baseline
  `e1b358ac201812be84ce538360f2c2619dac3f0a` (GitHub PR #72's squash merge).
- **Status:** Merged as GitHub PR #73, squash SHA
  `c72929ba4649fd75d1f81e4630b4e4feb3d136be`.
- **Consequences:** The backend export foundation exists; no browser print,
  PDF, or Excel output exists yet. Roadmap PR18 is not complete. PR18C
  (browser print presentation) is the next planned slice.

## Roadmap PR18C — Browser Print

- **Decision:** Implement the architecture-approved PR18A design's second
  implementation slice (`docs/design/PR18_PRINTING_EXPORT_PLAN.md` §9/§22
  "PR18C — Browser print presentation"): a dedicated, Thai-first browser-print
  view for all three Roadmap PR17 report families, consuming only the merged
  PR18B `GET /reports/{report_id}/print-data` endpoint. **This slice does not
  implement PDF or Excel export** — those remain PR18D/PR18E, not started
  here. No backend file changed; no migration added.
- **What was built:**
  - `frontend/src/pages/ReportPrintPage.tsx`: a dedicated print route
    (`/reports/:reportId/print`), deliberately declared outside the
    `AppShell`-wrapping route (mirrors `/login`'s own "bare page" shape) so no
    navigation/dashboard chrome ever appears in the printed output, but still
    guarded by `ProtectedRoute`. Fetches exactly one `PrintDocumentOut` for the
    report identity in the URL. The page forwards every query param present
    on the page that linked here; `frontend/src/services/printReports.ts`'s
    `getReportPrintData` removes only the two pagination controls (`cursor`,
    `limit`) that this route never accepts — enforced inside the service
    itself, not only by page-level preprocessing, so a caller cannot leak
    pagination parameters through it either way. The print-data endpoint
    always returns the complete bounded result set for the active filters
    (Owner Decision #1), never one cursor page. Every other query parameter is
    forwarded rather than silently removed by frontend logic. What actually
    happens to a forwarded parameter server-side depends on whether it is one
    of the eleven filters `GET /reports/{report_id}/print-data`
    (`backend/app/api/v1/reports.py`) declares in its route signature: a
    **declared** filter that does not apply to the current report identity is
    rejected by the already-merged PR18B applicability check
    (`_reject_inapplicable_print_data_filters`) with a structured
    `400 INVALID_INPUT`, surfaced here as a visible error rather than
    silently discarded on the frontend. An **undeclared** query key — one not
    in that route's parameter list at all — is not bound to anything by
    FastAPI's request parsing and may currently be ignored server-side
    without error; this is not the same guarantee as the declared-filter
    case, and this document does not claim every unknown query parameter
    produces `400 INVALID_INPUT`. The backend remains authoritative only for
    the filters actually represented in the endpoint's contract.
    The Print button is enabled only once all of the following hold: the
    current print-data request succeeded, the current `PrintDocumentOut`
    exists, and that document's own font-readiness check
    (`frontend/src/hooks/usePrintFontsReady.ts`) resolved successfully
    (design §9: "invokes the browser's native print dialog only after data
    and fonts are ready"). **This check is built on `document.fonts.load()`,
    not `document.fonts.ready`.** Per the CSS Font Loading Module Level 3
    spec, `FontFaceSet.ready` is defined to only ever fulfill — it "is not
    rejected" even when an individual font face fails to load — so no
    `.then(onFulfilled, onRejected)` written against it can ever observe a
    real font-load failure; an earlier round of this implementation
    mistakenly relied on that promise's reject branch as a failure detector,
    which was dead code in every real browser. `FontFaceSet.load(font, text)`
    is the API the spec defines to reject on a genuine network/parse
    failure for the specific font(s) requested, so the hook calls it
    explicitly for both weights (400/700) `print.css` declares. This also
    removes the original timing concern entirely: because the load is
    requested directly rather than discovered from rendered content, there
    is no "before the content has painted" race to guard against. The check
    is fail-closed — a genuine rejection from `document.fonts.load()` lands
    on an explicit Thai error state with a retry action and never enables
    Print — and tied to the specific document currently on screen via a
    monotonically increasing generation token, so a stale check belonging to
    a since-superseded document can never override a newer document's
    status. `window.print()` is never auto-invoked, and `handlePrint` itself
    refuses to call it unless every readiness condition above still holds.
  - `frontend/src/components/print/PrintDocumentView.tsx`: the purely
    presentational renderer — report title, generation metadata (generated
    time/by/timezone/report identity/template version), the backend-resolved
    human-readable applied-filter summary, row count, and a table using the
    exact column/row order `PrintDocumentOut` returned. Renders a clear Thai
    empty-state message for a zero-row document rather than treating it as an
    error (design §9/§19). No hospital name or logo (Owner Decision #2 remains
    unresolved) — uses design §16's own explicit interim fallback: a
    product-neutral Thai title, "Medical Equipment Pool" as a secondary system
    label, and a neutral footer with report identity/template version/
    generation time.
  - `frontend/src/services/printReports.ts` +
    `frontend/src/types/index.ts` (`PrintDocumentOut`/`PrintColumnOut`/
    `PrintRowOut`/`PrintMetadataOut`/`PrintFilterSummaryOut`/`ReportIdentity`):
    the typed client and contract mirroring the backend PR18B DTOs field for
    field (pagination-stripping behavior described above).
  - `frontend/src/styles/print.css`: print CSS scoped to the print route's own
    Vite code-split chunk only (confirmed by build output — the app's global
    stylesheet is untouched). Defines named CSS pages (`@page portrait-a4`/
    `@page landscape-a4`) for design §9's per-report orientation (Receive and
    Issue landscape; Equipment Verify Checklist portrait — no
    implementation-time clipping evidence to justify the design's own
    documented exception), repeated `<thead>` via `display:
    table-header-group`, `break-inside: avoid` on rows, and a documented
    acknowledgment that page numbers/running headers/margin substitution are
    not promised (design §9).
  - `frontend/public/fonts/noto-sans-thai-{400,700}-{thai,latin}.woff2` +
    `OFL.txt`: closes the deployment gap design §17 explicitly flags (the
    Tailwind font stack has named `"Noto Sans Thai"` since early in the
    project without ever bundling it) — a self-hosted, SIL Open Font License
    1.1 webfont, scoped to the print view's `@font-face` declarations only
    (not the global app font stack), with its license text committed verbatim
    alongside it.
  - Each of `ReceiveReportPage.tsx`/`IssueReportPage.tsx`/
    `EquipmentVerifyChecklistPage.tsx` gained one "พิมพ์รายงาน" link opening
    the corresponding print route in a new tab, carrying that page's exact
    current `location.search` verbatim — no filter re-derivation.
- **Explicit non-goals:** No PDF generation, no browser-controlled page
  numbering, no scheduled/automatic printing, no document-verification QR, no
  digital signature, no hospital logo/name, no backend route or contract
  change — all confirmed absent from this diff.
- **Testing:** `frontend/src/pages/ReportPrintPage.test.tsx` (report-identity
  validation, unmodified filter forwarding including report-inapplicable and
  unrecognized filters, loading/error/retry, metadata and backend-order
  column/row rendering, empty-state rendering, Print-button readiness gating
  including the fail-closed rejected-font-check path and its retry action,
  `window.print()` never auto-invoked and never reachable while font
  readiness has failed, the on-screen toolbar carrying the `.no-print`
  class); `frontend/src/hooks/usePrintFontsReady.test.ts` (proof that
  `document.fonts.load()`, not `document.fonts.ready`, is what the hook
  calls; the fail-closed and stale-result-guard behavior in isolation,
  including proof that a slow-resolving or slow-rejecting document-A check
  can never override a newer document-B's status once B has superseded it,
  and that `retry()` recovers from a failed check); `frontend/src/services/printReports.test.ts`
  (exact endpoint/params, `cursor`/`limit` stripped by the service itself
  even when passed directly to it, every other filter — including a
  report-inapplicable or unrecognized one — preserved unchanged); one added
  test per existing report page (`ReceiveReportPage.test.tsx`/
  `IssueReportPage.test.tsx`/`EquipmentVerifyChecklistPage.test.tsx`) proving
  the print link carries the page's current applied filters. Full existing
  frontend suite re-run with no regression.
- **Source:** `docs/design/PR18_PRINTING_EXPORT_PLAN.md` §9, §16, §17, §20.3,
  §22. Branch `feature/pr18c-browser-print`, baseline
  `4da1ebc016d48b2dece9362e029ecd15eb9dd31b` (GitHub PR #74's squash merge,
  the documentation-only governance sync recording Roadmap PR18B's
  completion — itself built directly on GitHub PR #73's own squash merge,
  `c72929ba4649fd75d1f81e4630b4e4feb3d136be`).
  Corrected in a second Codex review round (PR18C-H1R/PR18C-H2R) to make
  print readiness document-identity-aware and to replace an interim
  per-report-identity filter allowlist with pagination-only stripping,
  keeping the backend the sole authority on filter applicability. Corrected
  again in a third review round (PR18C-H1R2) after that second round's
  "fail-closed" font check turned out to rely on `document.fonts.ready`
  rejecting on font-load failure — which the CSS Font Loading Module Level 3
  spec defines it to never do (`FontFaceSet.ready` "is not rejected"), so
  the branch was dead code in every real browser. Replaced with
  `document.fonts.load()`, the API the spec does define to reject on a
  genuine network/parse failure, which also removed the original
  render-timing race entirely since the load is requested explicitly rather
  than discovered from rendered content. Corrected a fourth time
  (PR18C-H1/PR18C-H2R2/PR18C-H3) to close three remaining gaps: a resolved
  `document.fonts.load()` was treated as success even when it resolved with
  an empty FontFace array (no matching face actually loaded); readiness was
  stored in a plain `status` state variable that could still read a previous
  document's "ready" result on the very first render after the current
  document changed, before any effect had run to reset it; and an
  unavailable Font Loading API (or a missing `.load()` method) fell back to
  "ready" instead of failing closed. `frontend/src/hooks/usePrintFontsReady.ts`
  now derives status fresh on every render by comparing the outcome of the
  most recently completed check against the document identity it belongs
  to, and adds a distinct `"unsupported"` status for a browser that cannot
  run the check at all. The final review correction requires each declared
  font weight (400 and 700) to return a non-empty match independently, so one
  loaded weight cannot mask another missing weight. No backend file changed
  in any correction round; no PR18B behavior affected. Independent review
  recorded substantive APPROVE on exact head
  `9f764bcaf540a7546f0dd166e8628809521d620e` after all prior blockers were
  resolved.
- **Status:** Merged as GitHub PR #75, squash SHA
  `e919a2af8cc7ca11ab72bee274cb70e76c27ce8a`.
- **Consequences:** Receive Report, Issue Report, and Equipment Verify
  Checklist can each now be browser-printed from the merged PR18B foundation.
  Roadmap PR18D (backend PDF export) is built on this baseline — see the
  entry below. No Excel output exists yet.

## Roadmap PR18D — Backend PDF Export

- **Decision:** Implement the architecture-approved PR18A design's third
  implementation slice (`docs/design/PR18_PRINTING_EXPORT_PLAN.md` §10/§22
  "PR18D"): server-rendered PDF export for all three Roadmap PR17 report
  families, built on the merged PR18B `ExportDocument`/dataset builders —
  no new report/query logic. **This slice does not resolve Owner Decision
  #2 (branding configuration ownership)**, which remains open; PDF uses the
  same interim neutral branding fallback (design §16) already used by
  PR18C Browser Print. No Excel export; that remains PR18E.
- **Renderer selection (design §10.2 requires this comparison before any
  PDF dependency is pinned):** WeasyPrint (BSD-3-Clause) was compared
  against alternatives on Thai shaping/glyph coverage, font embedding,
  deterministic rendering, license compatibility, native/system
  dependencies, container/deployment impact, security update path,
  concurrency/memory behavior, and testing support, and selected as the
  server-controlled HTML/CSS-to-PDF renderer. Tested version: WeasyPrint
  69.0 (latest on PyPI at implementation time), requiring the Debian 12
  runtime packages `libpango-1.0-0`, `libpangoft2-1.0-0`,
  `libharfbuzz-subset0` (added to `backend/Dockerfile` and, for CI, to both
  pytest-running jobs in `.github/workflows/ci.yml`). pdfplumber (MIT,
  tested version 0.11.10) is used only by the test suite to parse and
  validate generated PDF content (embedded fonts, extracted text,
  per-character glyph data) — it is never imported by application/runtime
  code.
- **Font-asset finding and correction (design §10.2's own required
  pre-implementation font verification):** The existing
  `frontend/public/fonts/noto-sans-thai-{400,700}-{thai,latin}.woff2`
  assets — split by `unicode-range` into a Thai-glyph file and a
  Latin-glyph file per weight, exactly how Browser Print (PR18C) loads
  them — were verified empirically against WeasyPrint 69.0 before any
  rendering code was written, per the design's requirement. WeasyPrint
  69.0 does not reliably render that two-file/`unicode-range` split: once
  the rendered text contains enough distinct Thai glyphs, it silently
  subsets/merges the two files incorrectly and draws the wrong glyph for
  some Latin characters (reproduced and confirmed via two independent PDF
  text-extraction libraries, pdfplumber and PyMuPDF, and by visually
  inspecting a rasterized page). A single, non-split font file per weight
  — covering both Thai and Latin glyphs together — does not trigger this
  bug. This finding was reported to, and the correction below was
  explicitly approved by, the Repository Owner before any font asset was
  added, per the design's own stop condition for an unreliable font.
  - **Correction:** `backend/app/assets/fonts/NotoSansThai-{Regular,Bold}.ttf`
    — the same Noto Sans Thai typeface (no font-family change), repackaged
    as one merged static TTF per weight (400/700), sourced from the
    official upstream [notofonts/thai](https://github.com/notofonts/thai)
    GitHub Releases (release `NotoSansThai-v2.002`, the release's own
    "full" static TTF build, which merges in Latin/Latin-1 coverage — the
    release's "unhinted"/"hinted" static builds contain Thai-script glyphs
    only and are not usable alone for report content that mixes Thai and
    Latin/numeric text). SIL Open Font License 1.1 (`OFL.txt`, the license
    file from the same release archive), the same license already accepted
    for the `frontend/public/fonts/` copy. See
    `backend/app/assets/fonts/NOTICE.md` for the full provenance record.
    `frontend/public/fonts/` and `frontend/src/styles/print.css` are
    unchanged — Browser Print continues to use the split `.woff2` assets
    exactly as PR18C shipped them; only the backend PDF renderer uses the
    merged TTF assets, because only the backend PDF renderer is affected
    by this bug. This is an implementation-correctness decision about a
    third-party renderer's font-subsetting behavior, not a branding or
    typography decision.
- **Initial implementation (superseded — see "Review round 1/2/3 fixes" and
  "Final merged implementation" below for what actually shipped and merged;
  kept here verbatim as historical context, not the current production
  behavior):**
  - `backend/app/services/report_pdf_service.py`: `render_pdf(document:
    ExportDocument) -> bytes`, a synchronous, CPU-bound function. Builds a
    complete, self-contained HTML document (both fonts embedded as base64
    `data:` URIs, not `file://` paths or a `url_fetcher`) mirroring
    `PrintDocumentView.tsx`'s presentational structure (neutral secondary
    label, Thai report title, generation metadata, applied-filter summary,
    row count, column/row table or empty-state message, neutral footer),
    then renders it via `weasyprint.HTML(string=...).write_pdf()`. Never
    mutates the `ExportDocument` it is given. Per-report-identity page
    orientation (landscape for Receive/Issue, portrait for Equipment
    Verify Checklist) matches Browser Print's own
    `frontend/src/utils/printFormat.ts` `PRINT_ORIENTATION` mapping. (This
    function itself, and its HTML/font-embedding approach, is unchanged by
    every later review round — only how it is *called* changed; see below.)
  - `backend/app/api/v1/reports.py`: `GET /reports/{report_id}/pdf`,
    reusing `_build_export_document_for_request` — a new helper factored
    out of the existing `print-data` route so both routes dispatch through
    the exact same filter-validation and dataset-builder call sites, never
    a duplicated or divergent one. Same `VIEW_AND_REPORT_ROLES`
    authorization, same filter-applicability/date-range validation, same
    `MAX_EXPORT_ROWS` bound (design §8/§18: PR18D adopts, not
    re-derives, PR18B's approved synchronous row limit) and
    `ExportTooLargeError` → structured `422 EXPORT_TOO_LARGE` handling as
    `print-data`. At this stage, `render_pdf` ran via a bare
    `asyncio.to_thread` call with **no timeout or concurrency bound of its
    own** (superseded by review round 1's H1, below). Response is
    `application/pdf` with
    `Content-Disposition: attachment; filename="{filename_stem}.pdf"`,
    reusing the existing `ExportMetadata.filename_stem` (PR18B) with only
    the `.pdf` extension appended — no new filename logic.
  - `backend/requirements.txt`: `weasyprint>=69.0` (runtime) and
    `pdfplumber>=0.11.10` (test-only), added to the existing single,
    floor-pinned manifest — **floor-pinned with `>=`, not yet exact-pinned**
    (superseded by review round 1's H2, below).
  - `backend/Dockerfile`: adds `libpango-1.0-0 libpangoft2-1.0-0
    libharfbuzz-subset0` to the existing `apt-get install` line.
    `.github/workflows/ci.yml`: adds the same three packages to both
    pytest-running jobs (`backend-tests`, `backend-postgres-tests`), since
    neither job builds the Docker image and WeasyPrint loads Pango/HarfBuzz
    at runtime via `cffi`, not via a pip wheel. **No job actually built the
    Docker image at this stage** (superseded by review round 1's H4 and
    round 2's H2, below).
- **Review round 1 fixes (Codex review `4838921407` on PR #77, reviewed head
  `0f3b66e`; findings H1–H8):**
  - H1: bounded PDF rendering with an explicit timeout
    (`RENDER_TIMEOUT_SECONDS = 30`) and concurrency limit
    (`MAX_CONCURRENT_RENDERS = 4`) via the new
    `report_pdf_service.render_pdf_bounded`, an async wrapper around the
    existing synchronous `render_pdf`. A timeout raises the new
    `PdfRenderTimeoutError` (503); the semaphore is released in a `finally`
    block so a timeout or failure always frees its concurrency slot.
  - H2: exact-pinned `weasyprint==69.0` and `pdfplumber==0.11.10` (were
    `>=`), since the approved engineering comparison and the
    font-corruption finding are both specific to these exact tested
    versions.
  - H3: renderer failures (timeout or any other exception) now log their
    own distinguishable export-attempt event (`render_timeout`/
    `render_error`), reusing the existing `log_export_attempt`/outcome
    mechanism — no second event system.
  - H4: added a `backend-docker-build` CI job that smoke-builds the
    production Docker image (previously never built anywhere in CI).
  - H5/H6: rebased onto the latest governance baseline (`beedc4d`, GitHub
    PR #76) and corrected a baseline SHA typo (`e919a2af7...` →
    `e919a2af8...`) across `docs/DECISION_LOG.md`, `docs/ROADMAP.md`, and
    code comments.
  - H7: removed a vacuous `... or True` test assertion and a similarly weak
    `"<b>" in text or "b" in text` check; replaced both with real,
    content-stream-order-based per-character/per-cell assertions.
  - H8: stripped trailing whitespace from
    `backend/app/assets/fonts/OFL.txt` (now byte-identical to the frontend
    copy).
- **Review round 2 fixes (H1–H3):**
  - H1: `render_pdf_bounded` now ties semaphore release to actual renderer
    *completion* (a `Task` done-callback plus `asyncio.shield`) instead of
    the caller's request lifetime, so a client-facing timeout no longer
    frees a concurrency slot while the WeasyPrint worker thread is still
    running. Three new deterministic regression tests prove the bound
    holds under timeout and concurrent load.
  - H2: replaced the round-1 build-only Docker CI job with a production
    image smoke test that boots the container, migrates, seeds, logs in,
    and requests a real PDF export, asserting HTTP 200/`application/pdf`/
    `%PDF`.
  - H3: the Dockerfile now installs from a grep-filtered
    `requirements.runtime.txt` so `pdfplumber` and other test-only
    packages never ship in the production image; `requirements.txt` itself
    is unchanged (still one file, per the approved PR18D plan).
- **Review round 3 fixes (H1–H2):**
  - H1: `render_pdf_bounded` now uses **one total deadline**
    (`RENDER_TIMEOUT_SECONDS`) covering both the wait for renderer capacity
    *and* the active render, not a budget that only started once a slot
    was acquired — a request stuck behind other renders can no longer
    queue indefinitely and only then receive a full render timeout on top
    of that wait; if the deadline passes while still queued, the renderer
    is never started at all. Six new regression tests cover queue-only
    timeouts, queue-plus-render total-budget bounding, and that round 2's
    renderer-lifetime concurrency accounting still holds.
  - H2: fixed the Docker smoke test's seed step, which was failing because
    migration `0009_role_consolidation` already creates the confirmed
    roles (including `administrator`) as part of a plain
    `alembic upgrade head` on a fresh database, and `app/scripts/seed.py`
    unconditionally re-inserted them. `seed_reference_data` now reuses any
    pre-existing role/admin row instead of assuming an empty table — the
    fix that actually makes the documented `alembic upgrade head` +
    `python -m app.scripts.seed` deployment sequence
    (`docs/06-deployment-guide.md`) work at all, not only this smoke test.
    The smoke test's PDF assertions now also check the full `%PDF-` header
    and a non-trivial response body size.
- **Final merged implementation (what actually shipped in GitHub PR #77;
  this — not "Initial implementation" above — is the current production
  behavior):**
  - `GET /reports/{report_id}/pdf` calls
    `report_pdf_service.render_pdf_bounded`, not a bare synchronous
    `render_pdf`/`asyncio.to_thread` pairing. `render_pdf_bounded` enforces
    `MAX_CONCURRENT_RENDERS = 4` via a semaphore and
    `RENDER_TIMEOUT_SECONDS = 30` as **one total deadline covering both
    queue wait and active rendering** — a request that never obtains a
    renderer slot within the deadline is rejected with
    `PdfRenderTimeoutError` (503) without ever starting a render.
  - **Renderer-lifetime concurrency accounting:** the semaphore slot is
    released only when the renderer `Task` itself completes (via
    `Task.add_done_callback` plus `asyncio.shield`), never merely when the
    caller's request times out — so a client-facing timeout can never free
    a slot while WeasyPrint is still actively rendering in the background.
  - **Exact-pinned dependencies:** `backend/requirements.txt` declares
    `weasyprint==69.0` and `pdfplumber==0.11.10` (not `>=`), since the
    approved renderer comparison and the font-corruption finding are both
    specific to these exact tested versions.
  - **Dependency isolation:** the production Docker image installs from a
    grep-filtered `requirements.runtime.txt`, so `pdfplumber` and other
    test-only packages are never present in the production image;
    `requirements.txt` remains the single source-of-truth manifest file.
  - **Production Docker PDF smoke validation:** CI boots the production
    image, runs `alembic upgrade head`, runs the seed script, logs in, and
    requests a real PDF export end to end, asserting HTTP 200,
    `Content-Type: application/pdf`, the full `%PDF-` header, and a
    non-trivial response body size — not merely that the image builds.
  - **Seed-idempotency correction:** `app.scripts.seed.seed_reference_data`
    reuses any pre-existing role/admin row instead of assuming an empty
    table, since migration `0009_role_consolidation` already creates the
    confirmed roles on a fresh install — a real deployment-sequence
    correction (`docs/06-deployment-guide.md`), not only a test-fixture
    fix.
  - Distinguishable `render_timeout`/`render_error` export-attempt log
    outcomes (via the existing `log_export_attempt` mechanism) and
    content-stream-order-based (not substring/vacuous) PDF text-extraction
    test assertions are both part of the merged state.
  - Everything else described under "Initial implementation" above — the
    renderer/font selection, the HTML-document construction inside
    `render_pdf` itself, the route's authorization/filter/row-limit
    handling, and the response headers/filename — is unchanged by the
    review rounds and remains accurate for the merged state.
- **Explicit non-goals:** No Excel export, no async/background export job,
  no persisted generated file, no external resource fetch during
  rendering, no new synchronous row limit (reuses PR18B's), no change to
  Browser Print or PR17 report business semantics — all confirmed absent
  from this diff.
- **Testing:** `backend/tests/test_pr18d_pdf_export.py` — unit tests
  against `report_pdf_service.render_pdf` directly (valid PDF structure;
  both font weights embedded under a genuine subset tag, never a system
  fallback; a regression test reproducing the exact realistic mixed
  Thai/Latin sentence that triggered the pre-implementation corruption
  finding, verified via per-glyph, content-stream-order character
  inspection scoped to one table cell — not merely "starts with `%PDF`";
  per-report-identity page orientation; empty-result-set handling;
  neutral-branding presence; HTML-special-character escaping) and API
  tests against `GET /{report_id}/pdf` (authorized-role success,
  unauthenticated 401, unsupported `report_id` 422, reversed date-range and
  inapplicable-filter 400s, row-limit-exceeded 422 with a JSON error body
  — never partial PDF bytes, ASCII-safe `Content-Disposition` filename, no
  persistent audit-log write, no transaction-state mutation, and seeded
  end-to-end content checks for both a transaction report and the
  Equipment Verify Checklist's Thai status label). Added across the three
  review rounds, on top of the above: renderer-lifetime concurrency-bound
  regression tests against `render_pdf_bounded` (round 2, 3 tests);
  queue-only-timeout and queue-plus-render total-budget regression tests
  against `render_pdf_bounded` (round 3, 6 tests); and a dedicated
  production Docker-image smoke test (`.github/workflows/ci.yml`) that
  boots the actual production image and performs one full end-to-end PDF
  export request, asserting the `%PDF-` header and a non-trivial response
  body size (round 2 introduced the job; round 3 completed its assertions
  and fixed the seed-step dependency it relies on).
- **Source:** `docs/design/PR18_PRINTING_EXPORT_PLAN.md` §8, §10, §16, §18,
  §22. Branch `feature/pr18d-pdf-export`, baseline
  `beedc4d32c8d3ae6b6a418f36aa49b3177209b3f` (GitHub PR #76's squash merge,
  the documentation-only governance sync recording Roadmap PR18C's
  completion — itself built directly on GitHub PR #75's own squash merge,
  `e919a2af8cc7ca11ab72bee274cb70e76c27ce8a`, Roadmap PR18C). Renderer/font
  decisions above were presented to,
  and explicitly approved by, the Repository Owner before implementation
  proceeded (renderer comparison and recommendation approved first; the
  font-asset correction approved separately after the empirical finding
  above).
- **Status:** Merged as GitHub PR #77, squash SHA
  `bc274e6176f225518db4ebaf0b5ed643c653aaa7`.
- **Consequences:** Receive Report, Issue Report, and Equipment Verify
  Checklist can each now be exported as a backend-rendered PDF, reusing the
  PR18B foundation and PR18C's neutral branding. Owner Decision #2
  (branding configuration ownership) remains open — this entry does not
  resolve it. Excel output remains PR18E; Roadmap PR18 is not yet
  complete as of this entry — see "Roadmap PR18E" and "Roadmap PR18 —
  Printing and Export Complete" below for its subsequent completion.

## Roadmap PR18E — Excel `.xlsx` Export

- **Decision:** Implement the architecture-approved PR18A design's fourth
  implementation slice (`docs/design/PR18_PRINTING_EXPORT_PLAN.md` §11/§22
  "PR18E"): a backend Excel `.xlsx` adapter for all three Roadmap PR17
  report families, built on the merged PR18B `ExportDocument`/dataset
  builders — no new report/query logic, no second reporting engine. Same
  interim neutral branding fallback (design §16) already used by PR18C
  Browser Print and PR18D PDF; **this slice does not resolve Owner
  Decision #2** (branding configuration ownership), which remains open.
- **Excel library selection (task requirement: compare at least `openpyxl`
  and `xlsxwriter` before adding any dependency):**

  | Criterion | `openpyxl` | `xlsxwriter` |
  |---|---|---|
  | Maintenance | Actively maintained, widely adopted | Actively maintained, widely adopted |
  | License | MIT | BSD-2-Clause |
  | Memory usage at this bound (≤5,000 rows) | Low; standard mode is fast/low-memory at this scale | Low; comparable at this scale |
  | Streaming capability | Has its own write-only/streaming mode | Has a "constant memory" streaming mode |
  | Formatting support | Fonts, fills, alignment, number formats, freeze panes, autofilter, column widths — all present | Same feature set for these requirements |
  | Read capability | Can read/parse an existing `.xlsx` (already used by `app.services.import_service` for the PR12 Excel import path) | Write-only by design — cannot read a workbook at all |
  | Testing | This adapter's own tests can open and assert on the generated workbook with `openpyxl.load_workbook`, zero new test dependency | Would still need `openpyxl` (or another reader) as a *new test-only dependency*, since `xlsxwriter` cannot read back what it wrote |
  | Deployment impact | Already an existing, vetted runtime dependency (`backend/requirements.txt`, unpinned floor `>=3.1.5`) used by both `app.services.import_service` (`.xlsx` import parsing) and the legacy `app.services.report_service.export_xlsx` | Would be an entirely new runtime dependency with its own license/security-update surface |

  **Recommendation: `openpyxl`.** It is already a vetted, actively-used
  dependency in this exact codebase for both reading (Roadmap PR12 import)
  and writing (the legacy exporter) `.xlsx` files, so reusing it adds zero
  net-new dependency surface, license review, or CVE-monitoring burden.
  `xlsxwriter`'s headline strength — a very large streaming export — is not
  a real differentiator at the approved `MAX_EXPORT_ROWS = 5000` row bound,
  and adding it *alongside* `openpyxl` (which import parsing would still
  require regardless, since `xlsxwriter` cannot read a workbook at all)
  would mean carrying two Excel-writing libraries for the same job — the
  task's own instruction ("Do not add dependencies until the recommendation
  is documented") is satisfied by adding none. No change to
  `backend/requirements.txt`.
- **Streaming/write-only mode was deliberately not adopted:** design §11/§18
  say `.xlsx` "should use write-only/streaming generation where compatible
  with the required formatting." `openpyxl`'s write-only mode cannot
  reliably combine a metadata block, a frozen header row, an autofilter
  range, per-cell number formats, and formula-injection-safe text in one
  worksheet the way this adapter requires. At the approved 5,000-row bound,
  standard (buffered) `openpyxl` generation is fast and low-memory in
  practice — the same reasoning the pre-existing legacy
  `report_service.export_xlsx` already relies on for up to 50,000 rows.
- **Formula-injection mitigation (design §11/security):** cells whose
  string value begins with `=`, `+`, `-`, or `@` are written with a leading
  single quote (`'`) prefix — the standard, portable OWASP-documented
  CSV/Excel formula-injection defense — so the cell is always stored and
  displayed as literal text, never interpreted as a formula, in Excel or
  any other spreadsheet tool that might import the file. Only
  `value_type == "string"` cells are ever checked; `ExportDocument`'s own
  construction-time invariant guarantees no other declared value type can
  hold a `str` at all.
- **What was built:**
  - `backend/app/services/report_xlsx_service.py`: `build_workbook_sync
    (document: ExportDocument) -> bytes`, a synchronous, CPU-bound
    function. Writes a single worksheet (design §22 PR18E non-goal: "no
    multiple worksheets unless approved by design") containing a metadata
    block (secondary label, Thai report title, generation timestamp/
    timezone/generated-by/template-version/row-count, applied-filter
    summary), then a table with the document's declared columns in order —
    frozen header row, autofilter scoped to the header+data range only,
    bounded column widths, wrapped cell text, native Excel date/datetime
    cell types (timezone-converted to the document's own declared display
    timezone and stripped of `tzinfo`, since `openpyxl`/Excel's datetime
    cell type has no timezone concept), native numeric cells for
    integer/decimal columns, Thai-labeled text for boolean columns
    (matching `report_pdf_service._format_value`'s own convention), and
    genuinely blank cells for `None` (not a "-" placeholder, so
    spreadsheet features like `COUNTBLANK`/filtering behave correctly).
    Never mutates the `ExportDocument` it is given.
  - `backend/app/api/v1/reports.py`: `GET /reports/{report_id}/xlsx`,
    reusing the existing `_build_export_document_for_request` helper (the
    same one `print-data` and `pdf` already share) — no third, divergent
    dataset-building call site. Same `VIEW_AND_REPORT_ROLES` authorization,
    same filter-applicability/date-range validation, same
    `MAX_EXPORT_ROWS` bound and `ExportTooLargeError` → structured `422
    EXPORT_TOO_LARGE` handling as `print-data`/`pdf`. `build_workbook_sync`
    runs via `asyncio.to_thread` (the same pattern
    `report_pdf_service.render_pdf` and
    `import_service._parse_workbook_sync` already use for CPU-bound work),
    so it never blocks the event loop. **Superseded by the round 1 review
    fix below:** the route now calls the bounded wrapper
    `build_workbook_bounded`, which layers its own timeout/concurrency
    bound on top (a lighter one than PDF's, since `openpyxl` at the
    approved row bound has none of the native-library layout/font-shaping
    cost that motivated PDF's bound) — see "Round 1 review fixes" below.
    Response
    is `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
    with `Content-Disposition: attachment; filename="{filename_stem}.xlsx"`,
    reusing the existing `ExportMetadata.filename_stem` (PR18B) with only
    the `.xlsx` extension appended — no new filename logic. A renderer
    failure logs its own distinguishable `render_error` operational
    export-attempt event before re-raising, mirroring PR18D review
    `4838921407`'s H3 fix for the PDF route.
- **Explicit non-goals:** No CSV, no charts, no formulas derived from
  document content, no macros, no pivot tables, no multiple worksheets, no
  async/background export job, no persisted generated file, no new
  synchronous row limit (reuses PR18B's), no change to Browser Print, PDF
  export, `ExportDocument`, or PR17 report business semantics — all
  confirmed absent from this diff.
- **Testing:** `backend/tests/test_pr18e_excel_export.py` — unit tests
  against `report_xlsx_service.build_workbook_sync` directly (valid
  `.xlsx` structure; per-report-identity worksheet title; metadata-block
  content; header row matches declared columns in order; empty-result-set
  handling; native date/datetime cell types with correct timezone
  conversion, not preformatted text; genuinely blank cells for `None`;
  native numeric cells; Thai-labeled boolean cells; frozen header row and
  scoped autofilter; bounded column widths; single-worksheet-only;
  formula-injection escaping for all four prefix characters, parametrized,
  plus a matching "safe value is not escaped" counter-test) and API tests
  against `GET /{report_id}/xlsx` (authorized-role success, unauthenticated
  401, unsupported `report_id` 422, reversed date-range and
  inapplicable-filter 400s, row-limit-exceeded 422 with a JSON error body
  — never a partial workbook, ASCII-safe `Content-Disposition` filename, no
  persistent audit-log write, no transaction-state mutation, seeded
  end-to-end content checks for both a transaction report and the
  Equipment Verify Checklist's Thai status label, `item_no` absence from
  Equipment Verify Checklist output, unexpected-generation-error 500 with
  a distinguishable logged outcome distinct from `"success"`) plus
  regression tests proving `print-data` and `pdf` are unaffected.
- **Source:** `docs/design/PR18_PRINTING_EXPORT_PLAN.md` §11, §12, §16,
  §18, §22. Branch `feature/pr18e-excel-export`, baseline
  `bc274e6176f225518db4ebaf0b5ed643c653aaa7` (GitHub PR #77's squash
  merge, Roadmap PR18D). The library comparison above is documented in
  this PR's own description and this entry, per the task's explicit
  requirement to document the recommendation before adding any
  dependency — no new dependency was added.
- **Status:** Merged as GitHub PR #78, squash SHA
  `5d8cf7d8f378f6231d43e330310f664f6c19560f`.
- **Round 1 review fixes (reviewed head
  `cd524e5ffd87ad7cb40487031207354cf92e2e1d`, fixed in `8aea062`):**
  Codex's independent review found two gaps not covered by the description
  above. **H1 — workbook-wide formula-injection protection:** the
  as-implemented adapter sanitized report *row* values but not the
  metadata block; `generated_by_display_name` (a user's editable
  `full_name`) and applied-filter values (backend-resolved ward/category/
  equipment/operator display names — administrator-editable free text via
  `report_export_service._filter_summary`) could reach the workbook
  unsanitized. Fixed by introducing `report_xlsx_service._write_cell`, the
  single call site every string write in the module now goes through
  (report rows, report title, secondary label, every metadata line,
  applied-filter labels/values, header row) — `_cell_value_for` no longer
  sanitizes independently. **H2 — Excel export admission control:** the
  as-implemented adapter bounded only row count, not concurrent or queued
  generation. Fixed by adding `report_xlsx_service.build_workbook_bounded`,
  reusing PR18D's `render_pdf_bounded` protection model unchanged in
  structure (bounded semaphore, one total deadline covering queue wait and
  active generation, renderer-lifetime concurrency accounting via a
  `Task.add_done_callback` release) with Excel-specific constants
  (`MAX_CONCURRENT_RENDERS = 8`, `RENDER_TIMEOUT_SECONDS = 15`, both looser
  than PDF's 4/30s given `openpyxl`'s lighter resource profile at the
  approved row bound). A new `XlsxRenderTimeoutError` (503,
  `XLSX_RENDER_TIMEOUT`) mirrors `PdfRenderTimeoutError`. 21 new tests (14
  for H1, 7 for H2) were added to `backend/tests/test_pr18e_excel_export.py`
  (65 tests total).
- **Consequences:** Receive Report, Issue Report, and Equipment Verify
  Checklist can each now be exported as a backend-generated `.xlsx`
  workbook, reusing the PR18B foundation and the PR18C/PR18D neutral
  branding fallback. Owner Decision #2 (branding configuration ownership)
  remains open — this entry does not resolve it. **All three committed
  PR18 output formats (browser print, PDF, Excel) are now merged.** Roadmap
  PR18 is not marked complete by this entry; that final governance
  synchronization (recording the actual merged baseline for every slice)
  is PR18F's job — see "Roadmap PR18 — Printing and Export Complete"
  below.

## Roadmap PR18 — Printing and Export Complete (PR18F governance synchronization)

- **Decision:** Record Roadmap PR18 (Printing and Export) as complete, now
  that every committed output-format implementation slice —
  PR18B (backend export foundation), PR18C (Browser Print), PR18D (backend
  PDF export), and PR18E (Excel `.xlsx` export) — is merged. This is a
  documentation-only governance synchronization (`docs/design/PR18_
  PRINTING_EXPORT_PLAN.md` §22 "PR18F"); it changes no runtime behavior,
  route, schema, or business rule.
- **What PR18 delivered, end to end:**
  - a shared, output-neutral `ExportDocument` backend foundation (stable
    report identities, metadata, deterministic typed columns/rows,
    schema-invariant validation, bounded full-result retrieval, filter
    applicability enforcement, human-readable applied-filter metadata,
    bounded historical operator lookup, internal `print-data` endpoint) —
    PR18B;
  - Browser Print for Receive Report, Issue Report, and Equipment Verify
    Checklist, entirely backend-driven, with fail-closed font readiness
    bound to the current document identity — PR18C;
  - backend PDF export (WeasyPrint, embedded backend-only Thai font
    assets, neutral branding fallback, deterministic filenames, bounded
    concurrency/admission control with a total timeout covering queue
    wait, renderer-lifetime concurrency accounting, production Docker
    image validation and PDF smoke test, no generated-file persistence) —
    PR18D;
  - backend Excel `.xlsx` export for the same three reports (workbook
    metadata, Thai headers, frozen header row, autofilter, deterministic
    columns/order, workbook-wide formula-injection protection through one
    centralized write helper, bounded concurrency/admission control with a
    total timeout covering queue wait and active generation,
    renderer-lifetime concurrency accounting, no silent truncation, no
    migration) — PR18E.
  - Across all three output adapters, report semantics, eligibility,
    ordering, and filtering remain exactly PR17's — no adapter reconstructs
    or duplicates reporting logic, and no adapter introduced a database
    migration.
- **Unresolved:** **Owner Decision #2 (branding configuration ownership)
  remains open.** Every PR18 output format uses the same interim neutral
  fallback approved in the PR18A design (no hospital name, no department
  name, no logo, a Thai product-neutral report title, "Medical Equipment
  Pool" as the secondary label, a neutral footer) — this entry does not
  resolve Owner Decision #2, and no deployment/environment-managed or
  Administrator-managed branding configuration exists anywhere in the
  repository.
- **Source:** `docs/design/PR18_PRINTING_EXPORT_PLAN.md` §22–§25. Branch
  `docs/pr18f-governance-sync`, baseline
  `5d8cf7d8f378f6231d43e330310f664f6c19560f` (GitHub PR #78's squash merge,
  Roadmap PR18E).
- **Status:** Roadmap PR18 marked complete by this entry, on the strength
  of PR18B/PR18C/PR18D/PR18E all being merged. PR19 (Legacy Import
  Foundation) is the next planned Roadmap item and is **not** implemented
  by this entry.
- **Consequences:** Receive Report, Issue Report, and Equipment Verify
  Checklist can each be viewed, browser-printed, PDF-exported, and
  Excel-exported. `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`,
  `knowledge/CONTEXT.md`, and `knowledge/PROJECT_MEMORY.md` are updated
  alongside this entry to reflect the same completion and baseline.

## 2026-08-03 — Roadmap PR19 approved split: PR19A (backend) / PR19B (frontend skeleton)

- **Decision:** Approve splitting Roadmap PR19 ("Legacy Import Foundation")
  into two independent-scope implementation slices — **PR19A** (backend)
  and **PR19B** (frontend skeleton). "Parallel" describes their scope and
  dependency relationship only — neither is stacked on, nor blocked by, the
  other's unmerged branch. It does **not** mean the two slices share one
  frozen implementation baseline commit:
  - **PR19A — Legacy Import Foundation (backend):** the staged,
    validation-first, traceable import framework itself — API contract,
    session/document model, validation and dry-run mechanics. At the time
    this entry was originally written, PR19A had not started. **Update
    (post-authoring, this same still-unmerged governance PR):** PR19A's
    architecture design has since merged —
    `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`, GitHub PR **#83**,
    squash SHA `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7` — branched directly
    from `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` in genuine parallel with
    this governance PR and PR19B (exactly what "independent-scope, not
    stacked" was meant to allow; PR19A's branch did not wait for this PR to
    merge). That design defines PR19A's authoritative API/session/document
    model contract and further decomposes PR19A into implementation slices
    **PR19A1/PR19A2/PR19A3** (design §25). **Second update (2026-08-10,
    this same entry): all three implementation slices have since merged.**
    PR19A1 (schema, session/source lifecycle, CAS) merged as GitHub PR
    **#84**, squash SHA `7d58986095c4df6a425dc9cfd8298851eee86c17`. PR19A2
    (validation foundation) merged as GitHub PR **#85**, squash SHA
    `7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`. PR19A3 (dry-run, execution,
    recovery, retention) merged as GitHub PR **#86**, squash SHA
    `7f13a1e85e9b6a4828170c4b12bc2be27b15de39`. **PR19A (Legacy Import
    Foundation, backend) is now fully complete.** See "Roadmap PR19A
    complete: PR19A1 + PR19A2 + PR19A3 merged" (new entry, below) for the
    full slice-by-slice implementation and review chronology. This does
    **not** by itself close this Exception Record — see "Expiration /
    Follow-up" below, updated accordingly.
  - **PR19B — Legacy Import Frontend Skeleton:** a frontend-only, mock-data
    UI prototype of the future import workflow, for early hospital-user
    workflow review ahead of PR19A's real contract. Branched from
    `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` (GitHub PR #79, the PR18F
    governance synchronization) — the latest approved baseline at the time
    PR19B's branch was created. Implemented on branch
    `feature/pr19b-import-frontend-skeleton`, Draft PR **#80** — not yet
    independently reviewed or merged at the time of this entry. **Third
    update (2026-08-11, this same entry):** PR19B was reconciled against
    PR19A's merged contract at reviewed head
    `71dc97df583f60c3e9f8bccbbcb2e72b0b7307d5` (REQUEST CHANGES — findings
    PR80-H1 and PR80-H2), fixed at `6139bd4abd44c0a4ac07bf6ac63bf1b897dad653`
    (REQUEST CHANGES — remaining finding PR80-H1R), and fixed again at the
    final reviewed head `5edf1bfd8de7013eb74f300193456c9e5c0f0332`
    (**APPROVE**, CI green 6/6). PR19B then merged as GitHub PR **#80**,
    real squash-merge SHA `04f5bf5c76b51744981d1cc8072c074e604224e9`. **PR19B
    (Legacy Import Frontend Skeleton) is now fully complete.** See "Roadmap
    PR19B merged: Exception Record closed; Roadmap PR19 fully complete" (new
    entry, below) for the full review-round chronology. This closes the
    Exception Record below — see "Expiration / Follow-up", updated
    accordingly.

### Exception Record (per `docs/ENGINEERING_WORKFLOW.md` §22, Exception Policy)

- **Reason:** This repository's established precedent
  (Roadmap PR7/PR8/PR9/PR14/PR15/PR16/PR17/PR18) only splits a Roadmap item
  into lettered slices after an architecture-approved design document
  defines that split. No such design document exists for Roadmap PR19. This
  is therefore an explicit, Owner-approved exception to that normal sequence
  (`docs/PROJECT_PLAYBOOK.md` "Exception workflows"), made so PR19B could
  begin immediately as a hospital-facing workflow-review artifact without
  waiting for PR19A's backend contract to finalize. The conflict between
  this exception and the then-current Roadmap text (Roadmap PR19 as one
  unsplit item, with Equipment Master/Receive/Issue History categories
  belonging to the separate, dependent PR20/PR21) was identified and raised
  before any PR19B code was written — see Draft PR #80's own
  "Repository-Owner-confirmed scope decision" section — and the Repository
  Owner confirmed the split directly. This entry is the formal governance
  record required by that confirmation; it does not retroactively invent a
  design document neither slice actually had. The purpose of this exception
  is early hospital-user/UX review of a frontend workflow concept ahead of
  PR19A's backend contract — it exists solely to let that review happen
  sooner, not to authorize advancing PR20 or PR21 business implementation,
  and it must never be cited as permission to do so.
- **Scope:** This exception permits only: (1) implementing and reviewing
  PR19B as a **provisional, frontend-only mock skeleton** ahead of an
  approved PR19 design document and ahead of PR19A; and (2) recording
  PR19A/PR19B as the approved Roadmap PR19 slice names. It authorizes
  nothing beyond that. In particular, this exception does **not**
  authorize, and must never be read as authorizing:
  - PR20 (Equipment Master Import) business implementation;
  - PR21 (Legacy Receive and Issue History Import) business implementation;
  - any production legacy-import API implementation;
  - any database schema change;
  - any migration;
  - any backend business-rule change;
  - claiming that the Equipment Master, Receive, or Issue import workflows
    are implemented.

  PR19B's frontend skeleton may represent planned import categories and
  workflow concepts for UX review purposes only; it remains
  **non-authoritative** until reconciled with PR19A's merged, approved
  contract. It does not exempt either slice from ordinary independent
  review, exact-head CI, or Owner merge approval, and it does not
  pre-approve PR19A's eventual design or API contract.
- **Risks:**
  - **Contract divergence risk:** PR19B may be developed against
    provisional assumptions (`frontend/src/types/legacyImport.ts`,
    `legacyImportClient.ts`) that later differ from PR19A's authoritative
    API/domain contract once PR19A is designed.
  - **Branch divergence / integration risk:** because PR19B may progress in
    parallel with PR19A, its branch can diverge from the eventual PR19A
    baseline and require rebase, conflict resolution, or implementation
    changes before it can be considered aligned.
  - **Rework risk:** UI assumptions, mock data shapes, or workflow
    sequencing built into PR19B may need to be modified or discarded
    outright once PR19A's contracts become authoritative.
  - **Premature-completion risk:** the existence of PR19B's UI screens and
    preview category labels (Equipment Master / Receive History / Issue
    History) may be incorrectly interpreted as evidence that Roadmap PR19,
    PR20, PR21, or production legacy-import functionality is complete or
    implemented, when none of it is.
- **Mitigations:**
  - PR19B isolates every mock/provisional contract behind a single named
    seam (`LegacyImportClient`/`MockImportClient`, `types/legacyImport.ts`),
    never scattered inline.
  - PR19B disables real execution outright — no upload, parsing, validation,
    dry-run, or import-confirm action can run.
  - PR19B renders a persistent, visible skeleton banner
    ("ต้นแบบหน้าจอ — ยังไม่มีการนำเข้าข้อมูลจริง") on every screen.
  - PR19B must not claim, in code, tests, comments, or its own PR
    description, that PR20 is complete.
  - PR19B must not claim that PR21 is complete.
  - PR19B must not claim that production legacy-import functionality is
    complete.
  - Mock/provisional behavior must remain clearly and unambiguously
    identifiable as such everywhere it appears (banner, naming, seam
    isolation above) — never silently indistinguishable from real behavior.
  - No production API assumption introduced by PR19B becomes authoritative
    merely by existing in PR19B's code; only PR19A's merged contract is
    authoritative.
  - No backend business rule may be enforced solely by PR19B's frontend
    code — client-side checks in PR19B are UX affordances only, never a
    substitute for server-side enforcement.
  - Contract realignment between PR19B and PR19A's real API is mandatory
    once PR19A is approved, before PR19B (or any follow-up) can be
    considered aligned with production behavior; PR19B must be reconciled
    against the merged PR19A contract before it can be considered complete.
  - Contract/integration tests verifying frontend/backend agreement must be
    added and passing before any production implementation built on PR19B's
    UI is considered ready.
  - Rebase/integration of PR19B against the correct merged PR19A baseline is
    required before PR19B can be finally accepted.
  - Any provisional PR19B behavior found to conflict with PR19A's approved
    contract must be changed or removed in PR19B — PR19A must never be
    distorted or constrained to preserve an obsolete PR19B assumption.
  - An exact-head re-review is required after realignment, the same as any
    other post-fix incremental review.
- **Expiration / Follow-up:**

  This distinguishes two different things that this Exception Record
  governs — they end at different times, and conflating them previously
  made this section internally contradictory once PR19A's design merged
  (Codex finding GOV82-H1R2):

  > The provisional-development permission and the Exception Record have
  > different lifecycles. Provisional-development permission expired when
  > PR19A Design became authoritative. The Exception Record remains open
  > until the provisional PR19B work is reconciled, verified, independently
  > reviewed, and Owner-approved.

  - **Provisional Development Permission: EXPIRED**
  - **Exception Record: CLOSED (2026-08-11) — all seven closure steps
    below are satisfied and recorded.** *(Originally OPEN — pending PR19B
    reconciliation and verification; see Part B below for the closure
    evidence.)*

  ### A. Provisional Development Permission — EXPIRED

  The permission for PR19B to develop against provisional assumptions
  while PR19A had no approved contract to develop against **expired** when
  PR19A's architecture design — its API/session/document model contract —
  was approved and merged (GitHub PR #83, squash SHA
  `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`, see the PR19A bullet above).
  PR19A is now the source of truth for reconciliation.

  From this point forward:
  - PR19B may no longer rely on the original provisional-development
    exception to introduce **new** behavior based on assumptions that
    conflict with the authoritative PR19A Design.
  - Existing PR19B work must now be evaluated against the authoritative
    PR19A Design, not against the provisional assumptions it was originally
    written against.

  ### B. Exception Record — CLOSED (2026-08-11)

  The Exception Record did **not** close merely because PR19A merged. It
  remained **OPEN**, for governance traceability, until the existing
  provisional PR19B work was reconciled and verified. It closes now that
  **all** of the following are satisfied and recorded:

  1. **PR19B rebased/integrated onto the post-PR19A baseline** — done: the
     reconciliation head `71dc97df583f60c3e9f8bccbbcb2e72b0b7307d5` aligned
     PR19B against the merged PR19A1/PR19A2/PR19A3 contracts.
  2. **Provisional frontend assumptions compared against the merged PR19A
     contracts** — done: `frontend/src/types/legacyImport.ts` and
     `legacyImportClient.ts` were reconciled against the real
     `ImportSessionOut` contract (including `failure_reason` and nullable
     `imported_rows`).
  3. **Conflicting provisional behavior modified or removed** — done: mock
     fixtures were rebuilt around `assertImportSessionInvariants()` /
     `buildDetail()` (`frontend/src/utils/legacyImportInvariants.ts`,
     `frontend/src/services/legacyImportFixtures.ts`) to obey the real
     backend's §5/§9/§12/§13/§16/§18 invariants; `LegacyImportResultSummary`
     was rewritten to render truthful, status-specific outcomes instead of
     a single hardcoded success card.
  4. **Required frontend/backend contract and integration tests added and
     passing** — done: `legacyImportFixtures.test.ts` (37 tests) and
     `LegacyImportResultSummary.test.tsx` (8 tests), plus corrected
     `LegacyImportSessionDetailPage.test.tsx` / `LegacyImportListPage.test.tsx`
     fixtures.
  5. **PR19B passes independent Codex exact-head review** — done: final
     reviewed head `5edf1bfd8de7013eb74f300193456c9e5c0f0332` received
     **APPROVE** after two REQUEST CHANGES rounds (PR80-H1/H2, then
     PR80-H1R) were resolved.
  6. **Required CI passes on that exact reviewed head** — done: CI green
     (6/6) on `5edf1bfd8de7013eb74f300193456c9e5c0f0332`.
  7. **Repository Owner approves PR19B for merge** — done: PR19B merged as
     GitHub PR **#80**, real squash-merge SHA
     `04f5bf5c76b51744981d1cc8072c074e604224e9`.

  **All seven steps above are done and recorded; this Exception Record is
  therefore CLOSED.** See "Roadmap PR19B merged: Exception Record closed;
  Roadmap PR19 fully complete" (new entry, below) for the full evidence
  and review chronology.

  If PR19A materially changes semantics that provisional PR19B work
  assumed, the affected PR19B implementation must be modified to match, or
  that provisional work discarded if reconciliation is not practical.
  **PR19B changes; PR19A does not** — PR19A must never be distorted or
  constrained merely to preserve an obsolete provisional PR19B assumption.

  Roadmap PR19 must not be declared complete until every slice (PR19A and
  its own PR19A1/PR19A2/PR19A3 implementation slices, PR19B, and the
  realignment/governance-sync work that follows) is merged — mirroring the
  PR18F-style final governance synchronization already used for Roadmap
  PR18.

- **PR19B scope statement (binding on PR19B and any later PR19B follow-up):**
  frontend-only; mock/skeleton UI; intended for hospital-user workflow
  review; no file upload to any backend; no Excel/CSV parsing; no
  validation execution; no dry-run execution; no import execution; no
  database or migration change. Its import-category labels (Equipment
  Master / Receive History / Issue History) are preview labels aligned to
  future Roadmap PR20/PR21 scope, pulled forward for workflow-review
  purposes only — they are not an implemented capability and must not be
  read as approving or finalizing PR20 or PR21's own design.
- **PR20/PR21/PR22/PR23/PR24 unchanged:** Verified against
  `docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8, and
  this log's own 2026-07-28 entry above — their objectives, boundaries, and
  dependencies (PR20 depends on PR19; PR21 depends on PR19 and PR20; PR22
  depends on PR19–PR21; PR24 is blocked by PR19–PR23) already matched this
  decision and required no renumbering or reconciliation.
- **Source:** Draft PR #80 (`feature/pr19b-import-frontend-skeleton`,
  branched from `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52`), this governance
  PR (branch `docs/pr19-import-roadmap-split-governance`, also branched from
  `729d1aa...`), and GitHub PR #83 (`docs/pr19a-legacy-import-design`,
  likewise branched from `729d1aa...`, merged squash SHA
  `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`) — three genuinely independent
  branches from the same then-latest baseline, confirming in practice that
  "independent-scope" never meant a shared frozen baseline: PR83 did not
  wait for this governance PR to merge, and neither did PR19B. The base
  branch's actual current tip is now `38a21e8...` (PR #83); this governance
  PR has not been rebased onto it (no conflict — PR83 touches only
  `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`, disjoint from this
  PR's files), and this governance PR's own resulting squash SHA becomes the
  next approved base-branch baseline once merged.
- **Status:** Approved governance decision, documentation-only. **Neither
  PR19A nor PR19B is complete or implemented by this entry.** Roadmap PR19
  remains not done; PR19B's own implementation review is tracked
  separately on Draft PR #80. **Update (2026-08-11, this same entry): both
  slices have since merged — PR19A (PR19A1/PR19A2/PR19A3, GitHub PR #84/#85/
  #86) and PR19B (GitHub PR #80, squash SHA
  `04f5bf5c76b51744981d1cc8072c074e604224e9`). Roadmap PR19 (Legacy Import
  Foundation, backend + frontend skeleton) is now fully complete, and the
  Exception Record above is CLOSED.** Concrete production legacy dataset
  import (Equipment Master, Receive History, Issue History) remains
  unimplemented and is future Roadmap PR20/PR21 scope.
- **Consequences:** `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`,
  `docs/audits/04-consolidated-implementation-plan.md` (Group 8),
  `knowledge/CHANGE_HISTORY.md`, `knowledge/CONTEXT.md`, and
  `knowledge/PROJECT_MEMORY.md` are updated alongside this entry to record
  the approved split without claiming either slice is complete. **Update
  (2026-08-11):** the same files are updated again, alongside the new
  "Roadmap PR19B merged" entry below, to record both slices' completion.

## Numbering note — read this first

**Roadmap PR number** and **GitHub PR number** are different sequences and must not be conflated:

- **Roadmap PR number** (PR1, PR2, PR3, ...) is the product-sequencing number from `docs/audits/04-consolidated-implementation-plan.md` Part D. It identifies *what* is being built.
- **GitHub PR number** (`#2`, `#14`, `#16`, ...) is simply this repository's sequential Pull Request counter. It identifies *which review thread* a change went through, and does not line up 1:1 with Roadmap PR numbers — governance/infrastructure PRs (Knowledge Layer v2, the CI/AI-review-workflow PR, this Knowledge & Governance Foundation PR) consume GitHub PR numbers without being numbered items in the original 15-PR Roadmap plan.

For example, **GitHub PR #14 implemented Roadmap PR5** (equipment identifiers). It is unrelated to "Roadmap PR14" (Reliability and Performance Hardening, implemented as GitHub PR #46 and #48 across its PR14A/PR14B slices) — see `docs/ROADMAP.md`.

## Roadmap PR5 — Equipment identifier model (BCM Code / Item No)

- **Decision:** Add `bcm_code` and `item_no` as distinct, canonicalized, unique equipment columns; BCM Code is the only manual-search identifier, Item No is QR-lookup-only and excluded from normal operator responses.
- **Reason:** Resolve the identifier model per `knowledge/adr/ADR-002` through `ADR-004`, retiring the earlier "ME Code" placeholder.
- **Source:** GitHub PR #14; squash commit `099f0b8`; migration `0004_equipment_item_no_bcm_code.py`, later hardened by `0005_identifier_hardening.py`.
- **Status:** Merged.
- **Consequences:** Manual search and QR resolution use distinct code paths; Item No is stripped from operator-facing API responses (`knowledge/architecture/api-information-boundaries.md`).

## Governance — Knowledge Layer v2: identifier/QR architecture and authority hierarchy

- **Decision:** Formally resolve the identifier/QR architecture (`knowledge/adr/ADR-001` through `ADR-004`) and establish the repository's Level 1-7 source-of-truth hierarchy in `docs/PROJECT_PLAYBOOK.md`, ahead of Roadmap PR5's implementation reconciling against it.
- **Reason:** An implementation attempt for Roadmap PR5 was opened before this architecture was resolved; the architecture needed to be settled first so the implementation could be reconciled against a stable target rather than a moving one.
- **Source:** GitHub PR #15; squash commit `89b1f1e`; follow-up fix commit `1433be4` (GOV-H1: full-plan "ME Code" sweep; GOV-H2: authority hierarchy correction; GOV-L1: malformed prose).
- **Status:** Merged.
- **Consequences:** `knowledge/` became the authoritative source for equipment scope, identifier model, BCM manual search, and hospital QR identification, per the Playbook's topic-ownership table.

## Roadmap PR6 — Four-state equipment model

- **Decision:** Collapse the equipment status model to exactly four states (`AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`), adding a `legacy_status` column to preserve prior history.
- **Reason:** Confirmed target model per `docs/audits/04-consolidated-implementation-plan.md` Part A; a fifth "cleaning" state was explicitly rejected (see `docs/ARCHITECTURE_DECISIONS.md`, "No cleaning workflow").
- **Source:** GitHub PR #16; squash commit `9994c27`; migration `0006_equipment_state_model.py`.
- **Status:** Merged, including three review-fix rounds on the same PR before merge:
  - **H1:** Removed the `cleaning` field from the `ReturnRequest` OpenAPI contract — the contract must not expose a concept the system does not track.
  - **H2:** Split dispatch/receipt transitions from manual/administrative status-maintenance transitions into separate transition tables, so manual maintenance can never be used to simulate a dispatch or receipt.
  - **H3:** Closed a direct `AVAILABLE_AT_POOL -> DECOMMISSIONED` skip; decommissioning must pass through `UNAVAILABLE_DEFECTIVE`.
- **Consequences:** See `docs/BUSINESS_RULES.md` ("Four Equipment States", "Dispatch/Return owns transaction lifecycle", "Decommission requires AVAILABLE -> UNAVAILABLE_DEFECTIVE -> DECOMMISSIONED") — all three fix-round findings are now standing business rules, not just review comments.

## Infrastructure — GitHub Actions CI and AI review workflow

- **Decision:** Add required CI (backend dependency install, non-PostgreSQL and PostgreSQL-marked test suites, standalone Alembic upgrade validation, frontend build, whitespace check) and formally document the Claude -> Codex -> Owner review/merge sequence.
- **Reason:** `docs/TECH_DEBT.md` TD-003 ("No required PostgreSQL CI workflow") remained open; Roadmap PR7 was about to begin and needed a reliable, documented CI/review gate first.
- **Source:** GitHub PR #17; squash commit `3a1d30b`; `.github/workflows/ci.yml`; `docs/AI_REVIEW_WORKFLOW.md`.
- **Status:** Merged, including one review-fix round before merge:
  - The PostgreSQL CI job could report green via `pytest.skip()` when the database was unreachable or lacked scratch-database privilege, rather than failing. Fixed with `backend/scripts/postgres_ci_gate.py`, a fail-closed preflight (connect/authenticate/query/scratch-privilege) plus a post-run zero-skips assertion.
  - Added `permissions: contents: read` at the workflow level and `persist-credentials: false` on every checkout step (least privilege; no job needs write access).
- **Consequences:** TD-003 is partially resolved — the required CI workflow now exists and fails closed, but branch protection requiring it has not been enabled (a repository setting, not something a governance PR mutates — see `docs/REPOSITORY_STRATEGY.md`, "Branch protection and ruleset recommendation"). TD-003 should be re-assessed, not silently closed, by whoever next reviews `docs/TECH_DEBT.md`.
- **Limitation discovered during review:** the GitHub Connector used for review submission returned `403 Resource not accessible by integration` when attempting a native `APPROVE`/`REQUEST_CHANGES` review state. See `docs/KNOWN_LIMITATIONS.md` for the two-tier fallback policy this discovery led to (formal browser-submitted `COMMENTED` review preferred; PR Conversation comment as a last resort only). **GitHub-evidence-verified correction:** PR17's own review cycle used the formal fallback, not the last-resort one — both of its reviews (`#pullrequestreview-4731741895` and `#pullrequestreview-4732018565`) are Pull Request Review objects with `state: COMMENTED`, submitted through an authenticated browser session, each with a body stating the substantive decision ("REQUEST CHANGES" then "Substantive decision: APPROVE"). GitHub's PR-Conversation-comments API for PR17 returns zero results — no top-level Conversation comment was ever posted for that review flow. An earlier version of this entry incorrectly described PR17's workaround as a PR Conversation comment; that was wrong and is corrected here.

## Governance — Knowledge & Governance Foundation (this PR)

- **Decision:** Add a compact, current-state documentation/knowledge layer (`docs/PROJECT_WORKFLOW.md`, `BUSINESS_RULES.md`, `DECISION_LOG.md`, `ROADMAP.md`, `REVIEW_CHECKLIST.md`, `KNOWN_LIMITATIONS.md`; `knowledge/PROJECT_MEMORY.md`, `CONTEXT.md`, `CHANGE_HISTORY.md`) that summarizes and cross-references the existing Governance Pack v1.0, rather than replacing it.
- **Reason:** The existing hierarchy (`docs/PROJECT_PLAYBOOK.md` Levels 1-7) is detailed and authoritative but requires reading several documents to reconstruct current state; a single fast-onboarding layer reduces the risk of a future AI session acting on stale or incomplete context.
- **Source:** This PR; branch `docs/pr18-knowledge-governance-foundation`; baseline `3a1d30b4560f77867dfe36e925c1f3ef97d71596`.
- **Status:** Draft, pending review, after multiple Codex review-and-fix rounds. Each round's findings are summarized below in order; see the PR's own review history for exact per-round detail rather than relying on a count here, which is not kept current.
  - **Round 1:** `docs/BUSINESS_RULES.md` presented the approved target `OPEN`/`CLOSED` transaction model (Roadmap PR7) as already implemented. Fixed to separate current implementation (`borrowed`/`returned`/`overdue`, required `borrower_name`, nullable `due_at`/`ward_id`) from the approved target, with an explicit instruction not to implement PR7 ahead of its assigned order. Cleaning wording ("performed during receipt") overstated ordering; fixed to state cleaning may occur before or after the receipt record, is never a state, and needs no separate workflow. `docs/KNOWN_LIMITATIONS.md` used unsupported "silently downgrade" wording for the GitHub connector's review-submission behavior; fixed to describe the actual observed `403` failure. Wording implying GitHub enforces CI as a merge gate was clarified: CI is required by the documented process, not by branch protection, which is not yet enabled. Added the Knowledge Update Policy (this section's own list of files) to `docs/PROJECT_WORKFLOW.md` and `docs/REVIEW_CHECKLIST.md`.
  - **Round 2:** Round 1's own fallback description still conflated a formal browser-submitted `COMMENTED` review with a plain PR Conversation comment, and `knowledge/CONTEXT.md`/`knowledge/PROJECT_MEMORY.md` still contained the original "silently downgrade" wording untouched. Corrected to a two-tier policy across every affected file: a formal `COMMENTED` review submitted through an authenticated browser session is the preferred fallback and does satisfy independent-review evidence; a PR Conversation comment is a last-resort, incomplete status report used only when both connector and browser review submission are unavailable, and must never be treated as completed review evidence by itself.
  - **Round 3:** This entry's own PR17 history (above, "Infrastructure — GitHub Actions CI and AI review workflow") incorrectly described PR17's review workaround as a PR Conversation comment. GitHub evidence (the Reviews and Conversation-comments APIs) shows PR17 actually used two formal `COMMENTED` Pull Request Reviews and zero Conversation comments; corrected. The PR description was also updated to match the current verified wording and to record the CI result for the reviewed head.
- **Consequences:** Every new file is written as a summary that cites its authoritative source and defers to it on conflict — see each file's own "Authority" line. `docs/ARCHITECTURE_GUARDRAILS.md` gained two invariants (no new identifiers, no bypassing dispatch/receipt services) that were true in practice but not previously written down. `AGENTS.md` was trimmed to reference this layer instead of embedding long-form guardrail rationale.

## Roadmap PR7 — Transaction lifecycle model (OPEN/CLOSED)

- **Decision:** Rename `BorrowTransaction.status` from the three-value `borrowed`/`returned`/`overdue` field to an exactly-two-value `TransactionStatus` domain model, `OPEN`/`CLOSED` (persisted lowercase `"open"`/`"closed"`), mirroring `EquipmentStatus`'s `(str, enum.Enum)` shape from Roadmap PR6. `app.crud.transaction.create()` is the sole opener (relies on the column default); a new `app.crud.transaction.close()` is the sole closer; both are called only from `app.services.borrow_service`. A nullable `legacy_status` column preserves history: a row that genuinely had a pre-PR7 value (`borrowed`/`returned`/`overdue`) keeps that exact value; a row already `open`/`closed` before the migration ran (no real pre-PR7 value exists) instead gets a canonical downgrade-compatibility marker equal to its own status — see Round 2 below for why this distinction exists and how it's made unambiguous.
- **Reason:** `docs/HOSPITAL_DOMAIN_MODEL.md`'s confirmed workflow has never included an "overdue" *state*, only `OPEN`/`CLOSED`. This closes the current-vs-planned gap that `docs/BUSINESS_RULES.md` and `knowledge/PROJECT_MEMORY.md` explicitly flagged after Roadmap PR18.
- **Scope note:** This is a deliberate "7a"-style subset of `docs/audits/04-consolidated-implementation-plan.md` Part D's full Roadmap PR7 entry — that plan itself recommends splitting PR7 into a lifecycle-model slice and a `dispatch_type`/`routine_round`/ward-required/field-cleanup slice "if the reviewing team prefers smaller units." `dispatch_type`, `routine_round`, making `ward_id` required, and removing `borrower_name`/`due_at` from the write path remain unimplemented and open for a later PR. See `knowledge/adr/ADR-005-transaction-model.md`'s Context for the full reasoning.
- **Source:** Branch `feature/pr7-transaction-model`; baseline `f4146b380f2fe182516db386de328c2633f72a5f` (Roadmap PR18 squash merge); migration `0007_transaction_lifecycle.py`; `knowledge/adr/ADR-005-transaction-model.md`.
- **Status:** Merged (GitHub PR #19, squash SHA `4041cd2aec412c94f730285d7ba4635e00b095bd`), after two Codex REQUEST_CHANGES rounds (below).
- **Round 1 (Codex REQUEST_CHANGES):**
  - **BLOCKER — notification amplification:** the original implementation kept `app.worker.scheduler.check_overdue_returns`, an hourly job that re-selected every OPEN, `due_at`-passed transaction and created a fresh notification for it on every tick, with no de-duplication — a transaction open and overdue for a month would generate roughly 720 duplicate notifications. The approved MVP business model has no due-date/overdue workflow at all. Fixed by removing the job and its scheduler registration entirely (not by deduplicating a deprecated feature) — see `app/worker/scheduler.py` and `tests/test_borrow.py`'s `test_scheduler_never_registers_the_disabled_overdue_job` / `test_repeated_scheduler_restarts_create_zero_overdue_notifications`.
  - **API contract corrections:** `frontend/src/types/index.ts`'s `TransactionOut.status` still declared `"borrowed" | "returned" | "overdue"`; corrected to `"open" | "closed"`. `docs/03-api-specification.md` and `docs/02-database-schema.md` (both marked "Legacy design reference") still showed the old status literals in example payloads/DDL; corrected to `open`/`closed`. Genuinely historical audit reports (`docs/audits/01-*`, `02-*`, `03-*`) were left untouched — they are dated point-in-time findings about the pre-PR7 code, not live contracts.
  - **Migration 0007 schema convergence:** the pre-PR7 ORM model declared `status` as `String(20)`; because `0001_initial.py` builds its schema from *today's* `Base.metadata` (`docs/TECH_DEBT.md` TD-002), a database whose `0001` ran before this PR's model change got a physical `VARCHAR(20)` column that migration 0007's original version never narrowed — while a database whose `0001` ran after this PR's model change got `VARCHAR(10)` directly. Fixed: `0007`'s `upgrade()` now narrows `status` to `VARCHAR(10)` unconditionally after the remap is verified; `downgrade()` widens it back to `VARCHAR(20)`. New tests assert the resulting width on both a fresh-schema path and a simulated pre-PR7-width upgrade path, and after downgrade.
  - **Migration rollback documentation:** the docstring incorrectly claimed a row originally `overdue` would downgrade-restore to `borrowed`; the executable code has always restored the literal `legacy_status` value (`overdue` stays `overdue`). Docstring corrected to match the code — no behavior change.
  - **Future-OPEN collision preflight:** the pre-migration partial unique index only ever guarded `status = 'borrowed'` rows, never `overdue` ones, so a database could hold one `borrowed` row and one or more `overdue` rows for the same `equipment_id` — remapping both to `open` would collide on the new unique index. `0007`'s `upgrade()` now detects any `equipment_id` with more than one `borrowed`/`overdue` row before writing anything and aborts naming the affected equipment IDs; new PostgreSQL tests cover both the colliding and the ordinary single-row case.
- **Round 2 (Codex REQUEST_CHANGES):**
  - **MAJOR 1 — collision preflight incomplete:** Round 1's preflight only counted `borrowed`/`overdue` rows, but `0007` explicitly leaves a pre-existing `open` row untouched (target-domain passthrough, see preflight step 1) — a database with e.g. one legacy `borrowed` row *and* one already-`open` row for the same `equipment_id` would still collide on the new unique index, uncaught. Fixed: the preflight set (`FUTURE_OPEN_STATUSES`, was `OPEN_EQUIVALENT_LEGACY_STATUSES`) now includes `open` itself — every value that will read as `open` post-migration, not just the two legacy ones. New PostgreSQL tests cover `borrowed`+`open`, `overdue`+`open`, two pre-existing `open` rows for the same equipment (the source schema at revision 0006 permits creating this fixture directly, since the old index never constrained `open` at all), and the single-row success case.
  - **MAJOR 2 — upgrade/downgrade policy inconsistency:** a row already `open`/`closed` before `0007` ran got a NULL `legacy_status` (no entry in `LEGACY_STATUS_MAP`), which meant `upgrade()` could succeed for that database while `downgrade()` — which aborts on any NULL `legacy_status` — could never subsequently run, even with zero genuinely new writes since the upgrade. Resolved with one explicit, documented policy (see the Decision line above and this migration's docstring, "Target-state compatibility policy"): after the legacy remap, every row whose `legacy_status` is still NULL gets `legacy_status` set to its own current `status` — a canonical compatibility marker, never a value from `LEGACY_STATUS_MAP`'s keys (`borrowed`/`returned`/`overdue`), which is exactly what makes a marker distinguishable on read from a genuine preserved legacy value (`legacy_status IN ('open','closed')` = marker; `legacy_status IN ('borrowed','returned','overdue')` = real history). Downgrade code required no change — it already restores `status = legacy_status` verbatim, which now correctly reproduces every row's true pre-migration state, marker or not. The NULL-`legacy_status` abort still fires, unweakened, for a row genuinely created after `0007`'s upgrade (the OPEN/CLOSED-only application never writes `legacy_status`). New PostgreSQL tests cover a pre-existing `open` row and a pre-existing `closed` row each surviving a full upgrade→downgrade round trip with no fabricated history, a single migration run mixing a genuine-legacy row and a target-domain row, and confirmation that a genuinely-new post-upgrade row still fails downgrade as before.
- **Consequences:** See `docs/BUSINESS_RULES.md` ("Dispatch/Return owns transaction lifecycle") and `docs/DOMAIN_MODEL.md` ("Transaction") for the resulting standing rules. The partial unique index enforcing "at most one OPEN transaction per equipment" (`idx_tx_one_active_borrow`) was redefined in the same migration against the new `status = 'open'` predicate. Equipment State Model (`app/models/equipment.py`, Roadmap PR6) is unmodified by this decision. Concurrent-receipt protection (two simultaneous receipts racing on the same OPEN transaction) remains out of scope here and stays Roadmap PR8's explicit responsibility. The OPEN/CLOSED business rule itself (`docs/BUSINESS_RULES.md`) is unchanged by either review round — both rounds are migration-internal correctness fixes, not new business rules.

## Roadmap PR7 (7b slice) — dispatch type, routine round, and write-path cleanup

- **Decision:** Complete Roadmap PR7's remaining scope left out of the 7a lifecycle slice above. Add `DispatchType` (`routine_round`/`on_demand`) and `RoutineRound` (`06:00`/`11:00`/`15:00`/`21:00`) domain enums to `BorrowTransaction`, mirroring `TransactionStatus`/`EquipmentStatus`'s `(str, enum.Enum)` shape and `values_callable` persistence technique. `app.schemas.transaction.BorrowRequest` now requires `ward_id` and `dispatch_type` for every new dispatch, requires `routine_round` exactly when `dispatch_type == routine_round` (rejected via a `model_validator`), and no longer declares `borrower_name`, `due_at`, or `quantity` as accepted fields at all. `TransactionOut` drops `due_at` entirely and makes `borrower_name` nullable (still returned, as read-only history). Migration `0008_dispatch_fields.py` adds the two new nullable columns plus three CHECK constraints (`ck_borrow_transactions_dispatch_type`, `ck_borrow_transactions_routine_round`, `ck_borrow_transactions_routine_round_consistency`) and relaxes `borrower_name` to nullable at the database level.
- **Reason:** `docs/audits/04-consolidated-implementation-plan.md`'s confirmed-requirements table specifies exactly this two-value dispatch-type domain and four-value fixed routine-round schedule; the same acceptance criteria are repeated in `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §12. `ward_id`-required and the `borrower_name`/`due_at`/`quantity` write-path removal complete the confirmed target contract the 7a slice deliberately deferred (see that entry's "Scope note" above).
- **Enum value sourcing:** Both enums use only values confirmed in the source-of-truth audit documents — no value was invented from memory. The four routine-round values are the literal clock times themselves; no named label (e.g. "morning") is confirmed anywhere, so none was introduced. `docs/HOSPITAL_DOMAIN_MODEL.md` notes these fixed times are an explicit MVP simplification, to be replaced by a separately scoped, not-yet-scheduled future "Shift Sessions" change — this PR does not anticipate or partially implement that future model.
- **Historical-data compatibility strategy:** This migration is purely additive — `dispatch_type`/`routine_round` are brand-new nullable columns with no prior value domain to remap, so every existing row trivially satisfies every new CHECK constraint (`dispatch_type IS NULL AND routine_round IS NULL`) and there is no preflight-abort path on upgrade, unlike migration 0007's legacy-status remap. An existing row's `ward_id` is never auto-assigned; `borrower_name`/`due_at`/`quantity` existing values are preserved unmodified and remain readable (`borrower_name` via `TransactionOut`; `due_at`/`quantity` via `app.services.report_service`, which reads both directly from the ORM row). Downgrade mirrors migration 0007's `legacy_status` guard: restoring `borrower_name` to `NOT NULL` is preflighted and aborts, naming the affected row count, if any row has a NULL `borrower_name` (only possible for a dispatch created after this migration's upgrade, under a contract that no longer supplies one) — it never fabricates a value.
- **Source:** Branch `feature/pr20-transaction-fields`; baseline `4041cd2aec412c94f730285d7ba4635e00b095bd` (Roadmap PR7 7a slice squash merge, GitHub PR #19); migration `0008_dispatch_fields.py`; `knowledge/adr/ADR-005-transaction-model.md`.
- **Status:** Merged (GitHub PR #20, squash SHA `d0e888f3095c9a794928a9bd7d68b60907654522`), after one Codex REQUEST_CHANGES round (below).
- **Round 1 (Codex REQUEST_CHANGES):**
  - **MAJOR 1 — removed request fields were silently accepted:** `BorrowRequest` relied on Pydantic/FastAPI's default behavior of silently ignoring unrecognized fields, so a caller could still send `borrower_name`/`due_at`/`quantity` with no error at all — not the same as "removed from the contract." Fixed: `BorrowRequest` (only, not a global `BaseModel` change) now sets `model_config = {"extra": "forbid"}`, so all three are rejected with a 422, exactly like a missing required field. Verified with a parameterized API test asserting 422 plus zero side effects (no transaction, no equipment status change, no audit row) for each field.
  - **MAJOR 2 — migration tests did not reproduce the real pre-migration schema:** The original `test_migration_0008_*` historical-data tests inserted rows after upgrading only to `0007_transaction_lifecycle`, but `docs/TECH_DEBT.md` TD-002 means `0001_initial.py` builds from *today's* live `Base.metadata` — so that "0007" database already had `dispatch_type`/`routine_round` columns and a nullable `borrower_name` from `0001` onward, which real production history at revision 0007 never had. Fixed: the tests were rewritten into one comprehensive test that reconstructs the actual pre-0008 schema by running migration 0008's own real `downgrade()` DDL (upgrade to head, then downgrade to 0007 — raw `ALTER TABLE`, no ORM-metadata dependency), inserts historical rows against that reconstructed schema, upgrades, verifies `ADD COLUMN`/`DROP NOT NULL`/CHECK enforcement/historical preservation, downgrades, upgrades again, and compares the resulting schema against a genuinely fresh-head snapshot.
  - **MAJOR 3 — invalid ward reference misclassified as an equipment conflict:** `borrow_service.borrow()` caught every `IntegrityError` from `transaction_crud.create()`, including a bad `ward_id` foreign-key reference, and blanket-mapped it to 409 `EquipmentNotAvailableError` ("Equipment was just borrowed by someone else") — misleading for a request that never conflicted with anything. Fixed: `ward_id` is now proactively validated via the existing `ensure_referenced_row_exists` helper (the same mechanism `app.api.v1.equipment`/`master_data` already use for their own foreign-key fields), raising 400 `INVALID_INPUT` — the codebase's existing established "bad reference" style, not a new 404/422 convention. `app.core.db_errors._classify` was made public (`classify_integrity_error`) so the remaining `IntegrityError` handler only maps a genuine `idx_tx_one_active_borrow` unique-index collision to the equipment-conflict response; anything else raises `InvalidInputError`. Verified with a PostgreSQL-backed API test.
- **Consequences:** See `docs/BUSINESS_RULES.md` ("Dispatch/Return owns transaction lifecycle") and `docs/DOMAIN_MODEL.md` ("Transaction") for the resulting standing rules, and `docs/ROADMAP.md` for the updated PR7 status (now fully merged, both slices). `frontend/src/pages/BorrowPage.tsx` gained a required ward selector (previously optional) and dispatch-type/conditional routine-round selectors, and lost its borrower-name input — a minimum functional form change, not the full terminology/workflow redesign planned for Roadmap PR11. `frontend/src/pages/ReturnPage.tsx` received a one-line conditional-display fix for the now-nullable `borrower_name`, not a redesign. Concurrent-receipt protection (Roadmap PR8) remains unimplemented and is explicitly still required before pilot deployment — this PR does not touch it.

## Roadmap PR8 (PR8A slice) — Atomic receipt concurrency guard

- **Decision:** Close concurrent-receipt protection (two simultaneous receipts racing on the same OPEN transaction), left open by both slices of Roadmap PR7, at the database level only. `app.crud.transaction.close()` no longer performs an unconditional `UPDATE` guarded solely by a prior Python `status` read; it now performs a single conditional `UPDATE borrow_transactions SET status = 'closed', ... WHERE id = :id AND status = 'open'` and returns a `bool` decided by the statement's affected rowcount (`rowcount == 1` = winner) instead of the mutated ORM object. `app.services.borrow_service.return_equipment()` keeps its existing Python `status != OPEN` pre-check only as a fast-path for a genuine sequential repeat request (not the concurrency guard itself), then calls `close()`: on `False` (loser), the transaction is rolled back before any equipment-status change, status-history row, or audit row is written, and the existing `TransactionAlreadyReturnedError` (409 `TRANSACTION_ALREADY_RETURNED`) is raised — no new error code was introduced. On `True` (winner), the stale in-memory ORM object is explicitly `db.refresh()`d from the persisted row before the equipment transition and response are built, so the response always reflects committed state. The single-commit-after-both-writes pattern from the existing mandatory-audit-atomicity rule is unchanged.
- **Reason:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full Roadmap PR8 entry ("Atomic Single-Operation Equipment Receipt with concurrency guard") requires exactly one winner among racing receipt requests, with zero business side effects for every loser. The pre-existing Python `status` pre-check alone cannot guarantee this under genuine concurrency (two requests can both observe `OPEN` before either writes); only a single conditional `UPDATE` decided by affected rowcount is atomic at the database level.
- **Scope note:** This is a deliberate "8A"-style subset of Part D's full Roadmap PR8 entry, split during implementation planning (`docs/design/PR8_IMPLEMENTATION_PLAN.md`, design-only, uncommitted) following the same PR7a/PR7b precedent ("if the reviewing team prefers smaller units"). PR8A is the database-level concurrency guard only. **PR8B — narrowing the `condition` field to the confirmed binary usable/defective outcome, and distinguishing a race-loss rejection from a genuine repeat-request rejection — is not part of this decision, remains deferred, and has not been started.** No API contract, schema, or frontend change is part of this decision.
- **Source:** Branch `feature/pr8a-atomic-receipt`; baseline `a3085150eabc135322d45c89c16318f0b839a6a3` (post-PR21-24 governance sync, GitHub PR #25); `docs/design/PR8_IMPLEMENTATION_PLAN.md`.
- **Status:** Merged (GitHub PR #26, squash SHA `4820dbaa683f4cb80732406892b7708d2e242d85`), after one Codex REQUEST_CHANGES round (below).
- **Round 1 (Codex REQUEST_CHANGES):** The production concurrency algorithm (a single conditional `UPDATE ... WHERE id = :id AND status = 'open'`, decided solely by affected rowcount) was already correct as submitted. Round 1's findings were about strengthening the deterministic *proof* of that correctness under PostgreSQL testing, not about correcting the concurrency algorithm itself:
  - **HIGH — concurrency matrix did not deterministically force contention:** The original concurrency test matrix issued concurrent requests via plain `asyncio.gather()`, which does not guarantee that multiple requests actually race inside the conditional `UPDATE`'s contested window — a scheduler could serialize them without ever exercising genuine contention, leaving the claim of "exactly one winner under real concurrency" unproven. Strengthened: added an `asyncio.Barrier`-based test-only synchronization wrapper around `transaction_crud.close()` that forces every request in a bounded group to independently observe `OPEN` before any of them proceeds to the real conditional `UPDATE`, so the test provably exercises the contested window rather than merely hoping for it.
  - **MEDIUM — identical request payloads could not prove winner identity or exclude loser overwrites:** Concurrent requests originally used identical or indistinguishable payloads, so a passing test could not actually identify which request won, nor rule out a loser's data silently overwriting the winner's persisted state. Strengthened: added zero-padded unique per-request markers (e.g. `race-marker-003`) plus verification of the persisted row after the race, confirming exactly one winner's marker is present and no loser-side value leaked through.
  - Matrix: the PostgreSQL matrix covers 1, 2, 5, 10, and 50 requests. The 1-request case verifies normal receipt behavior with no concurrency involved. The 2/5/10 cases synchronize the complete burst via the barrier, so every request in those bursts genuinely contends. The 50-request case synchronizes only a bounded subset (below the test engine's default connection-pool capacity) to prove genuine conditional-`UPDATE` contention without exhausting the connection pool; requests outside that synchronized subset may observe either `RECEIPT_RACE_LOST` or `TRANSACTION_ALREADY_RETURNED`, since the test still issues one HTTP burst.
- **Consequences:** Concurrent-receipt protection is no longer an outstanding pilot blocker. No API contract, schema, or frontend change resulted from this decision. `docs/ROADMAP.md` records PR8A as the Completed-table entry and PR8B as still Planned — **Roadmap PR8 as a whole is not complete until PR8B also merges.**

## Roadmap PR8 (PR8B slice) — Receipt outcome contract narrowing

- **Decision:** Replace the receipt endpoint's pre-PR8B four-value free-form `condition` string (`available`/`pm`/`calibration`/`repair`) with a single frozen business term, `receipt_outcome`, restricted to exactly two values: `usable` and `defective` (`ReceiptOutcome`, `app/models/transaction.py`) — the confirmed domain vocabulary `docs/HOSPITAL_DOMAIN_MODEL.md` already used ("receipt outcome: usable"/"receipt outcome: defective"). `ReturnRequest.condition` is removed entirely, not kept alongside a compatibility alias (`ReturnRequest` now also sets `extra: "forbid"`, so a caller still sending `condition` gets a hard 422, mirroring `BorrowRequest`'s Roadmap PR7b precedent). The backend alone maps `receipt_outcome` to an `EquipmentStatus` (`RECEIPT_OUTCOME_TO_STATUS`, `backend/app/services/borrow_service.py`: `usable -> AVAILABLE_AT_POOL`, `defective -> UNAVAILABLE_DEFECTIVE`) — the frontend must never submit a lifecycle state directly. No database migration: `BorrowTransaction.condition_on_return` (the underlying column) is unchanged and still holds genuine pre-PR8B historical values. The response splits into two mutually-exclusive, strictly-typed fields: `TransactionOut.receipt_outcome` (`ReceiptOutcome | None` — a real enum, emitted as an enum in the OpenAPI schema, never a legacy value) and `TransactionOut.legacy_condition_on_return` (`str | None` — the raw pre-PR8B value, when one exists, preserved verbatim and never translated into the new domain).
- **Reason:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full Roadmap PR8 entry, and `docs/design/PR8_IMPLEMENTATION_PLAN.md`'s PR8A/PR8B split, both name "the receipt `condition` field is not the confirmed binary outcome" as an open contract-narrowing gap — the pre-PR8B contract accepted four equipment-status-shaped strings, collapsed to two statuses only inside an internal dict lookup, with nothing at the type level preventing a future caller/typo/new string from being silently misclassified. A binary, typed, business-named contract closes that gap and enforces the frontend/backend separation of concerns `docs/ARCHITECTURE_GUARDRAILS.md` already requires ("Do not bypass the dispatch/receipt services to change equipment status").
- **Scope note:** This decision implements the receipt **contract-narrowing** scope only. The distinguishable race-loss-vs-genuine-repeat error message/code is out of scope entirely and is now named its own separately-tracked slice, **Roadmap PR8 (PR8C slice)** (not started — see Round 1 below and `docs/ROADMAP.md`); both causes still share `409 TRANSACTION_ALREADY_RETURNED` until PR8C lands. This decision itself did not touch the frontend (`frontend/src/services/borrow.ts`/`types/index.ts`/`pages/ReturnPage.tsx`) or any authentication/authorization behavior — both were explicitly out of the assigned task's scope; a follow-up frontend change (GitHub PR #29, see Status below) adopted `receipt_outcome` and was deployed together with this backend (no compatibility layer was kept — see Round 1, finding 1). See `knowledge/adr/ADR-006-receipt-outcome-contract.md` ("Not decided here") for the full statement of what remains open (PR8C).
- **Source:** Baseline `4820dbaa683f4cb80732406892b7708d2e242d85` (Roadmap PR8A squash merge, GitHub PR #26); `docs/design/PR8_IMPLEMENTATION_PLAN.md`; `knowledge/adr/ADR-006-receipt-outcome-contract.md`.
- **Status:** Merged (backend: GitHub PR #28, squash SHA `da4d76a640548e5a1d38ff3d7690695f950c85fe`; frontend follow-up: GitHub PR #29, squash SHA `d3e027b5a4ee7d99b38dfd0d263dc460c74eb5c5`), after one Codex review round on each PR (backend round below; frontend review not itemized in this entry). Both were deployed together per the coordinated-release requirement in ADR-006 Decision 1. `docs/TECH_DEBT.md` TD-006, which tracked the frontend/backend gap, is now `Closed`.
- **Round 1 (Codex review):**
  - **Finding 1 — confirm no deployed client depends on `condition`; document the deployment consequence explicitly.** The original ADR asserted "no external client is known to depend on the old field name" without citing supporting evidence, and did not state the practical deployment consequence of breaking the contract with no compatibility layer. Addressed: `docs/ARCHITECTURE_DECISIONS.md`'s "Browser-first application" decision is now cited as the evidence (no native app shell, `frontend/` is the only client, no third-party/external integration documented anywhere in the repository); ADR-006 Decision 1 and `docs/api/receipt.md` now state explicitly that the backend and the follow-up frontend change **must be deployed together**, not independently, since the breaking change has exactly one known consumer and no compatibility layer exists to bridge a staggered rollout.
  - **Finding 2 — response contract was not semantically binary.** `TransactionOut.receipt_outcome` was typed `str | None` and could read back a genuine pre-PR8B legacy value (`available`/`pm`/`calibration`/`repair`) for an old transaction, contradicting the field's own binary contract — a client parsing it as strictly `usable`/`defective` could receive an unrecognized third shape. Fixed: `receipt_outcome` is now `ReceiptOutcome | None` (`None` for both "not yet received" and "received before this contract"), and a new, separate, mutually-exclusive field, `legacy_condition_on_return: str | None`, carries the raw pre-PR8B value when one exists — never translated or backfilled into the new domain, mirroring `BorrowTransaction.legacy_status`'s existing "distinct field, never fabricated" precedent. New serialization tests cover both a pre-PR8B legacy transaction and a post-PR8B transaction through `TransactionOut.model_validate`.
  - **Finding 3 — OpenAPI/TypeScript verification.** Fixed as a consequence of finding 2: `receipt_outcome`'s new `ReceiptOutcome | None` type is emitted as an enum reference in the generated OpenAPI schema, not an unconstrained string. This repository has no OpenAPI-to-TypeScript code generation pipeline (`frontend/` types are hand-authored) — there is no generated client to verify; `docs/TECH_DEBT.md` TD-006's resolution criteria was updated to require the follow-up frontend PR's hand-authored `receipt_outcome` type to be a `"usable" | "defective"` union, not a plain `string`.
  - **Finding 4 — ambiguous PR8 completion.** The original ADR left the race-vs-repeat gap as an unnamed "other half" of PR8B's description, risking Roadmap PR8 being read as complete once PR8B alone merged. Fixed: that gap is now explicitly named Roadmap PR8 (PR8C slice) in `docs/ROADMAP.md`'s Planned table and "PR8 note", `knowledge/CONTEXT.md`, and ADR-006 — Roadmap PR8 requires PR8A, PR8B, **and** PR8C, all three, to be considered complete.
- **Consequences:** `docs/api/receipt.md` and `docs/api/ERROR_CODES.md` are rewritten to document the frozen, current contract (no longer describing a "pre-PR8" contract), including the two-field `receipt_outcome`/`legacy_condition_on_return` response split. `docs/DOMAIN_MODEL.md` and `docs/BUSINESS_RULES.md` gain cross-references to `knowledge/adr/ADR-006-receipt-outcome-contract.md`. `docs/TECH_DEBT.md` gained TD-006, recording that between this PR's merge and the follow-up frontend PR's merge (#29, which adopted `receipt_outcome` as a `"usable" | "defective"` union), the *repository* temporarily contained a backend revision and a frontend revision that were contract-mismatched and could not be deployed independently — a known, deliberately accepted condition, not an oversight. The coordinated-release requirement meant the two were deployed together, so this repository-level mismatch never became a deployment-level one: coordinated deployment prevented a production outage. TD-006 is now `Closed`. `docs/ROADMAP.md` at the time tracked Roadmap PR8 as three required slices (PR8A/PR8B/PR8C — PR8C not yet started as of this decision; see the PR8C entry below for its completion). No equipment lifecycle state, identifier model, or business rule outside the receipt request/response contract itself changed.

## Roadmap PR8 (PR8C slice) — Race-loss-vs-genuine-repeat receipt rejection

- **Decision:** A losing receipt request (Roadmap PR8A's conditional-close guard) now surfaces one of two distinguishable, stable, machine-readable `code`s in its `409` response instead of always reusing `TRANSACTION_ALREADY_RETURNED`: the existing `TRANSACTION_ALREADY_RETURNED` (`backend/app/core/exceptions.py`) for a genuine sequential repeat — the transaction's `status` was already not `OPEN` when the request evaluated it — and a new `ReceiptRaceLostError` (code `RECEIPT_RACE_LOST`) for a request whose own read observed the transaction as `OPEN` but whose conditional-close UPDATE then lost the race to a concurrent request. Both share HTTP `409` (both are conflicts with current state); only `code`/`detail` differ. `app.services.borrow_service.return_equipment()`'s existing Case A (genuine repeat) and Case B (lost race) branches — already split by PR8A's own guard — now each raise a distinct exception class instead of sharing one. `frontend/src/services/api.ts` gains `apiErrorCode(error)`, and `ReturnPage.tsx` branches on that `code` (never on free-text `detail`) to show a duplicate-receipt message or a distinct race-condition message, falling back to the generic message for any other code.
- **Reason:** `docs/design/PR8_IMPLEMENTATION_PLAN.md` Part G.2 and `knowledge/adr/ADR-006-receipt-outcome-contract.md`'s "Not decided here" both named this as Roadmap PR8's remaining, explicitly deferred gap: a losing request's message conflated "you made a mistake" (a genuine repeat) with "you lost a timing race" (no fault of the requester), which is misleading and gives the operator the wrong recovery instruction (retry vs. refresh).
- **Scope note:** Contract-narrowing/error-distinguishing scope only — no lifecycle state, database schema, migration, or `receipt_outcome` request-contract change. This closes the last of Roadmap PR8's three slices; PR8A (concurrency guard) and PR8B (contract narrowing) were already merged. **Roadmap PR8, as a whole, is now complete.**
- **Codex review round 1 findings, addressed before merge:**
  - **Neutral wording.** The initial `RECEIPT_RACE_LOST` message/frontend copy read "someone else"/ผู้อื่น, which overclaims that another *person* caused the conflict — the backend has no evidence of that; the winning request could be the same user double-clicking, a browser/network retry, or a different staff member, and `received_by_user_id` is never compared between the two requests. Fixed: backend message is `"Another receipt request completed first. Refresh to see the current record."`; Thai frontend copy is `"มีคำขอรับเครื่องอื่นดำเนินการสำเร็จก่อน กรุณารีเฟรชเพื่อดูข้อมูลล่าสุด"`. Code and HTTP status unchanged.
  - **Concurrency test strength.** The 50-request PostgreSQL burst test (`test_concurrent_receipt_burst_produces_exactly_one_winner_on_postgres`) originally only asserted every loser's code was one of the two valid codes above the barrier-synchronization cap, which didn't prove the synchronized subset actually raced the real conditional UPDATE. Fixed: the barrier wrapper now records which specific requests (by unique marker) crossed the barrier, and the test asserts at least `barrier_size - 1` of that exact subset lost via `RECEIPT_RACE_LOST` — proving genuine contention was exercised, not merely that some 409 happened. At or under the barrier cap (concurrency 2/5/10), every loser is asserted to be `RECEIPT_RACE_LOST` exactly, since the entire burst is synchronized.
- **Source:** Branch `feature/pr8c-race-vs-repeat-error`; baseline `4af6a4c623f24718f37241105c90425276e5ce7a` (post-PR8B documentation sync, GitHub PR #30).
- **Status:** Merged (GitHub PR #31, squash SHA `f923f0aec8aa79fb4c33d2c1b0c05c08a057fe17`), after one Codex review round (the two findings above).
- **Consequences:** `docs/api/receipt.md` and `docs/api/ERROR_CODES.md` document `RECEIPT_RACE_LOST` alongside `TRANSACTION_ALREADY_RETURNED`. `knowledge/CHANGE_HISTORY.md` gains an entry recording the distinguishable-code change. Backend tests: a deterministic SQLite test proves the race-loss branch and zero side effects (transaction stays `OPEN`, equipment status unchanged, no audit row) without needing real concurrency; the real-PostgreSQL burst test proves the same property across the 1/2/5/10/50 matrix — the 1-request case verifies normal receipt behavior with no concurrency, the 2/5/10 cases synchronize the complete burst, and the 50-request case synchronizes a bounded subset to prove conditional-`UPDATE` contention without exhausting the connection pool — with zero silent skips (`scripts/postgres_ci_gate.py assert-no-skips`). `docs/ROADMAP.md` now records all three PR8 slices as merged and Roadmap PR8 as fully complete — this is the terminal entry for Roadmap PR8.

## Roadmap PR9 — Audited ward correction (PR9A/PR9B slices)

- **Decision:** Implement a dedicated, audited action to correct a transaction's recorded destination ward — never a generic transaction PATCH, never ward-transfer or current-location tracking — split into a backend slice (PR9A) and a frontend slice (PR9B), following the same lettered-slice precedent as PR7/PR8.
- **Context:** `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §7 ("Ward Recording Rules") identified an unimplemented gap: the system records only the first receiving ward for a dispatch, and that value is normally immutable, but an operator can enter it incorrectly and the mistake may only be discovered after the transaction is `open` or already `closed`. This is correction of historical operational data. It is explicitly not: ward-transfer tracking, current equipment location, a new dispatch, or a transaction/equipment lifecycle transition — no such concept was introduced anywhere in the system.
- **Backend decision (PR9A):** Add `POST /api/v1/transactions/{transaction_id}/correct-ward` (`app.services.borrow_service.correct_ward`) as a dedicated endpoint rather than a generic PATCH, so the request body can never carry an unrelated field (`WardCorrectionRequest {ward_id: UUID, reason: str(1-500, trimmed)}`, `extra: "forbid"`). Concurrency reuses PR8A's shape: a single conditional `UPDATE ... WHERE id = :id AND ward_id IS NOT DISTINCT FROM :expected_ward_id`, decided by affected-row count (`app.crud.transaction.correct_ward`) — a request whose expected `ward_id` is no longer current loses with `409 WARD_CORRECTION_CONFLICT`, a code distinct from Roadmap PR8C's receipt-flow codes. A same-ward submission is rejected as a no-op (`409 WARD_CORRECTION_NOOP`), and no audit entry is written for it. Every successful correction writes exactly one audit row via the canonical PR3 writer (`app.core.audit.record_audit_event`), in the same transaction/commit as the ward change, so a failure writing the audit rolls back the ward change too. The endpoint works identically whether the transaction is `open` or `closed` — there is no lifecycle-status precondition, since this corrects historical data rather than participating in an in-flight workflow step.
- **Authorization decision:** The confirmed 3-role permission matrix (`docs/audits/03-hospital-equipment-pool-workflow-audit.md` §10) grants this capability to Administrator **and** Equipment Pool Staff, but the current 5-role model has no confirmed, evidence-backed equivalent of Equipment Pool Staff — that same audit's §10 note states `biomedical_engineer`/`ward_nurse`/`transport_staff` "have no clear place in this workflow as described." Because ward correction modifies historical operational data, an inferred mapping was rejected as unacceptable; every role other than `admin` was denied with `403` (`app.api.v1.deps.WARD_CORRECTION_ROLES = (ROLE_ADMIN,)`) until Roadmap PR10's Role Model Consolidation landed the confirmed 3-role model and replaced this one constant (now merged — see the Roadmap PR10 entry below). This does not inherit permissions from, and is not derived from, whichever roles dispatch or receipt happen to trust.
- **Frontend decision (PR9B):** Provide two entry points rather than one, since the backend has no lifecycle-status precondition and a mis-recorded ward may only be discovered after receipt: `frontend/src/pages/ReturnPage.tsx` (the OPEN transaction currently being received) and `frontend/src/pages/EquipmentDetailPage.tsx`'s transaction-history section (every OPEN and CLOSED transaction for that equipment, sourced from the pre-existing `GET /transactions?equipment_id=` endpoint — never inferred from the equipment ID or from equipment status-history rows, which carry no transaction ID at all). Both entry points render one shared component pair, `frontend/src/components/WardCorrectionAction.tsx` (ward-list load/error/retry state and the trigger) and `WardCorrectionDialog.tsx` (form, confirmation, submission, and keyboard focus containment), so the mutation, validation, and error-mapping logic exist exactly once rather than once per screen. Visibility is gated by `frontend/src/hooks/useAuth.ts`'s `canCorrectTransactionWard(user)`, a frontend-only mirror of `WARD_CORRECTION_ROLES` — usability only, not a security boundary; every error path (starting with `403`) is still handled explicitly because the backend remains authoritative.
- **Review-driven decisions:** An initial frontend authorization draft inferred a `(admin, ward_nurse, transport_staff)` mapping from dispatch/receipt access; rejected as an unconfirmed inference and replaced with the fail-closed admin-only mapping above, matching the backend exactly. All five current roles (`admin`, `biomedical_engineer`, `ward_nurse`, `transport_staff`, `viewer`) are tested for correct trigger visibility. The mandatory reason's 500-character boundary is tested at exactly 500 (accepted) and 501 (rejected client-side before submission, no silent truncation) characters, trimmed before both validation and submission. Ward-list loading disables the trigger; a load failure shows an explicit error with a working retry, never a silently-unusable enabled button. The dialog's keyboard focus trap covers initial focus, ordinary and wrapped Tab/Shift+Tab, focus that escapes the tracked set, the zero-focusable pending-submission state, Escape (without submitting), and restoration to the exact triggering element on every close path. CLOSED-transaction access was added via `EquipmentDetailPage.tsx`'s cursor-paginated history (`useInfiniteQuery` over the endpoint's existing `next_cursor`), with its own loading/error/retry state distinct from a genuinely empty history. Every documented machine-readable error code (`FORBIDDEN`, `TRANSACTION_NOT_FOUND`, `INVALID_INPUT`, `VALIDATION_ERROR`, `WARD_CORRECTION_NOOP`, `WARD_CORRECTION_CONFLICT`, plus an unknown-code fallback) is covered by table-driven tests.
- **Source:** PR9A — branch `feature/pr9a-ward-correction` (backend); PR9B — branch `feature/pr9b-ward-correction-frontend`, baseline `9cef8411f067b14dd417d3dcd1335567cb669868` (PR9A squash merge). `docs/api/transactions.md`, `docs/api/ERROR_CODES.md`.
- **Status:** Merged. PR9A: GitHub PR #33, squash SHA `9cef8411f067b14dd417d3dcd1335567cb669868`. PR9B: GitHub PR #34, squash SHA `bfe8a42a55d738d3e591ce27145c7918186643ac`, after three review rounds addressing ward-list load state, dialog focus containment (including a pending-submission edge case), and CLOSED-transaction reachability with pagination.
- **Consequences:** Historical ward-recording mistakes can now be safely corrected, with every correction auditable and both OPEN and CLOSED transactions reachable; concurrent corrections are controlled by the same conditional-`UPDATE` pattern PR8A established. Non-admin Equipment Pool operators could not use the correction action until Roadmap PR10 established the confirmed 3-role model and updated both `WARD_CORRECTION_ROLES` and `canCorrectTransactionWard` — a deliberate, temporary trade-off, not an oversight, now resolved (see the Roadmap PR10 entry below). No equipment or transaction lifecycle state, database schema, migration, or dispatch/receipt contract changed in either slice. `docs/ROADMAP.md` now records both PR9 slices as merged and Roadmap PR9 as fully complete — this is the terminal entry for Roadmap PR9.

## Roadmap PR10 — Role Model Consolidation

- **Decision:** Replace the legacy 5-role model (`admin`, `biomedical_engineer`, `ward_nurse`, `transport_staff`, `viewer`) with the confirmed 3-role model — `administrator`, `equipment_pool_staff`, `read_only` — everywhere a role is persisted, checked, displayed, or seeded, closing the gap PR9A's temporary admin-only ward-correction rule was deliberately left open pending.
- **Context:** `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §10 ("Role and Permission Review") confirmed the 3-role model and its full capability matrix, but explicitly flagged that `biomedical_engineer`, `ward_nurse`, and `transport_staff` "have no clear place in this workflow as described" and that mapping any real account holding one of them is "a manual, per-person decision" requiring "a named decision-owner" (`docs/audits/04-consolidated-implementation-plan.md` §14 item 5) — this is why PR9A could not simply extend its role gate to a guessed Equipment Pool Staff equivalent, and why this migration cannot silently auto-map those three roles either.
- **Role representation decision:** One canonical backend representation — `backend/app/models/user.py`'s `ROLE_ADMINISTRATOR`/`ROLE_EQUIPMENT_POOL_STAFF`/`ROLE_READ_ONLY` string constants (the `roles` table itself remains a plain `name`/`permissions` table, not a native enum, unchanged from its pre-PR10 shape) — with Thai display labels kept frontend-only (`frontend/src/hooks/useAuth.ts`'s `ROLE_LABELS`). `app.schemas.master_data.RoleName` is a closed `Literal` of the 3 values, so an unrecognized `role_name` on `POST/PATCH /users` is now rejected at the schema layer (422 `VALIDATION_ERROR`) before the handler's runtime `get_role_by_name` lookup ever runs — a behavior change from the pre-PR10 400 `INVALID_INPUT` for this one case, covered by an updated test.
- **Capability-group decision:** `backend/app/api/v1/deps.py` centralizes four named role tuples — `EQUIPMENT_POOL_OPERATION_ROLES` (administrator + equipment_pool_staff: dispatch, receipt, ward correction, marking equipment defective), `ADMINISTRATOR_ONLY_ROLES` (reactivate, decommission, equipment master-data create/update/delete, master-data create, user/role management, audit-log reads), `VIEW_AND_REPORT_ROLES` (all 3 roles: reports export, preserving the existing pre-PR10 breadth rather than narrowing it), and `WARD_CORRECTION_ROLES = EQUIPMENT_POOL_OPERATION_ROLES` (replacing PR9A's temporary admin-only tuple). Every endpoint's role gate references one of these groups, never an inline ad hoc role list. The one endpoint that cannot be gated by a single static tuple — `POST /equipment/{id}/status`, which covers three distinct capabilities (mark-defective, reactivate, decommission) distinguished only by the request's target status — keeps a coarse `EQUIPMENT_POOL_OPERATION_ROLES` entry gate plus a second in-body check against a new `EQUIPMENT_STATUS_ADMINISTRATOR_ONLY_TARGETS` frozenset, before any database read or side effect.
- **Migration decision (`backend/alembic/versions/0009_role_consolidation.py`):** `admin`→`administrator` and `viewer`→`read_only` are remapped automatically — the only two legacy roles with a confirmed, evidence-backed equivalent. The other three are never auto-mapped; if any user holds one, `upgrade()` requires an explicit `MEP_PR10_ROLE_MAPPING` environment variable (a JSON array of `{employee_code, target_role}` objects, validated for coverage, valid target roles, no duplicates, and real employee_codes, all *before* any role is rewritten) and aborts with a `RuntimeError` naming the unresolved accounts otherwise — never emails, password hashes, or any other sensitive field. As of this revision, this repository's own seed/test fixtures hold zero users on any ambiguous legacy role, so the migration requires no manifest at all to run here; the manifest mechanism exists for a real deployment where such accounts might exist. Every user's pre-migration role name is captured into a new nullable `users.legacy_role_name` column (mirroring `BorrowTransaction.legacy_status`'s established PR7 pattern) before any rewrite, as human-readable provenance only — it is not the downgrade's source of truth (see the review-driven decisions bullet below for the durable snapshot/ownership tables that actually drive lossless restoration). Post-upgrade references do not cause downgrade failure solely because they are new. Downgrade fails closed when unrelated post-upgrade data depends on a confirmed-role row created by migration 0009, because that row cannot be safely removed while referenced — no legacy role is fabricated to make it disappear, and no partial downgrade occurs. References to a confirmed-role row that pre-existed migration 0009 do not by themselves block downgrade; those rows are never deleted and are preserved according to their `confirmed_role_ownership` provenance, subject to the remaining downgrade preflight checks (see the review-driven decisions bullet below for the exact mechanism). A `ck_roles_name_confirmed` CHECK constraint is added last, restricting `roles.name` to exactly the 3 confirmed values as defense in depth. The migration never calls `app.core.audit.record_audit_event` (it runs outside any authenticated request, so there is no real actor to attribute a role change to); every user-facing role change made through the API remains audited atomically with its `role_id` update, unchanged by this migration.
- **Stop-condition research:** Before implementing the migration, this repository's own database state (seed script and every test fixture) was inspected end-to-end and confirmed to hold zero real, non-seed, non-test user accounts, and critically zero users currently on any of the three ambiguous legacy roles anywhere — so the task's stop condition ("real ambiguous-role users exist with no authoritative mapping") did not apply, while the manifest mechanism itself was still built to be genuinely fail-closed for a hypothetical future deployment.
- **Endpoint-level decisions requiring judgment (no exact pre-PR10 precedent):** Equipment master-data create/update (`POST`/`PATCH /equipment`) narrowed from the pre-PR10 `admin`+`biomedical_engineer` gate to Administrator-only, since `biomedical_engineer` has no confirmed equivalent and the workflow audit's §10 matrix leans Admin-only for MVP master data. `GET /borrow/active` widened from a `BORROW_ROLES`+`biomedical_engineer`+`viewer` gate to no role restriction at all (any authenticated user), matching the pre-existing, already-unrestricted `GET /transactions` sibling endpoint — a view/list surface, not a write capability. `POST /return/{id}` (receipt) narrowed from also admitting `biomedical_engineer` to strictly `EQUIPMENT_POOL_OPERATION_ROLES`, since that role has no confirmed equivalent. `app.worker.scheduler._notify_engineers`'s PM/CAL due-date notification recipient list (previously `admin`+`biomedical_engineer`) was updated to `administrator`+`equipment_pool_staff` as a minimal required rename to keep an existing feature compiling and working, not a PM/CAL workflow redesign (out of scope for PR10).
- **Frontend decision:** `frontend/src/types/index.ts`'s `Role` type is now the closed 3-value union. `frontend/src/hooks/useAuth.ts` centralizes every capability check (`canCorrectTransactionWard`, `canMarkEquipmentDefective`, `canManageEquipmentMasterData`, `canReactivateEquipment`, `canDecommissionEquipment`, `canManageUsers`, `canDispatchOrReceiveEquipment`) mirroring the backend groups exactly — usability-only, never a security boundary, exactly like PR9B's `canCorrectTransactionWard` precedent. `AppShell.tsx`'s "จัดการระบบ" nav link now gates on `canManageEquipmentMasterData` (administrator-only, narrowed from the pre-PR10 admin-or-biomedical_engineer check); dispatch/receipt ("ยืม"/"คืน") nav entries are now hidden for Read Only, a new addition (no such gating existed pre-PR10, since Read Only did not exist as a distinct concept before). No new user-management or equipment-status-change UI was built — neither existed before PR10 (`AdminPage.tsx` has no user-management UI, and no screen calls the equipment-status-change endpoint), and building either is a feature addition beyond consolidating existing role checks, so both remain documented, pre-existing, out-of-scope gaps; the corresponding capability helper functions still exist for when that UI is eventually built.
- **Testing decision:** A complete table-driven RBAC matrix (`backend/tests/test_rbac_matrix.py`) exercises every capability group against all 3 roles, including explicit negative tests (unauthenticated caller rejected on every tier; both non-administrator roles denied identically on an administrator-only tier) — not just "some role is denied" smoke tests. `backend/tests/test_ward_correction.py`'s permission matrix was updated from the 5-role temporary table to the confirmed 3-role table (`administrator`→200, `equipment_pool_staff`→200, `read_only`→403), retaining every other existing test unchanged. Migration tests (`backend/tests/test_postgres_integration.py`) cover the safe auto-map, the ambiguous-role manifest's missing/invalid-target/nonexistent-employee_code/duplicate-employee_code abort paths, that no user row is ever deleted, the CHECK constraint, and a full downgrade round trip including the post-upgrade-user abort case — run for real via the `alembic` CLI against a scratch PostgreSQL database, the same pattern established for migrations 0002-0008. Frontend capability tests (`frontend/src/hooks/useAuth.test.ts`) cover every exported capability function across all 3 roles plus a null/undefined user.
- **Review-driven decisions (three iterative Codex review rounds on Draft PR #36, each completed on a new exact head before the next began, all before PR #36 was squash merged, and all against `backend/alembic/versions/0009_role_consolidation.py` only, no other file):** **Round 1** (review 4766143140) found three merge-blockers: no audit provenance for a migration-driven role change, the ambiguous-role manifest could override a non-ambiguous account, and downgrade could overwrite a legitimate post-upgrade role change without being lossless. Fixed by writing one `audit_logs` row per changed user (`user_id` always `NULL`, never a fabricated actor), validating every manifest entry against the named user's *current* role (never just existence), and adding a `user_role_migrations` table that preflights every currently-new-role user before any downgrade write. **Round 2** (review 4769035499) found downgrade's own role restorations were never audited (H1) and recreated a same-named legacy role with a freshly generated UUID and empty permissions instead of the exact original row (H3). Fixed by splitting the audit action into `role_migration_upgrade`/`role_migration_downgrade`, and adding a `role_migration_snapshots` table capturing each legacy role's exact `(id, name, permissions)` — its original primary key, metadata, and its one permission relationship in this schema — before upgrade touches `roles`, so downgrade recreates the exact original row and exact original user-to-role assignment rather than inferring either from a name. **Round 3** (review 4769328243) found downgrade could delete a confirmed-role row (`administrator`/`equipment_pool_staff`/`read_only`) that already existed before this migration's upgrade ever ran, since deletion was scoped by name alone. Fixed by a `confirmed_role_ownership` table recording, per confirmed role, whether it `existed_before_upgrade` or was `created_by_migration`; downgrade's preflight now aborts before any write if a confirmed role has no ownership record, if that record's role id doesn't match the role currently under that name, or if a migration-created role still has a reference from a user this migration did not itself migrate — and it deletes a role only when ownership provenance proves `created_by_migration = true`, matched by exact `role_id`, never a pre-existing row. All three rounds' fixes were pushed to new exact heads on the same Draft PR and re-reviewed before merge — none was discovered or fixed after PR #36 entered the baseline. All three rounds added dedicated PostgreSQL-backed migration tests: 53 total across `test_postgres_integration.py`'s `test_migration_0009_*` suite by the final round, verified against a real PostgreSQL database via the `alembic` CLI, never simulated.
- **Source:** Branch `feature/pr10-role-consolidation`, baseline `bfe8a42a55d738d3e591ce27145c7918186643ac` (Roadmap PR9B squash merge). `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §10; `docs/audits/04-consolidated-implementation-plan.md` Part D (PR10); `docs/BUSINESS_RULES.md` ("Roles and the confirmed 3-role permission matrix").
- **Status:** Merged. GitHub PR #36, squash SHA `53340f6d7d5c8cda685235411b60a57d2d033a7e`, after the three review rounds above.
- **Consequences:** Ward correction's temporary admin-only rule (Roadmap PR9A) is now superseded by the confirmed matrix — Equipment Pool Staff has ward-correction, dispatch, receipt, and mark-defective capability it did not have before. No equipment/transaction lifecycle state, dispatch/receipt/ward-correction request-response contract, database schema unrelated to roles, or CI/config change was part of this PR. Roadmap PR11 (Frontend Terminology and Workflow UI Pass) is now the next planned item. `docs/ROADMAP.md`'s baseline, and the temporary-rule language in the Roadmap PR9 entry above, were updated by the dedicated documentation-only post-merge governance sync that follows this entry — the same pattern used after Roadmap PR9.

## Roadmap PR11 — Frontend Terminology and Workflow UI Pass

- **Decision:** Retire "ยืม"/"คืน" (borrow/return) as user-facing UI terminology everywhere it appeared, and converge consistently on "เบิก"/"รับคืน" (issue/receive back) — the same words the workflow audit's confirmed terminology and this repository's own dispatch/receipt domain vocabulary (`app.services.borrow_service`'s "dispatch"/"receipt" framing, unchanged since Roadmap PR7) had already been converging toward in isolated spots (e.g. `BorrowPage.tsx`'s own dispatch-type label already said "ประเภทการเบิก" before this PR).
- **Context:** `docs/audits/04-consolidated-implementation-plan.md` Part D's PR11 entry required "the full user-facing terminology change and the new dispatch/receipt UI shape in one coordinated pass," with an explicit acceptance criterion: "No 'Borrow,' 'Borrower,' 'Due Date,' 'Overdue,' or 'Loan' terminology remains visible anywhere in the UI; the ward field carries the confirmed caption disclaiming real-time-location tracking." `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §7.1 ("Recommended UI labeling") supplied the exact ward-field label ("Receiving Ward (recorded at dispatch)") and detail-view caption text this PR translated into Thai.
- **Terminology-mapping decision:** "ยืม" (borrow) → "เบิก" (issue); "คืน" (return, as the primary verb) → "รับคืน" (receive back); the equipment noun stays "เครื่องมือ" (never "อุปกรณ์", which the codebase never used). Applied identically everywhere the action appears — navigation (`AppShell.tsx`'s `DISPATCH_NAV_ITEMS`), the dispatch form (`BorrowPage.tsx`: heading, success view, confirm button, error messages), the receipt form (`ReturnPage.tsx`: heading, success view, confirm button, error messages, the transaction-info block's "เบิกเมื่อ"/timestamp line), `EquipmentDetailPage.tsx`'s CTA buttons ("เบิกเครื่องนี้"/"รับคืนเครื่องนี้") and transaction-history heading/loading/error/empty states and per-transaction status/timestamp labels, and the dashboard/reports chart labels ("แนวโน้มการเบิก", "เครื่องที่ถูกเบิกบ่อยที่สุด", "ความถี่การเบิก"). Same action, same wording everywhere — never a second synonym introduced for the same concept.
- **Ward-field decision:** The dispatch form, receipt form, and equipment-detail transaction history all relabel the ward field "หอผู้ป่วยที่รับเครื่อง (บันทึก ณ วันที่เบิก)" ("Receiving ward (recorded at dispatch)") with an accompanying caption disclaiming real-time location tracking ("ระบบบันทึกเฉพาะหอผู้ป่วยที่ส่งเครื่องไปครั้งแรก ไม่ได้ติดตามการเคลื่อนย้ายเครื่องมือในภายหลัง" / on the dispatch form; "หอผู้ป่วยที่แสดงคือหอผู้ป่วยที่รับเครื่อง ณ วันที่เบิกเท่านั้น ระบบไม่ได้ติดตามการเคลื่อนย้ายเครื่องมือในภายหลัง" on equipment detail's transaction history), satisfying the Workflow Audit §7.1 acceptance criterion in full.
- **Deliberately not touched:** `WardCorrectionDialog.tsx`/`WardCorrectionAction.tsx` terminology (already aligned with the Workflow Audit's wording from the PR9 review rounds; high existing test coverage, no ambiguity to resolve, changing it would only add risk). Internal route paths (`/borrow`, `/return`) and function/service/query-key names (`createBorrow`, `listActiveBorrows`, `fetchBorrowTrend`, etc.) — `docs/audits/04-consolidated-implementation-plan.md`'s own numbering-note precedent (item 8) recommends leaving these unchanged for MVP to reduce blast radius; renaming them was never requested and this PR's scope is explicitly UI-presentation only, not an API/routing change.
- **Review-driven decisions (exactly three independent Codex reviews on Draft PR #38, each completed on a new exact head before the next began, all before PR #38 was squash merged):**
  1. **Review `4781057781`** (reviewed head `fc24cb9a60a1663cab37a8149829d38b70faf3c8`, finding **PR11-M1**) found PR11's explicitly mandatory test requirements were unimplemented — no `BorrowPage` component tests existed at all, and no test exercised the dispatch → receipt workflow end to end. Fixed by adding `frontend/src/pages/BorrowPage.test.tsx` (heading/action terminology, ward label/disclaimer, on-demand and routine_round payload shapes, the routine-round conditional field, validation gating, loading state, and both equipment-load and dispatch-submit API error states) and `frontend/src/pages/DispatchReceiptWorkflow.test.tsx`.
  2. **Review `4781138180`** (reviewed head `4a926e185b6d27b9bebdcc7cef118006a8d8cfd0`, findings **PR11-M1R** and **PR11-M2**) found that first workflow test manually swapped the mocked `getEquipment` resolved value between steps (available → issued → available) instead of deriving those states from the dispatch/receipt actions themselves, so the test could still pass even if `createBorrow`/`createReturn` stopped actually changing anything (PR11-M1R); and that the PR description itself had gone stale against the final diff — file count and test totals no longer matched (PR11-M2). Fixed by rewriting the workflow test around one shared, mutable mock store: `createBorrow` is the only thing that flips the store's equipment to `issued_to_ward` and creates the transaction; `createReturn` is the only thing that closes that exact transaction id and flips the store back to `available_at_pool` (and rejects an id it never created, the same way the backend would); every `getEquipment`/`listActiveBorrows`/`listTransactions` response is derived by reading the store; and by refreshing the PR description to the current file/test counts.
  3. **Review `4781151810`** (reviewed head `5d809357d974462e03055db540db030f10c081fc`) recorded **APPROVE**, with no remaining Critical/High/Medium/Low findings.

  All three reviews' fixes were pushed to new exact heads on the same Draft PR and re-reviewed before merge — none was discovered or fixed after PR #38 entered the baseline.
- **Source:** Branch `feature/pr11-frontend-terminology`, baseline `66bdd547937b7741d53b16a98fe74280dee18273` (Roadmap PR10 governance-sync squash merge, GitHub PR #37). `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §3, §7.1; `docs/audits/04-consolidated-implementation-plan.md` Part D (PR11).
- **Status:** Merged. GitHub PR #38, squash SHA `7708190ebf08b7212b7a73ba831263b94434d1eb`, after reviews `4781057781`, `4781138180`, and `4781151810` (Approved) above.
- **Consequences:** No "Borrow," "Borrower," "Due Date," "Overdue," or "Loan" terminology remains visible anywhere in the UI (repository-wide `frontend/src` sweep confirmed at merge time — remaining matches are internal route/function/service identifiers, never rendered UI text). No equipment/transaction lifecycle state, API contract, database schema, migration, or RBAC change was part of this PR. Roadmap PR12 (Inventory Import) is now the next planned item. `docs/ROADMAP.md`'s baseline was updated by the dedicated documentation-only post-merge governance sync that follows this entry — the same pattern used after Roadmap PR9 and Roadmap PR10.

## Governance — GitHub PR #40 classification (Post-PR11 Dashboard UX follow-up)

- **Decision:** GitHub PR #40 ("Dashboard & Equipment Status," a frontend-only Dashboard/quick-actions redesign) is **not** Roadmap PR12. It is classified as an **unnumbered Post-PR11 Frontend Dashboard UX Follow-up**, the same category this file and `docs/ROADMAP.md` already use for infrastructure/governance/documentation work that was never assigned a Roadmap PR number (e.g. GitHub PR #17, #21, #22-#25, #30, #32, #35, #37). Roadmap PR12 remains **Inventory Import**, exactly as `docs/audits/04-consolidated-implementation-plan.md` Part D defines it — unchanged in scope, number, or ordering. Roadmap PR13 ("Search, History, and Reporting Adjustments") is likewise unchanged.
- **Context:** GitHub PR #40's originating task description labeled the work "PR12," which conflicted with this repository's authoritative Roadmap numbering. `AGENTS.md` requires that a real Roadmap-boundary conflict be resolved through a dedicated Governance PR reviewed and approved by the Repository Owner — task-specific instructions cannot silently override or renumber an active Roadmap item. Two independent Codex reviews on GitHub PR #40 (finding PR40-H1: review `4781262010` — initial review, identified PR40-H1; review `4781273707` — follow-up review, blocker remained) blocked that PR from merging under the "PR12" identity for exactly this reason. The Repository Owner then directed this classification: leave Roadmap PR12/PR13 untouched, and treat GitHub PR #40 as unnumbered.
- **Numbering-note precedent applied:** consistent with this file's "Numbering note" (Roadmap PR numbers and GitHub PR numbers are different sequences), an unnumbered GitHub PR is not required to carry a Roadmap PR number at all — the Completed table in `docs/ROADMAP.md` already carries eight such unnumbered rows for prior infrastructure/governance/documentation work. GitHub PR #40 joins that same pattern, under a new "— (frontend)" category tag, once it merges.
- **Scope of this governance decision:** documentation-only. No application code was touched by this Governance PR. GitHub PR #40 itself was not modified, retitled, or rebased by this decision — that is deferred to a follow-up step, to be done only after this Governance PR merges (see `docs/ROADMAP.md`'s "Non-Roadmap work in flight" section for the current interim state).
- **Source:** GitHub PR #40 review history (reviews `4781262010`, `4781273707`, both finding PR40-H1); `AGENTS.md` (Governance PR requirement for Roadmap-boundary conflicts); `docs/audits/04-consolidated-implementation-plan.md` Part D (PR12, PR13 authoritative scope, unchanged).
- **Status:** Merged. GitHub PR #41 (this Governance PR), squash SHA `9de050c04174f0d1be1e82f363db3224e5bfa371`. The follow-up rebase/reclassification step described above is complete: GitHub PR #40 was rebased onto this squash commit, and the obsolete references in its own title, description, code comments, and test descriptions that incorrectly classified the work as "Roadmap PR12" were corrected to reflect its unnumbered classification (legitimate historical references — the review IDs and PR40-H1 finding history documenting how this conflict was raised and resolved — were preserved, not rewritten). It merged as GitHub PR #40, squash SHA `93b6f948a7f6eb60f084fa61966191b5ba13c098`, recorded in `docs/ROADMAP.md`'s Completed table as an unnumbered "— (frontend)" row.
- **Consequences:** Roadmap PR12 (Inventory Import) and Roadmap PR13 (Search, History, and Reporting Adjustments) are unaffected — no scope, dependency, or ordering change to either. GitHub PR #40 has merged and is recorded in `docs/ROADMAP.md`'s Completed table as an unnumbered "— (frontend)" row, not as "PR12."

## Process exception — GitHub PR #40 merge (reviewed head vs. merged head)

- **What happened:** The independent Codex review that approved GitHub PR #40 for merge (Review `4781341003`) was performed against head `8d8b23e7e8a16e8bef14f01883dce475d4a83b7b`. Before the merge was executed, one additional, non-blocking commit was pushed — the PR40-L2 fix (renaming a stale test title from "history" to "report" in `DashboardPage.test.tsx`, suggested as safe-to-fix-opportunistically by that same review) — moving the head to `d173cf1703636fab6e22d848d0ac70c6c57a34a1`. When the PR was then marked Ready for Review (leaving Draft), GitHub re-ran its required status checks on the new head; the assistant's squash-merge attempt at `d173cf1...` was rejected by GitHub with "2 of 2 required status checks are in progress." The Repository Owner then merged GitHub PR #40 directly once those checks completed, producing squash merge commit `93b6f948a7f6eb60f084fa61966191b5ba13c098`.
- **Reviewed head vs. merged head:** Reviewed head `8d8b23e7e8a16e8bef14f01883dce475d4a83b7b` and merged head `d173cf1703636fab6e22d848d0ac70c6c57a34a1` differ by exactly one commit — the PR40-L2 test-title rename. No functional or application-code change was introduced between the reviewed head and the merged head.
- **Owner-approved process exception:** Proceeding to merge at `d173cf1...` rather than waiting for a fresh formal review cycle at that exact head was an explicit Repository Owner decision, made after the assistant flagged the head-SHA mismatch and asked how to proceed. This is recorded as a deliberate, owner-approved exception to the general "reviewed head must exactly match merged head" governance rule — not a silent deviation — so that future reviewers can see why the reviewed head and the final merged head differ for this PR.
- **Final squash merge commit:** `93b6f948a7f6eb60f084fa61966191b5ba13c098`, recorded in `docs/ROADMAP.md`'s Completed table as GitHub PR #40, an unnumbered "— (frontend)" row.

## Roadmap PR12 — Inventory Import (update-only)

- **Decision:** Build the confirmed Administrator-only inventory import workflow — upload a spreadsheet, preview per-row validation results with zero database writes, then commit only valid rows in one transaction — matching rows to existing equipment by canonical BCM Code. Import **updates existing equipment only**; it never creates new equipment and never generates, derives, or synthesizes an `asset_number`. A row whose BCM Code has no match fails validation, directing the operator to create that equipment through the standard Equipment Master workflow first, then re-import to update it.
- **Context:** `docs/audits/04-consolidated-implementation-plan.md` Part D/F's PR12 entry specified the workflow stages, header/row validation rules, the illustrative Asset Status mapping table, and an "update existing" toggle (off by default) alongside an implicit create path for unmatched BCM Codes. The migration (`asset_id`, `raw_source_status` additive columns) and `asset_number`-derivation-from-BCM-Code policy for new rows were both raised to the Repository Owner and approved before implementation began (see the PR body's "Governance-approved design decisions" for the full original approval).
- **Migration decision (`backend/alembic/versions/0010_inventory_import_columns.py`):** Purely additive — `equipment.asset_id` (nullable, plain non-unique index; hospital-wide uniqueness unconfirmed per §14 open question 2) and `equipment.raw_source_status` (nullable, verbatim source-cell text). No `NOT NULL`, no backfill, matching migrations 0002-0009's dialect-gated (`IF NOT EXISTS`), no-runtime-model-import convention.
- **Review-driven architectural reversal (four independent Codex reviews on Draft PR #43, each on a new exact head before the next began, all before PR #43 was squash merged):**
  1. **Review `4781906397`** (reviewed head `a2056806c`, findings **PR12-H1 through H4, PR12-M1**) found the originally-approved policy — setting a new row's `asset_number` to its own canonical BCM Code — violated ADR-002 ("Not merged with, or inferred from, BCM Code or Item No"); the PR body's owner approval could not override an Accepted ADR. Also found: unbounded synchronous upload/XLSX parsing on the async request path with O(rows) sequential per-row queries; update mode validated only Asset ID for cross-record conflicts, not Item No/Serial Number; only BCM Code/Item No were length-validated pre-write, so an overlength Asset ID/Serial Number/Equipment Name/Manufacturer/Model could preview as success then crash commit with a PostgreSQL `DataError`, rolling back the whole batch; and no PostgreSQL-backed test proved migration 0010's real upgrade/downgrade/re-upgrade behavior. Fixed: replaced the BCM-derived `asset_number` with a random `IMPORT-<hex>` placeholder token (still ADR-002-non-compliant, see round 2 below); bounded upload reading, moved XLSX parsing off the event loop via `asyncio.to_thread`, replaced per-row lookups with bulk `IN(...)` queries; added Item No/Serial Number cross-record validation to update mode; added preview-phase length validation for every bounded field; added an initial migration round-trip test.
  2. **Review `4781971425`** (reviewed head `c08eac6`, findings **PR12-H1R, PR12-H2R, PR12-M1R**) found the round-1 migration tests failed on exact-head PostgreSQL CI (`2 failed, 139 passed`) because migration `0001_initial.py` builds its schema from `Base.metadata.create_all()` against the *current* ORM model, so a fresh database upgraded only to `0009_role_consolidation` already had `asset_id`/`raw_source_status` — the tests never proved a genuine historical pre-0010 schema, and after a real downgrade, ORM-based queries raised `UndefinedColumnError`; compressed-XLSX decompression remained unbounded before `openpyxl` touched any content; and the random-placeholder `asset_number` was still fabricated inventory metadata, not an ADR-002-approved absence or assigned value. Resolving the `asset_number` finding required a fresh Repository Owner architectural decision (the original approval had already been superseded by round 1's ADR-002 finding, and the round-1 workaround was itself rejected): **Roadmap PR12 ships update-only** — no create path exists at all, and import never generates an Asset Number under any circumstance; create-from-import is deferred follow-up scope pending a future ADR-governed design for real hospital Asset Number assignment. Also fixed: rewrote the migration tests to deliberately strip the 0010 additions via raw DDL after reaching 0009 (simulating a genuine pre-PR12 deployment), seeding/querying via raw SQL throughout that window; added ZIP-archive-bounds checking (entry count, per-entry/aggregate uncompressed size, compression ratio, permitted entry paths, worksheet/column caps) before `openpyxl` decompresses any content.
  3. **Review `4782840059`** (reviewed head `7c7c2af`, findings **PR12-H1R-GOV/UI, PR12-H5**) found the update-only cutover was not yet coherent everywhere: the authoritative spec (`docs/audits/04-consolidated-implementation-plan.md`) still described a create/update path and an off-by-default update mode; the frontend still had an "update existing" checkbox capable of submitting `update_existing=false`, a value the backend accepted into a batch where nothing could ever succeed (no create path, and a database match would simply be skipped); and the `raw_source_status` audit column was silently whitespace-stripped by the shared cell-parsing helper before persistence, contrary to its verbatim-preservation contract. Fixed: `process_import` now rejects an explicit `update_existing=false` immediately with a clear `400` (the field stays in the request shape for compatibility; the router defaults it to `true`); removed the frontend checkbox and all state driving it, so the service always sends `true`; rewrote the Thai UI copy to state plainly that import only updates existing equipment and creates nothing; updated the authoritative spec's Part D entry and F.1/F.3/F.4/G.4 to state the update-only contract explicitly, including that unmatched BCM Codes are rejected during preview and that create-from-import is deferred scope, not a permanent prohibition; and added a dedicated verbatim-text conversion used only for the Asset Status source cell, with a separately normalized copy driving the status-mapping lookup without ever mutating the persisted value.
  4. **Review `4782986913`** (reviewed head `ee2f97f`) recorded **APPROVE WITH NON-BLOCKING COMMENTS** — two documentation/test-hardening follow-ups (see "Non-blocking follow-ups" below), no remaining merge blocker.

  All four rounds' fixes were pushed to new exact heads on the same Draft PR and re-reviewed before merge — none was discovered or fixed after PR #43 entered the baseline.
- **Non-blocking follow-ups (owner-approved as normal maintenance, not merge blockers):** (1) Part E's "Preserve raw source Asset Status" table row in `docs/audits/04-consolidated-implementation-plan.md` still describes the pre-update-only behavior (populated only for newly-imported rows, existing rows left `NULL`) — to be corrected in the next documentation/governance synchronization pass. (2) A test exercising the omitted `update_existing` multipart field (rather than an explicit `true`) to lock down the router's default-true compatibility behavior — to be added as a small test-only follow-up or bundled with the next related backend PR.
- **Testing decision:** `backend/tests/test_import.py` (53 tests at merge) seeds equipment directly via `app.crud.equipment` for every scenario needing a row to succeed (never through the import endpoints, which cannot create), and covers: header validation, per-row BCM/Item No/Asset ID/Serial Number/Asset Status validation, update-mode cross-record conflicts, upload/ZIP-archive bounds, preview-phase length validation, `raw_source_status` verbatim preservation (leading/trailing/internal whitespace, mixed casing), non-matching-BCM-Code rejection (with and without `update_existing=true`), and exactly-one-audit-entry-per-batch. `backend/tests/test_postgres_integration.py` proves migration 0010's fresh-schema convergence and a genuine historical-0009-schema upgrade/downgrade/re-upgrade round trip via the `alembic` CLI against a real PostgreSQL database.
- **Source:** Branch `feature/pr12-inventory-import`, baseline `0974735f25dc12b71595801a2a32cf97c8c18cb3` (GitHub PR #42 — a documentation-only governance sync recording GitHub PR #40's merge and the GitHub PR #39/#41 baseline chain, not itself the Roadmap PR11 governance sync; that was GitHub PR #39, squash-merged before Governance PR #41 classified GitHub PR #40 and PR #42 recorded both). `docs/audits/04-consolidated-implementation-plan.md` Part D (PR12), Part F (§10); `knowledge/adr/ADR-002-identifier-model.md`.
- **Status:** Merged. GitHub PR #43, squash SHA `94554a3a2ce6812f8fca6ab22455cd04384a29e6`, after reviews `4781906397`, `4781971425`, `4782840059`, and `4782986913` (Approve with non-blocking comments) above.
- **Consequences:** Inventory Import cannot create new equipment in its current form — every row must already exist (matched by BCM Code) before it can be imported/updated; this is documented directly in the authoritative spec, not only in the PR description. No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or existing API contracts (aside from `update_existing=false` now returning `400` instead of being silently accepted). Roadmap PR13 (Search, History, and Reporting Adjustments) is now the next planned item. `docs/ROADMAP.md`'s baseline was updated by the dedicated documentation-only post-merge governance sync that follows this entry — the same pattern used after Roadmap PR9, PR10, and PR11.

## Roadmap PR13 — Search, history, and reporting adjustments

- **Decision:** Finalize BCM-Code-first search/scan priority (`knowledge/adr/ADR-003-bcm-manual-search.md`), add dispatch-type/round-aware history filtering, and remove MVP-irrelevant dashboard elements (PM/CAL widgets) in favor of a read-only "days since dispatch" indicator, per `docs/audits/04-consolidated-implementation-plan.md` Part D's PR13 entry.
- **Context:** Before writing any new search code, `app/crud/equipment.py`'s existing `search_bcm` (shipped in Roadmap PR5) was checked against every ADR-003 requirement — partial/prefix-optional matching, exact-match-first ranking, bounded results, minimal-disclosure suggestions (internal ID + BCM Code only), empty/short-query handling — and found already fully compliant, with existing test coverage in `backend/tests/test_equipment.py`. No new search code was written; this PR's actual scope is the two items ADR-003 did not already cover: history filtering and the dashboard cleanup.
- **What was built:** `dispatch_type`/`routine_round`/`from_date`/`to_date` query-parameter filters on `GET /transactions` (`app/crud/transaction.py`'s `search()`, `app/api/v1/transactions.py`), combinable with the existing `ward_id`/`equipment_id`/`status` filters; removal of `pm_due_soon`/`cal_due_soon` from `DashboardSummary` (`app/schemas/dashboard.py`, `app/services/dashboard_service.py`) — `DashboardPage.tsx` has never rendered them since the unnumbered Post-PR11 Dashboard PR (GitHub PR #40); and, on `EquipmentDetailPage.tsx`'s existing per-equipment transaction history (the dashboard itself carries no per-transaction history surface after PR40), new filter controls plus dispatch-type/round distinguishability per row (satisfying Part H's "an on-demand dispatch must be distinguishable from a routine dispatch in history" acceptance criterion) and a read-only, client-computed "days since dispatch" indicator shown only for OPEN transactions.
- **Review-driven correctness fix (two independent Codex reviews on Draft PR #45, each on a new exact head before the next began, both before PR #45 was squash merged):**
  1. **Review `4783120601`** (reviewed head `7c1f2c86a15aebdc2404564d9ee7f4c4dacfb180`, finding **PR13-M1**) found `transaction_crud.search()`'s date-range upper bound — computed as `to_date + timedelta(days=1)` — could raise `OverflowError` for `to_date=9999-12-31` (Python's `date.max`), an ordinary, syntactically valid ISO date string a client can send; this would have surfaced as an unhandled `500`, not a clean validation response. The same review found a reversed range (`from_date` after `to_date`) was silently accepted and simply returned an empty page. Fixed: the upper bound is computed as `datetime.combine(to_date, time.max)` instead of incrementing the date — always representable for any valid `date`, never overflows; a reversed range is now rejected explicitly with a structured `400` (`INVALID_INPUT`) at the API boundary, before the request reaches `search()`. Regression tests added for `date.max`/`date.min` bounds, reversed ranges (including the extreme combination of both), equal start/end dates, and omitted-date behavior left unchanged.
  2. **Review `4783200709`** (reviewed head `07b8c6293ff6ba0b80d9decf579f68b9d1bdaa49`) confirmed PR13-M1 resolved and recorded **APPROVE WITH NON-BLOCKING COMMENTS** — one non-blocking item (stale PR description/evidence — test counts, CI-pending wording), addressed by refreshing the PR description before merge; no remaining merge blocker.

  Both rounds' fixes were pushed to new exact heads on the same Draft PR and re-reviewed before merge — none was discovered or fixed after PR #45 entered the baseline.
- **Testing decision:** `backend/tests/test_transaction_search.py` (new, 16 tests) covers dispatch-type/routine-round/date-range filtering individually and combined with existing filters, dispatch-type persistence through receipt/closing, and the date-range edge cases above (`date.max`/`date.min`, reversed ranges, equal dates, omitted dates). `backend/tests/test_equipment.py`'s dashboard-summary test was tightened to assert the exact response-key set (no `pm_due_soon`/`cal_due_soon`). Frontend: `EquipmentDetailPage.test.tsx` gained coverage for the new filter controls, dispatch-type distinguishability, and the days-since-dispatch indicator; `DashboardPage.test.tsx`'s fixtures and stale comment were updated to match the schema change.
- **Source:** Branch `feature/pr13-search-history-reporting`, baseline `94554a3a2ce6812f8fca6ab22455cd04384a29e6` (Roadmap PR12 merge, GitHub PR #43). `docs/audits/04-consolidated-implementation-plan.md` Part D (PR13), Part H (acceptance criteria); `knowledge/adr/ADR-003-bcm-manual-search.md`.
- **Status:** Merged. GitHub PR #45, squash SHA `8f7ef12e1660b35021df64fc9a529495cca77e49`, after reviews `4783120601` and `4783200709` (Approve with non-blocking comments) above.
- **Consequences:** `GET /transactions` gained four optional query-parameter filters (backward-compatible for any client that omits them); `DashboardSummary` intentionally no longer returns `pm_due_soon`/`cal_due_soon` (no active client consumed them). No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or the database schema — no migration. Roadmap PR14 (Reliability and Performance Hardening) is now the next planned item. `docs/ROADMAP.md`'s baseline was updated by the dedicated documentation-only post-merge governance sync that follows this entry — the same pattern used after Roadmap PR9, PR10, PR11, and PR12.

## Roadmap PR14 (PR14A slice) — Reliability Correctness

- **Decision:** Treat Roadmap PR14 ("Reliability and Performance Hardening") as an Epic implemented through multiple focused slices rather than one broad PR, following the same lettered-slice precedent as PR7/PR8/PR9. **PR14A** is scoped to exactly three reliability-correctness concerns identified by `docs/audits/02-backend-architecture-audit.md`: PATCH nullable-field correctness (Finding 4.1), the scheduler notification N+1 (Finding 16.1), and a transaction boundary audit (Findings 6.1/7.1). Operational Logging (part of PR14's original consolidated scope) is deferred to Roadmap PR15; Pagination Performance is deferred to a later PR14B, gated on EXPLAIN ANALYZE evidence of a real query-plan problem rather than a document-only finding. No workflow redesign, no ADR changes, no schema/migration change.
- **Context:** `docs/audits/04-consolidated-implementation-plan.md` Part D's PR14 entry originally bundled commit-boundary centralization, `COUNT(*)` removal, the scheduler N+1 fix, and the PATCH null-clearing fix into one batch. Before implementation, the Repository Owner narrowed this: `COUNT(*)` must remain unchanged (API compatibility — no pagination-performance change may ship without EXPLAIN ANALYZE evidence first), and no PR may contain more than one architectural concern.
- **What was built (`app/crud/equipment.py::update()`, `app/crud/user.py::update()`):** Both previously used a single-pass `if value is not None: setattr(equipment_or_user, key, value)` loop — which silently discarded *every* explicit-null PATCH request, on every field, not only the ones that should have rejected it. Rewritten as a two-pass validate-then-mutate: pass 1 rejects an explicit null on any field the domain model requires to be non-null (`equipment_name`; `full_name`, `is_active`, both `nullable=False` in the database) with `400 INVALID_INPUT`, before any mutation; `bcm_code`/`item_no` (`NON_CLEARABLE_IDENTITY_FIELDS`, ADR-002 canonical identity fields) are also explicitly rejected on null — previously a silent no-op that could leave a misleading audit record (payload shows the submitted null, persisted value unchanged) — this makes the existing non-clearable contract explicit without altering ADR-002; non-null updates to these fields are unaffected. Because the raise happens before any `setattr` and before the caller reaches `record_audit_event`, a rejected request produces zero audit events and zero mutation. Pass 2 then applies every remaining key/value pair unconditionally — this is the actual bug fix: `brand`, `model`, `pm_due_date`, `cal_due_date`, `category_id`, `department_owner_id`, `current_location_id`, `serial_number` (Equipment), and `phone` (User) can now genuinely be cleared via PATCH null. Blank/whitespace-only string validation for `equipment_name`/`full_name` is explicitly out of scope — deferred to a future focused PR.
- **What was built (`app/worker/scheduler.py::check_pm_cal_due()`):** Previously re-queried the notification-recipient list once per due equipment row (N+1). Now queries PM-due and CAL-due equipment first; if both sets are empty, exits immediately with zero recipient queries; otherwise loads the recipient list exactly once and reuses it for every notification. No change to notification content, recipient role/active-status filtering, or the commit boundary shape (still one commit per run).
- **What was built (transaction boundary audit, `docs/audits/05-pr14a-transaction-boundary-audit.md`):** Every `await db.commit()` call site across `app/api`, `app/services`, `app/worker`, and `app/scripts` (16 sites total, plus the shared best-effort-commit helper) was inspected and categorized into four buckets: ordinary request/business commits (15 sites — one commit per successful request, closing a business mutation and its audit row together); the scheduler commit (one per scheduled run, its own session); the authentication-specific best-effort commit (`app/core/audit.py::commit_best_effort`, 4 call sites in `app/services/auth_service.py` — a successful login's commit closes both the `last_login_at` update and the `login_success` audit row together, and deliberately swallows a commit-time failure so a transient audit-subsystem problem can never turn a legitimate authentication outcome into an unrelated 500); and the seed/script commit (`app/scripts/seed.py`, a one-shot operator-run script, not reachable from the running application). Conclusion: no atomicity drift was identified; PR14A intentionally leaves the existing caller-owned commit architecture unchanged; structural transaction-management changes remain deferred and would require a separate architecture review. `app/db/session.py::get_db()`'s docstring now states only its actual guarantee — closing an uncommitted session rolls back the transaction — without implying automatic commit, automatic recovery, or a substitute for explicit rollback after a caught database error.
- **Review-driven correctness fix (one Codex review round on Draft PR #46, before the PR was squash merged):**
  1. **Review at reviewed head `e099309`** — the substantive review decision was **REQUEST CHANGES** (surfaced by GitHub as `COMMENTED` only because the reviewing account owns the PR) with four findings: (a) the `User.phone`-clearing regression test asserted only HTTP 200, which the pre-PR14A silent-no-op implementation could also return, so it did not actually prove persisted state changed; (b) the transaction-boundary audit had swapped the login-success/login-failure line references for `commit_best_effort` and omitted that the success-path commit also closes the `last_login_at` update, not only the audit row; (c) the PR description claimed "no API or data impact," which is inaccurate — PATCH null semantics changed observably; (d) `IMMUTABLE_IDENTITY_FIELDS` was a misleading name, since non-null updates to `bcm_code`/`item_no` are unaffected — only null-clearing is rejected. All four were fixed on a new exact head: the phone test (and the equivalent equipment `brand`-clearing test) now assert a direct DB re-read of the persisted value plus the audit row's `after` payload, not HTTP 200 alone; the audit doc's line references were corrected and the `last_login_at` detail added; the PR description gained explicit "API behavior impact," "Data impact," and "Rollback limitation" sections (code rollback does not un-clear a value a client legitimately cleared while PR14A was deployed); the constant was renamed to `NON_CLEARABLE_IDENTITY_FIELDS`. CI (141 tests, zero skips, including PostgreSQL) was green on the reviewed head both before and after the fix.

  The fix was pushed to a new exact head on the same Draft PR before merge — not discovered or fixed after PR #46 entered the baseline.
- **Non-blocking follow-ups (recorded, not merge blockers — candidates for a future small test-only PR or bundling with PR14B):** (1) Explicit PATCH null-clearing regression coverage was added for one representative nullable field per model (`Equipment.brand`, `User.phone`); the remaining nullable fields sharing the same pass-2 code path (`Equipment.model`, `pm_due_date`, `cal_due_date`, `category_id`, `department_owner_id`, `current_location_id`, `serial_number`) are covered by the shared CRUD-level logic but do not each have a dedicated end-to-end regression test. (2) A regression test asserting the two-pass ordering itself — a single PATCH request mixing a valid clear on one field with a rejected null on another (e.g. `{"brand": null, "equipment_name": null}`) — to lock down that pass 1 validates the *entire* payload before pass 2 mutates *anything*, not just that each field independently behaves correctly in isolation. (3) The blank/whitespace-only string question for `equipment_name`/`full_name`, explicitly deferred above, needs its own decision and test suite whenever it is picked up.
- **Testing decision:** New/strengthened tests in `backend/tests/test_equipment.py` (nullable-field clearing verified via PATCH response, a fresh GET, a direct DB re-read, and `audit.after_data`; identity-field null rejection with zero mutation and zero audit event); new `backend/tests/test_users_crud.py` (same pattern for `User.phone`/`full_name`/`is_active`); new `backend/tests/test_scheduler.py` (zero due rows → zero recipient queries; any due rows → exactly one recipient query; notification count == due rows × active recipients; inactive users and unrelated roles excluded; PM/CAL content unchanged; equipment outside the due horizon produces nothing).
- **Source:** Branch `feature/pr14a-reliability-correctness`, baseline `8f7ef12e1660b35021df64fc9a529495cca77e49` (Roadmap PR13 merge, GitHub PR #45). `docs/audits/02-backend-architecture-audit.md` Findings 4.1, 6.1, 7.1, 16.1; `docs/audits/04-consolidated-implementation-plan.md` Part D (PR14).
- **Status:** Merged. GitHub PR #46, squash SHA `ddd17b180c06a4fd2421f4886c0568876498abb2`, after the REQUEST CHANGES review above was fully addressed.
- **Consequences:** `PATCH /equipment/{id}` and `PATCH /users/{id}` now treat an explicit null observably differently from an omitted field — an intentional, documented API behavior change (see the PR description's "API behavior impact"/"Data impact"/"Rollback limitation" sections); routes and response schemas are unchanged. No schema or migration change. No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or the database schema. Roadmap PR14B (Pagination Performance) is now the next planned item, gated on EXPLAIN ANALYZE evidence before any design work begins; Operational Logging remains deferred to Roadmap PR15. `docs/ROADMAP.md`'s baseline was updated by the dedicated documentation-only post-merge governance sync that follows this entry — the same pattern used after Roadmap PR9, PR10, PR11, and PR12.

## Roadmap PR14 (PR14B slice) — Pagination Performance

- **Decision:** Ship the pagination-performance slice deferred by PR14A, strictly evidence-gated: no index or pagination-logic design work was permitted to begin without `EXPLAIN (ANALYZE, BUFFERS)` evidence of a real query-plan problem gathered first (`docs/audits/06-pr14b-pagination-index-evidence.md`). Scope explicitly limited to database indexes, migration, PostgreSQL verification, and regression tests — no API behavior change, no pagination-algorithm redesign, no `COUNT(*)` optimization, no endpoint contract change (Repository Owner "Architecture Approval — PR14B").
- **Context:** `docs/audits/02-backend-architecture-audit.md` Finding 5.2 (unindexed first-page/cursor pagination queries) and Finding 5.2's `COUNT(*)` note motivated this slice, but the Repository Owner required the evidence to be gathered against the literal queries `app.crud.equipment.search()`/`app.crud.transaction.search()` issue, at a stress scale (200,000 `equipment`/1,000,000 `borrow_transactions` rows, realistic non-clustered `created_at` timestamps spread over ~2 years — a first pass using tightly-clustered batch-insert timestamps was discarded as misleadingly pathological for deep-cursor measurement) before any code was written, plus two additional binding conditions: (1) verify PostgreSQL actually chooses the new index for each representative query, not merely that the index exists; (2) avoid ORM/migration drift, since migration `0001_initial.py` reflects current SQLAlchemy model state at run time (TD-002) rather than a frozen historical snapshot; (3) make an explicit, documented deployment-safety choice between plain `CREATE INDEX` (maintenance window) and `CREATE INDEX CONCURRENTLY` (non-atomic, autocommit-block build) rather than leaving it implicit.
- **What was built (`backend/alembic/versions/0011_pagination_ordering_indexes.py`):** Two composite `(created_at DESC, id DESC)` btree indexes — `ix_equipment_created_at_id` on `equipment`, `ix_borrow_transactions_created_at_id` on `borrow_transactions` — matching the literal `ORDER BY` clause both search functions already issue for cursor pagination. `CREATE INDEX CONCURRENTLY` was chosen over plain `CREATE INDEX`: `equipment`/`borrow_transactions` are actively read/written during live hospital-equipment-pool operation, and a plain `CREATE INDEX`'s `SHARE` lock (blocks writes for the full build duration; does **not** block ordinary reads) was judged less acceptable than `CONCURRENTLY`'s non-atomic, longer build — both statements run inside `op.get_context().autocommit_block()`, since `CREATE INDEX CONCURRENTLY` cannot execute inside a transaction block. Deliberately not declared on the SQLAlchemy models (`app/models/equipment.py`, `app/models/transaction.py`) — an ORM `index=True` would make a fresh install's `0001_initial.py` create the index too, racing this migration's own `CREATE INDEX ... IF NOT EXISTS` for the same name (the same pattern already used for the migration-0004 GIN trigram indexes). Migration `0011` is therefore the sole source of truth for both indexes on every path (fresh install, historical upgrade, downgrade, re-upgrade), each verified locally against real PostgreSQL 16 before being captured as a regression test.
- **Evidence (`docs/audits/06-pr14b-pagination-index-evidence.md`):** First-page queries dropped from 45.5-205.5ms (sequential/parallel scan + sort) to under 1ms (index scan, no sort node) at the evidence scale. **Honestly-reported limitation, not hidden:** the cursor `WHERE` clause (`created_at < :cursor OR (created_at = :cursor AND id < :cursor_id)`) is a disjunctive condition PostgreSQL cannot translate into a single sargable index-range boundary against a plain composite index — only `created_at <=` is pushed into an `Index Cond`; the rest becomes a `Filter` walking every row in range. Measured crossover point ≈75,000-100,000 rows past page one, beyond which the index makes deep-cursor pagination *slower*, not faster (up to 2,621ms at 500,000 rows deep, versus a flat ~146ms baseline without the index). Accepted, not fixed, because this system's confirmed real-world scale ("low hundreds of devices, thousands of transactions per year") never puts a real user 75,000+ rows deep in a paginated list; fixing it would be a pagination-logic redesign, explicitly out of scope for this slice.
- **Review-driven correctness fix (two Codex review rounds on Draft PR #48, each on a new exact head, before the PR was squash merged):**
  1. **Round 1 (merge-blocking, "PR48 cannot be merged yet"):** three required findings. **PR14B-H1 (detect existing invalid indexes / fail closed):** the original migration used a bare `CREATE INDEX CONCURRENTLY IF NOT EXISTS`, which cannot distinguish a genuinely completed index from one left `INVALID` by an interrupted build (process killed, connection lost, deadlock, or a genuine build failure) — both satisfy `IF NOT EXISTS`, so a naive retry would silently skip forever and Alembic would record the migration as successful while the intended index stayed unusable. **PR14B-M1 (interrupted/retry regression test):** required real PostgreSQL coverage proving retry safety, not just presence. A related requirement, **planner assertion**, required verifying the PostgreSQL planner actually selects the index (not merely that it exists) independently for both tables. **PR14B-L1 (lock documentation):** the migration's docstring incorrectly described a plain `CREATE INDEX`'s lock as blocking "all reads and writes"; corrected to state a `SHARE` lock blocks writes only, ordinary reads remain available. The Repository Owner explicitly directed **fail-closed over auto-repair** for the invalid-index case: an automatic drop/rebuild could mask an underlying deployment problem the migration has no way to diagnose (deployment cancellation, I/O failure, or a concurrent operation), whereas failing loudly with a clear error lets an operator inspect and decide — prioritizing data correctness and auditability over automatic recovery. Fixed by adding `_ensure_index_concurrently()`: before treating any existing same-named index as "already done," it reads `pg_indexes.indexdef` and `pg_index.indisvalid`/`indisready` (via `to_regclass(:name)`, not a `::regclass` cast, which hit an asyncpg bind-parameter syntax error); if the index is invalid, not ready, or valid-but-differently-defined, the migration raises `RuntimeError` explaining the detected state and the exact recovery step (`DROP INDEX CONCURRENTLY IF EXISTS ...`, then re-run) — following the same `raise RuntimeError(f"Migration XXXX aborted: ...")` convention already used ~20 times in migration `0009_role_consolidation.py`. All four states (no existing index; existing valid+matching; existing invalid/not-ready; existing valid-but-mismatched) were manually exercised against a live PostgreSQL 16 instance before being captured as regression tests, including `test_migration_0011_interrupted_concurrent_build_fails_closed_not_silent_skip` (a real `CREATE INDEX CONCURRENTLY` build, manually invalidated to reproduce an interrupted-build catalog state, confirms the rerun fails loudly with no partial application, then confirms the documented drop-and-rerun recovery converges) and `test_migration_0011_mismatched_definition_fails_closed`, plus a new `test_migration_0011_planner_uses_the_new_index_for_first_page_transaction_query` paralleling the existing equipment planner assertion.
  2. **Round 2:** recorded APPROVE WITH NON-BLOCKING COMMENT — one finding, **PR14B-L2**, that the PR description still described the superseded Round 1 behavior (`IF NOT EXISTS` without invalid-index detection, six tests, a stale 614-test count). Fixed by rewriting the description's "Deployment safety" and "Test plan" sections to describe `_ensure_index_concurrently()`, the fail-closed invalid/not-ready/definition-mismatch handling, the drop-and-rerun recovery path, all nine PR14B migration tests, and the exact-head CI counts (617 total: 467 non-PostgreSQL + 150 PostgreSQL). No code change required for Round 2; the review confirmed Round 1's `PR14B-H1`/`PR14B-M1`/`PR14B-L1` findings fully resolved.
- **Testing decision:** Nine PostgreSQL-marked regression tests in `backend/tests/test_postgres_integration.py`: fresh-install convergence; historical-upgrade/downgrade/re-upgrade round trip; index column order/direction inspected directly via `pg_indexes.indexdef` (SQLAlchemy's generic reflection does not reliably report index column direction); planner assertions for both `equipment` and `borrow_transactions` first-page queries (`Index Scan` present, no `Sort` node); cursor-pagination result-set completeness (120 rows, full traversal, no duplicates/gaps, matches unpaginated order); explicit `COUNT(*)` non-regression check; the interrupted-build fail-closed-with-recovery test; and the mismatched-definition fail-closed test.
- **Source:** Branch `feature/pr14b-pagination-ordering-indexes`, baseline `4d891ac8f9f1cc1ada45347d384d06fde705a97a` (Roadmap PR14A governance sync merge, GitHub PR #47). `docs/audits/02-backend-architecture-audit.md` Finding 5.2; `docs/audits/04-consolidated-implementation-plan.md` Part D (PR14); `docs/audits/06-pr14b-pagination-index-evidence.md`.
- **Status:** Merged. GitHub PR #48, squash SHA `82e289d40811b413659e7303a1690b66275e9759`, after both review rounds above were fully addressed.
- **Consequences:** No API, pagination-logic, or `COUNT(*)` change — confirmed by the diff itself (migration + tests + evidence doc only). `equipment`/`borrow_transactions` first-page and representative-filtered queries now use the new indexes where the planner chooses them (verified structurally, not assumed); a documented, accepted deep-cursor-depth limitation exists beyond this system's confirmed real-world scale. **Roadmap PR14 (both PR14A and PR14B slices) is now fully complete.** Roadmap PR15 (Observability and Schema Hygiene, which also covers PR14's deferred Operational Logging scope item) is now the next planned item. `docs/ROADMAP.md`'s baseline was updated by the dedicated documentation-only post-merge governance sync that follows this entry — the same pattern used after Roadmap PR9, PR10, PR11, PR12, and PR14A.

## Roadmap PR15 (PR15A slice) — Observability

- **Decision:** Treat Roadmap PR15 ("Observability and Schema Hygiene," which also covers PR14's deferred Operational Logging scope item) as an Epic implemented through multiple focused slices, following the same lettered-slice precedent as PR7/PR8/PR9/PR14, per an architecture-approved design revision (`docs/design/PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md`, Revision 2, uncommitted design doc per this repository's established convention). **PR15A** is scoped to observability only: structured logging, request/correlation IDs (reusing the existing request-context mechanism rather than introducing a parallel one), async-safe `ContextVar` propagation, exactly one bounded access-log event per request, background-job run IDs, and aggregate import-commit logging. Explicitly excludes schema migrations, timezone migrations, FK `ondelete` policy changes, CHECK constraints, index naming standardization (all deferred to PR15B), and application metrics, tracing, dashboards, log aggregation, and alerting (not scheduled to any PR15 slice; remain open Roadmap PR15 scope pending a future slice or an explicit governance decision to remove them — Roadmap PR15 as a whole is not complete once PR15A merges).
- **Context:** `docs/audits/04-consolidated-implementation-plan.md` Part D's PR15 entry, combined with a Repository Owner design-review round that produced a complete Roadmap PR15 disposition matrix (every listed topic — operational logging, structured logging, request correlation, metrics, tracing, alerting, log aggregation, operational dashboards, `ondelete` policies, users soft-delete, CHECK constraints, index naming, schema hygiene, timezone handling — assigned an explicit disposition: included in PR15A, included in PR15B, already completed by an earlier PR, or deferred with a governance justification) and a timezone policy required before any PR15B migration proposal. PR15A is the first implementation slice approved from that design; PR15B (schema hygiene) requires a separate architecture approval before implementation begins.
- **What was built (`app/core/log_context.py`, new):** `contextvars.ContextVar`-based `request_id`/`correlation_id`/`job_run_id`, propagated async-safely through a request's or job's whole call chain (not thread-local, which is unsafe under asyncio's cooperative concurrency), plus `RequestContextFilter`, a `logging.Filter` attached to the log handler that fills these onto every `LogRecord` unless a call site already supplied a value via `extra=`.
- **What was built (`app/core/logging.py`):** `JsonFormatter` — one JSON object per log line (timestamp, level, logger, message, correlation IDs, a small fixed allowlist of extra fields, exception traceback when present); the allowlist is deliberate, not a passthrough of `record.__dict__`, so a stray `extra={...}` field at some future call site can never silently reach output. `configure_logging()` explicitly clears the root logger's existing handlers before installing its own JSON handler, rather than relying on `logging.basicConfig()`'s default idempotency (a silent no-op once the root logger already has any handler) — deterministic regardless of whether Uvicorn, pytest, or this module happens to configure logging first, and idempotent on repeat calls. `safe_log()` — a fail-safe wrapper: runs a logging call and guarantees neither it nor its own best-effort fallback report can ever propagate an exception back to the caller.
- **What was built (`app/main.py`):** `request_context_middleware` sets/reuses `X-Request-ID`/`X-Correlation-ID` (an inbound header is validated against a conservative charset/length pattern before reuse, never trusted verbatim), emits exactly one access-log event per request (method, route *template* — not the raw URL, to keep log cardinality bounded; unmatched routes fall back to a fixed `"unmatched"` label) via `safe_log()` in a `finally` block, and unconditionally resets both ContextVars. All four exception handlers pass request/correlation IDs explicitly via `request.state` (not the ambient `ContextVar`), because Starlette's catch-all `Exception` handler runs inside `ServerErrorMiddleware`, which wraps *outside* this middleware — for a genuinely unhandled exception, the `ContextVar` is already reset by this middleware's `finally` block before that handler logs, but `request.state` survives regardless.
- **What was built (`app/worker/scheduler.py`):** `check_pm_cal_due()` wrapped with an independent `job_run_id` (deliberately not the HTTP request-ID mechanism — a background job is not a request) and run duration; both existing success-path log lines and the failure-path `logger.exception()` call now route through `safe_log()`.
- **What was built (`app/services/import_service.py`):** `_commit_rows()`'s post-commit success log and post-rollback failure log both route through `safe_log()`; the success log carries only aggregate row-count statistics, never the filename or any row/cell content.
- **Review-driven correctness fixes (three independent Codex reviews on Draft PR #50, each on a new exact head, before the PR was squash merged):**
  1. **Review 1 (review ID `4787144983`, reviewed head `746732dc2d758286d4340cf4628327e1206b8329`, CI run `30267254839`, 5/5 jobs green)** — the substantive review decision was **REQUEST CHANGES** (surfaced by GitHub as `COMMENTED` only because the reviewing account owns the PR), with two merge-blocking findings. **PR15A-H1:** `configure_logging()` relied on `logging.basicConfig()`'s default idempotency, which is a silent no-op once the root logger already has any handler — reproduced by installing a root `StreamHandler` before calling `configure_logging(False)` and confirming its formatter stayed unset. Since Uvicorn commonly configures logging before importing the application, the JSON formatter could silently never install, depending on import order. **PR15A-H2:** the new post-commit import-success log call in `_commit_rows()` ran after `await db.commit()` had already succeeded; a failure there could turn an already-committed, successful import into an HTTP 500. The access-log boundary was also incomplete: its fallback `logger.warning()` was itself unguarded.
  2. **Review 2 (review ID `4788591587`, reviewed head `c32270e01073fb486066d5f95548282056f3b930`, CI run `30277548822`, 5/5 jobs green)** — **REQUEST CHANGES.** `PR15A-H1` confirmed resolved: `configure_logging()` now explicitly clears the root logger's existing handlers before installing its own, deterministically, with a new test reproducing the original pre-existing-handler failure mode. `PR15A-H2R` (the unaddressed remainder of H2): the primary post-commit `logger.info()` call was now caught, but the fallback `logger.warning()` immediately following it was itself unguarded — if the same broken logging subsystem affected the fallback too, `_commit_rows()` would still propagate an exception after the database/audit commit had already succeeded. The identical gap existed in the access-log fallback (a doubly-broken logging path would mask the response/real exception and skip the ContextVar resets below it) and in scheduler completion logging (still inside the job's broad business `try`, so a completion-log failure was caught and reported as a job failure, followed by another unguarded exception log).
  3. **Review 3 (review ID `4789829543`, reviewed head `eeae67542d02e1dc266a15979c2b02857020f872`, CI run `30286421490`, 5/5 jobs — Backend tests non-PostgreSQL, Backend tests PostgreSQL, Alembic migration upgrade validation, Frontend build, `git diff --check` — all green)** recorded **APPROVE WITH NON-BLOCKING COMMENTS.** `PR15A-H2R` confirmed resolved: `safe_log()` — a small helper that runs a log call and guarantees neither it nor its own best-effort fallback report can ever propagate — now wraps the access-log emission, both scheduler success/failure log calls, and both import success/failure log calls, independently verified at this exact head by 24/24 passing tests in `backend/tests/test_observability_logging.py` (new regression tests covering the double-failure case — the primary log call *and* its own fallback both raising — for all three paths). **PR15A-M1** (non-blocking, explicitly accepted as a deferred follow-up, not a merge blocker): the four exception-handler log lines in `app/main.py` still log the raw request path (`request.url.path`) rather than the route template used by the access-log line.

  Each fix was pushed to a new exact head on the same Draft PR before merge — not discovered or fixed after PR #50 entered the baseline.
- **Testing decision:** `backend/tests/test_observability_logging.py` (new, 24 tests): concurrent-request `request_id` isolation; `ContextVar` reset in `finally` (including when the job/request raised); invalid/oversized/unsafe-character inbound request IDs rejected and never logged; exception-path logging for all four handler types (including the genuinely-unhandled-exception path, using the `ASGITransport(raise_app_exceptions=False)` pattern already established in `tests/test_exception_handling.py`); exactly one access-log event per request; route template (not raw URL) in the access log, with a fixed `"unmatched"` fallback; sensitive-data non-persistence (passwords, BCM codes, Item Numbers, filenames never appear in formatted log output, even via a stray `extra=`); the JSON formatter's fixed extra-field allowlist; `configure_logging()`'s idempotency when a handler already exists; and fail-safe coverage for every post-success logging path (access log, scheduler completion, import completion), including the double-failure case, for both `safe_log()` itself and each of its three call sites.
- **Source:** Branch `feature/pr15a-observability`, baseline `a43b680a5558aa322a613b3e3eba0eeb45858edf` — the documentation-only post-merge governance sync recording Roadmap PR14B's completion, GitHub PR #49 (not GitHub PR #48/`82e289d`, PR14B's own squash commit, which is one commit further back). `docs/audits/04-consolidated-implementation-plan.md` Part D (PR15); `docs/design/PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md` (Revision 2, uncommitted).
- **Status:** Merged. GitHub PR #50, squash SHA `e250638db186f8e4dc3358bd475e9cf4eebc0bc8`, after all three review rounds above were fully addressed.
- **Consequences:** No schema or migration change. **No breaking API changes:** the implementation adds backward-compatible response headers only (`X-Request-ID`, `X-Correlation-ID`); existing clients continue to function without modification, and business semantics, response bodies, and status codes remain unchanged. No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or business workflow. **PR15A is now fully complete. Roadmap PR15 (the Epic) is NOT fully complete** — PR15B (Schema Hygiene) is the next planned item, and application metrics, tracing, dashboards, log aggregation, and alerting remain open Roadmap PR15 scope, not scheduled to any slice, pending a future slice or an explicit governance decision to remove them from scope; per binding governance direction, Roadmap PR15 may not be marked complete until every one of its topics has been implemented, completed by an earlier PR, or explicitly removed through a governance decision. `docs/ROADMAP.md`'s baseline was updated by the dedicated documentation-only post-merge governance sync that follows this entry — the same pattern used after Roadmap PR9, PR10, PR11, PR12, PR14A, and PR14B.

## Roadmap PR15 (PR15B slice) — Schema Hygiene

- **Decision:** Implement the architecture-approved PR15B design (`docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md`, GitHub PR #52) as three independently-revertible migrations, per that design's approved three-migration split: `0012_timezone_conversion.py` (timezone), `0013_fk_ondelete_policy.py` (FK policy), `0014_index_naming_convergence.py` (index/constraint naming). No architecture, business-rule, or API contract change — this slice is schema hygiene only, exactly as scoped by the approved design.
- **Context:** The approved design established one binding invariant for every migration execution path: every rename, `ON DELETE` change, and type conversion must be decided only after full semantic catalog-state verification, applied identically to upgrade, downgrade, verify-and-no-op, legacy-name, and target-name paths — never a partial check, never assumed from a fixed before-state. An independent design-compliance review, conducted against this implementation before this branch's Pull Request was opened, verified that invariant end to end and raised three findings, all resolved before merge (see "What was fixed" below).
- **What was built (`0012_timezone_conversion.py`):** Converts `audit_logs.created_at`, `notifications.created_at`, `equipment_status_history.changed_at`, `borrow_transactions.borrowed_at`/`.returned_at` from naive `timestamp` to `timestamptz` via `AT TIME ZONE 'UTC'` — not a bare cast, since every existing value's write path traces to `datetime.utcnow()` (confirmed by grep), so the stored wall-clock numbers are already UTC by construction. `borrow_transactions.due_at` is deliberately excluded and remains naive: its historical values were client-supplied with no server-side timezone normalization, so there is no evidence to support reinterpreting them as UTC. Classifies each column's actual `information_schema.columns.data_type` into needs-transformation / already-`timestamptz` (no-op) / unexpected-type (fail closed) before ever running the conversion expression, so a fresh install that already produces `timestamptz` (via the paired ORM `UTCDateTime` change) is never re-converted — re-running the expression against an already-aware column would silently re-derive the value from the migration session's effective timezone, not a fixed shift.
- **What was built (`0013_fk_ondelete_policy.py`):** Makes `ON DELETE RESTRICT` explicit on all 25 foreign keys — zero observable behavior change, since the only `DELETE` endpoint in the running API (`DELETE /equipment/{id}`) is already a soft delete and no FK's `ondelete` behavior has ever been exercised by any code path. Paired with `ondelete="RESTRICT"` on all 25 ORM `ForeignKey()` declarations in the same commit, so `Base.metadata.create_all()` (and the SQLite test suite built from it) matches the post-migration PostgreSQL catalog. One shared helper, `_classify_fk()`, drives both upgrade and downgrade identically: it always runs the full semantic-definition comparison (referenced table/columns, `ON UPDATE`, deferrable/deferred state, validation state, `pg_get_constraintdef()`) before ever inspecting `confdeltype`, and only then decides needs-transformation / already-at-target (no-op) / fail-closed.
- **What was built (`0014_index_naming_convergence.py`):** Renames the 5 hand-named `idx_`-prefixed indexes (4 GIN trigram indexes, 1 partial unique safety index) and 7 PostgreSQL-auto-named `<table>_<column>_key` unique constraints onto the `ix_`/`uq_` convention already used by the other 29 indexes and 4 named constraints — 100% `ALTER INDEX`/`ALTER TABLE ... RENAME CONSTRAINT`, zero rebuild. Paired with explicit `UniqueConstraint(name="uq_...")` declarations replacing bare `unique=True` on the 7 affected columns, and the partial unique safety index (`idx_tx_one_active_borrow` → `ix_borrow_transactions_one_active_borrow`) declared under its target name directly in the ORM `Index(...)`. One shared classifier, `_classify_rename()`, drives every path (legacy-name, target-name, upgrade, downgrade) identically: full semantic-definition comparison (`pg_get_indexdef()`/`pg_get_constraintdef()`, access method, uniqueness, indexed columns/expressions/predicates, collation, included columns) plus health-state verification (`pg_index.indisvalid`/`indisready`) before any outcome is decided — an object matching every definitional check but unhealthy is never treated as a valid rename source or no-op target.
- **What was fixed (independent design-compliance review, before this branch's Pull Request was opened):**
  1. **H1** — migration `0014` originally verified only partial metadata (name plus a single field) before renaming or accepting an object as already-converged on some execution paths, rather than the full semantic-definition-plus-health check described above, applied uniformly. Fixed by introducing the single shared `_classify_rename()` helper, used unmodified by all four call sites (legacy-name/target-name × upgrade/downgrade).
  2. **H2** — migration `0013`'s downgrade path originally verified only `confdeltype` before reverting a foreign key to `NO ACTION`, rather than the same full-definition check its upgrade path used — a mismatched FK (e.g. pointing at the wrong referenced table, but coincidentally carrying the expected `confdeltype`) could have been silently reverted without the mismatch ever being detected. Fixed by introducing the single shared `_classify_fk()` helper described above, used identically by both directions.
  3. **H3** — migration `0014`'s `_ConstraintVerifier.fetch()` originally collapsed two distinct catalog states into `None`: a name that is truly absent (neither an index nor a unique constraint exists under it), and a name in a genuinely PARTIAL state (only one of the two exists) — silently treating the second as the first could let a leftover standalone index (or constraint) be renamed onto, or no-op'd past, without the inconsistency ever surfacing. Fixed by introducing an explicit `_CatalogState` (ABSENT/COMPLETE/PARTIAL) wrapper returned by both verifiers' `fetch()` methods; `_classify_rename()` now checks for PARTIAL on both the legacy and target name, in both directions, before any ABSENT/COMPLETE-based outcome is reached.
- **Testing decision:** `backend/tests/test_postgres_integration.py` — fresh-install, historical-upgrade (`0011 → head`), downgrade/re-upgrade, and second-run-is-noop coverage for all three migrations; explicit fail-closed regression tests for a mismatched FK/index/unique-constraint definition, both-names-present, an unhealthy index under both the legacy and target name (isolated `indisvalid`/`indisready` cases and the combined interrupted-concurrent-build case), a downgrade-direction FK mismatch (asserting zero mutation to any other FK), and all three PARTIAL-catalog-state combinations (valid target + legacy standalone index; valid legacy + target standalone index; a downgrade-direction partial state) — every fail-closed test asserts `RuntimeError`, zero schema mutation, and byte-for-byte unchanged definitions/health flags on every touched object afterward. A combined schema-convergence test compares full `pg_get_constraintdef()`/`pg_get_indexdef()` definitions and health flags (not just names) between the fresh-install and historical-upgrade paths for all three migrations together. `backend/tests/test_utc_datetime_invariant.py` (new) covers the SQLite-side write invariant below.
- **UTC write invariant (`app/models/mixins.py`):** `UTCDateTime.process_bind_param()` now fails closed (raises `ValueError`) on a non-UTC aware datetime rather than silently normalizing it to UTC, since this application has no legitimate call site that constructs one — every write already uses `datetime.now(timezone.utc)` (the three remaining `datetime.utcnow()` call sites, `auth_service.py::last_login_at`, `crud/transaction.py::returned_at`, `crud/equipment.py::soft_delete()::deleted_at`, were fixed in this same slice) — so a non-UTC value reaching this column indicates a real upstream bug, not a case to silently correct. A naive value is passed through unchanged (assumed UTC, this column's established convention).
- **Source:** Branch `feature/pr15b-schema-hygiene`, baseline `6a845140832b6269c8d7d0177c78fc00cb828f26` (a documentation audit and Roadmap consistency pass, GitHub PR #53). `docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md` (GitHub PR #52, architecture-approved).
- **Status:** Merged. GitHub PR #54, squash SHA `6f66d76`, after the independent design-compliance review above (APPROVE WITH NON-BLOCKING COMMENTS) and one incremental re-review of the same head after a `knowledge/CONTEXT.md` merge-conflict rebase against the target branch's newer tip (no implementation file touched by the rebase; APPROVE WITH NON-BLOCKING COMMENTS). CI (5/5 jobs: Backend tests PostgreSQL, Backend tests non-PostgreSQL, Alembic migration upgrade validation, Frontend build, `git diff --check`) was green on the exact merged head.
- **Consequences:** **PR15B is now fully complete — both of Roadmap PR15's scheduled slices (PR15A Observability, PR15B Schema Hygiene) are complete.** Per the same binding governance direction recorded in the PR15A entry above, **Roadmap PR15 (the Epic) is still NOT fully complete** — application metrics, tracing, dashboards, log aggregation, and alerting remain open Roadmap PR15 scope, not scheduled to any slice, pending a future slice or an explicit governance decision to remove them. No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or business workflow. The next planned item is Roadmap PR16 (Reporting Foundation — distinguishing actual transaction timestamp, `business_date`, and `shift`).

## Roadmap PR16 — Owner Decision #1 (Shift Boundary Policy)

- **Decision:** The Repository Owner confirms the full Day/Night shift boundary policy required by the architecture-approved PR16 design (`docs/design/PR16_REPORTING_FOUNDATION_PLAN.md`, GitHub PR #56):
  - **Night→Day transition (Day shift start):** `08:00` `Asia/Bangkok`.
  - **Day→Night transition (Night shift start):** `20:00` `Asia/Bangkok`.
  - **`business_date_anchor`:** `shift_start_date` — every instant within a shift, including the post-midnight portion of an overnight Night shift, takes the calendar date the shift *started* on. A Night shift starting `2026-07-28 20:00` and running past midnight is entirely `business_date = 2026-07-28`, not split across two business dates.
  - **`on_demand` dispatch classification:** a `dispatch_type = on_demand` transaction (not tied to one of the four confirmed `RoutineRound` values) is classified purely by `borrowed_at`'s `Asia/Bangkok` clock time against the two transition times above — identically to a `RoutineRound`-tied dispatch, with no special-case rule.
- **Context:** The PR16 design (independently reviewed, GitHub PR #56, reviews `4799462477`/`4799626588`) explicitly declined to invent this policy, per `docs/GLOSSARY.md`'s instruction not to invent fixed Day/Night boundaries, and flagged it as a blocking "Open Owner Decision #1" — a placeholder `_ShiftBoundaryPolicy` shape (both transition times, plus an explicit `business_date_anchor` rule distinguishing `shift_start_date` from `instant_calendar_date`) was specified, but left uninstantiated, pending exactly this decision. This entry records the Repository Owner's answer to all four required inputs ((a)–(d) in the design's §18).
- **Source:** `docs/design/PR16_REPORTING_FOUNDATION_PLAN.md` §7 (`_ShiftBoundaryPolicy`) and §18 (Owner Decision #1), updated in place to record these confirmed values, on branch `docs/pr16-owner-decision-1`, baseline `3e8d015` (GitHub PR #56 squash merge).
- **Status:** Decided. Not yet implemented — no code, migration, or schema change exists yet for this policy; `backend/app/core/reporting_time.py` (PR16 Implementation Slice 1) is the first place these values will be instantiated.
- **Consequences:** Roadmap PR16 Implementation Slice 1 (`backend/app/core/reporting_time.py` — the `Shift` enum, `_ShiftBoundaryPolicy`, the pure-Python and SQL-expression derivation twins) is now unblocked and may begin. No other Roadmap PR's scope, business rule, lifecycle state, or workflow is affected by this decision — it resolves exactly one previously-open input to the already-approved PR16 design, nothing more.

## Roadmap PR16 — Reporting Foundation Complete

- **Decision:** Implement the architecture-approved PR16 design (`docs/design/PR16_REPORTING_FOUNDATION_PLAN.md`, GitHub PR #56) as four independently-shippable Implementation Slices, per the design's own §16 slice plan and Owner Decision #1 (shift boundary policy, recorded above) — no architecture, business-rule, or workflow change beyond what the design and that decision already establish.
- **What was built:**
  - **Slice 1** (`backend/app/core/reporting_time.py`, GitHub PR #58, squash SHA `e8ef4da`): the `Shift` enum, the confirmed `_ShiftBoundaryPolicy` (Owner Decision #1's values), `business_date_and_shift()` (pure-Python reference) and `business_date_and_shift_sql()` (SQLAlchemy-expression twin, dialect-compiled for PostgreSQL `AT TIME ZONE 'Asia/Bangkok'` and a SQLite `+7 hours` literal-shift test-suite fallback — Thailand has held a single DST-free UTC+7 offset since 1920, so the two are provably equivalent). Tested for parity against each other on every shift-boundary/midnight/rollover case (`backend/tests/test_reporting_time.py`).
  - **Slice 2** (`app/models/transaction.py`/`app/schemas/transaction.py`, GitHub PR #59, squash SHA `bd4a02b`): `dispatch_business_date`/`dispatch_shift`/`receipt_business_date`/`receipt_shift` computed `@property`s on `BorrowTransaction`, surfaced on `TransactionOut` via Pydantic v2's `from_attributes=True` — no service/API-layer code needed. `receipt_business_date`/`receipt_shift` are `None` until the transaction is received, mirroring the existing `receipt_outcome` contract.
  - **Slice 3** (`app/crud/transaction.py::search()`/`app/api/v1/transactions.py::list_transactions()`, GitHub PR #60, squash SHA `6a28d73`): `business_date_from`/`business_date_to`/`shift`/`event` (`Literal["dispatch", "receipt"] = "dispatch"`) query parameters on the existing `GET /transactions`, filtering against the *derived* `business_date`/`shift` expression (never `datetime.combine`-based bounding of the raw timestamp, which remains exclusive to the existing `from_date`/`to_date` filters) — a new, separate `business_date_from > business_date_to` → `400 INVALID_INPUT` check, distinct from the pre-existing `from_date`/`to_date` check. An open transaction under `event=receipt` is silently excluded from any non-null filter (`receipt_business_date`/`receipt_shift` are `NULL`), not treated as an error. An implementation-readiness review conducted before this slice's code was written surfaced a real defect in the already-merged Slice 1 module: `business_date_and_shift_sql()`'s `shift` `CASE` expression silently returned `'night'` for a NULL input column instead of `NULL`, since standard SQL `CASE WHEN <NULL comparison>` is never `TRUE` — fixed with an explicit `column.is_(None)` branch and regression tests on both SQLite and PostgreSQL, folded into this slice's own commit since the defect would otherwise have first become externally observable exactly here (an open transaction filtered by `event=receipt`).
  - **Slice 4** (`frontend/src/pages/EquipmentDetailPage.tsx`, GitHub PR #61, squash SHA `ac19505`): `business_date_from`/`business_date_to` date pickers, `shift` selector, and `event` selector, as an explicitly separate control group from the existing `from_date`/`to_date` pair — never merged with or substituted for it. Committed via an Apply/Clear pair (not live on every keystroke, unlike the existing `from_date`/`to_date`/`dispatch_type`/`routine_round` controls), backed by URL search params as the single source of truth for the *applied* filter values. Frontend-only: `business_date`/`shift` are never computed client-side, only selected and sent verbatim.
- **Review chronology:**
  - Slice 3 (GitHub PR #60): one independent Codex review (review ID `4803420465`, base `bd4a02b`, reviewed head `a5a7dfc020f0b94b0832148ff4dd362ab4aec951`, CI run `30415732999`, 5/5 jobs green) recorded **APPROVE**, no blocking or non-blocking findings — the diff was narrow and every one of 6 explicit readiness-check points (inclusive bounds, `shift` values/omitted behavior, `event` mapping, `business_date` as the primary filter, date-range validation, unchanged pagination/ordering) had a dedicated test.
  - Slice 4 (GitHub PR #61): two independent Codex review rounds, on two different heads, not one round. **Round 1** (review ID `4803665535`, base `6a28d733b48fdd404bd371355f5cbae0c427400`, reviewed head `1e344f8001c9fd2d5b7a2e70594bc204a9b25636`, CI run `30417953722`, 5/5 jobs green) recorded **REQUEST CHANGES** with one merge-blocking finding, **PR16-S4-H1** (referred to as **PR61-H1** elsewhere in this repository's task tracking): the `เหตุการณ์` (event) selector's "ทั้งหมด" (All) option serialized to `event: undefined`, and the backend's `event` parameter (`Literal["dispatch", "receipt"] = "dispatch"`) has no "all" value — an omitted `event` silently means "dispatch," not "all events," so selecting "All" together with a `shift`/`business_date` filter silently narrowed results to dispatch-basis only while the UI's own label promised "all events." Confirmed against both the design (§8/§9/§16, all of which define `event` as a strict `dispatch|receipt` two-value basis with no third value) and the merged backend code directly, before any fix was proposed; plus one non-blocking UX note (draft filter-control state can go stale across browser Back/Forward navigation without a full remount — deferred, not a merge blocker). Fixed without any backend change or client-side dispatch/receipt calculation: `business_date_from`/`business_date_to`/`shift` are only meaningful together with one concrete event basis, so they are now disabled until a concrete event is chosen, cleared on switching back to "All," and — as the single authoritative gate applied where the request is actually built, not just at Apply-click time — never sent whenever the *applied* `event` resolves to "All," including from a hand-edited or stale URL. Regression tests added for all three `event` states (All/Dispatch/Receipt) plus the disabled-control and stale-URL cases. **Round 2** (review ID `4803863196`, incremental range `1e344f8001c9fd2d5b7a2e70594bc204a9b25636..a89237d4d54b99d3d8dc4c81d08e0394d3506e6a`, fixed/re-reviewed head `a89237d4d54b99d3d8dc4c81d08e0394d3506e6a`, CI run `30420209015`, 5/5 jobs green) confirmed PR16-S4-H1 resolved and recorded **APPROVE WITH NON-BLOCKING COMMENTS** — the Round 1 Back/Forward draft-state UX note remains an explicitly tracked, non-blocking follow-up.
- **Testing decision:** `backend/tests/test_reporting_time.py`, `backend/tests/test_transaction_search.py`, `backend/tests/test_postgres_integration.py` (backend, all four slices); `frontend/src/pages/EquipmentDetailPage.test.tsx` (frontend, Slice 4 plus the PR61-H1 fix) — full suites green at every merge (backend: 521 non-PostgreSQL + 176 PostgreSQL after Slice 3; frontend: 151 after the PR61-H1 fix).
- **Source:** `docs/design/PR16_REPORTING_FOUNDATION_PLAN.md` (GitHub PR #56, architecture-approved); Owner Decision #1 (see the entry above, GitHub PR #57). Slices implemented sequentially, each branched from the previous slice's own squash-merge SHA, never from a sibling slice's branch: Slice 1 baseline `5ace425` (Owner Decision #1 sync); Slice 2 baseline `e8ef4da`; Slice 3 baseline `bd4a02b`, reviewed at head `a5a7dfc020f0b94b0832148ff4dd362ab4aec951` (squash-merged as `6a28d73`); Slice 4 baseline `6a28d73`, Round 1-reviewed at head `1e344f8001c9fd2d5b7a2e70594bc204a9b25636`, PR16-S4-H1 (PR61-H1) fixed and Round 2-reviewed at head `a89237d4d54b99d3d8dc4c81d08e0394d3506e6a` — a fixed/re-reviewed head, not a new baseline (same branch/PR as Slice 4, pushed before merge, not a separate PR).
- **Status:** Merged. GitHub PRs #58 (`e8ef4da`), #59 (`bd4a02b`), #60 (`6a28d73`), #61 (`ac19505`) — all four Implementation Slices are complete.
- **Consequences:** **Roadmap PR16 (Reporting Foundation) is now fully complete.** `GET /transactions` can be filtered by `business_date_from`/`business_date_to`/`shift`/`event` (backend, Slice 3) with matching frontend controls (Slice 4), without losing the actual event timestamp — PR16's own Roadmap acceptance criterion ("New reporting data can be filtered by `business_date` and `shift` without losing the actual event timestamp") is met end to end for both dispatch and receipt events. No new endpoint, no export, no dashboard, and no migration beyond what Slices 1-2 already established (none — `business_date`/`shift` are computed, never persisted). No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or business workflow. The next planned item is Roadmap PR17 (Date/shift-filtered Receive, Issue, and Equipment Verify Checklist reports).

## Roadmap PR17 — Owner Decision #1 (Equipment Verify Checklist Definition)

- **Decision:** The Repository Owner confirms **Option A — Equipment master-data/status-history checklist** (`docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md` §7.3(A)/§18) as the definition of "Equipment Verify Checklist" for Roadmap PR17. Concretely:
  - Equipment Verify Checklist is a **read-only, current-state snapshot** of the pool's own `Equipment` master records and their status — realtime, no caching, no materialized snapshot.
  - It supports exactly the approved filters the merged design defines for this report: equipment category, current equipment status, and department (`equipment_category_id`/`status`/`department_id`, §9/§10.3). It does **not** support a `ward_id` filter — `Equipment` has no direct Ward relationship.
  - It does **not** create a physical-verification workflow. It does **not** record verification time, verification result, verifying operator, condition assessed at verification, pass/fail state, verification notes, or any reconciliation outcome. There is no "verification" action to complete under this interpretation — the report is a listing, not a task list.
  - It introduces **no new equipment lifecycle state**. `EquipmentStatus`'s existing four values (`AVAILABLE_AT_POOL`/`ISSUED_TO_WARD`/`UNAVAILABLE_DEFECTIVE`/`DECOMMISSIONED`, Roadmap PR6) are displayed as-is, never extended or reinterpreted.
  - It requires **no database migration** — the report reads existing `Equipment` columns only.
  - **Option B** (a genuine physical-verification event workflow — an operator recording "verified equipment X at time Y, condition Z") is explicitly **not** chosen. Physical verification, if ever wanted, is **outside Roadmap PR17** and requires its own, separately-numbered future Roadmap item and its own design/data-model/migration decision, mirroring how Shift Sessions/Standby Snapshots are tracked today (`docs/ROADMAP.md` "Confirmed future work") — not something this decision authorizes or schedules.
- **Context:** The PR17 design (`docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md`, §2/§6.3/§7.3/§18) found no hospital business process behind "Equipment Verify Checklist" confirmed anywhere in this repository's authoritative documentation, and flagged it as a blocking Owner Decision #1 — the same "flag rather than guess" discipline PR16's Day/Night boundary decision (above) already established for this repository. Two full candidate interpretations were specified in the design so it stayed reviewable despite the open decision; this entry records the Repository Owner's answer, obtained directly before GitHub PR #68's implementation began.
- **Source:** `docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md` §18 (Owner Decision #1), updated in place to record this resolution — the original unresolved framing is preserved immediately below the resolution note, unaltered, as the historical record, mirroring how PR16's own Owner Decision #1 entry (above) was recorded. GitHub PR #68, branched from baseline `8a1a280` (PR17 Slice 3's squash-merge SHA, GitHub PR #67).
- **Status:** Decided and implemented. GitHub PR #68 (Roadmap PR17 Slice 4) implements this resolved decision: `GET /reports/equipment-verify-checklist` (`app/crud/equipment.py::list_for_verify_checklist`, `app/api/v1/reports.py`) and its frontend screen (`EquipmentVerifyChecklistPage.tsx`).
- **Consequences:** Roadmap PR17 Slice 4 (Equipment Verify Checklist, previously blocked per §17/§18) is unblocked and implemented. No other Roadmap PR's scope, business rule, lifecycle state, or workflow is affected — this resolves exactly one previously-open input to the already-approved PR17 design, nothing more. **Roadmap PR17 is not yet declared complete by this entry** — per the design's own §17 Final Slice rule, that governance-completion entry (recording all of Receive, Issue, and Equipment Verify Checklist resolved, and advancing the Roadmap's next planned item to PR18) is a separate, dedicated entry made only once GitHub PR #68 itself has merged.

## Roadmap PR17 — Operational Reports Complete

- **Decision:** Implement the architecture-approved PR17 design (`docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md`, GitHub PR #63) as four independently-shippable Implementation Slices plus this Final Slice, per the design's own §17 slice plan and Owner Decision #1 (Equipment Verify Checklist definition, recorded above) — no architecture, business-rule, or workflow change beyond what the design and that decision already establish.
- **What was built:**
  - **Design** (GitHub PR #63, squash SHA `b935ac2`): `docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md` — the architecture-approved plan for Receive, Issue, and Equipment Verify Checklist reports, including the originally-open Owner Decision #1 (Equipment Verify Checklist definition).
  - **Slice 1** (`app/crud/transaction.py::search()`, internal report query functions, GitHub PR #65, squash SHA `ddb9733`): the `equipment_category_id` join, `operator_id` filter, and `require_receipt` unconditional predicate enforcing the Receive Report's completed-receipt-only rule regardless of which other filters are present; the confirmed backend-only deterministic ordering for the Issue Report.
  - **Slice 2** (`app/schemas/transaction.py::ReportTransactionOut`, `app/api/v1/reports.py`, `app/crud/user.py::list_operators`, GitHub PR #66, squash SHA `aeafb81`): `GET /reports/receive`, `GET /reports/issue`, and `GET /report-options/operators` — `VIEW_AND_REPORT_ROLES`-gated, cursor-paginated, with a dedicated report-only `ReportTransactionOut` schema (operator display fields kept off the shared `TransactionOut` contract) and a bounded historical-operator lookup (never a general user directory).
  - **Slice 3** (`frontend/src/pages/ReceiveReportPage.tsx`/`IssueReportPage.tsx`, `OperatorAutocomplete.tsx`, `ReportFilters.tsx`, GitHub PR #67, squash SHA `8a1a280`): Thai-first `/reports/receive` and `/reports/issue` screens, URL-state-backed business-date/shift/ward/category/operator filters, loading/empty/error states, on-screen result rendering that strictly preserves backend order.
  - **Slice 4** (`app/crud/equipment.py::list_for_verify_checklist`, `app/api/v1/reports.py`, `EquipmentVerifyChecklistPage.tsx`, GitHub PR #68, squash SHA `d4aaf0f`): `GET /reports/equipment-verify-checklist` and its frontend screen, per Owner Decision #1's resolution to interpretation A (recorded above) — a read-only, current-state listing of `Equipment` master records, reusing `EquipmentOut` (which deliberately excludes `item_no`, per ADR-002/ADR-003) rather than inventing a new DTO. GitHub PR #68 also added structured malformed-cursor handling for this endpoint and hardened the shared cursor-decoding layer (`app/utils/pagination.py::decode_cursor`/`decode_alpha_cursor`) for invalid Base64, malformed JSON/payloads, invalid timestamps, and missing required fields — a malformed cursor of those kinds previously escaped as an uncaught exception (HTTP 500) and now returns the repository-standard structured `400 INVALID_INPUT` client error wherever those shared utilities are used. At the time of PR68/PR69, full cursor hygiene across every existing caller was not yet complete: `app/crud/user.py::list_operators` performed an unguarded `uuid.UUID(cursor_id)` after `decode_alpha_cursor()` returned, so a structurally well-formed alpha cursor carrying a non-UUID id could still reach an uncaught exception on that one caller-specific path. **This gap is now closed** — see the "Cursor-hygiene maintenance fix" note below.
- **Review chronology:** See the individual GitHub PRs and this file's prior entries for full per-slice review detail — Slice 2 (PR66-H1, `ge=1` on `limit` parameters), Slice 4 (this file's "Roadmap PR17 — Owner Decision #1" entry above, plus GitHub PR #68's incremental fix round: Owner Decision #1 documentation consistency and the malformed-cursor fix). No slice required a database migration.
- **Testing decision:** Backend and frontend regression suites green at every slice merge, PostgreSQL-backed cursor-pagination evidence for the Equipment Verify Checklist endpoint (`backend/tests/test_postgres_integration.py`), and dedicated malformed-cursor regression coverage (`backend/tests/test_pr17_cursor_validation.py`) proving the Equipment Verify Checklist endpoint, and every cursor-consuming endpoint (Receive, Issue, operator lookup, Equipment list), reject the malformed-Base64/malformed-JSON/missing-field cursor classes with `400 INVALID_INPUT` rather than an uncaught `500`. At the time of this entry, that coverage did not yet exercise the narrower well-formed-envelope-but-non-UUID-id case on `list_operators` — closed by the maintenance fix noted below.

- **Cursor-hygiene maintenance fix:** `app/crud/user.py::list_operators`'s caller-specific `uuid.UUID(cursor_id)` gap noted above is resolved: the function now validates the decoded cursor's UUID before any query executes, mirroring `equipment_crud.list_for_verify_checklist`'s established convention, and raises the existing `InvalidInputError` (`400 INVALID_INPUT`) for a non-UUID id, same as every other cursor-consuming endpoint. Covered by `backend/tests/test_operator_options_cursor_validation.py`. No other Roadmap PR17 scope, business rule, or contract changed. This is a narrowly scoped maintenance fix, not a new Roadmap item.
- **Source:** `docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md` (GitHub PR #63, architecture-approved); Owner Decision #1 (see the entry above, GitHub PR #68). Slices implemented sequentially, each branched from the previous slice's own squash-merge SHA: Slice 1 baseline `b935ac2`; Slice 2 baseline `ddb9733`; Slice 3 baseline `aeafb81`; Slice 4 baseline `8a1a280`, incrementally fixed (Owner Decision #1 documentation consistency, cursor validation) and merged as squash SHA `d4aaf0f`.
- **Status:** Merged. GitHub PRs #63 (`b935ac2`), #65 (`ddb9733`), #66 (`aeafb81`), #67 (`8a1a280`), #68 (`d4aaf0f`) — all four Implementation Slices and the design are complete. This entry is the Final Slice per the design's own §17 rule: condition 1 (Owner Decision #1 resolved to interpretation A, and Slice 4 merged) is satisfied.
- **Consequences:** **Roadmap PR17 (Operational Reports) is now fully complete.** Receive, Issue, and Equipment Verify Checklist reports are all implemented, backend-owned for eligibility/semantics/ordering, cursor-paginated, and Thai-first on the frontend. No new equipment lifecycle state, no change to `TransactionOut`, no physical-verification workflow, and no database migration were introduced anywhere in Roadmap PR17. No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or business workflow. The next planned item is Roadmap PR18 (PDF export, Excel export, and print-ready Hard Copy templates for the PR17 reports).

## Roadmap PR19A — Owner Decision #1 (Data Retention Policy)

- **Decision:** The Repository Owner approves the following Version 1 data retention policy for the Legacy Import Foundation (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §9, GitHub PR #83):
  - Active/current validation data is retained in full while an import session is non-terminal (`CREATED`/`VALIDATING`/`VALIDATED`/`VALIDATION_FAILED`/`DRY_RUN_RUNNING`/`DRY_RUN_COMPLETED`/`DRY_RUN_FAILED`/`EXECUTING` — the last two of which are explicitly *not* terminal, since re-validation/re-dry-run remain possible).
  - Validation-attempt history and row-level findings are retained for **180 days** after the import session enters a terminal state (`COMPLETED`/`FAILED`/`CANCELLED`).
  - After the retention period: persisted source bytes are deleted (moot in Version 1 — no raw bytes are ever stored, see below); row-level submitted values are deleted; finding details containing source values or PII are deleted or redacted.
  - Non-sensitive durable records are retained indefinitely and never purged: session identity, source checksum, dataset type, summary counters, attempt status/timestamps, final outcome, and all audit metadata.
  - The retention period is deployment-configurable (an environment/deployment setting), not an Administrator-editable database value in Version 1 — **no Administrator UI to change retention exists in V1.**
  - Retention cleanup must be auditable (one audit entry per session cleaned) and idempotent (safe to re-run, safe to interrupt and resume).
  - **No indefinite retention of source values or PII is authorized by this decision** — the 180-day clock applies without exception once a session is terminal.
- **Context:** The PR19A design (Rev 2, `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`, GitHub PR #83) established that `ValidationFinding.message`/`field` and `ImportSource.filename` may echo raw legacy source content — potentially including names or other identifying information carried over from AppSheet — but had not yet defined how long that content may be retained. Independent review (PR #83, round 2, finding H5) required this to be resolved as an explicit Owner Decision before implementation could proceed, per this repository's "flag rather than guess" discipline for exactly this class of open business/compliance decision (the same discipline PR16's Day/Night shift boundary and PR17's Equipment Verify Checklist definition, both recorded above, already established).
- **Source:** `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §9 (Data Retention), updated in Rev 3 to record and implement this decision architecturally — `terminal_at`/`retention_purged_at` schema columns (§4.1), the per-session redaction contract, and the ordering/idempotency rules for cleanup. GitHub PR #83 (`docs/pr19a-legacy-import-design` branch), baseline `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52`.
- **Status:** Decided. Not yet implemented at the time this entry was originally written — the `terminal_at`/`retention_purged_at` schema columns were assigned to Implementation Slice PR19A1; the actual retention-cleanup logic and its operational scheduling were, at that time, described as deferred to a later, unscheduled Retention Cleanup slice (design §9/§22), not bundled into PR19A1–A3. **Superseded by a later design revision, recorded here for historical-chronology accuracy:** the design doc's own §18/§21/§25 subsequently assigned retention-cleanup concurrency and its endpoint explicitly to PR19A3, not to a later unscheduled slice — see "Roadmap PR19A complete: PR19A1 + PR19A2 + PR19A3 merged" below. PR19A3 (GitHub PR #86) implements this policy at runtime: a `POST /import-sessions/retention/cleanup` endpoint, an atomic `SELECT ... FOR UPDATE SKIP LOCKED` claim so concurrent cleanup workers never process the same session, and fenced in-place redaction of source/row-error PII, enforced by the 180-day window this entry approved (deployment-configurable via `IMPORT_RETENTION_DAYS`, fail-fast validated at application startup). No background scheduler was added — the endpoint is a callable maintenance operation an operator or an external scheduler invokes; correctness does not depend on a specific invocation source, consistent with this entry's "operational scheduling" being out of scope for what got implemented.
- **Consequences:** Roadmap PR19A's design (§9) is now unblocked on this previously-open question, and (per the update above) the retention-cleanup mechanism this decision approved is now implemented and merged, not merely designed.

## 2026-08-10 — Roadmap PR19A complete: PR19A1 + PR19A2 + PR19A3 merged

- **Decision:** None — this is a documentation/governance synchronization
  entry, not a new Owner Decision. It records that all three implementation
  slices of Roadmap PR19A (Legacy Import Foundation, backend), decomposed
  by the architecture-approved design (`docs/design/
  PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`, GitHub PR #83, design §25), are
  now merged, independently Codex-reviewed, and CI-green on their exact
  reviewed heads.
- **What was built:**
  - **PR19A1 — Schema / Session / Source Foundation** (GitHub PR **#84**,
    branch `feature/pr19a1-legacy-import-schema`, squash SHA
    `7d58986095c4df6a425dc9cfd8298851eee86c17`, based on PR #83's squash
    SHA `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`): the
    `import_sessions`/`import_sources`/`import_jobs`/`import_row_errors`
    tables (migration `0015_import_foundation`), CAS-guarded session
    lifecycle transitions, source registration/freeze, the composite
    ownership FK (`import_sessions` -> `import_jobs`), and cursor-paginated
    session listing. No parser, validation, execution, or frontend code
    shipped with this slice, per the design's slice-ownership table.
    - **Fail-closed migration convergence:** `_verify_schema_convergence()`
      re-reads the actual PostgreSQL catalog after every `CREATE`/`ALTER`
      statement and fails the migration outright on any mismatch, rather
      than trusting `CREATE ... IF NOT EXISTS`'s silent no-op as proof of
      compatibility with a pre-existing, same-named object (review finding
      **PR84-H1R**).
    - **Closed-world governed-schema verification:** the convergence check
      asserts exact equality between the migration's own governed set of
      columns/constraints/indexes and what the catalog actually contains —
      not merely that the expected set is a subset of what exists (review
      finding **PR84-H1R2**).
    - **Relation-scoped constraint verification:** constraint-name lookups
      are scoped to the owning relation (`conrelid`), so a same-named
      constraint belonging to an unrelated table can never satisfy this
      migration's own check (review finding **PR84-H1R3**).
    - **Rollback behavior:** `downgrade()` drops all four tables in
      FK-dependency order (row-errors and jobs before sessions/sources),
      guarded to run only on PostgreSQL and using `DROP TABLE IF EXISTS`
      throughout.
  - **PR19A2 — Validation Foundation** (GitHub PR **#85**, squash SHA
    `7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`, based on PR19A1's squash
    SHA): the complete, generic lease-acquisition / heartbeat-renewal /
    completion-fencing / failure-fencing mechanism (design §9) for the
    first time, wired into `VALIDATING` — what made `validate` safe to
    merge and deploy on its own.
    - **Atomic source freeze:** `admit_validate_job` fuses the source
      freeze and the session's own CAS transition into one transaction
      with the job-lease INSERT, so admission and freeze can never observe
      a partial state.
    - **Parser adapter / off-thread contract:** `ImportAdapter.parse()`
      runs via `asyncio.to_thread`, never blocking the event loop; batch
      validation avoids N+1 queries via one `preload_business_context()`
      call per attempt.
    - **Validation attempts/snapshots:** each validate attempt is one
      `ImportJob` row; findings are persisted atomically with the
      attempt's own completion write, never as a separate, unguarded
      insert.
    - **Lease/heartbeat/fencing/recovery:** a periodic renewal loop (its
      own session, bounded transient-failure retry), completion fencing on
      both the success and failure paths (`fenced_success`/
      `fenced_failure`, CAS on `lease_owner`/`lease_generation`/session
      `version`), and a recovery endpoint that reclaims an expired-lease
      job atomically and abandons it — generic across `job_type` from the
      start (design §25), so PR19A3 could extend it unchanged.
    - **TX1/TX2 failure publication:** on any exception, TX1 rolls back in
      full and a clean TX2 attempts fenced failure publication; a TX2
      infrastructure failure leaves the attempt `running` for recovery to
      resolve, never an unfenced write.
    - **Primitive capture across the rollback boundary:** every value TX2
      needs (`job_id`, the admitted session version, lease owner/
      generation) is captured into a local variable immediately after
      admission, before any statement that could roll back or expire the
      ORM objects — avoiding `MissingGreenlet` from an implicit lazy-reload
      on an expired instance outside an awaited context.
  - **PR19A3 — Dry-run, Execution, Recovery, Retention** (GitHub PR **#86**,
    squash SHA `7f13a1e85e9b6a4828170c4b12bc2be27b15de39`, based on
    PR19A2's squash SHA): the remaining generic-mechanism-reusing endpoints
    design §25 assigned to this slice.
    - **Enforced PostgreSQL read-only dry-run:** `plan_dry_run()` runs
      inside a separate session with `SET TRANSACTION READ ONLY` issued
      first, so a write attempt is rejected by the database itself, not
      merely discarded after the fact — proven by dedicated PostgreSQL
      tests (a write-attempting adapter and a no-op adapter, both against
      genuine `SET TRANSACTION READ ONLY` enforcement).
    - **Execution CAS / single-winner behavior:** the same atomic
      conditional-`UPDATE` admission pattern validate established
      (`dry_run_completed -> executing`), proven under genuine
      two-connection PostgreSQL concurrency to admit exactly one winner.
    - **Idempotency:** execute idempotency is **state-based replay**, per
      design §17 ("a repeat call, not a request-payload comparison") —
      `COMPLETED` always returns the existing session, `EXECUTING` is a
      running-attempt conflict, any other state requires a fresh dry-run.
      This is a deliberate, explicitly flagged deviation from the original
      task brief's compound key+fingerprint contract, which design §17
      does not define for execute (that mechanism is scoped to source
      registration, §15, only) — resolved in favor of the merged design
      per this repository's guardrail that task instructions cannot
      silently override it.
    - **Shared lease/heartbeat/fencing primitives:** `validate`, `dry_run`,
      and `execute` all admit and fence through the same implementation —
      `app/crud/import_job.py`'s `_claim_session_and_insert_job`/
      `_fence_job_terminal`/`_fence_session_terminal`, and
      `app/services/import_lease.py`'s renewal-loop/bound-failure-message/
      fence-lost-audit helpers — not per-phase copies. This was itself a
      review-round-1 fix (finding H1): the initial submission had composed
      dry-run/execute onto a new shared module while leaving `validate`
      with its own private, structurally-identical copies; fixed by
      migrating `validate` onto the same shared primitives with zero
      change to its externally observable contract (proven by the full,
      unmodified PR19A2 regression suite passing after the migration).
    - **PR19A2 validation migrated to shared primitives without semantic
      drift:** a review-round-2 finding caught that the round-1 refactor
      had inverted the original observable chronology invariant
      (`job.finished_at <= session.validated_at == session.updated_at`) by
      capturing the session's completion timestamp before the job fence
      completed; fixed by having the shared fencing primitive establish
      its own `now` strictly after the job fence succeeds and handing it
      to callers via a `Callable[[datetime], dict]` callback, restoring the
      original chronology for `validate`, `dry_run`, and `execute` alike.
    - **TX1/TX2 execution failure behavior:** identical contract to
      validate's own — TX1 rolls back in full on any exception, a clean
      TX2 attempts fenced failure publication, and a TX2 infrastructure
      failure leaves the attempt `executing` for recovery, never an
      unfenced write.
    - **Recovery:** reused from PR19A2 unchanged — dry-run/execute leases
      recover through the same generic, already-merged mechanism, requiring
      no new recovery code (design §25's own explicit claim, verified by
      recovery regression tests exercising both new phases).
    - **Retention enforcement:** implements the approved Owner Decision
      (see "Roadmap PR19A — Owner Decision #1" above) at runtime — a
      `POST /import-sessions/retention/cleanup` endpoint, an atomic
      `SELECT ... FOR UPDATE SKIP LOCKED` claim (PostgreSQL) so concurrent
      cleanup workers never claim the same session, and fenced in-place
      redaction of source/row-error PII — not merely documented as a
      future intent.
    - **Configuration fail-fast behavior:** a review-round-1 finding (H2)
      — `IMPORT_RETENTION_DAYS`, `IMPORT_RETENTION_CLEANUP_CLAIM_TIMEOUT_
      SECONDS`, `IMPORT_JOB_LEASE_DURATION_SECONDS`, and `IMPORT_JOB_
      HEARTBEAT_INTERVAL_SECONDS` now must all be positive, and the
      heartbeat interval must be strictly less than the lease duration,
      enforced by pydantic validators at `Settings()` construction (process
      startup), never deferred to the first request that touches them.
    - **Pagination correction:** a review-round-1 finding (M1) — retention
      cleanup's `has_more` flag previously used `len(claimed) >= limit`,
      which wrongly reported `true` when exactly `limit` eligible sessions
      existed; fixed with limit-plus-one selection, matching this
      codebase's other cursor-pagination helpers.
    - **Final timestamp chronology preservation:** see "PR19A2 validation
      migrated to shared primitives without semantic drift" above — this
      is the review-round-2 fix that closed PR19A3 out.
- **Review chronology:** Each slice received independent Codex review on
  its own exact head before merge, with CI green on that exact SHA in
  every case. **PR19A1:** `_verify_schema_convergence()` findings PR84-H1R/
  H1R2/H1R3, resolved before merge. **PR19A2:** one blocking review round —
  initial reviewed head `f286f6e2dfa8489923367d62c867d9b9bcf01608` was
  **REQUEST CHANGES** on finding **PR85-H1** (failure publication accessed
  ORM attributes after rollback where instances could be expired, risking
  `MissingGreenlet` and preventing the clean TX2 `validation_failed`
  publication the design required); fixed by capturing the required
  primitive identifiers/version/fence values before any rollback-capable
  work and using those captured primitives in TX2 (commit
  `7283ed5834ee95ba5a7a40cdc22502d20b47895b`, "capture pre-rollback
  primitives to fix TX2 MissingGreenlet"); the final approved head,
  `7283ed5834ee95ba5a7a40cdc22502d20b47895b`, received **APPROVE**. The
  real squash merge SHA, `7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`, is
  distinct from both the initial and final reviewed feature-branch heads
  above, per this repository's standard squash-merge SHA-retrieval
  practice — do not treat any reviewed feature head as the merged
  baseline. **PR19A3:** two review rounds — round 1 (H1 shared-primitive
  duplication, H2 configuration fail-fast, M1 pagination boundary) and
  round 2 (the validation-completion-timestamp-chronology regression
  introduced by round 1's own fix) — both resolved before the final
  APPROVE and squash merge.
- **Testing decision:** Full non-PostgreSQL and full PostgreSQL regression
  suites were run and green on the exact reviewed head before each of the
  three slices merged, including genuine two-connection PostgreSQL
  concurrency tests for admission/execution/retention-cleanup
  single-winner behavior and dedicated PostgreSQL tests proving the
  dry-run read-only enforcement. `alembic heads` remained
  `0015_import_foundation` throughout PR19A2 and PR19A3 — no new migration
  was required for either slice, since PR19A1's schema already carried
  every column both later slices needed.
- **Source:** `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`
  (GitHub PR #83, architecture-approved); GitHub PRs #84, #85, #86 and
  their linked review threads/CI runs.
- **Status:** Merged. GitHub PRs #84 (`7d589860`), #85 (`7e5e6f2d`), #86
  (`7f13a1e8`) — all three PR19A implementation slices are complete.
  **Roadmap PR19A (Legacy Import Foundation, backend) is now fully
  complete.** `7f13a1e85e9b6a4828170c4b12bc2be27b15de39` is the current
  authoritative base-branch tip.
- **Consequences:**
  - **PR19A is the backend import framework only.** No concrete legacy
    dataset import is implemented: Equipment Master, Receive History, and
    Issue History import business logic remain future Roadmap PR20/PR21
    scope, per the design's own §26 (Non-Goals) — nothing in PR19A1,
    PR19A2, or PR19A3 implements, approves, or finalizes PR20 or PR21's
    own design.
  - **Roadmap PR19 as a whole is not yet complete.** Per the "Roadmap PR19
    approved split" Exception Record above, Roadmap PR19 requires every
    slice — PR19A's own PR19A1/PR19A2/PR19A3 (now merged), PR19B, and the
    realignment/governance-sync work that follows — to be merged. PR19B
    (`feature/pr19b-import-frontend-skeleton`, Draft PR **#80**) remains
    open, not independently reviewed or merged, and its provisional
    frontend contracts (`frontend/src/types/legacyImport.ts`,
    `legacyImportClient.ts`) still require reconciliation against PR19A's
    now-fully-merged authoritative contract before its own Exception
    Record (Part B) can close — none of that reconciliation's seven
    required steps have happened as of this entry.
  - **GitHub PR #81** (`feature/pr19a-legacy-import-foundation`), an
    earlier, unsplit PR19A design-and-implementation candidate opened
    before the PR19A1/PR19A2/PR19A3 decomposition existed, was **closed
    without merging** on 2026-08-03, superseded by the slice sequence
    actually merged as PR #84/#85/#86. It introduced no runtime change to
    the repository.
  - **No change to any other Roadmap PR's scope**, business rule,
    lifecycle state, or workflow. This entry is documentation/governance
    synchronization only — no backend, frontend, migration, test, or CI
    file was modified to produce it.

## 2026-08-11 — Roadmap PR19B merged: Exception Record closed; Roadmap PR19 fully complete

- **Decision:** None — this is a documentation/governance synchronization
  entry, not a new Owner Decision. It records that Roadmap PR19B (Legacy
  Import Frontend Skeleton) has merged, that the Exception Record governing
  the Roadmap PR19 split ("Roadmap PR19 approved split: PR19A (backend) /
  PR19B (frontend skeleton)" above) is now CLOSED, and that Roadmap PR19
  (Legacy Import Foundation, backend + frontend skeleton) as a whole is now
  fully complete.
- **What was built:** PR19B is a **frontend-only, user-reviewable Legacy
  Import workflow skeleton**: navigation entry points (including mobile
  discoverability), Administrator-only visibility and route guarding,
  import-category selection (Equipment Master / Receive History / Issue
  History preview labels), `.xlsx` file-selection UX with category-change
  file reset, and mock-backed session list/detail/result presentation
  reconciled against PR19A's merged public contracts. It explicitly does
  **not** provide real file upload, real workbook parsing, real
  validation/dry-run/import execution, production legacy dataset adapters,
  or concrete Equipment Master/Receive History/Issue History import — those
  remain future Roadmap PR20/PR21 scope, not implemented by this merge.
  - **Reconciliation against merged PR19A contracts** (design
    `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`): frontend types
    (`frontend/src/types/legacyImport.ts`) and the mock client
    (`frontend/src/services/legacyImportClient.ts`) were aligned to the
    real `ImportSessionOut` contract, including nullable `imported_rows`
    and the `failure_reason` field.
  - **Invariant-enforced fixtures:** a new
    `frontend/src/utils/legacyImportInvariants.ts` module
    (`assertImportSessionInvariants()`) encodes the backend's real
    invariants — distinct-row counting (design §12: `invalid_rows`/
    `warning_rows` are independent, possibly-overlapping projections;
    `valid_rows = total_rows - invalid_rows` only, never also minus
    `warning_rows`), the state-machine reachability rules (design §5:
    dry-run only reachable from `VALIDATED`, implying zero invalid rows for
    every status reachable from there), and terminal-state rules (design
    §18: `terminal_at` set only for, and always for, `COMPLETED`/`FAILED`/
    `CANCELLED`). `frontend/src/services/legacyImportFixtures.ts` was
    rebuilt around a `buildDetail()` factory that derives every counter
    from a `findings` array and calls this guard before returning, so an
    impossible mock state cannot silently exist.
  - **Two legitimate flavors of `validation_failed` distinguished**
    (design §9.4.1 vs §9.4.2, §16): a structural/crash failure (TX1 rolls
    back entirely — null counters, empty findings, non-null
    `failureReason`) versus a clean completion that found blocking errors
    (TX1 commits — real counters/findings, null `failureReason`). Both are
    represented by distinct fixtures
    (`VALIDATION_FAILED_FIXTURE`/`VALIDATION_FAILED_WITH_FINDINGS_FIXTURE`).
  - **Truthful terminal-outcome presentation:** `LegacyImportResultSummary`
    renders a status-specific outcome — a green success card only for
    `completed` (with the real imported-row count, or an explicit
    "unavailable" message if `importedRows` is `null`, never a fabricated
    `0`), a red failure message for `failed`, and a neutral cancellation
    message for `cancelled` — never a single hardcoded success card
    regardless of outcome.
- **Review chronology (GitHub PR #80):** three independent-review rounds
  on exact heads, each with CI run on that same head.
  - **Round 1 — reconciliation head**
    `71dc97df583f60c3e9f8bccbbcb2e72b0b7307d5`: **REQUEST CHANGES.**
    **PR80-H1:** mock fixtures violated backend invariants (e.g. warning
    rows double-subtracted from valid rows, impossible dry-run-completed
    states with blocking ERROR findings). **PR80-H2:** failed/cancelled
    result presentation could falsely appear successful (a single
    hardcoded success card regardless of `status`).
  - **Round 2 — fix head** `6139bd4abd44c0a4ac07bf6ac63bf1b897dad653`:
    **REQUEST CHANGES.** PR80-H2 fully resolved; PR80-H1 mostly resolved,
    with one remaining finding, **PR80-H1R** — the structural
    `validation_failed` fixture claimed null counters *and* a persisted
    `ValidationFinding` simultaneously, a state the real backend (TX1
    rollback semantics, design §9.4.2) can never publish — plus a
    non-blocking observation that nullable `importedRows` must not be
    silently coerced to `0`.
  - **Round 3 — final fix head, the reviewed head that merged**
    `5edf1bfd8de7013eb74f300193456c9e5c0f0332`: **APPROVE**, CI green
    (6/6). Confirmed: the structural validation-failure fixture now aligns
    with TX1/TX2 semantics (null counters, empty findings, non-null
    `failureReason`); completed-with-errors validation findings/counters
    are coherent; impossible mock states are rejected by the invariant
    guard's own rejection tests; failed/cancelled presentation is truthful;
    `importedRows: null` is rendered distinctly from an actual `0`;
    frontend-only scope is preserved (no real import/API execution
    introduced); CI 6/6 green.
  - **Merge:** PR19B merged as GitHub PR **#80**. Its real squash-merge
    SHA, `04f5bf5c76b51744981d1cc8072c074e604224e9`, is distinct from the
    final reviewed feature-branch head above
    (`5edf1bfd8de7013eb74f300193456c9e5c0f0332`) — per this repository's
    standard squash-merge SHA-retrieval practice, the reviewed head is
    never treated as the merged baseline; `04f5bf5c...` (parent
    `bc4d490bd0e9b85eb6d630fc7aa013c801b333c9`, itself parented on
    `7f13a1e85e9b6a4828170c4b12bc2be27b15de39`, GitHub PR #86) is the
    actual commit landed on the base branch and is now the current
    authoritative baseline.
- **Testing decision:** Frontend test suites (`legacyImportFixtures.test.ts`,
  37 tests; `LegacyImportResultSummary.test.tsx`, 8 tests; plus corrected
  `LegacyImportSessionDetailPage.test.tsx` / `LegacyImportListPage.test.tsx`
  fixtures) were run and green on the exact reviewed head
  (`5edf1bfd8de7013eb74f300193456c9e5c0f0332`) before merge, alongside the
  full existing frontend suite. No backend, migration, or PostgreSQL test
  changed — PR19B introduces no backend, migration, or API change.
- **Source:** `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`
  (GitHub PR #83, the authoritative backend contract PR19B was reconciled
  against); GitHub PR #80 (`feature/pr19b-import-frontend-skeleton`) and
  its linked review threads/CI runs.
- **Status:** Merged. GitHub PR #80, squash SHA
  `04f5bf5c76b51744981d1cc8072c074e604224e9`. **Roadmap PR19B (Legacy
  Import Frontend Skeleton) is now fully complete.** Combined with
  "Roadmap PR19A complete: PR19A1 + PR19A2 + PR19A3 merged" above,
  **Roadmap PR19 (Legacy Import Foundation, backend + frontend skeleton)
  as a whole is now fully complete.** The Exception Record governing the
  Roadmap PR19 split ("Roadmap PR19 approved split" above, Part B) is
  **CLOSED** — all seven required closure steps are satisfied and recorded
  there. `04f5bf5c76b51744981d1cc8072c074e604224e9` is the current
  authoritative base-branch tip, superseding
  `7f13a1e85e9b6a4828170c4b12bc2be27b15de39` for current-state purposes
  (the latter remains accurate as historical provenance for Roadmap PR19A).
- **Consequences:**
  - **Roadmap PR19 is complete, but concrete legacy dataset import is
    not.** PR19B remains a frontend-only workflow-review skeleton: no real
    file upload, workbook parsing, validation/dry-run/import execution, or
    production legacy dataset adapter exists. Concrete Equipment Master,
    Receive History, and Issue History import business logic remain future
    Roadmap PR20/PR21 scope — merging PR19A and PR19B does not, by itself,
    provide end-to-end production import of legacy hospital datasets.
  - **Backend remains the sole source of truth** for import lifecycle
    states, validation rules, state transitions, permissions, dry-run
    safety, execution idempotency, and retention. PR19B's frontend
    types/mock fixtures were reconciled against PR19A's merged contracts
    for presentation purposes only; nothing in PR19B redefines, overrides,
    or duplicates ownership of any backend business rule.
  - **GitHub PR #81** remains closed without merge, superseded by
    PR19A1/PR19A2/PR19A3 (see "Roadmap PR19A complete" above) — this entry
    does not reopen or otherwise change PR #81's status.
  - **PR20/PR21 sequencing is unchanged by this entry.** PR20 has only
    ever depended on PR19A, not PR19B
    (`docs/audits/04-consolidated-implementation-plan.md`: "Dependencies:
    PR19A ... PR19B is a frontend preview only and is not a dependency").
    A separate, still-unresolved question of *relative sequencing*
    (not a hard dependency) between PR19B and PR20 was left TBD in
    `docs/ROADMAP_STATUS.md` pending an Owner Decision while PR19B was
    still provisional; PR19B's merge does not itself resolve that
    question, and this entry does not create a new Owner Decision to
    resolve it. PR20 remains the next planned, not-yet-started Roadmap
    item.
  - **Owner Decision #2** (branding configuration ownership, recorded
    elsewhere in this log) is unaffected by this entry and remains open.
  - **No change to any other Roadmap PR's scope**, business rule,
    lifecycle state, API, or database schema. This entry, and the
    governance-sync PR that introduces it, are documentation/knowledge-only
    — no backend, frontend, migration, test, or CI file was modified to
    produce them. Roadmap PR20 has not been started by this entry.
