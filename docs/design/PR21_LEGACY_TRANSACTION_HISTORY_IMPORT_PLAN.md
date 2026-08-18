# Roadmap PR21 — Legacy Receive and Issue History Import: Design Specification

**Status:** Design only. Not implemented (except PR21-Foundation, §46,
genuinely topology-independent generic plumbing, merged as GitHub PR
#100, squash SHA `7b99e5866df4b71ffa1aa09d265baa2bc7033c33`). **Owner
Decision Closure Round 1** (GitHub PR #101, squash SHA
`e22139346c7bdff1edf841022dd4b7dbebbb3573`) resolved OD-PR21-1,
OD-PR21-2, OD-PR21-3, OD-PR21-4, and OD-PR21-6; partially resolved
OD-PR21-5; and deliberately left OD-PR21-0's stable-event-identity and
Issue↔Receive-pairing sub-components open, per the Owner's own
instruction not to decide `ลำดับ`'s re-export durability unilaterally.

**Owner Decision Closure Round 2 (this round)** resolves both of those
remaining sub-components: **event-first architecture is ADOPTED**
(§11.2) — PR21 imports each accepted legacy source row as an
independent, immutable `LegacyEquipmentEvent` (§8.1); pairing an Issue
event to a Receive event is never required for import and is deferred
to PR22-or-later reconciliation, resolved only where deterministic
source evidence proves it. **Stable event identity is RESOLVED FOR
PR21 V1 only** (§24.2) via one immutable `LegacyMigrationAuthority`
design concept, bound to a frozen, Owner-approved workbook snapshot's
checksum — never claimed as a globally durable AppSheet key; the
database-enforced identity tuple is `(migration_authority_id,
dataset_type, legacy_source_row_key)`, not `ลำดับ` alone. **OD-PR21-5 is
now RESOLVED for V1's actual scope** (§20) — `LegacyEquipmentEvent` has
no `transaction_no` column at all. **OD-PR21-1 and OD-PR21-2 are
AMENDED, not reversed** (§16, §17) — the original safety principle
(never fabricate, never risk a live `OPEN` collision) is unchanged and,
under event-first, structurally strengthened; only the specific
"unmatched = `ERROR`" mechanism is narrowed, since pairing is no longer
attempted at import time. **No source-dependent PR21 implementation
slice has been implemented by this round** — PR21A becomes *ready to
start once this Design PR merges* (§54); PR21B/C's full scope remains
**NOT FULLY READY** (an explicitly bounded canonical-sheet-only
sub-slice of each may start; the SDC-sheet field-level-contract
ambiguity, §6.1, remains an open Owner Decision and is not resolved by
this round). This document remains design/decision-only: no schema,
migration, backend, frontend, or test file is touched (§51).

**PR #102 fix round.** Independent review of this round's first draft
found one substantive identity-tuple gap and two readiness-wording
contradictions; both are corrected throughout this revision (§24.2,
§8.1, §43, §45, §46, §47, §52, §54). The fix round does not reopen any
Owner Decision — it corrects this document's own not-yet-merged
wording to match the decisions actually made.

**Baseline:** `e22139346c7bdff1edf841022dd4b7dbebbb3573` (GitHub PR
#101, Owner Decision Closure Round 1 squash merge, on
`claude/medical-equipment-pool-0c7fz0`). Prior baselines:
`7b99e5866df4b71ffa1aa09d265baa2bc7033c33` (GitHub PR #100,
PR21-Foundation squash merge); `5d4b1d3a7f79e9b9e6d281a1eea1f7b5bc862217`
(GitHub PR #98, PR21 Design Phase 1 squash merge).

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
  to verify H3/H4/M1's claims — see §24, §29, §38)
- `backend/app/schemas/import_session.py` (Fix Round 2: read specifically
  to verify PR98-H4R's exact wire field names — `DryRunPlanOut`,
  `DryRunPlanRowOut`, `DryRunPlanSummaryOut`, `DryRunPlanConfirmOut` —
  see §29-§36)
- `backend/app/api/v1/transactions.py`, `backend/app/schemas/transaction.py`
- Repository-wide search for any real legacy Receive/Issue workbook, CSV,
  fixture, or column-level schema description (see §6).
- **Owner Decision Closure Round 1 (this round), additionally:**
  `docs/evidence/pr21/equipment-pool-workbook-manifest.json`/`.md`
  (re-read, to re-verify the exact row/reference/`ME.Code` counts cited
  in this round's own instructions against the committed evidence,
  §10.1); `backend/app/models/transaction.py` (re-verified §12's
  `BorrowTransaction` column table is still accurate — unchanged);
  `backend/app/models/master_data.py` (`Ward`, re-verified §14);
  `backend/app/models/user.py` (`User.password_hash` NOT NULL,
  re-verified §13); the merged PR21-Foundation runtime
  (`backend/app/services/import_plan_provider.py`,
  `backend/app/services/import_plan_providers/equipment_master.py`,
  `backend/app/crud/import_retention.py`, GitHub PR #100) — confirmed
  complete and unaffected by this round's decisions.

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
reuses.

**Source Evidence Update.** Direct inspection (§6.1, §6.2) confirms
**`ME.Code`** is the identifying field present on every canonical
Issue/Receive line-item row, alongside a `SCAN CODE`-family URL column
(`http://nsmart.nhealth-asia.com/mtdqrcode/asset_mast_show.php?code=...`)
and a `Barcode ส่ง/รับเครื่อง` column (a `*BCM-formatted*` wrapped
string). `ME.Code` values observed (e.g. `BCM01078`, `BCM03171`) match
the `Equipment BCM`-family identifier already used by
`ข้อมูลเครื่องEquipment Pool` (Equipment Master, §6.1) and by PR20's own
BCM concept — the closest and most natural mapping is `ME.Code` →
PR20's BCM identity path via `normalize_bcm_code()`. The full case
matrix (whether `SCAN CODE`/`Barcode` ever disagree with `ME.Code`,
exact conflict precedence) is not exhaustively verified by this
design-level inspection and remains PR21B/C implementation-grade work
(§6.3) — but the *governing identifying field* is no longer unknown.

| Question | Answer |
|---|---|
| Which legacy field identifies Equipment? | **`ME.Code`** (§6.1/§6.2), mapped via `normalize_bcm_code()`. |
| Can rows have only one of BCM/Item Number? | Every sampled row carries `ME.Code` + a `SCAN CODE` URL + a `Barcode` column together; exhaustive conflict/blank-case analysis deferred to PR21B/C (§6.3). |
| Identifier points to no Equipment? | Blocking finding (§15) — row not imported. |
| BCM and Item Number conflict? | Blocking finding (§15); never silently prefer one. |
| Can PR21 import an orphan transaction? | **No.** `equipment_id` is a NOT NULL FK — orphan rows are validation findings, never imported rows. |

---

## 5. Equipment lifecycle and operational safety (summary; full detail §19, §44)

No lifecycle state is added. No `Equipment.status` mutation occurs
during import. Historical `CLOSED` transactions are always safe with
respect to `idx_tx_one_active_borrow` (only constrains `status='open'`);
historical `OPEN` rows are the risk case, gated by Owner Decision (§16).

---

## 6. Source file contract — real workbook supplied and directly inspected

**Source Evidence Update.** The Owner supplied the actual production
Equipment Pool AppSheet workbook, `บันทึกข้อมูล Equipment Pool.xlsx`
(28 sheets, 20,690,045 bytes). This session inspected it **directly**
with `openpyxl` (headers, sample rows, full row counts, date ranges,
and uniqueness/referential-integrity checks computed fresh against the
real data) — not transcribed from a description. The frontend mock
fixture (`frontend/src/services/legacyImportFixtures.ts`) remains
**unused as evidence anywhere in this document.** The workbook file
itself is a session upload for design-review purposes and is **not
committed to this repository** by this PR (it contains real staff names
and ward assignments; scope is `docs/**` only, §51) — the real import at
implementation time will require the Owner to supply it again through
PR21's own upload flow.

**Immutable evidence binding.** Every workbook-derived claim in this
document (§6 through §14, §24) is based on the workbook identified by:

- **SHA-256:** `8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c`
- **Sanitized evidence manifest:**
  `docs/evidence/pr21/equipment-pool-workbook-manifest.json` (machine-
  readable, structural metadata and aggregate counts only) and its
  companion `docs/evidence/pr21/equipment-pool-workbook-manifest.md`
  (human-readable summary) — committed alongside this design document.
  No row-level values, personnel names, patient identifiers, or
  free-text notes appear in either file. A future re-inspection of a
  workbook that does not hash to the SHA-256 above is a **different**
  file, and the claims below do not automatically transfer to it.

### 6.1 Closed-world sheet classification (all 28 sheets, directly inspected)

**AUTHORITATIVE TRANSACTION INPUT** (canonical — see §6.2 for why these,
not the sheets originally suggested, are canonical):

| Sheet | Role |
|---|---|
| `Orders ยืมเครื่อง` | Issue **order header** — one row per borrow transaction. Columns: วันที่ (date), เลขที่ใบยืม (order no.), แผนกที่ยืม (ward), ผู้ส่งเครื่องยืม (User), ผู้ส่งเครื่องยืม (BME), เวลา (time), จำนวนเครื่องส่งทั้งหมด (total qty), หมายเหตุ (notes). |
| `ข้อมูลส่งเครื่องมือ` | Issue **order line items** — one row per equipment unit within an order, FK'd to `Orders ยืมเครื่อง` via เลขที่ใบส่ง = เลขที่ใบยืม. Columns: ลำดับ (row key, §6.4), วันที่, เลขที่ใบส่ง, SCAN CODE ส่ง, ME.Code, Barcode ส่งเครื่อง, Equipment, Brand, Model, Serial no., รูปเครื่อง, แผนกที่ส่ง, 3 checklist columns, จำนวน, หมายเหตุ, เวลา, ชื่อ BME, ชื่อ (User). |
| `Orders คืนเครื่อง` | Receive **order header**. Columns: วันที่, เลขที่ใบคืน, แผนกที่คืน, ผู้ส่งเครื่องคืน (User), ผู้รับเครื่องคืน (BME), เวลา, จำนวนเครื่องรับคืนทั้งหมด, หมายเหตุ. |
| `ข้อมูลรับเครื่องมือ` | Receive **order line items**, FK'd via เลขที่ใบรับเครื่อง = เลขที่ใบคืน. Columns: ลำดับ, วันที่, เลขที่ใบรับเครื่อง, SCAN CODE รับ, ME.Code, Barcode รับเครื่อง, Equipment, Brand, Model, Serial no., แผนกที่รับ, รูปเครื่อง, 3 checklist columns, จำนวน, หมายเหตุ, เวลา, ชื่อ BME, ชื่อ (User). |

**DERIVED/PRESENTATION** (not parsed — confirmed by direct inspection
to be AppSheet-generated, not source data):

| Sheet | Why derived |
|---|---|
| `BMEส่ง`, ` BMEส่งเมื่อว่าน`, `BMEรับ`, `BMEรับเมื่อว่าน` | Each sheet's own header row literally contains an AppSheet query string, e.g. `SELECT B,E,G,L,M,N,O,P,R,S,T,Q WHERE B=DATE '2026-07-28'` — a rolling "today"/"yesterday" date-filtered **view** over the line-item tables, hardcoded to whatever date the workbook was last opened. **This directly contradicts this task's own suggestion that `BMEส่งเมื่อว่าน` is "materially more suitable as canonical migration input"** — direct inspection shows the opposite: it is a derived, single-day slice, not a canonical historical table. |
| `สแกนจ่ายเครื่องที่ส่งวันนี้`, `สแกนรับเครื่องวันนี้` | Same pattern — header row contains `SELECT A,B,C,D,L,J,K WHERE L=DATE '2026-07-28'` etc. Scan-verification-focused derived views. |
| ` แบบบันทึกส่งเครื่อง`, `แบบบันทึกรับเครื่อง`, `แบบบันทึกส่งเครื่องเมื่อวาน`, ` แบบบันทึกรับเครื่องเมื่อวาน` | Print-form layouts — mostly empty cells, a title label (`ส่งเครื่อง`/`รับเครื่อง`), a single hardcoded date value. Not tabular data. |

**OUT OF PR21 V1 SCOPE** (per the Roadmap's own boundary, confirmed
present in the real workbook):

| Sheet | Why out of scope |
|---|---|
| `ข้อมูลเครื่องEquipment Pool` | Equipment Master (SCAN CODE, ID CODE, Barcode เครื่อง, Equipment BCM, หน่วยงาน, Brand, Model, Serial no., images) — PR20's domain, not PR21's. |
| `Equioment Verify Checklist`, ` Equioment Verify Checklist เมื`, `Verify Checklist 01`, `Verify Checklist 02` | Real checklist transaction data exists (Date, ME.Code, Cleaner, Function Test, Run Test, Battery Check, Status, Technician, Remark) — explicitly out of the Roadmap's V1 boundary (§1) unless a later approved decision adds it. |

**IGNORED/HELPER/OTHER** (reference or aggregate data, not transaction
history):

| Sheet | Role |
|---|---|
| `CODE QR`, `Barcode ` | BCM → QR/barcode-image reference lookups. |
| `ชื่อ BME` | **BME staff roster** — header `ชื่อพนักงาน`, exactly **8 names**. Directly relevant to OD-PR21-3 (§13.1). |
| `แผนก` | **Ward reference list** — header `แผนก`, **52 entries** (e.g. `Ward 11A`, `Ward 10A`). Directly relevant to OD-PR21-4 (§14.1). |
| `ฝึกงานข้อมูลรับ`, `ฝึกงาน` | Aggregate dashboard rollups by equipment category (totals/available/borrowed-today/received-today) — not row-level transactions. |
| `Sheet32` | Empty. |

**REQUIRES OWNER CLARIFICATION — not selected as canonical without
it** (§6.3):

| Sheet | Open question |
|---|---|
| `ข้อมูลการส่ง SDC`, `ข้อมูลการรับ SDC` | Structurally near-identical to the canonical line-item tables (same columns minus the checklist/qty/notes/time/BME/User fields). Total row counts diverge sharply from the canonical sheets (28,078 vs. `ข้อมูลส่งเครื่องมือ`'s 19,912; 51,444 vs. `ข้อมูลรับเครื่องมือ`'s 19,768), but re-measurement (`sdc_sheets_evidence` in the manifest, §6) shows the **non-blank** row counts and **distinct** order-reference/`ME.Code` counts are identical to the canonical sheets' own counts — the divergence is fully attributable to large trailing blocks of blank rows (8,207 and 31,694 respectively), not additional real data. This is aggregate-count evidence, not a row-by-row diff. "SDC" is not a term defined anywhere in this repository's documentation. **Narrowed, not resolved** — recorded as an open question, not guessed. |

### 6.2 Canonical source correction (supersedes this task's own suggestion)

The task's own framing suggested `BMEส่งเมื่อว่าน` (Issue) and the
`แบบบันทึกรับเครื่องเมื่อวาน` presentation sheet (Receive) as candidates.
**Direct inspection shows both are derived, single-day, AppSheet-generated
views — not canonical.** The genuinely canonical sources, verified by
direct inspection (§6.1's first table), are the **Orders-header +
line-item pairs**: `Orders ยืมเครื่อง` + `ข้อมูลส่งเครื่องมือ` for Issue,
`Orders คืนเครื่อง` + `ข้อมูลรับเครื่องมือ` for Receive. Verified evidence
for this conclusion:

- Both line-item tables span the **full available history**: 2026-01-01
  through 2026-07-28 (~7 months), not a single day.
- **Reference resolution (distinct-value basis, not a row-level count —
  full detail in the evidence manifest, §6):** of the 5,677 **distinct**
  `เลขที่ใบส่ง` reference values present on the Issue line-item sheet,
  **all but one (5,676 of 5,677) resolve** by set membership against
  the `Orders ยืมเครื่อง` header sheet's own distinct
  `เลขที่ใบยืม` values; the one exception, `'Borrow1000000005'`, does
  not resolve — an apparent truncated/malformed value, itself a
  concrete example of the orphan-reference `ERROR` finding §15 already
  specifies, not a structural problem. On the Receive side, all 6,141
  distinct `เลขที่ใบรับเครื่อง` reference values resolve against
  `Orders คืนเครื่อง`'s distinct `เลขที่ใบคืน` values — zero orphans
  measured. **This distinct-reference-resolution metric is unrelated
  to, and must not be confused with, the `ลำดับ` row-key uniqueness
  figures in §24** (a different basis: uniqueness within one sheet, not
  resolution against a different sheet).
- Order numbers are **100% unique** within their own header sheet
  (5,685 distinct `เลขที่ใบยืม` values for 5,685 non-null rows; 6,158
  for 6,158 `เลขที่ใบคืน`) — a genuine, stable, per-transaction key.
  This is a separate claim from reference *resolution* above (whether a
  line-item's reference value finds a matching header row).

### 6.3 Field-level mapping — still not fully closed

§9/§10 are updated below with the real, verified column lists for the
four canonical sheets — this is a material advance over "conceptual
fields only." **The field-contract gate remains open** for two reasons,
neither guessed around: (a) the `ข้อมูลการส่ง SDC`/`ข้อมูลการรับ SDC`
ambiguity (§6.1) — narrowed by re-measurement (their non-blank/distinct
counts match the canonical sheets exactly, consistent with trailing
blank rows rather than a distinct equipment sub-fleet) but not fully
closed without Owner confirmation, since a full row-by-row diff was not
performed; (b) full PR21B/C-grade field
mapping (exact validation rules, exact `ERROR`/`WARNING` code list) is
implementation-slice work, not finalized by a design document per this
Roadmap's own convention (mirroring PR20's own OD-1/§7/§8 split between
"schema resolved" and "implementation-grade mapping written in the
parser slice").

### 6.4 What remains open despite the new evidence

- **Stable event identity (§24):** direct evidence found — see §24 for
  the full analysis. Strengthened, not yet fully resolved.
- **Issue↔Receive pairing (§11):** direct evidence found — **no
  explicit linking field exists** between an issue and its eventual
  return anywhere in the workbook (verified: neither header carries a
  reference to the other's order number). Remains genuinely open.
- **SDC sheet ambiguity (§6.1):** requires Owner clarification, not
  guessed.

**OD-PR21-0's topology component is RESOLVED (§7). Its field-mapping
component is narrowed but not fully closed**, pending the above.

---

## 7. Source/session topology (H1) — RESOLVED: Option A

**The problem.** PR19's foundation is `ImportSession → exactly one
ImportSource` (`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §3-4;
`AdapterInvocationContext` correspondingly carries one
`import_session_id`/`import_source_id`/`source_checksum` per invocation,
`import_adapter_context.py:37-76`). PR21 must reason across **two**
logically distinct datasets (Issue History, Receive History), and one
historical `BorrowTransaction` may need provenance from **both** an
issue row and a receive row (§8). A design that quietly assumes a single
`import_source_id`/checksum/source-row is sufficient for that transaction
is incorrect.

**Three topology options were evaluated** (A: one workbook/one
`ImportSession`/one `ImportSource`; B: one session with multiple
sources, requiring a PR19 foundation extension; C: two independent
sessions plus a staging/pairing layer) — full evaluation preserved
below for record.

**RESOLVED (Source Evidence Update): Option (A).** The Owner-supplied
real workbook (§6) is confirmed to be **exactly this shape** — one
`.xlsx` file containing all Issue and Receive sheets (among 28 total),
including both canonical Issue/Receive pairs (§6.2). This is not a
hypothetical anymore:

- PR21's `ImportSession` → exactly one `ImportSource`, matching PR19's
  existing, unmodified topology — **zero PR19 foundation changes
  required.**
- PR21's adapter's `parse()` step selects and parses the whitelisted
  sheets (§6.1) from this one source, exactly as PR20's adapter already
  selects one sheet from one workbook.
- Options (B) and (C) are formally rejected — the evidence needed to
  choose between them never arises, since (A) is what the real
  deliverable actually is.

**OD-PR21-0's topology component is RESOLVED.** §9, §10 below now carry
real, verified field lists (§6.1) rather than conceptual placeholders.
§24's stable-identity analysis and the final table names in §8 and
§32/§36 are **still narrowed but not fully finalized** — see §6.4 for
exactly what remains open.

<details>
<summary>Full three-option evaluation (preserved for record; (B)/(C) are rejected, not deleted, so the reasoning remains auditable)</summary>

- **(A) One workbook / one `ImportSession` / one `ImportSource`**
  containing both Issue and Receive sheets. Fits PR19's existing
  topology with zero foundation changes — the adapter's `parse()` step
  simply selects and parses whitelisted sheets from one source, exactly
  as PR20's adapter already selects one sheet from one workbook.
  Lowest implementation risk. **Selected — confirmed to match the real
  deliverable.**
- **(B) One `ImportSession` with multiple `ImportSource`s.** Would
  require an explicit, reviewed PR19 foundation extension (today's
  schema and `AdapterInvocationContext` are built around exactly one
  source per session) — out of scope for a PR21-only design and a
  materially larger risk surface, since it touches shared infrastructure
  every other dataset type (including the merged PR20) also depends on.
  **Rejected — not needed; the real workbook is one file.**
- **(C) Two `ImportSession`s / two `ImportSource`s**, plus an explicit
  staging/pairing/reconciliation model to join rows across the two
  independent sessions. Would push real complexity into a new
  PR21-owned staging/pairing layer and risk quietly re-implementing part
  of what PR22 is chartered to own. **Rejected — not needed; the real
  workbook is one file.**

</details>

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

**Table names are not finalized**, but §7's topology resolution (Option
A) fixes one dimension: every source ref shares the same
`import_session_id`/`import_source_id` (one workbook, one source) and
differs only in sheet/row/event-type — the two-session variable
`import_session_id`/`import_source_id` case (former option C) no longer
applies.

**Source Evidence Update refinement:** §6.1's real structure is
**two-level per event side** (an `Orders` header row plus a line-item
row), not the single flat row per event this section originally
modeled. A historical transaction's full provenance may therefore span
up to **four** source rows — Issue-order-header, Issue-line-item,
Receive-order-header, Receive-line-item — not two. Whether the
order-header row needs its own persisted provenance ref, or whether the
line-item row (which already carries equipment/ward/time/BME/user
fields, §6.1) is sufficient and the header is only consulted for
order-level aggregate fields (total quantity, order-level notes) not
otherwise required by `BorrowTransaction` (§12), is left to PR21A's own
implementation-grade design — this document fixes the requirement (1:N,
richer than originally modeled) without prematurely fixing the exact
ref-table cardinality.

### 8.1 Owner Decision Closure Round 2 — RESOLVED: event-first provenance model (`LegacyEquipmentEvent`)

**This section supersedes §8's `HistoricalTransaction` framing above**
(preserved verbatim for record — it described the paired-transaction
architecture §11's original recommendation (B) assumed, before §11.1
raised the fork and this round resolved it via §11.2). The imported
artifact is no longer a paired transaction fed by up to four source
rows; it is one independent, immutable event fed by up to **two**:

```
LegacyEquipmentEvent (ISSUE | RECEIVE)
    |
    +--> LegacyEquipmentEventSourceRef[*]   (up to 2: this event's own
                                              order-header row, this
                                              event's own line-item row)
```

This is a genuine **simplification**, not merely a rename: because
pairing an Issue to a Receive is no longer attempted at import time
(§11.2), one event's provenance never needs to fuse evidence from a
*different, independently-timestamped* source row belonging to the
opposite event type. Each event's provenance is now self-contained.

**Conceptual fields (exact schema is PR21A's own implementation-grade
work, not fixed here):**

- `id` — internal UUID, the durable database identity (never the
  legacy order reference, §20).
- `equipment_id` — resolved per §4, NOT NULL (an unresolvable
  identifier remains a blocking `ERROR`, §15, unchanged).
- `event_type` — `ISSUE` | `RECEIVE`. **Not a new `Equipment` lifecycle
  state** (§18, unchanged) — this is the event's own type, not
  `Equipment.status`.
- `occurred_at` — the source's own date+time, normalized to aware UTC
  (§22, unchanged).
- `business_date` — derived at read time via the existing
  `business_date_and_shift()` (§23, unchanged) — never backfilled or
  stored redundantly as a separate write-time decision.
- `legacy_ward_text` / `resolved_ward_id` — per §14's already-resolved
  (OD-PR21-4) architecture and ownership, unchanged by this round.
- `legacy_bme_name` — per §13's already-resolved (OD-PR21-3) policy,
  unchanged by this round; still never conflated with `AuditLog.user_id`
  (§21).
- `legacy_order_reference` — the source's own `เลขที่ใบส่ง`/
  `เลขที่ใบรับเครื่อง` (order/slip number), preserved as business-
  reference provenance (§20's now-resolved OD-PR21-5, below).
- `migration_authority_id` — reference to the immutable
  `LegacyMigrationAuthority` (a design concept, not a table implemented
  by this round) this event was imported under (§24.2, PR #102 fix
  round) — together with `legacy_source_row_key`, forms this event's
  durable logical identity. Never null; never reassigned after import.
- `legacy_source_row_key` — the source's own `ลำดับ`. Durable **only in
  combination with `migration_authority_id`** (§24.2) — never treated
  as unique or durable on its own, and never claimed durable beyond the
  one migration authority that imported it.
- Import/session/source provenance fields (`import_session_id`,
  `import_source_id`, source checksum) — per §26, unchanged.
- `created_at`/`imported_at` — standard audit timestamps.

**What this section does NOT do:** it does not fix column types,
nullability beyond what is already normatively required above, index
names, or table names — those remain PR21A's own design work, exactly
as §8's original framing already deferred them. It does not remove
`equipment_id`'s NOT NULL requirement, does not weaken §15's validation
severity taxonomy for row-level validity (unchanged — only pairing-
specific findings are affected, §16/§17's Round 2 amendment below), and
does not touch `BorrowTransaction` itself (§12, revised below).

---

## 9. Issue History semantics (real fields verified; parse-rule detail deferred to PR21B)

**Source Evidence Update.** Real, directly-verified field lists from
the canonical sheets (§6.1, §6.2) — this replaces the prior
conceptual-only placeholder:

**`Orders ยืมเครื่อง` (order header, one row per transaction):**
วันที่ (date) → candidate `borrowed_at` date component; เลขที่ใบยืม
(order no., 100% unique, §6.2) → stable order-level identity candidate
(§24); แผนกที่ยืม (ward) → `ward_id` via §14; ผู้ส่งเครื่องยืม (User)
and ผู้ส่งเครื่องยืม (BME) (two named actors) → per-ref provenance
(§8/§13); เวลา (time) → combines with วันที่ for the full `borrowed_at`
timestamp; จำนวนเครื่องส่งทั้งหมด (total qty) → order-level aggregate,
not directly mapped to any single `BorrowTransaction` column; หมายเหตุ
(notes) → candidate `notes`, subject to the §42 privacy caveat.

**`ข้อมูลส่งเครื่องมือ` (order line item, one row per equipment unit):**
ลำดับ (row key, near-100%-unique — §24) → stable row-level identity
candidate; วันที่, เลขที่ใบส่ง (= parent order's เลขที่ใบยืม, §6.2);
SCAN CODE ส่ง / ME.Code / Barcode ส่งเครื่อง (§4's equipment-identity
candidates — `ME.Code` is the closest analogue to PR20's BCM concept
and warrants the same normalize-and-match treatment,
`identifiers.py`); Equipment / Brand / Model / Serial no. → descriptive,
not identity-bearing on their own; แผนกที่ส่ง (ward, line-level —
may differ from the order header's, requiring an explicit precedence
rule at implementation time); three checklist columns (equipment-
condition checks, e.g. "ตัวเครื่องหน้าจอไม่แตกร้าว") → not named in the
Roadmap objective, candidate for `notes`/provenance-only, not fabricated
into a schema column; จำนวน (qty, line-level, usually 1) → not
import-relevant per §12; หมายเหตุ → candidate `notes`; เวลา (line-level
time, may differ from order header's); ชื่อ BME / ชื่อ (User) → per-ref
provenance (§8/§13, cross-checked against the `ชื่อ BME` roster, §6.1).

No field beyond what the Roadmap objective already names (§1) is
promoted into a `BorrowTransaction` column — checklist/qty/image fields
remain candidates for provenance-only capture, not new schema. Final
`ERROR`/`WARNING` code assignment and the line-vs-header precedence
rule for fields present on both (date, ward, time) are implementation-
grade decisions deferred to PR21B, consistent with this Roadmap's own
design/implementation split (§6.3).

---

## 10. Receive History semantics (real fields verified; parse-rule detail deferred to PR21C)

**Source Evidence Update.** Same treatment as §9, from the Receive
canonical pair:

**`Orders คืนเครื่อง` (order header):** วันที่ → candidate `returned_at`
date component; เลขที่ใบคืน (order no., 100% unique) → stable
order-level identity candidate (§24); แผนกที่คืน (ward); ผู้ส่งเครื่องคืน
(User) and ผู้รับเครื่องคืน (BME) (two named actors — note the receive
side's own labeling: the *User* is the one returning/sending back, the
*BME* is the one receiving it at the pool, consistent with §21's
import-actor-vs-historical-operator distinction); เวลา; จำนวนเครื่องรับคืนทั้งหมด
(total qty, order-level aggregate); หมายเหตุ.

**`ข้อมูลรับเครื่องมือ` (order line item):** ลำดับ (row key candidate,
§24); วันที่; เลขที่ใบรับเครื่อง (= parent order's เลขที่ใบคืน); SCAN
CODE รับ / ME.Code / Barcode รับเครื่อง (§4); Equipment/Brand/Model/
Serial no.; แผนกที่รับ (ward, line-level); รูปเครื่อง; three checklist
columns → candidate `condition_on_return`/provenance-only (already
free-text-tolerant per §12), not fabricated into new schema; จำนวน;
หมายเหตุ; เวลา; ชื่อ BME / ชื่อ (User) → per-ref provenance.

**Whether receive records explicitly identify their matching issue
record: confirmed NO** by direct inspection — neither `Orders คืนเครื่อง`
nor `ข้อมูลรับเครื่องมือ` carries any field referencing the originating
`เลขที่ใบยืม`/Issue order. §11 defines the matching architecture; the
actual matching keys are **not** established by the source structure
(§6.4) — this is a confirmed negative finding, not an unresolved
inspection gap.

### 10.1 Field-level contract classification (Owner Decision Closure Round 1)

Every real, verified column (§6.1, §9, §10) on the four canonical
sheets, classified per this round's own required categories:
**imported business fact** (reaches a `BorrowTransaction` column, via
mapping/validation), **provenance only** (stored per §8's source-ref
model, never a `BorrowTransaction` column), **validation-only**
(consulted to accept/reject a row, never persisted as such),
**ignored** (not carried forward at all), or **privacy-blocked**
(withheld pending OD-PR21-6, §42). No field beyond what the Roadmap
objective (§1) already names is promoted into a new
`BorrowTransaction` schema column (§9, unchanged).

**Issue side (`Orders ยืมเครื่อง` + `ข้อมูลส่งเครื่องมือ`):**

| Field | Classification |
|---|---|
| ลำดับ | Validation-only / provenance — identity candidate pending §24.1; never a `BorrowTransaction` column |
| วันที่, เวลา | Imported business fact — `borrowed_at` date/time components |
| เลขที่ใบส่ง / เลขที่ใบยืม | Imported business fact (transaction_no legacy-namespace source, §20) + provenance (§8) |
| SCAN CODE ส่ง, Barcode ส่งเครื่อง | Validation-only — equipment-identity cross-check candidates (§4); `ME.Code` remains primary |
| ME.Code | Imported business fact — resolves `equipment_id` (§4) |
| Equipment, Brand, Model, Serial no. | Provenance only — descriptive, not identity-bearing (§9) |
| รูปเครื่อง (photo reference) | Ignored — not a data field this design imports |
| แผนกที่ส่ง | Imported business fact — `ward_id` via OD-PR21-4 (§14) |
| 3 equipment-condition checklist columns | Provenance only — candidate for provenance capture, never fabricated into a schema column (§9) |
| จำนวน | Ignored — not import-relevant (§12) |
| หมายเหตุ | **Privacy-blocked** — OD-PR21-6 (§42), never permanent |
| ชื่อ BME, ชื่อ (User) | Imported business fact / provenance — per-ref legacy operator names, `ISSUE`-tagged (§8, §13) |

**Receive side (`Orders คืนเครื่อง` + `ข้อมูลรับเครื่องมือ`):** identical
treatment, mirrored: ลำดับ (validation-only/provenance);
วันที่/เวลา (`returned_at` components); เลขที่ใบรับเครื่อง/เลขที่ใบคืน
(business fact + provenance); SCAN CODE รับ/Barcode รับเครื่อง
(validation-only); ME.Code (business fact); Equipment/Brand/Model/Serial
no. (provenance only); รูปเครื่อง (ignored); แผนกที่รับ (business fact,
`ward_id`); 3 checklist columns (provenance only, `condition_on_return`
candidate per §10); จำนวน (ignored); หมายเหตุ (**privacy-blocked**,
OD-PR21-6); ชื่อ BME/ชื่อ (User) (business fact/provenance,
`RECEIVE`-tagged).

**What remains genuinely unresolved by this classification:** the
`ข้อมูลการส่ง SDC`/`ข้อมูลการรับ SDC` sheet ambiguity (§6.1) — this
classification covers only the confirmed canonical sheets; if the Owner
later confirms SDC sheets represent additional, distinct transaction
data (not a trailing-blank-row artifact of the canonical sheets, §6.1),
this classification does not automatically transfer to them. **This
classification does not resolve OD-PR21-0's field-contract sub-component
in full** — it settles the canonical-sheet portion; the SDC question
remains open exactly as §45/§53 record.

---

## 11. Issue ↔ Receive matching — architecture and validation treatment

Three ways to represent historical pairs: **(A) independent events**
(simplest, but does not produce a `returned_at`-populated closed
transaction — the domain's normal meaning of "history"); **(B) paired
into historical `BorrowTransaction` rows** (most compatible with the
existing single-row-per-transaction schema and existing
search/reporting queries); **(C) a separate approved historical model**
(not recommended — fragments unified transaction history, §27).

**Recommendation: (B).** Architectural, not resolved.

**Source Evidence Update — matching keys confirmed NOT present.**
§7's topology is resolved and §9/§10's field lists are now real, but
direct inspection of both the Issue and Receive canonical sheets
(`Orders ยืมเครื่อง`/`ข้อมูลส่งเครื่องมือ`,
`Orders คืนเครื่อง`/`ข้อมูลรับเครื่องมือ`) confirms **no explicit,
deterministic Issue↔Receive linking field exists** — an issue's order
number (`เลขที่ใบยืม`, e.g. `Borrow1000000009210`) and its eventual
return's order number (`เลขที่ใบคืน`, e.g. `Return100000009892`) are
independent numbering series with no cross-reference column on either
side. The only shared attribute between a given piece of equipment's
issue and receive events is `ME.Code`/`SCAN CODE` (equipment identity)
plus timestamps — which is exactly the "nearest-previous-event"
heuristic this task explicitly forbids without Owner approval (§7 of
the source-evidence task: *"Do not assume Issue and Receive pair merely
by nearest timestamp... If absent, retain matching as a blocking Owner
Decision. No fuzzy pairing."*). **Pairing therefore remains a blocking
Owner Decision — now backed by a confirmed negative finding rather than
an inspection gap.** If the Owner determines temporal/equipment-based
matching is acceptable business policy despite the risk of ambiguity
(e.g. equipment double-borrowed the same day), that is an explicit,
reviewed policy decision this document does not make unilaterally.

**Validation treatment (unchanged):** ambiguous pairing is a blocking
`ERROR` finding (§15), **never** a fuzzy/temporal heuristic match unless
and until the Owner explicitly approves one, and — per §15's
all-or-nothing gate — an ambiguous pair anywhere in a batch blocks that
entire validation snapshot from producing a dry-run (§28), not just that
one row.

### 11.1 Owner Decision Closure Round 1 — an architecture fork raised, not resolved

§11's original recommendation, **(B) paired into historical
`BorrowTransaction` rows**, implicitly assumed *some* deterministic
pairing rule would eventually be found or approved for the large
majority of rows. §11's own confirmed-negative finding (no explicit
linking field exists) means that assumption cannot be taken for
granted, and this round's own evidence review does not identify any
combination of `ME.Code`/order-number/timestamp/Ward fields that
constitutes a deterministic (non-heuristic) pairing rule — every
candidate combination still requires either an exact-timestamp
coincidence or a "nearest" comparison, which is exactly the heuristic
this document has already ruled out without explicit Owner approval
(§11, unchanged).

This creates a genuine, previously-unstated architecture fork that
**this round does not resolve** (per this Owner Decision Closure
round's own instruction: raise the fork explicitly rather than change
architecture silently):

- **Fork (i) — approve a specific deterministic, non-fuzzy pairing
  rule**, if the Owner can identify one this document's evidence review
  did not find (e.g. a business-process guarantee such as "one
  equipment unit is never issued twice before being received," which
  would make Issue/Receive events for the same `ME.Code` pair
  deterministically by chronological adjacency without needing a
  "nearest" *heuristic* comparison across ambiguous candidates — this
  is offered as an illustration of the *kind* of rule that would
  qualify, not a pre-approved rule). §11's original option (B)
  architecture stands unmodified if this fork is chosen.
- **Fork (ii) — adopt event-first staging.** Import each Issue/Receive
  historical source row as an independent historical
  event/provenance record first (§11's original option (A)), with
  actual paired-`BorrowTransaction` construction deferred to a later,
  explicitly-scoped reconciliation step — which may fall inside a
  revised PR21D, or may belong to PR22's own chartered reconciliation
  work (§1's PR22 boundary) if the Owner decides pairing is better
  treated as post-import reconciliation rather than an import-time
  gate. Choosing this fork is an **architecture change** from §11's
  current recommendation (B), not a mechanical implementation detail —
  it changes what a "historical transaction" means at import time
  (an unpaired event record vs. a paired open/closed transaction) and
  therefore requires its own explicit Owner/architecture sign-off
  before PR21C/D may proceed, exactly as this section's own governing
  instruction requires.

**Both OD-PR21-1 and OD-PR21-2 (§16, §17) are resolved by this round
independently of this fork** — their resolution (block unmatched
ISSUE/RECEIVE as `ERROR`) holds under *either* fork: under fork (i), an
unmatched row after a deterministic pairing attempt is still blocked;
under fork (ii), "unmatched" is redefined as "no historical event
record was ever expected to pair," and whether that changes OD-PR21-1/2's
blocking treatment is itself part of what choosing fork (ii) would need
to settle. This dependency is stated here explicitly so a future reader
does not treat OD-PR21-1/2's resolution as implying this fork is closed.

**Status: OPEN.** Folded into OD-PR21-0's pairing sub-component (§45).
Blocks PR21C regardless of which fork the Owner eventually selects,
since PR21C's own parser/validation design differs materially between
the two forks.

### 11.2 Owner Decision Closure Round 2 — RESOLVED: fork (ii), event-first, adopted

**§11.1's fork is closed. Fork (ii) is selected: event-first staging.**
No deterministic, non-fuzzy Issue↔Receive pairing rule was identified
by this round's evidence review, and none was supplied by the Owner —
fork (i) remains available in principle (§11.1's own wording: "if the
Owner can identify one this document's evidence review did not find")
but is not exercised now. §11's original recommendation **(B) paired
into historical `BorrowTransaction` rows** is superseded — **(A)
independent events**, via `LegacyEquipmentEvent` (§8.1), is now
PR21's adopted architecture for V1.

**The resolved Owner Decision, stated precisely (per this round's own
governing instruction):**

- **(A)** If a future source or Owner-confirmed business rule supplies
  an explicit, immutable shared transaction key, deterministic pairing
  may be persisted at that time — this document does not foreclose
  that possibility, it only refuses to invent one now.
- **(B)** The currently inspected workbook (SHA-256
  `8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c`,
  §6) provides no such shared deterministic key — unchanged finding
  from §11/§11.1.
- **(C)** Therefore, for this workbook, Issue and Receive line-item
  rows are imported as **independent** `LegacyEquipmentEvent` rows
  during PR21 — never fused into one paired transaction at import time.
- **(D)** No validation `ERROR` is raised merely because an Issue event
  has no deterministically identifiable Receive counterpart, or vice
  versa. §16/§17 are amended accordingly, below — **not silently
  replaced**; see those sections for the precise amendment and what
  remains unchanged.

**Why this does not weaken the original safety principle (§3, §16,
§17):** the danger those sections guarded against was never "pairing is
philosophically important" — it was "importing an unresolved historical
fact as a live-meaningful `OPEN` `BorrowTransaction` risks colliding
with `idx_tx_one_active_borrow` and misrepresenting an unproven
outcome." `LegacyEquipmentEvent` is not a `BorrowTransaction` row at
all (§12, revised below) — it structurally cannot participate in that
constraint, and it never claims an event was returned (or not) beyond
exactly what the source itself states about that one event. The
principle is preserved; the mechanism that previously enforced it (a
validation-time block) is no longer the only way to satisfy it, because
the target data model no longer creates the risk in the first place.

**PR22 boundary, reaffirmed and sharpened (§1):** PR22 owns optional
reconciliation, likely-pair review, duplicate review across imports,
unified history validation, and sign-off. PR22 (or a later, explicitly
scoped PR21 sub-slice) **may propose or persist a link** between two
already-imported `LegacyEquipmentEvent` rows (one `ISSUE`, one
`RECEIVE`) — but only through deterministic evidence or explicit
authorized review, **never** a nearest-timestamp/same-day/BCM-alone/
Ward-alone/BME-alone/order-sequence/row-proximity/fuzzy-scoring
heuristic (all explicitly forbidden, restated from §11's own standing
prohibition). Any such later reconciliation step **must not rewrite or
delete** the original `LegacyEquipmentEvent` rows or their provenance —
they remain the permanent, immutable historical record (§27, §39,
unchanged) regardless of whether a later link is ever established.

**Status: RESOLVED (Owner Decision Closure Round 2).** Folded into
OD-PR21-0's pairing sub-component (§45). Unblocks PR21C's own pairing-
architecture dependency (§46, §54) — PR21C validates `RECEIVE` events
independently and adds no pairing heuristic of its own.

---

## 12. BorrowTransaction compatibility analysis

**Owner Decision Closure Round 2 — reframing, not deletion.** The table
below remains exactly as originally verified — it is the evidentiary
basis for a conclusion this round now states explicitly: **PR21 V1 does
not write `BorrowTransaction` rows for imported legacy history at all.**
`LegacyEquipmentEvent` (§8.1) is the actual imported artifact. This
table is retained as the audit trail proving *why* direct
`BorrowTransaction` representation was rejected, per §11.2/§5 of this
round's own task:

- **`transaction_no`** (NOT NULL, UNIQUE): satisfiable in principle
  (§20's resolved LEGACY-namespace direction) — not itself a blocker,
  but moot for `LegacyEquipmentEvent`, which has no such column.
- **`borrowed_at`** (NOT NULL): a structural incompatibility for an
  unpaired `RECEIVE` event specifically — there is no known issue
  timestamp to populate it with, and inventing one would fabricate
  evidence the source does not contain. This alone makes direct
  `BorrowTransaction` representation **impossible**, not merely
  policy-disfavored, for a `RECEIVE` event with no proven issue
  counterpart.
- **`status`** (`OPEN`/`CLOSED` only): for an unpaired `ISSUE` event,
  `OPEN` risks the live `idx_tx_one_active_borrow` collision §16
  already identified; `CLOSED` would assert a return the source does
  not prove. Neither value is supportable by evidence alone.
- **`returned_at`**, **`borrower_user_id`**/**`received_by_user_id`**:
  individually nullable and not fabrication risks on their own — the
  blocking issues above are `borrowed_at` and `status`, not these.

**Conclusion (§5 of this round's task): direct `BorrowTransaction`
representation of a raw, unpaired legacy source row is semantically
unsafe, and for the `RECEIVE`-without-known-`borrowed_at` case,
structurally impossible without fabrication.** This is the affirmative
case for `LegacyEquipmentEvent` (§8.1) as a genuinely separate model,
not a stylistic preference.

Full column inventory of `borrow_transactions`
(`backend/app/models/transaction.py:121-349`):

| Column | Type / constraint | Classification |
|---|---|---|
| `transaction_no` | `String(30)` NOT NULL, **UNIQUE**, indexed; normally sequence-generated | **Historical (superseded, §20/§20.1):** was "direction resolved, exact format deferred" under Round 1. **Moot under event-first** — `LegacyEquipmentEvent` has no `transaction_no` column; OD-PR21-5 is RESOLVED for V1's actual scope. |
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
| `notes` | `Text`, nullable | Derivable if source has a notes field (§42 privacy caveat applies). |
| `status` | NOT NULL, default `OPEN`; exactly `OPEN`/`CLOSED` | **Historical analysis (superseded by §11.2's Round 2 resolution, retained for record):** was framed as "derivable from pairing outcome" under §11's original (B) architecture. **Moot under event-first (§11.2, §8.1)** — `LegacyEquipmentEvent` has no `status` column of this kind; it is never `OPEN`/`CLOSED`, only `ISSUE`/`RECEIVE`. |
| `dispatch_type`, `routine_round` | nullable | Never inferred (§23) — leave NULL unless source states them. |
| `legacy_status` | `String(20)`, nullable, provenance-only | Direct precedent for the "preserve exact original value, never read by live workflow" pattern reused in §43. |

**Historical summary (superseded by this round's own conclusion above,
retained for record):** "No existing column is a blocking gap on its
own" was true for the columns considered individually against a
*paired* transaction, where a receive counterpart's `borrowed_at` would
already be known from its matched issue. **It is not true for an
unpaired `RECEIVE` event's `borrowed_at`** — see this section's Round 2
conclusion above, which is the current, governing analysis. No current
`User` row is ever fabricated (both actor FKs nullable) — that part of
the original finding stands unchanged.

---

## 13. Legacy BME name preservation policy

**OD-PR21-3 — RESOLVED (Owner Decision Closure Round 1).** The Owner
has explicitly accepted the recommended V1 policy: preserve the exact
legacy BME text permanently as historical provenance; never create
`User` accounts from it; never auto-map by display-name similarity; an
optional mapping to a current `User` is nullable and explicit
(Administrator-driven, out of PR21 V1's own scope per §13's existing
"later mapping procedure is not designed here" boundary); import
succeeds whether or not a current-user mapping exists; the import actor
(who ran the import) remains structurally separate from the historical
BME actor (who performed the original transaction), exactly as §21
already requires. This resolves the mapping-*procedure-boundary*
question §13 originally left open — the boundary is: PR21 V1 captures
and preserves the raw text only; the mapping procedure itself remains
future, separately-approved work, never blocking import.

No auto-created `User` accounts (`User.password_hash` is NOT NULL —
`backend/app/models/user.py:72-99` — structurally impossible without
fabricating credentials). No display-name-similarity auto-mapping.

Given §8's 1:N provenance requirement, the raw legacy operator name is
most naturally captured **per source ref** (tagged by that ref's
`event_type` — `ISSUE` actor vs. `RECEIVE` actor), not as two
independent flat columns directly on `borrow_transactions`. Whether a
denormalized convenience copy is also kept directly on
`borrow_transactions` (for query simplicity) is an implementation-time
schema-shape choice, not a normative requirement of this design — the
minimum requirement is that the raw text survives verbatim, attributed
to the correct role, per historical event. `borrower_user_id`/
`received_by_user_id` remain NULL until an explicit, auditable,
Owner-approved later mapping step resolves them (§21).

The later mapping procedure itself is **not** designed here — out of
PR21's Version 1 boundary (OD-PR21-3, §45).

### 13.1 Source Evidence Update — BME roster found

The workbook's `ชื่อ BME` sheet (§6.1) is a small, closed roster —
header `ชื่อพนักงาน` ("employee name"), **exactly 8 entries**. This is
materially useful evidence for OD-PR21-3's later-mapping-procedure
boundary decision: a roster this small makes a future manual
name-to-`User` mapping step tractable (8 names to reconcile, not
hundreds), even though this document still does not design that
procedure. **Historical note (Source Evidence Update, superseded):**
this roster evidence, on its own, did not resolve OD-PR21-3 at the time
it was found — a name *list* is not a mapping to existing `User` rows.
**Current truth (Owner Decision Closure Round 1): OD-PR21-3 is now
RESOLVED** (§13 above) — not by this roster evidence, but by the
Owner's separate, explicit acceptance of the preserve-raw-text/
no-auto-mapping policy. The roster remains useful evidence for a
possible *future* manual mapping step; it does not itself constitute
that mapping, which remains out of PR21 V1's scope exactly as §13
already states.

---

## 14. Ward normalization / mapping design

**OD-PR21-4 — RESOLVED (Owner Decision Closure Round 1).** The Owner
has explicitly accepted the recommended ownership/curation policy:
Administrator owns the `legacy_ward_aliases` mapping table; every
mapping is explicit, auditable, and persisted (an operator action, not
an automatic inference); exact canonical-string match resolves
automatically; a known alias resolves via the explicit mapping table; an
unknown or ambiguous Ward is a validation `ERROR` (§15), never a
silently-created `Ward` row and never a fuzzy/similarity match; the raw
legacy Ward text is always preserved regardless of match outcome (§26).
This resolves the alias table's *ownership* question §14 originally left
open — the architecture itself (§14's diagram below) was already
resolved and is unchanged by this round.

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
alias table's ongoing curation is **OD-PR21-4** (§45).

### 14.1 Source Evidence Update — Ward reference list found, lower ambiguity than feared

The workbook's `แผนก` sheet (§6.1) is a canonical Ward reference list —
header `แผนก` ("department/ward"), **52 entries** (e.g. `Ward 11A`,
`Ward 10A`). Spot-checking actual transaction rows against this list
(`ICU3`, `Ward 5A`, `Recovery Room`, `Emergency/Trauma Center`, `Labor
and Delivery Room` — all observed directly in `Orders`/line-item sample
rows, §6.1) shows the source data already uses names that read as
already-canonical/current-format strings, not obviously legacy or
inconsistently-formatted variants. This is evidence the exact-match path
of §14's architecture may resolve the large majority of rows, with the
alias table needed for a smaller edge-case set than originally assumed
— **not a guarantee**, since this observation is from a small sample,
not a full cross-check against the live `Ward` table's exact `code`/
`name` values (out of scope for a design document; that comparison
belongs to PR21A/B's implementation). **Historical note (Source
Evidence Update, superseded):** this reference-list evidence, on its
own, did not resolve OD-PR21-4's ownership question at the time it was
found — a 52-entry reference list is evidence of *lower ambiguity*, not
a decision about *who* curates the alias table. **Current truth (Owner
Decision Closure Round 1): OD-PR21-4 is now RESOLVED** (§14 above) —
not by this reference-list evidence, but by the Owner's separate,
explicit acceptance of the Administrator-ownership policy.

---

## 15. Validation model (H2) — all-or-nothing gate and severity taxonomy

**Current PR19 runtime behavior is authoritative and is not modified by
PR21:** if validation contains a blocking `ERROR`, the session becomes
`validation_failed`; dry-run is not admitted from `validation_failed`
(`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §13).

**Selected: ALL-OR-NOTHING VALIDATION GATE.** Any blocking `ERROR`
anywhere in the batch → the whole session becomes `validation_failed`;
findings remain visible in the validation result; **no `DryRunPlan` is
created for that session.** A `DryRunPlan` only ever exists for a
session whose validation snapshot passed with zero blocking errors —
see §28 for the exact, corrected downstream contract this implies. This
preserves PR19's state machine completely unmodified and is the
lowest-risk choice for a V1 implementation.

**PR21 does not support partial import in V1.** If the Owner later
wants partial import (some rows proceed to dry-run/execute while others
are excluded), that requires a separate, explicitly approved change to
PR19's own validation semantics — out of this document's scope, and not
claimed as already supported anywhere in this design.

**Consistent severity classification (no condition may read as
"blocking but still a candidate"):**

| Condition | Severity | Effect |
|---|---|---|
| Missing/unresolved equipment identifier, or identifier conflict | ERROR | Session → `validation_failed`, no dry-run |
| Invalid/malformed timestamp | ERROR | Session → `validation_failed`, no dry-run |
| Missing or unmapped or ambiguous Ward | ERROR | Session → `validation_failed`, no dry-run |
| Duplicate source row/event (§25) | ERROR | Session → `validation_failed`, no dry-run |
| Missing required source identity — data-bearing row with blank `ลำดับ` (§24.2) | ERROR | Session → `validation_failed`, no dry-run |
| Unknown BME name (mapping intentionally deferred) | WARNING | Non-blocking — expected, since BME mapping is a later step (§13), not an import precondition |
| Malformed source structure (wrong sheet, missing headers) | ERROR | Session → `validation_failed`, no dry-run |

**Owner Decision Closure Round 2 — three rows REMOVED, not silently
deleted.** This table previously listed **"Ambiguous Issue↔Receive
pairing (§11)"**, **"Unmatched ISSUE (§16)"**, and **"Unmatched RECEIVE
(§17)"** as `ERROR`-severity conditions. Under the now-adopted
event-first architecture (§11.2, §16.1, §17.1), PR21 V1 never attempts
Issue↔Receive pairing at import time, so there is no pairing outcome
for a row to be "ambiguous" or "unmatched" *about* — these three rows
are removed from the current severity table because the condition they
described no longer arises, not because the underlying safety concern
was weakened (§11.2 explains why the concern is structurally
addressed instead). See §16.1/§17.1 for the full amendment record.

**Exactly two severities — no third tier**, matching PR19A's own
taxonomy. `WARNING` never blocks, and a row carrying only `WARNING`
findings is the *only* kind of row that may appear in a dry-run plan
with attached warning context (§28). **Reporting convention preserved:**
`valid_rows = total_rows - invalid_rows` is retained as an informational
count inside the validation result (visible even when the session as a
whole is `validation_failed`, so the operator can see how close the
source is to a clean pass) — it does **not** imply any subset of rows
proceeds to dry-run on its own; the session-level gate is binary.

Final error-code list remains deferred to PR21B/C (contingent on §6),
consistent with §9/§10.

---

## 16. Unmatched historical ISSUE — Owner Decision required

**OD-PR21-1 — RESOLVED (Owner Decision Closure Round 1).** The Owner
has explicitly accepted the recommended safest V1 policy exactly as
proposed: an unmatched historical ISSUE row is `ERROR`-severity (§15);
the whole session becomes `validation_failed`; no `DryRunPlan` is ever
created for that session (§28); PR21 never imports an unmatched issue
as a live `OPEN` transaction, and never fabricates a synthetic receive
to force a pairing. Rationale, as stated by the Owner: historical import
must not fabricate transactions or affect live `OPEN` uniqueness.

The underlying danger this closes: `idx_tx_one_active_borrow` allows at
most one `OPEN` transaction per equipment (§3); importing an unmatched
issue as `OPEN` would have risked blocking today's live dispatch for a
reason no current operator caused. Because this is `ERROR`-severity, a
session containing an unmatched issue row never produces a `DryRunPlan`
at all (§28) — it is visible only as a validation finding, never as a
"blocked plan row." §52's Mandatory STOP condition on this point was
closed by explicit Owner decision in Round 1.

### 16.1 Owner Decision Closure Round 2 — AMENDMENT, not reversal

**§11.1's pairing-architecture fork was open when OD-PR21-1 was
resolved in Round 1** — the paragraph above (preserved verbatim as the
historical record of that resolution) explicitly said "every row that
reaches execution has already passed pairing (barring §11.1's still-open
architecture fork)." §11.2 has now closed that fork by adopting
event-first staging. This changes what "unmatched" means for this
Owner Decision, and this amendment states that change precisely rather
than leaving the Round 1 text to silently contradict the Round 2
architecture:

- **What changes:** an Issue event with no deterministically
  identifiable Receive counterpart is **no longer, by itself, an
  `ERROR`-severity finding**. Under event-first (§8.1, §11.2), it
  imports successfully as its own independent `LegacyEquipmentEvent`.
  "Unmatched" in the original Round 1 sense (§11's now-superseded
  option (B), "no paired Receive found") is not a validation condition
  under the adopted architecture — there is no pairing attempt at
  import time to fail.
- **What does NOT change:** every genuine row-level validity condition
  in §15's severity table remains exactly `ERROR` as before — an
  unresolvable equipment identifier, an invalid/malformed timestamp, an
  unmapped/ambiguous Ward, a duplicate source row/event, or a
  data-bearing row missing its required source identity (blank
  `ลำดับ`, §24.2) — none of these are "pairing" conditions, and none are
  weakened by this amendment. Nor does this amendment reopen the
  underlying safety principle: `LegacyEquipmentEvent` is not a
  `BorrowTransaction` row (§12) and cannot itself collide with
  `idx_tx_one_active_borrow` — the danger OD-PR21-1 was written to
  prevent is structurally absent from the adopted architecture, not
  merely re-permitted by a validation-severity change.
- **Net effect:** OD-PR21-1 remains **RESOLVED** — the Owner-accepted
  principle (never fabricate a live-meaningful `OPEN` transaction from
  unresolved history) is unchanged and, if anything, more directly
  guaranteed. Only the specific "unmatched issue = whole-session
  `ERROR`" mechanism, which assumed the now-superseded paired
  architecture, is withdrawn as inapplicable — never silently, always
  as this recorded amendment.

---

## 17. Legacy RECEIVE without ISSUE — Owner Decision required

**OD-PR21-2 — RESOLVED (Owner Decision Closure Round 1).** Same
treatment and same Owner acceptance as §16: an unmatched historical
RECEIVE row is `ERROR`-severity (§15); the whole session's validation
fails and no `DryRunPlan` is created (§28); an unmatched receive row is
visible only as a validation finding, never as a plan row; no synthetic
issue event is ever fabricated to force a pairing. §52's Mandatory STOP
condition on this point was closed by explicit Owner decision in
Round 1.

**Dependency on §11.1, stated explicitly (historical record):** both
OD-PR21-1 and OD-PR21-2's resolution above defined what happens to a
row that fails to pair *given* §11's then-current pairing architecture
(option B). This paragraph correctly anticipated that "if the Owner
later selects §11.1's fork (ii), 'unmatched' may need to be redefined"
— see §17.1 below for that redefinition, now that §11.2 has made that
selection.

### 17.1 Owner Decision Closure Round 2 — AMENDMENT, not reversal

Identical treatment and identical reasoning to §16.1: a Receive event
with no deterministically identifiable Issue counterpart is no longer,
by itself, an `ERROR`-severity finding — it imports successfully as its
own independent `LegacyEquipmentEvent` (§8.1). Every genuine row-level
validity condition in §15's severity table is unchanged. OD-PR21-2
remains **RESOLVED**; only the pairing-specific "unmatched = `ERROR`"
mechanism is withdrawn as inapplicable under the adopted event-first
architecture (§11.2), for the identical reasons §16.1 states in full.

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

**OD-PR21-5 — PARTIALLY RESOLVED (Owner Decision Closure Round 1):
direction adopted, exact format deferred to PR21A/D.** `transaction_no`
is confirmed `String(30)` NOT NULL, UNIQUE, indexed
(`backend/app/models/transaction.py`, re-verified this round — §12),
normally sequence-generated. The Owner has accepted the recommended
**direction**: PR21 must **not** generate a normal contemporary
live-format `transaction_no` for imported history — doing so would
imply the transaction occurred in the current system today. Instead:

- The legacy `เลขที่ใบส่ง`/`เลขที่ใบรับเครื่อง` order references are
  preserved as source references (§8, §26) — this is unconditional and
  does not depend on the rest of this decision.
- An internal historical transaction identity (the row's own UUID
  primary key, already present on every `BorrowTransaction`) is
  sufficient for database identity — `transaction_no` does not need to
  *be* the identity, only to satisfy the existing NOT NULL/UNIQUE
  constraint.
- `transaction_no` itself is populated only with a value from a
  **clearly segregated LEGACY namespace** (e.g. a deterministic,
  visually-distinguishable prefix), never a value indistinguishable from
  a live-generated one.

**Round 1's open remainder was the exact `transaction_no` namespace/
prefix format** (never decided, deferred to PR21D). Round 1 phrased
this as blocking PR21D specifically, because at that time PR21 still
assumed legacy history would eventually populate a real
`BorrowTransaction.transaction_no` (§11's then-current option (B)).

### 20.1 Owner Decision Closure Round 2 — RESOLVED for PR21 V1's actual scope

**§11.2 (event-first, adopted this round) removes the premise Round 1's
open remainder depended on.** `LegacyEquipmentEvent` (§8.1) is the
artifact PR21 V1 actually writes, and it has **no `transaction_no`
column at all** — that column exists only on `BorrowTransaction`, which
PR21 V1 does not write to (§12). Applying Round 1's already-resolved
direction to the model PR21 V1 actually uses:

- `legacy_order_reference` (§8.1) preserves the exact legacy
  `เลขที่ใบส่ง`/`เลขที่ใบรับเครื่อง` value as business-reference
  provenance — unconditional, unchanged from Round 1.
- `LegacyEquipmentEvent.id` (internal UUID) is the database identity —
  unconditional, unchanged from Round 1.
- No contemporary-looking, live-format number is ever generated for a
  `LegacyEquipmentEvent` — there is no column that would require one.

**OD-PR21-5 is therefore RESOLVED for PR21 V1's actual scope.** The
narrower question Round 1 left open — the exact LEGACY-namespace
`transaction_no` format — does not arise in V1 at all, because V1 never
populates that column. **This is not the original open question
answered; it is the original open question becoming moot** because the
architecture that would have needed it (paired `BorrowTransaction`
rows, §11's superseded option (B)) is no longer what PR21 V1 builds.
**What remains, precisely:** if a future PR22-or-later reconciliation
step ever chooses to materialize a real `BorrowTransaction` row for a
confirmed, deterministically-linked Issue/Receive pair (§11.2's PR22
boundary), *that* step would need to decide a `transaction_no` value at
*that* time, using Round 1's already-resolved direction (never
contemporary-looking; clearly segregated LEGACY namespace) as its
starting point — this is explicitly out of PR21 V1's own scope and is
not decided here. **Mandatory STOP condition** (§52) fully closed for
PR21 V1: no column on the artifact PR21 V1 actually writes
(`LegacyEquipmentEvent`) requires a value this document has not already
resolved how to supply.

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
to aware UTC is mandatory before any row is written.

**Source Evidence Update.** Direct inspection confirms the canonical
sheets store `วันที่` (date) and `เวลา` (time) as **separate native
Excel date/time cells** (read back by `openpyxl` as Python
`datetime.datetime`/`datetime.time` objects, not text strings) — a
parser combines the two per row into one timestamp. **Still open, not
guessed:** the workbook's date/time values carry no embedded timezone
information (Excel date/time cells are inherently timezone-naive) — the
working assumption remains Asia/Bangkok (consistent with the existing
Day/Night shift boundaries), pending explicit Owner confirmation, since
this design does not assume hospital operational timezone without it.
Seconds precision is present (`เวลา` values observed to the second,
e.g. `datetime.time(0, 28, 55)`). No malformed timestamps were
encountered in the sampled rows, though this is not an exhaustive
full-dataset validation pass. **Ambiguous dates are never interpreted
heuristically**; malformed timestamps are `ERROR` findings (§15).

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

**Corrected checksum semantics.** Verified against the actual schema
(`backend/app/models/import_session.py:125-141`):
`checksum: Mapped[str] = mapped_column(String(128), nullable=False)`,
with `Index("ix_import_sources_checksum", "checksum")` — **a regular
index, not a unique constraint.** A new `ImportSession` can register the
same file/checksum again; nothing in the database prevents it.
`ImportSource.checksum` provides source integrity/fingerprint and
comparison evidence — **it does not provide database-enforced global
replay prevention.**

**Stable historical event identity must not be `ImportSource.id` +
`row_number`.** That identity is only stable inside one exact source
artifact — a corrected/canonical export can shift row numbers, reorder
rows, or contain the same historical event registered under a brand-new
`ImportSource`. This must be a **database-enforced** identity, not an
assumption.

**Candidate stable identity fields:** an AppSheet row key, a
transaction/reference ID, an event UUID, or another immutable source
record identifier. **None of the following are acceptable as a
universal event identity without explicit source evidence:** timestamp
alone; equipment + timestamp alone; row number alone; checksum + row
number alone.

**Source Evidence Update — strong candidates found, not yet fully
confirmed.** Direct inspection of the canonical sheets (§6.1, §6.2)
found two concrete candidates, verified by direct uniqueness/integrity
checks, not assumed:

- **Order-level identity:** `เลขที่ใบยืม`/`เลขที่ใบคืน` (the order/slip
  number on `Orders ยืมเครื่อง`/`Orders คืนเครื่อง`) is **100% unique**
  within its sheet — verified by direct count (5,685 distinct values
  for 5,685 non-null Issue-order rows; 6,158 for 6,158 Receive-order
  rows) — and functions as a real business document number (values like
  `Borrow1000000009210`, `Return100000009892`), not an
  AppSheet-internal artifact.
- **Row-level identity:** the `ลำดับ` column on
  `ข้อมูลส่งเครื่องมือ`/`ข้อมูลรับเครื่องมือ` (line items) holds an
  8-character hex-like string (e.g. `b7f7169c`) rather than the
  sequential number its Thai label ("sequence/order number") would
  suggest — consistent with an AppSheet auto-generated row key. Verified
  **100% unique among non-null values, within its own sheet**
  (19,871/19,871 distinct for Issue; 19,750/19,750 for Receive), but
  **not fully populated**: 41 of 19,912 Issue rows and 18 of 19,768
  Receive rows have a blank `ลำดับ` — a validation-finding case (§15),
  not silently skippable. **This row-key-uniqueness figure is a
  different metric, on a different basis, from §6.2's distinct-
  reference-resolution figures (5,676/5,677 Issue, 6,141/6,141
  Receive) — the two must never be read as the same denominator.**

**Still not fully resolved, and not claimed as such:** (a) whether this
row key is AppSheet's genuinely stable, re-export-durable identifier, or
one that could be regenerated on a future export, cannot be determined
from a single snapshot — that requires either explicit Owner
confirmation of AppSheet's row-ID behavior, or comparing two exports
taken at different times, neither of which this document fabricates;
(b) the ~0.2% blank-`ลำดับ` rows need an explicit policy (fall back to
order-number + line-position? blocking `ERROR`? — not decided here).
**This is not invented as a resolved hash identity** — it is reported as
strong, verified, positive evidence, with the specific remaining
confirmation named precisely, per this task's own instruction not to
invent an identity without explicit reviewed design. Folded into
OD-PR21-0 (§45). This event-identity work belongs to a later,
source-dependent implementation slice — **not** to PR21-Foundation
(§46's H5 clarification).

### 24.1 Owner Decision Closure Round 1 — interim evidentiary policy adopted, identity itself still OPEN

Four ways this document could treat `ลำดับ` were evaluated: **(A)**
treat it as an immutable AppSheet/source row key outright; **(B)** use a
composite identity involving the order/slip reference; **(C)** generate
a fingerprint from multiple source fields; **(D)** require explicit
re-export stability evidence before choosing among (A)-(C).

**This round explicitly does not choose (A), (B), or (C).** Uniqueness
within one workbook snapshot (verified: 19,871/19,871 Issue,
19,750/19,750 Receive non-null values, zero duplicates — §24 above) is
evidence of *uniqueness*, not of *durability across a corrected/
re-exported file* — the two are different claims, and this document has
already stated (§24 above) that durability is unconfirmed. No Owner
evidence resolving AppSheet's row-ID re-export behavior was supplied to
this round.

**Adopted this round: interim policy (D), as the explicit default.**
Until one of the following is supplied, `ลำดับ` (alone or in any
composite) may **not** be approved as PR21's database-enforced stable
event identity, and no PR21 implementation slice may encode a unique
constraint on it as if it were durable:

- explicit Owner confirmation of AppSheet's row-ID behavior across a
  corrected/re-exported file (i.e., a business/vendor-level statement
  that this key does not regenerate on re-export), **or**
- direct comparison of two exports of the same underlying data taken at
  different times, showing the same historical events retain the same
  `ลำดับ` values.

This is a decision **about the evidentiary bar**, adopted as explicit
Owner-endorsed default policy this round — it is not a decision that
resolves the underlying factual question of whether `ลำดับ` is durable,
which remains genuinely unknown and is not guessed here. **OD-PR21-0's
event-identity sub-component therefore remains OPEN** (§45, §53);
PR21B/C/D may not proceed past this point until (D)'s evidentiary bar is
met and the Owner then makes an explicit (A)/(B)/(C)-style choice based
on it.

### 24.2 Owner Decision Closure Round 2 — RESOLVED FOR PR21 V1: frozen migration snapshot, migration-authority-scoped identity

**PR #102 fix round correction.** The revision below corrects a gap
found during independent review of this section's first draft: the
original draft's database-uniqueness tuple, `(dataset_type,
legacy_source_row_key)`, said nothing about *which* Owner-approved
snapshot it was scoped to — read on its own, it silently drifted toward
implying `legacy_source_row_key` (`ลำดับ`) is unique in some general,
durable sense, which is exactly the claim this document has never had
evidence for and has repeatedly disclaimed (§24, §24.1). This round
names the missing scope explicitly as `LegacyMigrationAuthority` and
folds it into the identity tuple. **This is a correction to this
section's own not-yet-merged text, not a reopening of the Owner
Decision it resolves** — see the closing paragraph below.

**§24.1's interim policy (D) required re-export stability evidence
before approving `ลำดับ` as durable. No such evidence has been
supplied.** This round does not manufacture it. Instead, it resolves
the underlying *architectural* question a different way: PR21 V1 does
not need `ลำดับ` to be durable *across arbitrary future exports* if
PR21 V1 is scoped, by explicit Owner decision, to import from exactly
**one** frozen, immutable, already-inspected workbook snapshot.

**Migration authority — the governance identity this tuple was missing.**
§24.1 and PR21 V1's whole approach scope `ลำดับ`'s uniqueness to "the
Owner-approved frozen snapshot," but that scope needs its own name and
its own identity if a database constraint is going to enforce it
correctly. This round introduces **`LegacyMigrationAuthority`**: a
governance-level identity representing *one* Owner-approved historical
migration source, immutably bound to the workbook checksum that source
was approved against.

**`LegacyMigrationAuthority` is a design concept only in this round —
no table, ORM model, migration, or API is added here.** Its exact
physical shape is PR21A's own implementation-grade work, exactly like
`LegacyEquipmentEvent`'s own schema (§8.1). Conceptually:

- `id` — internal identity, referenced by every `LegacyEquipmentEvent`
  row imported under this authority (§8.1's new `migration_authority_id`
  field).
- `approved_workbook_sha256` — the Owner-approved snapshot's checksum
  (`8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c`
  for PR21 V1, §6) — set once, at approval, and **immutable**
  afterward.
- `approved_at` / an explicit governance-approval reference — recorded
  once, never altered.
- A scope/dataset marker (e.g. "PR21 legacy history V1") — distinguishes
  this authority from any later, separately-approved migration
  authority a future correction, or a different historical dataset,
  might introduce.

**Why this is not `ImportSource.id`.** `ImportSource` (§7, §26)
identifies one *technical upload artifact* — a fresh row in
`import_sources` for every upload, including a retried upload of the
exact same bytes (§24: checksum is a regular index, not a unique
constraint, so re-registration is not prevented or detected there).
`LegacyMigrationAuthority` identifies the *business/governance
approval* behind a migration — the Owner's decision to treat one
specific, already-inspected workbook as PR21 V1's authoritative
historical source. These must stay separate identities: a retried
upload of the same approved workbook is a **new** `ImportSource` row
but the **same** migration authority, because it is the same approved
historical fact being re-submitted, not a new one. Substituting
`ImportSource.id` for the authority would make same-file retries look
like unrelated migrations and break the idempotency guarantee below.

**Two identity levels, kept strictly separate (never conflated):**

- **Level 1 — import-artifact row provenance:**
  `(import_source_id, sheet_name, source_row_number)`. This identifies
  *where in one specific uploaded artifact* a claim came from. It is
  **not** durable across a re-upload of the same or a corrected file —
  re-registering the same bytes under a new `ImportSource` changes this
  tuple even though the underlying historical fact is unchanged (§24's
  own finding: `ImportSource.checksum` is a regular index, not a unique
  constraint). Retained for audit/debugging; never the logical identity.
- **Level 2 — durable logical historical event identity, scoped to one
  migration authority:** `(migration_authority_id, dataset_type,
  legacy_source_row_key)` — i.e. `(migration_authority_id, dataset_type,
  ลำดับ)` — identifies one historical event **within the one
  Owner-approved migration authority that imported it, and nowhere
  else.** `legacy_source_row_key` (`ลำดับ`) alone, without the
  authority component, is never treated as unique or durable — see
  below.

**The resolved Owner Decision, stated with the precision this round's
own instruction requires:**

> Stable event identity for PR21 V1 is resolved by scoping the
> migration to one immutable `LegacyMigrationAuthority`, bound to the
> Owner-approved workbook snapshot's checksum (SHA-256
> `8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c`,
> §6). Within that one authority, `(migration_authority_id, dataset_type,
> source row key ลำดับ)` identifies an event. `ลำดับ` is not, on its
> own, claimed unique or durable outside its owning authority —
> cross-export durability of the source row key remains unproven and is
> outside automatic PR21 V1 replay semantics.

**This is deliberately not the same claim as "`ลำดับ` is a proven
globally stable AppSheet key."** That claim remains unsupported by
evidence and is not made anywhere in this document. What *is* resolved
is narrower and fully supported by evidence already in hand: within
one fixed, already-inspected, checksum-bound file, the key is 100%
unique among non-null values (§24: 19,871/19,871 Issue, 19,750/19,750
Receive) — sufficient for a database-enforced uniqueness constraint
scoped to that one migration authority, without needing to assume
anything about a future export this document has never seen. The
`migration_authority_id` component is exactly what keeps that
constraint properly scoped: it is a uniqueness claim about *this one
approved migration*, never a claim about `ลำดับ` in general.

**Full provenance is still persisted regardless** (§8.1, §26) —
`migration_authority_id`, `import_session_id`, `import_source_id`,
source checksum, sheet/row — the frozen-snapshot policy narrows what
the *logical identity* may rely on, it does not reduce what is
recorded.

**Corrected/re-exported workbook policy (fail-closed).** After PR21 V1's
migration executes under its approved `LegacyMigrationAuthority`, a
workbook with a **different** SHA-256 must **never** be silently
attached to that same authority:

- Automatic re-import **under the existing `migration_authority_id`**
  is **rejected** — that authority's approved checksum is immutable
  (above), so a different checksum cannot be absorbed by it; it is a
  structurally different artifact, not a same-migration retry.
- Any correction to already-imported history requires an **explicit**
  correction/reconciliation workflow, which must mint a **new or
  explicitly superseding** `LegacyMigrationAuthority` for the corrected
  workbook — owned by PR22 or a later, separately-scoped correction
  slice, never by silently re-running PR21 V1 against a new file under
  the existing authority.
- Original imported provenance and events are **never** silently
  overwritten by a later import attempt, regardless of checksum or
  which authority it claims to belong to.

**Same-file replay (idempotency), stated precisely.** The **same**
exact approved artifact — identical SHA-256, submitted again under the
**same** `migration_authority_id` (whether via the same `ImportSource`
row or a fresh one created by a retried upload — §24's own finding
that checksum registration is not itself unique means a retry can
freely create a new `ImportSource`) — **must** be safe: re-running the
migration must never create duplicate `LegacyEquipmentEvent` rows. The
database-level mechanism (PR21A/D's own implementation-grade work, not
fixed here) is expected to enforce uniqueness on
`(migration_authority_id, dataset_type, legacy_source_row_key)`
**without** including the source checksum or `ImportSource.id` directly
in that uniqueness scope — deliberately, so that:

- a retried upload of the identical workbook (new `ImportSource`, same
  `migration_authority_id`, same checksum) collides safely against the
  already-imported rows and creates nothing new — true idempotent
  replay; and
- a *different* (corrected) workbook — which, by the policy above,
  cannot be attached to the existing `migration_authority_id` at all —
  is rejected at the authority-assignment step, before it could ever
  reach this uniqueness constraint disguised as a same-authority "new"
  event under a different checksum.

Coupling uniqueness directly to the raw checksum instead of to
`migration_authority_id` was considered and rejected: a checksum is an
artifact-storage property, not a domain identity, and binding
uniqueness to it directly would re-couple the logical event identity to
file representation — exactly the coupling `LegacyMigrationAuthority`
exists to remove (above). Relying solely on an application-layer
pre-check (a `SELECT` before `INSERT`) is insufficient on its own —
§25's existing requirement for a database-enforced identity, not an
assumption, is unchanged and directly reused here.

**Blank-`ลำดับ` source rows.** The evidence manifest records blank row
keys among otherwise-structural rows: 41 of 19,912 Issue rows, 18 of
19,768 Receive rows (§24). This round classifies the required treatment
using existing manifest evidence only, without re-inspecting the raw
workbook:

- A **data-bearing** source row (one that otherwise carries real
  business fields — equipment identity, ward, timestamp, etc.) that
  lacks its required `ลำดับ` key is an `ERROR`-severity validation
  finding (§15) — the whole session becomes `validation_failed`. **No
  identity is ever synthesized** for such a row (e.g. falling back to
  order-number-plus-line-position) — that would be inventing a Level-2
  identity component this document has not approved.
- A **pure blank/formatting** row (a trailing or structural blank with
  no business data at all — the pattern already distinguished elsewhere
  in this evidence base, e.g. the SDC sheets' own trailing-blank-block
  finding, §6.1) is ignored structurally — it is never a data-bearing
  row in the first place, so it never reaches the identity requirement
  above. Which specific blank rows fall into which category is
  implementation-grade parsing work for PR21B/C, not decided here.

**OD-PR21-0's stable-event-identity sub-component is therefore
RESOLVED FOR PR21 V1** (§45) — narrowly, on the terms stated above, not
as an unqualified global claim. **This correction does not reopen that
resolution.** The underlying decision — PR21 V1 does not need `ลำดับ`
to be durable across arbitrary future exports, because V1 is scoped to
one frozen, Owner-approved snapshot — is unchanged from the original
draft of this section. What changes is only the precise shape of the
database-enforced tuple that implements it: `migration_authority_id` is
now an explicit scoping component, rather than leaving that scope
implicit in a bare `(dataset_type, legacy_source_row_key)` tuple that
was mis-readable as a global claim.

---

## 25. Duplicate detection and re-import / idempotency (corrected-export policy)

Three cases this design distinguishes:

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

Other cases, unchanged: duplicate ISSUE/RECEIVE row within one file
(§15 `ERROR`, in-workbook duplicate); duplicate against already-imported
legacy history (a database check against already-*executed*
transactions, not just already-uploaded sources); mapping changes after
an earlier dry-run (Ward/BME mapping added later) — per PR20's
persisted-plan immutability contract, a changed mapping supersedes the
prior plan and requires a fresh dry-run, never an in-place mutation.

---

## 26. Source traceability design

Every imported transaction must be traceable back to its exact source
row via §8's provenance refs: `ImportSession.id`, `ImportSource.id`,
`ImportSource.checksum`, sheet/tab identifier, source row number, and
source reference/event ID if present. Normalized provenance is
sufficient — no unnecessary full raw-row dump — consistent with PR19A's
redaction policy (§38).

---

## 27. Historical vs. live transaction separation

**Key invariant, restated under the adopted event-first architecture
(§8.1, §11.2):** legacy records are historical, immutable, and — unlike
this section's original framing below (preserved for record) —
structurally cannot participate in live operational commands at all,
since `LegacyEquipmentEvent` is not a `BorrowTransaction` row. A live
receipt or live dispatch can never touch a `LegacyEquipmentEvent`
regardless of any application-layer check, because no live code path
reads or writes that table.

**Historical framing (accurate under §11's original, now-superseded
option (B); preserved for record):** a live receipt cannot accidentally
close an imported historical `CLOSED` transaction (`close()` requires
`status='open'`); a live dispatch is not blocked by a legacy historical
record unless an explicit current `OPEN` state was intentionally
imported under an approved policy. This reasoning assumed legacy
records were `BorrowTransaction` rows — under §8.1's adopted model, the
question does not arise in the first place.

No `source_kind` (`LIVE`/`LEGACY_IMPORT`) column is added to
`BorrowTransaction` — moot under event-first, since legacy records
live in their own table (`LegacyEquipmentEvent`) and are never rows in
`borrow_transactions` to begin with.

### 27.1 Owner Decision Closure Round 2 — intended unified read-model behavior (documented, not designed)

The "unified transaction history" requirement (§1) is satisfied at the
**read** layer, not by writing legacy events into `borrow_transactions`.
Transaction History may eventually present one chronological timeline
blending: live `BorrowTransaction` activity, and legacy `ISSUE`/
`RECEIVE` events (§8.1) — merged at query time (e.g. a read-time
union/federated query across the two tables), never by materializing
legacy events as `BorrowTransaction` rows. Such a timeline does not
pretend every legacy `ISSUE` is known to pair with a `RECEIVE`, or vice
versa (§11.2) — each event is presented as exactly what the source
states, labeled distinctly as legacy history. **This is intent only:**
no frontend design, no read-model schema, no query implementation is
performed by this document (§28 of this round's own scope guard) — the
backend (and, within it, whichever table actually holds the durable
fact) remains the sole source of truth; a future read-model slice
designs the actual query/API.

---

## 28. Dry-run contract

Per §15's all-or-nothing gate, any blocking `ERROR` anywhere in a
validation batch means the session becomes `validation_failed` and **no
`DryRunPlan` is created at all** — not a plan containing only the
passing rows, and not a plan that also carries the blocked rows for
visibility. A `DryRunPlan` therefore only ever exists for a session
whose validation snapshot passed with **zero** blocking `ERROR`
findings.

**Conceptual flow (restated precisely, no exceptions):**

```
parse
  -> validate all rows -> findings + counters

IF any ERROR finding exists anywhere in the batch:
    session -> validation_failed
    findings remain exposed via the validation-findings result/endpoint
    STOP -- no DryRunPlan is created

ELSE (zero ERROR findings; WARNING findings may still exist):
    session -> validated
    dry-run is admitted
    the resulting DryRunPlan contains only rows drawn from this
    fully-passing snapshot, plus non-blocking WARNING context
    attached to those rows (e.g. an unknown BME name pending later
    mapping, §13) -- never a row that failed validation
```

**Dry-run summary contract.** The persisted plan's summary may report
only rows/counts that survived validation: issue events accepted,
receive events accepted, historical transactions planned (paired per
§11), non-blocking warning counts, and no-op/skip categories only if a
later slice's design explicitly defines one. **It must never include a
"blocked ERROR rows" category** — there is no such category, because a
batch containing any `ERROR` never produces a plan. If the frontend
needs to show validation errors to the operator, it reads the
validation-findings result for that session (already exposed by PR19's
existing validate-phase contract), never the dry-run plan — the two are
different artifacts for different states (`validation_failed` vs.
`validated`/`dry_run_completed`).

PR19/PR20's persisted-plan *pattern* (immutable header + rows,
`active`/`superseded`/`consumed`/`failed` lifecycle, explicit confirm
gate) is reused; the concrete tables are PR21-owned (§36), since the
existing `EquipmentMasterDryRunPlan`/`Row` tables are upsert-oriented
(`action IN ('CREATE','UPDATE','SKIP')`, `target_equipment_id`,
`expected_equipment_version`) and do not fit an insert-oriented
transaction import. No `borrow_transactions` row is ever written during
dry-run, via PR19's existing `READ ONLY` transaction enforcement.

---

## 29. Generic persisted-plan API architecture (H4) — PR20 static-route compatibility is mandatory

**Verified: the current PR20 GET/confirm endpoints are hardcoded to
Equipment Master, not a generic import-session plan API.**
`backend/app/crud/import_dry_run_plan.py` imports and operates on
`EquipmentMasterDryRunPlan`/`EquipmentMasterDryRunPlanRow` by concrete
type in every function (`get_current_plan`, `list_plan_rows`,
`confirm_plan`, etc. — lines 12, 32-234). `backend/app/api/v1/import_sessions.py`'s
`GET /{session_id}/dry-run-plan` (line 328,
`response_model=DryRunPlanOut`) and
`POST /{session_id}/dry-run-plan/{plan_id}/confirm` (line 388,
`response_model=DryRunPlanConfirmOut`) call this CRUD module directly,
with FastAPI's static, decorator-declared `response_model` on each route
— the mechanism that generates PR20's OpenAPI schema and enforces its
response shape today.

**Fix Round 3 (PR98-H4R2) correction — a dynamically dataset-typed
response on the existing route is not implementable and is rejected.**
Fix Round 2's "dispatches to a per-dataset-type provider, returning one
of `DryRunPlanOut` / `LegacyHistoryDryRunPlanOut` selected by
`dataset_type`" direction described a response shape FastAPI's static
`response_model` mechanism cannot express without either (a) a
`Union[DryRunPlanOut, LegacyHistoryDryRunPlanOut]` response model — which
changes the generated OpenAPI schema for the *existing, already-shipping*
PR20 route and is rejected (§31) — or (b) an untyped/`Any`/`dict`
`response_model=None` escape hatch, which this design also rejects
(§31) since it would silently drop PR20's current response-schema
guarantee. Both options were live/undecided in the prior revision; this
round selects and commits to exactly one architecture, corrected below.

**Selected architecture: the existing PR20 routes are never touched;
PR21 gets its own new, separately and statically typed routes later.**
Foundation generalizes only the **internal service/provider layer**
behind the existing routes — never their public `response_model` or
path. Concretely:

```
EXISTING, UNCHANGED (PR20):
GET  /import-sessions/{session_id}/dry-run-plan
       response_model=DryRunPlanOut            -- byte/field/OpenAPI unchanged
POST /import-sessions/{session_id}/dry-run-plan/{plan_id}/confirm
       response_model=DryRunPlanConfirmOut      -- byte/field/OpenAPI unchanged
   |
   +--> (internally, optionally) a thin compatibility service/provider
        wrapping the existing import_dry_run_plan_crud calls -- purely
        an internal refactor, invisible on the wire (§30)

NEW, ADDED LATER (PR21, source-dependent, not this PR, not Foundation):
GET  /import-sessions/{session_id}/legacy-history/dry-run-plan
       response_model=LegacyHistoryDryRunPlanOut   -- PR21's own schema
GET  /import-sessions/{session_id}/legacy-history/dry-run-plan/{plan_id}/rows
       response_model=<PR21 paginated row schema>
POST /import-sessions/{session_id}/legacy-history/dry-run-plan/{plan_id}/confirm
       response_model=LegacyHistoryDryRunPlanConfirmOut
```

Exact PR21 paths are illustrative and may be finalized to match
repository conventions when PR21B/C/D are actually designed in detail —
the binding contract is: PR20's existing routes and schemas are
untouched; PR21's routes are new, separate, and use PR21-specific static
response models; both may share generic provider/service internals
(§30); FastAPI's OpenAPI schema remains fully, statically typed
throughout, with no dynamic dispatch of `response_model` at runtime.
This mirrors the pattern already established for parse/validate/execute
via `register_adapter()`/`get_adapter()` (`import_adapter.py:285-295`)
at the **internal service layer only** — that registry pattern was never
about the public HTTP response shape, and this design does not extend it
to be. This requires real, non-trivial, independently-reviewable work on
shared PR19/PR20 infrastructure (the internal compatibility layer),
recorded as its own proposed implementation slice ("PR21-Foundation,"
§46), not something PR21A gets for free.

---

## 30. Generic provider interface (internal only — never owns `response_model`)

Internal service-layer contract (exact names may differ to match
repository conventions; this is the conceptual shape):

```
DryRunPlanProvider (per dataset_type)
  - load_plan(session_id) -> provider-owned plan identity/state
  - load_plan_rows(session_id, plan_id, cursor, limit) -> provider-owned rows
  - confirm_plan(session_id, plan_id, actor) -> ConfirmPlanResult (§35)
  - redact_plan_artifacts(session_id) -> retention hook (§38)
  - execute_plan(...) -- owned by §37's execution contract, not this
    interface directly
```

**Fix Round 3 (PR98-H4R2) clarification: this interface is strictly
internal.** It exists to let Equipment Master's route handler and (once
built) PR21's own route handlers share business logic — it never
selects or owns a FastAPI `response_model`. Each route's own decorator
still declares its own static, concrete response model (§29); a
provider's return value is mapped to that route's own response schema
inside that route's own handler, never dispatched dynamically by the
provider itself.

Provider selection is based on `ImportSession.dataset_type`, via the
same registration mechanism already used for adapters
(`register_adapter()`/`get_adapter()`) — but only for internal
service-layer wiring, never for HTTP response typing.

- **Equipment Master provider:** a thin, internal wrapper around the
  existing `import_dry_run_plan_crud` functions and
  `EquipmentMasterDryRunPlan`/`Row`. The existing PR20 routes may
  continue calling `import_dry_run_plan_crud` directly (no behavior
  change required), or call through this wrapper if useful for
  code-sharing — either way, `DryRunPlanOut`/`DryRunPlanConfirmOut`/
  `DryRunPlanRowOut` are returned **exactly as they exist today**,
  unchanged, by PR20's own unchanged route handlers.
- **PR21 provider:** added later, wraps PR21's own plan/row tables
  (§36) — used exclusively by PR21's own new routes (§29), returning
  PR21-specific schemas (§32).

**Do not force both datasets into one lossy common DTO** — PR20's row
shape (`action IN ('CREATE','UPDATE','SKIP')`, `target_equipment_id`,
`expected_equipment_version`) has no meaningful PR21 equivalent (§28);
attempting a shared row schema would either drop PR20 fields or add
meaningless nullable fields to PR21's rows. Separate routes with
separate static response models (§29) exist precisely so each dataset
owns its own response shape without this problem ever arising.

---

## 31. Public API strategy — statically typed routes per dataset, no dynamic dispatch

**Selected, per PR98-H4R2: static routes, not a union or dynamic
response type on one shared route.**

- **PR20's existing route is not touched.** `GET .../dry-run-plan`
  keeps `response_model=DryRunPlanOut` exactly as declared today; `POST
  .../confirm` keeps `response_model=DryRunPlanConfirmOut` exactly as
  declared today. Path, HTTP semantics, response body field names,
  field nullability, enum/status values, pagination semantics, and the
  generated OpenAPI schema are all unchanged (§29).
- **PR21 gets its own, separate, statically-typed routes**, added when
  PR21's source-dependent implementation is ready (illustrative paths
  in §29) — never a change to PR20's route.

**Why not a union on the existing PR20 route.** `Union[DryRunPlanOut,
LegacyHistoryDryRunPlanOut]` as the existing route's `response_model`
was considered and is explicitly rejected: it changes the generated
OpenAPI schema for a route the production PR20F frontend already
depends on, and risks breaking that already-reviewed contract for no
benefit — PR21 does not need to share PR20's route to have its own
correctly-typed API. **Likewise rejected as compatibility workarounds:**
`Any`, untyped `dict`, or `response_model=None` on either route — all
of them would silently discard FastAPI's response-schema guarantee and
degrade PR20's existing, already-relied-upon OpenAPI documentation.

**Net effect:** transport (route + `response_model`) stays statically
typed and dataset-specific; only the internal provider layer (§30) is
generic. No FastAPI route ever dynamically switches its declared
response type at runtime.

---

## 32. Plan and plan-row contract shape

**Internal invariant (never exposed as renamed wire fields):**
exact-plan identity is always the pair (`ImportSession.id`,
plan's own `id`) — the same pair `DryRunPlanOut.import_session_id` +
`DryRunPlanOut.id` already represent today; never inferred as "the
latest plan."

**PR20 (Equipment Master):** `DryRunPlanOut`/`DryRunPlanRowOut`/
`DryRunPlanSummaryOut`/`DryRunPlanConfirmOut` remain **exactly as
verified in §29** — no field added, renamed, or removed by this design.

**PR21 (new `LegacyHistoryDryRunPlanOut`/`LegacyHistoryDryRunPlanRowOut`,
exact final names TBD in PR21A):** mirrors the same overall shape
(`id`, `import_session_id`, `status`, `is_current`-equivalent,
`created_at`, `confirmed_at`, `confirmed_by_user_id`, a summary object,
paginated rows, cursor) but with PR21-specific row fields instead of
Equipment Master's upsert-oriented ones — historical transaction
action/category (§28's `IMPORT_OPEN`/`IMPORT_CLOSED`/`SKIP`),
issue/receive source refs (§8), mapped Ward, legacy BME display text
(§13), source timestamps, and non-blocking warning indicators (§15).
These are additive, PR21-owned fields on a PR21-owned schema — **not**
added to `DryRunPlanRowOut` itself.

---

## 33. Pagination contract

Cursor pagination with a validated limit; cursor binds to the exact
plan it was issued for. Since PR20 and PR21 use separate routes (§29,
§31), a cursor is naturally scoped to the route/provider that issued
it; internally, the provider's own `load_plan_rows` still validates the
cursor against its own plan ID defensively (a cursor issued for one
provider's plan rejected if somehow presented to another's lookup, not
silently reinterpreted). A malformed cursor returns a structured client
error. No unbounded/thousands-of-rows single response — matches PR20's
existing `list_plan_rows` cursor-pagination shape
(`import_dry_run_plan.py:222-234`) for Equipment Master, unchanged;
PR21's provider implements the equivalent contract for its own rows.

---

## 34. Missing / foreign / stale plan semantics

Preserves PR20's existing, already-verified semantics
(`backend/app/api/v1/import_sessions.py:328-425`) for Equipment Master
unchanged, and PR21's provider adopts the identical security semantics
(no documented reason to diverge):

- **READ** (`GET .../dry-run-plan`): missing/never-existed plan → `404
  IMPORT_DRY_RUN_PLAN_NOT_FOUND` (verified: `import_sessions.py:339-342`).
- **CONFIRM** (`POST .../confirm`): `404` only for an unknown session id;
  missing plan, foreign-session plan, or superseded/stale plan all
  unify to `409 IMPORT_DRY_RUN_PLAN_STALE` (verified:
  `import_sessions.py:407-425` docstring). No foreign-plan existence is
  ever leaked through a distinct error shape.

**Provider layer must not expose whether a foreign plan exists** — the
generic transport's unified error responses are what the caller sees;
a provider's internal lookup failure for a foreign-session plan must
produce the same `409 IMPORT_DRY_RUN_PLAN_STALE` the transport already
returns for every other stale/missing case, not a distinct signal.

---

## 35. Confirmation RBAC / audit — exactly once per first successful confirmation

**RBAC:** Administrator-only, via the existing
`require_roles(*ADMINISTRATOR_ONLY_ROLES)` dependency already applied to
every import-session endpoint including confirm (verified:
`import_sessions.py:394`) — enforced identically on both PR20's existing
route and PR21's future route (§29, §31), each declaring the dependency
itself since they are separate routes, not a shared dispatch point. No
new permission contract invented.

**Fix Round 3 (PR98-H4R3) correction — audit is written exactly once
per first successful confirmation, not once per confirm HTTP call.**
The prior revision's "invoked exactly once per confirm call" was wrong.
Verified against the actual runtime
(`backend/app/crud/import_dry_run_plan.py:252-259, 262-376` and
`backend/app/api/v1/import_sessions.py:388-452`):

- `import_dry_run_plan_crud.confirm_plan()` returns a
  `ConfirmationResult` dataclass carrying `plan` and a `newly_confirmed:
  bool` flag. Its own docstring (lines 280-283) states the contract
  precisely: a repeat confirm must "return the persisted row as-is
  (`newly_confirmed=False`), never re-attributing `confirmed_by_user_id`
  to a later caller."
- The route handler's own docstring (`import_sessions.py:431-436`)
  states it explicitly: *"The `CONFIRMED` audit event is written only
  when `result.newly_confirmed` — a repeat confirm (same user retry, a
  second user's idempotent re-confirm, or a network retry after a lost
  response) is reported as the same success but never produces a second
  audit row, and never re-attributes the persisted
  `confirmed_by_user_id` away from the original first confirmer."*
- The code matches exactly: `if result.newly_confirmed: await
  record_audit_event(...)` (`import_sessions.py:442-452`) — no `else`
  branch writes anything.

**Generic `ConfirmPlanResult` contract, required for any provider
(Equipment Master's existing one and PR21's future one) — conceptual
shape, exact DTO names may differ:**

```
ConfirmPlanResult:
  - plan                    -- the current, persisted plan state
  - newly_confirmed: bool
  - confirmed_at             -- the ORIGINAL first-confirmation timestamp
  - confirmed_by_user_id     -- the ORIGINAL first confirmer's identity

First successful confirm (atomic CAS transition wins):
  - newly_confirmed = true
  - confirmed_at / confirmed_by_user_id persisted for the FIRST time
  - caller (transport) writes the confirmation audit event, exactly once

Any subsequent confirm call for an already-confirmed plan (same actor
retrying, a different actor re-confirming, a network-retry replay):
  - newly_confirmed = false
  - confirmed_at / confirmed_by_user_id returned UNCHANGED, exactly as
    originally persisted -- the retrying/second actor is never
    substituted as confirmer
  - caller (transport) writes NO audit event
```

**Concurrent-confirmation race:** two callers racing to confirm the same
plan resolve to exactly one atomic state transition winning (the
existing conditional-`UPDATE` CAS pattern, unchanged); the winner's
result carries `newly_confirmed=true`, every other racer's result
carries `newly_confirmed=false` against the same persisted
`confirmed_at`/`confirmed_by_user_id` the winner produced — never two
audit rows, never two different persisted confirmers, regardless of how
many callers raced.

**Audit ownership — single owner, unchanged split.** The **transport
route handler** owns the conditional audit write (`if
result.newly_confirmed: write audit`), matching exactly where it
happens today. The **provider** owns the atomic confirm CAS/state
transition and the persisted first-confirmer identity — a provider's
`confirm_plan()` **must never** independently write its own audit event;
if it did, a transport-layer write plus a provider-layer write would
double-audit a single first confirmation, which this design forbids.
This is one point of ownership, gated on `newly_confirmed`, never one
audit row per HTTP request.

**Transaction atomicity — preserved exactly from current PR20 runtime,
not redesigned.** `record_audit_event()` flushes only; the caller owns
the commit (§21, `backend/app/core/audit.py:157-189`). In the existing
confirm endpoint, the plan's CAS state transition
(`import_dry_run_plan_crud.confirm_plan()`) and the conditional audit
write share the same request-scoped database session and are committed
together by the endpoint's own transaction boundary — Foundation and
PR21's own provider must preserve this same atomicity (persisted
confirmer identity + conditional audit write committed together, never
as two separate transactions that could diverge on a crash between
them). This is stated as a preserved invariant, not a redesign.

**Stale/foreign-plan security semantics (§34) are unaffected by any of
the above** — a confirm attempt against a stale, missing, or
foreign-session plan still raises before `ConfirmPlanResult` is ever
produced, exactly as today.

---

## 36. Plan persistence ownership decision

**Selected: fully adapter/provider-specific plan tables**, reachable
through the route architecture in §29/§31 (PR20's existing route calling
its existing tables directly or through a thin internal wrapper, §30;
PR21's future route calling its own new tables). This is the same shape
the existing `EquipmentMasterDryRunPlan`/`Row` tables already use (they
are not a shared generic header table today; each provider owns its own
plan tables). PR21 introduces its own header/row tables (§8's provenance
model attaches to the row level), used exclusively by PR21's own future
routes. This preserves: immutable plan, exact plan confirmation (§32),
pagination (§33), provider ownership, retention (§38), execution reuse
(§37), and creates **no PR20 regression** — Equipment Master's existing
route, tables, and response shape are untouched, byte/field unchanged
per §29/§31/§32's verified wire contract.

---

## 37. Execution contract

Reuses PR19's claim, idempotency, lease, heartbeat, fencing, recovery,
audit, and retention mechanisms unmodified (PR19A's own design doc: no
new lease/heartbeat/fencing/recovery code per adapter). PR21's adapter
implements the same `on_execution_success`/`on_execution_failure`/
`on_execution_recovery` hook triple PR20E's design maintains for the
**Job → Session → Plan/sub-resource** lock order
(`equipment_master.py:1496-1536`), applied to PR21's own dry-run-plan
sub-resource (§28/§36). Execution never mutates `Equipment` (§3, §19)
and never invokes live dispatch/receipt transitions (§3). Confirmation
flows through §29-§36's generalized confirm endpoint.

---

## 38. Retention design (M1) — policy, implementation, and fail-closed semantics

**PR19's 180-day retention POLICY is reused unmodified**
(`docs/design/PR19A_LEGACY_IMPORT_FOUNDATION_PLAN.md` §18: 180-day
post-terminal, redact-in-place, `IMPORT_RETENTION_DAYS`-configurable, no
V1 Administrator UI, no legal/manual hold).

**This is not "unchanged" at the implementation level.** Verified:
`backend/app/crud/import_retention.py`'s `redact_session()` explicitly
imports `EquipmentMasterDryRunPlanRow` (line 9) and issues a direct
`update(EquipmentMasterDryRunPlanRow)...` statement against it
(lines 139-140) — it has **no generic/dataset-type dispatch mechanism
today.** PR21's new plan/provenance content (§8, §36) would **not** be
redacted by the existing retention runtime unless extended.

**Selected direction: generic adapter retention hook**, for symmetry
with the existing `ImportAdapter` hook pattern
(`on_execution_success`/`failure`/`recovery`) — each adapter/provider
registers a redaction callback, invoked by `redact_session()` within
the same transaction, rather than `import_retention_service.py` needing
to know every dataset type by name as new ones are added.

**Fix Round 2 (M1) — fail-closed contract.** Retention redaction must
never silently succeed for a session whose dataset-owned artifacts were
not actually confirmed redacted:

```
BEGIN
  -> core import redaction (existing, unchanged: ImportSession/
     ImportSource/ImportRowError fields, per PR19A's existing contract)
  -> provider-specific artifact redaction (the new hook, §above)
  -> verify provider redaction actually succeeded
  -> set retention_purged_at
COMMIT

Any failure anywhere in this sequence (provider missing/unregistered
for a dataset_type that requires provider-owned redaction, provider
callback raises, or provider cannot positively confirm its artifacts
are redacted):
  -> ROLLBACK the entire transaction
  -> retention_purged_at is NOT set
  -> session retention completion is NOT published
  -> artifacts remain eligible for retry on the next retention pass
```

**No partial "purged" marker is ever written.** A session cannot end up
with `retention_purged_at` set while its provider-owned artifacts (e.g.
PR21's plan/provenance tables) remain unredacted.

**Unknown/missing provider registration is a retention failure, not a
silent skip.** For any dataset_type whose provider owns retention-
relevant artifacts, a missing/unregistered provider at redaction time
must be treated as a retryable operational error — never silently
treated as "nothing to redact." If a dataset type genuinely has no
provider-owned artifacts requiring redaction, its provider contract
must **explicitly declare that** (an intentional no-op registration),
rather than the retention runtime inferring it from the absence of a
registration.

**Required invariant, restated precisely:** retention redaction of
provider-owned artifacts **and** `ImportSession` retention-state
advancement (`retention_purged_at`) must be atomic in one caller-owned
transaction, with the fail-closed rollback behavior above — matching
and extending the existing all-or-nothing per-session redaction
transaction `redact_session()` already provides for Equipment Master.

**Corrected summary wording:** *retention policy is unchanged; retention
implementation requires additive PR21 integration (a new fail-closed
adapter retention hook), which is real, non-trivial work — not
automatic reuse, and never a partial or silently-skipped redaction.*

---

## 39. Retention boundary — temporary vs. permanent provenance

**Temporary import artifact retention** (180-day policy, §38) governs
`ImportSession`/`ImportSource`/`ImportRowError`/PR21's own dry-run-plan
tables (§36) — the *import process's* artifacts.

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

## 40. Audit design

Restated from §21/§35: audit records the import actor (`AuditLog.user_id`
via `record_audit_event()`), never the historical operator (which is
business data, §8/§13). Batch/session/source and execution outcome
recorded via the existing `AUDIT_ACTION_IMPORT`/
`AUDIT_ACTION_IMPORT_RECOVERY`/`AUDIT_ACTION_IMPORT_FENCE_LOST`/
`AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CREATED`/
`AUDIT_ACTION_IMPORT_DRY_RUN_PLAN_CONFIRMED` constants
(`backend/app/core/audit.py:48-80`), `entity_type="import_session"`. No
new audit-action constant proposed. Confirmation audit-write ownership
is exactly as specified in §35 — one write, at the transport layer,
gated on `newly_confirmed`, never one write per HTTP request.

---

## 41. Frontend

PR19B already previewed Receive History and Issue History as categories
in the Legacy Import UI (mock/placeholder data). PR21's frontend slice
(PR21E, §46) reuses that existing architecture and replaces the mocks
with real PR21 APIs — PR21's own new, separately and statically typed
routes and response schema (§29, §31) — no frontend redesign, and no
change whatsoever to the existing PR20F Equipment Master frontend
integration, since its route and wire contract are verified unchanged
(§29). Thai-first, mobile-first, minimal typing, large touch targets,
Administrator-controlled workflow all preserved. No frontend file is
touched by this Design PR (§51).

---

## 42. Security / privacy assessment

**OD-PR21-6 — RESOLVED (Owner Decision Closure Round 1).** The Owner
has explicitly accepted the recommended safest V1 policy: the real
`หมายเหตุ` (notes) columns, now confirmed present on both canonical
line-item sheets and both order-header sheets (§9, §10), are **not
imported into permanent `borrow_transactions.notes` by default.**
Structural presence of the field may still be validated (e.g. length
bounds), but its content is never copied into permanent historical
provenance. The raw notes value remains only inside the temporary
source artifact, governed entirely by PR19's existing 180-day
redact-in-place retention policy (§38, §39) — it is never treated as
permanent transaction history. **This content was never inspected for
patient-identifying data by any session** (no free-text sampling was
performed, consistent with §42's own original caveat that such review
requires explicit, separately-scoped privacy handling, not incidental
inspection while reading structure) — the resolution here is a policy
choice made *because* the content is unreviewed, not a claim that
review found it safe.

**Alternative preserved for the future, not adopted now:** if the Owner
later wants some or all notes content imported, that requires an
explicit allowlist/redaction policy adopted only after an explicit,
separately-scoped privacy-sampling review — not proposed or performed
by this round. §52's Mandatory STOP condition on this point is now
closed by explicit Owner decision (import notes permanently: never,
by default, until a future explicit review changes this).

None of PR21's conceptual fields (§9, §10) are otherwise
patient-related.

---

## 43. Schema assessment (gap analysis)

No migration is created by this Design PR.

| Proposed addition | Why existing schema is insufficient |
|---|---|
| `LegacyEquipmentEvent`-shaped table (§8.1, Owner Decision Closure Round 2 — supersedes the `HistoricalTransactionSourceRef`/`HistoricalTransaction` shape this row previously described), including per-event legacy operator-name capture (§13) | No existing table represents an independent, immutable historical `ISSUE`/`RECEIVE` fact; `borrow_transactions` is paired-transaction-shaped and, per §12's Round 2 conclusion, cannot safely represent an unpaired legacy event without fabrication. |
| `LegacyMigrationAuthority`-shaped table (§24.2, PR #102 fix round — design concept only, not implemented by this Design PR) | No existing table represents the governance identity of one Owner-approved historical migration source, immutably bound to its approved checksum; `ImportSource` is upload-artifact identity, not migration-approval identity (§24.2), and cannot substitute for it without breaking same-file-retry idempotency. |
| `LegacyEquipmentEventSourceRef`-shaped 1:N provenance table(s) (§8.1) — narrowed from up to 4 source rows per paired transaction to up to 2 per independent event | No existing link from a `LegacyEquipmentEvent` row back to import provenance exists; a flat single-provenance-per-event design cannot represent the header-plus-line-item shape (§6.1). |
| `legacy_ward_aliases` mapping table (§14) | Confirmed absent from `master_data.py`. |
| PR21-owned dry-run plan header/row tables (§36) | Existing `EquipmentMasterDryRunPlan`/`Row` are upsert-oriented and Equipment-specific; do not fit an insert-oriented event import, and are not reused directly per §30/§31's separate-routes decision. |
| Internal generic provider interface + PR21's own future public routes/schemas (§29-§31) — code change, not schema, but listed here as a real prerequisite | `import_dry_run_plan_crud` and the two existing `import_sessions.py` endpoints are hardcoded to Equipment Master today; no internal dataset-type provider dispatch exists, and PR21 has no routes of its own yet. **Now implemented and merged** (GitHub PR #100) — retained here as historical schema-gap record. |
| Fail-closed adapter retention hook (§38) — code change, not schema | `redact_session()` was hardcoded to `EquipmentMasterDryRunPlanRow`; no generic dispatch, and no fail-closed provider-verification step, existed. **Now implemented and merged** (GitHub PR #100) — retained here as historical schema-gap record. |
| ~~Historical-sentinel handling for `transaction_no`~~ **REMOVED (Owner Decision Closure Round 2, §20.1):** `LegacyEquipmentEvent` has no `transaction_no` column — moot under the adopted event-first architecture. |

Every schema addition is additive; none of it alters or constrains any
existing live-workflow column, and none of it renames or removes any
existing PR20 wire field (§29-§32). None of it touches
`borrow_transactions` at all (§12).

---

## 44. Concurrency / live safety

**Owner Decision Closure Round 2 reaffirmation.** `LegacyEquipmentEvent`
import (§8.1) MUST NOT: mutate `Equipment.status`; mutate current
Ward/location; increment `Equipment.version`; invoke live dispatch;
invoke live receipt; create a current `OPEN` `BorrowTransaction`;
interfere with `idx_tx_one_active_borrow`; or fabricate current `User`
rows. Historical import is append-only historical evidence — this
restates §3/§19's existing, unmodified invariants precisely for the
model this document now actually adopts, and none of them were relaxed
to reach that adoption.

**Historical analysis (accurate under §11's original, now-superseded
option (B); preserved for record):** this section previously stated
that imported historical `CLOSED` records never interfere with current
`OPEN` transactions, that unique `transaction_no` constraints must
never collide with the live sequence, and that write-time idempotency
using §24's stable event identity is required and not deferred to PR22.
The idempotency requirement is unchanged in substance — restated for
`LegacyEquipmentEvent` at §24.2 — but the `transaction_no` collision
concern no longer applies (§20.1: no such column exists on the adopted
model), and PR19's execution single-winner claim (§37) remains reused
unmodified regardless.

**"Historical `OPEN` import is the one case that cannot be guaranteed
safe by architecture alone" — RESOLVED, not merely mitigated, under
event-first.** §11.2/§8.1 mean PR21 V1 never creates any row with an
`OPEN`/`CLOSED` status at all for imported history — the case this
paragraph originally worried about does not arise, because
`LegacyEquipmentEvent` is not a `BorrowTransaction` and the
maintenance-window / "simply not needed" choice this section previously
offered as mitigations for an approved historical-`OPEN` import are no
longer necessary decisions, since that import shape itself is no longer
what PR21 V1 builds.

---

## 45. Required Owner Decisions

- **OD-PR21-0 — PARTIALLY RESOLVED; two of four sub-components newly
  RESOLVED this round.** Real source workbook supplied and directly
  inspected (§6), bound to its SHA-256 identity
  `8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c` and
  the sanitized evidence manifest at
  `docs/evidence/pr21/equipment-pool-workbook-manifest.json`. Four
  sub-components, tracked independently:
  - **Topology — RESOLVED** (Source Evidence Update): one workbook
    snapshot → one `ImportSession` → one `ImportSource` → whitelisted
    sheets within that source (Option A, §7).
  - **Field-level contract — PARTIALLY RESOLVED** (§10.1, Round 1):
    every canonical-sheet field is classified (imported business fact /
    provenance-only / validation-only / ignored / privacy-blocked).
    **Still open:** the `ข้อมูลการส่ง SDC`/`ข้อมูลการรับ SDC` ambiguity
    (§6.1/§6.3) — unchanged by this round.
  - **Stable event identity — RESOLVED FOR PR21 V1** (§24.2, **Owner
    Decision Closure Round 2, corrected in the PR #102 fix round**):
    PR21 V1 is a controlled, one-time migration scoped to one immutable
    `LegacyMigrationAuthority` (a design concept, §24.2), itself bound
    to the Owner-approved frozen workbook snapshot's checksum (SHA-256
    above). Within that one authority,
    `(migration_authority_id, dataset_type, source row key ลำดับ)`
    identifies an event, database-enforced. **Cross-export durability of
    `ลำดับ` remains unproven and is explicitly not claimed** — a
    different-checksum workbook can never be attached to the existing
    migration authority and is never automatically treated as a
    replay/update of the original migration (§24.2's corrected-export
    policy). §24.1's interim evidentiary bar (Option D) is superseded
    for V1's purposes by this narrower, evidence-supported architectural
    resolution — it is not that the original evidentiary question was
    answered, but that V1 no longer needs it answered to proceed safely.
    The fix-round correction (adding `migration_authority_id` to the
    identity tuple) does not reopen this resolution — see §24.2's own
    closing paragraph.
  - **Issue↔Receive pairing — RESOLVED: pairing NOT required for
    import** (§11.2, **Owner Decision Closure Round 2**): §11.1's
    architecture fork is closed by adopting fork (ii), event-first
    staging. Issue and Receive line-item rows import as independent,
    immutable `LegacyEquipmentEvent` rows (§8.1); no deterministic
    shared key exists in the inspected workbook (unchanged finding);
    only deterministic source evidence or explicit authorized review
    (PR22-or-later) may ever link two already-imported events, never a
    nearest-timestamp/same-day/BCM-alone/Ward-alone/BME-alone/fuzzy
    heuristic.
- **OD-PR21-1 — RESOLVED (Owner Decision Closure Round 1); AMENDED
  (Owner Decision Closure Round 2, §16.1).** The Owner-accepted
  principle (never fabricate a live-meaningful `OPEN` transaction from
  unresolved history) is unchanged. The specific "unmatched ISSUE =
  whole-session `ERROR`" mechanism is withdrawn as inapplicable under
  the now-adopted event-first architecture — an Issue event with no
  identifiable Receive counterpart imports successfully as its own
  independent historical fact; every genuine row-level validity
  condition (§15) still applies unchanged.
- **OD-PR21-2 — RESOLVED (Owner Decision Closure Round 1); AMENDED
  (Owner Decision Closure Round 2, §17.1).** Identical treatment and
  identical reasoning to OD-PR21-1, mirrored for RECEIVE.
- **OD-PR21-3 — RESOLVED (Owner Decision Closure Round 1).** Legacy
  BME-name preservation/mapping-procedure boundary (§13): preserve raw
  text permanently; no auto-created `User` accounts; no display-name
  auto-mapping; optional nullable mapping only, later, explicit,
  Administrator-driven; import never blocked on mapping existing.
  Unaffected by Round 2 (now attached to `LegacyEquipmentEvent`, §8.1,
  rather than `BorrowTransaction`, with no change to the policy itself).
- **OD-PR21-4 — RESOLVED (Owner Decision Closure Round 1).** Ward
  alias-mapping table ownership/curation (§14): Administrator-owned,
  explicit, auditable, persisted mappings; exact match auto-resolves;
  unknown/ambiguous is `ERROR`; no silent Ward creation; no fuzzy match.
  Unaffected by Round 2, for the same reason as OD-PR21-3.
- **OD-PR21-5 — RESOLVED for PR21 V1's actual scope (Owner Decision
  Closure Round 2, §20.1).** Round 1 resolved the *direction* (no
  contemporary-looking number; legacy reference preserved separately;
  internal UUID sufficient for DB identity) but left the exact
  LEGACY-namespace format open. Round 2 finds that open remainder moot
  for V1: `LegacyEquipmentEvent` has no `transaction_no` column at all,
  since V1 never writes `BorrowTransaction` rows (§12, §11.2). The
  format question only resurfaces if a future PR22-or-later
  reconciliation step ever materializes a real `BorrowTransaction` for
  a confirmed pair — explicitly out of V1's scope, not decided here.
- **OD-PR21-6 — RESOLVED (Owner Decision Closure Round 1).** Patient/
  clinical free-text handling (§42): `หมายเหตุ` is not imported into
  permanent transaction history by default; raw value survives only
  inside the temporary, 180-day-redacted source artifact; a future
  allowlist/redaction policy requires its own explicit, separately-
  scoped privacy review before any change to this default. Unaffected
  by Round 2.

**Net effect of Owner Decision Closure Round 2:** OD-PR21-0's
stable-event-identity and Issue↔Receive-pairing sub-components — the
two the Owner explicitly instructed this session not to guess at — are
now **RESOLVED**, on the precise, narrow terms stated above (never as
an unqualified "`ลำดับ` is globally stable" or "pairing is unnecessary
in general" claim). OD-PR21-5 moves from PARTIALLY RESOLVED to
**RESOLVED for V1's actual scope**. OD-PR21-1/2 remain RESOLVED, with a
recorded, non-silent amendment reflecting the architecture that
resolved OD-PR21-0's pairing sub-component. OD-PR21-3/4/6 are
unaffected. **OD-PR21-0's field-level-contract sub-component (SDC
ambiguity) remains the only open item across all seven decisions** —
narrower than at any prior round. See §54 for the full readiness
reassessment this implies for PR21A–F.

---

## 46. Proposed implementation slices (provisional)

**Fix Round 2 (PR98-H5) correction.** The prior revision contradicted
itself: it said "no slice below is ready today" while also describing
PR21-Foundation as not-blocked/startable, and its readiness table
referenced a "PR21-Foundation idempotency check" that was never actually
in Foundation's own scope. This is corrected below with one coherent
model.

**Corrected gate wording:** it is **not** true that "no implementation
slice may start." The precise statement is: **"no source-dependent PR21
implementation slice may start."** PR21-Foundation, being genuinely
topology-independent generic plumbing, may start once this Design PR
merges.

- **PR21-Foundation** — generic *internal* plumbing only, no public API
  surface of its own. **In scope:** the generic provider interface
  (§30, internal service layer only — never owns a FastAPI
  `response_model`); an internal compatibility wrapper/verification
  around PR20's existing plan service, proving Equipment Master's
  existing routes/response models/OpenAPI schema are byte/field
  unchanged (§29, §31); reusable internal pagination/error-response
  helpers, so long as they do not change PR20's wire shape (§33, §34);
  and the retention-hook **abstraction** (the fail-closed provider-
  dispatch mechanism itself, §38) — but registering PR21's *own*
  redaction callback is not in this slice, since PR21 has no artifacts
  yet. **Explicitly out of scope for PR21-Foundation:** any PR21
  database schema or migration; PR21's provenance tables (§8, §43),
  whose concrete shape follows §7's now-resolved topology but is still
  PR21A's job, not Foundation's; event-identity/idempotency constraints
  (§24 — this is a later,
  source-dependent slice's responsibility, not Foundation's); Issue/
  Receive parsers (§9, §10); pairing logic (§11); PR21's own
  idempotency keys (§25); the `legacy_ward_aliases` table (§14); legacy
  BME persistence (§13); **any PR21 public response schema or route**
  (§29, §31 — PR21's own `LegacyHistoryDryRunPlanOut` and its routes are
  added later, by a source-dependent slice, never by Foundation). At the
  time this list was written, all of these were blocked on OD-PR21-0;
  as of Owner Decision Closure Round 2 (PR #102 fix round), the
  identity/pairing sub-components are resolved and PR21A/PR21B/PR21C
  readiness is governed by §46/§54, not by this historical framing —
  regardless, none of this list is in PR21-Foundation's own scope. This
  slice carries **PR20-regression risk** (it touches shared PR19/PR20
  infrastructure) and deserves isolated, independent review separate
  from PR21's own dataset-specific
  schema.
- **PR21A — Historical Event Schema / Provenance Foundation** (renamed
  from "Historical Transaction Schema" — Owner Decision Closure Round 2:
  the artifact is `LegacyEquipmentEvent`, §8.1, not a paired
  `HistoricalTransaction`). §8.1's simplified 1:N provenance tables
  (up to 2 refs per event, not 4 per pair), the `LegacyMigrationAuthority`
  design concept (§24.2, PR #102 fix round), §14's `legacy_ward_aliases`,
  §36's PR21 plan tables (registered against PR21-Foundation's provider
  interface, merged as GitHub PR #100). §7's topology is resolved. **Owner
  Decision Closure Round 1:** OD-PR21-3/4 RESOLVED — no longer blockers.
  **Owner Decision Closure Round 2:** OD-PR21-0's stable-event-identity
  sub-component RESOLVED FOR V1 (§24.2) and pairing sub-component
  RESOLVED (§11.2) — both formerly the sole remaining blockers, now
  cleared. OD-PR21-5 RESOLVED for V1's actual scope (§20.1) — no
  `transaction_no` column on `LegacyEquipmentEvent` at all.
  **PR21A is READY TO START AFTER THIS DESIGN PR MERGES** (design/schema
  work; not yet implemented — a fresh, baseline-gated implementation
  task is still required, §54, gated on this PR's own merge like every
  other design decision in this document). **PR21A must not include:**
  Issue/Receive parser field contracts, any SDC-specific field, or any
  source-sheet assumption beyond the generic event/provenance/
  migration-authority schema — those remain scoped to PR21B/C below,
  which carry the still-open SDC caveat this PR21A schema itself does
  not depend on. The exact ref-table and `LegacyMigrationAuthority`
  cardinality/columns remain PR21A's own implementation-grade design
  work, as they always were.
- **PR21B — Issue History Parser + Validation.** Not blocked by
  topology, OD-PR21-1 (RESOLVED+AMENDED, §16.1 — PR21B does not itself
  perform pairing), or OD-PR21-0's identity/pairing sub-components
  (both RESOLVED, §24.2/§11.2). **PR21B's full scope is NOT FULLY
  READY — CONDITIONALLY BLOCKED** by OD-PR21-0's still-open
  field-level-contract sub-component (the SDC-sheet ambiguity, §6.1/
  §6.3): until the Owner clarifies whether the SDC sheets represent
  additional, distinct transaction data, PR21B's own field contract
  cannot be called final, and this document does not silently decide
  that question on the Owner's behalf (§13 of this fix round's own
  instruction). **A narrower, explicitly bounded sub-slice — parsing
  and validating only the four already-confirmed canonical sheets,
  excluding any SDC sheet entirely — may start once PR21A's schema is
  available and this Design PR has merged.** That bounded sub-slice is
  not the same commitment as "PR21B is ready": it must be scoped,
  reviewed, and accepted as a canonical-sheet-only slice, with full
  PR21B acceptance (including any SDC-derived fields) still pending the
  SDC Owner Decision. §4's identifier case matrix and §15's error-code
  list remain PR21B's own implementation-grade work, as originally
  scoped, for whichever scope (bounded or full) is actually undertaken.
- **PR21C — Receive History Parser + Matching/Validation.** Renamed
  emphasis: no longer "Matching" as an import-time gate — validates
  `RECEIVE` events **independently** (§11.2); adds no pairing heuristic
  of its own. OD-PR21-1/2 (RESOLVED+AMENDED) and OD-PR21-0's pairing
  sub-component (RESOLVED, §11.2) are no longer blockers. **PR21C's
  full scope is NOT FULLY READY — CONDITIONALLY BLOCKED**, identical
  reasoning and identical canonical-sheet-only bounded-sub-slice
  carve-out to PR21B above.
- **PR21D — Persisted Dry-run + Historical Event Execution** (renamed
  from "Historical Transaction Execution" — Owner Decision Closure
  Round 2: executes `LegacyEquipmentEvent` inserts, never
  `BorrowTransaction` inserts, §12). **Blocked on:** PR21A–C actually
  being implemented (not merely ready — design readiness is not
  completion), and on OD-PR21-5's narrow remaining piece (§20.1: the
  exact `transaction_no` format, relevant only if/when a future
  reconciliation step materializes real `BorrowTransaction` rows — out
  of PR21D's own V1 scope as currently defined).
- **PR21E — Frontend Real Integration.** **Blocked on:** PR21D.
- **PR21F — Governance Sync.** After all approved slices merge, per
  `docs/ENGINEERING_WORKFLOW.md` §14 — not performed by this Design PR
  (§50).

**Owner Decision Closure Round 2 correction, itself corrected by the
PR #102 fix round:** OD-PR21-0's identity and pairing sub-components
are resolved, which fully clears PR21A to start (once this Design PR
merges) since PR21A's own schema does not depend on SDC. It does
**not** fully clear PR21B/C: OD-PR21-0's remaining field-level-contract
sub-component (the SDC-sheet ambiguity, §6.1) is still an **open Owner
Decision**, and this document does not treat "identity and pairing are
resolved" as if it also resolved that separate, still-open
sub-component. PR21B/C's full scope therefore remains **NOT FULLY
READY** until the Owner closes the SDC question; only the explicitly
bounded, canonical-sheet-only sub-slice described above may start
before then. **This does not mean PR21A, or PR21B/C's bounded
sub-slice, are implemented** — each remains a separate, baseline-gated
implementation task, not started by this document (§28 of this round's
own scope guard), and none may start before this Design PR itself
merges.

---

## 47. Readiness table

| Area | Status | Blocking? | Required before slice |
|---|---|---|---|
| Source topology (§7) | **RESOLVED — Option A, confirmed against the real workbook** | NO | — |
| Canonical Issue/Receive sheet selection (§6.2) | RESOLVED — `Orders`+line-item pairs, verified by direct inspection | NO | — |
| Field-level contract, canonical sheets (§10.1) | RESOLVED — every canonical-sheet field classified | NO | — |
| SDC sheet ambiguity (§6.1) | NARROWED (aggregate counts match canonical sheets) but NOT RESOLVED — requires Owner clarification | Partially (scopes PR21B/C's eventual full completeness, not a start-blocker for the confirmed canonical scope) | Before PR21B/C's field contract is considered *final* |
| Stable event identity (§24, §24.1, §24.2) | **RESOLVED FOR PR21 V1, corrected in the PR #102 fix round** — one immutable `LegacyMigrationAuthority` (design concept) bound to the frozen snapshot's checksum (§6); `(migration_authority_id, dataset_type, ลำดับ)` scoped identity; cross-export durability explicitly NOT claimed | NO (for V1) | — |
| Issue↔Receive pairing (§11, §11.1, §11.2) | **RESOLVED this round** — event-first adopted; pairing not required for import; deterministic-only linking deferred to PR22-or-later | NO | — |
| Validation/dry-run semantics (§15, §28) | RESOLVED: all-or-nothing PR19 gate; dry-run never contains ERROR-severity rows | NO | — |
| Generic persisted-plan API design (§29-§32) | RESOLVED design contract, PR20 wire-compatible | NO (design) | — |
| Generic persisted-plan API implementation (PR21-Foundation) | **RESOLVED — implemented and merged (GitHub PR #100, squash `7b99e586...`)** | NO | — |
| Retention integration design (§38) | RESOLVED design direction, fail-closed | NO (design) | — |
| Retention hook implementation (PR21-Foundation, abstraction only) | **RESOLVED — implemented and merged (GitHub PR #100)**; fail-closed behavior test-covered | NO | — |
| Unmatched ISSUE/RECEIVE policy (§16/§17, §16.1/§17.1) | RESOLVED, AMENDED this round for event-first — no longer an `ERROR` condition on its own; row-level validity conditions unaffected | NO | — |
| Ward mapping ownership (§14) | RESOLVED — Administrator-owned, explicit/auditable/persisted; 52-entry reference list found (§14.1) | NO | — |
| BME mapping-procedure boundary (§13) | RESOLVED — preserve raw text, optional later mapping, never blocking | NO | — |
| Historical `transaction_no` policy (§20, §20.1) | **RESOLVED for V1's actual scope this round** — `LegacyEquipmentEvent` has no such column | NO (for V1) | Only relevant to a future PR22-or-later reconciliation step, if ever undertaken |
| Patient/clinical data handling (§42) | RESOLVED — notes never imported into permanent history by default | NO | — |
| `LegacyEquipmentEvent` schema / provenance shape (§8.1) | Semantics RESOLVED this round; **exact schema is PR21A's own implementation-grade work** | NO (design) | PR21A's own design task |

**PR21 overall readiness, reassessed (PR #102 fix round):** the
identity and pairing blockers that stopped every source-dependent slice
are now resolved. **PR21A is ready to start once this Design PR merges**
(design/implementation not yet begun — a separate, baseline-gated
task). **PR21B and PR21C are NOT fully ready** — OD-PR21-0's
field-level-contract sub-component (SDC-sheet ambiguity, §6.1) is still
an open Owner Decision that bounds their full scope; only an explicitly
bounded, canonical-sheet-only sub-slice of each may start, once PR21A's
schema exists (§46). PR21D/E/F remain blocked, transitively, on those
slices actually being built. **PR21-Foundation is complete** (merged,
GitHub PR #100). See §54 for the full per-slice reassessment.

---

## 48. Test strategy

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
  no `DryRunPlan`; a validated (zero-ERROR) session's plan never
  contains an ERROR-severity row — both directions regression-tested
  explicitly (§15, §28).
- **Idempotency:** same file replay, same event replayed via a
  corrected export with different `ImportSource`/row numbers, truly
  distinct events not falsely merged (§25).
- **Live safety:** current `Equipment.status` unchanged; current `OPEN`
  transaction unaffected; historical import does not block live
  dispatch (`idx_tx_one_active_borrow` regression tests, §3, §44).
- **Generic plan API / PR20 compatibility (PR21-Foundation):** internal
  provider dispatch-by-`dataset_type` correctness (service layer only);
  **byte/field-for-field no PR20 regression** — Equipment Master's
  existing route, `response_model`, OpenAPI schema, and
  `DryRunPlanOut`/`DryRunPlanConfirmOut`/`DryRunPlanRowOut` responses,
  pagination cursors, and 404/409 semantics all verified unchanged after
  §29-§31's internal generalization; confirmation-audit cardinality
  verified exactly once per first successful confirmation, never once
  per HTTP call, including under concurrent-confirmation races (§35).
- **Retention (PR21-Foundation abstraction + later PR21-specific hook):**
  fail-closed behavior — provider callback failure/missing registration
  correctly rolls back the whole redaction transaction and leaves
  `retention_purged_at` unset (§38); no partial-purged state is ever
  observable.
- **PostgreSQL:** stable event-identity uniqueness enforcement (once
  chosen, §24), concurrency, rollback, atomic execution (§37, §44).
- **Reporting:** timestamps normalize correctly to aware UTC (§22);
  business_date/shift derive correctly for both sides of a pair; unified
  history ordering alongside live transactions (§23, §27).

---

## 49. Design deliverable

This document is that deliverable — self-contained, standing on its own
without depending on GitHub review comments for its normative contract.
Fix Round 1 and Fix Round 2's corrections are incorporated directly into
the relevant sections above, not appended as separate "see review"
notes.

---

## 50. Governance update (this Design PR's own scope)

Per `docs/ENGINEERING_WORKFLOW.md` §6/§7 and PR19A/PR20's own design-PR
precedent, this PR's governance-update scope is limited to: this design
document and a new `docs/DECISION_LOG.md` entry.

**PR99 Source Evidence Update, historical record (unchanged from when
written):** records the inspected workbook's evidence, bound to its
SHA-256 identity (`8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c`,
§6); resolves the topology component of OD-PR21-0 (§7, §45).

**Owner Decision Closure Round 1, current truth (this round):** records
the Owner's explicit acceptance of OD-PR21-1, OD-PR21-2, OD-PR21-3,
OD-PR21-4, and OD-PR21-6 (§45, all RESOLVED); records the Owner's
explicit acceptance of OD-PR21-5's direction only (PARTIALLY RESOLVED,
§20, §45); records the field-level contract for the canonical sheets
(§10.1, narrowing OD-PR21-0's field-mapping sub-component); records an
explicit interim evidentiary policy for OD-PR21-0's stable-event-identity
sub-component (§24.1, Option D adopted, identity itself still open, per
the Owner's own explicit instruction not to decide `ลำดับ`'s durability
unilaterally); records an explicit, previously-implicit architecture
fork for OD-PR21-0's Issue↔Receive-pairing sub-component (§11.1,
neither fork selected); records this round's outcome in a new
`docs/DECISION_LOG.md` entry; and does **not** start, or otherwise
touch, PR21A/B/C/D/E (PR21-Foundation is separately complete — merged
as GitHub PR #100, squash SHA `7b99e5866df4b71ffa1aa09d265baa2bc7033c33`
— and this round does not modify it).

**Not performed:** any change to `docs/ROADMAP.md`,
`docs/ROADMAP_STATUS.md`, `knowledge/*`, or
`docs/audits/04-consolidated-implementation-plan.md`. **GitHub PR #97's
accepted non-blocking P2 follow-up, and GitHub PR #98's P2-A/P2-B
follow-ups, remain untouched and unresolved by this PR** — this update
edits neither `docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md` nor the
PR20-related content of `docs/DECISION_LOG.md`, and does not rewrite any
prior dated `DECISION_LOG.md` entry's own historical record.

---

## 51. Scope guard for this PR

**Touched:** `docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`
(revised), `docs/DECISION_LOG.md` (one new entry recording Owner
Decision Closure Round 1's findings and resolutions). **Not touched:**
`backend/**`, `frontend/**`, `alembic/**`, `tests/**`, `.github/**`,
Docker/runtime configuration, `docs/ROADMAP.md`,
`docs/ROADMAP_STATUS.md`, `knowledge/**`,
`docs/audits/04-consolidated-implementation-plan.md`,
`docs/evidence/pr21/**` (unchanged, still bound to the same SHA-256).
No workbook re-upload occurs in this round. No PR21 runtime
implementation (PR21A–F) is performed by this PR.

---

## 52. Mandatory STOP conditions encountered

- **Actual Receive/Issue source schema unavailable — RESOLVED.** Real
  workbook supplied and directly inspected (§6); canonical sheets
  identified and their real fields verified (§6.2, §9, §10). The SDC
  sheet ambiguity (§6.1) remains a narrower, explicitly-scoped open
  question, not a full recurrence of this STOP condition.
- **Source topology unknown — RESOLVED** (§7: Option A, confirmed
  against the real workbook).
- **Field-level contract unknown — RESOLVED for canonical sheets**
  (§10.1); SDC-sheet field contract remains open, scoped narrowly to
  that ambiguity.
- **Source event identity unknown — RESOLVED FOR PR21 V1 (Owner
  Decision Closure Round 2, corrected in the PR #102 fix round)** (§24,
  §24.1, §24.2: frozen migration snapshot policy adopted via one
  immutable `LegacyMigrationAuthority` design concept, bound to the
  Owner-approved snapshot's SHA-256; `(migration_authority_id,
  dataset_type, ลำดับ)` scoped to that one authority; cross-export
  durability explicitly not claimed — the underlying factual question
  about `ลำดับ`'s general AppSheet behavior remains genuinely
  unanswered, but PR21 V1 no longer needs it answered to proceed
  safely).
- **Issue↔Receive deterministic matching unknown — RESOLVED (Owner
  Decision Closure Round 2): event-first architecture adopted** (§11,
  §11.1, §11.2: direct inspection confirms no linking field exists,
  unchanged; the Owner has now selected fork (ii) — pairing is not
  required for import; only deterministic evidence or explicit
  authorized review may ever link two independently-imported events).
- **Unmatched ISSUE policy unknown — RESOLVED, AMENDED for event-first**
  (§16, §16.1, OD-PR21-1: the original `ERROR`-severity mechanism is
  withdrawn as inapplicable; the underlying safety principle is
  unchanged and structurally strengthened).
- **Unmatched RECEIVE policy unknown — RESOLVED, AMENDED for
  event-first** (§17, §17.1, OD-PR21-2: identical treatment).
- **Ward mapping policy — RESOLVED, architecture and ownership both**
  (§14, §14.1, OD-PR21-4: Administrator-owned, explicit/auditable/
  persisted; 52-entry reference list found).
- **Historical operator representation — RESOLVED, architecture and
  mapping-procedure boundary both** (§13, §13.1, OD-PR21-3: preserve
  raw text permanently, optional later mapping, never blocking; real
  8-name roster found).
- **BorrowTransaction schema cannot represent history without
  fabrication — ENCOUNTERED for the unpaired case, RESOLVED by adopting
  a different model (Owner Decision Closure Round 2)** (§12: an
  unpaired `RECEIVE` event's `borrowed_at` cannot be populated without
  fabrication — this finding is the evidentiary basis for adopting
  `LegacyEquipmentEvent` (§8.1) instead of writing `BorrowTransaction`
  rows directly; PR21 V1 does not attempt the unsafe representation this
  STOP condition warns against).
- **Live transaction uniqueness can be affected — RESOLVED (eliminated
  for V1) by OD-PR21-1's resolution, reaffirmed structurally by
  event-first** (§16, §44): PR21 V1 never writes any `BorrowTransaction`
  row for imported history at all, so `idx_tx_one_active_borrow` cannot
  be affected by legacy import in V1, independent of any validation-time
  check.
- **Patient/HN/MRN data present without an approved handling policy —
  RESOLVED (default policy adopted; content itself still unreviewed)**
  (§42, OD-PR21-6: notes are never imported into permanent history by
  default).
- **A new transaction lifecycle state appears necessary — NOT
  ENCOUNTERED** (§18). `LegacyEquipmentEvent.event_type` (`ISSUE`/
  `RECEIVE`, §8.1) is not an `Equipment` lifecycle state and does not
  touch `Equipment.status`'s existing enum.
- **Historical `transaction_no` cannot satisfy NOT NULL/UNIQUE without
  fabrication — RESOLVED for PR21 V1's actual scope (Owner Decision
  Closure Round 2)** (§20, §20.1, OD-PR21-5: `LegacyEquipmentEvent` has
  no `transaction_no` column; the question is moot for V1, not merely
  deferred).
- **PR21 requiring a change to PR19/PR20 safety semantics — NOT
  ENCOUNTERED**; every safety mechanism (§37, §38) is reused unmodified,
  and PR20's existing route, response model, and wire contract are
  verified unchanged (§29-§32), and remain so after PR21-Foundation's
  actual merge (GitHub PR #100) — no lock order, fencing, claim, audit
  contract, PR20 response field, or PR20 route was altered by that
  implementation.

**Net effect: OD-PR21-0's stable-event-identity and Issue↔Receive-
pairing sub-components — the two the Owner explicitly reserved for
itself rather than delegating to this session — are now RESOLVED**, on
the narrow, precisely-stated terms in §24.2/§11.2. Combined with Round
1's resolutions, **six of seven Owner Decisions (OD-PR21-1 through
OD-PR21-6) are now RESOLVED** (OD-PR21-5 resolved for V1's actual
scope); **OD-PR21-0 has three of four sub-components RESOLVED**
(topology, identity, pairing) and one narrowly open (field-level
contract's SDC-sheet ambiguity, §6.1). **PR21-Foundation is complete**
(§46, §47 — merged as GitHub PR #100). **PR21A is ready to start once
this Design PR merges** (design/implementation, not yet begun).
**PR21B/C's full scope remains NOT FULLY READY** — the open SDC
sub-component still blocks it — though an explicitly bounded,
canonical-sheet-only sub-slice of each may start once PR21A's schema
exists (§46, PR #102 fix round). See §54 for the precise, per-slice
readiness reassessment this round produces.

---

## 53. Owner Decision Closure Round 1 — readiness reassessment

**PR21A (Historical Transaction Schema / Provenance Foundation):
STILL BLOCKED.** OD-PR21-3/4 (now resolved) and PR21-Foundation's
provider interface (now merged) are no longer blockers. **Blocking
remainder: OD-PR21-0's stable-event-identity sub-component (§24.1)** —
PR21A's own provenance/plan-table schema needs to know the identity
mechanism before it can be designed without risking rework.

**PR21B (Issue History Parser + Validation): STILL BLOCKED.**
**Blocking remainder:** SDC-sheet clarification (§6.1/§6.3), §4's
identifier case matrix, §15's frozen error-code list, and OD-PR21-0's
stable-event-identity sub-component (§24.1, needed for write-time
idempotency, §25).

**PR21C (Receive History Parser + Matching/Validation): STILL
BLOCKED.** OD-PR21-1/2 (now resolved) are no longer blockers on their
own. **Blocking remainder:** SDC-sheet clarification, and §11.1's
Issue↔Receive pairing architecture fork (deterministic rule vs.
event-first staging) — an explicit Owner/architecture decision this
round raises but does not make.

**PR21D (Persisted Dry-run + Historical Transaction Execution):
STILL BLOCKED**, transitively on PR21A–C, plus its own additional,
narrower blocker: OD-PR21-5's exact `transaction_no` namespace/format
(§20) — the one remaining piece of OD-PR21-5 this round leaves open.

**PR21E (Frontend Real Integration): STILL BLOCKED**, transitively on
PR21D, unchanged.

**PR21F (Governance Sync): STILL BLOCKED**, transitively on all
approved slices merging, unchanged.

**What this round does NOT do, stated explicitly (per this round's own
scope guard, §51):** it does not implement PR21A/B/C/D/E; it does not
add a migration; it does not modify `backend/**`, `frontend/**`,
`alembic/**`, `tests/**`, or `.github/**`; it does not merge without
independent review; it does not decide `ลำดับ`'s re-export durability
(§24.1) or select an Issue↔Receive pairing rule (§11.1) — both are
explicitly left to the Owner, per this round's own governing
instruction; it does not touch GitHub PR #97's P2 follow-up or PR #98's
P2-A/P2-B follow-ups (unchanged, still accepted/non-blocking/unresolved
in their existing recorded wording).

**Superseded by Owner Decision Closure Round 2 (§54):** this section's
own STILL BLOCKED statuses for PR21A/B/C, and its statement that
`ลำดับ`'s durability and an Issue↔Receive pairing rule are undecided,
describe Round 1's state accurately as of when Round 1 was written.
Round 2 resolves both remaining OD-PR21-0 sub-components — on the
narrow, V1-scoped terms §24.2/§11.2 state precisely, not as the
open-ended decisions Round 1 was still waiting on. This section is
retained verbatim as the historical record of Round 1's own
assessment; §54 is the current, governing readiness reassessment.

---

## 54. Owner Decision Closure Round 2 — readiness reassessment

**Corrected by the PR #102 fix round.** This section's first draft
declared PR21B/C unconditionally "READY TO START for the four confirmed
canonical sheets" in the same breath as leaving the SDC field-level-
contract sub-component of OD-PR21-0 open — two statements that cannot
both be unconditionally true at once (independent review flagged this
as a governance contradiction). The corrected readiness model below
resolves it: OD-PR21-0's identity and pairing sub-components being
RESOLVED clears PR21A, whose schema does not depend on SDC; it does
**not** clear PR21B/C's full scope, whose field contract genuinely does
depend on the still-open SDC question.

**PR21A (Historical Event Schema / Provenance Foundation): READY TO
START ONCE THIS DESIGN PR MERGES.** §53's blocking remainder
(OD-PR21-0's stable-event-identity sub-component) is RESOLVED FOR V1
(§24.2, migration-authority-scoped). OD-PR21-0's pairing sub-component,
while not itself a direct PR21A blocker, is also RESOLVED (§11.2),
simplifying the provenance shape PR21A will design (§8.1: up to 2
source refs per event, not 4 per pair, plus the `LegacyMigrationAuthority`
design concept, §24.2). **PR21A must not include** Issue/Receive
parser field contracts, SDC-specific fields, or any source-sheet
assumption beyond the generic event/provenance/migration-authority
schema (§46). **Not yet implemented** — this is a design-readiness
statement, not a completion statement, and it does not take effect
until this Design PR itself merges; a separate, baseline-gated
implementation task is still required.

**PR21B (Issue History Parser + Validation): NOT FULLY READY —
CONDITIONALLY BLOCKED.** §53's blocking remainder (SDC-sheet
clarification, identifier case matrix, error-code list, stable event
identity) is reduced to: the SDC-sheet ambiguity (§6.1) alone, since
stable event identity is now RESOLVED FOR V1. That remaining item is a
genuine, still-open **Owner Decision** (OD-PR21-0's field-level-contract
sub-component), not a mere completeness caveat — this document does not
treat it as resolved just because the other two OD-PR21-0
sub-components are. **A bounded, canonical-sheet-only sub-slice** —
parsing/validating only the four already-confirmed canonical sheets,
explicitly excluding any SDC sheet — may start once PR21A's schema
exists and this Design PR has merged; that sub-slice must be scoped and
reviewed as a bounded slice, not treated as "PR21B is ready." Full
PR21B acceptance (including any SDC-derived scope) still requires the
Owner to close the SDC question. The identifier case matrix/error-code
list remain PR21B's own implementation-grade design work exactly as
originally scoped, for whichever scope is actually undertaken.

**PR21C (Receive History Parser + Matching/Validation): NOT FULLY
READY — CONDITIONALLY BLOCKED**, identical treatment and identical
canonical-sheet-only bounded-sub-slice carve-out to PR21B. §53's
blocking remainder (SDC-sheet clarification, pairing architecture fork)
is reduced to the SDC caveat alone — the pairing architecture fork is
RESOLVED (§11.2); PR21C validates `RECEIVE` events independently and
must not add a pairing heuristic of its own (§11.2's own PR22-boundary
restriction, unchanged).

**PR21D (Persisted Dry-run + Historical Event Execution): STILL
BLOCKED**, transitively on PR21A–C actually being implemented (design
readiness is not completion). OD-PR21-5's exact `transaction_no`
namespace/format (§20.1) is no longer a PR21D blocker for V1's own
scope — it is out of scope entirely unless a future PR22-or-later
reconciliation step needs it.

**PR21E (Frontend Real Integration): STILL BLOCKED**, transitively on
PR21D, unchanged.

**PR21F (Governance Sync): STILL BLOCKED**, transitively on all
approved slices merging, unchanged.

**What this round does NOT do, stated explicitly (per this round's own
scope guard, carried forward unchanged by the PR #102 fix round):** it
does not implement PR21A/B/C/D/E/F; it does not add a migration
(`LegacyMigrationAuthority` is a design concept only, §24.2 — no
SQLAlchemy model, Alembic migration, API, or test is added); it does
not modify `backend/**`, `frontend/**`, `alembic/**`, `tests/**`,
`.github/**`, or `Docker/**`; it does not merge without independent
review; it does not start PR21A; it does not resolve the SDC-sheet
ambiguity (§6.1) — that Owner Decision remains explicitly open, not
silently decided by this fix round. It resolves `ลำดับ`'s scope-narrowed
applicability (never its general, cross-export AppSheet behavior — that
remains genuinely unproven and is not claimed otherwise, §24.2) and
adopts event-first as the Issue↔Receive architecture (§11.2) — both
explicit Owner Decisions this round makes, per this round's own task
specification, not decisions this session withheld. It does not touch
GitHub PR #97's P2 follow-up or PR #98's P2-A/P2-B follow-ups, which
remain accepted/non-blocking/unresolved in their existing recorded
wording — not claimed resolved by this round. It does not modify
`docs/ROADMAP.md`/`docs/ROADMAP_STATUS.md` — this round is still
design/decision closure, not an implementation milestone requiring a
roadmap-status change; that change belongs to PR21F (Governance Sync)
after implementation slices actually merge, per this document's own
established convention (§50).

---

*(End of design document. See the PR description for the required final
report covering validation, diff statistics, and confirmation items.)*
