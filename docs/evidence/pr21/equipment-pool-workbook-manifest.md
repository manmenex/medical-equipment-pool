# PR21 Source Evidence Manifest — Equipment Pool Workbook

This file is the human-readable companion to
`equipment-pool-workbook-manifest.json`, the machine-readable sanitized
evidence artifact this manifest pair is built from. Every claim in the
PR21 design document (`docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`)
that is based on direct inspection of the real Equipment Pool AppSheet
workbook cites this manifest and the workbook's SHA-256 below as its
evidence trail.

**Neither file contains row-level data, personnel names, patient
identifiers, phone numbers, free-text notes, or raw QR/barcode payload
values.** Only sheet/column structural metadata and aggregate counts are
recorded. The raw workbook itself is never committed to this
repository.

## Workbook identity

| Field | Value |
|---|---|
| Logical name | `บันทึกข้อมูล Equipment Pool.xlsx` |
| SHA-256 | `8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c` |
| Size (bytes) | 20,690,045 |
| Sheet count | 28 |
| Inspection methodology | Direct read via Python `openpyxl` (`read_only=True, data_only=True`) — the inspection timestamp recorded in the JSON manifest is provenance metadata only, not a business-truth claim |
| Raw workbook committed to this repository? | **No** — contains real hospital personnel names and ward/operational data |

Any future re-inspection of a workbook that does not hash to the SHA-256
above is inspecting a **different** file, and any design claim citing
this manifest does not automatically transfer to it.

## Sheet classification summary (28/28 sheets)

| Classification | Count | Sheets |
|---|---|---|
| `AUTHORITATIVE_INPUT_CANDIDATE` | 4 | `ข้อมูลส่งเครื่องมือ`, `ข้อมูลรับเครื่องมือ`, `Orders ยืมเครื่อง`, `Orders คืนเครื่อง` |
| `PRESENTATION_DERIVED` | 10 | `สแกนจ่ายเครื่องที่ส่งวันนี้`, `สแกนรับเครื่องวันนี้`, ` แบบบันทึกส่งเครื่อง`, `แบบบันทึกรับเครื่อง`, `แบบบันทึกส่งเครื่องเมื่อวาน`, ` แบบบันทึกรับเครื่องเมื่อวาน`, `BMEส่ง`, ` BMEส่งเมื่อว่าน`, `BMEรับ`, `BMEรับเมื่อว่าน` |
| `EQUIPMENT_MASTER_OUT_OF_SCOPE` | 1 | `ข้อมูลเครื่องEquipment Pool` |
| `VERIFY_CHECKLIST_OUT_OF_SCOPE` | 4 | `Equioment Verify Checklist`, ` Equioment Verify Checklist เมื`, `Verify Checklist 01`, `Verify Checklist 02` |
| `HELPER_OTHER` | 7 | `CODE QR`, `ชื่อ BME`, `Sheet32`, `แผนก`, `Barcode `, `ฝึกงานข้อมูลรับ`, `ฝึกงาน` |
| `UNKNOWN_REQUIRES_REVIEW` | 2 | `ข้อมูลการส่ง SDC`, `ข้อมูลการรับ SDC` |

## Canonical-sheet evidence (why these four, structurally)

**Issue candidate — `Orders ยืมเครื่อง` (header) + `ข้อมูลส่งเครื่องมือ` (line items):**
row-oriented records; per-row date/time present; `ME.Code` identifier
column present; Ward column (`แผนกที่ส่ง`) present; BME/operator columns
(`ชื่อ BME`, `ชื่อ (User)`) present; no title/report rows before records
— data begins at row 2, header at row 1; spans the full available date
range (2026-01-01 to 2026-07-28); order-reference field
(`เลขที่ใบส่ง`/`เลขที่ใบยืม`) is 100% unique **at the header sheet**
(5,685 distinct values for 5,685 non-null header rows). **Reference
resolution (a separate metric — see below): of 5,677 distinct
line-item reference values, all but one resolve against the header
sheet; one distinct orphan reference remains.** This is not 100%.

**Receive candidate — `Orders คืนเครื่อง` (header) + `ข้อมูลรับเครื่องมือ` (line items):**
identical structural shape to the Issue side. Order-reference field is
100% unique at the header sheet (6,158 distinct for 6,158 non-null
header rows). **Reference resolution: of 6,141 distinct line-item
reference values, all 6,141 resolve against the header sheet — zero
orphans measured on this side.** `canonical_receive_source` is **not**
UNRESOLVED — the same structural evidence class applies symmetrically,
and is recorded as such.

### Reference resolution (distinct-reference basis — do not confuse with row-key uniqueness below)

This is the metric measured for the canonical-source correction: for
each side, take the **distinct** order-reference values present on the
line-item sheet, and check how many resolve by set membership against
the header sheet's own distinct order-reference values.

| Side | Basis | Present (distinct) | Resolved | Orphan | Resolution complete? |
|---|---|---|---|---|---|
| Issue | distinct `เลขที่ใบส่ง` values vs. `Orders ยืมเครื่อง.เลขที่ใบยืม` | 5,677 | 5,676 | 1 | **No** |
| Receive | distinct `เลขที่ใบรับเครื่อง` values vs. `Orders คืนเครื่อง.เลขที่ใบคืน` | 6,141 | 6,141 | 0 | Yes |

**This is a distinct-value count, never a row-level count.** It is
unrelated to, and must never be read interchangeably with, the row-key
uniqueness figures below (e.g. `19,871/19,871`) — those measure
uniqueness of the `ลำดับ` column *within one sheet*, not whether an
order reference resolves against a *different* sheet. Full detail
(including the numeric invariant `present = resolved + orphan`,
verified for both sides) is in the JSON manifest's
`reference_resolution` object.

**Presentation-sheet evidence (why these are excluded):** the
`BMEส่ง`/`BMEรับ`-family sheets' own header rows contain a literal
AppSheet query string (e.g. `SELECT B,E,G,...WHERE B=DATE '2026-07-28'`)
— confirmed derived, single-day views, not source records. The
`แบบบันทึก...` sheets are print-form layouts: title/report layout, date
stored outside row records (a single labeled cell, not a column), no
tabular structure to parse.

## Identifier uniqueness (aggregate only — see JSON for exact figures)

For both canonical line-item sheets, the `ลำดับ` column is a row-key
candidate: 100% unique among non-null values, with a small blank rate
(~0.2%) — this is uniqueness *within its own sheet*, unrelated to
cross-sheet reference resolution (see "Reference resolution" above).
The order-reference field is separately 100% unique *at the
header-sheet level* (i.e., no order number repeats within the header
sheet itself) — this is also not the same claim as whether line-item
references resolve against that header sheet. `ME.Code` (the
equipment-identifying field) repeats heavily across rows, as expected
for a many-transactions-per-equipment history.
Exact present/blank/distinct/duplicate counts for every field are in the
JSON manifest's `row_key_uniqueness`, `order_reference_stats`, and
`me_code_stats` objects per sheet — no actual ID or BCM values are
listed anywhere in either file.

## Issue↔Receive pairing evidence

> No deterministic shared source event/transaction key was identified
> in the inspected workbook identified by SHA-256
> `8657cfc6c23036c64ea601dcc64c2b2e9d4fc5b51321534098d7a9ff1d84b00c`.

Aggregate counts (full detail in the JSON manifest's
`issue_receive_pairing_evidence` object): 19,912 Issue-side rows,
19,768 Receive-side rows, **0** rows with an explicit shared Issue↔Receive
key, **0** deterministically joinable candidate references. This finding
does **not** approve timestamp- or equipment-based heuristic matching as
a substitute — that remains a separate, blocking Owner Decision.

## SDC sheets — narrowed, not resolved

`ข้อมูลการส่ง SDC`/`ข้อมูลการรับ SDC` were flagged in the prior round as
structurally similar to the canonical sheets but numerically divergent
in total row count. Re-measurement (see the JSON manifest's
`sdc_sheets_evidence` object) shows the **non-blank** row counts and
**distinct** order-reference/`ME.Code` counts are identical to the
canonical sheets' own counts — the total-row divergence is fully
attributable to large blocks of trailing blank rows (8,207 and 31,694
respectively), not additional real transaction data. This is
aggregate-count evidence, not a row-by-row diff; full row-level
equivalence was not verified. SDC sheets remain **not selected** as
canonical (the four sheets above remain primary) — this narrows, but
does not fully close, the open question.

**Owner Decision Closure Round 3 update (post-dates this manifest's own
measurements, which are unchanged and unrepeated by this note):** the
Owner has since selected the four canonical sheets above as the sole
PR21 V1 authoritative source and excluded the SDC sheets from V1, on
exactly the evidentiary basis this section states — a source-authority
decision, not a claim that the row-level-equivalence question this
section leaves open has since been answered. See
`docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md` §6.5 for
the governing decision text. This manifest's own measurements are not
re-run or amended by that decision.

## FK-resolution scope

All identifier/Ward matching statistics in this manifest are
**workbook-internal structural evidence only**. This inspection
environment did not have an authoritative current database snapshot
(the live `Ward`/`User` tables) available to check against — no
database-level FK-resolution claim is made anywhere in this manifest or
the design document. A small sample of Ward strings was compared only
against this same workbook's own `แผนก` reference sheet (52 entries),
which is internal consistency evidence, not external resolution proof.

## What was not measured

Merged-cell ranges, hidden-column counts, and formula-cell counts for
the candidate sheets were **not measured** — a non-read-only full
workbook load (required for `openpyxl` to expose this data) exceeded an
85-second timeout for this 20.7 MB, 28-sheet file in this environment.
This is recorded honestly as `NOT_MEASURED_IMPRACTICAL_IN_ENVIRONMENT`
in the JSON manifest, not fabricated or estimated.
