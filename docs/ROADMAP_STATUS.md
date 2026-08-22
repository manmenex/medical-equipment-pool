# Roadmap Status

**Purpose:** Concise live status dashboard.
**Authority:** Status summary only. [`ROADMAP.md`](ROADMAP.md) and
[`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md)
control detailed ordering, scope, dependencies, and acceptance criteria.
**Update trigger:** A Roadmap item, design, implementation, or baseline changes.

## Current baseline

`c802d66c9d1e5395cd20591c451ebdc0cefbf7df` — the real squash-merge SHA of
GitHub PR #113, the post-PR22A governance synchronization (documentation-
only), merged on top of `c924d8ba2c8c5d933ea36ea3d488e2550615df40`
(GitHub PR #112, Roadmap PR22A — Legacy Data Validation and
Reconciliation Architecture, design only). PR #113's final independently
reviewed feature-branch head was
`ec02ced43d649c8c813a458762f110b13eb5ab7d`, which carried **zero review
threads and zero comments**, with CI green (6/6) and the reviewed head's
tree independently verified byte-identical to the merged squash commit's
tree, sole parent `c924d8b...` confirmed — **that reviewed head is not
the baseline**; the squash commit actually landed on the base branch,
`c802d66...`, is. This baseline advances even though PR #113 is
documentation-only, consistent with this repository's squash-baseline
discipline: the authoritative baseline tracks the exact commit landed on
the base branch, not only commits that touch runtime code.

**Roadmap PR22 (Legacy Data Validation and Reconciliation)'s
architecture design is merged** (GitHub PR #112, folded into this
baseline) — implementation is **not started**, and all seven Owner
Decisions (OD-PR22-1 through OD-PR22-7) remain **OPEN**. **The next
planned step is Owner Decision Closure for OD-PR22-1 through OD-PR22-7
— not PR22B-G directly.**

`d64d50d09cdf8ed7ddc1f5116b38805dfcbc7810` (GitHub PR #110, Roadmap
PR21E — Legacy History Frontend Real Integration) is now historical,
superseded first by `e07a36a...` (GitHub PR #111, PR21F) and then by
this baseline. With PR21E merged, every Roadmap PR21 implementation
slice — PR21-Foundation (#100), PR21A
(#103), PR21B (#104), PR21C (#105), PR21D1 (#107), PR21D2 (#108), PR21E0
(#109), PR21E (#110), plus the design (#98, #99) and three Owner
Decision Closure rounds (#101, #102, #106) — is merged. **Roadmap PR21
(Legacy Receive and Issue History Import) is now fully complete.** See
"Roadmap PR21 complete" below for the full detail and
`docs/DECISION_LOG.md` ("Roadmap PR21 complete: PR21D1–PR21F merged") for
the closure record. Roadmap PR20 (Equipment Master Import) remains fully
complete, unaffected by PR21's completion — its own baseline,
`2743af849702ef551927b9c362421df08c80b5d9` (GitHub PR #96), is retained
below as provenance, followed by `04f5bf5c...` (PR19B), `7f13a1e...`
(PR19A3), and `729d1aa...` (PR18F) as provenance for earlier Roadmap
items.

`2743af849702ef551927b9c362421df08c80b5d9` — squash commit of GitHub PR
#96, Roadmap PR20F (Equipment Master Frontend Real API Integration),
merged on top of `698c34d9c280b2ca2ea4f299bd186517c9fb26a8` (GitHub PR
#95, Roadmap PR20E). With PR20F merged, all six implementation slices of
Roadmap PR20 — PR20A (#90), PR20B (#91), PR20C (#93), PR20D (#94), PR20E
(#95), PR20F (#96), plus the design (#89) and two governance syncs (#88,
#92) — were merged. **Roadmap PR20 (Equipment Master Import) is fully
complete** (unaffected by PR21's completion; see "Roadmap PR20 complete"
below). Superseded by `d64d50d...` (GitHub PR #110, PR21E) as the current
baseline once PR21E also merged.

`7f13a1e85e9b6a4828170c4b12bc2be27b15de39` — squash commit of GitHub PR
#86, the Roadmap PR19A3 implementation (Dry-run, Execution, Recovery,
Retention). It follows GitHub PR #85 (`7e5e6f2d`, Roadmap PR19A2 —
Validation Foundation) and GitHub PR #84 (`7d589860`, Roadmap PR19A1 —
Schema / Session / Source Foundation), both based on GitHub PR #83
(`38a21e8c`, the architecture-approved PR19A design). **All three of
PR19A's implementation slices are merged — Roadmap PR19A (Legacy Import
Foundation, backend) is now fully complete.** Superseded by `04f5bf5c...`
(GitHub PR #80, PR19B) once PR19B also merged — `04f5bf5c...` is itself
now historical/intermediate, superseded in turn by `2743af8...` (GitHub
PR #96, PR20F), itself since superseded by the current baseline at the
top of this section (`d64d50d...`, GitHub PR #110, PR21E).

`729d1aa2f40db60a6056ecbb5bc1ab8e64e92e52` — squash commit of GitHub PR #79,
the documentation-only PR18F governance synchronization recording Roadmap
PR18's completion. It follows GitHub PR #78 (`5d8cf7d`, the merged Roadmap
PR18E Excel `.xlsx` export implementation), GitHub PR #77 (`bc274e6`, PR18D
backend PDF export), GitHub PR #76 (`beedc4d`,
the documentation-only governance sync after PR18C), GitHub PR #75
(`e919a2a`, PR18C Browser Print), GitHub PR #74 (`4da1ebc`, the
documentation-only governance sync after PR18B), GitHub PR #73 (`c72929b`,
PR18B backend export foundation), GitHub PR #72 (`e1b358a`, post-PR18A
governance synchronization), and GitHub PR #71 (`6ba2c66`, approved PR18A
architecture design). PR18E added the backend Excel adapter (openpyxl, no new
dependency) for all three PR17 reports over PR18B's bounded foundation, with
workbook-wide formula-injection protection and bounded concurrency/admission
control. It added no migration or equipment lifecycle change. PR15A and PR15B
are both implemented
— both of Roadmap PR15's scheduled slices are complete.
Application metrics, tracing, dashboards, log aggregation, and alerting
remain open Roadmap PR15 scope, not scheduled to any slice, pending a
future slice or an explicit governance decision to remove them. Roadmap
PR16 (Reporting Foundation, all four Implementation Slices — GitHub PR #58,
#59, #60, #61) and Roadmap PR17 (Operational Reports, design GitHub PR #63
plus all four Implementation Slices — GitHub PR #65, #66, #67, #68) are now
fully complete. **Roadmap PR18 (printing/export architecture, backend export
foundation, Browser Print, backend PDF export, and Excel `.xlsx` export — GitHub
PR #71, #73, #75, #77, #78, with governance-sync PRs #72, #74, #76, #79 interleaved
between/after them) is now fully complete.** Owner Decision #2 (branding
configuration ownership) remains open.

**Roadmap PR19 split (approved 2026-08-03):** Roadmap PR19 is delivered as
two independent-scope slices — **PR19A** (backend import framework) and
**PR19B** (frontend-only workflow-review skeleton, no real import) — per
`docs/DECISION_LOG.md` ("Roadmap PR19 approved split: PR19A (backend) /
PR19B (frontend skeleton)") — an explicit, Owner-approved exception, since
at the time of approval no PR19 design document existed. "Parallel"
describes scope/dependency independence only, not a shared implementation
baseline. **PR19A's architecture design merged as GitHub PR #83** (squash
SHA `38a21e8c6094fcf8686b1ba5ae4807c0aa1bbbf7`, `docs/design/
PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`), branched directly from
`729d1aa...`; its implementation slices PR19A1/PR19A2/PR19A3 (design §25)
have since **all merged**: PR19A1 (schema, session/source lifecycle, CAS)
as GitHub PR #84, squash SHA `7d58986095c4df6a425dc9cfd8298851eee86c17`;
PR19A2 (validation foundation) as GitHub PR #85, squash SHA
`7e5e6f2d81057ca7d8c73bb32b6d8139b3807a4f`; PR19A3 (dry-run, execution,
recovery, retention) as GitHub PR #86, squash SHA
`7f13a1e85e9b6a4828170c4b12bc2be27b15de39`. **PR19A (Legacy Import
Foundation, backend) is now fully complete.** No concrete legacy dataset
import (Equipment Master, Receive History, Issue History) is implemented
by PR19A itself — true then and now; **Equipment Master import has since
been implemented separately by Roadmap PR20 (complete; see above); at
the time this paragraph was written, Receive History/Issue History
import remained future Roadmap PR21 scope — this was accurate then;
Roadmap PR21 has since fully completed too, see "Roadmap PR21 complete"
below.** PR19B
(`feature/pr19b-import-frontend-skeleton`), originally branched from
`729d1aa...` as a provisional Draft, was reconciled against PR19A's
merged authoritative contract at reviewed head
`71dc97df583f60c3e9f8bccbbcb2e72b0b7307d5`. Independent review went
through three rounds: the reconciliation head received REQUEST CHANGES
(findings PR80-H1 — mock fixtures violated backend invariants — and
PR80-H2 — failed/cancelled result presentation could falsely appear
successful); a fix round at `6139bd4abd44c0a4ac07bf6ac63bf1b897dad653`
resolved H2 and mostly resolved H1, leaving PR80-H1R (a structural
`validation_failed` fixture carried a persisted finding despite TX1
rollback semantics) plus a non-blocking observation about nullable
`importedRows`; a final fix round at the reviewed head
`5edf1bfd8de7013eb74f300193456c9e5c0f0332` closed PR80-H1R and received
**APPROVE**, with CI green (6/6). PR19B then merged as GitHub PR #80,
real squash-merge SHA `04f5bf5c76b51744981d1cc8072c074e604224e9` —
historical/intermediate, since superseded by `2743af8...` (PR20F), itself
in turn since superseded by `d64d50d...` (PR21E, the current baseline;
see "Current baseline" above). GitHub PR #81, an earlier unsplit
PR19A candidate, was closed without merging, superseded by
PR19A1/PR19A2/PR19A3. **PR19A and PR19B are both complete and merged;
Roadmap PR19 (Legacy Import Foundation, backend + frontend skeleton) as a
whole is now fully complete.** PR19B itself remains a frontend-only
workflow-review skeleton — no real file upload, workbook parsing,
validation/dry-run/import execution, or production legacy dataset
adapter was implemented by PR19B. **This was accurate as of PR19B's own
merge; Equipment Master import has since been separately implemented and
completed by Roadmap PR20 (see "Roadmap PR20 complete" above), and
Receive History/Issue History import — Roadmap PR21 — has since fully
completed too (see "Roadmap PR21 complete" below). No production import
path goes through PR19B's mock workflow any more.** The Exception Record governing this split
(`docs/DECISION_LOG.md`) is now closed — see "Roadmap PR19B merged:
Exception Record closed; Roadmap PR19 fully complete" there for the
closure record and the required-steps evidence.

Roadmap numbering and GitHub PR numbering are independent. In particular,
GitHub PR #18 was the Knowledge & Governance Foundation; it was not Roadmap
PR18.

**Roadmap PR20 complete:** Roadmap PR20 (Equipment Master Import) shipped
across six implementation slices, per the architecture-approved design
(GitHub PR #89, `docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`) and
Owner Decisions OD-1–OD-4 (source schema, create/update field policy,
BCM/Item Number identity policy, CREATE Asset Number policy), all
RESOLVED (GitHub PR #92). **PR20A** (source artifact infrastructure) as
GitHub PR #90, squash SHA `1de3db1eaef81ead2e20cdbf4758aebfdf9f55a0`;
**PR20B** (`Equipment.version` optimistic concurrency) as GitHub PR #91,
squash SHA `bd47701917207479f3d91a349961f3d61ef707c2`; **PR20C**
(parse/normalize/validate adapter) as GitHub PR #93, squash SHA
`1d04672ab6d767e35f5be63f765da0a94033b324`; **PR20D** (persisted,
immutable `DryRunPlan`) as GitHub PR #94, squash SHA
`c72baa19888edcfb2fa2fcb593c649ae2ac35bec`; **PR20E** (`execute()` —
CREATE/UPDATE mutation of the exact confirmed plan) as GitHub PR #95,
squash SHA `698c34d9c280b2ca2ea4f299bd186517c9fb26a8`; **PR20F** (real
frontend API integration, replacing the PR19B mock workflow for this
dataset type) as GitHub PR #96, squash SHA
`2743af849702ef551927b9c362421df08c80b5d9` (see "Current baseline"
above). **Roadmap PR20 (Equipment Master Import) is now fully complete.**
PR20 implements Equipment Master only — legacy Receive/Issue history
import was Roadmap PR21's own scope, now also complete (see "Roadmap
PR21 complete" below). See `docs/DECISION_LOG.md` ("Roadmap PR20
complete: PR20A–PR20F merged") for the full slice-by-slice review
chronology and closure record.

**Roadmap PR21 complete:** Roadmap PR21 (Legacy Receive and Issue
History Import) shipped across eight implementation slices, per the
architecture-approved design (GitHub PR #98, `docs/design/
PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`, with a Source Evidence
Update GitHub PR #99) and all seven Owner Decisions (OD-PR21-0 through
OD-PR21-6), all RESOLVED across three closure rounds (GitHub PR #101,
#102, #106) — including OD-PR21-0's SDC-sheet field-level-contract
sub-component, resolved by **excluding SDC from PR21 V1** (a
source-authority decision, not a row-level-equivalence claim). **PR21-
Foundation** (GitHub PR #100, squash SHA
`7b99e5866df4b71ffa1aa09d265baa2bc7033c33`) — generic internal
dry-run-plan provider + fail-closed retention-hook abstraction, no PR21
dataset schema of its own. **PR21A** (GitHub PR #103, squash SHA
`28f0f5eabb64cf4b27294fd3df251e90b167de0a`) — the `LegacyEquipmentEvent`
schema/provenance foundation; event-first architecture (Owner Decision
Closure Round 2) — each accepted row imports as an independent
`ISSUE`/`RECEIVE` event, pairing deferred to PR22-or-later. **PR21B**
(GitHub PR #104, squash SHA
`a8ae9fbfc571f74bad2100abf8f90bbd22a68e74`) and **PR21C** (GitHub PR
#105, squash SHA `651a3877c17d53c0163e34d9008ca744ac7f76ef`) — canonical
Issue and Receive parsers/validators, each merged as an unregistered
internal component pending the SDC decision. **PR21D1 — Combined
Canonical Adapter + Source Admission** (GitHub PR #107, squash SHA
`50b9e77269b238d95fb34b28d0bc223a369951e2`) — composed PR21B/PR21C into
the registered `legacy_transaction_history` `ImportAdapter`, added the
`PR21_MAX_UPLOAD_BYTES = 32 MiB` bounded upload allowance, wired the
mandatory all-or-nothing validation gate. **PR21D2 — Historical Event
Execution** (GitHub PR #108, squash SHA
`c4788de06bed9a13aa5ec981fb8e19c67bc5720b`) — executes the confirmed
plan's `LegacyEquipmentEvent` INSERTs; never `BorrowTransaction` replay,
live dispatch/receipt, or `Equipment.status`/version/location/lifecycle
mutation. **PR21E0 — Legacy Import Operator API Surface** (GitHub PR
#109, squash SHA `78eeea7827c53443f34de9e516573c2ed7c59581`) — the
Administrator-only migration-authority checksum-approval API and the
PR21-specific dry-run-plan/rows/confirm HTTP route family, separate from
and non-disruptive to PR20's own routes. **PR21E — Legacy History
Frontend Real Integration** (GitHub PR #110, squash SHA
`d64d50d09cdf8ed7ddc1f5116b38805dfcbc7810`, see "Current baseline"
above) — real frontend integration replacing the PR19B mock Receive/
Issue workflow with one combined `legacy_transaction_history` operator
flow (create → upload → explicit authority approval → validate →
dry-run → paginated row review → confirm → execute); `MockImportClient`
and the fixture set/skeleton banner were removed entirely. **PR #110's
independent Final Merge Gate recorded zero review threads and zero
findings of any kind — a genuine absence of findings, never an accepted
P2.** **Roadmap PR21 (Legacy Receive and Issue History Import) is now
fully complete.** No production import path goes through mock data for
either Equipment Master or legacy transaction history. See
`docs/DECISION_LOG.md` ("Roadmap PR21 complete: PR21D1–PR21F merged")
for the full slice-by-slice review chronology and closure record.

## Current and planned sequence

| Sequence | Roadmap item | Status |
|---|---|---|
| Next | PR22 — Legacy Data Validation and Reconciliation | Depends on PR20 and PR21, both now complete. **Architecture design merged** (`docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md`, GitHub PR #112, squash SHA `c924d8ba2c8c5d933ea36ea3d488e2550615df40`) — implementation not started, all seven Owner Decisions (OD-PR22-1 through OD-PR22-7) remain OPEN |
| After PR22 | PR23 — Cutover Readiness | Planned |
| After PR19–PR23 | PR24 — Go-live / deployment | Planned; blocked by PR19–PR23 |

**Historical note on PR19B/PR20 relative ordering:** before PR19B merged,
while it was still a provisional, unreviewed Draft (GitHub PR #80), this
table carried both a PR19B row and a PR20 row with no relative numeric
order between them, and noted that their sequencing had not been fixed by
an Owner Decision. That was never a statement about a hard dependency —
PR20 has only ever depended on PR19A, not PR19B — it only meant no Owner
Decision had settled which of the two would be worked on first. PR19B has
since been independently reviewed and merged (squash SHA
`04f5bf5c76b51744981d1cc8072c074e604224e9`; see "Roadmap PR19 split"
above); its own row therefore moved off this table the same way PR19A's
did, and the roadmap proceeded to PR20 as the next planned item at that
time. This was never a statement about a hard dependency, only settling
which of PR19B/PR20 would be worked on first — the one item whose
relative order was ever in question. **Roadmap PR20 has since also fully
completed (see "Roadmap PR20 complete" above); its row has likewise moved
off this table. Roadmap PR21 has since fully completed too (see "Roadmap
PR21 complete" above); its row has also moved off this table, and PR22
is now shown with sequence "Next" in the table above.** PR22 through
PR24's ordering is preserved as-is because it reflects an existing
authoritative dependency chain
(`docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8:
PR21 depended on PR20 — satisfied; PR22 depends on PR20 and PR21, both
now complete; PR24 is blocked by PR19–PR23), not a new sequencing
decision introduced by this or any prior governance sync.

Roadmap PR15B (Schema Hygiene implementation, GitHub PR #54), the
documentation audit and Roadmap consistency work that preceded it
(GitHub PR #53, unnumbered governance change), Roadmap PR16 (Reporting
Foundation, all four Implementation Slices — GitHub PR #58, #59, #60, #61),
and Roadmap PR17 (Operational Reports, design GitHub PR #63 plus all four
Implementation Slices — GitHub PR #65, #66, #67, #68) are all complete and
have moved off this table. **Roadmap PR18 (Printing and Export) is also now
fully complete and has moved off this table:** PR18A design (GitHub PR #71),
its governance sync (GitHub PR #72), PR18B backend export foundation (GitHub
PR #73), a governance sync recording PR18B's completion (GitHub PR #74),
PR18C Browser Print (GitHub PR #75), a governance sync recording PR18C's
completion (GitHub PR #76), PR18D backend PDF export (GitHub PR #77), and
PR18E Excel `.xlsx` export (GitHub PR #78) are all merged — see
`docs/ROADMAP.md`'s Completed table for the full historical record.
**Roadmap PR19 (Legacy Import Foundation, backend + frontend skeleton) is
also now fully complete and has moved off this table:** the architecture
design (GitHub PR #83) and its three PR19A implementation slices PR19A1
(GitHub PR #84), PR19A2 (GitHub PR #85), and PR19A3 (GitHub PR #86) are
all merged, and PR19B (GitHub PR #80, squash SHA
`04f5bf5c76b51744981d1cc8072c074e604224e9`) has since merged too — see
`docs/DECISION_LOG.md` ("Roadmap PR19A complete: PR19A1 + PR19A2 + PR19A3
merged" and "Roadmap PR19B merged: Exception Record closed; Roadmap PR19
fully complete") for the full record. **Roadmap PR20 (Equipment Master
Import) is also now fully complete and has moved off this table:** the
design (GitHub PR #89), PR20A–PR20F (GitHub PR #90, #91, #93, #94, #95,
#96), and two governance syncs (GitHub PR #88, #92) are all merged — see
"Roadmap PR20 complete" above and `docs/DECISION_LOG.md` ("Roadmap PR20
complete: PR20A–PR20F merged") for the full record. **Roadmap PR21
(Legacy Receive and Issue History Import) is also now fully complete and
has moved off this table:** the design (GitHub PR #98, #99), three Owner
Decision Closure rounds (GitHub PR #101, #102, #106), PR21-Foundation
(#100), PR21A–C (#103, #104, #105), and PR21D1/D2/E0/E (#107, #108,
#109, #110) are all merged — see "Roadmap PR21 complete" above and
`docs/DECISION_LOG.md` ("Roadmap PR21 complete: PR21D1–PR21F merged")
for the full record. This table now begins with PR22, the next planned
Roadmap item; PR19B's own historical relative-ordering note is preserved
above.

## Scope guardrails for the planned sequence

- Reporting distinguishes the actual transaction timestamp, `business_date`,
  and `shift`. `shift` is operational/reporting metadata, not an equipment
  lifecycle state. Do not create separate Day and Night transaction tables.
- Reports cover Receive, Issue, and Equipment Verify Checklist, filterable by
  date and shift, with PDF, Excel, and print-ready hard-copy output.
- Version 1 legacy history migration includes only the AppSheet equipment
  receive-data and equipment issue-data sheets. Equipment Verify Checklist
  history is excluded unless a later approved decision changes the scope.
- PR19B was a frontend-only workflow-review skeleton (no file upload, no
  parsing, no validation/dry-run/import execution, no database change),
  merged as GitHub PR #80. **This described PR19B's own scope at the time
  it merged; PR19B's mock workflow (`MockImportClient`, its fixtures, the
  skeleton banner) has since been removed entirely by Roadmap PR21E
  (GitHub PR #110) — both real import categories now go through the real
  backend.**
- PR20 Equipment Master Import (**COMPLETE / MERGED**, PR20A–PR20F) covers
  BCM, Item Number, equipment attributes, existing hospital QR linkage,
  equipment duplicate detection, and equipment-record validation. It does
  not own transaction BME or Ward data, and does not implement Receive
  History or Issue History import (PR21, also complete).
- PR21 Legacy Receive and Issue History Import (**COMPLETE / MERGED**,
  design #98/#99 through PR21E #110) covers Receive and Issue history,
  legacy BME-name preservation and user mapping, Ward normalization and
  mapping, transaction-row duplicate detection, and transaction source
  references — delivered as one combined `legacy_transaction_history`
  workbook/session, SDC excluded from V1, no Issue↔Receive pairing
  (deferred to PR22), no mutation of current Equipment state.
- PR22 Legacy Data Validation and Reconciliation covers cross-import
  validation, reconciliation, source traceability verification, duplicate
  review, and unified legacy/new history validation.
- Legacy migration occurs before Go-live and does not redesign or replace
  existing hospital QR codes.
- The only equipment lifecycle states remain `AVAILABLE_AT_POOL`,
  `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, and `DECOMMISSIONED`. Cleaning is
  not a state.

## Unscheduled confirmed work

- Standby Snapshots remain separate future work.
- Broader PR15 observability items (metrics, tracing, dashboards, centralized
  aggregation, and alerting) remain open until assigned to a focused slice or
  removed by an explicit governance decision.
- Create-from-import deferred from PR12 remains separate from the approved
  legacy migration sequence above.
