# Roadmap PR18 — Printing & Export Architecture: Design Proposal

**Status:** Design only. Nothing in this document has been implemented. No backend code, frontend code, Alembic migration, database schema change, or API modification was written to produce it.
**Repository:** Medical Equipment Pool. This is **not** MEMS and **not** Recall Monitor — no coupling to either system is introduced or assumed anywhere below.
**Baseline investigated:** `bc9e43b120aa7d0c4cfa6471be577f92ea910214` — squash commit of GitHub PR #70 (the operator-options cursor-hygiene maintenance fix), on branch `claude/medical-equipment-pool-0c7fz0`. Roadmap PR17 (Operational Reports, design + all four Implementation Slices) is fully merged and closed in governance at this baseline (`docs/DECISION_LOG.md` "Roadmap PR17 — Operational Reports Complete").
**Governing instruction:** DESIGN ONLY. Produce the minimum design documentation required for an independently reviewable PR18A Design PR. No implementation, no migration, no API change, no existing-file modification, no frontend change.

---

## 1. Objective

Design Roadmap PR18 — **PDF export, Excel export, and print-ready Hard Copy templates for the PR17 reports** (`docs/ROADMAP.md`'s "Approved forward sequence" table; `docs/audits/04-consolidated-implementation-plan.md`'s `#### PR18 — Reporting output` entry). PR18 adds output formats for three already-implemented, already-reviewed report families — it does not add a fourth report, does not change what any report contains, and does not touch the completed Reporting Foundation (Roadmap PR16) or Operational Reports (Roadmap PR17) query/filter/authorization logic in any way.

This document treats **Roadmap PR16 and PR17 as authoritative and unchanged** (§2). It is a **design PR** (PR18A) — implementation is split into later, independently reviewable slices (§17).

---

## 2. Authoritative Inputs

Documents and implementation areas inspected and treated as authoritative for this design, in the order consulted:

| Area | Source | What it established |
|---|---|---|
| Roadmap PR18 scope (authoritative) | `docs/audits/04-consolidated-implementation-plan.md` Part D (`#### PR18 — Reporting output`) | Objective: "Add PDF export, Excel export, and print-ready Hard Copy templates for the PR17 reports." Dependency: PR17. Acceptance criterion: "All three report families can be exported and printed without changing transaction or lifecycle business rules." |
| Report data contracts (must not be redesigned) | `backend/app/schemas/transaction.py` (`ReportTransactionOut`), `backend/app/schemas/equipment.py` (`EquipmentOut`), `backend/app/schemas/common.py` (`Page[T]`) | `GET /reports/receive`/`GET /reports/issue` already return `Page[ReportTransactionOut]`; `GET /reports/equipment-verify-checklist` already returns `Page[EquipmentOut]`. These are the exact, already-reviewed field sets every on-screen report renders today — no field is hidden from the operator that export/print would need to newly expose, and no field exists in the DTO that export/print must newly hide (`EquipmentOut` already excludes `item_no`, per ADR-002/ADR-003; `ReportOperatorOut` already excludes auth/contact fields). |
| Report query/filter logic (must not be redesigned) | `backend/app/api/v1/reports.py`, `backend/app/crud/transaction.py`, `backend/app/crud/equipment.py`, `backend/app/crud/user.py::list_operators` | Receive/Issue/Equipment-Verify-Checklist filtering, ordering, and business-date/shift semantics are fully implemented and reviewed (Roadmap PR16/PR17). Every export/print code path this design adds must call the *same* filter-validation and query functions the on-screen endpoints already call — never a parallel filter implementation (`docs/ARCHITECTURE_GUARDRAILS.md`: "Do not create parallel audit, database-access, state-transition, or workflow mechanisms when an authoritative path exists.") |
| PR17's own explicit forward-note for PR18 | `docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md` §11, §13 | §13 ("Printing (Deferred to Roadmap PR18)"): "every report returns already-paginated, already-filtered JSON data that a future PR18 design can format for print, PDF, Excel, or CSV without requiring PR17's own endpoints, query functions, or on-screen components to change." §11: "If PR18 needs export/print of these same three reports, it consumes these same endpoints' data (or a shared query function directly) rather than re-deriving report contents independently." This design follows both instructions directly (§6, §8). |
| Existing dependency footprint | `backend/requirements.txt`, `frontend/package.json` | `openpyxl>=3.1.5` is **already installed** (used by the pre-existing legacy `GET /reports/export` endpoint, below in this table). No PDF library exists on backend or frontend. No print CSS exists anywhere in the frontend (confirmed via repository-wide search — zero matches for `print`/`window.print`/`@media print`). No i18n library is installed; Thai text is hard-coded directly in JSX, consistent with the rest of the frontend. |
| Existing role gate | `backend/app/api/v1/deps.py` | `VIEW_AND_REPORT_ROLES = (ROLE_ADMINISTRATOR, ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY)` — the exact gate every existing report endpoint already uses. §11 keeps this unchanged. |
| Pre-existing, unrelated export endpoint | `backend/app/api/v1/reports.py::GET /reports/export`, `backend/app/services/report_service.py` | A **legacy, pre-PR16/PR17 endpoint**, unrelated to the Receive/Issue/Equipment-Verify-Checklist report family this design covers. Exports raw `BorrowTransaction` rows using retired fields (`due_at`, `condition_on_return` — preserved read-only history per Roadmap PR7/PR8, not on the active write path) with no `business_date`/`shift` filtering. Flagged as a pre-existing CSV/XLSX formula-injection gap by PR16's design doc §12 ("noted for completeness... a latent gap that predates PR16... flagged here as relevant context PR18 (export) must address when it introduces any export of business_date/shift-bearing data"). Addressed directly in §14/§19 below — this design does not extend or reuse that endpoint. |

---

## 3. Business Goal

Give Equipment Pool Staff, Administrators, and Read Only users a way to take a Receive Report, Issue Report, or Equipment Verify Checklist result **out of the browser** — as a physical printed page, a saved PDF, or an Excel workbook — for handoff to ward staff, filing, or offline review, **without ever changing what the report contains or how it is computed.** The three output formats exist because hospital operational workflows need different things from the same data: a quick printed page at a nursing station (Browser Print), an emailable/archivable fixed document (PDF), and a working spreadsheet for further filtering/sorting by the recipient (Excel).

---

## 4. Design Philosophy

1. **Backend remains the source of truth for report content and semantics** — export/print never re-derives, re-filters, or re-sorts data the backend already decided. This restates the same principle Roadmap PR16 §6/§10 and PR17 §12 already established for on-screen rendering, extended to every new output format.
2. **No duplicate filtering.** Every export/print code path calls the *existing* Receive/Issue/Equipment-Verify-Checklist query functions with the *existing* filter parameters — never a second, parallel query implementation.
3. **No client-side report logic.** The frontend never computes `business_date`/`shift`, never re-sorts rows, and never decides report eligibility for print/export, exactly as it already does not for on-screen rendering.
4. **Minimal new abstraction.** Reuse existing DTOs (`ReportTransactionOut`, `EquipmentOut`) wherever the *data* is unchanged; introduce a new structure only where a genuinely new concern exists (rendering metadata, §7).
5. **No new runtime dependency without justification.** `openpyxl` is already present and sufficient for Excel (§9). A new PDF-rendering dependency is unavoidable (§8) — its footprint and operational cost are stated explicitly, not hidden.

---

## 5. Architecture

```
Business Workflow (dispatch/receipt/master-data — unchanged, Roadmap PR6-PR9)
        ↓
Report Query Functions (transaction_crud / equipment_crud / user_crud — unchanged, Roadmap PR16/PR17)
        ↓
   ┌────────────────────────────┬─────────────────────────────┐
   │                            │                              │
 On-screen JSON API          NEW: Export Query               (same functions,
 (GET /reports/receive       (same functions, same filters,   different call
  etc. — unchanged,           cursor=None, bulk-capped —       shape — §6)
  Page[T], cursor-paginated)  §6)
   │                            │
   ↓                            ↓
Frontend on-screen table    Report Render Context
(unchanged, Roadmap PR17)   (title, generated_at, applied-filter
                             summary, rows — §7, backend-internal,
                             not a new public API DTO)
                                │
                    ┌───────────┼───────────┐
                    ↓           ↓           ↓
              HTML/print CSS  Excel writer  PDF renderer
              template        (openpyxl,    (backend HTML→PDF,
              (frontend)      §9)           reuses the render
                    │                        context's structure,
                    ↓                        §8)
              Browser Print                  ↓
              (window.print(),          Downloaded .pdf
               §10)                     Downloaded .xlsx
```

The on-screen report screens (Roadmap PR17, unchanged) and the new export/print pipeline both originate from the *same* query functions — they diverge only at the point where a bounded, cursor-paginated JSON page is no longer the right shape for "the whole filtered report as one document" (§6). Nothing upstream of that divergence point is touched by this design.

---

## 6. API Strategy

**Evaluated: separate export endpoints per report vs. a shared report endpoint with an export/format parameter.**

| | Separate endpoints (recommended) | Shared endpoint + `format` param |
|---|---|---|
| Response model | Each endpoint has one clear contract: binary file download (`Response` with `Content-Type`/`Content-Disposition`) for export; the existing `Page[T]` JSON is untouched. | The same route would need to switch between `Page[T]` JSON and a raw binary `Response` depending on a query parameter — an awkward, dual-shaped contract that breaks OpenAPI's ability to describe one clean response model per route. |
| Pagination semantics | Export explicitly is **not** paginated — it is "the whole filtered report, bounded by a hard row cap" (§6.1). A separate route makes that difference explicit in the URL and the OpenAPI docs. | Reusing `/reports/receive` for export would require `limit`/`cursor` to mean something different depending on `format`, which is confusing and error-prone for API consumers and for future maintainers. |
| Precedent | Matches this repository's own existing precedent: `GET /reports/export` (§2, legacy) is *already* a separate route from any on-screen `Page[T]` endpoint, not a query parameter on one. | No existing precedent in this codebase for a single route returning different response shapes by parameter. |
| Filter reuse | Both approaches reuse the same filter-parsing/validation code either way — this is an implementation detail of the handler, not the routing decision. | Same. |

**Recommendation: separate export endpoints, one per report, under an `/export` sub-path**, reusing the identical query-parameter contract (filters) as their on-screen counterparts:

- `GET /reports/receive/export`
- `GET /reports/issue/export`
- `GET /reports/equipment-verify-checklist/export`

Each accepts the exact same filter query parameters as its on-screen sibling (`business_date_from`, `business_date_to`, `shift`, `ward_id`, `equipment_category_id`, `operator_id`, etc. for Receive/Issue; `equipment_category_id`, `status`, `department_id` for the checklist) plus one new parameter:

- `format: Literal["xlsx", "pdf"]` — which artifact to generate. Browser Print does **not** go through this endpoint (§10) — it consumes the same bulk data via a dedicated, unauthenticated-by-format JSON fetch described in §6.1, then renders client-side.

Role gate: `require_roles(*VIEW_AND_REPORT_ROLES)` — identical to every existing report endpoint (§11). Business-date range validation reuses the exact same `_validate_business_date_range` helper `reports.py` already defines for the on-screen Receive/Issue endpoints.

### 6.1 Bulk fetch, not pagination

Export and Print both need "the complete filtered result set," not one cursor page. The underlying query functions (`transaction_crud.search`-family, `equipment_crud.list_for_verify_checklist`) are called with `cursor=None` and a **hard row cap** distinct from the on-screen page-size limit — per `docs/ARCHITECTURE_GUARDRAILS.md`'s explicit prohibition on "unbounded collection reads." A recommended cap (`MAX_EXPORT_ROWS`, a fixed constant, not client-controlled) is validated against this system's confirmed real-world scale (`docs/KNOWN_LIMITATIONS.md`: "low hundreds of devices, thousands of transactions per year") — the exact number is an implementation-slice detail (§17), not a design blocker, but the *shape* of the guard is fixed here: **if the filtered result set exceeds the cap, the endpoint returns a structured client error (a new `DomainError` subclass, e.g. `ExportTooLargeError`, HTTP 422) asking the operator to narrow their filters — it never silently truncates.** Silent truncation of a hospital operational record would violate the "backend remains source of truth" principle as badly as omitting a filter: a truncated report that looks complete is worse than an explicit refusal.

Browser Print (§10) reuses this same bulk-fetch shape via a JSON-returning sibling of the export endpoints (or the export endpoints themselves with `format` omitted and `Accept: application/json`, an implementation-slice decision) — never the paginated on-screen endpoint — so **the same row-cap guard applies uniformly to Print, PDF, and Excel.**

---

## 7. Print DTO

**Decision: no new public/API-facing DTO for report data. `ReportTransactionOut` and `EquipmentOut` are reused unchanged.** A new, backend-internal (non-API) rendering-context structure is warranted for presentation metadata that is not report business data.

**Justification.** The three output formats render the *same rows* the on-screen tables already render — introducing a second DTO shaped identically to `ReportTransactionOut`/`EquipmentOut` purely for export would be exactly the kind of parallel structure `docs/ARCHITECTURE_GUARDRAILS.md` warns against, and would create a second place a future field addition could be forgotten. The bulk-export query (§6.1) returns the same Pydantic models the on-screen `Page[T]` responses already use; only the *pagination envelope* (`Page[T]`'s `next_cursor`/cursor semantics) does not apply to a bulk, single-shot export — the bulk response is `list[ReportTransactionOut]` / `list[EquipmentOut]` directly, or `.xlsx`/`.pdf` bytes for the download formats.

What genuinely does **not** exist in any current DTO, because it is not report business data: the report **title**, the **generated-at timestamp**, and a **human-readable summary of the applied filters** (e.g. "ช่วงวันที่: 1–15 ก.ค. 2569 · กะ: กลางวัน · หอผู้ป่วย: อายุรกรรม 1"). This is presentation/rendering metadata, constructed once per export/print request from the already-validated filter parameters and the current server time — it never needs to be queried, stored, or exposed as a reusable API resource. It is represented as a small backend-internal structure (a plain dataclass or an unexposed Pydantic model, an implementation-slice detail) — call it a **Report Render Context** — consumed directly by the format renderers (§9, §10) and never serialized as a standalone API response. This satisfies the task's "Print DTO" question precisely: existing DTOs are sufficient for *data*; a dedicated (but non-API) structure is required for *rendering metadata*, and the two are kept distinct so the public API surface (§6) never grows a field that exists only to support formatting.

---

## 8. PDF Strategy

**Evaluated: backend rendering vs. frontend rendering.**

| | Backend rendering (recommended) | Frontend rendering |
|---|---|---|
| Consistency | One artifact, generated identically regardless of the requesting browser/OS/printer driver — critical for hospital devices with inconsistent browser versions (`docs/KNOWN_LIMITATIONS.md` context: modest device fleet, no guarantee of a modern evergreen browser everywhere). | `jsPDF`/`html2canvas`-class libraries render inconsistently across browsers and produce lower-fidelity output for complex tables and Thai text shaping; visual result depends on the client's font availability, which this repository does not currently control (§2 — no bundled Thai webfont exists yet). |
| New dependency | One new backend dependency (an HTML→PDF library). | One new frontend dependency, plus the frontend bundle grows for a capability only a minority of report views will use. |
| Source-of-truth alignment | Matches "backend remains source of truth" directly — the same service that already computed and validated the report content also produces the downloadable, archival artifact. | Requires trusting the client to faithfully reproduce backend-decided content in a downloadable file — a weaker guarantee for an operational/audit record. |
| Thai text and complex layout | Python HTML→PDF libraries (the recommended class, below) have mature Unicode/Thai shaping support via the same font-embedding mechanism used for any language. | Client-side PDF libraries have historically weaker complex-script (Thai) text shaping, especially for combining vowel/tone marks. |

**Recommendation: backend-rendered PDF, via an HTML→PDF library in the WeasyPrint class** (pure-Python, HTML+CSS input, PDF output, supports CSS Paged Media — page counters, running headers/footers — better than any Chromium print engine does, see §10.3). The backend renders a Jinja2 (or equivalent) HTML template — populated from the same Report Render Context (§7) and the same bulk-fetched rows (§6.1) — into a PDF.

**Explicitly rejected alternative: headless-browser rendering (Playwright/Puppeteer navigating the frontend's own print view and exporting to PDF).** This would guarantee pixel-perfect parity between the interactive Browser Print view and the downloaded PDF by construction — a real advantage — but was rejected for this design because it requires running a browser-automation service in production, a materially heavier operational footprint (memory, image size, a new failure mode class) than this system's confirmed scale justifies, and is inconsistent with this repository's own established practice of evidence-gating new infrastructure before adopting it (Roadmap PR14B's `EXPLAIN ANALYZE`-gated indexing decision is the precedent). **Accepted trade-off:** the browser print CSS (frontend, §10) and the backend PDF template (Jinja2, backend) are therefore two separate template implementations, not one — both driven by the same Report Render Context and the same column/title/filter-summary specification (§12, "Future Extension"), but not byte-identical markup. This is stated as a known, bounded duplication, not hidden — implementation slices (§17) must include a visual-parity review between the two as an explicit test step, not an automated byte-comparison.

**Explicitly rejected alternative: a native PDF-drawing library (e.g. ReportLab).** Requires re-implementing table layout, pagination, and text wrapping in Python drawing primitives rather than HTML+CSS — meaningfully more implementation and maintenance cost for the same result, with worse complex-script text support than an HTML-based renderer, and no reuse of any layout knowledge the frontend's print CSS will already encode. Not recommended.

---

## 9. Excel Strategy

**Recommendation: `.xlsx` via `openpyxl`**, already an installed dependency (§2) — no new backend dependency for this format. Formatting suitable for hospital operational use, built on the bulk-fetched rows (§6.1) and the same column set the on-screen tables already render:

- **Header row styling:** bold, filled background, frozen (`ws.freeze_panes`) so column headers stay visible while scrolling a long exported sheet.
- **Column widths:** sized to content (or a sane fixed default per column), not Excel's raw character-count default — a bare `openpyxl` dump (as the legacy `report_service.export_xlsx`, §2, currently does) is not "suitable for hospital operational use" on its own.
- **Date/timestamp formatting:** `business_date` as a real Excel date cell (`number_format`), not a string, so recipients can sort/filter natively; `business_date`/`shift` rendered exactly as the on-screen table shows them (Thai shift labels), never re-derived.
- **A metadata row or separate sheet** carrying the same title/generated-at/filter-summary the Report Render Context (§7) already assembles — so an exported workbook is self-describing even after being detached from the application (renamed, emailed, archived).
- **Formula-injection defense (new export code only):** every free-text cell value (e.g. `borrower_name`-derived display strings, notes) is defensively prefixed/escaped if it begins with `=`, `+`, `-`, or `@`, per the exact gap PR16's design doc flagged as pre-existing in the *legacy* `report_service.export_xlsx`/`export_csv` (§2, §19) — the new export code introduced by this design must not repeat that gap, even though fixing the legacy endpoint's existing instance of it is out of this design's scope (§19, `TECH_DEBT.md`).

CSV is **not** recommended as a first-class PR18 output — the Roadmap's own acceptance criterion names PDF, Excel, and print-ready Hard Copy specifically, not CSV, and CSV cannot carry the formatting (frozen headers, real date types, styled header row) that makes an exported workbook usable to a recipient. (The legacy `/reports/export` endpoint already offers CSV for its own unrelated purpose — §2, §19 — and this design does not extend that.)

---

## 10. Browser Printing

A dedicated print view, built in the frontend from the bulk-fetched rows (§6.1) and Report Render Context (§7) — **not** the on-screen paginated table re-styled — driven by `@media print` CSS, invoked by an explicit "Print" action (not a bare `window.print()` on the current page, since the current page may only have one cursor-page loaded).

### 10.1 Layout

**Landscape A4 is the recommended default for all three report types.** Both `ReportResultsTable` (Receive/Issue, 8 rendered columns per the on-screen component: transaction no., equipment, ward, dispatch operator, dispatch date/shift, receipt operator, receipt date/shift, receipt outcome) and the Equipment Verify Checklist's rendered column set are wide enough that portrait A4 would force cramped columns or wrapped headers. Landscape is stated as the default, not an absolute — a future report with genuinely few columns may reasonably use portrait, decided per-template at implementation time, not redesigned here.

### 10.2 Fonts

**Gap identified, must be closed as part of this initiative:** the frontend currently references `"Noto Sans Thai"` **by name only** in `tailwind.config.ts`'s font stack, with no `@font-face`/bundled webfont anywhere (§2). This is adequate for on-screen rendering on a device that happens to have the font installed, but is **not reliable for print or PDF**, where consistent glyph rendering across arbitrary hospital-owned printers/browsers/OS font sets matters. **Recommendation: bundle a self-hosted Thai webfont** (`@font-face`, shipped as a static asset) for the print stylesheet and reused as the PDF template's embedded font (§8) — both renderers then depend on the *same* bundled font file, not on OS-provided fonts, guaranteeing identical glyph shapes between the two. Noto Sans Thai (already the named fallback) is the default recommendation; THSarabunNew (the Thai government's standard document font) is noted as an alternative more conventional for official Thai paperwork, left as an implementation-slice/visual-review decision, not a design blocker.

### 10.3 Header, footer, filter summary, timestamp

- **Table column headers** (the data column row, e.g. "เลขที่รายการ", "เครื่องมือ") repeat on every printed page via the table's native `<thead>`/`display: table-header-group` — universally supported by browser print engines and by the WeasyPrint-class PDF renderer (§8); no special handling required beyond correct HTML structure.
- **Document header/footer** (report title, applied-filter summary, generated-at timestamp) is **not** the same mechanism as the table header. CSS Paged Media's `@page { @top-center {...} }` margin-box content — the technically "correct" way to do this — has inconsistent-to-nonexistent support in Chromium's print engine (Chrome does not render `@page` margin-box content as of current versions). **Recommendation: `position: fixed` elements scoped to `@media print`**, the pragmatic, broadly-compatible technique real-world browser-print implementations use, placing the title/filter-summary/timestamp block at the top and a footer block at the bottom of every printed page.
- **Page numbering ("Page X of Y") is honestly split by output format, not promised uniformly:**
  - The **backend-rendered PDF path** (§8) genuinely supports `counter(page)`/`counter(pages)` via CSS Paged Media, since WeasyPrint-class renderers implement that specification — accurate "หน้า X จาก Y" is achievable there.
  - The **interactive Browser Print path** cannot reliably compute a page count from CSS/JS before the browser's own print engine paginates the content — this is a well-known, real browser limitation, not an oversight. **Recommendation: the Browser Print view states "พิมพ์เมื่อ: [timestamp]" and the applied filter summary, but does not attempt a false "Page X of Y"** — if the end user wants a numbered hard copy, the browser's own print dialog page-range/number option remains available outside this application's control, or they use the PDF export path instead. This constraint is stated here explicitly so no implementation slice (§17) is scored against an unachievable acceptance criterion.

### 10.4 Landscape vs. portrait — summary

Landscape A4 default (§10.1); no additional decision needed here.

---

## 11. Security

**No new permission or capability is introduced.** Every export/print code path (§6, §6.1) is gated by the exact same `VIEW_AND_REPORT_ROLES` (`administrator`, `equipment_pool_staff`, `read_only`) every existing report endpoint already requires — the same three roles that can already view a report on-screen can already export or print it; no role gains a capability it did not already effectively have (viewing the data), and no role is newly excluded. `require_roles(*VIEW_AND_REPORT_ROLES)` is reused verbatim, not reimplemented.

**No new data exposure.** Export/print render exactly the fields the reused DTOs (§7) already carry — `EquipmentOut`'s existing exclusion of `item_no` (ADR-002/ADR-003) and `ReportOperatorOut`'s existing exclusion of contact/auth fields are inherited automatically, not something this design must re-implement or could accidentally weaken, because no new DTO is introduced for report data.

**Bulk-fetch bounding (§6.1) is itself a security-adjacent guardrail**, not only a performance one — an unbounded export endpoint would be a straightforward resource-exhaustion vector; the hard row cap with an explicit rejection (rather than silent truncation or unbounded computation) closes that.

---

## 12. Future Extension

Architecture should support a future report module (e.g., a hypothetical later Roadmap item introducing a new report family) without redesign. This is satisfied by keeping the format renderers (Excel writer, PDF renderer, print-CSS template) **generic over a Report Render Context + row source**, rather than hardcoded per report:

- A backend-internal registration concept — call it a **Report Export Spec** (column definitions, title, the query function to call for bulk fetch, format eligibility) — is the seam a future report registers against. This is purely a backend organizational structure, never exposed via the API, and is an implementation-slice detail (§17), not something this design PR builds.
- Because the Report Render Context (§7) and the Report Export Spec above are decoupled from any single report's DTO shape, adding a fourth report later means registering its existing query function and column spec, not touching the Excel writer, PDF renderer, or print-CSS shell.

---

## 13. Out of Scope

Restating and extending PR17 §21's own out-of-scope list, since none of it is newly in scope here:

- **Physical verification** (Equipment Verify Checklist remains the read-only master-data snapshot Owner Decision #1 established — PR18 exports/prints that snapshot exactly as-is; it does not add a verification workflow, verified-by/verified-at fields, or any new equipment lifecycle state).
- **Analytics, BI, dashboards.** These remain operational reports (§3), not analytical ones — no aggregation, trend, or summary view is introduced.
- **MEMS, Recall Monitor.** No coupling to either, per this repository's standing scope boundary.
- **Offline mode.** Export/print require the same authenticated, online API access every other report screen already requires; no offline-generation or service-worker-cached report capability is designed here.
- **The legacy `GET /reports/export` endpoint's own retirement or CSV formula-injection fix.** Flagged in §2/§14/§19 as a pre-existing, unrelated gap this design does not extend — its disposition (retire, leave as-is, or fix in place) is a separate decision point, not resolved by this document (§14).
- **CSV as a first-class PR18 output format** (§9) — the Roadmap names PDF, Excel, and print specifically.

---

## 14. Decision Points Requiring Repository Owner Confirmation Before Implementation

Unlike Roadmap PR16 (Owner Decision #1: shift boundary policy) and Roadmap PR17 (Owner Decision #1: Equipment Verify Checklist definition), **this design does not require a business-policy Owner Decision to proceed** — every choice made above (separate export endpoints, backend-rendered PDF, `openpyxl` for Excel, landscape A4, `position: fixed` print headers) is an engineering trade-off within already-approved Roadmap PR18 scope, not an open question about what the hospital's process should be. Implementation may begin directly from this design once reviewed.

One narrower confirmation is flagged for the Repository Owner before **PR18B** (or whichever implementation slice touches it) proceeds, since it is a compatibility question, not a pure engineering one:

- **Disposition of the legacy `GET /reports/export` endpoint (§2, §19).** This design does not extend, reuse, or depend on it. Before any implementation slice retires or modifies it, confirm whether any external consumer currently depends on it (none is known from repository inspection, but this design cannot itself rule that out) — if none, it is a reasonable candidate for retirement once the three new report-family export endpoints ship, superseding its purpose; if a dependency exists, it should be left running unmodified, distinct from and unaffected by this design's new endpoints.

---

## 15. Testing Considerations for Implementation Slices

Not implemented here — stated for the implementation slices (§17) to inherit:

- Bulk-export query functions must be tested against the same filter/authorization matrix the on-screen endpoints already have, plus the row-cap-exceeded rejection path (§6.1).
- Excel output must be verified to contain real typed date cells (not strings) and the formula-injection escaping (§9) for at least one deliberately formula-shaped free-text input.
- PDF output must be verified for at least: correct row count matching the bulk-fetch result, page-count accuracy (§10.3), and a Thai-glyph rendering spot check using the bundled font (§10.2).
- Browser Print must be verified to include the *complete* bulk-fetched result set, not merely whatever was scrolled/loaded on the on-screen paginated view, per §6.1's design intent.
- A visual-parity review (not a byte-comparison) between the Browser Print view and the backend-rendered PDF, per §8's accepted-duplication trade-off.

---

## 16. Acceptance Criteria

Restated verbatim from the authoritative source (`docs/audits/04-consolidated-implementation-plan.md`, PR18 entry): **"All three report families can be exported and printed without changing transaction or lifecycle business rules."** Every architectural choice in this document is made specifically to keep that true — export/print consume, never recompute, the already-authoritative report data (§4, §5, §6).

---

## 17. Suggested Implementation Slices

Following this repository's established lettered/numbered-slice precedent (Roadmap PR7/PR8/PR9/PR14/PR15/PR16/PR17), suggested for a future Repository-Owner-approved implementation sequence — **none of these are started by this design PR**:

- **PR18A (this PR):** Design only — this document.
- **PR18B — Excel export.** Bulk-fetch query support (§6.1), the three `.../export?format=xlsx` endpoints, `openpyxl` formatting (§9), row-cap rejection, formula-injection defense. Lowest-risk slice — no new dependency, no new frontend surface.
- **PR18C — Browser Print.** Frontend print view + `@media print` CSS (§10), bundled Thai webfont (§10.2), Report Render Context assembly reused from PR18B's bulk-fetch plumbing.
- **PR18D — PDF export.** New backend PDF-rendering dependency (§8), Jinja2 template reusing PR18C's layout knowledge, `.../export?format=pdf`, page-numbering via CSS Paged Media (§10.3).
- **Deferred governance-sync PR** (per this repository's own established convention, `docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md` §17/§22): recording Roadmap PR18 complete and advancing the Roadmap's next planned item, opened only once all approved PR18 slices have merged — not opened by this design PR.

---

## 18. Documentation

This design intentionally touches no runtime file. In addition to this document, `docs/TECH_DEBT.md` gains one new register entry (TD-007) formally logging the pre-existing legacy-export formula-injection gap this design's own investigation surfaced from PR16's design doc (§2) — a documentation-only addition, not a fix, consistent with this repository's Technical Debt Register purpose ("Single home for evidenced deferred defects").

---

## 19. Final Validation

- [x] No backend runtime file changed.
- [x] No frontend runtime file changed.
- [x] No Alembic migration added.
- [x] No API contract changed (only new, additive routes are *designed*, none implemented).
- [x] `ReportTransactionOut`/`EquipmentOut`/`Page[T]` reused unchanged (§7) — no redesign of Roadmap PR16/PR17.
- [x] `VIEW_AND_REPORT_ROLES` reused unchanged (§11) — no new permission introduced.
- [x] Legacy `GET /reports/export` endpoint left untouched and unextended (§2, §14) — its pre-existing formula-injection gap is logged (`docs/TECH_DEBT.md` TD-007), not fixed, and not conflated with this design's new endpoints.
- [x] Physical verification, analytics/BI, MEMS, Recall Monitor, and offline mode confirmed out of scope (§13).

---

## 20. Deliverables

- Report Render Context concept (§7) and Report Export Spec concept (§12) — internal, non-API structures — as the seam future report modules and future output formats extend against without redesign.
- Recommended API shape: three new `.../export` endpoints (§6), reusing existing filters/roles.
- Recommended PDF strategy: backend HTML→PDF rendering, WeasyPrint-class library (§8).
- Recommended Excel strategy: `openpyxl` (already installed), with hospital-appropriate formatting and formula-injection defense (§9).
- Recommended Browser Print design: landscape A4, bundled Thai webfont, `position: fixed` header/footer, honestly-scoped page-numbering (§10).
- One flagged, non-blocking confirmation point for the Repository Owner regarding the legacy export endpoint's disposition (§14).
- Suggested implementation slice sequence (§17) for a future Repository-Owner-approved PR18B onward.

---

*This document is a design proposal only. No code, configuration, dependency addition, or documentation file other than this one and the `docs/TECH_DEBT.md` entry it introduces (§18) was changed to produce it.*
