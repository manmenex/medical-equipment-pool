# Roadmap PR5 — Equipment Master, BCM Search, and Internal QR Item-No Lookup

**Status:** Implemented in Draft PR (branch `feat/pr5-equipment-master-bcm-search`).
**Scope:** Equipment Pool only. See "Permanent project boundary" below.

## 1. Terminology reconciliation with prior planning documents

`docs/audits/04-consolidated-implementation-plan.md` (its PR5 section),
`GLOSSARY.md`, `HOSPITAL_DOMAIN_MODEL.md`, and `ROADMAP_STATUS.md` previously
described Roadmap PR5 around an **"ME Code"** identifier — a placeholder name
used while its real-world value was still unconfirmed, together with a
reconciliation-against-an-authoritative-spreadsheet migration strategy and a
deferred `NOT NULL` constraint pending an "eligible for Equipment Pool
operation" definition that was never supplied (see that plan's open
questions #2, #9, #10).

This PR implements a **confirmed, different, and more concrete** design,
supplied directly as this PR's business requirements:

- **BCM Code** — not "ME Code" — is the confirmed, primary, operator-facing
  identifier hospital staff use to manually find equipment.
- **Item No** is a second, separate, confirmed identifier: the content of
  the hospital's *existing physical QR labels*, used only for internal QR
  resolution — a role the prior "Item Number: future import metadata"
  glossary entry did not anticipate.
- Both are simple nullable+unique columns, populated by the equipment
  create/update API for now and by a future controlled Excel import
  (Roadmap PR8) — no spreadsheet-reconciliation backfill script, and no
  deferred/scoped `NOT NULL` constraint question, because neither column is
  `NOT NULL` in this design.

Treating this task's explicit, detailed business context as the confirmed
terminology superseding the "ME Code" placeholder is a judgment call, not a
certainty — it mirrors how earlier Roadmap PRs (PR4) resolved previously
open questions via confirmed Owner Decisions once real requirements
arrived. `GLOSSARY.md`, `HOSPITAL_DOMAIN_MODEL.md`, and `ROADMAP_STATUS.md`
have been updated to reference BCM Code/Item No in place of ME Code, with a
pointer back to this document; a short note was added to the consolidated
plan's PR5 section rather than rewriting it. **If "ME Code" was in fact
intended as a third, still-separate identifier, this reconciliation is
wrong and should be corrected in review** — nothing about this PR's
database schema forecloses adding a third identifier column later.

## 2. Permanent project boundary (unchanged, reaffirmed)

This repository remains exclusively the Medical Equipment Pool system. No
recall, alert, FDA, ECRI, FSN, or FSCA model, field, service, API, page,
dependency, or roadmap item was added or implied by this PR, and none is
planned for this repository. See `PROJECT_MEMORY.md` and
`HOSPITAL_DOMAIN_MODEL.md` for the (pre-existing, unmodified) history of
that boundary.

## 3. Confirmed identifier rules

| Field | Storage | Uniqueness | Manual search? | QR resolution? | Normal operator UI? |
|---|---|---|---|---|---|
| `item_no` | Equipment Master | Unique | No — never | Yes — the only field it uses | Not surfaced |
| `bcm_code` | Equipment Master | Unique | Yes — the only field it uses | No | Displayed after selection |
| `id` (UUID) | Equipment Master | Primary key | N/A | N/A | Internal only |

Borrow/return records continue to reference `equipment_id` (the internal
UUID) exactly as before — this PR does not touch that.

**Most devices already belong to the Equipment Pool.** No
`EquipmentAssignment`, `LocationAssignment`, `DepartmentAssignment`,
`PoolAssignment`, or equivalent ownership/assignment table was added — the
pre-existing `department_owner_id`/`current_location_id` columns on
`Equipment` are unchanged and were not touched by this PR.

## 4. Workflows

**Primary (QR):** scan existing QR (existing `QRScanner` component, unchanged)
→ `POST /api/v1/equipment/resolve-qr` extracts and validates the Item No
server-side → exact `item_no` lookup → matching equipment → continue into
the existing borrow/return workflow.

**Fallback (manual):** type into the BCM search box → `GET
/api/v1/equipment/search/bcm` returns up to `limit` BCM-Code-only
suggestions, exact match ranked first → operator selects one → the
application fetches and shows normal equipment details.

Both are wired into `BorrowPage` and `ReturnPage`, replacing the previous
"type an asset number, this project's own QR value" text box (which shared
no schema with the confirmed BCM Code identifier and was never a real
manual-search feature).

## 5. QR format decision

No real hospital QR sample was supplied to this PR. The narrowest,
deterministic, documented decision was made instead (see
`app/services/qr_service.py::extract_item_no_from_qr`): the scanned
payload's raw text, trimmed, *is* the Item No — no prefix, no structure.
Empty, over-length (>64 chars, the `item_no` column width), or URL-shaped
(`"://"` present) payloads are rejected as malformed before any lookup
runs. This is additive and independent of this application's own
self-generated `MEP:{asset_number}` QR scheme (`build_qr_value`,
`GET /equipment/{id}/qrcode`), which is unchanged and still used to print
labels for equipment that has none. **If the real hospital QR format
differs (e.g. it wraps the Item No in a URL or a structured payload),
`extract_item_no_from_qr` is the single place to adjust — no other code
depends on the assumption.**

## 6. Excel import readiness (not built here)

`item_no` and `bcm_code` are nullable, unique, indexed columns on the
existing `Equipment` model — structurally ready for a future controlled
Excel import (Roadmap PR8) to populate. No import UI, parser, or bulk-load
service was built in this PR; the equipment create/update API (which
already validates uniqueness via the existing `translate_integrity_error`
path) is the only write path today.

## 7. Non-goals for this PR

- No daily-reset or ME-Code-recalculation logic.
- No frontend admin UI for editing `item_no` (write-only via API for now;
  its intended source is the future Excel import).
- No camera/scanner redesign — the existing `QRScanner` component is reused
  unmodified.
- No change to transaction-number generation, audit architecture, borrow
  transaction semantics, return transaction semantics, or any unrelated API
  contract.
