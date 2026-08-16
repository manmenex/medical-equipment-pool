# Roadmap PR21 — Legacy Receive and Issue History Import: Design Specification

**Status:** Design only. Not implemented. **Fix Round 1** (architecture
review, findings H1–H4/M1/L1) applied. This document opens Owner
Decisions (§43) and encounters mandatory STOP conditions (§50) because no
real Receive/Issue source artifact exists in this repository, and because
this round's own findings (H1, H3) surfaced additional evidence-dependent
architecture questions that cannot be finalized without that same source
artifact. No implementation, migration, or runtime change is made by this
PR.

**Baseline:** `4cab688708320f1e8523a906f5a5ce17ad1e5d9a` (GitHub PR #97,
Post-PR20 Governance Sync squash merge, on
`claude/medical-equipment-pool-0c7fz0`).

**Roadmap authority:** `docs/audits/04-consolidated-implementation-plan.md`
is Level 4 in the source-of-truth hierarchy
(`docs/PROJECT_PLAYBOOK.md`) — it governs PR21's scope, order,
dependencies, and acceptance criteria. This document narrows *how* PR21
is designed; it does not redefine that scope. Owner Decisions are opened
only where repository evidence cannot answer a business-policy question.

---

## 1. Objective (verbatim from the authoritative plan)

`docs/audits/04-consolidated-implementation-plan.md`, Group 8:

> **PR21 — Legacy Receive and Issue History Import**
> - **Objective:** Import the AppSheet equipment receive-data and equipment
>   issue-data sheets; preserve legacy BME names for later user mapping;
>   normalize and map Ward values; detect duplicate transaction rows; and
>   retain transaction source references.
> - **Version 1 boundary:** These are the only transaction-history sheets
>   in the initial migration. Equipment Verify Checklist history is not
>   required unless a later approved decision explicitly adds it.
> - **Dependencies:** PR19A, PR20.

Both dependencies are merged. PR21 is unblocked from a dependency-ordering
standpoint.

**PR22 boundary (do not absorb):** `docs/audits/04-...md` Group 8
immediately following:

> **PR22 — Legacy Data Validation and Reconciliation**
> - **Objective:** Perform cross-import validation and reconciliation,
>   verify source traceability, review duplicates, and validate the
>   unified display of legacy and new transaction history before Go-live.
> - **Dependencies:** PR20, PR21.

This design does not perform cross-import reconciliation, does not
verify traceability across separately-imported datasets, and does not
build unified legacy/new history validation. **PR21 still owns
write-time idempotency strong enough to avoid duplicate history
insertion within its own import runs (§25) — this is not offloaded to
PR22.** PR22's reconciliation-review UI/workflow is not pulled into
PR21.

---

## 2. Required reading performed

This design is grounded in direct inspection of the merged runtime, not
the roadmap paragraph alone. Sources inspected (file:line references
given throughout this document):

- `AGENTS.md`, `docs/PROJECT_PLAYBOOK.md`, `docs/ENGINEERING_WORKFLOW.md`
- `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `docs/DECISION_LOG.md`,
  `docs/audits/04-consolidated-implementation-plan.md`
- `docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`
- `docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md`
- `backend/app/models/transaction.py`, `backend/app/models/equipment.py`,
  `backend/app/models/master_data.py`, `backend/app/models/user.py`,
  `backend/app/models/import_session.py`, `backend/app/models/audit.py`
- `backend/app/services/borrow_service.py`, `backend/app/crud/transaction.py`
- `backend/app/core/reporting_time.py`, `backend/app/core/audit.py`
- `backend/app/services/import_adapter.py`,
  `backend/app/services/import_adapter_context.py`,
  `backend/app/services/import_adapters/equipment_master.py`,
  `backend/app/services/import_lease.py`,
  `backend/app/services/import_execution_service.py`,
  `backend/app/services/import_validation_service.py`,
  `backend/app/services/import_retention_service.py`,
  `backend/app/services/identifiers.py`
- `backend/app/api/v1/import_sessions.py`, `backend/app/crud/import_dry_run_plan.py`,
  `backend/app/crud/import_retention.py` (Fix Round 1: read specifically
  to verify H3/H4/M1's claims — see §24, §29, §36)
- `backend/app/api/v1/transactions.py`, `backend/app/schemas/transaction.py`
- Repository-wide search for any real legacy Receive/Issue workbook, CSV,
  fixture, or column-level schema description (see §6).

---

## 3. Critical business rule — historical import must not replay live operations

PR21 imports **historical facts**. It must not replay them through the
live dispatch/receipt workflow as if they occurred today.

- **Live dispatch** (`backend/app/services/borrow_service.py:45-150`,
  `borrow()`): requires `Equipment.status == AVAILABLE_AT_POOL`
  (line 75), inserts an `OPEN` `BorrowTransaction`, and calls
  `equipment_crud.change_status_for_dispatch_receipt(..., new_status=ISSUED_TO_WARD, ...)`
  (line 134) — mutating live `Equipment.status`.
- **Live receipt** (`borrow_service.py:153-258`, `return_equipment()`):
  requires `tx.status == OPEN`, maps `ReceiptOutcome` to an
  `Equipment.status` value, and again mutates live `Equipment.status`.
- `backend/app/models/equipment.py:52-97` — `DISPATCH_RECEIPT_TRANSITIONS`
  is the *only* table permitted to move `Equipment.status` into or out
  of `ISSUED_TO_WARD`.
- `borrow_transactions` carries a DB-level unique **partial index**
  `idx_tx_one_active_borrow` on `equipment_id WHERE status = 'open'`
  (`transaction.py:140-148`) — at most one `OPEN` transaction per piece
  of equipment, enforced by PostgreSQL.

**PR21's rule, stated positively:** historical transaction rows are
inserted directly into `borrow_transactions` by the import execution
step. They never call `borrow_service.borrow()` or
`borrow_service.return_equipment()`, never call
`equipment_crud.change_status_for_dispatch_receipt`, and never write an
`EquipmentStatusHistory` row.

---

## 4. Equipment linkage

PR20's `backend/app/services/identifiers.py`
(`normalize_bcm_code()`/`normalize_item_no()`) is dataset-agnostic and
directly reusable by PR21's adapter for resolving a legacy row's stated
identifier(s) to `equipment_id`. PR20's §9 OD-3 case-matrix pattern
("never fabricate a missing identifier") is the governing principle PR21
reuses; the exact case matrix for Receive/Issue rows is blocked on §6/§7.

| Question | Answer |
|---|---|
| Which legacy field identifies Equipment? | **Unknown — blocked on §6.** |
| Can rows have only one of BCM/Item Number? | **Unknown — blocked on §6.** |
| Identifier points to no Equipment? | Blocking finding (§15) — row not imported. |
| BCM and Item Number conflict? | Blocking finding (§15); never silently prefer one. |
| Can PR21 import an orphan transaction? | **No.** `equipment_id` is a NOT NULL FK — orphan rows are validation findings, never imported rows. |

---

## 5. Equipment lifecycle and operational safety (summary; full detail §19, §42)

No lifecycle state is added. No `Equipment.status` mutation occurs
during import. Historical `CLOSED` transactions are always safe with
respect to `idx_tx_one_active_borrow` (only constrains `status='open'`);
historical `OPEN` rows are the risk case, gated by Owner Decision (§16).

---

## 6. Source file contract — STOP: no real source artifact exists

A repository-wide search confirmed no real legacy AppSheet Receive
History or Issue History workbook, CSV, or column-level schema
description exists anywhere in this repository. The only source-adjacent
file, `frontend/src/services/legacyImportFixtures.ts`, is explicitly
labeled by its own header comment as invented UI-mock data, not real
hospital data — **not used as evidence anywhere in this document.**

By contrast, PR20's own OD-1 was resolved only once the Owner supplied a
real `export_template.xlsx` (32-column header list, verified against
4,729 real records). No equivalent evidence exists for Receive/Issue
History.

**This is a mandatory STOP on field-level mapping.** §9/§10 describe
only conceptual fields, not a binding source contract. **Fix Round 1
adds:** this STOP also blocks §7's topology decision and §24's stable
event-identity decision — both require inspecting the actual source
artifact's structure (one workbook vs. two, presence/absence of a stable
per-row reference ID), not just its column semantics. §7, §24, and every
section downstream of them are explicitly marked **NOT READY** until this
resolves.

**Required from the Owner (OD-PR21-0, §43):** the real AppSheet Issue
History export and Receive History export (workbook/CSV or exact
column-level description), exact sheet/tab name(s), header row location,
and a representative row-count sample — plus, per this round's findings,
confirmation of whether Issue History and Receive History are delivered
as **one workbook** (e.g. two sheets/tabs) or **two separate files**, and
whether each row carries any stable identifier (legacy row key,
transaction/reference ID, or event UUID) that survives a corrected
re-export.

---

## 7. Source/session topology (H1) — BLOCKED, options analyzed

**The problem.** PR19's foundation is `ImportSession → exactly one
ImportSource` (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §3-4;
`AdapterInvocationContext` correspondingly carries one
`import_session_id`/`import_source_id`/`source_checksum` per invocation,
`import_adapter_context.py:37-76`). PR21 must reason across **two**
logically distinct datasets (Issue History, Receive History), and one
historical `BorrowTransaction` may need provenance from **both** an
issue row and a receive row (§8). A design that quietly assumes a single
`import_source_id`/checksum/source-row is sufficient for that transaction
is incorrect — this round's review correctly identified that the
previous revision of this document did exactly that.

**Three topology options, evaluated:**

- **(A) One workbook / one `ImportSession` / one `ImportSource`**
  containing both Issue and Receive sheets. Fits PR19's existing
  topology with **zero foundation changes** — the adapter's `parse()`
  step simply selects and parses two sheets from one source, exactly as
  PR20's adapter already selects one sheet from one workbook (source
  contract's "exact sheet/tab selection," §6). Lowest implementation
  risk; requires the real export to actually be delivered this way.
- **(B) One `ImportSession` with multiple `ImportSource`s.** Would
  require an explicit, reviewed **PR19 foundation extension** (today's
  schema and `AdapterInvocationContext` are built around exactly one
  source per session) — out of scope for a PR21-only design and a
  materially larger risk surface, since it touches shared infrastructure
  every other dataset type (including the merged PR20) also depends on.
- **(C) Two `ImportSession`s / two `ImportSource`s**, plus an explicit
  staging/pairing/reconciliation model to join rows across the two
  independent sessions. Fits PR19's topology with no foundation change,
  but pushes real complexity into a new PR21-owned staging/pairing layer
  that has to reconcile two independently-lifecycled sessions (each with
  its own validate/dry-run/execute state machine) into one set of
  historical transactions — a materially harder implementation problem
  than (A), and one that risks quietly re-implementing part of what PR22
  is chartered to own (cross-import reconciliation) inside PR21 instead.

**Recommended default, contingent on OD-PR21-0: Option (A).** If the
real export turns out to be one workbook with separate Issue/Receive
sheets, (A) applies with no PR19 foundation change and no new
staging/pairing layer — the lowest-risk path, and the one most
consistent with this task's own repeated instruction to reuse PR19/PR20
mechanisms unmodified wherever possible. If the real export is delivered
as two genuinely separate files, the fallback is (C), not (B) — (B)'s
foundation-extension cost should only be paid if neither (A) nor (C) can
represent the real deliverable, which cannot be evaluated without seeing
it.

**This is not a final decision.** Per this round's own instruction,
topology remains a **blocking Owner Decision** (folded into OD-PR21-0,
§43) until the real source artifact confirms which structure applies.
§9, §10, §24's stable-identity design, and the final table names in §8
and §30/§34 are **NOT READY** and are not finalized by this document —
only their required *shape* (§8's 1:N requirement) is fixed regardless
of which topology option is ultimately selected.

---

## 8. 1:N source provenance contract

One historical `BorrowTransaction` may be supported by **one Issue
source row and one Receive source row** (§11's pairing model). Provenance
must therefore **not** be modeled as singular fields on the transaction
or a plan row — it requires a 1:N relationship, conceptually:

```
HistoricalTransaction
    |
    +--> HistoricalTransactionSourceRef[*]
```

Each source ref must retain, at minimum:

- `import_session_id`
- `import_source_id`
- source checksum/fingerprint (defense-in-depth copy, mirroring
  `EquipmentMasterDryRunPlan.source_checksum` pattern)
- sheet/tab identifier
- source row number
- source reference/event ID, if present (§24)
- **source event type: `ISSUE` / `RECEIVE`** — required so a paired
  transaction's two refs are distinguishable, and so the legacy operator
  name captured per ref (§13) is attributable to the correct role
  (issuer vs. receiver) without a separate flat-column scheme.

**Table names are not finalized** — they depend on §7's topology
resolution (a two-session topology, option C, would need the ref's
`import_session_id`/`import_source_id` to actually vary per row within
one transaction's pair; a one-session topology, option A, would have
both refs share the same `import_session_id`/`import_source_id` and
differ only in sheet/row/event-type). **The 1:N shape itself is
required regardless of which topology option is ultimately selected** —
this is not itself blocked by §7, only the concrete table/column
definition is.

---

## 9. Issue History semantics (provisional — NOT READY, blocked on §6/§7)

Based solely on the Roadmap objective's wording and the existing
`BorrowTransaction` schema, the conceptual fields a legacy ISSUE row is
expected to carry: equipment identity (§4), issue timestamp (→
`borrowed_at`), receiving Ward (→ `ward_id` via §14), legacy BME/operator
name (→ per-ref provenance, §8/§13), source reference ID if present (→
§8), issue type/routine-vs-on-demand if present, notes if present,
historical status if present (→ provenance-only, mirroring
`BorrowTransaction.legacy_status`). No field is fabricated that the
Roadmap objective does not name. This section is not a binding parse
contract — it is deferred to PR21B, after §7/OD-PR21-0 resolve.

---

## 10. Receive History semantics (provisional — NOT READY, blocked on §6/§7)

Same treatment as §9. Conceptual fields: equipment identity (§4), receive
timestamp (→ `returned_at`), legacy BME/operator name (→ §8/§13),
received condition/outcome if present (→ `condition_on_return`, already
free-text-tolerant), source reference ID (§8), Ward/origin if present,
notes if present. Whether receive records explicitly identify their
matching issue record is unknown without the real source file — §11
defines the matching architecture, not the actual matching keys.

---

## 11. Issue ↔ Receive matching — architecture and validation treatment

Three ways to represent historical pairs: **(A) independent events**
(simplest, but does not produce a `returned_at`-populated closed
transaction — the domain's normal meaning of "history"); **(B) paired
into historical `BorrowTransaction` rows** (most compatible with the
existing single-row-per-transaction schema and existing
search/reporting queries); **(C) a separate approved historical model**
(not recommended — fragments unified transaction history, §27).

**Recommendation: (B).** Architectural, not resolved — the deterministic
matching keys actually available depend on §6/§7.

**Validation treatment (Fix Round 1 correction):** ambiguous pairing is
a blocking `ERROR` finding (§15), **never** a fuzzy/temporal heuristic
match, and — per §15's all-or-nothing gate — an ambiguous pair anywhere
in a batch blocks that entire validation snapshot from producing a
dry-run, not just that one row.

---

## 12. BorrowTransaction compatibility analysis

Full column inventory of `borrow_transactions`
(`backend/app/models/transaction.py:121-349`):

| Column | Type / constraint | Classification |
|---|---|---|
| `transaction_no` | `String(30)` NOT NULL, **UNIQUE**, indexed; normally sequence-generated | Requires explicit historical policy — §20 (OD-PR21-5). |
| `equipment_id` | UUID FK NOT NULL | Derivable if source identifier resolves (§4); otherwise blocks. |
| `quantity` | Integer NOT NULL, default 1 | Not import-relevant; default suffices. |
| `borrowed_at` | `UTCDateTime` NOT NULL | Derivable from source issue timestamp, once normalized to aware UTC (§22). |
| `due_at` | naive datetime, nullable | Dead column (ADR-005) — leave NULL. |
| `returned_at` | `UTCDateTime`, nullable | Derivable for matched/CLOSED rows (§11); NULL for an unmatched/OPEN row, subject to §16. |
| `borrower_user_id` / `received_by_user_id` | UUID FK, nullable | Never fabricated — §21. |
| `borrower_name` | `String(150)`, nullable | Design choice between reusing this field vs. a dedicated provenance column — see §13/§8. |
| `ward_id` | UUID FK, nullable at DB level | Derivable once Ward mapping resolves (§14); unmapped is a validation finding, not silent NULL. |
| `department_id`, `phone_number`, `pickup_location_id`, `dropoff_location_id` | nullable | Not named in the Roadmap objective — leave NULL. |
| `condition_on_return` | `String(30)`, unconstrained, nullable | Derivable if source states a receive condition (§10). |
| `notes` | `Text`, nullable | Derivable if source has a notes field (§40 privacy caveat applies). |
| `status` | NOT NULL, default `OPEN`; exactly `OPEN`/`CLOSED` | Derivable from pairing outcome (§11): `CLOSED` for matched pairs, `OPEN` only if §16 explicitly permits. |
| `dispatch_type`, `routine_round` | nullable | Never inferred (§23) — leave NULL unless source states them. |
| `legacy_status` | `String(20)`, nullable, provenance-only | Direct precedent for the "preserve exact original value, never read by live workflow" pattern reused in §41. |

**No existing column is a blocking gap on its own.** No current `User`
row is ever fabricated (both actor FKs nullable) — no structural need to
fabricate exists.

---

## 13. Legacy BME name preservation policy

No auto-created `User` accounts (`User.password_hash` is NOT NULL —
`backend/app/models/user.py:72-99` — structurally impossible without
fabricating credentials). No display-name-similarity auto-mapping.

**Fix Round 1 refinement:** given §8's 1:N provenance requirement, the
raw legacy operator name is most naturally captured **per source ref**
(tagged by that ref's `event_type` — `ISSUE` actor vs. `RECEIVE` actor),
not as two independent flat columns directly on `borrow_transactions`.
Whether a denormalized convenience copy is also kept directly on
`borrow_transactions` (for query simplicity) is an implementation-time
schema-shape choice, not a normative requirement of this design — the
minimum requirement is that the raw text survives verbatim, attributed
to the correct role, per historical event. `borrower_user_id`/
`received_by_user_id` remain NULL until an explicit, auditable,
Owner-approved later mapping step resolves them (§21).

The later mapping procedure itself is **not** designed here — out of
PR21's Version 1 boundary (OD-PR21-3, §43).

---

## 14. Ward normalization / mapping design

No alias/mapping table exists for Ward anywhere in the codebase
(`backend/app/models/master_data.py:25-35`). PR20 explicitly deferred
this identical class of problem to PR21 (its own §11).

**Architecture:**

```
source raw Ward text
  -> normalized lookup key   (new utility, same shape as
                               identifiers.py's normalize_bcm_code/
                               normalize_item_no)
  -> explicit mapping table  (new: legacy_ward_aliases --
                               raw/normalized text -> ward_id,
                               operator-maintained, not auto-populated
                               by fuzzy matching)
  -> current ward_id
```

Exact match resolves automatically; alias-table hit resolves via the
explicit mapping; unknown/ambiguous/blank is a validation finding (§15),
never a silently-created Ward, never a fuzzy match. Original source Ward
text is preserved regardless of match outcome (§26). Ownership of the
alias table's ongoing curation is **OD-PR21-4** (§43).

---

## 15. Validation model (H2) — all-or-nothing gate and severity taxonomy

**Current PR19 runtime behavior is authoritative and is not modified by
PR21:** if validation contains a blocking `ERROR`, the session becomes
`validation_failed`; dry-run is not admitted from `validation_failed`
(`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §13). The previous
revision of this document contradicted itself — classifying rows as
`ERROR` while also describing them as appearing inside a `DryRunPlan`.
Fix Round 1 resolves this by selecting a single architecture:

**Selected: ALL-OR-NOTHING VALIDATION GATE.** Any blocking `ERROR`
anywhere in the batch → the whole session becomes `validation_failed`;
findings remain visible in the validation result; **no `DryRunPlan` is
created for that session.** A `DryRunPlan` only ever exists for a
session whose validation snapshot passed with zero blocking errors. This
preserves PR19's state machine completely unmodified and is the
lowest-risk choice for a V1 implementation.

**Confirmation: PR21 does not support partial import in V1.** If the
Owner later wants partial import (some rows proceed to dry-run/execute
while others are excluded), that requires a separate, explicitly
approved change to PR19's own validation semantics — out of this
document's scope, and not claimed as already supported anywhere in this
design.

**Consistent severity classification (no condition may read as
"blocking but still a candidate"):**

| Condition | Severity | Effect |
|---|---|---|
| Missing/unresolved equipment identifier, or identifier conflict | ERROR | Session → `validation_failed`, no dry-run |
| Invalid/malformed timestamp | ERROR | Session → `validation_failed`, no dry-run |
| Missing or unmapped or ambiguous Ward | ERROR | Session → `validation_failed`, no dry-run |
| Ambiguous Issue↔Receive pairing (§11) | ERROR | Session → `validation_failed`, no dry-run |
| Duplicate source row/event (§25) | ERROR | Session → `validation_failed`, no dry-run |
| Missing required source identity (§24) | ERROR | Session → `validation_failed`, no dry-run |
| Unmatched ISSUE (§16) | ERROR (default, pending OD-PR21-1) | Session → `validation_failed`, no dry-run |
| Unmatched RECEIVE (§17) | ERROR (default, pending OD-PR21-2) | Session → `validation_failed`, no dry-run |
| Unknown BME name (mapping intentionally deferred) | WARNING | Non-blocking — expected, since BME mapping is a later step (§13), not an import precondition |
| Malformed source structure (wrong sheet, missing headers) | ERROR | Session → `validation_failed`, no dry-run |

**Exactly two severities — no third tier**, matching PR19A's own
taxonomy. `WARNING` never blocks. **Reporting convention preserved:**
`valid_rows = total_rows - invalid_rows` is retained as an informational
count inside the validation result (visible even when the session as a
whole is `validation_failed`, so the operator can see how close the
source is to a clean pass) — it does **not** imply any subset of rows
proceeds to dry-run on its own; the session-level gate is binary.

Final error-code list remains deferred to PR21B/C (contingent on §6),
consistent with §9/§10.

---

## 16. Unmatched historical ISSUE — Owner Decision required

**OD-PR21-1.** Per §15, this is now explicitly an `ERROR`-severity
finding by default — any unmatched issue row blocks the entire session's
validation, not merely "is excluded from execution." The underlying
danger is unchanged from the prior revision: `idx_tx_one_active_borrow`
allows at most one `OPEN` transaction per equipment (§3); importing an
unmatched issue as `OPEN` risks blocking today's live dispatch for a
reason no current operator caused.

**Architectural recommendation unchanged: do not allow unresolved legacy
history to alter current operational eligibility.** If the Owner later
approves representing some unmatched issues as genuinely still-open,
that requires either a separate historical-state representation or an
explicit, reviewed exclusion from the live uniqueness constraint —
neither proposed here. Also **Mandatory STOP condition** (§50).

---

## 17. Legacy RECEIVE without ISSUE — Owner Decision required

**OD-PR21-2.** Per §15, also `ERROR`-severity by default. No synthetic
issue event is ever fabricated to force a pairing. Also **Mandatory STOP
condition** (§50).

---

## 18. Transaction status — no new states

The live lifecycle is exactly `OPEN`/`CLOSED`
(`transaction.py:13-39`). This design does not introduce `LEGACY`,
`UNKNOWN`, `UNMATCHED`, or `IMPORTED` as new enum values. Provenance and
incompleteness are represented through §8's provenance model and §15's
validation findings — never by polluting the operational state machine.

---

## 19. Equipment lifecycle safety

Historical import never changes `Equipment.status`, never derives it
from old transactions, and the backend remains the sole source of truth
for current lifecycle state (§3). No additional lifecycle states.

---

## 20. Transaction number policy — Owner Decision required

**OD-PR21-5.** `transaction_no` is `String(30)` NOT NULL, UNIQUE,
normally sequence-generated. Options: preserve the legacy reference
separately (§8 already captures a source reference ID if present) and
populate `transaction_no` with a distinguishable historical-format
value; use the legacy source's own number directly if it is safe
(globally unique, stable, non-colliding with the live sequence); or
generate a new current-format number — not recommended without
reviewing reporting/API expectations first, since a contemporary-looking
number on a decades-old event is misleading. Not resolved — depends on
§6. Source reference is preserved regardless (§26). Also **Mandatory
STOP condition** (§50), since it touches a NOT NULL/UNIQUE constraint.

---

## 21. User foreign keys

`borrower_user_id`/`received_by_user_id` are both nullable (§12). No fake
`User` rows; no assigning Administrator as the historical actor; no using
the importing Administrator's identity as though they performed the
original transaction.

**Import actor** (current authenticated Administrator running PR21) is
recorded via `record_audit_event()`'s `actor_user_id`
(`backend/app/core/audit.py:157-189`) → `AuditLog.user_id` — the *only*
actor field `AuditLog` has. **Historical operator** (legacy BME name) is
business data captured per §8/§13, never conflated with `AuditLog.user_id`.

---

## 22. Timestamp / timezone policy

`reporting_time.business_date_and_shift()` requires an aware UTC
`datetime` and raises on naive/non-UTC input
(`backend/app/core/reporting_time.py:96-101`) — timestamp normalization
to aware UTC is mandatory before any row is written. Source timezone
(working assumption: Asia/Bangkok, consistent with the existing Day/Night
shift boundaries), whether Excel cells are timezone-naive, ambiguous
date formats, seconds precision, date-only values, and malformed
timestamps are all open questions pending §6 — **ambiguous dates are
never interpreted heuristically**; malformed timestamps are `ERROR`
findings (§15).

---

## 23. Reporting metadata policy

`business_date`/`shift` are computed at read time from stored timestamps
(`transaction.py:251-349`, calling `business_date_and_shift()`) — **no
separate backfill step is needed.** Source timestamps are never
overwritten to fit a desired reporting date/shift; routine round/shift
are never retroactively inferred (§9). An unreceived row's
`returned_at IS NULL` already correctly yields NULL
`receipt_business_date`/`receipt_shift` (`reporting_time.py:204-214`
NULL-propagation) — no special casing needed.

---

## 24. Stable historical event identity and checksum semantics (H3)

**Corrected checksum semantics.** The prior revision of this document
incorrectly implied `ImportSource.checksum` alone prevents cross-session
replay. Verified against the actual schema
(`backend/app/models/import_session.py:125-141`):
`checksum: Mapped[str] = mapped_column(String(128), nullable=False)`,
with `Index("ix_import_sources_checksum", "checksum")` — **a regular
index, not a unique constraint.** A new `ImportSession` can register the
same file/checksum again; nothing in the database prevents it.
`ImportSource.checksum` provides source integrity/fingerprint and
comparison evidence — **it does not provide database-enforced global
replay prevention.** Any prior wording in this document implying
otherwise is superseded by this section.

**Stable historical event identity must not be `ImportSource.id` +
`row_number`.** That identity is only stable inside one exact source
artifact — a corrected/canonical export can shift row numbers, reorder
rows, or contain the same historical event registered under a brand-new
`ImportSource`. This must be a **database-enforced** identity, not an
assumption.

**Candidate stable identity fields** (to be evaluated once §6 resolves):
an AppSheet row key, a transaction/reference ID, an event UUID, or
another immutable source record identifier. **None of the following are
acceptable as a universal event identity without explicit source
evidence:** timestamp alone; equipment + timestamp alone; row number
alone; checksum + row number alone. **If the real source provides no
stable per-row identifier of any kind, this is itself a blocking Owner
Decision** — folded into OD-PR21-0 (§43), since it cannot be resolved
without seeing the source.

---

## 25. Duplicate detection and re-import / idempotency (corrected-export policy)

Three cases this design distinguishes, per Fix Round 1's correction:

- **(A) Exact same source artifact replayed** — same `ImportSource`
  checksum re-registered. Detectable at the source level, but §24
  confirms checksum is not globally unique, so this alone is not
  sufficient protection — row-level idempotency (below) is still
  required even for this case.
- **(B) A corrected export containing the same historical event** —
  different `ImportSource` (different checksum, possibly different row
  numbers), same underlying historical fact. **Not assumed distinct
  merely because the `ImportSource` differs** — this is exactly why §24
  requires a database-enforced stable event identity independent of
  which file/row it arrived in.
- **(C) A truly distinct event with similar values** — a different
  stable identity (§24); imported as a new row.

**A distinct source reference is not automatically treated as a distinct
event** until the source contract (§6) proves that reference is
authoritative and stable across corrected exports. Until §24 resolves
with real evidence, this design does not claim a specific deduplication
mechanism is implemented — it states the requirement (database-enforced
stable identity, checked at write time) and defers the concrete key to
PR21A, gated on OD-PR21-0.

Other cases, unchanged from the prior revision: duplicate ISSUE/RECEIVE
row within one file (§15 `ERROR`, in-workbook duplicate); duplicate
against already-imported legacy history (a database check against
already-*executed* transactions, not just already-uploaded sources);
mapping changes after an earlier dry-run (Ward/BME mapping added later)
— per PR20's persisted-plan immutability contract, a changed mapping
supersedes the prior plan and requires a fresh dry-run, never an
in-place mutation.

---

## 26. Source traceability design

Every imported transaction must be traceable back to its exact source
row via §8's provenance refs: `ImportSession.id`, `ImportSource.id`,
`ImportSource.checksum`, sheet/tab identifier, source row number, and
source reference/event ID if present. Normalized provenance is
sufficient — no unnecessary full raw-row dump — consistent with PR19A's
redaction policy (§36).

---

## 27. Historical vs. live transaction separation

**Key invariant:** legacy records are historical and immutable through
normal live operational commands. A live receipt cannot accidentally
close an imported historical `CLOSED` transaction (`close()` requires
`status='open'`). A live dispatch is not blocked by a legacy historical
record unless an explicit current `OPEN` state was intentionally
imported under an approved policy (§16).

No `source_kind` (`LIVE`/`LEGACY_IMPORT`) column is added — §8's
provenance link already distinguishes an imported row (always has a
non-null provenance ref) from a live row (never does), satisfying the
"unified transaction history" requirement (§1) without unnecessary
schema surface. Revisit only if PR22's reconciliation work finds a
concrete need.

---

## 28. Dry-run contract

Per §15, a `DryRunPlan` is only ever created from a session whose
validation snapshot passed with zero blocking errors — never a
mixed/partial plan. PR19/PR20's persisted-plan *pattern* (immutable
header + rows, `active`/`superseded`/`consumed`/`failed` lifecycle,
explicit confirm gate) is reused; the concrete tables are PR21-owned
(§34), since the existing `EquipmentMasterDryRunPlan`/`Row` tables are
upsert-oriented (`action IN ('CREATE','UPDATE','SKIP')`,
`target_equipment_id`, `expected_equipment_version`) and do not fit an
insert-oriented transaction import. The dry-run shows historical import
effects (paired transactions, duplicate rows, unmapped Wards, unresolved
equipment, preserved legacy BME names) without writing any
`borrow_transactions` row, via PR19's existing `READ ONLY` transaction
enforcement.

---

## 29. Generic persisted-plan API architecture (H4)

**Verified: the current PR20 GET/confirm endpoints are hardcoded to
Equipment Master, not a generic import-session plan API.**
`backend/app/crud/import_dry_run_plan.py` imports and operates on
`EquipmentMasterDryRunPlan`/`EquipmentMasterDryRunPlanRow` by concrete
type in every function (`get_current_plan`, `list_plan_rows`,
`confirm_plan`, etc. — lines 12, 32-234). `backend/app/api/v1/import_sessions.py`'s
`GET /{session_id}/dry-run-plan` (line 328) and
`POST /{session_id}/dry-run-plan/{plan_id}/confirm` (line 388) call this
CRUD module directly. **PR21 cannot simply create new PR21 plan tables
and claim these endpoints "reuse" — they would need to be extended to
even know PR21's tables exist.**

**Selected architecture: generalize the existing generic transport,
dispatch to adapter-owned plan providers, keep persistence
dataset-specific.** Concretely:

```
GET  /import-sessions/{session_id}/dry-run-plan
POST /import-sessions/{session_id}/dry-run-plan/{plan_id}/confirm
   |
   +--> generic route handler (existing, in import_sessions.py)
   |         reads ImportSession.dataset_type
   +--> dispatches to a per-dataset-type plan-provider
             (EquipmentMaster's existing behavior becomes the first/
              default case; PR21 registers its own provider)
```

This mirrors the pattern already established for parse/validate/execute
via `register_adapter()`/`get_adapter()` (`import_adapter.py:285-295`) —
a per-dataset-type provider lookup, not a duplicated endpoint family.
**This requires real, non-trivial work on shared PR19/PR20 infrastructure**
(`import_dry_run_plan_crud` and the two endpoints above are not
dataset-agnostic today) — this is flagged explicitly as its own
implementation-slice question in §44, not something PR21A gets for free.
Duplicating a whole second endpoint family (e.g.
`/legacy-history-dry-run-plan`) is rejected as the default — it would
fragment the API surface without a compelling reason, and this design
does not identify one.

---

## 30. Plan and plan-row contract shape

**Plan summary response:** `plan_id`, `session_id`, `dataset_type`,
`created_at`, current/superseded/confirmed state, aggregate counts,
warning counts. **Plan-row response:** stable row ID, plan ID,
display/action category, safe normalized presentation fields, pagination
cursor. **Exact-plan identity is always `session_id` + `plan_id`** —
never inferred as "the latest plan." Every page of a paginated row list
must be scoped to the same immutable `plan_id`.

---

## 31. Pagination contract

Cursor pagination with a validated limit; cursor binds to the exact
`plan_id` it was issued for; a malformed cursor returns a structured
client error; a cursor issued for a different plan is rejected, not
silently reinterpreted. No unbounded/thousands-of-rows single response —
matches PR20's existing `list_plan_rows` cursor-pagination shape
(`import_dry_run_plan.py:222-234`), generalized per §29.

---

## 32. Missing / foreign / stale plan semantics

Preserves PR20's existing, already-verified semantics
(`backend/app/api/v1/import_sessions.py:328-425`), generalized per §29
rather than reinvented:

- **READ** (`GET .../dry-run-plan`): missing/never-existed plan → `404
  IMPORT_DRY_RUN_PLAN_NOT_FOUND` (verified: `import_sessions.py:339-342`).
- **CONFIRM** (`POST .../confirm`): `404` only for an unknown session id;
  missing plan, foreign-session plan, or superseded/stale plan all
  unify to `409 IMPORT_DRY_RUN_PLAN_STALE` (verified:
  `import_sessions.py:407-425` docstring). No foreign-plan existence is
  ever leaked through a distinct error shape.

---

## 33. Confirmation RBAC / audit

**RBAC:** Administrator-only, via the existing
`require_roles(*ADMINISTRATOR_ONLY_ROLES)` dependency already applied to
every import-session endpoint including confirm (verified:
`import_sessions.py:394`) — reused as-is, no new permission contract
invented. **Audit:** confirmation records actor, import session, plan
ID, dataset type, and timestamp, with no raw source payload — via the
existing `record_audit_event()`/`AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED`
mechanism (§38), not a second audit framework.

---

## 34. Plan persistence ownership decision

**Selected: fully adapter-specific plan tables, behind the generalized
generic API from §29** — the same shape the existing
`EquipmentMasterDryRunPlan`/`Row` tables already use (they are not a
shared generic header table today; each adapter owns its own plan
tables). PR21 introduces its own header/row tables (§8's provenance
model attaches to the row level), reachable through the same generic
`GET`/`confirm` routes once §29's dispatch layer exists. This preserves:
immutable plan, exact plan confirmation (§30), pagination (§31),
adapter ownership, retention (§36), execution reuse (§35), and creates
**no PR20 regression** — Equipment Master's existing behavior becomes
the dispatch layer's default/first case, unchanged.

---

## 35. Execution contract

Reuses PR19's claim, idempotency, lease, heartbeat, fencing, recovery,
audit, and retention mechanisms unmodified (PR19A's own design doc: no
new lease/heartbeat/fencing/recovery code per adapter). PR21's adapter
implements the same `on_execution_success`/`on_execution_failure`/
`on_execution_recovery` hook triple PR20E's design maintains for the
**Job → Session → Plan/sub-resource** lock order
(`equipment_master.py:1496-1536`), applied to PR21's own dry-run-plan
sub-resource (§28/§34). Execution never mutates `Equipment` (§3, §19)
and never invokes live dispatch/receipt transitions (§3). Confirmation
flows through §29's generalized confirm endpoint (§33).

---

## 36. Retention design (M1) — policy vs. implementation

**PR19's 180-day retention POLICY is reused unmodified**
(`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §18: 180-day
post-terminal, redact-in-place, `IMPORT_RETENTION_DAYS`-configurable, no
V1 Administrator UI, no legal/manual hold).

**Fix Round 1 correction — this is not "unchanged" at the implementation
level.** Verified: `backend/app/crud/import_retention.py`'s
`redact_session()` explicitly imports `EquipmentMasterDryRunPlanRow`
(line 9) and issues a direct `update(EquipmentMasterDryRunPlanRow)...`
statement against it (lines 139-140) — it has **no generic/dataset-type
dispatch mechanism today.** PR21's new plan/provenance content (§8, §34)
would **not** be redacted by the existing retention runtime unless
extended.

**Selected direction: generic adapter retention hook**, for symmetry
with the existing `ImportAdapter` hook pattern
(`on_execution_success`/`failure`/`recovery`) — each adapter registers a
redaction callback, invoked by `redact_session()` within the same
transaction, rather than `import_retention_service.py` needing to know
every dataset type by name as new ones are added (the alternative —
explicit additive PR21-specific redaction logic bolted directly onto
`redact_session`, parallel to the existing Equipment-Master-specific
block — was also evaluated and rejected as not scaling past two dataset
types).

**Required invariant, restated precisely:** retention redaction of PR21
artifacts **and** `ImportSession` retention-state advancement must be
atomic in one caller-owned transaction — matching the existing
all-or-nothing per-session redaction transaction `redact_session()`
already provides for Equipment Master.

**Corrected summary wording, replacing "retention unchanged":**
*retention policy is unchanged; retention implementation requires
additive PR21 integration (a new adapter retention hook, or equivalent),
which is real, non-trivial work — not automatic reuse.*

---

## 37. Retention boundary — temporary vs. permanent provenance

**Temporary import artifact retention** (180-day policy, §36) governs
`ImportSession`/`ImportSource`/`ImportRowError`/PR21's own dry-run-plan
tables (§34) — the *import process's* artifacts.

**Permanent historical transaction/provenance retention:** once a legacy
row executes into `borrow_transactions` plus its §8/§13 provenance refs,
it becomes operational historical data, exactly like a live-created
transaction — **never deleted or redacted on the 180-day timer.**

**Which minimal provenance fields survive after raw-source redaction**
(mirroring PR19A's existing redact-in-place split, which purges
free-text/`notes`/`filename`/`message`/`field` content but retains
`error_code`/`severity`/`row_number`/summary counts indefinitely):
survive — `import_session_id`, `import_source_id`, sheet/tab identifier,
row number, event type, and the source reference/event ID if that turns
out to be §24's chosen stable identity (needed permanently for
audit/traceability/idempotency, even after raw redaction). Redacted —
any free-text content ever staged alongside a finding (this design does
not propose storing full raw rows, §26, so there is little beyond
`ImportRowError`'s own fields, which PR19A already redacts generically).

---

## 38. Audit design

Restated from §21/§33: audit records the import actor (`AuditLog.user_id`
via `record_audit_event()`), never the historical operator (which is
business data, §8/§13). Batch/session/source and execution outcome
recorded via the existing `AUDIT_ACTION_IMPORT`/
`AUDIT_ACTION_IMPORT_RECOVERY`/`AUDIT_ACTION_IMPORT_FENCE_LOST`/
`AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CREATED`/
`AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED` constants
(`backend/app/core/audit.py:48-80`), `entity_type="import_session"`. No
new audit-action constant proposed.

---

## 39. Frontend

PR19B already previewed Receive History and Issue History as categories
in the Legacy Import UI (mock/placeholder data). PR21's frontend slice
(PR21E, §44) reuses that existing architecture and replaces the mocks
with real PR21 APIs (via §29's generalized endpoints) — no frontend
redesign. Thai-first, mobile-first, minimal typing, large touch targets,
Administrator-controlled workflow all preserved. No frontend file is
touched by this Design PR (§49).

---

## 40. Security / privacy assessment

None of PR21's conceptual fields (§9, §10) are patient-related. **Cannot
be fully assessed without the real source file (§6)** — a free-text
`notes` field, if present, could plausibly contain patient names,
HN/MRN, or clinical free-text incidentally entered by staff. Explicit
policy, pending source-file review: patient-identifying data is out of
scope and never silently imported; if found present, a reject/redact/
ignore policy requires explicit Owner approval before any free-text
field reaches the database. **OD-PR21-6** (§43), **Mandatory STOP
condition** (§50), contingent on §6.

---

## 41. Schema assessment (gap analysis)

No migration is created by this Design PR.

| Proposed addition | Why existing schema is insufficient |
|---|---|
| `HistoricalTransactionSourceRef`-shaped 1:N provenance table(s) (§8), including per-ref legacy operator-name capture (§13) | No existing link from a transaction row back to import provenance exists at all; a flat single-provenance-per-transaction design cannot represent §8's required 1:N shape. |
| `legacy_ward_aliases` mapping table (§14) | Confirmed absent from `master_data.py`. |
| PR21-owned dry-run plan header/row tables (§34) | Existing `EquipmentMasterDryRunPlan`/`Row` are upsert-oriented and Equipment-specific; do not fit an insert-oriented transaction import. |
| Generic dry-run-plan API dispatch layer (§29) — code change, not schema, but listed here as a real prerequisite | `import_dry_run_plan_crud` and the two `import_sessions.py` endpoints are hardcoded to Equipment Master today; no dataset-type dispatch exists. |
| Adapter retention hook (§36) — code change, not schema | `redact_session()` is hardcoded to `EquipmentMasterDryRunPlanRow` today; no generic dispatch exists. |
| Historical-sentinel handling for `transaction_no` (§20) | NOT NULL/UNIQUE with no historical-import carve-out today; exact mechanism pending OD-PR21-5/§6. |

Every schema addition is additive; none of it alters or constrains any
existing live-workflow column.

---

## 42. Concurrency / live safety

Imported historical `CLOSED` records never interfere with current `OPEN`
transactions (`idx_tx_one_active_borrow` only constrains `status='open'`,
§3). Unique constraints (`transaction_no`, §20) never collide with the
live sequence by using a distinct historical scheme. **Write-time
idempotency is required, using §24's stable event identity — this is
not deferred to PR22** (§1). PR19's execution single-winner claim is
reused unmodified (§35).

**Historical `OPEN` import (§16) is the one case that cannot be
guaranteed safe by architecture alone** — if ever approved, it directly
competes with live dispatch for `idx_tx_one_active_borrow`. Safe paths
if approved: a maintenance-window requirement (stated explicitly, not a
silently weakened constraint), or the Owner deciding historical-OPEN
import is simply not needed (the recommended default).

---

## 43. Required Owner Decisions

- **OD-PR21-0 (blocking).** Real Issue/Receive History source
  artifact(s). **Fix Round 1 expands this decision's scope**: it now
  also requires confirming (a) §7's source/session topology (one
  workbook vs. two files) and (b) §24's stable per-row event identity
  (does one exist in the real source, and if so which field). Every
  other field-level or evidence-dependent decision below remains
  provisional until this resolves.
- **OD-PR21-1.** Unmatched historical ISSUE-row policy (§16) —
  recommendation: block/reconcile by default (now `ERROR`-severity per
  §15, not merely an execution-time exclusion).
- **OD-PR21-2.** Unmatched historical RECEIVE-row policy (§17) — same
  treatment.
- **OD-PR21-3.** Legacy BME-name mapping-procedure boundary (§13).
- **OD-PR21-4.** Ward alias-mapping table ownership/curation (§14).
- **OD-PR21-5.** Historical `transaction_no` policy (§20), contingent on
  OD-PR21-0.
- **OD-PR21-6.** Patient/clinical free-text handling (§40), contingent
  on OD-PR21-0.

No Owner Decision above is resolved by this Fix Round. This round
selected and documented **architecture** (H2's validation model, H3's
corrected checksum semantics, H4's generic plan API direction, M1's
retention-hook direction) where the repository's own runtime behavior
already answers the question — it did not invent business-policy answers
that depend on evidence this repository does not have.

---

## 44. Proposed implementation slices (provisional)

**Design Gate 1 (prerequisite to any slice below): source evidence
(OD-PR21-0) and the Owner Decisions in §43 that depend on it.** No slice
below is "ready today."

- **PR21-Foundation (new, Fix Round 1 addition)** — the shared-
  infrastructure work identified by H4/M1: generalizing the
  dry-run-plan API dispatch layer (§29) and adding the adapter retention
  hook (§36). This touches `import_dry_run_plan_crud`,
  `import_sessions.py`, and `import_retention_service.py`/
  `import_retention.py` — shared PR19/PR20 infrastructure, not
  PR21-specific data — and carries **PR20-regression risk** that
  deserves isolated review separate from PR21's own dataset-specific
  schema. Not blocked on OD-PR21-0 — this slice's scope does not depend
  on Receive/Issue field-level detail.
- **PR21A — Historical Transaction Schema / Provenance Foundation.**
  §8's 1:N provenance tables, §14's `legacy_ward_aliases`, §34's plan
  tables. **Blocked on:** §7 topology resolution (table shape depends on
  it), OD-PR21-3/4/5.
- **PR21B — Issue History Parser + Validation.** **Blocked on:**
  OD-PR21-0, §4's identifier case matrix, §15's frozen error-code list,
  §24's stable identity.
- **PR21C — Receive History Parser + Matching/Validation.** **Blocked
  on:** OD-PR21-0, OD-PR21-1, OD-PR21-2, §11's finalized matching keys.
- **PR21D — Persisted Dry-run + Historical Transaction Execution.**
  **Blocked on:** PR21-Foundation, PR21A–C.
- **PR21E — Frontend Real Integration.** **Blocked on:** PR21D.
- **PR21F — Governance Sync.** After all approved slices merge, per
  `docs/ENGINEERING_WORKFLOW.md` §14 — not performed by this Design PR
  (§48).

---

## 45. Readiness table

| Area | Status | Blocking? | Required before slice |
|---|---|---|---|
| Source topology (§7) | BLOCKED BY OD-PR21-0 | YES | Before PR21A's table shape, PR21B/C |
| Stable event identity / replay semantics (§24) | BLOCKED pending source evidence | YES | Before PR21B/C, PR21-Foundation's idempotency check |
| Validation semantics (§15) | RESOLVED: all-or-nothing PR19 gate | NO | — |
| Generic persisted-plan API (§29) | RESOLVED design contract | NO (design); YES the *implementation* is a real prerequisite slice (PR21-Foundation) | Before PR21D |
| Retention integration (§36) | RESOLVED design direction | NO (design); YES the *implementation* is a real prerequisite slice (PR21-Foundation) | Before PR21D |
| Unmatched ISSUE/RECEIVE policy (§16/§17) | NOT RESOLVED | YES | Before PR21C |
| Ward mapping ownership (§14) | Architecture resolved; ownership NOT RESOLVED | Partially | Before PR21A's alias table is operational |
| BME mapping-procedure boundary (§13) | Architecture resolved; boundary NOT RESOLVED | Partially | Before PR21B/C |
| Patient/clinical data handling (§40) | CONTINGENT on OD-PR21-0 | YES (if source contains such data) | Before PR21B/C |

**PR21 implementation overall: NOT READY** until the source-dependent
blockers above close.

---

## 46. Test strategy

- **Source contract:** wrong sheet, missing headers, duplicate headers,
  malformed dates, formulas/macros, oversized file — contract finalized
  after §6.
- **Equipment:** valid identity, not found, identifier conflict (§4).
- **Ward:** exact mapping, alias, unknown, ambiguous, blank (§14).
- **BME:** preserved raw name per event type, no fake-user creation
  (§13, §21).
- **Pairing:** deterministic pair, ambiguous pair (ERROR, whole-session
  block per §15), missing issue, missing receive, duplicate source
  reference (§11, §16, §17).
- **Validation gate:** any single blocking `ERROR` anywhere in a batch
  correctly fails the whole session (`validation_failed`) and produces
  no `DryRunPlan` — regression-tested explicitly, since this is the
  H2 architecture decision (§15).
- **Idempotency:** same file replay, same event replayed via a
  corrected export with different `ImportSource`/row numbers, truly
  distinct events not falsely merged (§25).
- **Live safety:** current `Equipment.status` unchanged; current `OPEN`
  transaction unaffected; historical import does not block live
  dispatch (`idx_tx_one_active_borrow` regression tests, §3, §42).
- **Generic plan API:** dispatch-by-`dataset_type` correctness; **no
  PR20 regression** — Equipment Master's existing plan
  GET/confirm/pagination/404/409 behavior verified unchanged after §29's
  generalization.
- **Retention:** adapter retention hook invoked atomically with
  `ImportSession` retention-state advancement (§36); PR21 artifacts
  actually redacted, not silently skipped.
- **PostgreSQL:** stable event-identity uniqueness enforcement (once
  chosen, §24), concurrency, rollback, atomic execution (§35, §42).
- **Reporting:** timestamps normalize correctly to aware UTC (§22);
  business_date/shift derive correctly for both sides of a pair; unified
  history ordering alongside live transactions (§23, §27).

---

## 47. Design deliverable

This document is that deliverable — self-contained, standing on its own
without depending on GitHub review comments for its normative contract.
Fix Round 1's corrections are incorporated directly into the relevant
sections above, not appended as a separate "see review" note.

---

## 48. Governance update (this Design PR's own scope)

Per `docs/ENGINEERING_WORKFLOW.md` §6/§7 and PR19A/PR20's own design-PR
precedent, this Fix Round's governance-update scope remains limited to:
this design document, and a new `docs/DECISION_LOG.md` entry recording
the architecture decisions made in this fix round (H2's selected
validation model, H3's corrected checksum semantics, H4's generic-API
direction, M1's retention-hook direction) — **without** claiming any
Owner Decision in §43 is resolved. **Not performed:** any change to
`docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`, `knowledge/*`, or
`docs/audits/04-consolidated-implementation-plan.md`. **GitHub PR #97's
accepted non-blocking P2 follow-up remains untouched and unresolved by
this PR** — this fix round edits neither
`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md` nor the PR20-related
content of `docs/DECISION_LOG.md`.

---

## 49. Scope guard for this PR

**Touched:** `docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`
(revised), `docs/DECISION_LOG.md` (one new entry, this fix round's
architecture decisions only). **Not touched:** `backend/**`,
`frontend/**`, `alembic/**`, `tests/**`, `.github/**`, Docker/runtime
configuration, `docs/ROADMAP.md`, `docs/ROADMAP_STATUS.md`,
`knowledge/**`, `docs/audits/04-consolidated-implementation-plan.md`. No
PR21 runtime implementation is performed.

---

## 50. Mandatory STOP conditions encountered

- **Actual Receive/Issue source schema unavailable — ENCOUNTERED** (§6).
- **Source topology unknown — ENCOUNTERED** (§7, folded into OD-PR21-0).
- **Source event identity unknown — ENCOUNTERED** (§24, folded into
  OD-PR21-0).
- **Issue↔Receive deterministic matching unknown — ENCOUNTERED**
  (§11, depends on §6/§7).
- **Unmatched ISSUE policy unknown — ENCOUNTERED** (§16, OD-PR21-1).
- **Unmatched RECEIVE policy unknown — ENCOUNTERED** (§17, OD-PR21-2).
- **Ward mapping policy — architecture RESOLVED, operational ownership
  NOT RESOLVED** (§14, OD-PR21-4) — not a full stop on the architecture
  itself.
- **Historical operator representation — architecture RESOLVED, later
  mapping-procedure boundary NOT RESOLVED** (§13, OD-PR21-3) — not a
  full stop on the architecture itself.
- **BorrowTransaction schema cannot represent history without
  fabrication — NOT ENCOUNTERED**; §12 confirms no column requires
  fabricating a value.
- **Live transaction uniqueness can be affected — risk identified and
  contained** by OD-PR21-1's default recommendation (§16, §42); not an
  unresolved stop on its own, but downstream of OD-PR21-1.
- **Patient/HN/MRN data present without an approved handling policy —
  CONTINGENT, cannot be evaluated without §6** (§40, OD-PR21-6).
- **A new transaction lifecycle state appears necessary — NOT
  ENCOUNTERED** (§18).
- **PR21 requiring a change to PR19/PR20 safety semantics — NOT
  ENCOUNTERED**; every safety mechanism (§35, §36) is reused unmodified.
  (§29's generic-API generalization and §36's retention hook are
  additive extensions to shared *infrastructure*, not changes to *safety
  semantics* — no lock order, fencing, claim, or audit contract is
  altered.)

**Net effect: PR21 implementation is NOT READY.** OD-PR21-0 (with its
Fix-Round-1-expanded scope covering topology and stable event identity)
and OD-PR21-1/OD-PR21-2 must resolve before PR21B/C can begin.
PR21-Foundation (§44) is not blocked by source evidence and could
proceed once independently reviewed, but no slice in this document is
declared ready today.

---

*(End of design document. See the PR description for the required final
report covering validation, diff statistics, and confirmation items.)*
