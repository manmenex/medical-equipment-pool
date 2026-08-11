# Change History

**Purpose:** Record important conceptual (mental-model) changes, distinct from per-PR decisions
**Authority:** Historical navigation. Each entry cites the decision that made it authoritative — see `docs/DECISION_LOG.md` for the full rationale behind each change.
**Update trigger:** A concept this project uses is added, retired, or redefined
**Maintainer:** Documentation/Governance Engineer

This file tracks *what changed in the shared mental model* over time, one line of context per concept. For the PR-by-PR rationale behind each change, see `docs/DECISION_LOG.md` (from Roadmap PR5 onward) and `docs/PROJECT_MEMORY.md` (Roadmap PR1 through Governance Pack v1.0).

## Roadmap PR19B merged: Exception Record closed; Roadmap PR19 fully complete (GitHub PR #80)

Roadmap PR19B (Legacy Import Frontend Skeleton) merged after three
independent-review rounds on GitHub PR #80: reconciliation head
`71dc97df583f60c3e9f8bccbbcb2e72b0b7307d5` (REQUEST CHANGES, findings
PR80-H1 — mock fixtures violated backend invariants — and PR80-H2 —
failed/cancelled result presentation could falsely appear successful); fix
head `6139bd4abd44c0a4ac07bf6ac63bf1b897dad653` (REQUEST CHANGES, remaining
finding PR80-H1R — a structural `validation_failed` fixture carried a
persisted finding despite TX1 rollback semantics); final reviewed head
`5edf1bfd8de7013eb74f300193456c9e5c0f0332` (**APPROVE**, CI green 6/6).
The real squash-merge SHA, `04f5bf5c76b51744981d1cc8072c074e604224e9`, is
distinct from that final reviewed feature-branch head, per this
repository's standard squash-merge SHA-retrieval practice — the reviewed
head is never treated as the merged baseline. `04f5bf5c...` is now the
current authoritative base-branch tip, superseding `7f13a1e...` for
current-state purposes. PR19B's frontend types/mock fixtures were
reconciled against PR19A's merged public contracts (nullable
`imported_rows`, the `failure_reason` field); its terminal-outcome
presentation (`LegacyImportResultSummary`) now renders truthfully per
status instead of a single hardcoded success card. PR19B remains a
frontend-only workflow-review skeleton — no real file upload, workbook
parsing, validation/dry-run/import execution, or production legacy
dataset adapter exists; concrete Equipment Master/Receive History/Issue
History import remains future Roadmap PR20/PR21 scope, not implemented by
this merge. **Both PR19A and PR19B are now merged; Roadmap PR19 (Legacy
Import Foundation, backend + frontend skeleton) as a whole is now fully
complete**, and the Exception Record governing the PR19A/PR19B split
(`docs/DECISION_LOG.md`, "Roadmap PR19 approved split") is **CLOSED** —
all seven required closure steps are satisfied. This supersedes the
"Roadmap PR19 split into PR19A (backend) and PR19B (frontend skeleton)"
entry below insofar as it described PR19B as unimplemented; that entry's
description of the original split decision remains accurate historical
record. GitHub PR #81 remains closed without merge, superseded by
PR19A1/PR19A2/PR19A3 — unaffected by this entry. A separate,
still-unresolved question of relative sequencing between PR19B and PR20
was left TBD pending an Owner Decision while PR19B was provisional
(`docs/ROADMAP_STATUS.md`); PR20 has only ever depended on PR19A, not
PR19B (`docs/audits/04-consolidated-implementation-plan.md`), so this
merge does not change PR20's readiness, and this entry does not resolve
that sequencing question or start PR20. See `docs/DECISION_LOG.md`
("Roadmap PR19B merged: Exception Record closed; Roadmap PR19 fully
complete") for the full review-round and closure-evidence record.

## Roadmap PR19A complete: PR19A1 + PR19A2 + PR19A3 merged (GitHub PR #84, #85, #86)

All three of Roadmap PR19A's design-decomposed implementation slices (design
§25) have merged, each after its own exact-head Codex review and required CI:
PR19A1 — schema, session/source lifecycle, CAS-guarded state transitions — as
GitHub PR #84, squash SHA `7d58986095c4df6a425dc9cfd8298851eee86c17`; PR19A2 —
validation foundation, including the lease/heartbeat/fencing/recovery
mechanism later shared by PR19A3 — as GitHub PR #85, squash SHA
`7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`; PR19A3 — enforced PostgreSQL
read-only dry-run, CAS single-winner execution, idempotency, retention
enforcement, and migration of PR19A2's validation phase onto the shared
lease/fencing primitives without semantic drift — as GitHub PR #86, squash SHA
`7f13a1e85e9b6a4828170c4b12bc2be27b15de39`. `7f13a1e...` is the current
authoritative base-branch tip. **Roadmap PR19A (Legacy Import Foundation,
backend) is now fully complete.** No concrete legacy dataset import
(Equipment Master, Receive History, Issue History) is implemented by PR19A;
that remains future Roadmap PR20/PR21 scope. This supersedes the "PR19A1
implementation started" entry below, which describes an intermediate,
now-historical state. See `docs/DECISION_LOG.md` ("Roadmap PR19A complete:
PR19A1 + PR19A2 + PR19A3 merged") for the full slice-by-slice technical
record, including each slice's review chronology.

## PR19A1 implementation started (Draft PR #84)

Roadmap PR19A1 (schema, session/source lifecycle, CAS-guarded state
transitions — the first of PR19A's design-decomposed implementation
slices, design §25) is in progress on Draft PR #84
(`feature/pr19a1-legacy-import-schema`), based on PR #83's squash SHA
`38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`. Open, not yet merged or
complete. PR19A2 and PR19A3 have not started. This does not change
`docs/DECISION_LOG.md`'s Exception Record: PR19A's design merging (not
PR19A1 starting) is what ended PR19B's provisional-development
authorization; the Exception Record itself remains open regardless of
PR19A1's progress, pending PR19B's own reconciliation and verification.

## PR19A architecture design approved (GitHub PR #83)

Roadmap PR19A's architecture design (`docs/design/
PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`) merged as GitHub PR #83, squash SHA
`38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`, branched directly from
`729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` in genuine parallel with PR19B
(Draft PR #80) and the PR19-split governance PR — none of the three waited
for either of the others to merge, confirming in practice that
"independent-scope" never required a shared implementation baseline. The
design defines PR19A's authoritative API/session/document-model contract
and decomposes PR19A's own implementation into slices PR19A1/PR19A2/PR19A3
(design §25) — see the entry above for PR19A1's subsequent progress. This does **not** by itself
complete or close PR19B's Exception Record: per `docs/DECISION_LOG.md`,
PR19A's design merging ends the "develop provisionally, no contract yet"
authorization for new PR19B work, but the Exception Record itself remains
open until PR19B is rebased/reconciled against this contract, required
contract/integration tests pass, exact-head re-review is complete, and
Repository Owner acceptance is recorded — none of which had happened as of
this entry.

## Roadmap PR19 split into PR19A (backend) and PR19B (frontend skeleton)

Roadmap PR19 ("Legacy Import Foundation") was previously one unsplit Roadmap
item, with no PR19A/PR19B naming anywhere in governance material. The
Repository Owner explicitly approved splitting it into two independent-scope
implementation slices: **PR19A**, the backend import framework itself, and
**PR19B**, a frontend-only, mock-data UI prototype of the future import
workflow for early hospital-user workflow review, ahead of PR19A's real
contract. "Independent-scope" (parallel) describes dependency independence
only — neither slice is stacked on, or blocked by, the other's unmerged
branch — it does not mean the two slices share one implementation baseline
commit: PR19B branched from `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52`
(GitHub PR #79). This split is an explicit exception to this repository's
usual pattern of splitting a Roadmap item into lettered slices only after
an architecture-approved design document — at the time of this decision, no
PR19 design document existed yet (see the entry below recording that PR19A's
design has since merged). PR19B's import-category labels (Equipment Master / Receive
History / Issue History) are preview labels pulled forward from PR20/PR21
scope for review purposes only, not an implemented capability or an approval
of PR20/PR21's own design. Neither PR19A nor PR19B is implemented by this
change; PR19B's own implementation is tracked on Draft PR #80. See
`docs/DECISION_LOG.md` ("Roadmap PR19 approved split: PR19A (backend) /
PR19B (frontend skeleton)") for the full Exception Record.

## Printing and Export complete; Roadmap PR18 closed (Roadmap PR18E / PR18F)

Roadmap PR18E added the backend Excel `.xlsx` adapter (`report_xlsx_service`,
`GET /reports/{report_id}/xlsx`) for Receive Report, Issue Report, and
Equipment Verify Checklist, over the same PR18B `ExportDocument` foundation
Browser Print and PDF already use — `openpyxl` was reused with no new
dependency (it already parsed `.xlsx` imports and drove the legacy exporter).
Codex review required two fixes before merge: every worksheet string write —
report rows and the metadata/applied-filter block alike — now passes through
one centralized helper (`_write_cell`) that applies the Excel
formula-injection guard unconditionally, closing a gap where administrator-
editable display names (generated-by, resolved ward/category/operator filter
values) could reach the workbook unsanitized; and Excel generation gained the
same bounded-admission-control shape already established for PDF
(`build_workbook_bounded`: a concurrency semaphore, one total timeout
covering queue wait and active generation, renderer-lifetime concurrency
accounting), with lighter constants than PDF's own given `openpyxl`'s smaller
resource footprint at the approved row bound. Merged as GitHub PR #78, squash
SHA `5d8cf7d8f378f6231d43e330310f664f6c19560f`.

With PR18B (shared export foundation), PR18C (Browser Print), PR18D (backend
PDF export), and PR18E (Excel `.xlsx` export) all merged, **one shared,
output-neutral export model now drives all three output adapters** for every
PR17 report family — no adapter duplicates report/query logic or
reconstructs eligibility, ordering, or filter rules. Every bulk export is
bounded (the shared `MAX_EXPORT_ROWS = 5000` synchronous limit, rejecting
outright rather than truncating silently); PDF and Excel each additionally
enforce explicit concurrency/admission control with a total timeout that
covers queue wait. Field- and operator-information boundaries established by
PR17 (e.g. `item_no` excluded from the Equipment Verify Checklist) carry
through unchanged to every output format. All three formats use the same
interim neutral branding fallback approved in the PR18A design (no hospital
name, no department name, no logo) — **Owner Decision #2 (branding
configuration ownership) remains unresolved**; no deployment/environment- or
Administrator-managed branding configuration exists anywhere in the
repository.

**Roadmap PR18 (Printing and Export) is now fully complete.** This is
recorded by Roadmap PR18F, a documentation-only governance synchronization
(branch `docs/pr18f-governance-sync`, baseline
`5d8cf7d8f378f6231d43e330310f664f6c19560f`) that changes no runtime behavior.
See `docs/DECISION_LOG.md` ("Roadmap PR18E — Excel `.xlsx` Export" and
"Roadmap PR18 — Printing and Export Complete") for the full review
chronology and final governance record, and `docs/ROADMAP.md`/
`docs/ROADMAP_STATUS.md` for the updated baseline. The next planned item is
Roadmap PR19 (Legacy Import Foundation); no PR19 implementation has started.

## Reporting and legacy-migration sequence aligned

The Roadmap now distinguishes actual transaction timestamp, `business_date`,
and `shift` in one reporting model; schedules Receive, Issue, and Equipment
Verify Checklist reports plus PDF/Excel/hard-copy output as PR16–PR18; and
places Equipment Master plus AppSheet Receive/Issue history migration,
validation, reconciliation, and cutover readiness in PR19–PR23 before PR24
Go-live. Equipment Verify Checklist history is outside the Version 1 migration.
PR20 is limited to Equipment Master fields, QR linkage, equipment duplicates,
and equipment-record validation. Transaction-derived BME names, Ward values,
transaction duplicates, and source references belong to PR21; cross-import
validation and reconciliation belong to PR22.
See `docs/ROADMAP.md` and `docs/DECISION_LOG.md`.

## Printing/export architecture approved (Roadmap PR18A)

Roadmap PR18A merged the architecture design for browser print, backend PDF
export, and Excel `.xlsx` export for the three PR17 reports. The approved
direction keeps PR17 report semantics as the backend source of truth and adds
an output layer around them: a shared backend dataset/document-model slice
first, then browser print, PDF, Excel, and a final governance sync. The design
does **not** implement any PR18 runtime behavior yet and leaves three Owner
Decisions open before dependent implementation can merge: export extent,
branding configuration ownership, and maximum synchronous output size.
Merged as GitHub PR #71, squash SHA `6ba2c666a11043d03669abdb65f966061dd02cfa`.
See `docs/design/PR18_PRINTING_EXPORT_PLAN.md` and `docs/DECISION_LOG.md`
("Roadmap PR18A printing/export architecture design").

## Shared export foundation implemented (Roadmap PR18B)

Roadmap PR18B added one output-neutral export foundation for all three PR17
report families. Stable report identities, export metadata, deterministic
typed columns and rows, and centrally enforced `ExportDocument` schema
invariants now feed Receive, Issue, and Equipment Verify Checklist builders.
Those builders reuse the existing PR17 query/eligibility/filter/ordering
semantics rather than creating a second reporting engine. The internal
`GET /reports/{report_id}/print-data` endpoint returns the complete matching
dataset within the approved bound and records human-readable applied-filter
metadata. Report-specific filter applicability is enforced, and operator-name
resolution stays inside the same transaction-referenced historical-operator
boundary as `/report-options/operators`. Browser Print, PDF, and Excel remain
separate future adapters. Merged as GitHub PR #73, squash SHA
`c72929ba4649fd75d1f81e4630b4e4feb3d136be`. See `docs/DECISION_LOG.md`
("Roadmap PR18B — Backend Export Foundation").

## Browser Print implemented (Roadmap PR18C)

Roadmap PR18C added a dedicated Thai-first Browser Print adapter for Receive
Report, Issue Report, and Equipment Verify Checklist. The frontend consumes
PR18B's bounded `print-data` representation of `ExportDocument` and renders
the backend-provided report content, filters, columns, ordering, metadata, and
information boundaries without reconstructing report rules. Print requests
remove `cursor` and `limit` so pagination never constrains the retained
document while preserving the other declared filters for backend validation.
Required Noto Sans Thai weights are loaded and validated independently, and
font readiness fails closed when a weight or the Font Loading API is
unavailable; completed readiness is accepted only for the current document
identity. PDF and Excel remain separate future adapters. Merged as GitHub PR
#75, squash SHA `e919a2af8cc7ca11ab72bee274cb70e76c27ce8a`. See
`docs/DECISION_LOG.md` ("Roadmap PR18C — Browser Print").

## Cleaning status removed

A cleaning status/workflow was proposed early (a two-step "Return Received" / "Cleaning Confirmed" process, `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §6.1) and explicitly superseded before implementation: the hospital confirmed receipt is one atomic usable/defective operation, and the system never tracks cleaning. See `docs/ARCHITECTURE_DECISIONS.md` ("No cleaning workflow").

## ME Code retired

An earlier placeholder identifier, "ME Code," was used for every user-facing equipment-identification role (manual search, QR lookup, general reference) without distinguishing them. `knowledge/adr/ADR-002-identifier-model.md` retired it and replaced it with four distinct identifiers, each with one role. Any document still saying "ME Code" is out of date.

## BCM adopted

BCM Code was confirmed as the primary operator-facing identifier and the only identifier accepted by manual search, replacing the "ME Code" placeholder's search role. Implemented in Roadmap PR5 (GitHub PR #14). See `knowledge/adr/ADR-002-identifier-model.md`, `ADR-003-bcm-manual-search.md`.

## Item No visibility reduced

Item No (the hospital QR-label identifier) was confirmed as QR-lookup-only and explicitly excluded from normal operator-facing API responses — it may appear only in explicitly restricted administrative/import contexts. Implemented in Roadmap PR5; the API information-boundary rule is in `knowledge/architecture/api-information-boundaries.md`.

## Four-state model introduced

The equipment status model was collapsed to exactly four states (`AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`), retiring an earlier, wider set of statuses (preserved for history in a `legacy_status` column). Implemented in Roadmap PR6 (GitHub PR #16), migration `0006_equipment_state_model.py`.

## Dispatch/receipt and manual maintenance transitions separated

Roadmap PR6's review found that the equipment-status transition table did not distinguish dispatch/receipt-driven transitions from administrative/manual status maintenance, creating a path where manual maintenance could simulate a dispatch or receipt without going through the actual transaction lifecycle. Split into two transition tables; manual maintenance can never open or close a transaction. See `docs/BUSINESS_RULES.md` ("Dispatch/Return owns transaction lifecycle").

## Decommission path closed

Roadmap PR6's review also found `AVAILABLE_AT_POOL` could skip directly to `DECOMMISSIONED`. Closed: decommissioning must now pass through `UNAVAILABLE_DEFECTIVE`. See `docs/BUSINESS_RULES.md`.

## Process-required CI introduced

Through Roadmap PR3/PR4/PR5/PR6, PostgreSQL-backed integration tests existed but no GitHub Actions workflow ran them on a PR at all (`docs/TECH_DEBT.md` TD-003). The CI/AI-review-workflow infrastructure PR (GitHub PR #17) added a workflow required by the documented project process (`docs/PROJECT_WORKFLOW.md`), later hardened to fail closed rather than silently pass via skipped tests when PostgreSQL infrastructure is unusable. GitHub branch protection does not yet enforce this workflow as a required status check (`docs/KNOWN_LIMITATIONS.md`).

## Governance layer consolidated

The Knowledge & Governance Foundation PR (GitHub PR #18) is itself a conceptual change: it introduces a compact, cross-referenced quick-reference layer (`docs/PROJECT_WORKFLOW.md` and friends, `knowledge/PROJECT_MEMORY.md` and friends) alongside the existing detailed Governance Pack v1.0 (`docs/PROJECT_PLAYBOOK.md`'s Level 1-7 hierarchy), rather than replacing it.

## OPEN/CLOSED transaction lifecycle introduced

`BorrowTransaction.status` was collapsed from a three-value `borrowed`/`returned`/`overdue` field to an exactly-two-value `TransactionStatus` (`OPEN`/`CLOSED`), retiring "overdue" entirely — not just as a status value, but as a workflow: the `due_at`-driven hourly notification job (`app.worker.scheduler.check_overdue_returns`) was removed after Codex's PR7a review found it re-notified on every OPEN, overdue transaction on every hourly tick with no de-duplication (a BLOCKER). The approved MVP business model has no due-date/overdue workflow at all. The prior status is preserved for history in a `legacy_status` column, mirroring the four-state equipment model's pattern — with one refinement a second review round required: a row that genuinely had a pre-PR7 value (`borrowed`/`returned`/`overdue`) keeps that exact value, while a row already `open`/`closed` before the migration ran (no real legacy value exists for it) gets a canonical compatibility marker equal to its own status, never a fabricated legacy value — so downgrade remains possible for every database regardless of which population its rows started in. Implemented as Roadmap PR7's lifecycle slice ("7a"), migration `0007_transaction_lifecycle.py`, merged as GitHub PR #19. See `knowledge/adr/ADR-005-transaction-model.md`, `docs/DOMAIN_MODEL.md`, `docs/DECISION_LOG.md`.

## Dispatch type and routine round introduced; borrower_name/due_at/quantity retired from the write path

Roadmap PR7's remaining scope ("7b") added a `dispatch_type` domain (`routine_round`/`on_demand`) and a `routine_round` domain (the four confirmed fixed times `06:00`/`11:00`/`15:00`/`21:00`, an explicit MVP simplification pending a future, not-yet-scheduled Shift Sessions redesign) to `BorrowTransaction`, and made `ward_id` required for every new dispatch at the application layer. `borrower_name`, `due_at`, and `quantity` were retired as active write-path fields — no longer accepted by `BorrowRequest`, and `due_at` also dropped from `TransactionOut` — while every existing historical value for all three is preserved unmodified and remains readable (`borrower_name` still visible in `TransactionOut`; `due_at`/`quantity` still exportable via `app.services.report_service`). Both new columns and the relaxed `borrower_name` `NOT NULL` constraint are additive, non-destructive changes at the database level (migration `0008_dispatch_fields.py`); no existing row's `ward_id`, `dispatch_type`, or `routine_round` was fabricated or auto-assigned. Implemented as Roadmap PR7's remaining slice ("7b"), merged as GitHub PR #20. Codex's review of that PR made two further contract refinements before merge: `BorrowRequest` now rejects any unrecognized request field outright (`extra="forbid"`) instead of relying on Pydantic's default silent-ignore behavior, so a caller still sending `borrower_name`/`due_at`/`quantity` gets a hard 422, not a silently-accepted-and-discarded field; and an invalid `ward_id` reference is now a distinct 400 `INVALID_INPUT` (validated proactively, the same pattern already used for other foreign-key fields), separated from the pre-existing 409 "equipment just borrowed by someone else" concurrency response it was previously misclassified as. Roadmap PR7 (both slices) is now fully merged. See `knowledge/adr/ADR-005-transaction-model.md`, `docs/DOMAIN_MODEL.md`, `docs/DECISION_LOG.md`.

## Receipt concurrency guard introduced

Concurrent-receipt protection (two simultaneous receipts racing on the same OPEN transaction), left as Roadmap PR7's explicit remaining gap and Roadmap PR8's stated responsibility, was closed at the database level: `app.crud.transaction.close()` changed from an unconditional `UPDATE` guarded only by a prior Python `status` read, to a single conditional `UPDATE ... WHERE id = :id AND status = 'open'` whose affected rowcount is the sole winner guard — exactly one concurrent request wins, and every loser rolls back before any business side effect (no equipment-status change, no status-history row, no audit row), reusing the existing `TRANSACTION_ALREADY_RETURNED` response with no new error code. Proven with deterministic PostgreSQL tests across a matrix of 1, 2, 5, 10, and 50 requests: the 1-request case verifies normal receipt behavior with no concurrency, the 2/5/10 cases synchronize the complete burst to force genuine contention, and the 50-request case synchronizes a bounded subset to prove conditional-`UPDATE` contention without exhausting the connection pool. Implemented as Roadmap PR8, split into "8A"/"8B"/"8C" slices following the same precedent `docs/audits/04-consolidated-implementation-plan.md` Part D already used for PR7 ("if the reviewing team prefers smaller units"): PR8A (this change) merged as GitHub PR #26, squash SHA `4820dbaa683f4cb80732406892b7708d2e242d85`, after CI and Codex review approval. PR8B — narrowing the `condition` field to a binary usable/defective outcome — has since merged in two coordinated parts, backend (GitHub PR #28, squash SHA `da4d76a640548e5a1d38ff3d7690695f950c85fe`) and frontend (GitHub PR #29, squash SHA `d3e027b5a4ee7d99b38dfd0d263dc460c74eb5c5`), deployed together. See `docs/DECISION_LOG.md` ("Roadmap PR8 (PR8A slice)", "Roadmap PR8 (PR8B slice)").

## Race-vs-repeat receipt rejection distinguished (Roadmap PR8C)

Roadmap PR8's remaining slice: a losing receipt request (Roadmap PR8A's conditional-close guard) now surfaces one of two distinguishable, stable, machine-readable `code`s instead of always reusing `TRANSACTION_ALREADY_RETURNED` — `TRANSACTION_ALREADY_RETURNED` for a genuine sequential repeat (the transaction was already closed *before* this request read it), and a new `RECEIPT_RACE_LOST` for a request whose own read observed the transaction as OPEN but which then lost the conditional-close race to a concurrent request. Both share the same `409` HTTP status (both are conflicts with current state) — only the `code` (and `detail`) differ, so a caller can distinguish the two without parsing free-text. No lifecycle state, schema, migration, or request contract changed: `app.services.borrow_service.return_equipment()`'s existing Case A/Case B branches (already split by PR8A) now each raise a distinct `DomainError` subclass (`app.core.exceptions.TransactionAlreadyReturnedError` / `ReceiptRaceLostError`) instead of sharing one. The frontend (`ReturnPage.tsx`) reads the response's `code` field explicitly (never inferring behavior from the `detail` text) to show a duplicate-receipt message or a distinct "another receipt request completed first" message — deliberately neutral wording, since `RECEIPT_RACE_LOST` only proves a concurrent request committed first, not that it came from a different person (it could be the same user double-clicking, or a browser/network retry); `received_by_user_id` is never compared between the two requests. See `docs/api/receipt.md`, `docs/api/ERROR_CODES.md`, `knowledge/adr/ADR-006-receipt-outcome-contract.md` ("Not decided here").

## Audited ward correction introduced (Roadmap PR9A)

A transaction's recorded destination ward, previously immutable after dispatch, can now be corrected through one narrow, audited action: `POST /api/v1/transactions/{transaction_id}/correct-ward` (`app.services.borrow_service.correct_ward`). This is a data-correction action, not ward-transfer tracking — no ward-to-ward transfer concept was introduced anywhere in the system, and this closes the gap `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §7 ("Ward Recording Rules") identified as unimplemented. Only `ward_id` changes: no lifecycle state (equipment or transaction), `dispatch_type`/`routine_round`, or business-event timestamp is touched, and the action works identically on an OPEN or CLOSED transaction. A same-ward submission is rejected as a no-op (`409 WARD_CORRECTION_NOOP`, no audit entry). Concurrency uses the same conditional-`UPDATE`-decided-by-affected-rowcount shape Roadmap PR8A established for the receipt-close guard, applied to `ward_id` (`app.crud.transaction.correct_ward`) — a request whose read is no longer current loses with `409 WARD_CORRECTION_CONFLICT`, a distinct code from Roadmap PR8C's receipt-flow codes, never a silently-applied lost update. Every successful correction writes exactly one audit entry via the canonical PR3 writer (`app.core.audit.record_audit_event`), committed atomically with the ward change. Authorization was temporarily restricted to `admin` only (`app.api.v1.deps.WARD_CORRECTION_ROLES`) at the time this slice merged — an intentionally conservative rule, not the confirmed final matrix. The confirmed 3-role matrix (`docs/audits/03-hospital-equipment-pool-workflow-audit.md` §10) grants this capability to Administrator and Equipment Pool Staff, but the then-current 5-role model had no confirmed, evidence-backed equivalent of Equipment Pool Staff, and ward correction modifies historical operational data, so an inferred mapping was rejected. `biomedical_engineer`, `ward_nurse`, `transport_staff`, and `viewer` were all denied with `403` until Roadmap PR10's Role Model Consolidation landed the confirmed 3-role model and replaced this one constant (now merged — see the PR10 entry below). This is the backend slice only (Roadmap PR9A) — see the following entry for the merged frontend slice (PR9B). See `docs/api/transactions.md`, `docs/api/ERROR_CODES.md`.

## Ward correction reachable from the frontend; Roadmap PR9 complete (Roadmap PR9B)

Roadmap PR9A's backend action is now reachable through two frontend entry points, since the endpoint has no lifecycle-status precondition and a mis-recorded ward may only be discovered after receipt: `frontend/src/pages/ReturnPage.tsx` (an OPEN transaction) and `frontend/src/pages/EquipmentDetailPage.tsx`'s cursor-paginated transaction history (OPEN or CLOSED, sourced from the pre-existing `GET /transactions?equipment_id=` endpoint, never inferred from the equipment ID or from equipment status-history rows). Both entry points share one component pair, `WardCorrectionAction.tsx`/`WardCorrectionDialog.tsx`, so the mutation, validation, and error-mapping logic exist exactly once. Visibility mirrors PR9A's temporary `admin`-only authorization as a usability-only gate; the backend remains authoritative. Merged as GitHub PR #34, squash SHA `bfe8a42a55d738d3e591ce27145c7918186643ac`, after three review rounds addressing ward-list load/error/retry state, full keyboard focus containment and restoration (including a pending-submission edge case), and CLOSED-transaction reachability with pagination. No backend, schema, migration, or lifecycle change. **With both slices merged, Roadmap PR9 is fully complete.** The next planned item was Roadmap PR10 (Role Model Consolidation), which updated both `WARD_CORRECTION_ROLES` (backend) and `canCorrectTransactionWard` (frontend) together — see the entry below. See `docs/DECISION_LOG.md` ("Roadmap PR9 — Audited ward correction (PR9A/PR9B slices)").

## Role Model Consolidation complete (Roadmap PR10)

The legacy 5-role model (`admin`, `biomedical_engineer`, `ward_nurse`, `transport_staff`, `viewer`) was replaced everywhere a role is persisted or checked by the confirmed 3-role model — `administrator`, `equipment_pool_staff`, `read_only` — per `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §10. `backend/app/api/v1/deps.py` now centralizes four named capability groups (`EQUIPMENT_POOL_OPERATION_ROLES`, `ADMINISTRATOR_ONLY_ROLES`, `VIEW_AND_REPORT_ROLES`, `WARD_CORRECTION_ROLES`) that every endpoint's role gate references, replacing scattered inline role tuples; `frontend/src/hooks/useAuth.ts` mirrors the same matrix as a centralized, usability-only capability layer. Ward correction's temporary Administrator-only rule (Roadmap PR9A) is now superseded by the confirmed matrix (Administrator + Equipment Pool Staff).

A new migration, `backend/alembic/versions/0009_role_consolidation.py`, is not mechanical: `admin`→`administrator` and `viewer`→`read_only` are safe, automatic remaps, but `biomedical_engineer`/`ward_nurse`/`transport_staff` have no confirmed equivalent and are never auto-mapped — the migration requires an explicit `MEP_PR10_ROLE_MAPPING` manifest (a JSON array of `{employee_code, target_role}` objects) for any user holding one of those three roles, and aborts with a `RuntimeError` naming the unresolved accounts otherwise. Every user's pre-migration role name is preserved in a new `users.legacy_role_name` column (mirroring `BorrowTransaction.legacy_status`'s Roadmap PR7 pattern) as human-readable provenance only — it is not the downgrade's source of truth. Losslessness comes from three durable migration tables instead: `user_role_migrations` (each user's exact legacy and migrated role ids), `role_migration_snapshots` (every touched legacy role's exact pre-upgrade `id`/`name`/`permissions`), and `confirmed_role_ownership` (whether each confirmed role already existed before upgrade or was created by it). `downgrade()` restores every legacy role to its exact original primary key and permissions, restores every user to their exact original role id, writes downgrade audit provenance, deletes a confirmed-role row only when ownership provenance proves this migration created it, and preflights for post-upgrade divergence and missing/inconsistent provenance before writing anything — see the review rounds below for how this reached its final shape. A `ck_roles_name_confirmed` CHECK constraint then restricts `roles.name` to exactly the 3 confirmed values.

Three iterative Codex review rounds, completed before PR #36 was squash merged, hardened the migration, all against `0009_role_consolidation.py` only: **round 1** added per-user audit provenance for migration-driven role changes and restricted the ambiguous-role manifest to genuinely ambiguous accounts (never able to override an already-safe or already-confirmed role); **round 2** added downgrade-side audit provenance and a `role_migration_snapshots` table so downgrade recreates each legacy role's exact original `(id, name, permissions)` row rather than a same-named row with a freshly generated id; **round 3** added a `confirmed_role_ownership` table so downgrade can prove, per confirmed role, whether it created that row or reused a pre-existing one — a confirmed-role row downgrade did not create is never deleted, regardless of its name. Each round's fixes were pushed to new exact heads on the same Draft PR and re-reviewed before the next round began. All three rounds are backed by dedicated PostgreSQL-backed migration tests (53 total, `test_migration_0009_*` in `test_postgres_integration.py`) run via the real `alembic` CLI against a scratch database.

Merged as GitHub PR #36, squash SHA `53340f6d7d5c8cda685235411b60a57d2d033a7e`. See `docs/DECISION_LOG.md` ("Roadmap PR10") and `docs/BUSINESS_RULES.md` ("Roles and the confirmed 3-role permission matrix") for full detail. **Roadmap PR10 is now fully complete.** The next planned item is Roadmap PR11 (Frontend Terminology and Workflow UI Pass).

## Frontend terminology and workflow UI pass complete (Roadmap PR11)

"ยืม"/"คืน" (borrow/return) — the terminology the confirmed workflow retires everywhere in the UI per `docs/audits/04-consolidated-implementation-plan.md` Part D's PR11 entry — is replaced consistently by "เบิก"/"รับคืน" (issue/receive back) across every screen it appeared: navigation (`AppShell.tsx`), the dispatch form (`BorrowPage.tsx`: heading, success view, confirm button, error messages), the receipt form (`ReturnPage.tsx`: heading, success view, confirm button, error messages, the transaction-info block), `EquipmentDetailPage.tsx`'s CTA buttons and transaction-history heading/loading/error/empty states and per-transaction status/timestamp labels, and the dashboard/reports chart labels. The same action always uses the same wording — no duplicate or ambiguous term was introduced for the same concept. The equipment noun stays "เครื่องมือ" throughout; "อุปกรณ์" is never used.

The ward field — on the dispatch form, receipt form, and equipment-detail transaction history — is relabeled "หอผู้ป่วยที่รับเครื่อง (บันทึก ณ วันที่เบิก)" ("Receiving ward (recorded at dispatch)") with an accompanying caption disclaiming real-time location tracking, translating `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §7.1's ("Recommended UI labeling") confirmed English copy into Thai. This satisfies PR11's explicit acceptance criterion in full: the ward field carries the confirmed caption, and it is never presented as a live location tracker.

Deliberately left unchanged: `WardCorrectionDialog.tsx`/`WardCorrectionAction.tsx` terminology (already aligned with the Workflow Audit's wording from the Roadmap PR9 review rounds), and internal route paths (`/borrow`, `/return`) and function/service/query-key names (`createBorrow`, `listActiveBorrows`, `fetchBorrowTrend`, etc.) — per the consolidated plan's own numbering-note precedent (item 8) recommending these stay unchanged for MVP to reduce blast radius. No backend, API, database, migration, RBAC, or business-rule change — this PR is frontend-only.

Two iterative Codex review rounds, both completed on a new exact head before PR #38 was squash merged, closed a test-coverage gap against PR11's own explicit requirement ("component tests for the new dispatch/receipt forms; an end-to-end workflow test (dispatch → receipt) using only the new terminology and fields"): **round 1** found no `BorrowPage` component tests existed at all and no test exercised the dispatch → receipt workflow, and was fixed by adding `frontend/src/pages/BorrowPage.test.tsx` and `frontend/src/pages/DispatchReceiptWorkflow.test.tsx`. **Round 2** found that first workflow test manually swapped the mocked equipment-status value between steps instead of deriving it from the dispatch/receipt actions themselves, so the test could pass even if those actions stopped working — fixed by rewriting the test around one shared, mutable mock store where `createBorrow` alone advances equipment to `issued_to_ward` and creates the transaction, and `createReturn` alone closes that exact transaction id and restores `available_at_pool`. Both rounds' fixes were pushed to new exact heads on the same Draft PR and re-reviewed before merge.

Merged as GitHub PR #38, squash SHA `7708190ebf08b7212b7a73ba831263b94434d1eb`, after a documentation-only governance sync (GitHub PR #37, squash SHA `66bdd547937b7741d53b16a98fe74280dee18273`) recorded Roadmap PR10's completion as this PR's baseline. See `docs/DECISION_LOG.md` ("Roadmap PR11") for full detail. **Roadmap PR11 is now fully complete.** The next planned item is Roadmap PR12 (Inventory Import).

## Inventory import complete, shipped update-only (Roadmap PR12)

The confirmed Administrator-only inventory import workflow — upload a spreadsheet, preview per-row validation results with zero database writes, then commit only valid rows in one transaction — is implemented: `POST /api/v1/import/preview` and `POST /api/v1/import/commit`, both re-parsing and re-validating the raw uploaded file from scratch (commit never trusts a client-supplied preview result). Rows are matched to existing equipment by canonical BCM Code. A new migration (`0010_inventory_import_columns.py`) adds `equipment.asset_id` (nullable, non-unique index — hospital-wide uniqueness unconfirmed) and `equipment.raw_source_status` (nullable, the exact source-cell text, verbatim). "Update mode" only ever touches the approved master-data field set (Asset ID, Manufacturer, Model, and Location/Receive Date/Register Date/Purchase Year provenance fields inside `equipment_metadata`) — it never writes `status`, `legacy_status`, `asset_number`, `item_no`, `serial_number`, or `equipment_name` on an existing record, so import can never become a backdoor around the dispatch/receipt/defective/decommission state-machine.

**The originally-planned create path never shipped.** Part D/F's design assumed a bulk-aware create-or-update path with an off-by-default update toggle. During independent review, the owner-approved policy for populating a new row's `asset_number` (deriving it from the row's own canonical BCM Code, since the import file has no Asset Number column) was found to violate `knowledge/adr/ADR-002-identifier-model.md` — Asset Number is "retained as inventory metadata only... not merged with, or inferred from, BCM Code or Item No." A replacement policy (a random placeholder token, distinct from BCM Code) was independently found to still be fabricated inventory metadata, not an ADR-002-approved absence or assigned value — `equipment.asset_number` is `NOT NULL`/`UNIQUE` real, hospital-assigned metadata used throughout the application (dashboards, reports, PM/Calibration notifications, API responses), and randomness doesn't change that a value was invented rather than assigned. Resolving this required a fresh Repository Owner architectural decision: **Roadmap PR12 ships update-only.** There is no create path at all; import never generates, derives, or synthesizes an Asset Number under any circumstance. A row whose BCM Code has no match in the database fails validation with a message directing the operator to create that equipment through the standard Equipment Master workflow first, then re-import to update it. `update_existing=false` — which, in the originally-planned create/update design, meant "skip an existing match instead of updating it" — no longer has a coherent meaning once there is no create path for it to select instead, so the backend rejects an explicit `false` immediately with a clear `400`, and the frontend removed the toggle entirely (the service always sends `true`). Create-from-import is deferred follow-up scope, not a permanent prohibition, pending a future ADR-governed design for real hospital Asset Number assignment (hospital-assigned values, a nullable-provisional-record model, or another authoritative approach).

Upload handling is bounded end to end: compressed size, row count, filename length/extension, and — since an `.xlsx` file is itself a ZIP container — the archive's central directory is inspected (entry count, per-entry and aggregate uncompressed size, compression ratio, permitted entry paths) before a single byte of member content is decompressed, closing the gap where a small, highly-compressible upload could otherwise expand past the compressed-size cap once `openpyxl` parsed it. The CPU-bound XLSX parse itself runs via `asyncio.to_thread`, off the event loop. Database duplicate lookups (BCM Code, Item No, Asset ID, Serial Number) are bulk `IN(...)` queries — a fixed handful per batch, never one query per row. Every bounded/persisted field (Asset ID, Serial Number, Equipment Name, Manufacturer, Model, Asset Status) is length-validated during preview, using the same code path commit uses, so a row can never preview as "success" and then crash commit with a database `DataError`. Update mode validates Item No and Serial Number against *other* equipment records the same way Asset ID always was, so a source row whose identifiers point at a different physical device is never reported as a clean update. `raw_source_status` preserves the exact Asset Status source-cell text — leading/trailing/internal whitespace, casing — via a dedicated verbatim-only text conversion used only for that column; a separately normalized copy (trimmed, lowercased) drives the status-mapping lookup without ever mutating the persisted value.

Four independent Codex reviews on Draft PR #43, each on a new exact head before the next began: **round 1** (`4781906397`) found the ADR-002 violation above plus unbounded/synchronous upload parsing, incomplete update-mode identity validation, missing preview-length validation, and no real PostgreSQL migration evidence. **Round 2** (`4781971425`) found the replacement placeholder policy still fabricated metadata, the round-1 migration tests failed on exact-head PostgreSQL CI because migration `0001_initial.py` builds its schema from the current ORM model rather than genuine history, and compressed-XLSX decompression remained unbounded — this round is where the update-only decision was made. **Round 3** (`4782840059`) found the update-only cutover incoherent between the authoritative spec, frontend, and backend (the frontend still exposed the toggle; the backend still accepted `update_existing=false`), and found `raw_source_status` was being silently whitespace-stripped before persistence. **Round 4** (`4782986913`) recorded APPROVE WITH NON-BLOCKING COMMENTS — a stale Part E table row and a small missing test, both tracked as ordinary follow-up maintenance, not merge blockers.

Merged as GitHub PR #43, squash SHA `94554a3a2ce6812f8fca6ab22455cd04384a29e6`, from branch `feature/pr12-inventory-import`, baseline `0974735f25dc12b71595801a2a32cf97c8c18cb3`. See `docs/DECISION_LOG.md` ("Roadmap PR12 — Inventory Import (update-only)") for the full four-round review chronology. **Roadmap PR12 is now fully complete.** The next planned item is Roadmap PR13 (Search, History, and Reporting Adjustments).

## Search/history filtering and dashboard cleanup complete (Roadmap PR13)

`docs/audits/04-consolidated-implementation-plan.md` Part D's PR13 entry called for three things: finalizing BCM-Code-first search/scan priority per `knowledge/adr/ADR-003-bcm-manual-search.md`, dispatch-type/round-aware history filtering, and removing MVP-irrelevant dashboard elements (PM/CAL widgets) in favor of a read-only "days since dispatch" indicator. Before writing any new search code, `app.crud.equipment.search_bcm` (shipped in Roadmap PR5) was checked against every ADR-003 requirement — partial/prefix-optional matching, exact-match-first ranking, bounded results, minimal-disclosure suggestions (internal ID + BCM Code only), empty/short-query handling — and found already fully compliant, with existing test coverage in `backend/tests/test_equipment.py`. No new search code was needed; PR13's actual implementation scope was the remaining two items.

`GET /transactions` gained `dispatch_type`, `routine_round`, `from_date`, and `to_date` query-parameter filters (`app.crud.transaction.search()`, `app/api/v1/transactions.py`), combinable with the existing `ward_id`/`equipment_id`/`status` filters. `DashboardSummary` (`app/schemas/dashboard.py`, `app/services/dashboard_service.py`) no longer returns `pm_due_soon`/`cal_due_soon` — the unnumbered Post-PR11 Dashboard PR (GitHub PR #40) had already stopped rendering these on `DashboardPage.tsx`, so removing them from the backend response affected no active client. On `EquipmentDetailPage.tsx`'s existing per-equipment transaction history — the dashboard itself carries no per-transaction history surface after PR40 — new filter controls for the four params were added, alongside dispatch-type/round distinguishability per row (satisfying Part H's acceptance criterion that a completed on-demand dispatch must be distinguishable from a routine dispatch in history) and a read-only, client-computed "days since dispatch" indicator shown only for OPEN transactions, replacing the retired overdue-indicator concept without implying any due date or maintenance deadline.

Two independent Codex reviews on Draft PR #45, each on a new exact head before the next began: **Review `4783120601`** (finding **PR13-M1**) found `transaction_crud.search()`'s date-range upper bound — computed as `to_date + timedelta(days=1)` — could raise `OverflowError` for `to_date=9999-12-31` (Python's `date.max`), an ordinary, syntactically valid ISO date string a client can send; this would have surfaced as an unhandled `500`, not a clean validation response. The same review found a reversed range (`from_date` after `to_date`) was silently accepted and simply returned an empty page. Fixed: the upper bound is computed as `datetime.combine(to_date, time.max)` instead of incrementing the date — always representable for any valid `date`, never overflows; a reversed range is now rejected explicitly with a structured `400` (`INVALID_INPUT`) at the API boundary, before the request reaches `search()`. Regression tests were added for `date.max`/`date.min` bounds, reversed ranges (including the extreme combination of both), equal start/end dates, and omitted-date behavior left unchanged. **Review `4783200709`** confirmed PR13-M1 resolved and recorded APPROVE WITH NON-BLOCKING COMMENTS — one non-blocking item (stale PR description/evidence), addressed by refreshing the description before merge.

`backend/tests/test_transaction_search.py` (new, 16 tests) covers dispatch-type/routine-round/date-range filtering individually and combined with existing filters, dispatch-type persistence through receipt/closing, and the date-range edge cases above. `backend/tests/test_equipment.py`'s dashboard-summary test was tightened to assert the exact response-key set. Frontend: `EquipmentDetailPage.test.tsx` gained coverage for the new filter controls, dispatch-type distinguishability, and the days-since-dispatch indicator; `DashboardPage.test.tsx`'s fixtures were updated to match the schema change.

Merged as GitHub PR #45, squash SHA `8f7ef12e1660b35021df64fc9a529495cca77e49`, from branch `feature/pr13-search-history-reporting`, baseline `94554a3a2ce6812f8fca6ab22455cd04384a29e6`. See `docs/DECISION_LOG.md` ("Roadmap PR13 — Search, history, and reporting adjustments") for the full review chronology. **Roadmap PR13 is now fully complete.**

## Reliability correctness complete (Roadmap PR14, PR14A slice)

Roadmap PR14 ("Reliability and Performance Hardening") is treated as an Epic implemented through multiple focused slices, following the same lettered-slice precedent as PR7/PR8/PR9, rather than one broad PR — Operational Logging is deferred to Roadmap PR15, and Pagination Performance is deferred to a later PR14B, gated on EXPLAIN ANALYZE evidence of a real query-plan problem rather than a document-only finding. PR14A is scoped to exactly three reliability-correctness concerns from `docs/audits/02-backend-architecture-audit.md`: Finding 4.1 (PATCH nullable-field correctness), Finding 16.1 (scheduler N+1), and Findings 6.1/7.1 (transaction boundary audit).

**PATCH nullable-field correctness.** `app.crud.equipment.update()` and `app.crud.user.update()` both previously used a single-pass `if value is not None: setattr(...)` loop, which silently discarded *every* explicit-null PATCH request — including on nullable business fields a client should have been able to clear. Rewritten as a two-pass validate-then-mutate: pass 1 rejects an explicit null on any field the domain model requires to be non-null (`equipment_name`; `full_name`, `is_active`) with `400 INVALID_INPUT`, before any mutation, and also rejects an explicit null on `bcm_code`/`item_no` (`NON_CLEARABLE_IDENTITY_FIELDS`, ADR-002 canonical identity fields — non-clearable, not immutable; non-null updates are unaffected), which was previously a silent no-op that could leave a misleading audit record showing the submitted null while the persisted identifier stayed unchanged. Because the raise happens before any `setattr` and before the caller reaches `record_audit_event`, a rejected request produces zero audit events and zero mutation. Pass 2 then applies every remaining key/value pair unconditionally — the actual bug fix: `brand`, `model`, `pm_due_date`, `cal_due_date`, `category_id`, `department_owner_id`, `current_location_id`, `serial_number` (Equipment), and `phone` (User) can now genuinely be cleared via PATCH null. Blank/whitespace-only string validation for `equipment_name`/`full_name` is explicitly out of scope, deferred to a future focused PR.

**Scheduler N+1 fix.** `app.worker.scheduler.check_pm_cal_due()` previously re-queried the notification-recipient list once per due equipment row. It now queries PM-due and CAL-due equipment first; if both sets are empty, it exits immediately with zero recipient queries; otherwise it loads the recipient list exactly once and reuses it for every notification. No change to notification content, recipient role/active-status filtering, or the commit boundary shape.

**Transaction boundary audit.** `docs/audits/05-pr14a-transaction-boundary-audit.md` inspected every `await db.commit()` call site across `app/api`, `app/services`, `app/worker`, and `app/scripts`, and categorized them into four buckets: ordinary request/business commits (15 sites, one per successful request); the scheduler commit (one per run, its own session); the authentication-specific best-effort commit (`app.core.audit.commit_best_effort`, 4 call sites in `app.services.auth_service` — a successful login's commit closes both the `last_login_at` update and the `login_success` audit row together, and deliberately swallows a commit-time failure so a transient audit-subsystem problem can never turn a legitimate authentication outcome into an unrelated 500); and the seed/script commit (`app.scripts.seed`, an operator-run script not reachable from the running application). Conclusion: no atomicity drift was identified; the existing caller-owned commit architecture is intentionally left unchanged, and structural transaction-management changes remain deferred pending a separate architecture review. `app.db.session.get_db()`'s docstring now states only its actual guarantee — closing an uncommitted session rolls back the transaction — without implying automatic commit, automatic recovery, or a substitute for explicit rollback after a caught database error.

One Codex review round on Draft PR #46, before the PR was squash merged: the substantive review decision was **REQUEST CHANGES** (surfaced by GitHub as `COMMENTED` only because the reviewing account owns the PR), with four findings — the `User.phone`-clearing regression test asserted only HTTP 200, which the pre-PR14A silent-no-op implementation could also return, so it did not prove persisted state actually changed; the transaction-boundary audit had swapped the login-success/login-failure line references and omitted the `last_login_at` detail; the PR description claimed "no API or data impact," which understated a real PATCH-semantics change; and `IMMUTABLE_IDENTITY_FIELDS` was a misleading name, since non-null updates to `bcm_code`/`item_no` are unaffected. All four were fixed on a new exact head: the phone test (and the equivalent equipment `brand`-clearing test) now assert a direct DB re-read of the persisted value plus the audit row's `after` payload, not HTTP 200 alone; the audit doc's line references were corrected and the `last_login_at` detail added; the PR description gained explicit "API behavior impact," "Data impact," and "Rollback limitation" sections (code rollback does not un-clear a value a client legitimately cleared while PR14A was deployed); the constant was renamed to `NON_CLEARABLE_IDENTITY_FIELDS`. CI (141 tests, zero skips, including PostgreSQL) was green on the reviewed head both before and after the fix.

New/strengthened tests: `backend/tests/test_equipment.py` (nullable-field clearing verified via PATCH response, a fresh GET, a direct DB re-read, and the audit row's `after` payload; identity-field null rejection with zero mutation and zero audit event); new `backend/tests/test_users_crud.py` (same pattern for `User.phone`/`full_name`/`is_active`); new `backend/tests/test_scheduler.py` (zero due rows → zero recipient queries; any due rows → exactly one recipient query; notification count == due rows × active recipients; inactive users and unrelated roles excluded; PM/CAL content unchanged; equipment outside the due horizon produces nothing).

Merged as GitHub PR #46, squash SHA `ddd17b180c06a4fd2421f4886c0568876498abb2`, from branch `feature/pr14a-reliability-correctness`, baseline `8f7ef12e1660b35021df64fc9a529495cca77e49`. See `docs/DECISION_LOG.md` ("Roadmap PR14 (PR14A slice) — Reliability Correctness") for the full review chronology and the recorded non-blocking test-hardening follow-ups (additional per-field PATCH null-clearing coverage; a two-pass-ordering regression test; the deferred blank-string-validation decision). **PR14A is now fully complete.**

## Pagination performance complete (Roadmap PR14, PR14B slice)

Roadmap PR14's remaining slice, deferred by PR14A: strictly evidence-gated, per Repository Owner approval — no index or pagination-logic design work began without `EXPLAIN (ANALYZE, BUFFERS)` evidence of a real query-plan problem gathered first (`docs/audits/06-pr14b-pagination-index-evidence.md`, 200,000 `equipment`/1,000,000 `borrow_transactions` rows, realistic non-clustered `created_at` timestamps spread over ~2 years — a first pass using tightly-clustered batch-insert timestamps was discarded as misleadingly pathological for deep-cursor measurement). Scope limited to database indexes, migration, PostgreSQL verification, and regression tests: no API behavior change, no pagination-algorithm redesign, no `COUNT(*)` optimization, no endpoint contract change.

**What was built.** `backend/alembic/versions/0011_pagination_ordering_indexes.py` adds two composite `(created_at DESC, id DESC)` btree indexes — `ix_equipment_created_at_id` on `equipment`, `ix_borrow_transactions_created_at_id` on `borrow_transactions` — matching the literal `ORDER BY` clause `app.crud.equipment.search()`/`app.crud.transaction.search()` already issue for cursor pagination. First-page queries dropped from 45.5-205.5ms (sequential/parallel scan + sort) to under 1ms (index scan, no sort node) at evidence scale, verified structurally via `EXPLAIN` for both tables, not assumed. `CREATE INDEX CONCURRENTLY` was chosen over plain `CREATE INDEX`: `equipment`/`borrow_transactions` are actively read/written during live hospital-equipment-pool operation, and a plain `CREATE INDEX`'s `SHARE` lock (blocks writes for the full build duration; ordinary reads remain available throughout) was judged less acceptable than `CONCURRENTLY`'s non-atomic, longer build — both statements run inside `op.get_context().autocommit_block()`. Deliberately not declared on the SQLAlchemy models (TD-002 — `0001_initial.py` reflects current ORM state at run time, so an ORM-declared index would race the dedicated migration on a fresh install); migration `0011` is the sole source of truth for both indexes on every path, each verified locally against real PostgreSQL 16 before being captured as a regression test.

**Honestly-reported limitation.** The cursor `WHERE` clause (`created_at < :cursor OR (created_at = :cursor AND id < :cursor_id)`) is a disjunctive condition PostgreSQL cannot translate into a single sargable index-range boundary against a plain composite index — only `created_at <=` is pushed into an `Index Cond`; the rest becomes a `Filter` walking every row in range. Measured crossover point ≈75,000-100,000 rows past page one, beyond which the index makes deep-cursor pagination *slower*, not faster (up to 2,621ms at 500,000 rows deep, versus a flat ~146ms baseline without the index). Accepted, not fixed, because this system's confirmed real-world scale ("low hundreds of devices, thousands of transactions per year") never puts a real user 75,000+ rows deep in a paginated list; fixing it would be a pagination-logic redesign, out of scope for this slice.

Two Codex review rounds on Draft PR #48, each on a new exact head before the PR was squash merged: **Round 1 was merge-blocking.** A bare `CREATE INDEX CONCURRENTLY IF NOT EXISTS` retry cannot distinguish a genuinely completed index from one left `INVALID` by an interrupted build (process killed, connection lost, deadlock, or a genuine build failure) — both satisfy `IF NOT EXISTS`, so a naive retry would silently skip forever and Alembic would record the migration as successful while the intended index stayed unusable. Also required real PostgreSQL regression coverage proving retry safety (not just presence), independent planner assertions for both tables, and a lock-semantics documentation correction — the original docstring incorrectly described a plain `CREATE INDEX`'s lock as blocking all reads and writes; corrected to state a `SHARE` lock blocks writes only. The Repository Owner explicitly directed **fail-closed over auto-repair**: an automatic drop/rebuild could mask an underlying deployment problem the migration has no way to diagnose, whereas failing loudly with a clear error lets an operator inspect and decide — prioritizing data correctness and auditability over automatic recovery. Fixed by adding `_ensure_index_concurrently()`, which inspects `pg_indexes.indexdef` and `pg_index.indisvalid`/`indisready` for any existing same-named index before treating it as done, and raises `RuntimeError` with the detected state and the exact recovery step (`DROP INDEX CONCURRENTLY IF EXISTS ...`, then re-run) when the index is invalid, not ready, or valid-but-differently-defined. **Round 2** recorded APPROVE WITH NON-BLOCKING COMMENT — the PR description still described the superseded Round 1 behavior (a stale test count and no mention of the fail-closed handling); fixed by rewriting the description to match the final diff. No code change required for Round 2; the review confirmed Round 1's findings fully resolved.

Nine PostgreSQL-marked regression tests in `backend/tests/test_postgres_integration.py`: fresh-install convergence; historical-upgrade/downgrade/re-upgrade round trip; index column order/direction (inspected via `pg_indexes.indexdef` directly, since SQLAlchemy's generic reflection does not reliably report index column direction); planner assertions for both `equipment` and `borrow_transactions` first-page queries; cursor-pagination result-set completeness (120 rows, full traversal, no duplicates/gaps, matches unpaginated order); an explicit `COUNT(*)` non-regression check; the interrupted-build fail-closed-with-recovery test; and the mismatched-definition fail-closed test.

Merged as GitHub PR #48, squash SHA `82e289d40811b413659e7303a1690b66275e9759`, from branch `feature/pr14b-pagination-ordering-indexes`, baseline `4d891ac8f9f1cc1ada45347d384d06fde705a97a` (the PR14A governance sync merge, GitHub PR #47). CI (617 tests: 467 non-PostgreSQL + 150 PostgreSQL) was green on the merged head. See `docs/DECISION_LOG.md` ("Roadmap PR14 (PR14B slice) — Pagination Performance") for the full review chronology. **PR14B is now fully complete — Roadmap PR14 (both PR14A and PR14B slices) is fully complete.** Roadmap PR15 (Observability and Schema Hygiene, which also covers PR14's deferred Operational Logging scope item) is the next planned item.

## Observability complete (Roadmap PR15, PR15A slice)

Roadmap PR15 ("Observability and Schema Hygiene," which also covers PR14's deferred Operational Logging scope item) is treated as an Epic implemented through multiple focused slices, following the same lettered-slice precedent as PR7/PR8/PR9/PR14, per an architecture-approved design revision (`docs/design/PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md`, Revision 2, uncommitted design doc per this repository's established convention — see the PR8 design-doc precedent). **PR15A** is scoped to observability only: structured logging, request/correlation IDs, async-safe propagation, one bounded access-log event per request, background-job run IDs, and aggregate import-commit logging. Schema migrations, timezone migrations, FK `ondelete` policies, CHECK constraints, and index naming are deferred to a later PR15B; application metrics, tracing, dashboards, log aggregation, and alerting are not scheduled to any PR15 slice at all — they remain open Roadmap PR15 scope pending a future slice or an explicit governance decision to remove them.

**Structured logging and correlation IDs.** `app.core.log_context` introduces three `contextvars.ContextVar`s — `request_id`, `correlation_id`, `job_run_id` — propagated async-safely through a request's or job's whole call chain (not thread-local, which is unsafe under asyncio's cooperative concurrency), plus `RequestContextFilter`, a `logging.Filter` on the log handler that fills these onto every `LogRecord` unless a call site already supplied a value via `extra=`. `app.core.logging.JsonFormatter` emits one JSON object per log line (timestamp, level, logger, message, correlation IDs, a small fixed allowlist of extra fields, exception traceback when present) — the allowlist is deliberate, not a passthrough of `record.__dict__`, so a stray `extra={...}` field at some future call site can never silently reach output.

**Idempotent logging configuration.** `configure_logging()` explicitly clears the root logger's existing handlers before installing its own JSON handler, rather than relying on `logging.basicConfig()`'s default idempotency (a silent no-op once the root logger already has any handler) — this makes the end state deterministic regardless of whether Uvicorn, pytest, or this module happens to configure logging first, and idempotent on repeat calls.

**One-per-request access log, fail-safe post-success logging (`safe_log()`).** `app.main`'s `request_context_middleware` sets/reuses `X-Request-ID`/`X-Correlation-ID` (an inbound header is validated against a conservative charset/length pattern before reuse, never trusted verbatim) and emits exactly one access-log event per request (method, route *template* — not the raw URL, to keep log cardinality bounded; unmatched routes fall back to a fixed `"unmatched"` label) from a `finally` block, unconditionally resetting both ContextVars afterward. `app.core.logging.safe_log()` is the mechanism that makes this fail-safe: it runs a logging call and guarantees that neither it nor its own best-effort fallback report can ever propagate an exception back to the caller — a real architectural gap the review chronology below found and closed in two rounds, since a naive try/except-with-unguarded-fallback pattern could still let a broken logging subsystem turn a successful request, scheduler run, or import commit into an unhandled failure. `safe_log()` is applied to the access-log emission, both scheduler success/failure log calls, and both import success/failure log calls (`app.worker.scheduler.check_pm_cal_due()`, `app.services.import_service._commit_rows()`) — the import success log carries only aggregate row-count statistics, never the filename or any row/cell content.

Three independent Codex reviews on Draft PR #50, each on a new exact head, before the PR was squash merged: **Review 1** (review ID `4787144983`, reviewed head `746732dc2d758286d4340cf4628327e1206b8329`, CI run `30267254839`, 5/5 jobs green) was **REQUEST CHANGES** with two merge-blocking findings — `PR15A-H1`: `configure_logging()` relied on `logging.basicConfig()`'s default idempotency, reproduced by installing a root `StreamHandler` before calling `configure_logging(False)` and confirming its formatter stayed unset; since Uvicorn commonly configures logging before importing the application, the JSON formatter could silently never install depending on import order. `PR15A-H2`: the new post-commit import-success log ran after `await db.commit()` had already succeeded; a failure there could turn an already-committed, successful import into an HTTP 500, and the access-log's fallback `logger.warning()` was itself unguarded. **Review 2** (review ID `4788591587`, reviewed head `c32270e01073fb486066d5f95548282056f3b930`, CI run `30277548822`, 5/5 jobs green) was **REQUEST CHANGES** — H1 confirmed resolved (root handlers now explicitly cleared before installing the JSON handler, deterministic regardless of import order); `PR15A-H2R` (the unaddressed remainder of H2): the primary post-commit `logger.info()` call was now caught, but the fallback `logger.warning()` immediately following it was itself still unguarded — the same gap existed in the access-log fallback and in scheduler completion logging (still inside the job's broad business `try`, so a completion-log failure was caught and reported as a job failure). **Review 3** (review ID `4789829543`, reviewed head `eeae67542d02e1dc266a15979c2b02857020f872`, CI run `30286421490`, 5/5 jobs — Backend tests non-PostgreSQL, Backend tests PostgreSQL, Alembic migration upgrade validation, Frontend build, `git diff --check` — all green) recorded **APPROVE WITH NON-BLOCKING COMMENTS** — `PR15A-H2R` confirmed resolved by `safe_log()`, independently verified at this exact head by 24/24 passing tests in `backend/tests/test_observability_logging.py` (new regression tests covering the double-failure case — the primary log call *and* its own fallback both raising — for all three affected paths); `PR15A-M1` (non-blocking, explicitly accepted as a deferred follow-up): the four exception-handler log lines in `app/main.py` still log the raw request path rather than the route template used by the access-log line.

New tests: `backend/tests/test_observability_logging.py` (24 tests) — concurrent-request `request_id` isolation; `ContextVar` reset in `finally` (including when the job/request raised); invalid/oversized/unsafe-character inbound request IDs rejected and never logged; exception-path logging for all four handler types; exactly one access-log event per request with the route template (not raw URL); sensitive-data non-persistence (passwords, BCM codes, Item Numbers, filenames never appear in formatted log output); `configure_logging()`'s idempotency when a handler already exists; and fail-safe coverage for every post-success logging path, including the double-failure case, for `safe_log()` itself and each of its three call sites.

Merged as GitHub PR #50, squash SHA `e250638db186f8e4dc3358bd475e9cf4eebc0bc8`, from branch `feature/pr15a-observability`, baseline `a43b680a5558aa322a613b3e3eba0eeb45858edf` — the documentation-only post-merge governance sync recording Roadmap PR14B's completion, GitHub PR #49 (not GitHub PR #48/`82e289d`, PR14B's own squash commit one further back). CI run `30286421490` (5/5 jobs: Backend tests non-PostgreSQL, Backend tests PostgreSQL, Alembic migration upgrade validation, Frontend build, `git diff --check`) was green on the merged head. No schema or migration change. **No breaking API changes:** the implementation adds backward-compatible response headers only (`X-Request-ID`, `X-Correlation-ID`); existing clients continue to function without modification, and business semantics, response bodies, and status codes remain unchanged. See `docs/DECISION_LOG.md` ("Roadmap PR15 (PR15A slice) — Observability") for the full three-round review chronology. **PR15A is now fully complete. Roadmap PR15 (the Epic) is NOT fully complete** — PR15B (Schema Hygiene) is the next planned item, and application metrics, tracing, dashboards, log aggregation, and alerting remain open Roadmap PR15 scope, not scheduled to any slice, pending a future slice or an explicit governance decision to remove them from scope.

## Schema Hygiene complete (Roadmap PR15, PR15B slice)

Roadmap PR15's remaining scheduled slice — the architecture-approved design from `docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md` (GitHub PR #52) — is implemented across three independently-revertible migrations. **Migration `0012_timezone_conversion.py`** converts five naive `timestamp` columns (`audit_logs.created_at`, `notifications.created_at`, `equipment_status_history.changed_at`, `borrow_transactions.borrowed_at`/`.returned_at`) to `timestamptz` via `AT TIME ZONE 'UTC'` — not a bare cast, since the design traced every existing value's write path to `datetime.utcnow()` and confirmed the wall-clock numbers are already UTC by construction. `borrow_transactions.due_at` is deliberately excluded and remains naive: its historical values were client-supplied with no server-side timezone normalization, so there is no evidence to support reinterpreting them. **Migration `0013_fk_ondelete_policy.py`** makes `ON DELETE RESTRICT` explicit on all 25 foreign keys — zero observable behavior change, since the only `DELETE` endpoint in the API is already a soft delete and none of the 25 relationships was ever exercised by a real `DELETE`. **Migration `0014_index_naming_convergence.py`** renames the 5 hand-named `idx_`-prefixed indexes and 7 auto-named `<table>_<column>_key` unique constraints onto the `ix_`/`uq_` convention already used by the other 29 indexes and 4 named constraints. All three migrations are paired with the ORM-side companion changes the design requires (`UTCDateTime`/`DateTime(timezone=True)` on the five converting columns, `ondelete="RESTRICT"` on all 25 `ForeignKey()` declarations, explicit `UniqueConstraint(name="uq_...")` on the 7 renamed constraints) so a fresh `Base.metadata.create_all()` install and a historical `alembic upgrade` converge on the identical schema.

**One invariant applies uniformly across all three migrations, on every execution path:** every rename, `ON DELETE` change, and type conversion is decided only after inspecting the actual PostgreSQL catalog state (`pg_get_indexdef()`/`pg_get_constraintdef()`, `pg_index.indisvalid`/`indisready`, `information_schema.columns.data_type`) through one shared classification helper per migration (`_classify_rename()` in `0014`, `_classify_fk()` in `0013`) — never assumed, never based on a partial check, and identical whether the object is found under its legacy name, its target name, on a fresh install, or a historical upgrade, and in either direction (upgrade or downgrade). An object matching every definitional check but found unhealthy (`indisvalid`/`indisready` false, e.g. left behind by an interrupted `CREATE INDEX CONCURRENTLY`) or in a genuinely partial state (a standalone index with no owning unique constraint, or vice versa) always fails closed with a `RuntimeError` naming the exact mismatch — never silently repaired, renamed, or no-op'd past.

An independent design-compliance review, conducted before this branch's Pull Request was opened, raised and resolved three findings against this invariant: **H1** — migration `0014` originally verified only partial metadata (name and a single field) before renaming or accepting an object as already-converged, instead of the full semantic-definition-plus-health check described above; **H2** — migration `0013`'s downgrade path originally verified only `confdeltype` before reverting a foreign key, rather than the same full-definition check its upgrade path used; **H3** — migration `0014`'s `_ConstraintVerifier.fetch()` originally collapsed two distinct catalog states into `None` — a name that is truly absent, and a name that is in a genuinely partial state (only the index or only the unique constraint exists under it) — silently treating the second as the first. All three were fixed by unifying verification into the shared classifiers described above, with a `_CatalogState` (ABSENT/COMPLETE/PARTIAL) wrapper closing H3 specifically. Regression tests for all three scenarios (interrupted/unhealthy index builds under both the legacy and target name, mismatched FK/unique-constraint semantics, both-names-present, and each PARTIAL-catalog-state combination under both upgrade and downgrade) are in `backend/tests/test_postgres_integration.py`, each asserting `RuntimeError`, zero schema mutation, and byte-for-byte unchanged definitions/health flags afterward.

`backend/app/models/mixins.py`'s `UTCDateTime` type also gained a write-side invariant during this work: `datetime.utcnow()` call sites (`auth_service.py::last_login_at`, `crud/transaction.py::returned_at`, `crud/equipment.py::soft_delete()::deleted_at`) were changed to `datetime.now(timezone.utc)`, and `UTCDateTime.process_bind_param()` now fails closed (raises) on a non-UTC aware datetime rather than silently normalizing it, since this application has no legitimate reason to construct one — a value reaching this column with the wrong offset indicates a real bug upstream.

Merged as GitHub PR #54, squash SHA `6f66d76`, from branch `feature/pr15b-schema-hygiene`, baseline `6a845140832b6269c8d7d0177c78fc00cb828f26` (the documentation audit and roadmap alignment commit, GitHub PR #53). The design-compliance review (H1/H2/H3 above) and one incremental re-review after a `knowledge/CONTEXT.md` merge-conflict rebase (no implementation file touched by the rebase) both recorded APPROVE WITH NON-BLOCKING COMMENTS. CI (5/5 jobs: Backend tests PostgreSQL, Backend tests non-PostgreSQL, Alembic migration upgrade validation, Frontend build, `git diff --check`) was green on the exact merged head. **PR15B is now fully complete — both of Roadmap PR15's scheduled slices (PR15A Observability, PR15B Schema Hygiene) are complete. Roadmap PR15 (the Epic) is still NOT fully complete**, since application metrics, tracing, dashboards, log aggregation, and alerting remain open Roadmap PR15 scope, not scheduled to any slice, pending a future slice or an explicit governance decision to remove them.

## Reporting Foundation complete (Roadmap PR16)

Roadmap PR16 ships across four Implementation Slices, per the architecture-approved design (`docs/design/PR16_REPORTING_FOUNDATION_PLAN.md`, GitHub PR #56) and the Repository Owner's confirmed Day/Night shift boundary policy (Owner Decision #1: 08:00/20:00 Asia/Bangkok, `business_date_anchor = shift_start_date`, `on_demand` classified identically to a routine-round dispatch). `business_date` and `shift` are computed, never persisted — one pure-Python reference function and one SQLAlchemy-expression twin (`backend/app/core/reporting_time.py`, Slice 1), both driven by the same named boundary policy, tested against each other so they can never silently diverge.

`BorrowTransaction` gained four computed properties — `dispatch_business_date`/`dispatch_shift` (from `borrowed_at`, always present) and `receipt_business_date`/`receipt_shift` (from `returned_at`, `None` until received) — surfaced on `TransactionOut` (Slice 2). `GET /transactions` gained `business_date_from`/`business_date_to`/`shift`/`event` (`dispatch`/`receipt`, default `dispatch`) query parameters, filtering against the derived value directly, never the raw timestamp — the existing `from_date`/`to_date` filters are untouched and remain a separate, raw-timestamp basis (Slice 3). `EquipmentDetailPage.tsx` gained matching filter controls, explicitly separate from the existing `from_date`/`to_date` pair, committed via Apply/Clear and backed by URL state (Slice 4).

A review-fix during Slice 4 (PR61-H1) closed a UI/API semantics mismatch: since the backend's `event` parameter has no "all events" value (a strict `dispatch|receipt` two-value basis, confirmed against both the design and the merged code directly, not assumed), the frontend's "ทั้งหมด" (All) option now never sends `business_date_from`/`business_date_to`/`shift` on the wire — the only way "All" can honestly mean "all events" without a backend change or client-side dispatch/receipt merging.

See `docs/DECISION_LOG.md` ("Roadmap PR16 — Reporting Foundation Complete") for the full slice-by-slice implementation and review chronology, and `docs/ROADMAP.md`/`docs/ROADMAP_STATUS.md` for the updated baseline. **Roadmap PR16 is now fully complete.** The next planned item is Roadmap PR17 (Date/shift-filtered Receive, Issue, and Equipment Verify Checklist reports).

## Operational Reports complete (Roadmap PR17)

Roadmap PR17 ships across four Implementation Slices, per the architecture-approved design (`docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md`, GitHub PR #63) and the Repository Owner's confirmed Equipment Verify Checklist definition (Owner Decision #1: Option A — a read-only, current-state Equipment master-data snapshot; no physical-verification workflow, no verification-event storage, no new equipment lifecycle state, no migration).

`transaction_crud.search()` gained `equipment_category_id`/`operator_id` filters and an unconditional `require_receipt` predicate enforcing the Receive Report's completed-receipt-only rule regardless of which other filters are present (Slice 1, GitHub PR #65). `GET /reports/receive` and `GET /reports/issue` were added, backed by a dedicated report-only `ReportTransactionOut` schema (operator display fields kept off the shared `TransactionOut` contract, unlike Roadmap PR16's `business_date`/`shift` properties which live directly on `TransactionOut`), plus `GET /report-options/operators` — a bounded historical-operator lookup, never a general user directory (Slice 2, GitHub PR #66). Thai-first `/reports/receive` and `/reports/issue` frontend screens were added, with URL-state-backed business-date/shift/ward/category/operator filters and strictly backend-preserved result ordering (Slice 3, GitHub PR #67).

`GET /reports/equipment-verify-checklist` and its frontend screen were added last (Slice 4, GitHub PR #68) — a read-only listing of the pool's own `Equipment` master records and their current status, filterable by category/status/department (no `ward_id` filter — `Equipment` has no direct Ward relationship). It reuses the existing operator-facing `EquipmentOut` response boundary (which deliberately excludes `item_no`, per ADR-002/ADR-003) rather than inventing a new DTO, and is explicitly not a transaction/event report: no `business_date`/`shift` basis, no "verification" action or completion state. GitHub PR #68's incremental fix round recorded Owner Decision #1's resolution in `docs/DECISION_LOG.md`, synchronized every stale "not confirmed/unresolved/pending" reference in the design document, and added structured malformed-cursor handling for the Equipment Verify Checklist endpoint by hardening the shared cursor-decoding layer: `app/utils/pagination.py::decode_cursor`/`decode_alpha_cursor` previously let a malformed client-supplied cursor (invalid Base64, corrupt JSON, missing fields, unparseable timestamp) escape as an uncaught exception (HTTP 500); it now raises the existing `InvalidInputError` `DomainError`, returning the repository-standard structured `400 INVALID_INPUT` client error for those cases — this also hardens the already-merged Receive/Issue/operator-lookup/`GET /equipment` endpoints, which shared the same decoder. At the time of GitHub PR #68, full cursor hygiene across every existing caller was not yet complete: `app/crud/user.py::list_operators`'s own caller-specific `uuid.UUID(cursor_id)` parsing, which ran after the shared decoder returned, remained unguarded, so a structurally well-formed alpha cursor carrying a non-UUID id could still reach an uncaught exception on that one path.

## Operator-options cursor-hygiene gap closed (maintenance fix)

The `list_operators` gap noted above is resolved: `app/crud/user.py::list_operators` now validates the decoded cursor's UUID before any query executes (mirroring `equipment_crud.list_for_verify_checklist`'s established convention from GitHub PR #68), and raises the existing `InvalidInputError` (`400 INVALID_INPUT`) for a structurally well-formed alpha cursor whose id is not a real UUID, the same as every other cursor-consuming endpoint in the codebase. Covered by `backend/tests/test_operator_options_cursor_validation.py`. This was a narrowly scoped maintenance fix — no runtime contract, response schema, migration, or business semantics changed, and it did not begin Roadmap PR18.

Merged as GitHub PR #68, squash SHA `d4aaf0f08016b6e63774a06cdade5afe4737d3f7`, from branch `feature/pr17-slice4-equipment-verify-checklist`, baseline `8a1a28042e791bd321a67d4dae7a7b46ab0f8f6c` (Slice 3's squash merge). See `docs/DECISION_LOG.md` ("Roadmap PR17 — Owner Decision #1 (Equipment Verify Checklist Definition)" and "Roadmap PR17 — Operational Reports Complete") for the full slice-by-slice implementation and review chronology, and `docs/ROADMAP.md`/`docs/ROADMAP_STATUS.md` for the updated baseline. **Roadmap PR17 is now fully complete.** No new equipment lifecycle state, no change to `TransactionOut`, no physical-verification workflow, and no database migration were introduced anywhere in Roadmap PR17. See the newer entries above for subsequent PR18 status.
