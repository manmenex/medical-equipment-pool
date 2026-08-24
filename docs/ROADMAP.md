# Roadmap

**Purpose:** Current-state snapshot of the Medical Equipment Pool Roadmap — what is merged, what is next, at the current baseline
**Authority:** Detailed Roadmap summary. `docs/audits/04-consolidated-implementation-plan.md` Part D remains authoritative for Roadmap PR scope, order, dependencies, and acceptance criteria. `docs/ROADMAP_STATUS.md` is the concise live dashboard and does not redefine scope.
**Update trigger:** A Roadmap PR merges, is added, is reordered, or the baseline changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

**The single current authoritative baseline is
`527ffc48966d7e5cda16a869f0ae464de8b7512a`** — the real squash-merge SHA
of GitHub PR **#121**, "PR22G — Roadmap PR22 Governance Close-out",
squash-merged into `claude/medical-equipment-pool-0c7fz0` on top of
`76040d5e87223767c9dbe36eb67c6a156af12c0c` (GitHub PR #120, PR22F, now
historical/superseded by this baseline). PR #121's final independently
reviewed feature-branch head (`fafb40e7ef388a35b3b1848d04d26ba2f37c7281`,
after three fix rounds correcting stale "PR22F in progress"/"PR22 is
next" current-state prose across `knowledge/PROJECT_MEMORY.md`,
`docs/ROADMAP_STATUS.md`, `docs/audits/04-consolidated-implementation-plan.md`,
`knowledge/CHANGE_HISTORY.md`, and `docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md`)
carried **zero review threads and zero comments**, CI green 6/6, and the
reviewed head's tree was verified byte-identical to the merged squash
commit's tree, sole parent `76040d5e...` confirmed. Per this
repository's standing process, **no separate self-referential "baseline
adoption" PR is created for PR #121's squash SHA** — it became
authoritative immediately upon merge, and its recording here is folded
into PR23A (the next PR that legitimately touches these governance
files).

**Roadmap PR22 (Legacy Data Validation and Reconciliation) is now fully
complete** — architecture design (GitHub PR #112), all seven Owner
Decisions OD-PR22-1 through OD-PR22-7 (GitHub PR #115), every
implementation slice PR22B–PR22F (GitHub PR #116/#117/#118/#119/#120:
schema/run-snapshot foundation, deterministic analysis engine, finding
review/disposition API, sign-off + concurrency/audit, frontend
integration), and governance close-out PR22G (GitHub PR #121) are all
merged. See `docs/DECISION_LOG.md`'s PR22-prefixed entries and the
"PR21 note"-style paragraph below for the full slice-by-slice
chronology; every individual PR22B–F squash SHA is preserved there and
in the Completed table, not repeated in full here.

**Roadmap PR23 (Cutover Readiness)'s first slice, PR23A (Architecture &
Operational Design), is in progress, not yet merged** —
`docs/design/PR23_CUTOVER_READINESS_PLAN.md`, design/governance only,
zero `backend/**`/`frontend/**`/`alembic/**`/`tests/**` change. PR23A
proposes a minimal PR23B–F implementation sequence and identifies six
Owner Decisions (source-of-truth transition, current-state/open-
transaction handling, Go/No-Go and rollback authorization, rollback
boundary, pilot scope, persisted evidence model) that must be resolved
before any PR23B+ slice begins implementation.

`d64d50d09cdf8ed7ddc1f5116b38805dfcbc7810` (GitHub PR #110, Roadmap
PR21E — Legacy History Frontend Real Integration) is now historical,
superseded first by `e07a36a...` (GitHub PR #111, PR21F) and then by
this baseline. **With PR21E merged, every Roadmap PR21 implementation
slice — PR21-Foundation, PR21A (Historical Event Schema / Provenance
Foundation), PR21B (canonical Issue parser), PR21C (canonical Receive
parser), PR21D1 (Combined Canonical Adapter + Source Admission), PR21D2
(Historical Event Execution), PR21E0 (Legacy Import Operator API
Surface), and PR21E (Frontend Real Integration) — is now merged.
Roadmap PR21 (Legacy Receive and Issue History Import) is now fully
complete.** See "Roadmap PR21 complete: PR21D1–PR21F merged" in
`docs/DECISION_LOG.md` for the full slice-by-slice review chronology and
closure record, and the PR21 note below for full detail. Both concrete
legacy dataset imports required for Version 1 (Equipment Master, PR20;
legacy transaction history, PR21) are now real, backend-and-frontend-
integrated workflows — no production import path goes through
`MockImportClient` or any PR19B mock/fixture data.

**Historical — superseded by `d64d50d...` (PR21E), itself now historical,
superseded by the current baseline above:** `2743af849702ef551927b9c362421df08c80b5d9` — the real
squash-merge SHA of GitHub PR **#96**, Roadmap PR20F (Equipment Master
Frontend Real API Integration), squash-merged into
`claude/medical-equipment-pool-0c7fz0` on top of
`698c34d9c280b2ca2ea4f299bd186517c9fb26a8` (GitHub PR #95, Roadmap
PR20E — see the PR20 note below for full slice-by-slice detail). PR #96's
final independently reviewed feature-branch head was
`38c6d33c15ed13929392d0736b9accda0886fa2e` — that reviewed head was never
the baseline either; the squash commit, `2743af8...`, was. **With PR20F
merged, all six implementation slices of Roadmap PR20 (PR20A source
artifact infrastructure, PR20B `Equipment.version`, PR20C
parse/normalize/validate, PR20D persisted `DryRunPlan`, PR20E execute,
PR20F frontend integration) were merged. Roadmap PR20 (Equipment Master
Import) was fully complete.** See "Roadmap PR20 complete: PR20A–PR20F
merged" in `docs/DECISION_LOG.md` for the full slice-by-slice review
chronology and closure record. **At the time this paragraph was current,
Equipment Master was the only concrete legacy dataset import
implemented — Receive History and Issue History import remained future
Roadmap PR21 scope, not started. This was accurate at the time; Roadmap
PR21 has since fully completed — see the current baseline above.** Every
other paragraph in this section is a historical baseline snapshot, each
superseded by every entry that describes a later-merged PR — position
within this section reflects the order paragraphs were originally
written, not chronological order. Where a paragraph's own "supersedes"
label conflicts with that fact, the label below has been corrected; no
paragraph in this section other than the current-baseline paragraph at
the top is current.

**Historical — superseded by `2743af8...` (PR20F) immediately above,
itself since superseded by `d64d50d...` (PR21E), itself in turn
superseded by the current baseline at the top of this section:**
`04f5bf5c76b51744981d1cc8072c074e604224e9` — the real
squash-merge SHA of GitHub PR **#80**, Roadmap PR19B (Legacy Import
Frontend Skeleton), squash-merged into `claude/medical-equipment-pool-0c7fz0`
on top of `7f13a1e85e9b6a4828170c4b12bc2be27b15de39` (GitHub PR #86,
Roadmap PR19A3). PR #80's final independently reviewed feature-branch
head was `5edf1bfd8de7013eb74f300193456c9e5c0f0332` (**APPROVE**, CI green
6/6) — that reviewed head was never the baseline either; the squash
commit, `04f5bf5c...`, was. **With PR19B merged, both slices of the
Roadmap PR19 approved split — PR19A (backend, all three of
PR19A1/PR19A2/PR19A3) and PR19B (frontend skeleton) — were merged.
Roadmap PR19 (Legacy Import Foundation + Frontend Skeleton) is fully
complete.** See "Roadmap PR19B merged: Exception Record closed; Roadmap
PR19 fully complete" in `docs/DECISION_LOG.md` for the full review
chronology and closure record.

**Historical — superseded by the current baseline above:** `d4aaf0f` —
squash commit of GitHub PR #68,
the Roadmap PR17 Slice 4 implementation (`GET /reports/equipment-verify-checklist`
and its frontend screen, per Owner Decision #1 resolved to interpretation A),
including its incremental fix round (Owner Decision #1 documentation
consistency, structured malformed-cursor handling for the checklist endpoint
and hardened shared cursor decoding for common malformed-payload cases —
see the PR17 note below for the `list_operators` cursor-hygiene gap that
fix round left open, since closed by a separate maintenance fix). It is
based on `8a1a280` (GitHub PR #67,
Slice 3 — frontend Receive and Issue report screens), which is based on
`aeafb81` (GitHub PR #66, Slice 2 — report APIs, `ReportTransactionOut`, and
bounded operator options), which is based on `ddb9733` (GitHub PR #65, Slice
1 — report domain and query foundation), which is based on `ed8530e`
(GitHub PR #64, the Engineering Workflow governance infrastructure — see the
Completed table below; this is supporting governance infrastructure, not a
functional PR17 slice), which is based on `b935ac2` (GitHub PR #63, the
architecture-approved PR17 design, `docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md`),
which is based on `a572a7a` (GitHub PR #62, the documentation-only governance
sync recording Roadmap PR16's completion), which is based on `ac19505`
(GitHub PR #61, the Roadmap PR16 Slice 4 implementation).
**All four Roadmap PR17 Implementation Slices are now complete — Roadmap
PR17 (Operational Reports) is fully complete.** See the PR17 note below.

**Historical — superseded by `04f5bf5c...` (PR19B) immediately above,
itself now historical/intermediate, superseded in turn by `2743af8...`
(PR20F), then by `d64d50d...` (PR21E), and now by the current baseline
at the top of this section; supersedes the paragraph below, which
described PR19A1 as still open on Draft PR #84 and PR19A2/PR19A3 as not
started:**
`7f13a1e85e9b6a4828170c4b12bc2be27b15de39` — squash commit of GitHub PR
**#86**, the Roadmap PR19A3 implementation (Dry-run, Execution, Recovery,
Retention). It is based on `7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`
(GitHub PR **#85**, Roadmap PR19A2, the Validation Foundation), which is
based on `7d58986095c4df6a425dc9cfd8298851eee86c17` (GitHub PR **#84**,
Roadmap PR19A1, Schema / Session / Source Foundation), which is based on
`38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7` (GitHub PR #83, the
architecture-approved PR19A design, itself based on `729d1aa...` below).
**All three of PR19A's implementation slices — PR19A1, PR19A2, PR19A3 —
are now merged. Roadmap PR19A (Legacy Import Foundation, backend) is now
fully complete.** This is the backend import framework only: enforced
PostgreSQL read-only dry-run, single-winner execute admission with
idempotent state-based replay, one shared lease/heartbeat/fencing
implementation used by validate/dry-run/execute (design §25), crash
recovery reuse, and 180-day retention cleanup with `SELECT ... FOR UPDATE
SKIP LOCKED` concurrency safety. **No concrete legacy dataset import is
implemented by PR19A itself** — per
`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §26 (Non-Goals), true
then and now for PR19A's own scope. **Equipment Master import has since
been separately implemented and completed by Roadmap PR20 (see the PR20
note below); only Receive History and Issue History import remain future
Roadmap PR21 scope.**
**Update (2026-08-11, this same historical paragraph): PR19B has since
merged too** as GitHub PR #80, real squash SHA `04f5bf5c...` — historical
and intermediate as of this later governance sync, itself since
superseded by `2743af8...` (PR20F), then `d64d50d...` (PR21E; see "PR21
note" below), and now by the current baseline at the top of this
section — Roadmap PR19 as a whole is now fully complete;
see `docs/DECISION_LOG.md` for the closure record. GitHub
PR #81 (an earlier,
unsplit PR19A design/implementation candidate) was closed without merging
on 2026-08-03, superseded by the PR19A1/PR19A2/PR19A3 sequence actually
merged as PR #84/#85/#86. See `docs/DECISION_LOG.md` ("Roadmap PR19A
complete: PR19A1 + PR19A2 + PR19A3 merged") for the full slice-by-slice
implementation and review chronology, including each slice's independent
Codex review rounds.

**Historical — superseded by `04f5bf5c...` (PR19B), reached via the
intermediate historical paragraph immediately above (`7f13a1e...`, itself
also superseded, not current) — `04f5bf5c...` is in turn superseded by
`2743af8...` (PR20F), then `d64d50d...` (PR21E), and now the current
baseline at the top of this section —
retained as provenance for Roadmap PR18 and earlier:**
`729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` — squash commit of GitHub PR #79,
the documentation-only PR18F governance synchronization recording Roadmap
PR18's completion. It is based on `5d8cf7d8f378f6231d43e330310f664f6c19560f`
(GitHub PR #78, the Roadmap PR18E Excel `.xlsx` export implementation) and
the PR18A–PR18D chain described in the paragraph immediately below.
**Roadmap PR18 (PR18A design, PR18B backend foundation, PR18C Browser
Print, PR18D backend PDF export, and PR18E Excel `.xlsx` export) is fully
complete.** The next planned item is Roadmap PR19, approved
(`docs/DECISION_LOG.md`, 2026-08-03 entry) as an independent-scope
**PR19A** (backend) / **PR19B** (frontend skeleton) split — see "Approved
forward sequence" below. PR19B is Draft PR #80
(`feature/pr19b-import-frontend-skeleton`), branched from this baseline
(`729d1aa...`) — **historical statement, as this paragraph was originally
written; PR19B has since merged (real squash SHA `04f5bf5c...`,
now itself historical) and Roadmap PR19, PR20, and PR21 are all now fully
complete — `d64d50d...` (PR21E) was that completion's own baseline, now
itself historical; see the current baseline at the top of this
section.** PR19A's architecture design has since merged as GitHub PR
**#83** (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`, squash SHA
`38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`, branched directly from
`729d1aa...` in parallel, not stacked on this or any other PR19 branch);
its runtime implementation slices (PR19A1/PR19A2/PR19A3, design §25) are
in progress: **PR19A1** (schema, session/source lifecycle, CAS) is Draft PR
**#84** (`feature/pr19a1-legacy-import-schema`, based on PR #83's squash
SHA), open and not merged; **PR19A2** and **PR19A3** have not started. The
base branch's actual current tip is `38a21e8...`.

**Historical — superseded by the paragraph above (`729d1aa...`, itself
also historical), which chains up through the intermediate historical
baselines `7f13a1e...` and `04f5bf5c...` to `2743af8...` (PR20F), then
`d64d50d...` (PR21E), and now the current baseline at the top of this
section — none of `729d1aa...`, `7f13a1e...`, `04f5bf5c...`,
`2743af8...`, `d64d50d...`, or this entry's `5d8cf7d...` is current —
retained as provenance for Roadmap PR18E and earlier:**
`5d8cf7d8f378f6231d43e330310f664f6c19560f` — squash commit of GitHub PR
#78, the Roadmap PR18E Excel `.xlsx` export implementation. It is based on
`bc274e6176f225518db4ebaf0b5ed643c653aaa7` (GitHub PR #77, the Roadmap PR18D
backend PDF export implementation), which is based on `beedc4d32c8d3ae6b6a418f36aa49b3177209b3f`
(GitHub PR #76, the documentation-only governance sync recording Roadmap
PR18C's completion), which is based on `e919a2af8cc7ca11ab72bee274cb70e76c27ce8a`
(GitHub PR #75, the Roadmap PR18C Browser Print implementation), which is based
on `4da1ebc016d48b2dece9362e029ecd15eb9dd31b` (GitHub PR #74, the
documentation-only governance sync recording Roadmap PR18B's completion),
which is based on `c72929b` (GitHub PR #73, the PR18B backend export
foundation), which follows `e1b358a` (GitHub PR #72, the post-PR18A
governance synchronization) and `6ba2c66` (GitHub PR #71, the approved
PR18A printing/export architecture design). **Roadmap PR18 (PR18A design,
PR18B backend foundation, PR18C Browser Print, PR18D backend PDF export, and
PR18E Excel `.xlsx` export) is now fully complete.** The next planned item
is Roadmap PR19.

The older baseline narrative immediately below is retained as provenance
for PR16 and earlier.

`ac19505` — squash commit of GitHub PR #61,
the Roadmap PR16 Slice 4 implementation (frontend `business_date_from`/
`business_date_to`/`shift`/`event` filter controls on `EquipmentDetailPage.tsx`,
plus the PR61-H1 merge-blocking review fix — the "ทั้งหมด" (All) `event`
option no longer silently defaults to `dispatch`). It is based on `6a28d73`
(GitHub PR #60, Slice 3 — `GET /transactions` `business_date_from`/
`business_date_to`/`shift`/`event` filter extension), which is based on
`bd4a02b` (GitHub PR #59, Slice 2 — `BorrowTransaction` computed
business-date/shift properties and `TransactionOut` schema fields), which is
based on `e8ef4da` (GitHub PR #58, Slice 1 — `backend/app/core/reporting_time.py`
derivation foundation), which is based on `5ace425` (GitHub PR #57, Roadmap
PR16 Owner Decision #1 — the confirmed Day/Night shift boundary policy),
which is based on `3e8d015` (GitHub PR #56, the architecture-approved PR16
design, `docs/design/PR16_REPORTING_FOUNDATION_PLAN.md`), which is based on
`6f66d76` (GitHub PR #54, the Roadmap PR15B Schema Hygiene implementation).
**All four Roadmap PR16 Implementation Slices are now complete — Roadmap
PR16 (Reporting Foundation) is fully complete.** See the PR16 note below.
The older baseline narrative immediately below is retained as provenance
for PR15B/PR15A.

`6f66d76` — squash commit of GitHub PR #54,
the Roadmap PR15B Schema Hygiene implementation (migrations `0012`-`0014`:
timezone conversion, FK `ON DELETE RESTRICT`, index/constraint naming
convergence). It is based on `6a84514` (GitHub PR #53, a documentation audit
and Roadmap consistency pass), which is based on `4b0d422` (GitHub PR #52,
the approved Roadmap PR15B Schema Hygiene design,
`docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md`), which is based on `fa570da`, the
post-PR15A governance sync, and `e250638`, the PR15A implementation. **Both
of Roadmap PR15's scheduled slices (PR15A Observability, PR15B Schema
Hygiene) are now complete.** The older baseline narrative immediately below
is retained as provenance for PR15A.

`e250638db186f8e4dc3358bd475e9cf4eebc0bc8` — squash commit of GitHub PR #50 (Roadmap PR15, PR15A slice — Observability: structured JSON logging, async-safe request/job correlation IDs, one-per-request access-log event with route templates, fail-closed `safe_log()` post-success logging; see the Completed table below and the PR15 note), on branch `claude/medical-equipment-pool-0c7fz0`. This sits on top of `a43b680a5558aa322a613b3e3eba0eeb45858edf` (documentation-only post-merge governance sync recording Roadmap PR14B's completion, GitHub PR #49 — this is the actual PR15A base, correcting a prior PR49 self-reference gap; see the PR15 note), which sits on top of `82e289d40811b413659e7303a1690b66275e9759` (squash commit of GitHub PR #48, Roadmap PR14, PR14B slice — Pagination Performance: evidence-gated composite ordering indexes, fail-closed PostgreSQL catalog verification for `CREATE INDEX CONCURRENTLY`), which sits on top of `4d891ac8f9f1cc1ada45347d384d06fde705a97a` (documentation-only post-merge governance sync recording Roadmap PR14A's completion, GitHub PR #47), which sits on top of `ddd17b180c06a4fd2421f4886c0568876498abb2` (squash commit of GitHub PR #46, Roadmap PR14, PR14A slice — Reliability Correctness: PATCH nullable-field correctness, scheduler N+1 fix, transaction boundary audit), which sits on top of `8f7ef12e1660b35021df64fc9a529495cca77e49` (squash commit of GitHub PR #45, Roadmap PR13, Search, History, and Reporting Adjustments). **Roadmap PR8 (all three slices), Roadmap PR9 (both slices — PR9A, PR9B), Roadmap PR10, Roadmap PR11, Roadmap PR12, Roadmap PR13, and Roadmap PR14 (both slices — PR14A, PR14B) are now fully complete. Roadmap PR15 (Observability and Schema Hygiene) is an Epic split into focused slices (see the PR15 note): both scheduled slices — PR15A (Observability) and PR15B (Schema Hygiene) — are now merged. Application metrics, tracing, dashboards, log aggregation, and alerting are not scheduled to any PR15 slice and remain open Roadmap PR15 scope, pending a future slice or an explicit governance decision to remove them — Roadmap PR15 is NOT fully complete even with both scheduled slices merged (see the PR15 note). The next planned item is Roadmap PR16 (Reporting Foundation).**

## Numbering note

**Roadmap PR number** (this file, `docs/audits/04-consolidated-implementation-plan.md`) and **GitHub PR number** (this repository's PR counter) are different sequences — see `docs/DECISION_LOG.md`'s "Numbering note" for the full explanation and a worked example. This file uses Roadmap PR numbers except where a row is explicitly infrastructure/governance work that was never assigned one.

## Completed

| Roadmap PR | Title | GitHub PR | Squash SHA |
|---|---|---|---|
| PR1 | Production Security and Availability Foundation | #2 | `25b460d` |
| PR2 | Structured Exception Handling | #5 | `14b4174` |
| PR3 | Audit Logging Framework | (merged via feature/pr3-audit-logging) | `0f2ef51` |
| PR4 | Transaction-Number Generation (global PostgreSQL sequence) | #13 | `7bcaa4a` |
| — (governance) | Knowledge Layer v2 — identifier/QR architecture and authority hierarchy | #15 | `89b1f1e` |
| PR5 | Equipment Master identifier model, BCM manual search, hospital Item-No QR identification | #14 | `099f0b8` |
| PR6 | Equipment State Model Migration (4 states) | #16 | `9994c27` |
| — (infrastructure) | GitHub Actions CI and AI review workflow | #17 | `3a1d30b` |
| — (governance) | Knowledge & Governance Foundation | #18 | `f4146b3` |
| PR7 (7a slice) | Transaction lifecycle model (OPEN/CLOSED) | #19 | `4041cd2` |
| PR7 (7b slice) | Transaction fields: dispatch type, routine round, required ward_id, borrower_name/due_at/quantity write-path removal | #20 | `d0e888f` |
| — (governance) | Post-merge governance sync after Roadmap PR7b (GitHub PR #20) | #21 | `0ed6598` |
| — (infrastructure) | Test Infrastructure Cleanup — consolidated duplicated test helpers into `tests/conftest.py`, no behavior change | #22 | `06a736c` |
| — (documentation) | Developer Documentation (`docs/development/`: SETUP, TESTING, MIGRATIONS, CODE_REVIEW, CONTRIBUTING) | #23 | `2e403fb` |
| — (documentation) | API & Error Catalog (`docs/api/`: ERROR_CODES, dispatch, receipt, equipment, transactions) | #24 | `f6f7c2a` |
| — (governance) | Post-merge governance sync after PR21-PR24 | #25 | `a308515` |
| PR8 (PR8A slice) | Atomic receipt concurrency guard — PostgreSQL conditional `UPDATE` + affected-rowcount winner guard | #26 | `4820dba` |
| PR8 (PR8B slice, backend) | Receipt outcome contract narrowing — `receipt_outcome` (`usable`/`defective`) replaces `condition` | #28 | `da4d76a` |
| PR8 (PR8B slice, frontend) | Frontend adoption of `receipt_outcome`; deployed together with the backend slice above | #29 | `d3e027b` |
| — (documentation) | Post-merge documentation sync after Roadmap PR8B (TD-006 closed, ADR-006/DECISION_LOG/ROADMAP updated) | #30 | `4af6a4c` |
| PR8 (PR8C slice) | Race-loss-vs-genuine-repeat receipt rejection — distinguishable `TRANSACTION_ALREADY_RETURNED`/`RECEIPT_RACE_LOST` codes, both HTTP 409 | #31 | `f923f0a` |
| — (documentation) | Documentation-only follow-up recording Roadmap PR8's completion (PR8A/PR8B/PR8C) | #32 | `94a14b8` |
| PR9 (PR9A slice) | Audited ward correction (backend) — `POST /transactions/{id}/correct-ward`, temporarily Administrator-only | #33 | `9cef841` |
| PR9 (PR9B slice) | Frontend audited ward correction for OPEN/CLOSED transaction records | #34 | `bfe8a42` |
| — (governance) | Post-merge governance sync after Roadmap PR9 | #35 | `bc1b163` |
| PR10 | Role Model Consolidation — legacy 5-role model replaced by the confirmed 3-role model (`administrator`, `equipment_pool_staff`, `read_only`) | #36 | `53340f6` |
| — (governance) | Post-merge governance sync after Roadmap PR10 | #37 | `66bdd54` |
| PR11 | Frontend Terminology and Workflow UI Pass — retired "ยืม"/"คืน" (borrow/return) UI terminology, converged on "เบิก"/"รับคืน" (issue/receive back) | #38 | `7708190` |
| — (governance) | Post-merge governance sync after Roadmap PR11 | #39 | `2944210` |
| — (governance) | Governance — classified GitHub PR #40 as an unnumbered Post-PR11 Frontend Dashboard UX Follow-up (not Roadmap PR12) | #41 | `9de050c` |
| — (frontend) | Dashboard & Equipment Status — operational lifecycle-status counts, permission-gated quick actions, loading/empty/error states, `/scan` quick-lookup destination; unnumbered, not Roadmap PR12 | #40 | `93b6f94` |
| PR12 | Inventory Import (update-only) — Administrator-only upload → preview → commit workflow, matching rows to existing equipment by canonical BCM Code | #43 | `94554a3` |
| PR13 | Search, History, and Reporting Adjustments — dispatch-type/round/date-range history filters, dashboard `pm_due_soon`/`cal_due_soon` removal, read-only "days since dispatch" indicator | #45 | `8f7ef12` |
| PR14 (PR14A slice) | Reliability Correctness — PATCH nullable-field correctness (two-pass validate-then-mutate, identity-field null rejection), scheduler N+1 fix, transaction boundary audit | #46 | `ddd17b1` |
| — (governance) | Post-merge governance sync after Roadmap PR14A | #47 | `4d891ac` |
| PR14 (PR14B slice) | Pagination Performance — evidence-gated composite `(created_at DESC, id DESC)` ordering indexes on `equipment`/`borrow_transactions`, fail-closed PostgreSQL catalog verification for `CREATE INDEX CONCURRENTLY` | #48 | `82e289d` |
| — (governance) | Post-merge governance sync after Roadmap PR14B | #49 | `a43b680` |
| PR15 (PR15A slice) | Observability — structured JSON logging, async-safe request/job correlation IDs (`contextvars`), one-per-request access-log event with route templates, background-job run IDs, aggregate import-commit logging, fail-safe (`safe_log()`) post-success logging | #50 | `e250638` |
| — (governance) | Documentation audit and Roadmap consistency pass | #53 | `6a84514` |
| PR15 (PR15B slice) | Schema Hygiene — timezone conversion to `timestamptz` (5 columns), explicit FK `ON DELETE RESTRICT` (all 25 relationships), index/unique-constraint naming convergence onto `ix_`/`uq_` (12 renames) | #54 | `6f66d76` |
| PR16 (Slice 1) | Reporting Foundation — `business_date`/`shift` derivation (`backend/app/core/reporting_time.py`) | #58 | `e8ef4da` |
| PR16 (Slice 2) | Reporting Foundation — `BorrowTransaction` computed business-date/shift properties, `TransactionOut` schema fields | #59 | `bd4a02b` |
| PR16 (Slice 3) | Reporting Foundation — `GET /transactions` `business_date_from`/`business_date_to`/`shift`/`event` filter extension | #60 | `6a28d73` |
| PR16 (Slice 4) | Reporting Foundation — frontend `business_date_from`/`business_date_to`/`shift`/`event` filter controls (`EquipmentDetailPage.tsx`), incl. PR61-H1 review fix | #61 | `ac19505` |
| — (governance) | Post-merge governance sync after Roadmap PR16 | #62 | `a572a7a` |
| — (design) | Roadmap PR17 — Operational Reports Foundation design (`docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md`) | #63 | `b935ac2` |
| — (governance) | Engineering Workflow and review governance (`docs/ENGINEERING_WORKFLOW.md`) | #64 | `ed8530e` |
| PR17 (Slice 1) | Operational Reports — report domain and query foundation (`equipment_category_id`/`operator_id`/`require_receipt` filters on `transaction_crud.search()`) | #65 | `ddb9733` |
| PR17 (Slice 2) | Operational Reports — `GET /reports/receive`, `GET /reports/issue`, `GET /report-options/operators`; `ReportTransactionOut` schema | #66 | `aeafb81` |
| PR17 (Slice 3) | Operational Reports — frontend Receive and Issue report screens, URL-state-backed filters | #67 | `8a1a280` |
| PR17 (Slice 4) | Operational Reports — Equipment Verify Checklist (`GET /reports/equipment-verify-checklist`), per Owner Decision #1 resolved to interpretation A; incl. incremental fix round (Owner Decision #1 documentation consistency, malformed-cursor handling) | #68 | `d4aaf0f` |
| — (governance) | Post-merge governance sync recording Roadmap PR17 complete and PR18 next | #69 | `9b2fc1a` |
| — (maintenance) | Operator-options cursor hygiene — reject a well-formed cursor envelope with a non-UUID id as `400 INVALID_INPUT` | #70 | `bc9e43b` |
| PR18A (design) | Printing and Export Architecture — approved design for Browser Print, PDF export, and Excel `.xlsx` export; no runtime implementation | #71 | `6ba2c66` |
| — (governance) | Post-merge governance sync after Roadmap PR18A | #72 | `e1b358a` |
| PR18B | Backend Export Foundation — output-neutral export document model, bounded builders for all three PR17 reports, and internal `GET /reports/{report_id}/print-data` endpoint | #73 | `c72929b` |
| — (governance) | Post-merge governance sync after Roadmap PR18B | #74 | `4da1ebc` |
| PR18C | Browser Print — dedicated Thai-first print presentation for Receive, Issue, and Equipment Verify Checklist over the PR18B export foundation | #75 | `e919a2a` |
| — (governance) | Post-merge governance sync after Roadmap PR18C | #76 | `beedc4d` |
| PR18D | Backend PDF Export — WeasyPrint-based server-rendered PDF for Receive, Issue, and Equipment Verify Checklist, embedded backend Thai font assets, bounded concurrency/admission control | #77 | `bc274e6` |
| PR18E | Excel `.xlsx` Export — openpyxl-based server-generated workbook for the same three reports, workbook-wide formula-injection protection, bounded concurrency/admission control | #78 | `5d8cf7d` |
| — (governance) | Post-merge governance sync recording Roadmap PR18 complete and PR19 next (PR18F) | #79 | `729d1aa` |
| PR19A (design) | Legacy Import Foundation — architecture-approved design (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`), no runtime implementation | #83 | `38a21e8` |
| PR19A1 | Legacy Import Foundation — Schema / Session / Source Foundation (`import_sessions`/`import_sources`/`import_jobs`/`import_row_errors`, migration `0015_import_foundation`) | #84 | `7d58986` |
| PR19A2 | Legacy Import Foundation — Validation Foundation (lease/heartbeat/completion-fencing mechanism, wired into `VALIDATING`) | #85 | `7e5e6f2` |
| PR19A3 | Legacy Import Foundation — Dry-run, Execution, Recovery, Retention (enforced read-only dry-run, single-winner execute, 180-day retention cleanup) | #86 | `7f13a1e` |
| — (governance) | Post-merge governance sync recording Roadmap PR19A foundation completion | #87 | `bc4d490` |
| PR19B | Legacy Import Frontend Skeleton — reviewable, mock-backed workflow prototype (session list/create/validation summary/dry-run/result screens), reconciled against PR19A's merged contract; no file upload, parsing, or real import execution | #80 | `04f5bf5` |
| — (governance) | Post-merge governance sync recording Roadmap PR19 complete and PR20 next | #88 | `e3156bf` |
| — (design) | Roadmap PR20 — Equipment Master Import design (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`), no runtime implementation | #89 | `9c2342a` |
| PR20A | Equipment Master Import — source artifact infrastructure (`import_source_blobs`, migration `0016`, server-authoritative checksum/byte-size upload, `VerifiedSourceContent`, `AdapterInvocationContext`) | #90 | `1de3db1` |
| PR20B | Equipment Master Import — `Equipment.version` optimistic-concurrency column (migration `0017`), incl. PR91-H1 fix (undeclared-field rejection, no-op-safe version increment) | #91 | `bd47701` |
| — (governance) | Roadmap PR20 Owner Decisions OD-1–OD-4 resolution (source schema, create/update field policy, identity policy, CREATE Asset Number policy) | #92 | `120319a` |
| PR20C | Equipment Master Import — parse/normalize/validate adapter (32-column mapping, BCM/Item No. normalization, OD-3 identity matrix, OD-4 fail-closed Asset Number policy, OOXML structural rejection) | #93 | `1d04672` |
| PR20D | Equipment Master Import — persisted, immutable `DryRunPlan` (migration `0018`), unified `IMPORT_DRY_RUN_PLAN_STALE` confirm contract, `ConfirmationResult`/`newly_confirmed` idempotent confirm | #94 | `c72baa1` |
| PR20E | Equipment Master Import — `execute()` (CREATE/UPDATE mutation of the exact confirmed `DryRunPlan`), global Job→Session→resource lock ordering, `resolved_resource_id` survival, UPDATE freshness-before-no-op | #95 | `698c34d` |
| PR20F | Equipment Master Import — frontend real API integration, replacing the PR19B mock workflow for this dataset type only | #96 | `2743af8` |
| — (governance) | Post-merge governance sync recording Roadmap PR20 complete and PR21 next | #97 | `4cab688` |
| — (design) | Roadmap PR21 — Legacy Receive and Issue History Import design and contract, Phase 1 (with two fix rounds folded into the same GitHub PR) | #98 | `5d4b1d3` |
| — (design) | Roadmap PR21 Source Evidence Update — OD-PR21-0 topology resolved against the real production workbook (with one fix round folded in) | #99 | `c2e125d` |
| — (infrastructure) | PR21-Foundation — internal dry-run-plan provider + fail-closed retention hook (generic plumbing only, no PR21 dataset schema) | #100 | `7b99e58` |
| — (governance) | Roadmap PR21 Owner Decision Closure Round 1 — OD-PR21-1/2/3/4/6 resolved, OD-PR21-5 partially resolved | #101 | `e221393` |
| — (governance) | Roadmap PR21 Owner Decision Closure Round 2 — event-first architecture adopted, OD-PR21-0's identity and pairing sub-components resolved | #102 | `42dd041` |
| PR21A | Legacy Receive and Issue History Import — Historical Event Schema / Provenance Foundation (`LegacyEquipmentEvent` and provenance tables) | #103 | `28f0f5e` |
| PR21B | Legacy Receive and Issue History Import — canonical Issue parser + validation | #104 | `a8ae9fb` |
| PR21C | Legacy Receive and Issue History Import — canonical Receive parser + validation | #105 | `651a387` |
| — (governance) | Roadmap PR21 Owner Decision Closure Round 3 — SDC excluded for V1 (OD-PR21-0 fully closed, all seven PR21 V1 Owner Decisions resolved), combined canonical adapter and PR21-specific upload admission authorized | #106 | `6ffb3df` |
| PR21D1 | Legacy Receive and Issue History Import — Combined Canonical Adapter + Source Admission | #107 | `50b9e77` |
| PR21D2 | Legacy Receive and Issue History Import — Historical Event Execution (`LegacyEquipmentEvent` INSERTs) | #108 | `c4788de` |
| PR21E0 | Legacy Receive and Issue History Import — Legacy Import Operator API Surface (migration-authority approval API, PR21-specific dry-run-plan/rows/confirm HTTP routes) | #109 | `78eeea7` |
| PR21E | Legacy Receive and Issue History Import — frontend real API integration, replacing the PR19B mock workflow for this dataset type | #110 | `d64d50d` |

Full rationale and review-fix history for PR5 through PR21E: `docs/DECISION_LOG.md`. PR22-PR25, PR30/PR32, PR35, PR37, PR47, PR49, PR53, PR62, PR64, PR72, PR74, PR76, PR79, PR87, PR88, and PR92 (GitHub PR numbers) are process/documentation-only additions with no code, business-rule, or schema change. PR8A/PR8B/PR8C/PR9A/PR9B/PR10/PR11/PR12/PR13/PR14A/PR14B/PR15A/PR15B/PR16 Slices 1-4/PR17 Slices 1-4/PR18B/PR18C/PR18D/PR18E/PR19A1/PR19A2/PR19A3/PR19B/PR20A/PR20B/PR20C/PR20D/PR20E/PR20F/PR21A/PR21B/PR21C/PR21D1/PR21D2/PR21E0/PR21E (GitHub PR #26, #28, #29, #31, #33, #34, #36, #38, #43, #45, #46, #48, #50, #54, #58, #59, #60, #61, #65, #66, #67, #68, #73, #75, #77, #78, #84, #85, #86, #80, #90, #91, #93, #94, #95, #96, #103, #104, #105, #107, #108, #109, #110) are production code changes. PR18A (GitHub PR #71), PR19A design (GitHub PR #83), PR20 design (GitHub PR #89), and PR21 design (GitHub PR #98, plus its Source Evidence Update GitHub PR #99) are approved design/documentation changes, not runtime implementation. PR10, PR11, PR12, PR13, PR14A, PR14B, PR15A, PR15B, PR16 Slices 1-4, PR17 Slices 1-4, PR18A, PR18B, PR18C, PR18D, PR18E, PR19A (design + A1/A2/A3), PR19B, PR20 (design + A/B/C/D/E/F), PR21 (design + Foundation/ODR1/ODR2/A/B/C/ODR3/D1/D2/E0/E), and both PR9 entries now have a `docs/DECISION_LOG.md` entry (see the PR9, PR10, PR11, PR12, PR13, PR14, PR15, PR16, PR17, PR18A, PR18B, PR18C, PR18D, PR18E, PR19, PR20, and PR21 notes below); PR21A/B/C's own detailed review chronology lives in their own GitHub PR descriptions (#103/#104/#105) rather than being duplicated into `docs/DECISION_LOG.md`, per that file's own PR21 entries.

**PR7 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR7 entry recommended splitting into a 7a (lifecycle model) and 7b (`dispatch_type`/`routine_round`/ward-required/field-cleanup) slice "if the reviewing team prefers smaller units." PR7 (7a slice) shipped `TransactionStatus` (`OPEN`/`CLOSED`), the `create()`/`close()` mutator split, `legacy_status` preservation, and disabling the deprecated `due_at`-driven overdue-notification scheduler job (Codex PR7a review round 1, BLOCKER — see `docs/DECISION_LOG.md`). PR7 (7b slice) completed PR7's remaining scope: `dispatch_type` (`routine_round`/`on_demand`), `routine_round` (the four confirmed fixed times), a required `ward_id` for every new dispatch (application-layer enforced), and removing `borrower_name`/`due_at`/`quantity` from the active write path while preserving every existing historical value as read-only history — plus, after Codex round 1 review, `BorrowRequest` now rejects unknown request fields outright, an invalid `ward_id` is classified as a distinct 400 `INVALID_INPUT` rather than the equipment-conflict 409, and the migration 0008 test suite was rewritten to exercise a genuinely reconstructed pre-migration production schema. Roadmap PR7 (both slices) is now fully merged. Concurrent-receipt protection (two simultaneous receipts racing on the same OPEN transaction) was **not** part of either slice — that gap is closed by Roadmap PR8A below.

**PR8 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's full PR8 entry ("Atomic Single-Operation Equipment Receipt with concurrency guard") was split into **three** slices during implementation planning (`docs/design/PR8_IMPLEMENTATION_PLAN.md`, design-only, uncommitted; the original PR7a/PR7b-style two-slice split was refined to three once PR8B's own scope proved to have two independent, separately-shippable halves — see the Codex review recorded in `docs/DECISION_LOG.md` "Roadmap PR8 (PR8B slice)"). **PR8A** (GitHub PR #26) is the database-level concurrency guard: `app.crud.transaction.close()` performs a single conditional `UPDATE ... WHERE id = :id AND status = 'open'`, deciding the winner by affected-row count, so exactly one concurrent receipt request succeeds and every loser rolls back before any business side effect — proven with deterministic PostgreSQL tests across a matrix of 1, 2, 5, 10, and 50 requests: the 1-request case verifies normal receipt behavior with no concurrency, the 2/5/10 cases synchronize the complete burst to force genuine contention, and the 50-request case synchronizes a bounded subset to prove conditional-`UPDATE` contention without exhausting the connection pool. No API contract, schema, or frontend change. **PR8B** (GitHub PR #28 backend + #29 frontend, deployed together) narrows the `condition` field to the confirmed binary `receipt_outcome` (`usable`/`defective`) contract, backend and frontend. `docs/TECH_DEBT.md` TD-006, which tracked the frontend/backend gap between the two PR8B slices, is `Closed`. **PR8C** (GitHub PR #31) distinguishes the two causes of a losing receipt request by machine-readable code — `TRANSACTION_ALREADY_RETURNED` (the transaction was already closed when the request evaluated current state) versus `RECEIPT_RACE_LOST` (the request observed an open transaction but lost the conditional-update race) — both still `409 Conflict`; `RECEIPT_RACE_LOST`'s wording deliberately attributes the outcome to another *request*, not another person, since the backend has no basis to identify who sent the winning request. The frontend branches on the response's `code` field, never on free-text `detail`. No lifecycle, schema, migration, or request-contract change; `receipt_outcome: "usable" | "defective"` is unchanged. PostgreSQL integration coverage verifies exactly one winner, documented 409 codes for every loser, and (via a synchronized barrier subset) that the conditional-update race is genuinely exercised, with zero silent test skips. **Roadmap PR8 (PR8A, PR8B, and PR8C) is now fully complete.** See `docs/DECISION_LOG.md` ("Roadmap PR8 (PR8A slice)", "Roadmap PR8 (PR8B slice)", "Roadmap PR8 (PR8C slice)").

**PR9 note:** `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §7 ("Ward Recording Rules") identified an unimplemented gap: no endpoint existed to correct a transaction's recorded destination ward, an audited correction of historical data — deliberately **not** ward-transfer or current-location tracking, which remains out of scope. Following the same lettered-slice precedent as PR7/PR8, this was split into two, both now merged: **PR9A** (backend, GitHub PR #33) added `POST /transactions/{id}/correct-ward` — a narrow, purpose-built action (never a generic transaction PATCH), a conditional-`UPDATE`-decided-by-affected-rowcount concurrency guard mirroring PR8A's shape, and exactly one audited entry per success, atomic with the ward change. Works identically for an `open` or `closed` transaction. Authorization was temporarily restricted to `admin` only (`app.api.v1.deps.WARD_CORRECTION_ROLES`) at the time PR9A merged — the then-current 5-role model had no confirmed, evidence-backed equivalent of the "Equipment Pool Staff" role (docs/audits/03-hospital-equipment-pool-workflow-audit.md §10). This temporary rule is superseded by Roadmap PR10's confirmed 3-role matrix (see the PR10 note below): ward correction is now available to `administrator` and `equipment_pool_staff`. **PR9B** (frontend, GitHub PR #34) added a minimal ward-correction dialog reachable from both the receipt screen (`ReturnPage.tsx`, an OPEN transaction) and equipment detail's transaction history (`EquipmentDetailPage.tsx`, OPEN or CLOSED, matching PR9A's own lack of a lifecycle-status precondition), correction actions always keyed by the transaction's actual UUID, mirroring the same temporary admin-only visibility as a usability-only gate (the backend remains authoritative). No lifecycle, schema, migration, or receipt/dispatch contract change in either slice. **Roadmap PR9 is fully complete.** See `docs/DECISION_LOG.md` ("Roadmap PR9 — Audited ward correction (PR9A/PR9B slices)").

**PR10 note:** `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §10 ("Role and Permission Review") recommended collapsing the legacy 5-role model (`admin`, `biomedical_engineer`, `ward_nurse`, `transport_staff`, `viewer`) to the confirmed 3-role model — `administrator`, `equipment_pool_staff`, `read_only` — everywhere a role is persisted, checked, displayed, or seeded. GitHub PR #36 implemented this: canonical backend role constants and centralized capability groups, a fail-closed `MEP_PR10_ROLE_MAPPING` manifest mechanism for any legacy role with no confirmed automatic equivalent, a `ck_roles_name_confirmed` CHECK constraint, and a closed 3-value `Role` type/capability layer on the frontend. Three iterative Codex review rounds, completed before PR #36 was squash merged, hardened the migration itself (`backend/alembic/versions/0009_role_consolidation.py`): atomic audit provenance for both upgrade and downgrade, fail-closed manifest validation restricted to genuinely ambiguous accounts, lossless downgrade restoring exact legacy role IDs/permissions/user assignments (via durable `role_migration_snapshots`/`user_role_migrations` provenance tables, not `legacy_role_name` alone), and confirmed-role ownership provenance (`confirmed_role_ownership`) so downgrade never deletes a pre-existing confirmed-role row. See `docs/BUSINESS_RULES.md` ("Roles and the confirmed 3-role permission matrix") for the full capability-by-capability matrix and `docs/DECISION_LOG.md` ("Roadmap PR10") for the full migration mechanism and design rationale. **Roadmap PR10 is now fully complete.** Ward correction's temporary Administrator-only rule (Roadmap PR9A) is superseded by the confirmed matrix (Administrator + Equipment Pool Staff) — see the updated PR9 note above.

**PR11 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's PR11 entry called for "the full user-facing terminology change and the new dispatch/receipt UI shape in one coordinated pass." GitHub PR #38 implemented this: "ยืม"/"คืน" (borrow/return) is retired everywhere it was visible in the UI — navigation, the dispatch (`BorrowPage.tsx`) and receipt (`ReturnPage.tsx`) forms, `EquipmentDetailPage.tsx`'s CTA buttons and transaction history, and the dashboard/reports chart labels — replaced consistently by "เบิก"/"รับคืน" (issue/receive back). The ward field (dispatch form, receipt form, and equipment-detail transaction history) is relabeled "หอผู้ป่วยที่รับเครื่อง (บันทึก ณ วันที่เบิก)" with a caption disclaiming real-time location tracking, satisfying the Workflow Audit §7.1 acceptance criterion. Three independent Codex reviews on Draft PR #38, each on a new exact head before PR #38 was squash merged, hardened the required test coverage: **Review `4781057781`** (finding PR11-M1) found no `BorrowPage` component tests existed at all, and no test exercised the dispatch → receipt workflow — fixed by adding `BorrowPage.test.tsx` (dispatch-form component tests: terminology, ward label/disclaimer, on-demand/routine_round payloads, validation gating, loading/empty states, API error states) and a `DispatchReceiptWorkflow.test.tsx` end-to-end test. **Review `4781138180`** (findings PR11-M1R and PR11-M2) required that workflow test be rewritten around one shared, mutable mock store so the equipment-status transitions it asserts (available → issued → available) are actually caused by the mocked `createBorrow`/`createReturn` implementations rather than hand-fed per step, and required the PR description be refreshed to match the final diff. **Review `4781151810`** recorded APPROVE with no remaining findings. No backend, API, database, migration, RBAC, or business-rule change — this PR is frontend-only, exactly as scoped; internal route paths (`/borrow`, `/return`) and service/function names (`createBorrow`, `listActiveBorrows`, etc.) were intentionally left unchanged. See `docs/DECISION_LOG.md` ("Roadmap PR11") for full detail. **Roadmap PR11 is now fully complete.**

**PR12 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D/F's PR12 entry called for the confirmed inventory import workflow: upload → preview (zero database writes) → commit, per-row validation and reporting, exactly one audit entry per batch. GitHub PR #43 implemented this, plus a migration (`0010_inventory_import_columns.py`) adding `equipment.asset_id` (nullable, non-unique index) and `equipment.raw_source_status` (nullable, verbatim source-cell text). Four independent Codex reviews on Draft PR #43, each on a new exact head before the PR was squash merged, drove the final shape: **Review `4781906397`** found the original design derived `asset_number` from BCM Code, violating ADR-002 ("Not merged with, or inferred from, BCM Code or Item No"), plus unbounded upload parsing, incomplete update-mode identity validation, missing preview-length validation, and no real PostgreSQL migration evidence (findings PR12-H1 through H4, PR12-M1). **Review `4781971425`** found a replacement random-placeholder `asset_number` policy was still fabricated inventory metadata (PR12-H1R), the round-1 migration tests failed on exact-head CI because migration `0001_initial.py` builds its schema from the current ORM model rather than genuine migration history (PR12-M1R), and compressed-XLSX decompression remained unbounded before `openpyxl` parsed it (PR12-H2R). Resolving PR12-H1R required a Repository-Owner architectural decision, since `equipment.asset_number` is `NOT NULL`/`UNIQUE` real hospital-assigned inventory metadata with no source column in the import file: **Roadmap PR12 shipped update-only** — import matches rows to existing equipment by canonical BCM Code and updates them; a row with no matching BCM Code fails validation, directing the operator to create the equipment through the standard Equipment Master workflow first, then re-import to update it. Create-from-import is deferred follow-up scope, not a permanent prohibition, pending a future ADR-governed design for real hospital Asset Number assignment. **Review `4782840059`** found the update-only cutover was not yet coherent everywhere — the authoritative spec still described a create/update path and an off-by-default update mode, the frontend still exposed an "update existing" checkbox capable of submitting `update_existing=false` (a request the backend accepted into a batch where nothing could ever succeed), and the `raw_source_status` audit column was being silently whitespace-stripped before persistence, contrary to its verbatim-preservation contract. Fixed: the backend now rejects an explicit `update_existing=false` immediately with a clear `400`; the frontend checkbox and all state driving it were removed (the service always sends `true`); the authoritative spec (`docs/audits/04-consolidated-implementation-plan.md` Part D and F.1/F.3/F.4/G.4) was updated to state the update-only contract explicitly; and a dedicated verbatim-text path was added for the Asset Status source cell, with a separately normalized copy used only for the status-mapping lookup. **Review `4782986913`** recorded APPROVE WITH NON-BLOCKING COMMENTS (two documentation/test-hardening follow-ups, tracked separately — see `docs/DECISION_LOG.md`). No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or existing API contracts (aside from `update_existing=false` now returning `400` instead of being silently accepted). See `docs/DECISION_LOG.md` ("Roadmap PR12") for full detail. **Roadmap PR12 is now fully complete.**

**PR13 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's PR13 entry called for finalizing BCM-Code-first search/scan priority (ADR-003), dispatch-type/round-aware history filtering, and removing MVP-irrelevant dashboard elements (PM/CAL widgets) in favor of a read-only "days since dispatch" indicator. GitHub PR #45 (branch `feature/pr13-search-history-reporting`, baseline the PR12 merge `94554a3`) implemented this: verified Roadmap PR5's `search_bcm` already fully satisfies every ADR-003 requirement with existing test coverage — no new search code needed; added `dispatch_type`/`routine_round`/`from_date`/`to_date` query-parameter filters to `GET /transactions`, combinable with the existing `ward_id`/`equipment_id`/`status` filters; removed `pm_due_soon`/`cal_due_soon` from the dashboard summary response (never rendered by `DashboardPage.tsx` since GitHub PR #40, so no active client was affected); and added dispatch-type/round distinguishability (Part H acceptance criterion) plus a read-only, client-computed "days since dispatch" indicator (OPEN transactions only) to `EquipmentDetailPage.tsx`'s transaction history. Two independent Codex reviews on Draft PR #45, each on a new exact head before the PR was squash merged: **Review `4783120601`** (finding **PR13-M1**) found the date-range upper-bound arithmetic (`to_date + timedelta(days=1)`) could raise `OverflowError` for `to_date=9999-12-31` (Python's `date.max`), a syntactically valid ISO date string a client can send — fixed by computing the bound as `datetime.combine(to_date, time.max)` instead of incrementing the date (always representable, never overflows), and by rejecting a reversed range (`from_date > to_date`) with a structured `400` at the API boundary before it reaches `search()`. **Review `4783200709`** recorded APPROVE WITH NON-BLOCKING COMMENTS (one non-blocking PR-description-metadata item, addressed before merge). No changes to any other Roadmap PR's scope, dispatch/receipt/ward-correction/status-transition logic, or the database schema. See `docs/DECISION_LOG.md` ("Roadmap PR13") for full detail. **Roadmap PR13 is now fully complete.**

**PR14 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's PR14 entry ("Reliability and Performance Hardening") is treated as an Epic implemented through multiple focused slices, following the same lettered-slice precedent as PR7/PR8/PR9, rather than one broad PR. **PR14A** (GitHub PR #46, branch `feature/pr14a-reliability-correctness`, baseline the PR13 merge `8f7ef12`) shipped exactly three reliability-correctness concerns, deliberately excluding pagination/indexing (deferred to PR14B, evidence-gated) and operational logging (deferred to Roadmap PR15): (1) PATCH nullable-field correctness (Backend Audit 4.1) — `app.crud.equipment.update()`/`app.crud.user.update()` rewritten from a single-pass `if value is not None: setattr(...)` loop (which silently discarded every explicit-null PATCH, on every field) to a two-pass validate-then-mutate: pass 1 rejects an explicit null on any required field (`equipment_name`; `full_name`, `is_active`) or non-clearable identity field (`bcm_code`/`item_no`, ADR-002 — non-clearable, not immutable; non-null updates are unaffected) with `400 INVALID_INPUT` and zero mutation/audit event, before pass 2 applies every remaining field unconditionally, so nullable business fields (`brand`, `model`, `pm_due_date`, `cal_due_date`, `category_id`, `department_owner_id`, `current_location_id`, `serial_number`, `phone`) can now genuinely be cleared; (2) the scheduler N+1 fix (Backend Audit 16.1) — `app.worker.scheduler.check_pm_cal_due()` now queries PM/CAL-due equipment first and, only if either set is non-empty, loads the notification recipient list exactly once and reuses it, instead of re-querying recipients once per due row; a run with nothing due now performs zero recipient queries; (3) a transaction boundary audit (Backend Audit 6.1/7.1, `docs/audits/05-pr14a-transaction-boundary-audit.md`) categorizing every commit site into ordinary request/business commits, the scheduler commit, the authentication-specific best-effort commit (including that a successful login's commit closes both the `last_login_at` update and its audit row together), and the seed/script commit — concluding no atomicity drift was found and the existing caller-owned commit architecture is intentionally left unchanged pending a separate architecture review, plus a corrected `get_db()` docstring stating only its actual rollback-on-close guarantee. One Codex review round on Draft PR #46: **the substantive review decision was REQUEST CHANGES** (findings: strengthen the `User.phone`-clearing regression test to prove persisted state rather than HTTP 200 alone; correct the transaction-boundary audit's swapped login-success/failure line references and add the `last_login_at` detail; add explicit API-behavior/data-impact/rollback-limitation sections to the PR description; rename `IMMUTABLE_IDENTITY_FIELDS` to `NON_CLEARABLE_IDENTITY_FIELDS` for accuracy) — all four addressed on a new exact head before merge; CI (141 tests, zero skips, including PostgreSQL) was green on that reviewed head. No workflow redesign, no ADR changes, no schema/migration change. See `docs/DECISION_LOG.md` ("Roadmap PR14 (PR14A slice)") for full detail. **PR14A is now fully complete.**

**PR14B** (GitHub PR #48, branch `feature/pr14b-pagination-ordering-indexes`, baseline the PR14A governance sync `4d891ac`) shipped the pagination-performance slice deferred by PR14A, gated on `EXPLAIN (ANALYZE, BUFFERS)` evidence of a real query-plan problem gathered *before* any index/migration code was written (`docs/audits/06-pr14b-pagination-index-evidence.md`, 200,000 `equipment`/1,000,000 `borrow_transactions` rows, realistic non-clustered timestamps): two composite `(created_at DESC, id DESC)` btree indexes (`ix_equipment_created_at_id`, `ix_borrow_transactions_created_at_id`) matching the literal `ORDER BY` clause `app.crud.equipment.search()`/`app.crud.transaction.search()` already issue for cursor pagination, dropping first-page query latency from 45-205ms (sequential scan + sort) to under 1ms (index scan, no sort node) at that evidence scale. Deliberately not declared on the SQLAlchemy models (TD-002 — migration `0001_initial.py` reflects current ORM state at run time, so an ORM-declared index would race the dedicated migration on a fresh install); migration `0011_pagination_ordering_indexes.py` is the sole source of truth for both indexes on every path. A measured, honestly-reported limitation is documented rather than hidden: very deep cursor pagination (~75,000-100,000+ rows past page one) gets *slower* with the index present, because the cursor `WHERE` clause's `OR`/`AND` shape isn't sargable against a plain composite index — accepted as unreachable at this system's confirmed real-world scale ("low hundreds of devices, thousands of transactions per year"), not fixed here (a pagination-logic redesign, explicitly out of scope). Two review rounds on Draft PR #48, each on a new exact head: **Round 1** was merge-blocking (`PR14B-H1`) — a bare `CREATE INDEX CONCURRENTLY IF NOT EXISTS` retry cannot distinguish a genuinely completed index from one left `INVALID` by an interrupted build (process killed, connection lost, deadlock), so a naive retry would let Alembic silently record success while the index stayed unusable; also required real PostgreSQL regression coverage for that failure mode (`PR14B-M1`) and a lock-semantics documentation correction — a plain `CREATE INDEX` takes a `SHARE` lock that blocks writes only, not reads (`PR14B-L1`). Fixed by adding `_ensure_index_concurrently()`, which inspects `pg_indexes.indexdef` and `pg_index.indisvalid`/`indisready` for any existing same-named index before treating it as done, and **fails closed** — raising a `RuntimeError` with the detected state and an explicit recovery step — rather than auto-repairing, per the Repository Owner's explicit direction (an automatic drop/rebuild could mask an underlying deployment problem; failing loudly lets an operator inspect and decide). **Round 2** recorded APPROVE WITH NON-BLOCKING COMMENT (`PR14B-L2`, a stale PR-description metadata correction, fixed before merge) — confirming the fail-closed catalog verification, regression coverage for the interrupted-build/recovery and mismatched-definition paths, and both equipment/transaction planner assertions were all in place. CI (617 tests: 467 non-PostgreSQL + 150 PostgreSQL) was green on the merged head. No API, pagination-logic, or `COUNT(*)` change. See `docs/DECISION_LOG.md` ("Roadmap PR14 (PR14B slice)") for full detail. **PR14B is now fully complete — Roadmap PR14 (both slices) is fully complete.** Roadmap PR15 (Observability and Schema Hygiene) is next — see the PR15 note below.

**PR15 note:** `docs/audits/04-consolidated-implementation-plan.md` Part D's PR15 entry ("Observability and Schema Hygiene," which also covers PR14's deferred Operational Logging scope item) is treated as an Epic implemented through multiple focused slices, following the same lettered-slice precedent as PR7/PR8/PR9/PR14, per the architecture-approved design revision (`docs/design/PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md`, Revision 2, uncommitted design doc). **PR15A** (GitHub PR #50, branch `feature/pr15a-observability`, baseline `a43b680a5558aa322a613b3e3eba0eeb45858edf` — the PR14B post-merge governance sync, GitHub PR #49) shipped exactly the observability slice: structured JSON logging (`app.core.logging.JsonFormatter`); async-safe request/correlation-ID propagation via `contextvars` and a `logging.Filter` (`app.core.log_context`), reusing the existing request-context mechanism rather than introducing a parallel one; exactly one bounded access-log event per request using the route *template* (not the raw URL, to keep log cardinality bounded); an independent `job_run_id` for scheduler runs (deliberately not the HTTP request-ID mechanism, since a background job is not a request); aggregate-only import-commit logging (row-count statistics, never filenames or cell contents); and `safe_log()`, a fail-safe wrapper guaranteeing that no logging call — including its own best-effort fallback report — can ever propagate an exception back into request, job, or import-commit handling, so observability can never influence a business outcome. Deliberately excludes schema migrations, timezone migrations, FK `ondelete` policy changes, CHECK constraints, index naming, and any application metrics/tracing/dashboards/log aggregation/alerting (all remain separate, ungoverned-by-this-change Roadmap PR15 scope — see below). Three independent Codex reviews on Draft PR #50, each on a new exact head before the PR was squash merged: **Review 1** (review ID `4787144983`, reviewed head `746732dc2d758286d4340cf4628327e1206b8329`, CI run `30267254839`, 5/5 jobs green) was REQUEST CHANGES with two merge-blocking findings — `PR15A-H1`, `configure_logging()` relied on `logging.basicConfig()`'s default idempotency, which is a silent no-op once the root logger already has any handler (e.g. Uvicorn configuring its own logging before importing the app), so the JSON formatter could silently never install depending on import order; and `PR15A-H2`, the new post-commit import-success log (and the access-log's fallback) could raise and turn an already-committed, successful outcome into an HTTP 500. **Review 2** (review ID `4788591587`, reviewed head `c32270e01073fb486066d5f95548282056f3b930`, CI run `30277548822`, 5/5 jobs green) was REQUEST CHANGES — `PR15A-H1` confirmed resolved (`configure_logging()` now explicitly clears existing root handlers before installing its own, deterministically, regardless of import order); `PR15A-H2R`, the *fallback* log call inside the round-1 fix's own try/except was itself still unguarded, so a broken logging subsystem could still raise past it, with the same gap in the access-log fallback and scheduler completion logging. **Review 3** (review ID `4789829543`, reviewed head `eeae67542d02e1dc266a15979c2b02857020f872`, CI run `30286421490`, 5/5 jobs — Backend tests non-PostgreSQL, Backend tests PostgreSQL, Alembic migration upgrade validation, Frontend build, `git diff --check` — all green) recorded **APPROVE WITH NON-BLOCKING COMMENTS** — `PR15A-H2R` confirmed resolved by `safe_log()` (a helper guaranteeing neither the primary log call nor its own fallback report can ever escape), applied to access logging, scheduler success/failure logging, and import success/failure logging, independently verified by 24/24 passing tests in `backend/tests/test_observability_logging.py` at this exact head; `PR15A-M1` (non-blocking) — the four exception-handler log lines in `app/main.py` still log the raw request path rather than the route template — accepted as a deferred, explicitly tracked follow-up, not a merge blocker. No schema or migration change. **No breaking API changes:** the implementation adds backward-compatible response headers only (`X-Request-ID`, `X-Correlation-ID`); existing clients continue to function without modification, and business semantics, response bodies, and status codes remain unchanged. See `docs/DECISION_LOG.md` ("Roadmap PR15 (PR15A slice) — Observability") for the full three-round review chronology. **PR15A is now fully complete.**

**PR15B** (GitHub PR #54, branch `feature/pr15b-schema-hygiene`, baseline `6a845140832b6269c8d7d0177c78fc00cb828f26` — a documentation audit and Roadmap consistency pass, GitHub PR #53) shipped the schema-hygiene slice per the architecture-approved design (`docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md`, GitHub PR #52): migration `0012_timezone_conversion.py` converts five naive `timestamp` columns to `timestamptz` via `AT TIME ZONE 'UTC'` (`borrow_transactions.due_at` deliberately excluded — client-supplied historical values with no UTC provenance); migration `0013_fk_ondelete_policy.py` makes `ON DELETE RESTRICT` explicit on all 25 foreign keys (zero observable behavior change — the only `DELETE` endpoint is already a soft delete); migration `0014_index_naming_convergence.py` renames 5 hand-named `idx_`-prefixed indexes and 7 auto-named unique constraints onto the `ix_`/`uq_` convention. All three are paired with the ORM-side companion changes the design requires (`UTCDateTime`, `ondelete="RESTRICT"` on all 25 `ForeignKey()`s, explicit `UniqueConstraint(name=...)`) so a fresh install and a historical upgrade converge on the identical schema. An independent design-compliance review, conducted before this branch's Pull Request was opened, verified the design's binding invariant — every migration execution path (upgrade, downgrade, verify-and-no-op, legacy-name, target-name) must use full semantic catalog-state verification through one shared helper, never a partial check — and raised three findings, all resolved before merge: **H1**, migration `0014` originally verified only partial metadata on some paths rather than the full semantic-definition-plus-health check, fixed by introducing the single shared `_classify_rename()` helper used by all four call sites; **H2**, migration `0013`'s downgrade originally verified only `confdeltype` rather than the same full-definition check its upgrade path used, fixed by introducing the single shared `_classify_fk()` helper used by both directions; **H3**, migration `0014`'s constraint verifier originally collapsed a genuinely PARTIAL catalog state (only an index, or only a unique constraint, existing under a name) into ABSENT, fixed by introducing an explicit `_CatalogState` (ABSENT/COMPLETE/PARTIAL) model checked before any other outcome. Regression tests for all three findings (interrupted/unhealthy index builds, mismatched FK/constraint semantics, both-names-present, and each PARTIAL-catalog-state combination under both upgrade and downgrade) are in `backend/tests/test_postgres_integration.py`. `app/models/mixins.py`'s `UTCDateTime` also gained a write-side fail-closed invariant: a non-UTC aware datetime is now rejected outright rather than silently normalized. See `docs/DECISION_LOG.md` ("Roadmap PR15 (PR15B slice) — Schema Hygiene") for full detail. **PR15B is now fully complete — both of Roadmap PR15's scheduled slices are complete. Roadmap PR15 (the Epic) is NOT fully complete** — application metrics, tracing, dashboards, log aggregation, and alerting are not scheduled to any PR15 slice and remain open Roadmap PR15 scope, pending a future slice or an explicit governance decision to remove them.

**PR16 note:** Roadmap PR16 (Reporting Foundation) shipped across four Implementation Slices per the architecture-approved design (`docs/design/PR16_REPORTING_FOUNDATION_PLAN.md`, GitHub PR #56) and the Repository Owner's confirmed Day/Night shift boundary policy (Owner Decision #1, GitHub PR #57: 08:00/20:00 Asia/Bangkok, `business_date_anchor = shift_start_date`, `on_demand` classified identically to a routine-round dispatch). **Slice 1** (GitHub PR #58) added `business_date`/`shift` derivation as one pure-Python reference function and one SQLAlchemy-expression twin, tested against each other so they can never silently diverge; both are computed, never persisted. **Slice 2** (GitHub PR #59) added `BorrowTransaction` computed properties (`dispatch_business_date`/`dispatch_shift` from `borrowed_at`; `receipt_business_date`/`receipt_shift` from `returned_at`, `None` until received) and surfaced them on `TransactionOut`. **Slice 3** (GitHub PR #60) added `business_date_from`/`business_date_to`/`shift`/`event` (`dispatch`/`receipt`, default `dispatch`) query parameters to `GET /transactions`, filtering against the derived value directly and leaving the existing `from_date`/`to_date` raw-timestamp filters untouched; one Codex review round recorded APPROVE with no findings. **Slice 4** (GitHub PR #61) added matching frontend filter controls to `EquipmentDetailPage.tsx` — Apply/Clear-committed, URL-state-backed, with loading/empty/backend-validation-error states — plus a merge-blocking review fix (**PR61-H1**): since the backend's `event` parameter has no "all events" value (confirmed directly against both the design and the merged code, not assumed), the UI's "ทั้งหมด" (All) option now never sends `business_date_from`/`business_date_to`/`shift` on the wire, the only way "All" can honestly mean "all events" without a backend contract change or client-side dispatch/receipt merging (both out of scope); the three dependent controls are disabled until a concrete event is chosen, gated by a single authoritative check applied at request-build time so it also holds for a stale or hand-edited URL. See `docs/DECISION_LOG.md` ("Roadmap PR16 — Reporting Foundation Complete") for the full slice-by-slice implementation and review chronology. **Roadmap PR16 (Reporting Foundation) is now fully complete.** The next planned item is Roadmap PR17 (Date/shift-filtered Receive, Issue, and Equipment Verify Checklist reports).

**PR17 note:** Roadmap PR17 (Operational Reports) shipped across four Implementation Slices, per the architecture-approved design (`docs/design/PR17_OPERATIONAL_REPORTS_PLAN.md`, GitHub PR #63) and the Repository Owner's confirmed Equipment Verify Checklist definition (Owner Decision #1: Option A — a read-only, current-state Equipment master-data snapshot, no physical-verification workflow). **Slice 1** (GitHub PR #65) added the report domain and query foundation — `equipment_category_id`/`operator_id` filters and the `require_receipt` unconditional predicate on `transaction_crud.search()`, plus the confirmed backend-only deterministic ordering for the Issue Report. **Slice 2** (GitHub PR #66) added `GET /reports/receive`, `GET /reports/issue`, and the bounded historical-operator lookup `GET /report-options/operators`, backed by a dedicated report-only `ReportTransactionOut` schema kept off the shared `TransactionOut` contract. **Slice 3** (GitHub PR #67) added the Thai-first `/reports/receive` and `/reports/issue` frontend screens, URL-state-backed business-date/shift/ward/category/operator filters. **Slice 4** (GitHub PR #68) added `GET /reports/equipment-verify-checklist` and its frontend screen — a read-only listing of `Equipment` master records reusing the existing `EquipmentOut` response boundary (which excludes `item_no`, per ADR-002/ADR-003), per Owner Decision #1's resolution to interpretation A — plus an incremental fix round that recorded the Owner Decision in `docs/DECISION_LOG.md`, synchronized the design document's wording, and added structured malformed-cursor handling for the checklist endpoint by hardening the shared cursor-decoding layer (`app/utils/pagination.py`) for invalid Base64, malformed JSON/payloads, invalid timestamps, and missing required fields — those cases now return the repository-standard structured `400 INVALID_INPUT` client error instead of an uncaught `500` wherever the shared decoder is used. At the time of GitHub PR #68, a caller-specific `uuid.UUID(cursor_id)` parsing path in the existing `GET /report-options/operators` lookup (`app/crud/user.py::list_operators`) still ran unguarded after the shared decoder returned, so a structurally well-formed alpha cursor with a non-UUID id could still reach an uncaught exception there — this narrow, non-blocking cursor-hygiene gap was closed by a separate maintenance fix (`app/crud/user.py::list_operators` now validates the decoded UUID before any query executes, same convention as every other cursor-consuming endpoint). See `docs/DECISION_LOG.md` ("Roadmap PR17 — Owner Decision #1 (Equipment Verify Checklist Definition)" and "Roadmap PR17 — Operational Reports Complete") for the full slice-by-slice implementation and review chronology. **Roadmap PR17 (Operational Reports) is now fully complete.** No new equipment lifecycle state, no change to `TransactionOut`, no physical-verification workflow, and no database migration were introduced anywhere in Roadmap PR17. See the PR18A/PR18B note below for current PR18 status.

**PR18A/PR18B/PR18C note:** GitHub PR #71 merged the approved Roadmap PR18A design (`docs/design/PR18_PRINTING_EXPORT_PLAN.md`) for Browser Print, backend PDF export, and Excel `.xlsx` export over the PR17 reports. GitHub PR #73 then merged PR18B's shared, output-neutral backend export document model; stable report identities and metadata; deterministic typed columns/rows; centrally enforced schema invariants; bounded full-filtered dataset builders for Receive, Issue, and Equipment Verify Checklist; human-readable applied-filter metadata; report-specific filter applicability enforcement; and internal `GET /reports/{report_id}/print-data`. A documentation-only governance synchronization then recorded PR18B's completion as GitHub PR #74, squash SHA `4da1ebc016d48b2dece9362e029ecd15eb9dd31b`. GitHub PR #75 added the dedicated Thai-first Browser Print adapter for all three reports over that same foundation, with backend-controlled content/order/metadata, pagination keys removed from print requests, and fail-closed per-weight font readiness bound to the current document identity. Another documentation-only governance synchronization then recorded PR18C's completion as GitHub PR #76, squash SHA `beedc4d32c8d3ae6b6a418f36aa49b3177209b3f`. PR18B and PR18C introduced no migration or lifecycle change; neither did their governance-sync PRs (#74, #76).

**PR18D note:** Roadmap PR18D (backend PDF export, `GET /reports/{report_id}/pdf`) is merged, built from the PR18C governance-sync baseline (`beedc4d32c8d3ae6b6a418f36aa49b3177209b3f`, GitHub PR #76 — itself built directly on PR18C's own squash merge, `e919a2af8cc7ca11ab72bee274cb70e76c27ce8a`, GitHub PR #75). It reuses the PR18B `ExportDocument`/dataset builders unchanged (no second report/query engine), renders via WeasyPrint (BSD-3-Clause) with pdfplumber (MIT) as a test-only PDF parser, and uses the existing neutral branding fallback (design §16) — **Owner Decision #2 (branding configuration ownership) remains open and is not decided by PR18D.** Three Codex review rounds hardened bounded concurrency/timeout behavior (renderer-lifetime accounting, a total deadline covering queue wait) and completed the production Docker image smoke test before merge. See `docs/DECISION_LOG.md` ("Roadmap PR18D — Backend PDF Export") for the renderer/font engineering-comparison record and full review chronology. Merged as GitHub PR #77, squash SHA `bc274e6176f225518db4ebaf0b5ed643c653aaa7`.

**PR18E note:** Roadmap PR18E (backend Excel `.xlsx` export, `GET /reports/{report_id}/xlsx`) is merged, built from the PR18D baseline (`bc274e6176f225518db4ebaf0b5ed643c653aaa7`, GitHub PR #77). It reuses the PR18B `ExportDocument`/dataset builders unchanged, renders via `openpyxl` (already a vetted dependency — no new dependency added), and uses the same neutral branding fallback as PR18C/PR18D — **Owner Decision #2 remains open and is not decided by PR18E.** One Codex review round required workbook-wide formula-injection sanitization (a single centralized write helper, not only report rows) and Excel export admission control (reusing PR18D's bounded-semaphore/total-deadline model), both fixed before merge. See `docs/DECISION_LOG.md` ("Roadmap PR18E — Excel `.xlsx` Export") for the library comparison and full review chronology. Merged as GitHub PR #78, squash SHA `5d8cf7d8f378f6231d43e330310f664f6c19560f`. **With PR18B, PR18C, PR18D, and PR18E all merged, Roadmap PR18 (Printing and Export) is now fully complete** — see `docs/DECISION_LOG.md` ("Roadmap PR18 — Printing and Export Complete") for the final governance record.

**PR19 note:** Roadmap PR19 (Legacy Import Foundation) was delivered as an approved parallel split — **PR19A** (backend) and **PR19B** (frontend skeleton) — per `docs/DECISION_LOG.md` ("Roadmap PR19 approved split: PR19A (backend) / PR19B (frontend skeleton)"), an explicit Owner-approved exception since no PR19 design document existed at the time of approval. **PR19A's architecture design merged as GitHub PR #83** (squash SHA `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`), decomposing its own implementation into slices PR19A1 (GitHub PR #84, squash SHA `7d58986095c4df6a425dc9cfd8298851eee86c17`), PR19A2 (GitHub PR #85, squash SHA `7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`), and PR19A3 (GitHub PR #86, squash SHA `7f13a1e85e9b6a4828170c4b12bc2be27b15de39`) — all three merged, each independently Codex-reviewed with CI green on its exact reviewed head; see `docs/DECISION_LOG.md` ("Roadmap PR19A complete: PR19A1 + PR19A2 + PR19A3 merged"). A documentation-only governance sync (GitHub PR #87, squash SHA `bc4d490bd0e9b85eb6d630fc7aa013c801b333c9`) then recorded PR19A's completion. **PR19B** — a frontend-only, mock-backed workflow-review prototype (session list, create flow, validation summary, dry-run/confirm-gate, result summary) — was originally branched from `729d1aa...` before PR19A's contracts existed (Draft PR #80), then rebased and reconciled against PR19A's merged, authoritative contract (real 11-value session status enum, `ImportSessionOut`/`ValidationFindingOut` field names, `Page[T]` cursor pagination, warning-vs-error semantics) across three review rounds: an initial reconciliation review (reviewed head `71dc97d`) found PR80-H1 (mock fixtures violating backend invariants) and PR80-H2 (failed/cancelled result presentation could read as falsely successful); a fix round (reviewed head `6139bd4`) resolved H2 and mostly resolved H1, leaving PR80-H1R (a structural `validation_failed` fixture that contradicted the backend's TX1-rollback semantics) plus a non-blocking nullable-`importedRows` observation; a final fix round (reviewed head `5edf1bfd8de7013eb74f300193456c9e5c0f0332`) resolved H1R and the nullable-count issue and received **APPROVE**, with CI green (6/6) on that exact head. **PR19B merged as GitHub PR #80, real squash SHA `04f5bf5c76b51744981d1cc8072c074e604224e9`** — the reviewed feature head `5edf1bfd...` is not the baseline; the squash commit is. This closes the Roadmap PR19 Exception Record's Part B (all seven required steps satisfied) — see `docs/DECISION_LOG.md` ("Roadmap PR19B merged: Exception Record closed; Roadmap PR19 fully complete") for the full closure record. **With both PR19A and PR19B merged, Roadmap PR19 (Legacy Import Foundation + Frontend Skeleton) is now fully complete.** PR19B remains a frontend-only, non-executing preview — no file upload, no Excel/CSV parsing, no real validation/dry-run/import execution, and no database change were introduced by PR19B; that was true of every concrete legacy dataset import at the time PR19B merged. **Equipment Master import has since been separately implemented and completed by Roadmap PR20 (see the PR20 note below); at the time PR19B merged, Receive History and Issue History import remained unimplemented, future Roadmap PR21 scope — this was accurate then; Roadmap PR21 has since fully completed too, see the PR21 note below.** GitHub PR #81, an earlier unsplit PR19A candidate, remains closed without merging, superseded by PR19A1/PR19A2/PR19A3. **Before PR19B merged, the relative ordering between PR19B and PR20 had not been fixed by an Owner Decision (`docs/ROADMAP_STATUS.md`); that was a statement about work sequencing, never about a hard dependency — PR20 has only ever depended on PR19A, not PR19B.** PR19B has since merged, which is simply what already happened, not a new Owner Decision recorded by this note; the previously-open question of which of PR19B/PR20 would be worked on first is therefore moot. Roadmap PR20 (Equipment Master Import) has since fully completed — see the PR20 note below.

**PR20 note:** Roadmap PR20 (Equipment Master Import) shipped across six
implementation slices, per the architecture-approved design
(`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`, GitHub PR #89) and
Owner Decisions OD-1 (source schema), OD-2 (create/update field policy),
OD-3 (BCM/Item Number identity policy), and OD-4 (CREATE Asset Number
policy — `asset_number` never fabricated or derived; CREATE requires an
authoritative source, absent which a row receives a blocking
`ASSET_NUMBER_REQUIRED_FOR_CREATE` finding rather than a placeholder
value), all RESOLVED (GitHub PR #92). **PR20A** (GitHub PR #90) added the
source-artifact infrastructure: server-authoritative checksum/byte-size
upload, read-time re-verification, and the adapter invocation-context
contract — no parser or Equipment mutation. **PR20B** (GitHub PR #91)
added `Equipment.version`, a general optimistic-concurrency counter
required as a prerequisite for PR20E's later CAS predicate, incl. a fix
(PR91-H1) closing a gap where a client could bump the counter without a
genuine mutation. **PR20C** (GitHub PR #93) implemented the read-only
parse/normalize/validate adapter against OD-1–OD-4's resolved contract:
the 32-column `export_template.xlsx` mapping, BCM/Item No. normalization,
the OD-3 identity matrix, the OD-4 fail-closed CREATE Asset Number gate,
authoritative legacy status mapping, and OOXML macro/VBA structural
rejection. **PR20D** (GitHub PR #94) added a persisted, immutable
`DryRunPlan` artifact bound to session/source/checksum/validation-snapshot/
mapping-version identity, so the plan an operator reviews and confirms is
the exact artifact PR20E later executes, never a live recomputation;
multiple review rounds hardened a global Job→Session→Plan lock order
(closing a deadlock risk against concurrent recovery), idempotent-confirm
semantics (`ConfirmationResult`/`newly_confirmed`), and a single unified
`409 IMPORT_DRY_RUN_PLAN_STALE` contract covering every plan-invalidation
sub-case (superseded, session moved on, missing, or belonging to another
session) without ever distinguishing them by a different code. **PR20E**
(GitHub PR #95) executes exactly the persisted, confirmed `DryRunPlan`,
reusing PR19A3's execution claim/lease/fencing/TX1/TX2/recovery/audit
machinery unchanged and adding only the Equipment-Master-specific
CREATE/UPDATE mutation; two review rounds hardened global lock ordering
(Job → Session → adapter-owned resource), `resolved_resource_id`
survival across rollback, and UPDATE freshness-before-no-op validation
against `Equipment.version`. **PR20F** (GitHub PR #96) replaced the PR19B
mock Equipment Master workflow with real frontend calls against
PR20A–E — a dedicated real API client, a workflow panel rendering the
actual persisted `DryRunPlan` (never just aggregate counters), cursor
pagination for plan rows/findings/session lists, a fail-closed guard
against combining rows from two different plan generations, always-
reachable running-state recovery after reload, and a findings-fetch
failure state that never masquerades as a genuine empty result; two
independent review rounds (round 1 REQUEST CHANGES on four findings,
round 2 the cross-plan-pagination identity guard, no finding remaining)
preceded CI green (6/6) on the final exact reviewed head
`38c6d33c15ed13929392d0736b9accda0886fa2e`, merged as the real squash SHA
`2743af849702ef551927b9c362421df08c80b5d9` — PR20's own final baseline at
the time, since superseded by `d64d50d...` (PR21E; see above), itself
since superseded by the current baseline at the top of this document.
See `docs/DECISION_LOG.md`
("Roadmap PR20 complete: PR20A–PR20F
merged") for the full slice-by-slice record. **Roadmap PR20 (Equipment
Master Import) is now fully complete.** PR20 implements Equipment Master
only — legacy Receive/Issue history import is Roadmap PR21's own scope.
**At the time PR20 completed, PR19B's Receive/Issue History screens
remained frontend-only mock placeholders, unchanged by PR20; Roadmap
PR21 had not started. This was accurate at the time — Roadmap PR21 has
since fully completed and PR19B's mock Receive/Issue screens have been
removed entirely — see the PR21 note immediately below.**

**PR21 note:** Roadmap PR21 (Legacy Receive and Issue History Import)
shipped across eight implementation slices plus its own design and
Owner Decision governance work, per the architecture-approved design
(`docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`, GitHub PR
#98, with a Source Evidence Update GitHub PR #99) and seven Owner
Decisions (OD-PR21-0 through OD-PR21-6), all RESOLVED across three
closure rounds (GitHub PR #101, #102, #106) — most notably OD-PR21-0's
final sub-component, the SDC-sheet field-level-contract ambiguity,
resolved by **excluding the SDC sheets from PR21 V1** by explicit Owner
decision (a source-authority selection, not a row-level-equivalence
claim): the four already-confirmed canonical sheets (`Orders
ยืมเครื่อง` + `ข้อมูลส่งเครื่องมือ` for Issue, `Orders คืนเครื่อง` +
`ข้อมูลรับเครื่องมือ` for Receive) are PR21 V1's sole authoritative
source contract. **PR21-Foundation** (GitHub PR #100) added the
generic, topology-independent internal dry-run-plan provider and
fail-closed retention-hook abstraction PR21 shares with PR20, with no
PR21 dataset schema of its own. **PR21A** (GitHub PR #103) added the
`LegacyEquipmentEvent` schema and its provenance tables — every accepted
legacy source row imports as an independent, immutable event
(`event_type` = `ISSUE` | `RECEIVE`), never a paired transaction; Issue
and Receive are never required to be matched at import time (event-first
architecture, Owner Decision Closure Round 2), pairing remains Roadmap
PR22-or-later's own responsibility. **PR21B** (GitHub PR #104) and
**PR21C** (GitHub PR #105) added the canonical Issue and Receive
parsers/validators respectively, each initially an unregistered internal
component (so a real `ImportSession` could not reach `validated`/dry-run/
execute from either side alone, until SDC was resolved). With SDC
excluded, **PR21D1** (GitHub PR #107) composed the two parsers into the
production `legacy_transaction_history` `ImportAdapter`, registered it,
added the `PR21_MAX_UPLOAD_BYTES = 32 MiB` bounded upload allowance
(generic 10 MiB cap unchanged for every other dataset), and wired a
mandatory all-or-nothing validation gate — an Issue-only or Receive-only
`LegacyHistoryDryRunPlan` is structurally unreachable. **PR21D2** (GitHub
PR #108) executes the validated, confirmed plan's `LegacyEquipmentEvent`
INSERTs — never `BorrowTransaction` replay, live dispatch/receipt, or
`Equipment.status`/version/location/lifecycle mutation; historical
import never changes current Equipment state. **PR21E0** (GitHub PR
#109) added the Administrator-only `POST`/`GET
/legacy-migration-authorities` checksum-approval API (exact scope
`pr21_legacy_transaction_history_v1`, no automatic approval, no delete/
revoke) and the PR21-specific `GET`/`POST
.../legacy-history/dry-run-plan[/{plan_id}/rows|/confirm]` route family,
deliberately separate from PR20's own `.../dry-run-plan` routes, which
remain byte/field/OpenAPI-unchanged. **PR21E** (GitHub PR #110) replaced
the PR19B mock Receive/Issue frontend with the real, single combined
`legacy_transaction_history` operator workflow (create → upload →
explicit, never-auto-approved authority approval → validate → dry-run →
paginated ISSUE/RECEIVE row review → confirm → execute), removed
`MockImportClient`/the fixture set/the skeleton banner entirely, and
replaced the prior UUID-shape session-detail routing with real
`dataset_type`-based dispatch. PR #110's independent Final Merge Gate
recorded zero review threads and zero findings of any kind — a genuine
absence of findings, not an accepted P2. See `docs/DECISION_LOG.md`
("Roadmap PR21 complete: PR21D1–PR21F merged") and
`docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md` §56 for the
full closure record. **Roadmap PR21 (Legacy Receive and Issue History
Import) is now fully complete** — its own baseline at completion was
`d64d50d...` (PR21E), now historical; see the current baseline at the
top of this document. **Roadmap PR22 (Legacy Data Validation and
Reconciliation) has since fully completed** — architecture design, all
seven Owner Decisions, every implementation slice (PR22B-F), and
governance close-out (PR22G) are all merged; **Roadmap PR23 (Cutover
Readiness)'s first slice, PR23A, is now in progress** (see the top of
this document).

## Approved forward sequence

The least disruptive numbering keeps the repository's established Roadmap
PR1–PR15 sequence and assigns the newly approved work as follows. Roadmap
numbers are not GitHub PR numbers; GitHub PR #18 was a governance PR, not
Roadmap PR18.

Roadmap PR18A (`docs/design/PR18_PRINTING_EXPORT_PLAN.md`) is merged as the
approved architecture design, and PR18B (shared backend export foundation),
PR18C (Browser Print), PR18D (backend PDF export), and PR18E (Excel `.xlsx`
export) are all merged. **Roadmap PR18 (Printing and Export) is now fully
complete.** The next planned item is Roadmap PR19.

**Roadmap PR19 split (approved 2026-08-03):** Roadmap PR19 is delivered as
two independent-scope implementation slices, per `docs/DECISION_LOG.md`
("Roadmap PR19 approved split: PR19A (backend) / PR19B (frontend
skeleton)") — an explicit, Owner-approved exception to this repository's
usual design-document-first slice precedent, since at the time of approval
no PR19 design document existed. "Parallel" describes scope/dependency
independence only (neither slice is stacked on, or blocked by, the other's
unmerged branch) — it does **not** mean the two slices share one
implementation baseline commit. **PR19A** is the backend import framework
itself; **PR19B** is a frontend-only, mock-data workflow-review prototype
(no upload, parsing, validation, dry-run, or import execution; its
Equipment Master/Receive/Issue History category labels are preview labels
pulled forward from PR20/PR21, not an implemented capability). PR19B was
implemented on Draft PR #80 (`feature/pr19b-import-frontend-skeleton`),
branched from `729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` (the latest
approved baseline when its branch was created) — **historical statement,
as this paragraph was originally written; PR19B has since merged (real
squash SHA `04f5bf5c...`, now itself historical) and Roadmap PR19, PR20,
and PR21 are all now fully complete — `d64d50d...` (PR21E) was that
completion's own baseline, now itself historical; see the current
baseline at the top of this document.** **PR19A's architecture design has since merged as
GitHub PR #83** (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`,
squash SHA `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`), likewise branched
directly from `729d1aa...` in parallel — confirming in practice that
"independent-scope" never required a shared baseline. That design defines
PR19A's authoritative contract and decomposes it into implementation
slices PR19A1/PR19A2/PR19A3 (design §25). **All three are now merged:
PR19A1 (schema, session/source lifecycle, CAS) as GitHub PR #84, squash
SHA `7d58986095c4df6a425dc9cfd8298851eee86c17`; PR19A2 (validation
foundation) as GitHub PR #85, squash SHA
`7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`; PR19A3 (dry-run, execution,
recovery, retention) as GitHub PR #86, squash SHA
`7f13a1e85e9b6a4828170c4b12bc2be27b15de39`, each independently reviewed by
Codex and merged only after CI passed on the exact reviewed head. **PR19A
(Legacy Import Foundation, backend) is now fully complete.**

**Historical text below (as originally written, describing PR19B as still
open) is superseded — update (2026-08-11): PR19B has since merged as
GitHub PR #80, real squash SHA `04f5bf5c76b51744981d1cc8072c074e604224e9`,
after independent Codex APPROVE on reviewed head
`5edf1bfd8de7013eb74f300193456c9e5c0f0332` and CI green (6/6) on that exact
head.** The PR19A/PR19B split's Exception Record required every slice
(PR19A's own PR19A1/PR19A2/PR19A3, PR19B, and the realignment/
governance-sync work that followed) to merge before Roadmap PR19 could be
declared complete — **all of them now have. Roadmap PR19 (Legacy Import
Foundation, backend + frontend skeleton) is fully complete.** GitHub PR
#81 (an earlier, unsplit PR19A candidate opened before the
PR19A1/PR19A2/PR19A3 decomposition existed) was closed without merging,
superseded by the slices actually merged. See `docs/DECISION_LOG.md`'s
Exception Record (Part B, now CLOSED) for the full seven-step closure
record and the "PR19 note" paragraph above for PR19B's own review
chronology.

| Roadmap item | Planned scope |
|---|---|
| PR19A | Legacy Import Foundation (backend) — **COMPLETE / MERGED** (PR19A1 #84, PR19A2 #85, PR19A3 #86) |
| PR19B | Legacy Import Frontend Skeleton (workflow-review prototype only; no real import) — **COMPLETE / MERGED** as GitHub PR #80, squash SHA `04f5bf5c76b51744981d1cc8072c074e604224e9` |
| PR20 | Equipment Master Import: BCM, Item Number, equipment attributes, existing hospital QR linkage, equipment duplicate detection, and equipment-record validation — **COMPLETE / MERGED** (design #89; PR20A #90, PR20B #91, OD-1–OD-4 resolution #92, PR20C #93, PR20D #94, PR20E #95, PR20F #96), squash SHA `2743af849702ef551927b9c362421df08c80b5d9` (PR20F, historical baseline — superseded by PR21E, see below) |
| PR21 | Legacy Receive and Issue History Import: Receive/Issue history, legacy BME-name preservation and user mapping, Ward normalization and mapping, transaction-row duplicate detection, and transaction source references — **COMPLETE / MERGED** (design #98/#99; PR21-Foundation #100; Owner Decision Closure Rounds 1-3 #101/#102/#106; PR21A #103, PR21B #104, PR21C #105, PR21D1 #107, PR21D2 #108, PR21E0 #109, PR21E #110), squash SHA `d64d50d09cdf8ed7ddc1f5116b38805dfcbc7810` (PR21E, historical baseline — superseded by PR21F then PR22A/PR113, see the top of this document) |
| PR22 | Legacy Data Validation and Reconciliation: cross-import validation, reconciliation, source traceability verification, duplicate review, and unified legacy/new history validation — **COMPLETE / MERGED** (design #112, squash SHA `c924d8ba2c8c5d933ea36ea3d488e2550615df40`; Owner Decision Closure #115, squash SHA `f03af893d727b221bd941466d83e5eceb9eb596a`; PR22B #116, PR22C #117, PR22D #118, PR22E #119, PR22F #120; PR22G governance close-out #121, squash SHA `527ffc48966d7e5cda16a869f0ae464de8b7512a`), squash SHA `527ffc48966d7e5cda16a869f0ae464de8b7512a` (PR22G, current baseline — see the top of this document). **Roadmap PR22 is fully complete.** |
| PR23 | Cutover Readiness — **PR23A (Architecture & Operational Design) in progress, not yet merged** (`docs/design/PR23_CUTOVER_READINESS_PLAN.md`); PR23B+ not started, pending Owner Decision resolution (see PR23A) |
| PR24 | Go-live / deployment, blocked by PR19–PR23 |

The documentation audit and Roadmap consistency work is an unnumbered
governance change and does not consume a Roadmap number.

### Reporting and shift contract

Reporting must preserve three distinct concepts: the actual transaction
timestamp, `business_date`, and `shift`. Shift is reporting and operational
metadata, not an equipment lifecycle state. Day and Night are values in one
model; do not create separate Day and Night tables.

Reports must support date-and-shift filtering for Receive, Issue, and Equipment
Verify Checklist data, followed by PDF, Excel, and print-ready Hard Copy
output.

### Version 1 legacy migration contract

Legacy migration is mandatory before Go-live. The minimum Version 1 scope is:

- Equipment Master;
- legacy Receive history from the AppSheet equipment receive-data sheet; and
- legacy Issue history from the AppSheet equipment issue-data sheet.

Equipment Verify Checklist history is not part of the initial migration. The
migration scope is divided as follows:

- **PR20 — Equipment Master Import (COMPLETE / MERGED, PR20A–PR20F):** BCM,
  Item Number, equipment attributes, existing hospital QR linkage, equipment
  duplicate detection, and equipment-record validation.
- **PR21 — Legacy Receive and Issue History Import (COMPLETE / MERGED,
  design #98/#99 through PR21E #110 — see the PR21 note above):** Receive
  history, Issue history, legacy BME-name preservation and user mapping,
  Ward normalization and mapping, transaction-row duplicate detection, and
  transaction source references. Delivered as one combined
  `legacy_transaction_history` workbook/`ImportSession` (not two separate
  imports); SDC sheets excluded from V1 by explicit Owner decision; each
  accepted row imports as an independent `LegacyEquipmentEvent`
  (`ISSUE`/`RECEIVE`), Issue↔Receive pairing deferred to PR22-or-later;
  historical import never mutates current Equipment status/location.
- **PR22 — Legacy Data Validation and Reconciliation:** cross-import
  validation, reconciliation, source traceability verification, duplicate
  review, and unified legacy/new history validation.

The migration must not redesign or replace the hospital QR system.

## Prior planned note (superseded where inconsistent)

The PR15A-era text below is retained for provenance. Its statement that the
PR15B design was uncommitted is superseded by GitHub PR #52 and the approved
sequence above.

Per `docs/audits/04-consolidated-implementation-plan.md` Part D:

| Roadmap PR | Title |
|---|---|
| PR15 (PR15B slice) | Schema Hygiene — validate-before-enforce migration slice (timezone policy execution, FK `ondelete` policy follow-through, index naming standardization, etc.), per the architecture-approved design (`docs/design/PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md`). Not started. |

**PR14 above is Reliability and Performance Hardening — it is not related to GitHub PR #14 (which implemented Roadmap PR5).** See the numbering note. Roadmap PR14 (both PR14A Reliability Correctness and PR14B Pagination Performance) is now fully complete — see the Completed table and the PR14 note above. **Roadmap PR15 is only partially complete:** PR15A (Observability) is merged — see the Completed table and the PR15 note above; PR15B (Schema Hygiene) is the next planned item. Application metrics, tracing, dashboards, log aggregation, and alerting are **not** scheduled to either PR15 slice and remain open Roadmap PR15 scope, not yet assigned to any Roadmap PR, pending a future slice or an explicit governance decision to remove them from scope — Roadmap PR15 as a whole may not be marked complete until every one of its topics has been implemented, completed by an earlier PR, or explicitly removed through a governance decision.

**GitHub PR #40 note:** GitHub PR #40 ("Dashboard & Equipment Status") is merged and recorded in the Completed table above as an unnumbered "— (frontend)" row. It did **not** implement Roadmap PR12 — its originating task description used "PR12" as an informal label, which conflicted with this file's Roadmap PR12 (Inventory Import). Governance PR #41 (see `docs/DECISION_LOG.md`, "Governance — GitHub PR #40 classification") resolved that conflict by classifying it as an unnumbered Post-PR11 Frontend Dashboard UX Follow-up. Roadmap PR12 was subsequently implemented and merged as GitHub PR #43 (see the PR12 note above), Roadmap PR13 as GitHub PR #45 (see the PR13 note above), Roadmap PR14's PR14A and PR14B slices as GitHub PR #46 and #48 respectively (see the PR14 note above), and Roadmap PR15's PR15A slice as GitHub PR #50 (see the PR15 note above). **Roadmap PR15's PR15B slice (Schema Hygiene) is the next planned item and has not started; broader Roadmap PR15 scope (metrics, tracing, dashboards, log aggregation, alerting) remains open pending future scheduling or an explicit governance decision.**

## Confirmed future work (not scheduled to a Roadmap PR)

- **Shift Sessions (superseded terminology)** — the approved PR16 direction is
  transaction reporting metadata (`business_date` and `shift`) in one model,
  not separate Day/Night tables or a new equipment lifecycle state. Any future
  session workflow would require its own approval and must not contradict PR16.
- **Standby Snapshots** — Day/Night department-level equipment-count reports.
- **Managed deployment** — production must not assume direct access to hospital-managed servers.
- **Create-from-import** — Roadmap PR12 (Inventory Import, GitHub PR #43) shipped update-only; creating new equipment from an imported spreadsheet row was deferred, not permanently prohibited, pending a dedicated design for real hospital Asset Number assignment (hospital-assigned values, a nullable-provisional-record model, or another authoritative approach) and, if the identifier model itself needs to change, a governing ADR update. See `docs/ROADMAP.md`'s PR12 note and `docs/DECISION_LOG.md` ("Roadmap PR12").

Detail and rationale: `AGENTS.md` ("Confirmed Future Workflow Direction"), `docs/ARCHITECTURE_DECISIONS.md`.

## Related documents

| Concern | Document |
|---|---|
| Full scope, ordering, dependencies, acceptance criteria per PR | `docs/audits/04-consolidated-implementation-plan.md` |
| Per-decision rationale for PR5 onward | `docs/DECISION_LOG.md` |
| Per-decision rationale for PR1 through Governance Pack v1.0 | `docs/PROJECT_MEMORY.md` |
| Current-state AI-memory snapshot | `knowledge/PROJECT_MEMORY.md` |
| Right-now state (current PR, outstanding work, risks) | `knowledge/CONTEXT.md` |
| Domain entity structural reference | `docs/DOMAIN_MODEL.md` |
| Transaction lifecycle decision (PR7, both slices) | `knowledge/adr/ADR-005-transaction-model.md` |
