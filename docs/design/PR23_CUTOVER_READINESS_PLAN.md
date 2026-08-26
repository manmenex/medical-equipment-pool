# Roadmap PR23 — Cutover Readiness: Architecture & Operational Design (PR23A)

**Status:** DESIGN, GOVERNANCE, AND OWNER DECISION CLOSURE ONLY. No
`backend/**`, `frontend/**`, `alembic/**`, or `tests/**` file has been
created or modified by this document or by its Owner Decision Closure
round. No cutover runtime logic, no deployment, no production data
migration, no pilot has started. **PR23A (this document) is merged**
(GitHub PR #122, squash SHA
`7ca9c87b4c525a1835403dac5d08e6e1be79d33b`). **This Owner Decision
Closure round records all six PR23 Owner Decisions (OD-PR23-1 through
OD-PR23-6, §26) as Owner-approved; PR23B remains blocked until this
closure round's own PR merges** (§27) — see that section for the exact
gate wording while this closure PR is open.

**Baseline (Owner Decision Closure round):**
`7ca9c87b4c525a1835403dac5d08e6e1be79d33b` — the real squash-merge SHA
of GitHub PR #122 (PR23A — Cutover Readiness Architecture & Operational
Design). **Roadmap PR22 (Legacy Data Validation and Reconciliation) is
fully complete**, and **PR23A is merged and architecture-approved**, as
of this baseline: PR22A design, all seven Owner Decisions (OD-PR22-1
through OD-PR22-7), PR22B–PR22F implementation, PR22G governance
close-out, and PR23A itself are all merged.

**Prior baseline (as of PR23A's own creation):**
`527ffc48966d7e5cda16a869f0ae464de8b7512a` — the real squash-merge SHA
of GitHub PR #121 (PR22G — Roadmap PR22 Governance Close-out), now
historical/superseded by the baseline above.

**Purpose:** Design Roadmap PR23 — Cutover Readiness — the workflow,
gates, evidence model, and Owner Decisions that must exist before this
repository's application can become the hospital's sole operational
Medical Equipment Pool system, replacing the AppSheet process. This
document answers *what* "ready to cut over" means and *who* decides it
are; it does not implement any of the mechanisms it describes.

---

## 1. Status / Baseline

See the header above. This document supersedes nothing — it is the
first PR23 design artifact. `docs/audits/04-consolidated-implementation-plan.md`
Part D's PR23 entry (quoted verbatim in §3 below) is the sole prior
authoritative statement of PR23's existence and remains authoritative;
this document expands it into an implementable plan, it does not
redefine it.

---

## 2. Objective

Produce an architecture-approved Cutover Readiness Plan that:

- states exactly what data, evidence, and sign-off must exist before
  cutover;
- defines deterministic, non-subjective readiness gates;
- defines the source-of-truth transition between the legacy AppSheet
  workflow and this application;
- defines how currently-open (in-flight) equipment issues are handled
  at the cutover instant;
- defines rollback, freeze-window, and post-cutover validation models;
- maps PR23's own responsibilities onto this repository's existing four
  Final Go-Live Gates (Development / UAT / Pilot / Production);
- identifies every decision that cannot be made from repository code or
  documentation alone, as an explicit Owner Decision; and
- proposes the smallest maintainable sequence of later PR23 slices.

This document does not implement any backend, frontend, migration, or
deployment change. It does not begin a pilot. It does not select a
cutover date.

---

## 3. Authoritative Inputs

Quoted verbatim from `docs/audits/04-consolidated-implementation-plan.md`
Part D (the sole authoritative definition of PR23's existence):

> #### PR23 — Cutover Readiness
> - **Objective:** Rehearse migration, obtain reconciliation sign-off, and close
>   operational readiness gaps.
> - **Dependencies:** PR22.

No other section of Part D adds in-scope/out-of-scope detail or
acceptance criteria specific to PR23 by name. The acceptance-criteria
content instead lives in the same document's **Part I — Final Go-Live
Gates (§13)**, which this document treats as authoritative and maps
against directly (§20 below) rather than re-deriving. The single most
relevant Production Readiness bullet, quoted verbatim:

> Legacy import reconciliation signed off; old and new transaction
> history is presented as one unified history.

No conflict was found between `docs/audits/04-consolidated-implementation-plan.md`,
`docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, and `docs/DECISION_LOG.md`
regarding PR23's scope or dependencies — all three describe PR23 as
"Cutover Readiness," dependent on PR22, next after PR22 closes. No
STOP-worthy conflict exists; this document proceeds.

Other authoritative inputs consulted, with the specific facts they
established, cited throughout this document by section:

- `docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md` §36 —
  OD-PR22-6 (PR23 cutover-readiness threshold) and OD-PR22-7 (temporal
  coverage model) — see §9 and §12.D below.
- `docs/audits/04-consolidated-implementation-plan.md` §14 item 7 —
  "Backup/restore procedure ... not designed by any of the three audits
  or this plan — needs a separate, dedicated infrastructure task" — see
  §23 below.
- `docs/ARCHITECTURE_DECISIONS.md` ("Managed deployment preferred") —
  no production deployment platform is selected; the current Docker
  Compose setup is a development convenience only — see §23 below.
- `AGENTS.md` — domain guardrails (four equipment states, four
  identifiers, no ward staff as application users, no patient tracking)
  — see §5/§6 below.
- `backend/app/models/legacy_reconciliation.py`,
  `backend/app/models/transaction.py`, `backend/app/models/equipment.py`,
  `backend/app/models/user.py` — exact current schema/enum shapes cited
  throughout.

---

## 4. Scope

**In scope for PR23A (this document):**

- The cutover business workflow and its readiness gates.
- The source-of-truth transition model between AppSheet and this
  application.
- The temporal-boundary extension from PR22's reconciliation-scoped
  coverage to an actual cutover instant.
- The current-equipment-state and outstanding-open-transaction handling
  strategy.
- Go/No-Go decision model, authorization, evidence/audit design.
- Concurrency/freshness, freeze-window, and rollback models.
- Post-cutover validation and UAT/Pilot/Production gate mapping.
- Conceptual (non-committing) API/frontend/deployment implications.
- Every Owner Decision required before any later PR23 slice implements
  runtime behavior.
- A proposed, minimal PR23B+ implementation sequence.

**Out of scope for PR23A:**

- Any `backend/**`, `frontend/**`, `alembic/**`, or `tests/**` change.
- Any new database migration or persisted model.
- Any new API route or frontend screen.
- Selecting an actual cutover date, freeze duration, or pilot ward.
- Selecting a production deployment platform/provider.
- Performing a real backup/restore rehearsal.
- Starting UAT, Pilot, or Production activity.
- Reopening, reinterpreting, or loosening any of the seven approved PR22
  Owner Decisions.
- Reimplementing PR20 (Equipment Master import), PR21 (legacy history
  import), or PR22 (reconciliation/sign-off) — PR23 consumes their
  already-merged outputs only (§6).

---

## 5. Non-Goals

- PR23 does not introduce a new Equipment lifecycle state. The four
  states remain exactly `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`,
  `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`
  (`backend/app/models/equipment.py`). No `CUTOVER`, `MIGRATING`,
  `LEGACY`, `PENDING`, or `SYNCING` state is added or proposed.
- PR23 does not introduce a fourth application role. Roles remain
  exactly `administrator`, `equipment_pool_staff`, `read_only`
  (`backend/app/models/user.py`).
- PR23 does not redesign hospital QR codes, BCM Code, Item Number, or
  Asset Number identity roles.
- PR23 does not replay `LegacyEquipmentEvent` rows into
  `BorrowTransaction` rows, and does not treat historical evidence as
  automatically authoritative for current operational state (§11).
- PR23 does not weaken, bypass, or add a stricter application-level gate
  on top of OD-PR22-6's sign-off threshold without an explicit new Owner
  Decision (none is proposed here — see §12.D).
- PR23 does not select a managed-hosting provider or assume direct
  server access to a hospital-managed host (`docs/ARCHITECTURE_DECISIONS.md`,
  "Managed deployment preferred") — see §23.
- PR23 does not implement MEMS, patient tracking, or any capability
  outside the confirmed Equipment Pool scope (`AGENTS.md`).

---

## 6. Current-State Inputs from PR20/PR21/PR22

PR23 consumes, never reimplements, three already-merged capabilities:

- **PR20 — Equipment Master Import.** BCM/Item Number matching,
  equipment attributes, existing hospital QR linkage, duplicate
  detection, record validation. PR23 treats a successfully imported and
  validated Equipment Master as an input fact, verified via PR20's own
  `DryRunPlan`/execution evidence — PR23 does not re-validate Equipment
  Master data with a second engine.
- **PR21 — Legacy Receive and Issue History Import.** Each accepted
  legacy source row is an independent, immutable
  `LegacyEquipmentEvent` (`event_type` = `ISSUE` | `RECEIVE`) —
  never a paired transaction, never a `BorrowTransaction`, and never a
  mutation of current `Equipment.status`/version/location
  (`docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`, event-
  first architecture). PR23 treats this as permanent historical
  evidence, not as a source of current operational state (§11).
- **PR22 — Legacy Data Validation and Reconciliation.** Produces
  `LegacyReconciliationRun` → `LegacyReconciliationFinding` (with
  `disposition` from the closed four-value vocabulary: `confirmed_valid`,
  `confirmed_duplicate`, `accepted_unresolved`, `requires_correction`) →
  at most one immutable `LegacyReconciliationSignOff` per run
  (`backend/app/models/legacy_reconciliation.py`). PR23 treats a valid,
  current sign-off as the reconciliation-readiness evidence artifact —
  it does not recompute reconciliation state itself (§12.D).

None of PR20/PR21/PR22's own scope, schema, or business rules are
reopened by this document.

---

## 7. Cutover Business Workflow

At a business level, cutover is the single moment the Medical Equipment
Pool application (not AppSheet) becomes the system Equipment Pool staff
use to record every dispatch and receipt. Before that moment:

1. Equipment Master and legacy transaction history have been imported
   (PR20, PR21) and reconciled with a valid final sign-off (PR22,
   OD-PR22-6).
2. A defined set of deterministic readiness gates (§12) all pass.
3. A designated approver records an explicit Go decision (§13).
4. Any operational freeze window required (§17) has run and completed.
5. The application is confirmed to reflect the correct current
   equipment state, including outstanding issued equipment (§11).

At the cutover instant, AppSheet stops being the write system of record
for new dispatch/receipt activity (§8), and the application becomes
authoritative going forward. This is a one-time business transition,
not a recurring workflow — PR23's design is written for exactly one
cutover event, with an explicit, bounded rollback window (§18)
immediately after.

---

## 8. Source-of-Truth Transition

Three operational options were evaluated, per the task's own framing:

| Option | Description | Duplicate-transaction risk | Missing-transaction risk | Staff usability | Rollback feasibility | Reconciliation complexity | Auditability |
|---|---|---|---|---|---|---|---|
| **A — Hard cutover** | AppSheet write access stops at a defined instant; the application becomes the sole write system from that instant. | Low — exactly one system can accept a write at any time. | Low, provided the freeze window (§17) is respected. | High — staff use one system, no dual-entry decision to make per transaction. | High before the first production transaction; bounded after (§18). | Low — no ongoing dual-source reconciliation needed after cutover. | High — one clear boundary instant, one system of record per period. |
| **B — Short controlled overlap** | Both systems temporarily accept writes, with explicit per-transaction source ownership rules (e.g. by ward, by shift). | Medium-High — any ambiguity in ownership rules creates a duplicate. | Medium — a transaction recorded nowhere if staff assume "the other system has it." | Medium — staff must know which system owns which transaction at any moment. | Medium — harder to define a single rollback point. | High — every transaction in the overlap window needs explicit source attribution and possible reconciliation. | Medium — two systems of record simultaneously. |
| **C — Read-only legacy archive after cutover** | AppSheet becomes read-only immediately at cutover (no new writes accepted by either legacy write path or manual edit); the application is the only write system, identical write behavior to Option A but stated as the durable target end-state rather than only the cutover mechanism. | Same as A. | Same as A. | Same as A. | Same as A. | Same as A. | Same as A — and additionally preserves AppSheet as a permanently queryable historical reference. |

Options A and C are not mutually exclusive — C is the natural permanent
state that A's cutover instant transitions into. **Recommendation:
Option A (hard cutover) at the cutover instant, transitioning
permanently into Option C (AppSheet becomes read-only/archival) as the
stable post-cutover state.** This matches the user's own explicit
guidance for this design round and is consistent with PR21's own
event-first architecture, which was deliberately built to keep
historical import evidence (`LegacyEquipmentEvent`) separate from
operational truth (`BorrowTransaction`) rather than to support any
form of ongoing dual-write reconciliation.

**Option B is explicitly not recommended.** Dual-write during any
overlap window creates exactly the ambiguity §22 of the task instructs
against — "never permit 'staff can use either system' without
reconciliation rules" — and this repository's own architecture has no
existing mechanism (and PR22 explicitly does not build one) for
continuous, real-time cross-system reconciliation of live operational
transactions. Building one would be new scope well beyond "Cutover
Readiness."

This recommendation is **not binding** without confirming operational
feasibility (can AppSheet genuinely be locked to read-only for the
relevant users at the chosen instant?) — see **OD-PR23-1** (§26).

---

## 9. Temporal Boundary

PR23 does not invent a new temporal model. It reuses OD-PR22-7's
three-boundary model exactly as resolved
(`docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md` §36):

- `legacy_coverage_start` / `legacy_coverage_end` — the
  Administrator/Owner-approved historical coverage window recorded on a
  `LegacyMigrationAuthorityCoverage` row, never derived from
  `MIN`/`MAX(event timestamp)`.
- `live_system_start` — a distinct governed boundary representing when
  modern-system transaction history becomes authoritative for the
  reconciliation projection; not automatically equal to
  `legacy_coverage_end`. All three relationships — **gap**
  (`legacy_coverage_end < live_system_start`), **clean handoff**
  (`legacy_coverage_end == live_system_start`), and **overlap**
  (`legacy_coverage_end > live_system_start`) — remain explicitly
  representable, never collapsed.

**PR23 introduces one additional concept the reconciliation design
deliberately left to it (OD-PR22-6: "PR23's own cutover-evidence design
remains out of this document's scope"): the `cutover_instant`** — the
actual real-world moment AppSheet write access stops and the
application becomes the sole write system (§8). `cutover_instant` is
**not automatically assumed equal to `live_system_start`.**
`live_system_start` was approved for reconciliation-scoping purposes,
potentially before the actual go-live date is known; `cutover_instant`
is the real operational event. The only structural constraint this
document imposes is: **`cutover_instant` must never be earlier than the
signed-off run's `live_system_start`** — the reconciliation evidence a
Go decision relies on cannot postdate the moment it claims to cover.
How close `cutover_instant` must be to `live_system_start` (same day?
same week?), and who approves any gap between them, is **not**
determinable from repository authority — see **OD-PR23-1** (folded into
the source-of-truth decision, §26) which also covers this timing
question.

Late legacy records (a legacy row discovered after `legacy_coverage_end`
was approved) and transactions entered during the transition window are
both explicitly **evidence for a new reconciliation run**, per
OD-PR22-7's "corrected/re-exported authorities... do not silently
inherit temporal coverage" rule — never silently absorbed into an
existing signed-off run, and never used to justify reopening a
completed sign-off (sign-offs are immutable by schema — no `UPDATE`
path exists on `LegacyReconciliationSignOff`).

No authoritative date is set anywhere in this document.

---

## 10. Current Equipment State

This is, per the task's own framing, one of the two most critical open
questions (the other being §11). Repository inspection found **no
existing design or implementation answering it** — PR20 imports
Equipment Master *attributes* (BCM, Item Number, category, etc.), not a
*current status* projection derived from legacy transaction history;
PR21 explicitly never mutates `Equipment.status`/version/location;
PR22 reconciles historical evidence, it does not compute or assert
current state.

Two candidate sources exist, and this document deliberately does not
pick between them by default:

1. **PR20's own imported `Equipment.status`** — if the Equipment Master
   source workbook already carries an authoritative status field per
   row (mapped through PR20's existing legacy-status mapping, per
   `docs/audits/04-consolidated-implementation-plan.md` Part E), that
   becomes each equipment record's status at import time, and remains
   whatever it was subsequently changed to via ordinary application use
   between import and cutover.
2. **A fresh, explicit, human-performed physical/administrative
   verification immediately before cutover** — Equipment Pool staff
   confirm what is actually at the pool, issued, defective, or
   decommissioned at (or just before) the cutover instant, using the
   application's own existing status-maintenance and issue/receive
   workflows (never a new bulk-mutation mechanism).

**This document does not recommend deriving current state from
`LegacyEquipmentEvent` replay.** Doing so would require inferring "the
last event before cutover determines current status," which the user's
own explicit instruction for this round identifies as exactly the
mechanism PR21/PR22 were deliberately architected to avoid — historical
evidence and current operational truth were kept structurally separate
on purpose (`LegacyEquipmentEvent` vs. `Equipment`/`BorrowTransaction`),
and inferring state from historical event sequence reintroduces the
"reconciliation via fuzzy replay" risk §7 of the task explicitly
prohibits.

**Recommendation: source (1) as the baseline (Equipment Master import
already establishes an initial status), confirmed/corrected by source
(2) as a mandatory Gate E check (§12) immediately before the Go
decision** — never fully automated, never silently inferred from
history. This requires an explicit Owner Decision to confirm the
Equipment Master's status field is actually populated and trustworthy
for this purpose in the real source data — see **OD-PR23-2** (§26).

---

## 11. Outstanding/Open Transactions

The second critical open question. Concretely: at the cutover instant,
some equipment is legitimately issued to a ward in the *real world* via
the legacy AppSheet workflow, with no corresponding `OPEN`
`BorrowTransaction` row in this application (`backend/app/models/transaction.py`,
`TransactionStatus.OPEN`/`CLOSED`) — because PR21 only ever creates
immutable `LegacyEquipmentEvent` rows, never `BorrowTransaction` rows.

Resolving the questions posed by the task:

- **Does the new system already contain the live OPEN
  `BorrowTransaction`?** No — by design, it cannot; PR21's event-first
  architecture guarantees this.
- **Must outstanding AppSheet issues be seeded?** Only if the hospital
  needs the application to show "who currently has this equipment" for
  equipment that was issued before cutover and not yet returned. This
  is an operational question repository authority cannot answer.
- **Is there a one-time current-state migration?** This document
  recommends **no automated migration path** (no bulk `INSERT` of
  synthetic `BorrowTransaction` rows derived from `LegacyEquipmentEvent`
  matching). Instead: **Equipment Pool staff perform a one-time,
  explicit re-issue** through the application's own existing issue
  workflow for each piece of equipment confirmed still outstanding at
  cutover (§10's Gate E verification), recording it as a normal `OPEN`
  `BorrowTransaction` dated at or after `cutover_instant`. This keeps
  the same invariant PR21/PR22 already enforce: `BorrowTransaction` is
  never populated by inference over historical import data, only by the
  ordinary dispatch workflow, operated by a real Equipment Pool staff
  member confirming reality.
- **How is transaction provenance retained?** The original legacy
  `ISSUE` event remains permanently visible as historical evidence
  (unified legacy + modern history projection, OD-PR22-7 §15); the new
  `BorrowTransaction` is a distinct, newly-created operational record,
  never claimed to be "the same transaction" as the legacy event — it
  is a fresh administrative acknowledgment of an already-outstanding
  physical fact.
- **How is duplicate OPEN state prevented?** By making this a bounded,
  one-time, staff-performed activity gated by the Gate E current-state
  verification (§10/§12), not an automated or repeatable process — the
  same discipline that prevents duplicate imports elsewhere in this
  repository (idempotent state-based replay, PR19A).
- **How are later returns recorded?** Identically to any other
  `BorrowTransaction` — through the existing receipt workflow, no new
  mechanism.
- **How is ward identity resolved?** Through the same Ward
  normalization/mapping PR21 already established
  (`docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`), for
  staff to select the correct ward when re-issuing.

This recommendation (manual, explicit, staff-confirmed re-issue; no
automated replay) is **not binding** without Owner confirmation that
the operational cost (staff time to walk the pool/wards and re-issue
each outstanding item) is acceptable — see **OD-PR23-2** (§26), the same
decision that governs §10.

---

## 12. Readiness Gates

Deterministic gates, explicitly cross-referenced against this
repository's own **Part I — Final Go-Live Gates** so PR23 does not
silently redefine an existing gate. Gate letters below are PR23's own
organizing structure for *cutover-specific* readiness only — they are
not a replacement for Development/UAT/Pilot/Production (§20 maps
between the two).

- **Gate A — Application readiness.** Required PRs merged (PR19–PR22,
  confirmed via `docs/ROADMAP.md`'s Completed table), CI green on the
  exact deployed head, database migrations applied and verified
  (`alembic upgrade head` against the head migration,
  `0020_reconciliation_foundation.py` as of this baseline), production
  configuration validated (real secrets, not defaults — `docs/06-deployment-guide.md`
  §4, itself marked "legacy design reference," current authority
  pending §23), backup/restore procedure validated (§23 — currently
  **undesigned**, per Part I's own open item 7).
- **Gate B — Master data readiness.** PR20's Equipment Master import
  completed successfully against the real hospital inventory; required
  BCM/Item Number integrity satisfied; ward/master-data mapping
  approved (PR21's Ward normalization).
- **Gate C — Historical data readiness.** PR21's canonical
  `legacy_transaction_history` import completed; the approved source
  artifact/checksum recorded via the existing
  `POST/GET /legacy-migration-authorities` API (PR21E0).
- **Gate D — Reconciliation readiness.** Exactly OD-PR22-6's four
  conditions, restated here as PR23's own gate rather than re-derived:
  (1) every reconciliation finding has a disposition; (2) the
  `requires_correction` count is zero; (3) the reconciliation run has a
  valid final sign-off; (4) that sign-off is against the exact
  immutable run/snapshot, approved rule version, approved data/
  migration authorities, and approved temporal coverage.
  `accepted_unresolved` **is** permitted — PR23 does not add a stricter
  threshold. This gate is satisfied by querying the existing
  `GET /legacy-reconciliation-runs/{run_id}/sign-off` endpoint (PR22E)
  for the run intended to govern cutover, never by a second, PR23-owned
  reconciliation computation.
- **Gate E — Current-state readiness.** *New — not explicitly present
  in the repository's existing Part I gates.* Live equipment-state
  snapshot validated (§10); outstanding issued equipment accounted for
  and re-issued through the ordinary workflow (§11); no unresolved
  equipment-identity conflicts (BCM/Item Number/Asset Number collisions
  — reuses PR20's own duplicate-detection evidence, never a new
  detector).
- **Gate F — Operational readiness.** Users/roles ready and matched to
  the real production roster (Part I, UAT/Production Readiness); staff
  trained on the application's terminology/workflow (Part I, UAT
  Readiness — "no 'Borrow'/'Borrower'/'Due Date' language remaining");
  QR workflow verified (existing `ADR-004-hospital-item-no-qr.md`
  contract, unchanged); issue/receive smoke test passed; rollback/
  contact responsibilities defined (§18/§19).
- **Gate G — Cutover authorization.** A designated approver records an
  explicit Go/No-Go decision (§13) — cutover **cannot** proceed while
  any mandatory gate above is failing.

Whether every one of Gates A–G is "mandatory" (blocks Go) vs. some
subset is advisory is intentionally left to §13's Go/No-Go model — this
document treats Gate D (reconciliation) as always mandatory (it is the
one gate an existing repository authority, OD-PR22-6/Part I Production
Readiness, already requires), and Gates A/B/C/E as mandatory by direct
consequence of Gate D's own dependency chain (a valid sign-off cannot
exist if the data it reconciles was never actually imported). Gate F is
recommended mandatory but is the one most likely to need Owner
confirmation, since it touches real people/training, not code.

---

## 13. Go/No-Go

**Recommendation: cutover Go is deterministically impossible while any
mandatory gate (§12) fails** — no subjective "looks OK" override. Three
explicit blocker categories, per the task's own suggested framing:

- **BLOCKER** — a mandatory gate (A–E, and F per §12's note) is not
  satisfied. Go is structurally impossible while any BLOCKER exists.
- **WARNING** — a non-mandatory readiness item is incomplete (e.g. a
  Gate F sub-item not yet confirmed, or an advisory observability check
  from §24). Go remains possible but the approver must explicitly
  acknowledge each WARNING.
- **INFO** — informational evidence with no gating effect (e.g. current
  finding counts by disposition, coverage window dates) shown to the
  approver for context.

**This document deliberately does not introduce a persisted enum/model
for these categories in PR23A** (per the task's own instruction), and
does not commit to their exact list beyond the mapping to §12's gates —
a later PR23 slice (§27) defines the concrete evaluation logic, if the
persistence Owner Decision (§26, `OD-PR23-6`) resolves toward a
persisted model.

---

## 14. Authorization

No fourth application role. Recommended usability mapping onto the
existing three roles (backend authorization, if any is eventually
implemented, remains the real boundary — see §24):

- **Viewing cutover readiness** — `administrator`, `equipment_pool_staff`,
  `read_only` (mirrors PR22F's `VIEW_AND_REPORT_ROLES` precedent —
  read access is broad, mutation is narrow).
- **Executing readiness checks** (if any check requires a mutating
  action, e.g. re-running an evidence query) — `administrator` only,
  mirroring PR22D/E's `ADMINISTRATOR_ONLY_ROLES` precedent for every
  reconciliation mutation.
- **Final Go/No-Go approval** — `administrator` records the decision in
  the application, but the *person* accountable for that decision may
  be an Owner/hospital authority who is not necessarily the same
  individual operating the `administrator` account day-to-day. This
  document models that accountability as **operational governance**
  (who the Owner designates, recorded outside the application's role
  system — e.g. in the cutover runbook/Owner Decision record) rather
  than as a new application role, per the task's own explicit
  instruction (§16). See **OD-PR23-3** (§26).
- **Rollback authorization** — same accountable authority as Go/No-Go;
  recommended to require the same person or an explicitly designated
  deputy, never a unilateral `equipment_pool_staff` decision.

---

## 15. Evidence / Audit

At minimum, the following evidence should exist for any cutover,
regardless of whether it is persisted in the database (§16) or captured
only in a runbook/governance record:

- Application baseline SHA (this repository's real squash-merge SHA at
  deployment time).
- Database migration head (`alembic_version` table's current revision —
  `0020_reconciliation_foundation.py` as of this baseline).
- Equipment Master import authority/source reference (PR20's
  `ImportSource`/`DryRunPlan` identity).
- Legacy transaction import authority/source reference (PR21's
  `LegacyMigrationAuthority` checksum-approval identity).
- Reconciliation run ID (`LegacyReconciliationRun.id`).
- Reconciliation sign-off ID (`LegacyReconciliationSignOff.id`).
- Temporal coverage (`legacy_coverage_start`, `legacy_coverage_end`,
  `live_system_start`, and the new `cutover_instant`, §9).
- Finding/disposition counts at time of sign-off (already captured in
  `LegacyReconciliationSignOff.attestation_summary`, per PR22E — reused,
  never recomputed).
- Current-state verification evidence (§10/§12 Gate E) — what was
  checked, by whom, when.
- Go/No-Go decision, approver identity, and timestamp.
- Rollback decision, if invoked, and its own timestamp/reason.

**Never store PHI.** No patient-identifiable field exists anywhere in
this application's schema today (Part I, Pilot Readiness: "No
patient-identifiable fields present anywhere in the workflow"), and
PR23's evidence model must not become the first place one is
introduced. **Never duplicate raw workbook contents** into audit
records — PR19A/PR20/PR21 already retain the original uploaded
artifact (`ImportSourceBlob`) and its checksum; cutover evidence
references that identity, it does not copy file contents.

---

## 16. Concurrency / Freshness

If Gate D/E readiness is evaluated at one instant and the Go decision is
recorded at another (even minutes later), staff may still be issuing or
receiving equipment in between, or a reconciliation sign-off could
(in principle) be superseded by a later run. PR23 must not claim
consistency without defining this explicitly:

- A **persisted cutover readiness snapshot** (if the Owner Decision in
  §18/§26 adopts one) must record the exact evidence identities (run
  ID, sign-off ID, migration head, etc.) it was evaluated against, the
  same discipline `LegacyReconciliationRun`/`LegacyReconciliationFinding`
  already use (`version`/CAS-style staleness detection, per PR22D/E's
  own `expected_version` precedent).
- **Freshness is proven, not assumed**, by re-checking each mandatory
  gate's evidence identity immediately before the Go decision is
  recorded — mirroring PR22E's own re-verification discipline (head/CI
  re-checked immediately before every squash merge in this session's
  own governance practice) rather than trusting a stale earlier
  snapshot.
- If a **new reconciliation run supersedes the one Gate D was
  evaluated against** between snapshot and Go, the snapshot is
  considered stale and Gate D must be re-evaluated against the new
  run — never silently carried forward.
- **Equipment state changing between the readiness check and the Go
  decision** is expected and acceptable up to the point of Gate E's
  own verification instant — this is precisely why Gate E (§10/§12) is
  evaluated as close to `cutover_instant` as operationally possible,
  not once far in advance.

---

## 17. Freeze Window

Evaluated concept, no time value set:

```
T0 — stop writes in the legacy AppSheet system
T1 — capture/export final legacy data (if a final import pass is needed)
T2 — run final import/reconciliation/current-state validation (Gates B–E)
T3 — Go decision recorded (Gate G, §13)
T4 — application write operations enabled for Equipment Pool staff
```

A short freeze window between T0 and T4 reduces the risk of missed or
duplicated transactions (directly supporting the Option A/C
recommendation, §8) at the operational cost of a period where neither
system accepts new dispatch/receipt activity. **Whether a freeze window
is required, and its duration, cannot be determined from repository
authority** — it depends on how disruptive a short write-freeze is to
actual hospital operations. See **OD-PR23-1** (§26, folded together with
the source-of-truth decision since they are the same operational
trade-off).

---

## 18. Rollback

Rollback must be defined before any implementation exists to roll back
from. Recommended boundary, evaluated per the task's own suggested
distinction:

- **Before the first accepted production transaction in the
  application:** full cutover rollback is recommended as feasible —
  AppSheet resumes writes, and the application's cutover-period state
  (any re-issued `BorrowTransaction` rows from §11, any persisted
  readiness snapshot) can be discarded or marked abandoned without
  affecting real operational history, since no new operational fact was
  yet recorded that AppSheet does not already reflect.
- **After the first accepted production transaction:** full rollback is
  **not** recommended — a real dispatch or receipt recorded only in the
  application would be lost or require manual reconstruction in
  AppSheet. **Controlled forward-fix is recommended instead**, unless an
  explicit reconciliation procedure for reintroducing application-only
  transactions back into AppSheet is separately designed and approved
  (no such procedure exists today, and building one is out of PR23A's
  scope).

This boundary — "before vs. after the first accepted production
transaction" — gives Go/No-Go and rollback authorization (§14) a single,
unambiguous instant to reason about, rather than a fuzzy time-based
window. It is **not binding** without Owner confirmation that
AppSheet can genuinely resume accepting writes on short notice if
rollback is invoked — see **OD-PR23-4** (§26).

---

## 19. Post-Cutover Validation

Mandatory checks immediately after activation, evaluated against
existing, already-implemented application capability only (no new
mechanism):

- Login for each of the three roles.
- Equipment lookup by BCM Code (`ADR-003-bcm-manual-search.md`).
- QR lookup by Item Number (`ADR-004-hospital-item-no-qr.md`).
- Issue to ward (existing dispatch workflow).
- Receive usable (existing receipt workflow → `AVAILABLE_AT_POOL`).
- Receive defective (existing receipt workflow → `UNAVAILABLE_DEFECTIVE`).
- Transaction history visible, and legacy history visible in the same
  unified projection (OD-PR22-7 §15).
- Reconciliation run/finding/sign-off visible (PR22F frontend).
- Role permission checks (each role sees exactly its own confirmed
  capability set).
- Audit records generated for every action above.

**Use test/demo equipment or a small number of pre-agreed, clearly
labeled real records for this validation** — never mutate arbitrary
real clinical-operational equipment merely to smoke-test, and never
without a controlled, reversible procedure agreed in advance (consistent
with the existing repository's demo-seed precedent,
`app.scripts.seed`, rather than inventing a new test-data mechanism).

---

## 20. UAT / Pilot / Production Mapping

Mapping PR23's own responsibility onto the repository's existing four
gates (`docs/audits/04-consolidated-implementation-plan.md` Part I,
quoted, not redefined):

| Existing Gate | What it already requires (verbatim/paraphrased) | PR23's contribution |
|---|---|---|
| **Development Readiness** | Confirmed domain model, migration design approved, PR sequence agreed, test strategy agreed, no unresolved Critical assumption. | Already fully satisfied by PR1–PR22 (Development Readiness only requires PR5–PR8 explicitly, and the confirmed domain model has not changed since). PR23A itself changes nothing here — no runtime code. |
| **UAT Readiness** | BCM/Item No import exercised against a real sample; dispatch/receipt operational end-to-end; duplicate/concurrent protection verified; roles match the confirmed matrix; audit coverage verified; search/history BCM-first; terminology approved; test data imported via PR12. | PR23's Gates A–C (§12) confirm the import-related bullets specifically for the *legacy* migration (PR20/PR21), which UAT Readiness does not itself cover — UAT Readiness predates PR19–PR22 in this plan's own numbering and was written before legacy migration existed as scope. PR23 does not re-run UAT itself. |
| **Pilot Readiness** | All P0 findings resolved; concurrency tests passing at pilot volume; error handling verified; audit logging verified; **backup procedure documented**; pilot users trained; **rollback plan documented**; no PHI present. | PR23's §17 (freeze window) and §18 (rollback) directly extend "rollback plan documented" to cover the *cutover-specific* rollback, not only migration rollback. §23 (backup/restore) remains an **open item this repository has never designed** (Part I's own §14 item 7) — PR23A does not close it, only names it explicitly as a Gate A dependency. |
| **Production Readiness** | Version 1 legacy migration completed; **legacy import reconciliation signed off; unified history presented**; BCM/Item Number/QR/BME/Ward/duplicate/source-traceability verified; backup/restore *rehearsed* (not just documented); secure production configuration; full audit coverage; monitoring/logging (PR15); concurrency verified under production-representative load; permissions matrix verified against the real roster; migrations verified against real production data; inventory reconciliation complete; **UAT sign-off obtained; Pilot sign-off obtained**; support/recovery process documented. | This is the gate PR23 exists to satisfy. Gates A–G (§12) are this document's decomposition of exactly this bullet list, plus the two genuinely new items this repository has not previously named: current-state/open-transaction readiness (Gate E, §10/§11) and an explicit recorded Go/No-Go decision (Gate G, §13) — Production Readiness today only says "sign-off obtained," it does not describe a formal Go/No-Go record. |

**What PR23 proves vs. what requires real hospital evidence outside
source code:** PR23's design and any later implementation can prove
that the *application* correctly reflects reconciled data, enforces its
own gates, and records evidence. It **cannot** prove that AppSheet was
actually locked to read-only, that staff were actually trained, that a
real backup was actually restorable, or that a real physical equipment
count matches the application's current-state snapshot — those require
actual hospital UAT/Pilot execution and sign-off, which PR23's evidence
model (§15) is designed to *record*, not fabricate.

---

## 21. API Implications

**No API is committed to by PR23A.** If a later slice (§27) adopts the
persisted-evidence recommendation (§26, `OD-PR23-6`), the conceptual
shape — subject to this repository's existing naming conventions
(`GET/POST /legacy-reconciliation-runs/...` precedent) — would be
something like:

```
GET  /api/v1/cutover-readiness              # current gate status (read-only, all roles)
GET  /api/v1/cutover-readiness/{run_id}      # detail for one readiness evaluation
POST /api/v1/cutover-readiness/{run_id}/decision   # Administrator-only Go/No-Go record
```

This shape is illustrative only, not a commitment. It deliberately
mirrors PR22's `.../sign-off` shape (read/POST pair, Administrator-only
mutation, immutable decision record) rather than inventing a new
pattern.

---

## 22. Frontend Implications

**No frontend change is made by PR23A.** If a later slice needs a UI
(§27, `PR23E`), the requirements — reusing PR22F's already-established
conventions rather than inventing new ones — are:

- Thai-first, mobile-friendly, consistent with the existing AppShell/
  page conventions.
- Clear Go/No-Go status display, using the BLOCKER/WARNING/INFO model
  (§13) — never a single ambiguous "ready"/"not ready" toggle.
- Minimal typing, large touch targets (mirrors PR22F's own accessibility
  requirements).
- Explicit, itemized blockers (never a single opaque error).
- A strong, irreversible-action confirmation dialog for the Go decision
  itself, mirroring `ReconciliationSignOffDialog.tsx`'s established
  focus-trapped confirmation pattern.
- **The frontend must never calculate readiness authoritatively** — per
  §29 of the original PR22F task's own binding rule, reapplied here:
  the frontend may show backend-returned gate/evidence state, but Go/
  No-Go authorization is decided by the backend response alone, exactly
  as PR22F's sign-off UI never reimplements sign-off eligibility.

---

## 23. Deployment Implications

**Explicitly separated from application cutover readiness**, per the
task's own instruction and this repository's own confirmed constraint
(`docs/ARCHITECTURE_DECISIONS.md`, "Managed deployment preferred"):
production deployment must not assume direct access to hospital-managed
servers, no specific managed platform has been selected, and the
current Docker Compose setup (`docs/06-deployment-guide.md`, itself
marked "Legacy design reference," not current authority) is a
development convenience only, not the confirmed production target.

**This document does not assume:**

- Kubernetes.
- A specific cloud vendor.
- On-premises hospital server access.
- Docker availability on any hospital-controlled host.
- Public Internet exposure vs. hospital-internal network placement.

**What PR23A can state:** Gate A (§12) requires that *whatever*
production deployment target is eventually selected has been validated
(migrations apply cleanly, health check responds — `GET /api/v1/health`
already exists, `backend/app/api/v1/health.py`), and that backup/
restore has been rehearsed against it (§23 below repeats this as its
own explicit open item). **Selecting the actual deployment target
remains a pre-existing open architecture item this document does not
resolve** — it was already known-open before PR23 started
(`docs/ROADMAP.md`, "Confirmed future work — Managed deployment") and
is not a new PR23 Owner Decision; PR23 only depends on it being resolved
by the time Gate A is evaluated for a real cutover.

---

## 24. Security

- No new authentication model. Existing JWT-based auth
  (`app/core/security.py`) is unchanged.
- No secrets in any readiness artifact — evidence records reference
  identities (run IDs, migration heads, source checksums), never
  connection strings, tokens, or credentials.
- No raw passwords/tokens in evidence or audit output.
- No PHI (§15, reaffirmed — no patient-identifiable field exists in this
  schema today, and PR23 must not become the first place one appears).
- Administrator-only capabilities (readiness-check execution, Go/No-Go
  recording, if implemented) remain backend-enforced — any future
  `canRecordCutoverDecision`-style frontend helper would be usability-
  only, exactly like every PR22F capability helper, never a security
  boundary.
- If a cutover endpoint is eventually implemented (§21), its
  authorization lives in `backend/app/api/v1/deps.py`'s existing
  `require_roles(...)` pattern — no new authorization mechanism.

---

## 25. Failure Modes

- **A mandatory gate fails after the Go decision was recorded but
  before `cutover_instant`** (e.g. a new `requires_correction` finding
  surfaces from a late-discovered legacy record, §9) — the Go decision
  must be treated as void; re-evaluate before proceeding, per §16's
  freshness discipline. This document does not recommend allowing a
  stale Go decision to survive a gate regression.
- **Freeze window overruns** (T2 validation takes longer than planned,
  §17) — no application-side automatic behavior is proposed; this is an
  operational/runbook concern, not a system design one, since neither
  system is nominally accepting writes during the freeze.
- **Rollback invoked after the boundary in §18** — explicitly
  discouraged by this design; if it happens anyway, it is an
  operational incident requiring its own ad hoc recovery, not something
  PR23's design attempts to make automatic or safe.
- **Current-state verification (Gate E) finds a discrepancy it cannot
  resolve** (e.g. equipment physically missing, or a duplicate BCM
  Code) — this is a BLOCKER (§13), not something PR23 attempts to
  auto-resolve; it is exactly the kind of finding PR22's own
  `requires_correction` disposition exists to capture, and if
  discovered as part of Gate E it should be routed through the same
  human-disposition discipline, not a new ad hoc fix path.

---

## 26. Owner Decisions Required Before PR23 Implementation

Per the task's own instruction, only decisions that materially affect
architecture are listed. Numbering follows this repository's
`OD-PR<n>-<m>` convention.

**Closure note:** all six decisions below were **RESOLVED / OWNER
APPROVED** by the PR23 Owner Decision Closure round ("อนุมัติ
OD-PR23-1 ถึง OD-PR23-6 ตาม Recommendation", with an explicit Owner
clarification for OD-PR23-5 — see that entry). Each entry below retains
its original Question/Options/Trade-offs for decision provenance and
adds the Owner-approved choice as the now-authoritative status.

- **OD-PR23-1 — Source-of-truth transition strategy, freeze window, and
  `cutover_instant`-to-`live_system_start` alignment.**
  *Question:* Is Option A (hard cutover into a permanently read-only
  legacy archive, §8) operationally acceptable? Can AppSheet actually be
  locked to read-only for the relevant users at a defined instant? Is a
  freeze window (§17) required, and for how long? How close must
  `cutover_instant` be to the reconciliation run's approved
  `live_system_start` (§9)?
  *Options:* Option A/C (recommended); Option B (dual-write, not
  recommended); no freeze window vs. a short defined freeze.
  *Trade-offs:* see §8's comparison table.
  *Recommendation:* Option A/C, with a short freeze window (T0–T4, §17),
  exact duration to be set operationally.
  *Consequence if unresolved:* PR23B+ cannot define the actual cutover
  sequencing logic; Gate G (§13) has no concrete procedure to execute.
  *Status:* **RESOLVED / OWNER APPROVED.**
  *Approved choice:* Hard cutover (Option A). Legacy AppSheet becomes
  read-only for operational users after cutover; the new Medical
  Equipment Pool system becomes the sole operational write system. A
  short, controlled freeze window is used during final cutover
  validation. Actual freeze duration and cutover date remain operational
  inputs, not hardcoded by architecture. Uncontrolled dual-write is not
  permitted. `cutover_instant`, legacy coverage, and `live_system_start`
  must be explicitly governed and aligned per the PR23/PR22 temporal
  model (§9).

- **OD-PR23-2 — Current-state and outstanding-open-transaction
  migration method.**
  *Question:* Is the manual, staff-performed re-issue model (§10/§11)
  operationally acceptable, given its staff-time cost? Is Equipment
  Master's imported status field (PR20) trustworthy as the current-state
  baseline, or does every record need physical re-verification?
  *Options:* manual re-verification + manual re-issue (recommended, no
  automated replay); PR20-import-status-only (lower cost, higher risk of
  drift since import); automated `LegacyEquipmentEvent`-derived replay
  (explicitly not recommended — would reintroduce historical-evidence-
  as-operational-truth, contradicting PR21/PR22's own architecture).
  *Trade-offs:* see §10/§11.
  *Recommendation:* manual verification (Gate E) + manual re-issue for
  confirmed outstanding equipment.
  *Consequence if unresolved:* Gate E (§12) has no defined procedure;
  cutover could proceed with an application that silently
  under-represents currently-issued equipment.
  *Status:* **RESOLVED / OWNER APPROVED.**
  *Approved choice:* Manual/physical verification of current equipment
  state is performed for cutover (Gate E). Imported legacy history is
  not treated as current operational truth, and `LegacyEquipmentEvent`
  is not automatically replayed into live `BorrowTransaction`. Equipment
  confirmed as still issued to a ward is represented in the new
  operational system only through the approved manual/current-state
  cutover procedure, preserving provenance and avoiding duplicate OPEN
  transactions. Current-state verification remains a mandatory cutover
  gate.

- **OD-PR23-3 — Go/No-Go and rollback authorization.**
  *Question:* Who is the accountable approver for the final Go decision
  and for invoking rollback? Is this always the same person operating
  the `administrator` account, or a named Owner-designated authority
  recorded outside the application?
  *Options:* application `administrator` role only; a named
  individual/committee recorded as operational governance (recommended,
  §14).
  *Trade-offs:* a fourth application role would violate the confirmed
  three-role model (§5) for no real benefit, since the accountable
  person can simply also hold the `administrator` role or have their
  decision recorded by one.
  *Recommendation:* operational governance record, not a new role.
  *Consequence if unresolved:* Gate G (§13) has no defined approver;
  any `administrator` account holder could record Go, which may not
  match real hospital accountability requirements.
  *Status:* **RESOLVED / OWNER APPROVED.**
  *Approved choice:* No fourth application role is introduced;
  application authorization continues to use the existing
  `administrator` role. Final Go/No-Go accountability is an operational
  governance responsibility, and the authorized accountable
  person/committee may be recorded separately from application role
  semantics. Backend authorization remains authoritative for any future
  cutover mutation endpoint.

- **OD-PR23-4 — Rollback boundary confirmation.**
  *Question:* Can AppSheet genuinely resume accepting writes on short
  notice if rollback is invoked before the first production
  transaction? Is any forward-fix procedure needed for the (hopefully
  rare) case rollback is attempted after that point?
  *Options:* the before/after-first-transaction boundary (§18,
  recommended); a time-based boundary instead (not recommended — less
  precise); no rollback support at all (not recommended — contradicts
  Pilot Readiness's existing "rollback plan documented" requirement).
  *Recommendation:* the before/after-first-transaction boundary.
  *Consequence if unresolved:* §18 remains a recommendation only; a real
  incident during cutover would have no agreed recovery procedure.
  *Status:* **RESOLVED / OWNER APPROVED.**
  *Approved choice:* The before/after-first-accepted-real-production-
  transaction boundary (§18). Before that point, full cutover rollback
  may be permitted per the approved runbook. After that point,
  controlled forward-fix is the default strategy. Operational
  transactions are never silently moved back and forth between systems;
  any exceptional post-boundary rollback requires explicit
  incident/recovery handling, not automatic behavior.

- **OD-PR23-5 — Pilot scope.**
  *Question:* Which ward(s), and for how long, participate in a Pilot
  before full Production cutover (Part I, Pilot Readiness)?
  *Options:* cannot be enumerated from repository authority — pure
  operational input.
  *Recommendation:* none — this is purely an Owner/operational input,
  not an architecture choice.
  *Consequence if unresolved:* Pilot Readiness (existing gate) cannot be
  entered; Production Readiness's "Pilot sign-off obtained" bullet has
  nothing to reference.
  *Status:* **RESOLVED / OWNER APPROVED WITH OWNER CLARIFICATION.**
  *Approved choice (Pilot Ward selection):* The Pilot Ward is selected
  from the existing Ward/department master data corresponding to the
  legacy `แผนกที่ยืม` value — that legacy column is used only as a
  reference to identify/resolve an already-existing Ward/department
  record, never to create a new Ward record automatically or to make
  raw legacy text a new uncontrolled master-data authority. This
  preserves existing Ward identity/mapping rules and data integrity.
  Pilot begins with **one controlled Pilot Ward**.
  *Approved choice (duration):* Pilot duration is **not** a fixed number
  of calendar days (e.g. not "5 working days"). Pilot ends based on
  operational acceptance criteria, not calendar duration, and depends on
  real equipment usage and return behavior. Pilot does not need to wait
  for every issued device to be returned before Pilot can be considered
  complete.
  *Approved Pilot exit criteria (minimum evidence):* successful
  login/authorized operation; equipment lookup by BCM; QR lookup by
  existing Item Number; a successful Issue from Equipment Pool to the
  Pilot Ward; correct first-receiving-Ward recorded; correct Transaction
  History; at least one representative complete Issue → Receive cycle; a
  usable Receive correctly producing `AVAILABLE_AT_POOL`; defective
  Receive behavior validated only when a genuine defective case occurs
  during Pilot — a defective event must never be manufactured purely to
  complete Pilot criteria (an approved non-production test/UAT procedure
  may instead verify the defective workflow, if repository authority
  permits, without mutating genuine production equipment); no unresolved
  Critical/Blocking defect; and the responsible operational Owner
  confirming the workflow is fit to replace AppSheet for the scoped
  Pilot.
  *Approved Ward-transfer clarification (not a new feature):* the system
  records only the **first** receiving Ward/department for a
  transaction. If physical equipment later moves Equipment Pool → Ward A
  → Ward B → Equipment Pool, the transaction continues to record Ward A
  as the receiving Ward; Ward A → Ward B is **not** a tracked transfer
  workflow in V1 — no transfer endpoint, table, state, lifecycle state,
  or UI is introduced. The final Receive back to Equipment Pool closes
  the transaction according to existing business rules. The first
  receiving Ward remains immutable except through the already-governed,
  audited correction mechanism. This clarification does not change the
  established V1 business model (§5, §30).

- **OD-PR23-6 — Persisted cutover evidence model.**
  *Question:* Should cutover readiness/Go-No-Go evidence be (1)
  documentation/runbook only, (2) a backend-persisted immutable
  readiness snapshot + sign-off (mirroring PR22's own
  `LegacyReconciliationRun`/`SignOff` model), or (3) an external
  governance record referencing system evidence?
  *Trade-offs:* Option 1 is zero implementation cost but weak
  auditability/repeatability and no freshness enforcement (§16). Option
  2 gives the strongest auditability, immutability, and freshness
  guarantees (reusing an already-proven pattern in this codebase), at
  the cost of a new migration and API surface (a genuine PR23B+ scope
  item, not PR23A). Option 3 sits in between but introduces a
  dependency on tooling outside this repository's own system of record.
  *Recommendation:* **Option 2**, deferred to a future PR23 slice — it
  is the only option consistent with this repository's own established
  evidence discipline (PR3's audit framework, PR22's reconciliation
  evidence model) and with §16's freshness requirements.
  *Consequence if unresolved:* PR23B+ cannot be scoped precisely (§27);
  the evidence model in §15 would need to be re-derived per-cutover
  from scattered sources rather than one queryable artifact.
  *Status:* **RESOLVED / OWNER APPROVED.**
  *Approved choice:* **Option 2** — a backend-persisted, immutable
  Cutover Readiness evidence model: a persisted readiness snapshot/run,
  an immutable Go/No-Go/sign-off record, freshness/concurrency
  protection, and permanent audit/provenance references. The future
  implementation should reuse architectural patterns proven by PR22
  where appropriate, without tightly coupling PR23 to PR22 internals.
  Expected future implementation may require additive schema, an
  Alembic migration, a backend service, a REST API, an audit trail, and
  concurrency/freshness checks — **none of which is implemented by this
  Owner Decision Closure PR**; that work remains genuine PR23B+ scope.

---

## 27. Implementation Slices

**Implementation authorization gate (fail-closed):** No PR23B or later
implementation slice may begin until all PR23A Owner Decisions that
materially affect implementation are resolved. **OD-PR23-1 through
OD-PR23-6 are Owner-approved in the proposed PR23 Owner Decision Closure
(§26); PR23B remains blocked until that closure PR itself merges.**
Once the closure PR merges, its real squash SHA becomes the new
authoritative baseline and PR23B becomes eligible to start from it,
governed by this §27 together with the approved choices recorded in
§26. Until then, this document's own status remains as stated in the
header above. If a future governance change explicitly narrows
dependencies per slice, a given slice may begin only after every Owner
Decision that materially affects that specific slice is resolved — the
per-slice mapping below is explanatory rationale for *why* each slice
needs which decisions, not a claim that any subset of decisions alone
authorizes implementation to start today.

Proposed minimal sequence, **none of which is implemented by PR23A**:

- **PR23B — Cutover Readiness Evidence Foundation.** **Implemented.**
  Backend-only: a persisted, immutable `CutoverReadinessRun` model
  (`backend/app/models/cutover_readiness.py`) referencing the exact
  evidence identities in §15 by id — PR20's `ImportSource`, PR21's
  `LegacyMigrationAuthority`, PR22's
  `LegacyMigrationAuthorityCoverage`/`LegacyReconciliationRun`/
  `LegacyReconciliationSignOff`, and (optionally, per OD-PR23-5)
  `Ward` — never duplicating their contents. One additive Alembic
  migration (`0021_cutover_readiness.py`), empirically
  convergence-verified against real PostgreSQL, mirroring PR22B's own
  discipline. A minimal `pending`/`completed` (`running`/`failed`
  reserved for a later slice) lifecycle with a `version` CAS column, a
  DB-level CHECK requiring every mandatory evidence reference before
  `status = 'completed'` (no partial snapshot ever persisted), and
  forward-only supersession via `supersedes_run_id` mirroring
  `LegacyReconciliationRun`'s OD-PR22-3 discipline. A minimal CRUD
  module (`create_readiness_run`/`complete_readiness_run`/
  `get_readiness_run`/`list_readiness_runs`,
  `backend/app/crud/cutover_readiness.py`) validates every evidence
  reference's existence, the sign-off/reconciliation-run pairing, and
  `cutover_instant >= coverage.live_system_start` (§9) inside the same
  transaction as the completion CAS `UPDATE`. A minimal Administrator-
  only-mutation API (`POST/GET /cutover-readiness-runs`,
  `POST .../complete`; read endpoints open to every role, mirroring
  PR22D/E's precedent) exercises the foundation end-to-end. **No
  readiness-gate evaluation (Gates A–G), no BLOCKER/WARNING/INFO
  classification, no Go/No-Go decision/sign-off logic, no frontend, and
  no mutation of `Equipment`/`BorrowTransaction`/`LegacyEquipmentEvent`
  exists in this slice** — completion means only that the immutable
  evidence snapshot was captured, never a readiness or Go/No-Go
  judgment (see the model's own module docstring).
  *Depended on:* OD-PR23-1 (source-of-truth/freeze model shapes what
  evidence is captured), OD-PR23-2 (current-state/open-transaction
  method shapes the evidence identities in §15), OD-PR23-6 (persistence
  model — Option 2, now implemented as described above).
  **PR23B Fix Round 1** (independent review, two P1 findings): (1)
  `database_migration_head` is no longer a `RunCreateRequest` field --
  it is always read server-side from `alembic_version` by
  `_get_current_database_migration_head`, which fails closed
  (`CUTOVER_READINESS_DATABASE_MIGRATION_HEAD_UNAVAILABLE`, 503) if the
  database's own current revision cannot be established as exactly one
  row; (2) completion now validates the whole evidence provenance chain
  — `legacy_coverage_id`'s own `migration_authority_id` must match the
  supplied `legacy_migration_authority_id`, and `reconciliation_run_id`'s
  own `coverage_id` must match the supplied `legacy_coverage_id` — not
  merely that each id independently resolves to an existing row, so an
  immutable snapshot can never mix evidence drawn from two unrelated
  provenance chains. No migration was added (the persisted column shape
  was already correct; only the source/validation of its value changed).
- **PR23C — Readiness Gate Evaluation.** **Implemented.** Backend
  service that evaluates Gates A–F (§12) against live evidence (import
  status, reconciliation sign-off, migration head, etc.) and returns
  BLOCKER/WARNING/INFO (§13) — read-only, no mutation, no Go decision
  yet.
  *Depends on:* PR23B's persisted schema plus every Owner Decision that
  shapes what a gate evaluates — OD-PR23-1 (source-of-truth/freeze),
  OD-PR23-2 (current-state/open-transaction — Gate E), OD-PR23-6
  (evidence model consumed by gate evaluation).
  **PR23C Fix Round 1** (independent review, one P1 finding): Gate B
  resolved `equipment_master_import_source_id -> ImportSource ->
  ImportSession` and checked only `ImportSession.status == 'completed'`,
  never the owning session's `dataset_type` -- a completed source/
  session for a *different* dataset (e.g. `legacy_transaction_history`)
  could be cross-wired into this field and Gate B would incorrectly
  report `GATE_B_SATISFIED`. Fixed at two layers: (1) `_evaluate_gate_b`
  now also checks `dataset_type == EQUIPMENT_MASTER_DATASET_TYPE`,
  BLOCKER (`GATE_B_WRONG_DATASET_TYPE`) on mismatch, distinct from
  `GATE_B_IMPORT_NOT_COMPLETED`; (2) PR23B's own `complete_readiness_run`
  (`_validate_evidence`) now rejects the same mismatch at completion
  time (`CUTOVER_READINESS_EVIDENCE_INVALID`, 422) -- evidence must be
  valid at capture time, not only discovered invalid later by this
  gate's own read-only evaluation. No other evidence reference in
  `CompletionEvidence` is an `ImportSource`/`ImportSession` reference
  (Gate C already correctly scopes its own `dataset_type` check via its
  checksum join), so no further same-class issue was found.
- **PR23D — Go/No-Go Decision + Current-State Re-Issue Support.**
  **Implemented.** Administrator-only
  mutation endpoint recording the Go/No-Go decision (Gate G): an
  immutable `CutoverGoNoGoDecision` model
  (`backend/app/models/cutover_readiness.py`,
  `UNIQUE(cutover_readiness_run_id)`, closed `GO`/`NO_GO` vocabulary),
  one additive Alembic migration (`0022_cutover_go_no_go_decision.py`,
  empirically convergence-verified against real PostgreSQL, mirroring
  PR23B's own discipline), and
  `POST/GET /cutover-readiness-runs/{run_id}/decision`
  (`app/crud/cutover_readiness.create_go_no_go_decision`). Recording a
  decision always performs a fresh re-evaluation of Gates A-F at
  decision time (never a cached or client-supplied evaluation): `GO` is
  rejected if any live BLOCKER exists or any live WARNING code is not
  present in the caller's acknowledgement (the backend stores its own
  canonical, sorted, live-warning-code set, never the raw client
  payload); `NO_GO` never requires readiness success. The same
  lock-order/transaction discipline PR22E's `create_signoff`
  established is reused: lock the run `FOR UPDATE` first, validate
  `status == 'completed'`, validate the run has not itself been
  superseded (a new check distinct from Gate D's own
  `LegacyReconciliationRun` supersession check), validate
  `expected_version`, re-evaluate gates, then insert the decision row
  inside a `db.begin_nested()` SAVEPOINT so a concurrent duplicate
  submission is rejected as a clean structured conflict rather than a
  raw `IntegrityError`, proven by a genuine two-connection PostgreSQL
  concurrency test. Gate A's migration-head check and Gate D's
  reconciliation-freshness check are reused verbatim from PR23C, never
  re-derived; PR23C Fix Round 1's Gate B dataset-type correction is
  preserved unchanged. **No current-state re-issue write endpoint was
  added**: inspection of the existing `POST /borrow` Issue workflow
  confirmed it already satisfies OD-PR23-2's manual re-issue model
  (per-equipment, staff-confirmed, duplicate-OPEN-transaction
  protection already enforced) — no new bulk-mutation mechanism, no
  replay of `LegacyEquipmentEvent` history. Recording a `GO` decision
  performs no cutover action itself (no AppSheet disablement, no
  `Equipment` mutation, no migration execution, no Pilot start) —
  evidence-recording only; actual cutover execution remains PR23F/
  operational-runbook scope.
  *Depends on:* OD-PR23-3 (Go/No-Go and rollback authorization model —
  this slice's own authorization contract), OD-PR23-2 (re-issue
  tooling scope), and the evidence model (OD-PR23-6) the decision is
  recorded against.
  **PR23D Fix Round 1** (CI-red on the PR23D PR itself, one finding):
  migration `0022_cutover_go_no_go_decision`'s two new `ON DELETE
  RESTRICT` foreign keys were not yet rolled into the pre-existing
  whole-schema regression test
  `test_migration_0013_fresh_database_all_foreign_keys_are_restrict`
  (`assert 80 == 78`). Fixed by bumping the expected count to 80 and
  extending the test's own running per-migration commentary; no
  production code changed.
- **PR23E — Frontend/Operator Workflow.** **Implementation in
  progress, not yet merged.** Thai-first
  UI for readiness status, blockers, and the Go/No-Go confirmation
  dialog (§22), mirroring PR22F's established patterns file-for-file
  (`ReconciliationListPage`/`ReconciliationRunDetailPage`/
  `ReconciliationSignOffDialog`). Delivers a run list page
  (`CutoverReadinessListPage.tsx`), a run detail page
  (`CutoverReadinessRunDetailPage.tsx`) presenting Gates A-F
  (BLOCKER/WARNING/INFO items, manual-attestation items) and the
  immutable decision once recorded, and a GO/NO_GO confirmation
  dialog (`CutoverGoNoGoDialog.tsx`). The frontend never computes
  readiness, eligibility, or gate status itself — it only reads and
  renders `GET .../gate-evaluation` and `GET .../decision` verbatim,
  and the dialog submits exactly the four documented
  `DecisionCreateRequest` fields, proven by a dedicated test asserting
  the exact key-set of the submitted payload. The decision action
  (both GO and NO_GO) is shown only under a fail-closed visibility
  rule requiring Administrator role plus a successfully loaded run,
  gate evaluation, and (confirmed-absent) existing decision —
  mirroring PR22F Fix Round 1's own `canEditDisposition` fail-closed
  pattern; loading/error states are never treated as "safe to
  mutate." Only the exact `CUTOVER_DECISION_NOT_FOUND` error code is
  normalized to "no decision yet" inside the decision query; every
  other error re-throws and surfaces as a genuine error state,
  mirroring `ReconciliationRunDetailPage`'s own `signoffQuery`
  pattern. Warning acknowledgement is a checkbox list populated
  exclusively from the current gate-evaluation's live warning items —
  never pre-checked, never a free-text input path, so
  `acknowledged_warning_codes` can only ever contain codes the
  backend itself just reported as live. `NO_GO` remains usable even
  while a BLOCKER exists (it records "not approved," not a readiness
  pass); `GO` is independently re-checked against Gates A-F by the
  backend on every submission regardless of what the frontend allowed
  through — the frontend's `disabled={hasBlocker}` on the GO trigger
  is UX-only guidance, never authoritative. No run-creation or
  run-completion UI, and no new current-state re-issue write endpoint
  or page, were added — the Gate E card links to the existing
  `/borrow` route only.
  *Depends on:* the finalized PR23B–D backend/readiness/sign-off
  contracts, which themselves depend on OD-PR23-1, OD-PR23-2,
  OD-PR23-3, and OD-PR23-6.
- **PR23F — Cutover Runbook + Governance.** Documentation-only:
  operational runbook (actual T0–T4 procedure, contact list, rollback
  steps), final governance sync recording Roadmap PR23 as complete once
  every prior slice has merged and the real cutover-readiness capability
  exists (not the cutover event itself — that is Pilot/Production
  execution, outside any PR's scope).
  *Depends on:* OD-PR23-4 (rollback boundary — the runbook's rollback
  steps have no defined boundary without it), OD-PR23-5 (pilot scope —
  the runbook cannot name a pilot ward/duration without it), and every
  decision consumed by PR23B–E, since this slice documents the
  resulting end-to-end procedure.

This per-slice mapping does not relax the gate stated above: **all six
Owner Decisions remain required before any PR23B+ slice starts**, since
every slice either directly depends on a decision or depends on an
earlier slice that does. This is the **minimal sequence that preserves
independent reviewability** — each slice is reviewable and revertible
on its own, matching this repository's established
one-objective-per-PR discipline (`AGENTS.md`, "Git Discipline").
Repository needs discovered during PR23B may justify collapsing or
further splitting these; this is a recommendation, not a binding
commitment.

---

## 28. Test Strategy

For PR23A itself: none — no runtime code exists to test. For each later
slice:

- **PR23B:** schema/migration tests (upgrade/downgrade, constraint
  checks) mirroring PR22B's own test shape — no gate-evaluation logic
  to test yet.
- **PR23C:** gate-evaluation unit tests per gate (A–F), each exercising
  a real evidence-not-satisfied case and a real evidence-satisfied case,
  plus a staleness/freshness test (§16) proving a superseded
  reconciliation run correctly re-fails Gate D.
  Also a PostgreSQL concurrency test proving Gate D's read reuses PR22's
  existing sign-off query and does not race with an in-flight
  disposition mutation, mirroring PR22D/E's own two-connection test
  precedent.
- **PR23D:** Administrator-only authorization tests for the Go/No-Go
  mutation; a "Go structurally impossible while a BLOCKER exists" test;
  an audit-write test mirroring PR22E's own "sign-off and audit commit
  together" discipline.
- **PR23E:** role-aware usability tests (canReviewCutoverReadiness/
  canRecordGoDecision-style, mirroring PR22F's useAuth pattern), plus a
  proof test that the frontend never computes Go/No-Go itself (mirroring
  PR22F's §29 "no client-side eligibility engine" proof pattern).
- **PR23F:** none — documentation-only, no test surface.

---

## 29. Acceptance Criteria for PR23A

PR23A (this document and its accompanying governance updates) is
complete when:

- The exact repository-defined PR23 scope (§3) is documented, quoted
  verbatim, and no conflict across authoritative sources was found (or,
  if found, was explicitly stopped on and reported — none was found
  here).
- The current AppSheet → application cutover workflow is explicit (§7).
- The source-of-truth transition is defined with a recommendation and
  escalated as an Owner Decision (§8, OD-PR23-1).
- Current live-equipment-state handling is defined with a
  recommendation and escalated as an Owner Decision (§10, OD-PR23-2).
- Outstanding-issued-equipment handling is defined with a
  recommendation and escalated as an Owner Decision (§11, OD-PR23-2).
- Readiness gates are deterministic and explicitly mapped to existing
  repository gates, not redefined from scratch (§12, §20).
- The sign-off/reconciliation dependency is stated exactly as OD-PR22-6
  defines it, with no loosening or tightening (§12 Gate D).
- The temporal boundary is explicit, extending OD-PR22-7 rather than
  replacing it (§9).
- The freeze/concurrency strategy is explicit (§16, §17).
- The rollback model is explicit, with a concrete boundary
  recommendation (§18).
- Post-cutover validation is explicit and reuses only existing
  application capability (§19).
- UAT/Pilot/Production gate mapping is explicit and does not redefine
  any existing gate (§20).
- Every Owner Decision this document could identify is listed with
  options, trade-offs, a recommendation, and a consequence-if-unresolved
  (§26).
- A minimal, independently-reviewable implementation slice sequence is
  proposed (§27), with an explicit fail-closed gate: no PR23B+ slice
  may begin until all six Owner Decisions (OD-PR23-1 through OD-PR23-6)
  are resolved, not merely the subset that most directly names a given
  slice.
- No runtime code — backend, frontend, migration, or test — was changed
  by this PR.

---

## 30. Explicit Non-Changes

To make the "no implementation" boundary unambiguous, this PR
explicitly changes **none** of the following, all of which remain
exactly as merged through PR22G:

- `backend/**` — zero files.
- `frontend/**` — zero files.
- `backend/alembic/versions/**` — zero new migrations; database head
  remains `0020_reconciliation_foundation.py`.
- `backend/tests/**`, `frontend/src/**/*.test.ts(x)` — zero files.
- The four Equipment lifecycle states, their transition tables, or the
  cleaning-is-not-a-state rule.
- The three application roles or the capability groups that gate them.
- The four equipment identifiers (UUID, BCM Code, Item Number, Asset
  Number) or the hospital QR-code contract.
- Any of the seven approved PR22 Owner Decisions (OD-PR22-1 through
  OD-PR22-7) — none reopened, reinterpreted, or extended.
- Any existing API route, request/response schema, or error code.
- Any deployment, backup, or infrastructure configuration — the
  managed-deployment constraint (`docs/ARCHITECTURE_DECISIONS.md`)
  remains exactly as confirmed, unresolved as to specific provider.

---

## Related documents

| Concern | Document |
|---|---|
| Roadmap PR scope, order, dependencies | `docs/audits/04-consolidated-implementation-plan.md` |
| Final Go-Live Gates | `docs/audits/04-consolidated-implementation-plan.md` Part I (§13) |
| PR22 reconciliation/sign-off contract | `docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md` |
| PR21 legacy history import contract | `docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md` |
| Managed deployment constraint | `docs/ARCHITECTURE_DECISIONS.md` |
| Current-state governance/status | `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `knowledge/CONTEXT.md` |
| Decision chronology | `docs/DECISION_LOG.md` |
