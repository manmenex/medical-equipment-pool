# Context

**Purpose:** Current project state — the most volatile document in the
knowledge layer
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

Current baseline: `73652b062fb2ad6fdab4f7bbc0b743ff5f548e86` on
`claude/medical-equipment-pool-0c7fz0` — the real squash-merge SHA of
GitHub PR #135, "PR24D-L1 — Local Docker Staging/UAT Foundation" (three
independent-review fix rounds: Redis non-blocking-startup correction,
structural single-backend scale guard via a fixed `container_name`, and
two stale-documentation-wording cleanups — see `docs/DECISION_LOG.md`
for the exact before/after text), squash-merged on top of
`7e2bfb2001642ea9a9754310b85d1911b7b2be5c` (GitHub PR #134, PR24D —
Post-Merge Governance Close-out, now historical/superseded by this
baseline). PR #135's final reviewed feature-branch head
(`85c0d0075a141ae50cba4a63f96b8cc39896de0f`; independent Final Merge
Gate: zero reviews, zero comments, zero review threads, CI green 6/6 on
that exact head) — **that reviewed head is not the baseline**; the
squash commit actually landed on the base branch, `73652b0...`, is,
independently verified tree-identical to that reviewed head with sole
parent `7e2bfb2...` confirmed. Per this repository's standing process,
**no separate "baseline adoption" PR is created** — the squash SHA
became authoritative immediately upon merge, recorded here by this PR
(PR24D-L2, the next PR that legitimately touches these governance
files), consistent with this repository's squash-baseline discipline.
**PR24D (CI/CD & Staging) code/tooling is merged and complete.
Operational managed-Staging evidence remains pending:** the manual `cd-staging.yml`
workflow has not yet been executed even once, no hosting provider has
been selected, no real persistent managed-Staging environment exists,
and the real PR24C backup/restore rehearsal against a managed-Staging
target has not yet been performed (see
`docs/runbooks/PR24_STAGING_DEPLOYMENT_RUNBOOK.md`). OD-PR24-1 remains
resolved at the architecture-class level (Managed Application Platform +
Managed PostgreSQL) — the specific provider is an
execution/configuration decision within that approved class, not a
reopened Owner Decision; any paid resource provisioning still requires
explicit Owner approval. **PR24E (UAT Readiness) remains not started**,
gated on real managed-Staging availability and sufficient operational
deployment/backup evidence; PR24F (Pilot Execution) and PR24G
(Production Go-Live Governance) also remain not started. **PR24 overall
is in progress, not complete.** Real Pilot execution, Production
cutover, AppSheet's actual read-only transition, a selected commercial
provider, and a real managed-Staging-class backup/restore rehearsal
have **not** occurred.

**Owner direction (recorded 2026-08-30): no current budget for paid
cloud infrastructure.** The Owner explicitly approved a zero-cost
**local execution of the existing Staging/UAT environment class** using
Docker on a Windows PC, LAN-reachable by other authorized devices, plus
an installer/deployment mechanism (Setup.exe deferred until a
script-based installer engine is proven). **This is not a fourth
environment** — OD-PR24-4's taxonomy (Development, Staging/UAT,
Production) is unchanged. **PR24D-L1 (Local Docker Staging/UAT
Foundation) is COMPLETE / MERGED** (GitHub PR #135, squash SHA
`73652b062fb2ad6fdab4f7bbc0b743ff5f548e86`, current baseline above):
`deployment/local-staging/compose.yml` (PostgreSQL/Redis never
LAN-exposed, exactly one backend replica/Uvicorn worker, no committed
secrets/default credentials/demo data) plus a `COOKIE_SECURE` backend
setting (`backend/app/core/config.py`) decoupling the refresh-token
cookie's `Secure` attribute from `ENVIRONMENT` for this local mode only
— real Production is unaffected. **PR24D-L2 (Local Staging/UAT
Installer & Operations Engine) is now in progress**: the script-based
installer (`install.ps1`/`start.ps1`/`stop.ps1`/`status.ps1`/
`update.ps1`/`uninstall.ps1` + shared `lib/Common.ps1`), reusing the
existing PR24B Administrator bootstrap and PR24D explicit-migration
mechanisms unchanged, no Setup.exe. See
`docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md` §32 for the
full architecture, the still-ahead PR24D-L3 scope, and the binding
"LOCAL evidence, never real managed-Staging evidence" classification —
local execution does not satisfy PR24E's real managed-Staging gate.

**Roadmap PR22 (Legacy Data Validation and Reconciliation) is now fully
complete** — architecture design (GitHub PR #112), all seven Owner
Decisions OD-PR22-1 through OD-PR22-7 (GitHub PR #115), every
implementation slice PR22B–PR22F (GitHub PR #116/#117/#118/#119/#120:
schema/run-snapshot foundation, deterministic analysis engine, finding
review/disposition API, sign-off + concurrency/audit, frontend
integration), and governance close-out PR22G (GitHub PR #121) are all
merged. See `docs/ROADMAP.md`'s "Current baseline" section for the
full slice-by-slice chronology.

**Roadmap PR23 (Cutover Readiness)'s first slice, PR23A (Architecture &
Operational Design), is merged** (GitHub PR #122, squash SHA
`7ca9c87b4c525a1835403dac5d08e6e1be79d33b`, historical) —
`docs/design/PR23_CUTOVER_READINESS_PLAN.md`, design/governance only,
zero `backend/**`/`frontend/**`/`alembic/**`/`tests/**` change. **The
PR23 Owner Decision Closure round is also merged** (GitHub PR #123,
squash SHA `22ec7a25d686b0cd37d2a366172cb31a49eebff8`, historical): the
Repository Owner approved all six Owner Decisions PR23A identified
(OD-PR23-1 through OD-PR23-6 — source-of-truth transition,
current-state/open-transaction handling, Go/No-Go and rollback
authorization, rollback boundary, pilot scope, persisted evidence
model) per Recommendation, with an explicit Owner clarification for
OD-PR23-5's Pilot Ward selection (resolved from existing Ward/
department master data via the legacy `แผนกที่ยืม` reference, never a
new auto-created Ward), non-fixed criteria-based Pilot duration/exit
criteria, and the explicit no-Ward-to-Ward-tracking clarification (see
`docs/design/PR23_CUTOVER_READINESS_PLAN.md` §26). That closure round
released the fail-closed PR23B+ implementation-authorization gate
(§27). **PR23B (Cutover Readiness Evidence Foundation) is also
merged** (GitHub PR #124, squash SHA
`833f6758a93a78398207d64fbefa65ff2802cf46`, historical): an additive
backend-only persistence foundation implementing OD-PR23-6, hardened by
one fix round (server-derived `database_migration_head`; a bound
evidence provenance chain), with no readiness-gate evaluation, Go/No-Go
logic, frontend, pilot execution, cutover execution, rollback
execution, or Ward-to-Ward transfer tracking. **PR23C (Readiness Gate
Evaluation) is also merged** (GitHub PR #125, squash SHA
`c10f5082fdc5cb7fd66615fe25516a4982297026`, historical): a read-only
Gates A-F BLOCKER/WARNING/INFO evaluation endpoint against a completed
run's persisted evidence; no mutation, no persisted gate/decision
model, no Go/No-Go decision, hardened by one fix round (Gate B
dataset-type check, both at the evaluator and the PR23B completion
boundary). **PR23D (Go/No-Go Decision + Current-State Re-Issue
Support) is also merged** (GitHub PR #126, squash SHA
`2da80231d4f037136b291863e379e739aa2905dd`, historical): an immutable
`CutoverGoNoGoDecision` evidence record (Gate G) with a fresh Gates A-F
re-evaluation at decision time; no current-state re-issue write
endpoint (the existing `POST /borrow` Issue workflow already covers
it), hardened by one fix round (a whole-schema `ON DELETE RESTRICT`
foreign-key-count regression test correction). **PR23E (Frontend /
Operator Workflow) is also merged** (GitHub PR #127, squash SHA
`8644536403eeec269e6dadf835f1bda3844b6cce`, historical): Thai-first
operator UI over the merged PR23B-D backend that only reads and
renders backend-computed readiness state, no new backend route or
migration. **PR23F (Cutover Runbook + Final Governance Close-out) is
also merged** (GitHub PR #128, squash SHA
`f35fe716d57c51042d86a661657f679799b6a9e3`, historical, see above): a
documentation-only operational runbook
(`docs/runbooks/PR23_CUTOVER_RUNBOOK.md`) plus the final governance
close-out — **Roadmap PR23 overall is now fully implementation-
complete.** **The Production Deployment & Go-Live Architecture
Planning round is also merged** (GitHub PR #129, squash SHA
`599478992de363e1eda2fe8005ff79d565dee76d`, historical, see
above; `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md`,
including Fix Round 1's §15A liveness/readiness contract): design/
Owner-Decisions only. **The PR24 Owner Decision Closure round is also
merged** (GitHub PR #130, squash SHA
`f64f7d148ba956adef43c5d363ad52680398541c`, historical, see above),
recording all six Owner Decisions it raised (OD-PR24-1 through
OD-PR24-6, §28) as Owner-approved. **PR24B (Deployment Foundation) has
since merged too** (GitHub PR #131, squash SHA
`d4a40349f62d76d129dcc6f1feea3e7e8fc8f28d`, historical) — fail-closed
readiness endpoint, production-safe admin bootstrap script, scheduler
single-instance deployment invariant, fail-closed production
configuration checks; no infrastructure provisioned. **PR24C (Backup &
Restore) has since merged too** (GitHub PR #132, squash SHA
`cd9764ef5ba5e56062ee41266c8d96e50f1152c0`, historical — superseded by
PR24D). **PR24D (CI/CD & Staging) code/tooling has since merged too**
(GitHub PR #133, squash SHA `84144f096aacb9e2687422c7cd84cc1354346aa7`,
historical — superseded by GitHub PR #134's governance close-out, see
"Current baseline" above) — operational Staging evidence remains
pending. **PR24 overall is now in progress, not yet complete; PR24E is
not started.** See "Current work" below.

`d64d50d09cdf8ed7ddc1f5116b38805dfcbc7810` (GitHub PR #110, Roadmap
PR21E — Legacy History Frontend Real Integration) is now historical,
superseded first by `e07a36a...` (GitHub PR #111, PR21F), then
`c924d8b...` (GitHub PR #112, PR22A), then `c802d66...` (GitHub PR #113),
then `f03af893...` (GitHub PR #115), then `c5e750c...` (GitHub PR #116),
then `b45cf750...` (GitHub PR #117), then `966d7a71...` (GitHub PR #118),
then `896d92f8...` (GitHub PR #119), then `76040d5e...` (GitHub PR
#120), then `527ffc4...` (GitHub PR #121), then `7ca9c87...` (GitHub PR
#122), then `22ec7a25...` (GitHub PR #123), then `833f6758...` (GitHub
PR #124), and now by this baseline. With
PR21E merged, **Roadmap PR21 (Legacy Receive and Issue History Import)
is now fully complete** — every implementation slice (Foundation, A, B,
C, D1, D2, E0, E) is merged. See `docs/DECISION_LOG.md` ("Roadmap PR21
complete: PR21D1–PR21F merged") for the closure record.

This baseline follows `78eeea7827c53443f34de9e516573c2ed7c59581` (GitHub
PR #109, PR21E0 — Legacy Import Operator API Surface), `c4788de06bed9a13aa5ec981fb8e19c67bc5720b`
(GitHub PR #108, PR21D2 — Historical Event Execution),
`50b9e77269b238d95fb34b28d0bc223a369951e2` (GitHub PR #107, PR21D1 —
Combined Canonical Adapter + Source Admission), and the earlier PR21A/B/C
and design/Owner Decision chain — see `docs/ROADMAP.md`'s Completed table
for every squash SHA. That chain in turn follows
`2743af849702ef551927b9c362421df08c80b5d9` (GitHub PR #96, Roadmap PR20F —
Equipment Master Import complete) and `04f5bf5c76b51744981d1cc8072c074e604224e9`
(GitHub PR #80, PR19B — now historical: its mock workflow has been fully
removed by PR21E). **Roadmap PR19, PR20, and PR21 are all now fully
complete.** Roadmap PR17 (Operational Reports), Roadmap PR16 (Reporting
Foundation), and Roadmap PR15B Schema Hygiene remain implemented.

Roadmap PR21 (Legacy Receive and Issue History Import) delivers the legacy
transaction-history import workflow end-to-end, as one combined
`legacy_transaction_history` workbook/session (not two separate Receive/
Issue imports): the `LegacyEquipmentEvent` schema/provenance foundation
(PR21A), canonical Issue/Receive parsers (PR21B/PR21C, SDC sheets excluded
from V1 by explicit Owner decision), the combined adapter and PR21-specific
upload allowance (PR21D1), historical event execution — `ISSUE`/`RECEIVE`
events, never `BorrowTransaction` rows, never Equipment lifecycle mutation
(PR21D2), the Administrator-only migration-authority approval API and
PR21-specific dry-run-plan HTTP surface (PR21E0), and real operator-facing
frontend integration replacing the PR19B mock workflow (PR21E). **PR21
does not pair Issue and Receive events, does not implement MEMS or Recall
Monitor, and does not perform cross-import reconciliation** — pairing and
reconciliation are Roadmap PR22-or-later's own scope. See
`docs/DECISION_LOG.md` ("Roadmap PR21 complete: PR21D1–PR21F merged") for
the full slice-by-slice record.

## Current work

Roadmap PR21 (Legacy Receive and Issue History Import) is now fully
complete — implementation (PR21-Foundation #100, PR21A #103, PR21B #104,
PR21C #105, PR21D1 #107, PR21D2 #108, PR21E0 #109, PR21E #110) and
governance closure (PR21F, GitHub PR #111, squash SHA
`e07a36aa8482b7b97368a6adb9cfcc81c93d0ee0`) are both merged. **Roadmap
PR22 (Legacy Data Validation and Reconciliation)'s architecture design
has merged** — `docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md`,
GitHub PR #112 (PR22A, three independent-review fix rounds folded in:
Owner Decision numbering/cross-reference sweep; the new §9.J temporal
coverage boundary and OD-PR22-7; the sign-off-ambiguity resolution
blocking all final sign-off until OD-PR22-7 resolves), squash SHA
`c924d8ba2c8c5d933ea36ea3d488e2550615df40`, sole parent `e07a36a...`
(PR21F). The post-PR22A governance synchronization (GitHub PR #113) has
since also merged — squash SHA `c802d66c9d1e5395cd20591c451ebdc0cefbf7df`,
docs-only. **All seven Owner Decisions (OD-PR22-1 through OD-PR22-7) are
RESOLVED / OWNER APPROVED**, recorded in the design document's own §36
by GitHub PR #115 (the PR22 Owner Decision Closure round, the Owner
approved all seven per Recommendation), squash SHA
`f03af893d727b221bd941466d83e5eceb9eb596a` (see "Current baseline"
above). No `backend/**`, `frontend/**`, `alembic/**`, or `tests/**` file
was touched by the design, the governance sync, or the closure round
itself. **PR22B** (Reconciliation Schema + Run/Snapshot Foundation) —
the first implementation slice — **is merged** (GitHub PR #116, squash
SHA `c5e750cecd7458e9570c6dc1679abeacde0da369`, see "Current baseline"
above): `LegacyMigrationAuthorityCoverage` (OD-PR22-7's governed
two-boundary temporal-coverage artifact, closed `approval_basis`
domain), `LegacyReconciliationRun` (`pending`/`running`/`completed`/
`failed` status, OD-PR22-3's forward-only `supersedes_run_id`
supersession), `LegacyReconciliationFinding` (bounded, DB-unconstrained
`code`; closed `severity`; OD-PR22-2's four-value disposition domain),
`LegacyReconciliationFindingEvent` (provenance junction table),
`LegacyReconciliationSignOff` (table shape only, no sign-off logic),
and `LegacyBMEUserAlias` (OD-PR22-4's display-only BME-name-to-User
mapping). Schema/persistence only — no analysis/detection engine, no
API, no frontend, no disposition-mutation service, and no sign-off
logic existed in that slice. **PR22C** (Deterministic
Reconciliation Analysis Engine) — the analysis engine that executes a
`LegacyReconciliationRun` against one consistent PostgreSQL
`REPEATABLE READ` snapshot and persists immutable findings via nine
deterministic rule modules — **is merged** (GitHub PR #117, squash SHA
`b45cf7503a3ff941d4b65741c7ac14a0af6e7a25`, see "Current baseline"
above): zero new Alembic migrations, 54 regression tests. **PR22D**
(Finding Review / Disposition API) — read endpoints for runs/findings
plus an Administrator-only disposition-mutation endpoint (OD-PR22-5) —
**is merged** (GitHub PR #118, squash SHA
`966d7a712681e40780f954c8744a592316af56ec`, see "Current baseline"
above): zero new Alembic migrations, 47 regression tests. **PR22E**
(Reconciliation Sign-off + Concurrency/Audit) — the final
Administrator-only sign-off workflow (all eight preconditions), reusing
PR22D's own Run-row-lock-first discipline — **is merged** (GitHub PR
#119, squash SHA `896d92f8c00ee860c82892e4e4d466d5869dcf48`, see
"Current baseline" above): zero new Alembic migrations, 30 regression
tests. **PR22F** (Reconciliation Frontend Integration) — the
operator-facing UI for the PR22B-E backend (run list/detail, finding
filters incl. `code`/`severity`/`disposition`/`equipment_id`, finding
detail/evidence, Administrator-only disposition mutation and final
sign-off) — **is merged** (GitHub PR #120, squash SHA
`76040d5e87223767c9dbe36eb67c6a156af12c0c`, see "Current baseline"
above): zero new backend routes, schema, or business logic; the
frontend never reimplements sign-off eligibility, every mutation is
submitted to the backend and every response/error code decides the
outcome. **PR22G** (governance close-out) — **is merged** (GitHub PR
#121, squash SHA `527ffc48966d7e5cda16a869f0ae464de8b7512a`, see
"Current baseline" above). **Roadmap PR22 (Legacy Data Validation and
Reconciliation) is now fully complete.** **Roadmap PR23 (Cutover
Readiness)'s first slice, PR23A** (Architecture & Operational Design)
— **is merged** (GitHub PR #122, squash SHA
`7ca9c87b4c525a1835403dac5d08e6e1be79d33b`, historical). **The PR23
Owner Decision Closure round is also merged** (GitHub PR #123, squash
SHA `22ec7a25d686b0cd37d2a366172cb31a49eebff8`, historical): the
Repository Owner has approved all six Owner Decisions PR23A identified
(OD-PR23-1 through OD-PR23-6), releasing the fail-closed PR23B+
implementation-authorization gate. **PR23B (Cutover Readiness Evidence
Foundation) is also merged** (GitHub PR #124, squash SHA
`833f6758a93a78398207d64fbefa65ff2802cf46`, historical) — an additive
backend-only persistence foundation (`CutoverReadinessRun` model,
migration `0021_cutover_readiness`, CRUD, minimal Administrator-only
API) implementing OD-PR23-6's approved persisted-evidence model,
hardened by one fix round. **PR23C (Readiness Gate Evaluation) is also
merged** (GitHub PR #125, squash SHA
`c10f5082fdc5cb7fd66615fe25516a4982297026`, historical) — a read-only
Gates A-F BLOCKER/WARNING/INFO evaluation endpoint against a completed
run's persisted evidence, hardened by one fix round. **PR23D (Go/No-Go
Decision + Current-State Re-Issue Support) is also merged** (GitHub PR
#126, squash SHA `2da80231d4f037136b291863e379e739aa2905dd`, historical)
— an immutable `CutoverGoNoGoDecision` evidence record (Gate G) with a
fresh Gates A-F re-evaluation at decision time. **PR23E (Frontend /
Operator Workflow) is also merged** (GitHub PR #127, squash SHA
`8644536403eeec269e6dadf835f1bda3844b6cce`, historical) — Thai-first
operator UI over the merged PR23B-D backend. **PR23F (Cutover Runbook +
Final Governance Close-out) is also merged** (GitHub PR #128, squash
SHA `f35fe716d57c51042d86a661657f679799b6a9e3`, historical) —
documentation-only operational runbook plus final governance
close-out. **Roadmap PR23 overall is now fully implementation-
complete. The Production Deployment & Go-Live Architecture Planning
round is also merged** (GitHub PR #129, squash SHA
`599478992de363e1eda2fe8005ff79d565dee76d`, historical; design/
Owner-Decisions only,
`docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md`). **The PR24
Owner Decision Closure round is also merged** (GitHub PR #130, squash
SHA `f64f7d148ba956adef43c5d363ad52680398541c`, historical) — all six
Owner Decisions (OD-PR24-1 through OD-PR24-6, §28) Owner-approved.
**PR24B (Deployment Foundation) has since merged too** (GitHub PR
#131, squash SHA `d4a40349f62d76d129dcc6f1feea3e7e8fc8f28d`, historical).
**PR24C (Backup & Restore) has since merged too** (GitHub PR #132,
squash SHA `cd9764ef5ba5e56062ee41266c8d96e50f1152c0`, historical —
superseded by PR24D). **PR24D (CI/CD & Staging) code/tooling has since
merged too** (GitHub PR #133, squash SHA
`84144f096aacb9e2687422c7cd84cc1354346aa7`, historical — see "Current
baseline" above) — operational managed-Staging evidence remains
pending. **PR24 overall is now in progress; PR24E is not started, gated
on real managed-Staging availability and sufficient operational
evidence.**

## Next sequence

Roadmap PR19, PR20 (Equipment Master Import), PR21 (Legacy Receive and
Issue History Import), and now **PR22 (Legacy Data Validation and
Reconciliation) are all fully complete** — architecture design (GitHub
PR #112), all seven Owner Decisions (GitHub PR #115), every
implementation slice PR22B–PR22F (GitHub PR #116/#117/#118/#119/#120),
and governance close-out PR22G (GitHub PR #121, squash SHA
`527ffc48966d7e5cda16a869f0ae464de8b7512a`) are all merged — per
`docs/audits/04-consolidated-implementation-plan.md` Part D, PR22
depended on PR20 and PR21 (both satisfied) and covered: cross-import
validation, reconciliation, source traceability verification,
duplicate review, and unified legacy/new history validation, including
Issue↔Receive pairing (resolved as OD-PR22-1). **Roadmap PR23 (Cutover
Readiness)'s first slice, PR23A (Architecture & Operational Design),
has merged (GitHub PR #122); all six PR23 Owner Decisions are
Owner-approved via the PR23 Owner Decision Closure round, itself now
merged (GitHub PR #123); PR23B (Cutover Readiness Evidence Foundation)
has since merged too (GitHub PR #124); PR23C (Readiness Gate
Evaluation) has since merged too (GitHub PR #125); PR23D (Go/No-Go
Decision + Current-State Re-Issue Support) has since merged too (GitHub
PR #126); PR23E (Frontend / Operator Workflow) has since merged too
(GitHub PR #127); and PR23F (Cutover Runbook + Final Governance
Close-out) has since merged too (GitHub PR #128). **Roadmap PR23
overall is now fully implementation-complete.** The next planned item
is the Production Deployment & Go-Live Architecture Planning round
— see "Current baseline" and "Current work" above.

1. PR19A — Legacy Import Foundation (backend) — **complete.**
2. PR19B — Legacy Import Frontend Skeleton — **complete, merged as GitHub
   PR #80; its mock workflow has since been fully removed by PR21E.**
3. PR20 — Equipment Master Import (PR20A–PR20F) — **complete**, merged as
   GitHub PR #90/#91/#93/#94/#95/#96 (design GitHub PR #89; governance
   syncs GitHub PR #88/#92).
4. PR21 — Legacy Receive and Issue History Import (Foundation, A, B, C,
   D1, D2, E0, E) — **complete**, merged as GitHub PR
   #100/#103/#104/#105/#107/#108/#109/#110 (design GitHub PR #98/#99;
   Owner Decision Closure rounds GitHub PR #101/#102/#106).
5. PR22 — Validation and reconciliation: cross-import validation,
   reconciliation, source traceability verification, duplicate review, and
   unified legacy/new history validation. **Complete** — architecture
   design (GitHub PR #112), all seven Owner Decisions resolved (GitHub PR
   #115), PR22B (GitHub PR #116), PR22C (GitHub PR #117), PR22D (GitHub PR
   #118), PR22E (GitHub PR #119), PR22F (GitHub PR #120), and governance
   close-out PR22G (GitHub PR #121, squash SHA
   `527ffc48966d7e5cda16a869f0ae464de8b7512a`) are all merged.
6. PR23 — Cutover readiness. **PR23A (Architecture & Operational Design)
   is COMPLETE / MERGED** (GitHub PR #122, squash SHA
   `7ca9c87b4c525a1835403dac5d08e6e1be79d33b`, historical) —
   `docs/design/PR23_CUTOVER_READINESS_PLAN.md`, design/governance only.
   **PR23 Owner Decision Closure is COMPLETE / MERGED** (all six
   OD-PR23-1 through OD-PR23-6 Owner-approved, GitHub PR #123, squash
   SHA `22ec7a25d686b0cd37d2a366172cb31a49eebff8`, historical).
   **PR23B (Cutover Readiness Evidence Foundation) is COMPLETE / MERGED**
   (GitHub PR #124, squash SHA
   `833f6758a93a78398207d64fbefa65ff2802cf46`, historical).
   **PR23C (Readiness Gate Evaluation) is COMPLETE / MERGED** (GitHub
   PR #125, squash SHA `c10f5082fdc5cb7fd66615fe25516a4982297026`,
   historical). **PR23D (Go/No-Go Decision + Current-State Re-Issue
   Support) is COMPLETE / MERGED** (GitHub PR #126, squash SHA
   `2da80231d4f037136b291863e379e739aa2905dd`, historical).
   **PR23E (Frontend / Operator Workflow) is COMPLETE / MERGED**
   (GitHub PR #127, squash SHA
   `8644536403eeec269e6dadf835f1bda3844b6cce`, historical).
   **PR23F (Cutover Runbook + Final Governance Close-out) is COMPLETE /
   MERGED** (GitHub PR #128, squash SHA
   `f35fe716d57c51042d86a661657f679799b6a9e3`, historical).
   **Roadmap PR23 overall is now fully implementation-complete.**
7. PR24 — Go-live / deployment. Dependency (PR19-PR23) satisfied.
   **Architecture & Go-Live Planning is COMPLETE / MERGED** (GitHub PR
   #129, squash SHA `599478992de363e1eda2fe8005ff79d565dee76d`,
   historical; `docs/design/PR24_PRODUCTION_DEPLOYMENT_GO_LIVE_PLAN.md`,
   including Fix Round 1's §15A liveness/readiness contract). **PR24
   Owner Decision Closure is COMPLETE / MERGED** (GitHub PR #130, squash
   SHA `f64f7d148ba956adef43c5d363ad52680398541c`, historical; all
   six Owner Decisions OD-PR24-1 through OD-PR24-6 Owner-approved, §28).
   **PR24B (Deployment Foundation) is COMPLETE / MERGED** (GitHub PR
   #131, squash SHA `d4a40349f62d76d129dcc6f1feea3e7e8fc8f28d`,
   historical) — fail-closed readiness endpoint, production-safe admin
   bootstrap script, scheduler single-instance deployment invariant,
   fail-closed production configuration checks; no infrastructure
   provisioned. **PR24C (Backup & Restore) is COMPLETE / MERGED**
   (GitHub PR #132, squash SHA
   `cd9764ef5ba5e56062ee41266c8d96e50f1152c0`, historical — superseded by
   PR24D) — `pg_dump`/`pg_restore`/prune tooling, CI-proven round trip,
   operator runbook; no real Staging rehearsal yet. **PR24D (CI/CD &
   Staging) code/tooling COMPLETE / MERGED** (GitHub PR #133, squash SHA
   `84144f096aacb9e2687422c7cd84cc1354346aa7`, historical — superseded
   by GitHub PR #134's governance close-out, itself now historical —
   superseded by GitHub PR #135's PR24D-L1, current baseline
   `73652b062fb2ad6fdab4f7bbc0b743ff5f548e86`) — immutable-artifact
   build/scan/migrate/deploy/verify mechanism, including two
   independent-review fix rounds, proven against an ephemeral
   CI-provisioned target only; manual workflow execution pending, no
   provider selected, no real Staging infrastructure provisioned, no
   real backup/restore rehearsal performed.

Legacy migration and reconciliation are mandatory before PR24.

## Current scope boundaries

- Product: Medical Equipment Pool, not MEMS or Recall Monitor.
- States: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`,
  `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`; cleaning is not a state.
- Shift: reporting/operational metadata in one model, not separate Day/Night
  tables and not a lifecycle state.
- Version 1 legacy history: equipment receive-data and equipment issue-data
  sheets only; Equipment Verify Checklist history excluded.
- QR: preserve existing hospital QR codes; do not redesign the QR system.
- Rules: backend/service/API authorities own business behavior; frontend gates
  are usability only.

## Current risks and unresolved design details

- Branch protection is not enabled; required CI remains a documented manual
  merge gate.
- The default branch still has a temporary `claude/*` name.
- PR18A Owner Decisions #1 and #3 are resolved and implemented by PR18B: all
  matching filtered rows are included up to the 5,000-row synchronous bound.
  **Owner Decision #2 (branding configuration ownership) remains open** — no
  PR18 output format (Browser Print, PDF, or Excel) resolved it; every format
  uses the same interim neutral fallback, and it must be resolved before any
  future work depends on real hospital branding.
- PR19A's design (GitHub PR #83) defines the import framework and source
  mappings; **PR20's own design (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`,
  GitHub PR #89) has since defined Equipment Master matching/validation in
  full — Owner Decisions OD-1 (source schema), OD-2 (create/update field
  policy), OD-3 (BCM/Item Number identity policy), and OD-4 (CREATE Asset
  Number policy) are all RESOLVED and implemented (PR20A–PR20F, all
  merged).** **PR21's own design
  (`docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`, GitHub
  PR #98/#99) has since defined transaction BME-name/user and Ward
  mappings, event identity, and the SDC exclusion in full — all seven
  Owner Decisions (OD-PR21-0 through OD-PR21-6) are RESOLVED and
  implemented (PR21-Foundation/A/B/C/D1/D2/E0/E, all merged).** **PR22's
  own design (`docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md`,
  GitHub PR #112) has since named, scoped, and — via the PR22 Owner
  Decision Closure round — resolved cross-import validation,
  reconciliation ownership, and Issue↔Receive pairing policy: all seven
  Owner Decisions (OD-PR22-1 through OD-PR22-7) are RESOLVED / OWNER
  APPROVED. PR22B (Reconciliation Schema + Run/Snapshot Foundation) has
  since merged (GitHub PR #116); PR22C (Deterministic Reconciliation
  Analysis Engine) has since merged (GitHub PR #117); PR22D (Finding
  Review / Disposition API) has since merged (GitHub PR #118); PR22E
  (Reconciliation Sign-off + Concurrency/Audit) has since merged (GitHub
  PR #119, squash SHA `896d92f8c00ee860c82892e4e4d466d5869dcf48`); PR22F
  (Reconciliation Frontend Integration) has since merged (GitHub PR
  #120, squash SHA `76040d5e87223767c9dbe36eb67c6a156af12c0c`); PR22G
  (governance close-out) has since merged (GitHub PR #121, squash SHA
  `527ffc48966d7e5cda16a869f0ae464de8b7512a`). **Roadmap PR22 is now
  fully complete.** PR23's first slice, PR23A (Architecture &
  Operational Design), has merged (GitHub PR #122, squash SHA
  `7ca9c87b4c525a1835403dac5d08e6e1be79d33b`) and defines cutover
  evidence; all six PR23 Owner Decisions (OD-PR23-1 through OD-PR23-6)
  are Owner-approved via this PR23 Owner Decision Closure round.
  **PR23B (Cutover Readiness Evidence Foundation) has since merged
  (GitHub PR #124, squash SHA
  `833f6758a93a78398207d64fbefa65ff2802cf46`). PR23C (Readiness Gate
  Evaluation) has since merged too (GitHub PR #125, squash SHA
  `c10f5082fdc5cb7fd66615fe25516a4982297026`). PR23D (Go/No-Go Decision
  + Current-State Re-Issue Support) has since merged too (GitHub PR
  #126, squash SHA `2da80231d4f037136b291863e379e739aa2905dd`). PR23E
  (Frontend / Operator Workflow) has since merged too (GitHub PR #127,
  squash SHA `8644536403eeec269e6dadf835f1bda3844b6cce`). PR23F
  (Cutover Runbook + Final Governance Close-out) has since merged too
  (GitHub PR #128, squash SHA
  `f35fe716d57c51042d86a661657f679799b6a9e3`).**
  Roadmap PR23 overall is now fully implementation-complete — see
  "Current baseline" and "Current work" above. PR19B's category labels
  were a UI preview only and did not resolve any of this — PR20's and
  PR21's own implementations are what actually resolved it.
- PR19's approved PR19A/PR19B split (`docs/DECISION_LOG.md`, 2026-08-03) was
  an explicit Owner-approved exception to this repository's usual
  design-document-first slice precedent, since at the time no PR19 design
  document existed. PR19A's architecture design merged (GitHub PR #83), and
  all three of PR19A's own implementation slices have since merged too —
  PR19A1 (GitHub PR #84), PR19A2 (GitHub PR #85), PR19A3 (GitHub PR #86).
  **PR19A is fully complete.** PR19B's types/mock client were realigned to
  PR19A's authoritative contract, independently reviewed across three
  rounds (findings PR80-H1, PR80-H2, PR80-H1R, all resolved), and merged as
  GitHub PR #80 (squash SHA `04f5bf5c76b51744981d1cc8072c074e604224e9`).
  **PR19B is fully complete; Roadmap PR19 as a whole is now fully complete,
  and the Exception Record governing this split (`docs/DECISION_LOG.md`)
  is closed.** Before PR19B merged, a separate question of relative work
  sequencing (never a hard dependency — PR20 has only ever depended on
  PR19A) between PR19B and PR20 had not been fixed by an Owner Decision;
  PR19B has since merged, which settles which of the two came first
  without a new Owner Decision. **PR20 has since also fully completed
  (PR20A–PR20F, GitHub PR #90/#91/#93/#94/#95/#96), and Roadmap PR21
  (Legacy Receive and Issue History Import) has since fully completed too
  (PR21-Foundation/A/B/C/D1/D2/E0/E, GitHub PR
  #100/#103/#104/#105/#107/#108/#109/#110) — PR19B's own mock Receive/
  Issue workflow has been removed entirely by PR21E, and Roadmap PR22
  (Legacy Data Validation and Reconciliation) has since also fully
  completed (PR22A–PR22G, GitHub PR #112/#115/#116/#117/#118/#119/#120/
  #121); Roadmap PR23 (Cutover Readiness)'s first slice, PR23A, has
  since merged (GitHub PR #122), and all six PR23 Owner Decisions are
  Owner-approved via this PR23 Owner Decision Closure round; PR23B
  (Cutover Readiness Evidence Foundation) has since merged (GitHub PR
  #124, squash SHA `833f6758a93a78398207d64fbefa65ff2802cf46`); PR23C
  (Readiness Gate Evaluation) has since merged too (GitHub PR #125,
  squash SHA `c10f5082fdc5cb7fd66615fe25516a4982297026`); PR23D
  (Go/No-Go Decision + Current-State Re-Issue Support) has since merged
  too (GitHub PR #126, squash SHA
  `2da80231d4f037136b291863e379e739aa2905dd`); PR23E (Frontend /
  Operator Workflow) has since merged too (GitHub PR #127, squash SHA
  `8644536403eeec269e6dadf835f1bda3844b6cce`); PR23F (Cutover Runbook +
  Final Governance Close-out) has since also merged too (GitHub PR
  #128, historical) — **Roadmap PR23 overall is fully
  implementation-complete.** PR24's architecture/design, all six Owner
  Decisions, PR24B, PR24C, and PR24D's code/tooling have since also
  merged too, PR24D's own post-merge governance close-out (GitHub PR
  #134) has since merged as well, and PR24D-L1 (Local Docker
  Staging/UAT Foundation, GitHub PR #135) has since merged too — see
  "Current baseline" above for the live baseline
  (`73652b062fb2ad6fdab4f7bbc0b743ff5f548e86`).**
  GitHub PR #81, an earlier unsplit PR19A
  candidate, was closed without merging, superseded by
  PR19A1/PR19A2/PR19A3.
- Broader PR15 metrics/tracing/dashboards/aggregation/alerting work is still
  unscheduled.

## Related documents

- `docs/ROADMAP.md` — detailed order and scope.
- `docs/ROADMAP_STATUS.md` — concise status dashboard.
- `docs/DOCUMENTATION_AUDIT.md` — full documentation inventory.
- `knowledge/PROJECT_MEMORY.md` — stable current-state orientation.
- `knowledge/CHANGE_HISTORY.md` — conceptual history.
