# Roadmap PR21 — Legacy Receive and Issue History Import: Design Specification

**Status:** Design only. Not implemented. This document defines the
architecture and contract for PR21. It opens Owner Decisions (§34) and
encounters a mandatory STOP condition (§41) on field-level source mapping
because no real Receive History or Issue History source artifact exists
anywhere in this repository as of this document's baseline. No
implementation, migration, or runtime change is made by this PR.

**Baseline:** `4cab688708320f1e8523a906f5a5ce17ad1e5d9a` (GitHub PR #97,
Post-PR20 Governance Sync squash merge, on
`claude/medical-equipment-pool-0c7fz0`).

**Roadmap authority:** `docs/audits/04-consolidated-implementation-plan.md`
is Level 4 in the source-of-truth hierarchy
(`docs/PROJECT_PLAYBOOK.md`) — it governs PR21's scope, order, dependencies,
and acceptance criteria. This document narrows *how* PR21 is designed; it
does not redefine that scope. Where this document opens an Owner Decision,
it is because repository evidence cannot answer a business-policy question —
never to expand or reinterpret the authoritative scope below.

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

Both dependencies are merged (PR19A: GitHub PR #83/#84/#85/#86; PR20:
GitHub PR #89–#96). PR21 is unblocked from a dependency-ordering
standpoint.

**PR22 boundary (do not absorb):** `docs/audits/04-...md` Group 8
immediately following:

> **PR22 — Legacy Data Validation and Reconciliation**
> - **Objective:** Perform cross-import validation and reconciliation,
>   verify source traceability, review duplicates, and validate the
>   unified display of legacy and new transaction history before Go-live.
> - **Dependencies:** PR20, PR21.

This design does not perform cross-import reconciliation, does not verify
traceability across separately-imported datasets, and does not build
unified legacy/new history validation. PR21 imports and preserves; PR22
reconciles and verifies.

---

## 2. Required reading performed

This design is grounded in direct inspection of the merged runtime, not
the roadmap paragraph alone, per the assignment's explicit instruction.
Sources inspected (file:line references given throughout this document):

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
- `backend/app/api/v1/transactions.py`, `backend/app/schemas/transaction.py`,
  `backend/tests/test_transaction_search.py`
- Repository-wide search for any real legacy Receive/Issue workbook, CSV,
  fixture, or column-level schema description (see §6).

---

## 3. Critical business rule — historical import must not replay live operations

PR21 imports **historical facts**. It must not replay them through the
live dispatch/receipt workflow as if they occurred today. This is a
hard architectural boundary, evidenced directly in the merged runtime:

- **Live dispatch** (`backend/app/services/borrow_service.py:45-150`,
  `borrow()`): requires `Equipment.status == AVAILABLE_AT_POOL`
  (line 75), inserts an `OPEN` `BorrowTransaction`, and then calls
  `equipment_crud.change_status_for_dispatch_receipt(..., new_status=ISSUED_TO_WARD, ...)`
  (line 134) — mutating live `Equipment.status`. It also writes an audit
  row for `action="borrow"`.
- **Live receipt** (`borrow_service.py:153-258`, `return_equipment()`):
  requires `tx.status == OPEN`, maps `ReceiptOutcome` to an
  `Equipment.status` value via `RECEIPT_OUTCOME_TO_STATUS` (lines 39-42),
  and again calls `equipment_crud.change_status_for_dispatch_receipt`
  (mutating live `Equipment.status`) plus an `action="return"` audit row.
- `backend/app/models/equipment.py:52-97` — `DISPATCH_RECEIPT_TRANSITIONS`
  is the *only* table permitted to move `Equipment.status` into or out of
  `ISSUED_TO_WARD`; a generic admin status-change endpoint
  (`MANUAL_LIFECYCLE_TRANSITIONS`) is explicitly forbidden from touching
  it.
- PR20's own precedent (`equipment_master.py:1390-1402`,
  `_apply_create_row`) already refuses to create Equipment directly into
  `ISSUED_TO_WARD` without a corresponding `BorrowTransaction`, because
  doing so "would violate the invariant that `ISSUED_TO_WARD` equipment
  always has an active transaction."
- `borrow_transactions` carries a DB-level unique **partial index**
  `idx_tx_one_active_borrow` on `equipment_id WHERE status = 'open'`
  (`transaction.py:140-148`) — at most one `OPEN` transaction per piece
  of equipment, enforced by PostgreSQL, not just application code.

**PR21's rule, stated positively:** historical transaction rows are
inserted directly into `borrow_transactions` by the import execution
step. They never call `borrow_service.borrow()` or
`borrow_service.return_equipment()`, never call
`equipment_crud.change_status_for_dispatch_receipt`, and never write an
`EquipmentStatusHistory` row. `Equipment.status` and the current
`ISSUED_TO_WARD`/`AVAILABLE_AT_POOL`/`UNAVAILABLE_DEFECTIVE`/
`DECOMMISSIONED` lifecycle are exclusively today's operational truth —
PR21 never derives or overwrites it from history (see §19).

The one case that requires the most care is a historical `OPEN`
transaction (an unmatched legacy issue with no matching receive — see
§16): inserting it would compete for the same
`idx_tx_one_active_borrow` slot as a live dispatch on the same equipment,
and would misrepresent equipment as "currently issued" when it may not
be. This is why §16 treats unmatched historical issues as a blocking
Owner Decision rather than an architectural default.

---

## 4. Equipment linkage

PR20 established two normalization utilities
(`backend/app/services/identifiers.py`):
`normalize_bcm_code()` and `normalize_item_no()`. These are dataset-agnostic
and directly reusable by PR21's adapter for the same purpose: resolving a
legacy row's stated identifier(s) to `equipment_id` (UUID FK, NOT NULL on
`borrow_transactions`).

Per §9 OD-3 of the PR20 design (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md:1943-2013`),
BCM is the primary legacy matching key and Item Number a secondary
integrity check, with a seven-case matrix resolving blank/present ×
BCM/Item-No combinations, cross-identity conflicts, and duplicates. PR21
should reuse the **same governing principle** — "never fabricate a missing
identifier" — but the exact case matrix for Receive/Issue rows cannot be
finalized without knowing which identifier(s) the legacy sheets actually
carry (§6 STOP applies here too). This document therefore establishes the
architecture (reuse `identifiers.py`; equipment resolution happens once,
during `preload_business_context()`, cached onto the raw row, never
re-derived downstream — mirroring `equipment_master.py:674-711`) without
finalizing the case matrix.

**Required design questions, and their current answer:**

| Question | Answer |
|---|---|
| Which legacy field identifies Equipment? | **Unknown — blocked on §6.** |
| Is BCM present? Is Item Number present? Can rows have only one? | **Unknown — blocked on §6.** |
| Can the source contain historical identifiers no longer matching current Equipment? | Architecturally assumed possible (equipment gets decommissioned/renumbered over years); the design must treat "identifier present but no matching Equipment row" as a validation finding (§24), never a fabricated match. |
| What happens when identifier points to no Equipment? | Blocking `ERROR` finding (analogous to PR20's `EQUIPMENT_MASTER_*` not-found codes) — row is not imported, transaction is not orphaned into the database. |
| What happens when BCM and Item Number conflict? | Blocking `ERROR` finding; never silently prefer one over the other — mirrors PR20 OD-3's conflict handling. Exact precedence (if any) is part of the source-schema-dependent case matrix deferred to §6. |
| Can PR21 import an orphan transaction, or must it block? | **Must block.** `equipment_id` is a NOT NULL FK on `borrow_transactions` (`transaction.py` column table, §10) — there is no schema path to represent a transaction with no resolvable equipment short of adding a nullable column and losing referential integrity, which this design does not propose. Orphan rows are validation findings, not imported rows. |

---

## 5. Equipment lifecycle and operational safety (summary; full detail §19, §33)

No lifecycle state is added. No `Equipment.status` mutation occurs during
import. `Equipment.status` remains exclusively derived from live
dispatch/receipt (§3, §19). Historical `CLOSED` transactions are always
safe to insert with respect to `idx_tx_one_active_borrow`, since the
partial index only constrains `status='open'` rows; historical `OPEN`
rows are the risk case and are gated by Owner Decision (§16, §34).

---

## 6. Source file contract — STOP: no real source artifact exists

A repository-wide search was performed for the actual legacy AppSheet
Receive History and Issue History workbook or any column-level schema
description of it:

- No `.xlsx`/`.xls`/`.csv` file matching Receive/Issue history exists
  anywhere in the repository.
- No `fixtures/`, `samples/`, or `docs/legacy/` directory exists.
- `docs/design/` contains only `PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`
  and `PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md` — no `PR21*` source-schema
  document exists prior to this one.
- `docs/audits/` (01–06) contains only prose references to "Receive
  History" / "Issue History" as roadmap category names, never a
  column-level schema.
- The only file resembling source content is
  `frontend/src/services/legacyImportFixtures.ts`, whose own header
  comment states explicitly: *"Every value below is representative/
  invented sample data for UI review. None of it comes from, or is
  derived from, real hospital data."* Its illustrative Thai field labels
  (e.g. `หอผู้ป่วย` "ward", `รหัส BCM` "BCM code", `วันที่รับคืน` "return
  date") exist purely to give mock UI finding-messages plausible context.
  **This is not a real column list and is not used as source-of-truth
  anywhere in this document.**

By contrast, PR20's own OD-1 (`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md:1731-1789`)
was resolved only once the Repository Owner supplied a real
`export_template.xlsx` — a concrete, evidence-backed 32-column header
list, verified against actual observed source records. **No equivalent
evidence exists for Receive History or Issue History as of this
document.**

**Per this task's own §5/§6/§41 instructions, this is a mandatory STOP on
field-level mapping.** This document does not guess column names, sheet
names, header rows, or cell-type behavior. §7 and §8 below describe only
the *conceptual* fields the Roadmap objective names (equipment identity,
timestamp, Ward, BME name, source reference), not a binding source
contract — they are explicitly marked provisional.

**What is required from the Owner before field-level mapping (the PR21
analogue of PR20's §7/§8/OD-1) can be written:**

1. The real AppSheet **Issue History** export (workbook or CSV), or an
   exact column-level description if the live export cannot be shared
   directly.
2. The real AppSheet **Receive History** export (workbook or CSV), same
   requirement.
3. For both: confirmation of exact sheet/tab name, header row location,
   and — ideally — a representative row-count sample large enough to
   observe real value distributions (PR20's OD-1 cited 4,729 real source
   records; equivalent evidence is needed here for status/Ward/BME-name
   value distributions).

This is recorded as **OD-PR21-0** (§34) — a blocking Owner Decision, not
a design gap this document can close by inference.

---

## 7. Issue History semantics (provisional — blocked on §6)

Based solely on the Roadmap objective's own wording
(`docs/audits/04-...md`, §1) and the existing `BorrowTransaction` schema
(§10), the conceptual fields a legacy ISSUE row is expected to carry are:

- equipment identity (see §4)
- issue timestamp (→ candidate for `borrowed_at`)
- receiving Ward (→ candidate for `ward_id`, via mapping, §12)
- legacy BME/operator name (→ provenance column, §11, not `borrower_user_id`)
- source transaction/reference ID, if present (→ traceability, §14)
- issue type / routine vs. on-demand, if present (→ candidate for
  `dispatch_type`/`routine_round`, both nullable at the DB level per
  `transaction.py`, so their absence does not block import)
- notes, if present (→ candidate for `notes`)
- historical status, if present (→ provenance-only column, mirroring
  `BorrowTransaction.legacy_status`, `transaction.py:239` — never read
  by live workflow, exactly the pattern already established for
  PR20-imported Equipment rows and pre-migration transactions)

No field is fabricated that the roadmap objective does not name. Routine
round / shift are **not** retroactively inferred from timestamps in this
design (§23) — if the source already states them, they are preserved as
stated; if not, they are left null, which the schema already tolerates.

This section is **not** a binding parse contract. It exists only so §10
(BorrowTransaction compatibility) and §24 (validation taxonomy) have a
consistent vocabulary to reference. The binding contract is deferred to
the PR21B implementation slice, after OD-PR21-0 is resolved.

---

## 8. Receive History semantics (provisional — blocked on §6)

Same treatment as §7. Conceptual fields:

- equipment identity (§4)
- receive timestamp (→ candidate for `returned_at`)
- legacy BME/operator name (→ provenance column, §11, not
  `received_by_user_id`)
- received condition/outcome, if present (→ candidate for
  `condition_on_return`, which already tolerates both the binary
  `ReceiptOutcome` values and free-text legacy strings —
  `transaction.py` `condition_on_return` column, unconstrained
  `String(30)`)
- source reference ID (§14)
- Ward/origin, if present
- notes, if present

**Whether receive records explicitly identify their matching issue
record is unknown** without the real source file (§6). §9 defines the
matching architecture options; the actual matching keys available are
determined by what the source file contains, not assumed here.

---

## 9. Issue ↔ Receive matching — architecture options

The current `BorrowTransaction` schema is a single-row model: one row
covers dispatch through receipt (`borrowed_at`...`returned_at` on the
same row, `status` transitions `OPEN → CLOSED` in place via
`crud/transaction.py:close()`). There is no separate "issue event" /
"receive event" pair of tables today.

Three ways PR21 could represent historical pairs, per this task's own
framing:

- **(A) Independent events** — import each legacy issue row and each
  legacy receive row as separate facts, with no attempt to pair them
  into a single `BorrowTransaction`. Simplest, avoids all matching risk,
  but does not produce a `returned_at`-populated closed transaction,
  which is what "history" conventionally means for this domain and what
  the existing transaction-history API/reports expect to query
  (`crud/transaction.py:294-446` `search()`, `event="dispatch"|"receipt"`
  filters already assume paired rows).
- **(B) Paired into historical BorrowTransaction rows** — deterministic
  matching keys (legacy transaction ID / source reference, equipment
  identifier, timestamps, Ward) join an issue row and a receive row into
  one inserted `CLOSED` `BorrowTransaction`, matching the shape live
  dispatch+receipt produces today. This is the option most compatible
  with the existing schema, existing search/reporting queries
  (`business_date_and_shift` on both `borrowed_at` and `returned_at`,
  §23), and the existing nullable-tolerant `TransactionOut` schema for
  the (rarer) unmatched case.
- **(C) A separate approved historical model** — a new table distinct
  from `borrow_transactions` for imported history. Not recommended: it
  would fragment "transaction history" into two query surfaces
  (live/legacy), directly contradicting §15's key invariant that users
  see unified transaction history, and would duplicate schema PR21
  otherwise gets for free from the existing table's nullable-tolerant
  design (§10).

**Recommendation: (B), paired into `BorrowTransaction` rows**, using the
existing single-row-per-transaction model as-is (imported directly at
`status=CLOSED` when a pair is found; see §16/§17 for the unpaired
cases). This recommendation is architectural, not a resolved Owner
Decision — the deterministic matching keys actually available (does the
source carry a shared legacy transaction ID across its issue and
receive sheets, or must pairing rely on equipment identifier + Ward +
temporal ordering?) are unknown until §6 is resolved. **Ambiguous
pairing must be a validation `ERROR`/reconciliation finding, never a
fuzzy/temporal heuristic match** — this rule holds regardless of which
keys turn out to be available.

---

## 10. BorrowTransaction compatibility analysis

Full column inventory of `borrow_transactions`
(`backend/app/models/transaction.py:121-349`), classified for historical
import:

| Column | Type / constraint | Classification |
|---|---|---|
| `transaction_no` | `String(30)` NOT NULL, **UNIQUE**, indexed; normally generated from a PostgreSQL sequence (`crud/transaction.py generate_transaction_no()`) | **Requires explicit historical sentinel policy** — see §20 (OD-PR21-5). A historical row cannot be left without a value (NOT NULL, UNIQUE), but generating a contemporary-format number for a decades-old event is misleading unless reporting/API expectations are reviewed. |
| `equipment_id` | UUID FK NOT NULL | Deterministically derivable, if source identifier resolves (§4); otherwise blocks (row not imported). |
| `quantity` | Integer NOT NULL, default 1 | Nullable/legacy-compatible — default suffices, not import-relevant. |
| `borrowed_at` | `UTCDateTime` NOT NULL, default now() | Deterministically derivable from source issue timestamp, **once normalized to aware UTC** (§22) — `reporting_time.business_date_and_shift()` raises on naive/non-UTC input (`reporting_time.py:96-101`), so timestamp normalization is mandatory, not optional. |
| `due_at` | naive datetime, nullable | Dead column (ADR-005) — leave NULL. Not import-relevant. |
| `returned_at` | `UTCDateTime`, nullable | Deterministically derivable for matched/CLOSED rows (§9); NULL is already the schema's correct representation for an unmatched/OPEN historical row (subject to §16's Owner Decision on whether such a row is ever inserted at all). |
| `borrower_user_id` | UUID FK, nullable | **Requires explicit historical sentinel** — must remain NULL for legacy rows; see §21 (never fabricate a User). |
| `borrower_name` | `String(150)`, nullable (relaxed in migration `0008`) | Deterministically derivable if the source's legacy BME/operator name is treated as free text here — but see §11: this column is display-oriented, not necessarily the intended provenance home. Needs a design choice between reusing `borrower_name` directly vs. a new dedicated legacy-provenance column (§32). |
| `ward_id` | UUID FK, nullable at DB level, app-required for new dispatch | Deterministically derivable **once Ward mapping resolves** (§12); nullable at the DB level means import is not blocked while mapping is pending, but an unmapped Ward should still be a validation finding, not a silent NULL. |
| `department_id` | UUID FK, nullable | Nullable/legacy-compatible — leave NULL unless source data justifies otherwise; not named in the Roadmap objective. |
| `phone_number` | `String(20)`, nullable | Nullable/legacy-compatible. |
| `pickup_location_id` / `dropoff_location_id` | UUID FK, nullable | Nullable/legacy-compatible — no Location-mapping requirement in the Roadmap objective. |
| `condition_on_return` | `String(30)`, unconstrained, nullable | Deterministically derivable if source states a receive condition (§8); tolerant of free-text legacy values by design already (mirrors `legacy_condition_on_return` handling). |
| `notes` | `Text`, nullable | Deterministically derivable if source has a notes field. |
| `received_by_user_id` | UUID FK, nullable | Same treatment as `borrower_user_id` — §21. |
| `status` | NOT NULL, default `OPEN`; exactly `OPEN`/`CLOSED` | Deterministically derivable from pairing outcome (§9): `CLOSED` for matched pairs, `OPEN` only if §16's Owner Decision explicitly permits historical-open import. |
| `dispatch_type` | nullable at DB level | Nullable/legacy-compatible — leave NULL unless source states it. |
| `routine_round` | nullable, CHECK-constrained to require `dispatch_type=ROUTINE_ROUND` | Nullable/legacy-compatible; never inferred (§23). |
| `legacy_status` | `String(20)`, nullable, provenance-only, never read by live workflow | **Direct precedent column** — establishes the "preserve exact original value, verbatim, provenance-only" pattern this design reuses in §32 for new legacy-provenance columns. |

**No existing column is a blocking gap on its own.** The two genuine open
questions are (a) whether `transaction_no` needs a historical-sentinel
policy or a schema addition (§20, OD-PR21-5), and (b) where legacy
BME-name provenance is best stored — reusing `borrower_name` (display
field, currently free-text-tolerant) vs. a new dedicated column that is
explicitly never conflated with a "real" borrower name (§11, §32).
**No current User row is ever fabricated to satisfy `borrower_user_id`/
`received_by_user_id` NOT NULL constraints — both are nullable, so no
fabrication is structurally necessary.**

---

## 11. Legacy BME name preservation policy

The Roadmap objective is explicit: *"preserve legacy BME names for later
user mapping."* This design must not:

- auto-create `User` accounts from legacy BME names — structurally
  impossible without fabricating credentials anyway, since
  `User.password_hash` is NOT NULL (`backend/app/models/user.py:72-99` —
  every `User` row requires a real login credential);
- auto-map a name to a current `User` by display-name similarity.

**No existing schema field is designed for this.** `User` has a
`legacy_role_name` column (`user.py`, nullable) that establishes the same
provenance-only pattern as `BorrowTransaction.legacy_status`, but nothing
on `User` or `BorrowTransaction` currently represents "an unmapped legacy
actor name attached to a specific historical transaction, in a specific
role (issued-by vs. received-by)."

**Proposed minimum schema addition (not created by this Design PR — see
§32):** a small number of new nullable, provenance-only columns on
`borrow_transactions` (or a separate 1:1/1:N provenance table, if two
independent legacy names — issuer and receiver — must be preserved on
one row) holding the raw legacy operator text verbatim, per role. These
columns are never read by any live workflow, mirroring `legacy_status`'s
treatment exactly. `borrower_user_id`/`received_by_user_id` remain NULL
until an explicit, auditable, Owner-approved later mapping step resolves
them — this design does not build that mapping step; it only ensures the
raw text survives untouched until one exists.

The later mapping procedure itself (who performs it, what evidence is
required, whether it is name-similarity-assisted-but-human-confirmed) is
**not** designed here — it is out of scope for PR21's own Version 1
boundary and belongs to whichever future item is chartered to build it.
This is recorded as a boundary note under OD-PR21-3 (§34), not resolved
as a full mapping-tool design.

---

## 12. Ward normalization / mapping design

Confirmed via search: **no alias/mapping table exists for Ward anywhere
in the codebase** (`backend/app/models/master_data.py:25-35` — `Ward` has
only `code`, `name`, `department_id`; no fuzzy/alias resolution mechanism
exists). PR20 hit the identical class of problem for
`department_owner_id`/location fields and explicitly deferred it (its
own §11, `PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md:2118`, cites *"Legacy BME
names and Ward values belong to transaction history and are handled by
PR21, not this Equipment Master import"* — i.e. PR20 explicitly punted
this exact problem to PR21).

**Recommended architecture** (mirrors this task's own suggested shape):

```
source raw Ward text
  -> normalized lookup key   (whitespace/case normalization; new utility,
                               same shape as identifiers.py's
                               normalize_bcm_code/normalize_item_no)
  -> explicit mapping table  (new: e.g. `legacy_ward_aliases` —
                               raw text or normalized key -> ward_id,
                               Owner/operator-maintained, not auto-populated
                               by fuzzy matching)
  -> current ward_id
```

- **Exact match** (after normalization) against `Ward.code`/`Ward.name`:
  resolves automatically.
- **Alias table hit:** resolves via the explicit mapping.
- **Unknown/ambiguous (no exact match, no alias entry):** validation
  finding (`WARD_NOT_MATCHED` or similar — §24), not a silently-created
  Ward, not a fuzzy-matched Ward. Reconciliation is a human/operator
  decision, consistent with §12's "Do NOT create a Ward silently" and
  "Do NOT map by fuzzy similarity automatically" instructions.
- **Blank Ward:** validation finding, not a default Ward.
- Original source Ward text is preserved for traceability regardless of
  match outcome (§14), so an unmatched value is never lost, only blocked
  from writing `ward_id` until reconciled.

**Ownership of the alias table's ongoing maintenance is an Owner
Decision** (OD-PR21-4, §34) — this document proposes the mechanism, not
who curates it operationally.

---

## 13. Duplicate transaction policy

The Roadmap objective requires PR21 to *"detect duplicate transaction
rows."* PR19's source-level checksum (`ImportSource.checksum`,
`import_session.py:115-150`) prevents re-registering an **identical
file**, but is explicitly insufficient for **row-level** transaction
idempotency (a corrected re-export of the same underlying data would have
a different file checksum but should not duplicate already-imported
transactions).

Distinct cases this design separates, per this task's own breakdown:

- **Duplicate ISSUE row within one source file** — same equipment +
  timestamp + (if available) source reference appearing twice in one
  workbook: validation finding at parse/validate time, analogous to
  PR20's in-workbook duplicate handling (its OD-3 case matrix).
- **Duplicate RECEIVE row within one source file** — same treatment.
- **Same source row imported twice** (identical file re-uploaded) —
  caught at the `ImportSource.checksum` level (already-registered source
  is rejected/reused per PR19A's existing contract) before row-level
  logic even runs.
- **Duplicate source reference across different files** — requires a
  stable **row identity** independent of which file it arrived in (see
  below).
- **Duplicate against already-imported legacy history** — requires
  checking newly-parsed rows against previously-*executed* (not just
  previously-uploaded) transactions, which is a database check, not a
  file check.
- **Semantically-identical rows with distinct source references** — not
  treated as duplicates; a distinct source reference is definitionally a
  distinct historical event unless the Owner states otherwise.

**Stable row/source identity, not timestamp-only comparison:** the
identity key should combine `ImportSource.id` (or checksum) +
`source_row_number` (or the source's own transaction/reference ID, if
present) — never timestamps alone, since two legitimate historical
events for the same equipment can share a timestamp granularity. The
exact key composition depends on what identifiers the real source
actually provides (§6).

---

## 14. Source traceability design

Every imported transaction/event must be traceable back to its exact
source row, per the Roadmap objective ("retain transaction source
references"). Minimum fields to persist per imported row, following
PR19A/PR20's existing provenance conventions:

- `ImportSession.id`
- `ImportSource.id`
- `ImportSource.checksum` (defense-in-depth copy, mirroring
  `EquipmentMasterDryRunPlan.source_checksum`,
  `import_session.py:247-339`)
- source sheet/tab identifier
- `source_row_number`
- source transaction/reference ID, if the legacy sheet provides one

This is provenance metadata, not a full raw-row dump — normalized
provenance is sufficient (per this task's own instruction not to store
unnecessary full raw rows when normalized fields suffice), consistent
with PR19A's redaction policy (§30) which purges raw source content but
retains structural/summary/audit fields indefinitely.

---

## 15. Historical vs. live transaction separation

**Key invariant:** legacy records are historical and immutable through
normal live operational commands. A live receipt must never accidentally
close an imported historical `CLOSED` transaction (it can't — `close()`
requires `status='open'`, `crud/transaction.py:144-220`, and a properly
imported historical row is inserted directly as `CLOSED`). A live
dispatch must not be blocked by a legacy historical record unless an
explicit current `OPEN` state was intentionally imported under an
approved policy (§16).

**Does the schema need a `source_kind` (`LIVE`/`LEGACY_IMPORT`) column or
equivalent?** Evaluated, not assumed necessary: the safety invariants
above (§3, §18, §19) do not actually *require* the application to
distinguish provenance at query time — a `CLOSED` transaction behaves
identically whether it came from live receipt or historical import, and
the existing `TransactionOut` schema is unified by design (§1's
"unified transaction history" requirement). The traceability fields in
§14 already carry provenance (an imported row always has a non-null
`ImportSession`/`ImportSource` link; a live row never does) — this is
sufficient to distinguish provenance **without** adding an operational
`source_kind` field, avoiding unnecessary schema surface. **Recommendation:
do not add a `source_kind` column** unless a concrete reporting/UI
requirement for filtering by provenance emerges (none has, as of this
document) — reuse the traceability link itself as the provenance signal.
This can be revisited if PR22's reconciliation work finds it needs one.

---

## 16. Unmatched historical ISSUE — Owner Decision required

**OD-PR21-1 candidate.** What happens when a legacy ISSUE row has no
matching RECEIVE row? Three interpretations were evaluated:

- Import as historical `OPEN` transaction.
- Import as a historical incomplete/unknown record (some form not
  competing for `idx_tx_one_active_borrow`).
- Block pending reconciliation (do not insert into `borrow_transactions`
  at all; surface as a validation/reconciliation finding).

**The danger, concretely:** `idx_tx_one_active_borrow` allows at most one
`OPEN` transaction per equipment (§3). If a historical unmatched issue is
imported as `OPEN`, and that equipment is later dispatched live before
PR22's reconciliation work resolves the historical gap, live dispatch
will fail with `EquipmentNotAvailableError` (`borrow_service.py:119-132`)
for a reason no operator caused today — a historical import silently
blocking today's workflow.

**Architectural recommendation: do not allow unresolved legacy history
to alter current operational eligibility.** Concretely: unmatched
historical issues are **not** imported as `OPEN` `BorrowTransaction`
rows by default. They are recorded as a validation/reconciliation
finding (visible in the dry-run plan and execution summary, traceable
per §14) but do not occupy the `idx_tx_one_active_borrow` slot. If the
Owner determines that representing some unmatched issues as genuinely
still-open (e.g. equipment legitimately never returned) is required,
that needs either a separate historical-state representation or an
explicit, reviewed exclusion from the live uniqueness constraint —
neither of which this document proposes without Owner direction, per
this task's own instruction to raise rather than assume it.

This is opened as **OD-PR21-1** and is also **Mandatory STOP condition
#3** (§41) — implementation of the Issue parser/execution slice cannot
proceed past this point until resolved.

---

## 17. Legacy RECEIVE without ISSUE — Owner Decision required

**OD-PR21-2 candidate.** A legacy RECEIVE row with no deterministic issue
match must not be paired via a synthetic/fabricated issue event merely to
satisfy the paired-row model (§9). Recommended safe default: treat as a
validation/reconciliation finding, not imported as a standalone
transaction with a fabricated `borrowed_at`. Escalated as an Owner
Decision since current requirements do not already specify this case,
per this task's own instruction. Also **Mandatory STOP condition #4**
(§41).

---

## 18. Transaction status — no new states

Confirmed via schema inspection (`transaction.py:13-39`,
`TransactionStatus`; migration `0007_transaction_lifecycle.py`, cited in
research as ADR-005): the live lifecycle is **exactly** `OPEN`/`CLOSED`.
This design does not introduce `LEGACY`, `UNKNOWN`, `UNMATCHED`, or
`IMPORTED` as new values on that enum. Provenance and incompleteness are
represented through the metadata mechanisms already described (§11
BME-name columns, §14 traceability links, §16/§17 validation findings for
unresolved pairs) — never by polluting the operational state machine.
This directly satisfies this task's own §18 instruction.

---

## 19. Equipment lifecycle safety

Restated for completeness (see §3 for the evidence): historical import
never changes `Equipment.status`, never derives it from old transactions,
and the backend remains the sole source of truth for current lifecycle
state. No additional lifecycle states are introduced. This is not merely
a policy statement — it is enforced by the architectural choice in §3 to
never call `equipment_crud.change_status_for_dispatch_receipt` (or any
lifecycle-mutating path) from the PR21 adapter's `execute()`.

---

## 20. Transaction number policy — Owner Decision required

**OD-PR21-5 candidate.** `transaction_no` is `String(30)` NOT NULL,
UNIQUE, normally sequence-generated (`crud/transaction.py
generate_transaction_no()`). Historical transactions may not have a
current-format number. Three options, per this task's framing:

- Preserve the legacy transaction number/reference **separately** (§14
  traceability already captures a source reference ID if present) and
  populate `transaction_no` with a distinguishable historical-format
  value (e.g. a clearly-prefixed sequence reserved for imports, avoiding
  collision with the live sequence).
- If the legacy source's own number is safe (globally unique, stable,
  non-colliding with the live sequence's format), use it directly as
  `transaction_no`.
- Generate a new current-format `transaction_no` for imported rows —
  **not recommended without reviewing reporting/API expectations first**,
  since a contemporary-looking transaction number on a decades-old event
  is misleading (this task's own instruction).

This document does not resolve which option, because the answer depends
on (a) whether the real source provides a safe, stable reference (§6) and
(b) confirming no reporting/API code assumes `transaction_no` format
implies recency. **Source reference is preserved regardless of which
option is chosen** (§14 is unconditional). Also **Mandatory STOP
condition #7** (§41), since it touches a NOT NULL/UNIQUE constraint.

---

## 21. User foreign keys

`borrower_user_id`/`received_by_user_id` are both nullable FKs (§10).
This design's rule, restated precisely: **no fake `User` rows, no
assigning Administrator as the historical actor, no using the importing
Administrator's identity as though they performed the original
historical transaction.**

**Import actor vs. historical operator are two distinct, never-conflated
concepts:**

- **Import actor** — the current authenticated Administrator who ran
  PR21's import. Recorded exactly as PR19A/PR20 already record it: via
  `record_audit_event()`'s `actor_user_id`
  (`backend/app/core/audit.py:157-189`), sourced from
  `AdapterInvocationContext.actor_user_id`
  (`import_adapter_context.py:76`). This is `AuditLog.user_id` — the
  **only** actor field `AuditLog` has (`backend/app/models/audit.py:18`).
  It answers "who ran the import," never "who historically dispatched
  or received the equipment."
- **Historical operator** — the legacy BME/operator name from the source
  row. This is **business data on the transaction itself**, not an audit
  concern, and is stored per §11's provenance columns, never conflated
  with `AuditLog.user_id`.

If future BME-name-to-User mapping (§11) later resolves a legacy name to
a real `User`, `borrower_user_id`/`received_by_user_id` can be populated
then, through that separate, explicit, auditable process — not by this
import.

---

## 22. Timestamp / timezone policy

`reporting_time.business_date_and_shift()` **requires an aware UTC
datetime** and raises `ValueError` on a naive or non-UTC-offset input
(`backend/app/core/reporting_time.py:96-101`). Since `borrowed_at`/
`returned_at` are both `UTCDateTime`-typed and feed this function at read
time (§23), **timestamp normalization to aware UTC is mandatory before
any row is written** — there is no leniency to rely on.

Open questions this document cannot resolve without the source file
(§6): source timezone (Asia/Bangkok hospital-local is the working
assumption, consistent with the existing Day/Night shift boundaries
being defined in that timezone per Owner Decision #1 in
`docs/DECISION_LOG.md`, but this must be confirmed against the actual
export, not assumed for parsing purposes); whether Excel cells are
timezone-naive (typically yes, for AppSheet/Excel exports — must be
confirmed); ambiguous date formats; seconds precision; date-only values
(no time component); DST relevance (Thailand does not observe DST, so
this is likely moot, but stated for completeness); malformed timestamps
(validation `ERROR`, never heuristically repaired).

**Do not interpret ambiguous dates heuristically** — malformed or
ambiguous timestamps are validation findings, consistent with every
other "do not guess" rule in this document.

---

## 23. Reporting metadata policy

`business_date`/`shift` are **computed at read time**, not stored —
`BorrowTransaction.dispatch_business_date`/`dispatch_shift`/
`receipt_business_date`/`receipt_shift` are computed properties
(`transaction.py:251-349`) calling `business_date_and_shift()` on the
stored `borrowed_at`/`returned_at`. **This means PR21 needs no separate
backfill step for reporting metadata** — once a historical row's
timestamps are correctly normalized to aware UTC (§22) and written to
`borrowed_at`/`returned_at`, business_date/shift derive automatically and
correctly, using the exact same derivation live transactions use. Source
timestamps are never overwritten to fit a desired reporting date/shift
(this task's own instruction) — the derivation is one-directional, from
true timestamp to reporting metadata, never the reverse.

An unreceived (historical-OPEN, if ever approved per §16) row's
`returned_at IS NULL` already correctly yields NULL
`receipt_business_date`/`receipt_shift`
(`reporting_time.py:204-214` SQL twin's NULL-propagation), so no special
casing is needed for that scenario either.

---

## 24. Validation finding taxonomy

Following PR20's `<DATASET>_<CONDITION>` stable-error-code convention
(`equipment_master.py:177-194`), PR21 should define its own codes rather
than reuse `EQUIPMENT_MASTER_*` codes. Proposed taxonomy (final list
depends on §6 resolution; this is the conceptual set, not yet a frozen
`ERROR_CODES.md` entry):

| Condition | Severity |
|---|---|
| Missing equipment identifier | ERROR |
| Equipment not found | ERROR |
| Conflicting identifiers (BCM vs. Item Number) | ERROR |
| Invalid/malformed timestamp | ERROR |
| Missing Ward | ERROR |
| Unmapped Ward (no exact match, no alias) | ERROR (blocks `ward_id` write; row may still be a candidate for import with Ward left unresolved, pending §12's Owner-approved policy on whether that blocks the whole row or only the field) |
| Ambiguous Ward (matches more than one alias/current Ward) | ERROR |
| Duplicate source row (within file) | ERROR |
| Duplicate source reference (across files/already-imported) | ERROR |
| Unmatched RECEIVE (no issue pair) | ERROR — reconciliation item, per §17 |
| Unmatched ISSUE (no receive pair) | ERROR — reconciliation item, per §16, pending OD-PR21-1 |
| Invalid/malformed source reference | ERROR |
| Unknown BME name (mapping intentionally deferred/optional) | WARNING — this is expected and non-blocking, since BME mapping is explicitly a *later* step (§11), not a precondition for import |
| Malformed source structure (wrong sheet, missing headers, etc.) | ERROR |

**Exactly two severities — `ERROR`/`WARNING`, no third tier**, matching
PR19A's own taxonomy (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`
§13, line 735) and this task's own instruction not to invent a third.
Warnings remain non-blocking per PR19's existing contract.

---

## 25. Dry-run contract

PR19/PR20's persisted `DryRunPlan` architecture is reused for its
**pattern** (immutable header + rows, `active`/`superseded`/`consumed`/
`failed` lifecycle, explicit confirm gate before execution) — but the
concrete `EquipmentMasterDryRunPlan`/`EquipmentMasterDryRunPlanRow`
tables (`import_session.py:247-377`) are not directly reusable as-is.
That model is upsert-oriented: `action IN ('CREATE','UPDATE','SKIP')`,
`target_equipment_id`, `expected_equipment_version` (an optimistic-
concurrency column `BorrowTransaction` does not have — it is not
versioned the way `Equipment` is). PR21 is an **insert-oriented** import
(historical transactions do not already exist to be updated against), so
this design proposes new, PR21-owned tables mirroring the shape:

- `legacy_transaction_import_dry_run_plans` (header — same fields as
  `EquipmentMasterDryRunPlan` minus anything Equipment-specific:
  `import_session_id`, `import_source_id`, `source_checksum`,
  `accepted_validation_job_id`, `dry_run_job_id`, `ruleset_version`,
  `status`, `confirmed_at`/`confirmed_by_user_id`, summary counters)
- `legacy_transaction_import_dry_run_plan_rows` (row — `source_row_number`,
  `action IN ('IMPORT_OPEN', 'IMPORT_CLOSED', 'SKIP')` — `IMPORT_OPEN`
  only meaningful if OD-PR21-1 ultimately approves it — `matched_identity_fields`,
  `normalized_values`, `warnings`; no `expected_*_version` column, since
  there is no pre-existing row being updated)

This is a genuinely new schema addition (§32), not a migration performed
by this Design PR. The dry-run must show historical import effects
(issue rows, receive rows, paired transactions, duplicate rows, unmapped
Wards, unresolved equipment, preserved legacy BME names, blocked rows —
using only fields this design has actually justified above) without
writing any `borrow_transactions` row — exactly PR19's existing
`READ ONLY` transaction enforcement (`PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md`
§16) already guarantees for any adapter that participates correctly in
the framework.

---

## 26. Execution contract

Execution reuses PR19's claim, idempotency, lease, heartbeat, fencing,
recovery, audit, and retention mechanisms **unmodified** — this is not
optional; PR19A's own design doc states no new lease/heartbeat/fencing/
recovery code should be added per adapter
(`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §25, restated
verbatim in `import_execution_service.py:1-12` and
`import_lease.py:1-14`). PR21's adapter (`import_adapters/legacy_transaction_history.py`
or similarly named, following `equipment_master.py`'s precedent) must
implement the same `on_execution_success`/`on_execution_failure`/
`on_execution_recovery` hook triple that PR20E's design maintains the
**Job → Session → Plan/sub-resource** lock order for
(`equipment_master.py:1496-1536`), applied to PR21's own dry-run-plan
sub-resource (§25).

Historical transaction inserts are atomic per the final approved
execution contract (single transaction per plan-row batch, or per the
granularity PR20E's own precedent establishes — not re-litigated here).
Execution never mutates `Equipment` (§3, §19) and never invokes live
dispatch/receipt transitions (§3).

---

## 27. Re-import / idempotency

Per this task's framing, the following must not silently duplicate
history:

- Same source file re-uploaded — caught at `ImportSource.checksum`
  (existing PR19A contract).
- Same source row appears in a corrected later file — requires the
  row-level stable identity from §13 (source reference / row-number-based
  key, not file checksum) to detect this is "the same historical event,"
  distinct from "a genuinely new row."
- Same transaction source reference imported twice — blocked as a
  duplicate finding (§13, §24).
- Mapping changes after an earlier dry-run (Ward mapping added, BME
  mapping added later) — per PR20's own precedent, a dry-run plan is
  immutable once persisted (`status='active'` until superseded/consumed/
  failed); a changed mapping invalidates the prior plan (superseded) and
  requires a fresh dry-run, not an in-place mutation of the old plan.
  This mirrors PR20D's persisted-plan immutability contract exactly.

Reconciliation behavior stays traceable throughout (§14) — nothing about
idempotency handling discards the ability to trace a row back to its
source.

---

## 28. Frontend

PR19B already previewed Receive History and Issue History as categories
in the Legacy Import UI (mock/placeholder data). PR21's own frontend
slice (proposed as PR21E, §35) reuses that existing architecture and
replaces the mocks with real PR21 APIs — it does not redesign the
frontend. Preserved: Thai-first, mobile-first, minimal typing, large
touch targets, Administrator-controlled import workflow — consistent
with every prior import slice's frontend requirements. No frontend file
is touched by this Design PR (§39 scope guard).

---

## 29. Security / privacy assessment

The Roadmap objective does not mention patient-identifying data, and
none of PR21's conceptual fields (§7, §8) are patient-related — they are
staff/operational (BME name, Ward, equipment, timestamps). **However,
this cannot be fully assessed without the real source file (§6)** — a
free-text `notes` field, if present in the actual export, could
plausibly contain patient names, HN/MRN, phone numbers, or clinical
free-text incidentally entered by hospital staff, even though it is not
the field's intended purpose.

**Explicit policy, pending source-file review:** patient-identifying
data is out of scope and must never be silently imported. If the real
source is found to contain any such data (in `notes` or elsewhere), this
design's `notes` field must not be imported as-is — a reject/redact/
ignore policy requires explicit Owner approval before any free-text
field reaches the database, let alone an API response. This is recorded
as **OD-PR21-6** (§34) and **Mandatory STOP condition #10** (§41) —
contingent on §6's resolution, since the actual risk cannot be evaluated
against a file that does not exist in this repository.

No raw source rows are exposed broadly through APIs (§14 — traceability
is normalized-provenance, not raw-row storage, consistent with PR19A's
existing redaction policy).

---

## 30. Retention design

Two distinct retention concerns, kept explicitly separate per this
task's instruction:

- **Temporary import artifact retention** — reuses PR19's existing
  180-day post-terminal retention policy unmodified
  (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §18: 180-day
  post-terminal retention, redact-in-place for source/finding content,
  structural/summary/audit fields retained indefinitely,
  `IMPORT_RETENTION_DAYS` deployment-configurable, no V1 Administrator
  UI, no legal/manual hold). This governs `ImportSession`/`ImportSource`/
  `ImportRowError`/PR21's own dry-run-plan tables (§25) — the *import
  process's* artifacts.
- **Persisted historical transaction/provenance retention** — once a
  legacy row is successfully executed into `borrow_transactions` (plus
  its §11/§14 provenance columns), it becomes **operational historical
  data**, exactly like any live-created transaction. It is not subject
  to the 180-day import-artifact purge — nothing in this design proposes
  ever deleting or redacting an imported `BorrowTransaction` row on a
  timer. This distinction directly satisfies this task's instruction
  that imported transaction history "must not disappear merely because
  import artifacts reach retention age."

---

## 31. Audit design

Restated precisely from §21: audit records the **import actor** (current
authenticated Administrator, via `record_audit_event()`'s
`actor_user_id` → `AuditLog.user_id`) — never the historical operator.
The **historical operator** (legacy BME/operator name) is business data
on the transaction (§11), never written into `AuditLog`. Batch/session/
source and execution outcome are recorded exactly as PR19A/PR20 already
do, via the existing `AUDIT_ACTION_IMPORT`/`AUDIT_ACTION_IMPORT_RECOVERY`/
`AUDIT_ACTION_IMPORT_FENCE_LOST` constants
(`backend/app/core/audit.py:48-80`), `entity_type="import_session"`. No
new audit-action constant is proposed unless implementation reveals a
genuine gap — none is evident from this design.

---

## 32. Schema assessment (gap analysis)

Explicit gap analysis, one row per candidate addition, each justified
against why existing schema is insufficient. **No migration is created
by this Design PR** — this is a proposal for the implementation slice
that eventually needs it (PR21A, §35).

| Proposed addition | Why existing schema is insufficient |
|---|---|
| Legacy operator/BME-name provenance column(s) on `borrow_transactions` (issuer + receiver, both nullable, provenance-only) | No existing column represents "raw legacy actor name, per role, not yet mapped to a User" — `borrower_name` is a display field with different semantics (§11); `legacy_status` establishes the pattern but doesn't cover actor names. |
| Source provenance columns/table (`import_session_id`, `import_source_id`, `source_row_number`, source reference) linked from `borrow_transactions` | No existing link from a transaction row back to its import provenance exists at all — `borrow_transactions` has no import-related columns today. |
| `legacy_ward_aliases` mapping table (§12) | Confirmed absent from `master_data.py` — no Ward alias/fuzzy-matching mechanism exists anywhere in the codebase today. |
| PR21-owned dry-run plan header/row tables (§25) | `EquipmentMasterDryRunPlan`/`Row` are upsert-oriented and carry Equipment-specific columns (`target_equipment_id`, `expected_equipment_version`) that don't apply to an insert-oriented transaction import. |
| Historical-sentinel handling for `transaction_no` (§20) — exact mechanism pending OD-PR21-5 | `transaction_no` is NOT NULL/UNIQUE with no existing historical-import carve-out; whether this needs a new column (e.g. a distinct `legacy_reference_no`, already partially covered by the source-reference provenance column above) or just a reserved numbering scheme depends on OD-PR21-5's resolution. |

Every proposed addition is additive (new nullable columns / new tables);
none of them alter or constrain any existing live-workflow column,
consistent with this task's "prefer additive changes, avoid breaking
current live workflows" instruction.

---

## 33. Concurrency / live safety

Historical import may run while the current Equipment Pool is in active
use. Design points ensuring this is safe:

- **Imported historical `CLOSED` records never interfere with current
  `OPEN` transactions** — `idx_tx_one_active_borrow` only constrains
  `status='open'` rows (`transaction.py:140-148`); bulk-inserting
  `CLOSED` rows never competes for that slot, regardless of how many are
  inserted for the same equipment.
- **Unique constraints do not accidentally block live dispatch** —
  `transaction_no`'s uniqueness is protected by using a distinct
  historical numbering scheme/sequence (§20), never colliding with the
  live sequence's format/range.
- **Historical transaction numbers/source refs do not collide** — the
  same stable row-identity key from §13 prevents this by construction.
- **Re-import cannot duplicate data** — §27's idempotency design.
- **PR19 execution single-winner remains intact** — PR21's `execute()`
  reuses the existing single-winner execution claim
  (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §17) unmodified;
  no parallel execution-safety mechanism is introduced (§26).

**The one case that cannot be guaranteed safe by architecture alone is
historical `OPEN` import** (§16) — if ever approved, it directly competes
with live dispatch for `idx_tx_one_active_borrow` on the same equipment.
This design does not attempt to weaken that constraint to accommodate
it; if the Owner approves historical-OPEN import, the safe path is
either (a) restricting it to equipment that is not concurrently live-
dispatchable during the import window (a maintenance-window requirement,
stated explicitly per this task's instruction, rather than silently
weakening constraints), or (b) the Owner deciding historical-OPEN import
is simply not needed (the recommended default, §16). Which applies is
part of OD-PR21-1's resolution, not decided here.

---

## 34. Required Owner Decisions

Opened only where repository/source evidence cannot answer the business
question — not opened merely to make implementation easier, and not
resolved by guessing, per this task's explicit instruction.

- **OD-PR21-0 — Real source artifact required (blocking, §6).** The
  actual AppSheet Issue History and Receive History exports (or an exact
  column-level description) must be supplied before any field-level
  mapping, parser, or validation-rule implementation slice can begin.
  Every other Owner Decision below that concerns field-level specifics
  is provisional until this resolves.
- **OD-PR21-1 — Unmatched ISSUE rows (§16).** Import as historical
  `OPEN`, import as a separate incomplete-record representation, or
  block pending reconciliation. Architectural recommendation: do not
  allow unresolved legacy history to alter current operational
  eligibility (i.e. block/reconcile, not `OPEN`-import, by default).
- **OD-PR21-2 — Unmatched RECEIVE rows (§17).** Recommended default:
  validation/reconciliation finding, never a fabricated paired issue.
- **OD-PR21-3 — Legacy BME-name mapping policy boundary (§11).** This
  design preserves raw names safely; it does not design the later
  mapping procedure itself — Owner confirmation needed on whether that
  procedure is in a future PR21 sub-slice, PR22, or elsewhere.
- **OD-PR21-4 — Ward alias/mapping table ownership (§12).** This design
  proposes the mechanism (explicit alias table, no fuzzy matching); Owner
  Decision needed on who curates it operationally and whether any
  existing Ward data (from PR20 or elsewhere) should seed it.
- **OD-PR21-5 — Historical transaction-number policy (§20).** Preserve
  legacy number as-is (if safe), reserve a distinct historical-format
  sequence, or another approach — contingent on what the source
  actually provides (OD-PR21-0) and a review of reporting/API
  expectations.
- **OD-PR21-6 — Patient/clinical free-text handling (§29).** Contingent
  entirely on what the real source contains — cannot be resolved without
  OD-PR21-0.

---

## 35. Proposed implementation slices

Starting hypothesis only, per this task's instruction — not authoritative
until dependency analysis against the real source file is complete:

- **PR21A — Historical Transaction Schema / Provenance Foundation.**
  New nullable/provenance columns and tables from §32 (BME-name
  provenance, source-provenance link, `legacy_ward_aliases`, PR21-owned
  dry-run plan tables). Migration-bearing. **Blocked on:** OD-PR21-3
  (boundary confirmation), OD-PR21-4 (alias table shape), OD-PR21-5
  (transaction_no approach) — or can proceed with the safe subset that
  doesn't depend on their exact resolution (e.g. the provenance/
  traceability columns), with the remainder split out if needed once
  those resolve.
- **PR21B — Issue History Parser + Validation.** **Blocked on:**
  OD-PR21-0 (source file), §4's finalized identifier case matrix,
  §24's frozen error-code list.
- **PR21C — Receive History Parser + Matching/Validation.** **Blocked
  on:** OD-PR21-0, OD-PR21-1, OD-PR21-2, §9's finalized matching keys.
- **PR21D — Persisted Dry-run + Historical Transaction Execution.**
  **Blocked on:** PR21A–C, §26's execution-contract detail.
- **PR21E — Frontend Real Integration.** **Blocked on:** PR21D (reuses
  PR19B's existing Receive/Issue History UI categories, §28).
- **PR21F — Governance Sync.** After all approved slices merge, per the
  established PR19/PR20 pattern (ENGINEERING_WORKFLOW.md §14) — not
  performed by this Design PR (§38).

**Readiness table:**

| Slice | Owner-Decision-blocked? | Depends on | Ready now? |
|---|---|---|---|
| PR21A | Partially (OD-PR21-3/4/5 for full scope; provenance/traceability subset is not) | This design | Partially — safe subset only |
| PR21B | Yes — OD-PR21-0 | PR21A (provenance columns) | No |
| PR21C | Yes — OD-PR21-0, OD-PR21-1, OD-PR21-2 | PR21A, PR21B (shared parser infra, if any) | No |
| PR21D | Yes — transitively, via PR21A–C | PR21A, PR21B, PR21C | No |
| PR21E | No new Owner Decisions of its own | PR21D | No |
| PR21F | No | All PR21A–E merged | No |

---

## 36. Test strategy

Following this task's own coverage list, mapped to this design's
architecture:

- **Source contract:** wrong sheet, missing headers, duplicate headers,
  malformed dates, formulas/macros (reuse PR20's OOXML macro-rejection
  precedent, `equipment_master.py` parse-time handling), oversized file
  — all deferred to PR21B/C implementation, contract finalized after §6.
- **Equipment:** valid identity, not found, identifier conflict (§4).
- **Ward:** exact mapping, alias, unknown, ambiguous, blank (§12).
- **BME:** preserved raw name, later-mapping-readiness, duplicate
  display names across rows, no fake-user creation (§11, §21).
- **Pairing:** deterministic issue/receive pair, ambiguous pair (blocked
  as ERROR, never fuzzy-matched), missing issue, missing receive,
  duplicate source reference (§9, §16, §17).
- **Idempotency:** same file replay, same row replay, corrected later
  source (§27).
- **Live safety:** current `Equipment.status` unchanged after import;
  current `OPEN` transaction unaffected; historical import does not
  block live dispatch (regression tests directly exercising
  `idx_tx_one_active_borrow` with concurrent live-dispatch attempts, §3,
  §33).
- **PostgreSQL:** unique source-row identity enforcement, concurrency
  (import running alongside live traffic), rollback, atomic execution
  (§26, §33) — two-connection tests following PR20D/E's own established
  pattern for this repository.
- **Reporting:** timestamps normalize correctly to aware UTC (§22);
  business_date/shift derive correctly for both dispatch and receipt
  sides of an imported pair; unified history ordering alongside live
  transactions (§15, §23).

---

## 37. Design deliverable

This document is that deliverable — self-contained, standing on its own
without depending on GitHub review comments for its normative contract,
per this task's explicit instruction. No section defers to "unchanged
from prior revision" or "see previous review," since this is the first
revision.

---

## 38. Governance update (this Design PR's own scope)

Per `docs/ENGINEERING_WORKFLOW.md` §6 (Design PR Policy) and §7 (Owner
Decision Policy), and the direct precedent of PR19A's and PR20's own
design PRs (neither touched `ROADMAP.md`/`ROADMAP_STATUS.md`/
`knowledge/*` at design time — confirmed via research; that six-file
sweep is explicitly reserved for the post-implementation governance sync
under ENGINEERING_WORKFLOW.md §14, performed only "after all approved
implementation slices for a Roadmap item are merged"), this Design PR's
governance-update scope is:

- This design document itself.
- A new `docs/DECISION_LOG.md` entry recording that PR21 design has
  started and which Owner Decisions (§34) were opened — **not** recording
  any of them as resolved, since none are.

**Not performed by this PR:** any change to `docs/ROADMAP.md`,
`docs/ROADMAP_STATUS.md`, `knowledge/CONTEXT.md`,
`knowledge/PROJECT_MEMORY.md`, `knowledge/CHANGE_HISTORY.md`, or
`docs/audits/04-consolidated-implementation-plan.md`. PR21 is not marked
implemented anywhere. **PR #97's accepted non-blocking P2 follow-up
(precise wording of the PR20 design-edit-scope description in
`docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md` and
`docs/DECISION_LOG.md`) is explicitly not touched or closed by this PR** —
this document edits neither of those files' PR20-related content, and
closing that follow-up would require its own explicit, reviewed content
correction, not a side effect of starting PR21.

---

## 39. Scope guard for this PR

**Touched by this PR:** `docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`
(new file), `docs/DECISION_LOG.md` (one new entry).

**Not touched:** `backend/**`, `frontend/**`, `alembic/**`, `tests/**`,
`.github/**`, Docker/runtime configuration, `docs/ROADMAP.md`,
`docs/ROADMAP_STATUS.md`, `knowledge/**`,
`docs/audits/04-consolidated-implementation-plan.md`. No PR21 runtime
implementation is performed.

---

## 40. Mandatory STOP conditions encountered

Evaluated against this task's own §41 list:

1. **Actual Receive/Issue source schema is unavailable — ENCOUNTERED.**
   §6. Blocks field-level mapping (§7, §8) and downstream parser/
   validation slices (PR21B/C).
2. Issue↔receive matching cannot be deterministic — **not yet
   evaluable** (depends on #1); architecture proposed (§9), exact keys
   pending.
3. **Unmatched historical issue policy is unresolved — ENCOUNTERED.**
   §16, OD-PR21-1.
4. **Unmatched receive policy is unresolved — ENCOUNTERED.** §17,
   OD-PR21-2.
5. BME actor provenance representation — **addressed by this design**
   (§11, §32 proposes the schema); the later mapping *procedure* remains
   a boundary note under OD-PR21-3, not a full stop.
6. Ward mapping policy — **architecture addressed by this design**
   (§12); operational ownership remains OD-PR21-4, not a full stop on
   the architecture itself.
7. **Current BorrowTransaction NOT NULL/UNIQUE constraints require a
   policy decision — ENCOUNTERED** for `transaction_no` specifically
   (§20, OD-PR21-5). No constraint requires fabrication of a value with
   no legitimate provenance (§10 confirms no other NOT NULL column is at
   risk).
8. Historical import changing current Equipment.status — **not
   encountered**; this design's architecture (§3, §19) prevents it by
   construction.
9. Historical imported rows interfering with live OPEN uniqueness — the
   underlying risk exists only for the OD-PR21-1 unmatched-issue case;
   see §16/§33 — treated as part of that same STOP, not a separate one.
10. **Patient/HN/MRN data present without an approved handling policy —
    CONTINGENT, cannot be evaluated without #1.** §29, OD-PR21-6.
11. A new transaction lifecycle state appears necessary — **not
    encountered**; §18 confirms no new state is proposed.
12. PR21 requiring a change to PR19/PR20 safety semantics — **not
    encountered**; every mechanism reused (§25, §26, §30) is reused
    unmodified.

**Net effect:** this Design PR is complete as an architecture document,
but downstream implementation (PR21A's full scope, and all of PR21B/C/D)
cannot begin until OD-PR21-0 (source file) and OD-PR21-1/2 (unmatched-row
policy) are resolved, consistent with this task's explicit instruction
not to solve STOP conditions by assumption.

---

*(End of design document. See the PR description for the required final
report covering validation, diff statistics, and confirmation items.)*
