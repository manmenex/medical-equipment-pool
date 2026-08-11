# Roadmap Status

**Purpose:** Concise live status dashboard.
**Authority:** Status summary only. [`ROADMAP.md`](ROADMAP.md) and
[`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md)
control detailed ordering, scope, dependencies, and acceptance criteria.
**Update trigger:** A Roadmap item, design, implementation, or baseline changes.

## Current baseline

`04f5bf5c76b51744981d1cc8072c074e604224e9` — the real squash-merge SHA of
GitHub PR #80, Roadmap PR19B (Legacy Import Frontend Skeleton), merged on
top of `7f13a1e85e9b6a4828170c4b12bc2be27b15de39` (GitHub PR #86, Roadmap
PR19A3). PR19B's final independently reviewed feature-branch head was
`5edf1bfd8de7013eb74f300193456c9e5c0f0332`, which received **APPROVE**
with CI green (6/6) — **that reviewed head is not the baseline**; the
squash commit actually landed on the base branch, `04f5bf5c...`, is. With
PR19B merged, both slices of the Roadmap PR19 approved split — PR19A
(backend: PR19A1 #84, PR19A2 #85, PR19A3 #86, all merged) and PR19B
(frontend skeleton: #80, merged) — are complete. **Roadmap PR19 (Legacy
Import Foundation, backend + frontend skeleton) is now fully complete.**
See "Roadmap PR19 split" below for the full detail and
`docs/DECISION_LOG.md` ("Roadmap PR19B merged: Exception Record closed;
Roadmap PR19 fully complete") for the closure record. The older baseline
narrative immediately below (`7f13a1e...`, PR19A3) is retained as
provenance for Roadmap PR19A, and the one below that (`729d1aa...`,
PR18F) is retained as provenance for Roadmap PR18 and earlier.

`7f13a1e85e9b6a4828170c4b12bc2be27b15de39` — squash commit of GitHub PR
#86, the Roadmap PR19A3 implementation (Dry-run, Execution, Recovery,
Retention). It follows GitHub PR #85 (`7e5e6f2d`, Roadmap PR19A2 —
Validation Foundation) and GitHub PR #84 (`7d589860`, Roadmap PR19A1 —
Schema / Session / Source Foundation), both based on GitHub PR #83
(`38a21e8c`, the architecture-approved PR19A design). **All three of
PR19A's implementation slices are merged — Roadmap PR19A (Legacy Import
Foundation, backend) is now fully complete.** Superseded by the current
baseline above (`04f5bf5c...`) once PR19B also merged.

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
by PR19A; that remains future Roadmap PR20/PR21 scope. PR19B
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
real squash-merge SHA `04f5bf5c76b51744981d1cc8072c074e604224e9` (see the
"Current baseline" section above). GitHub PR #81, an earlier unsplit
PR19A candidate, was closed without merging, superseded by
PR19A1/PR19A2/PR19A3. **PR19A and PR19B are both complete and merged;
Roadmap PR19 (Legacy Import Foundation, backend + frontend skeleton) as a
whole is now fully complete.** PR19B remains a frontend-only
workflow-review skeleton — no real file upload, workbook parsing,
validation/dry-run/import execution, or production legacy dataset
adapter is implemented; concrete legacy dataset import (Equipment Master,
Receive History, Issue History) remains future Roadmap PR20/PR21 scope,
not yet started. The Exception Record governing this split
(`docs/DECISION_LOG.md`) is now closed — see "Roadmap PR19B merged:
Exception Record closed; Roadmap PR19 fully complete" there for the
closure record and the required-steps evidence.

Roadmap numbering and GitHub PR numbering are independent. In particular,
GitHub PR #18 was the Knowledge & Governance Foundation; it was not Roadmap
PR18.

## Current and planned sequence

| Sequence | Roadmap item | Status |
|---|---|---|
| TBD | PR20 — Equipment Master Import | Planned; not started. Depends on PR19A only — `docs/audits/04-consolidated-implementation-plan.md` records PR20's dependency as "PR19A (the backend import framework; PR19B is a frontend preview only and is not a dependency)", so PR19B's merge does not change PR20's readiness. A historical, still-unresolved question of *relative sequencing* (not a hard dependency) between PR19B and PR20 was left TBD pending an Owner Decision while PR19B was still provisional (see below); PR19B has since merged, but that TBD relative-ordering question was not itself an implementation blocker and remains unresolved — no Owner Decision has been made, and this governance sync does not create one. |
| After PR20 | PR21 — Legacy Receive and Issue History Import | Planned; **depends on PR20** (`docs/audits/04-consolidated-implementation-plan.md`: "Dependencies: PR19A, PR20") |
| After PR20, PR21 | PR22 — Legacy Data Validation and Reconciliation | Planned; depends on PR20 and PR21 |
| After PR22 | PR23 — Cutover Readiness | Planned |
| After PR19–PR23 | PR24 — Go-live / deployment | Planned; blocked by PR19–PR23 |

**Historical note on PR19B/PR20 relative ordering:** while PR19B was still
a provisional, unreviewed Draft (GitHub PR #80), this table carried both a
PR19B row and a PR20 row with no relative numeric order between them,
noting the sequencing was undecided pending an Owner Decision. PR19B has
since been independently reviewed and merged (squash SHA
`04f5bf5c76b51744981d1cc8072c074e604224e9`; see "Current baseline" above
and "Roadmap PR19 split" below), so its own row has moved off this table
the same way PR19A's did. The relative-ordering question itself was never
about a hard dependency — PR20 has only ever depended on PR19A, not
PR19B — and remains open exactly as before: no Owner Decision has
resolved it, and this governance sync does not introduce one. PR21
through PR24's ordering is preserved as-is because it reflects an
existing authoritative dependency chain
(`docs/audits/04-consolidated-implementation-plan.md` Part D, Group 8:
PR21 depends on PR20; PR22 depends on PR20 and PR21; PR24 is blocked by
PR19–PR23), not a new sequencing decision introduced by this governance
sync.

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
fully complete") for the full record. This table now begins with PR20,
the next planned Roadmap item; PR19B's own historical relative-ordering
note is preserved above.

## Scope guardrails for the planned sequence

- Reporting distinguishes the actual transaction timestamp, `business_date`,
  and `shift`. `shift` is operational/reporting metadata, not an equipment
  lifecycle state. Do not create separate Day and Night transaction tables.
- Reports cover Receive, Issue, and Equipment Verify Checklist, filterable by
  date and shift, with PDF, Excel, and print-ready hard-copy output.
- Version 1 legacy history migration includes only the AppSheet equipment
  receive-data and equipment issue-data sheets. Equipment Verify Checklist
  history is excluded unless a later approved decision changes the scope.
- PR19B is a frontend-only workflow-review skeleton: no file upload, no
  parsing, no validation/dry-run/import execution, no database change. Its
  Equipment Master/Receive/Issue History category labels preview PR20/PR21
  scope and are not an implemented capability.
- PR20 Equipment Master Import covers BCM, Item Number, equipment attributes,
  existing hospital QR linkage, equipment duplicate detection, and
  equipment-record validation. It does not own transaction BME or Ward data.
- PR21 Legacy Receive and Issue History Import covers Receive and Issue
  history, legacy BME-name preservation and user mapping, Ward normalization
  and mapping, transaction-row duplicate detection, and transaction source
  references.
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
