# Hospital Domain Model

**Purpose:** Concise reference for confirmed Equipment Pool terminology and workflow
**Authority:** Domain summary; `AGENTS.md`, active decisions, and the Roadmap govern changes. Topics migrated into `../knowledge/` (currently: equipment identifiers, BCM search, QR identification — see `PROJECT_PLAYBOOK.md`'s topic-ownership table) are owned there instead of here.
**Update trigger:** Hospital-approved workflow or terminology change
**Maintainer:** Architecture Owner

This is system-domain guidance, not clinical guidance.

## People and organizational terms

- **Equipment Pool:** The central operational unit that controls pool equipment
  dispatch and receipt records.
- **BME / operator:** An authenticated Equipment Pool staff member who records
  an action. Every transaction records the actual authenticated operator.
- **Administrator:** An application user authorized for governance/master-data
  actions assigned by the current role model.
- **Department:** An organizational grouping that may contain wards and may be
  used for reporting or future standby counts.
- **Ward:** The first receiving destination recorded for a dispatch. Ward staff
  may request equipment externally, but they are not application operators.

The system does not model a patient, patient's location, or later movement of
equipment between wards after its first recorded destination.

## Equipment identity

- **Equipment:** One physical device, stored internally with a UUID primary key.

The identifier model (BCM Code, Item No, Asset Number, and internal UUID),
manual-search behavior, and QR identification are owned by the Knowledge
Layer, not this document — see
[`../knowledge/adr/ADR-002-identifier-model.md`](../knowledge/adr/ADR-002-identifier-model.md)
through `ADR-004`, `../knowledge/architecture/`, and
`../knowledge/business-rules/`. "ME Code" is a retired placeholder name and
must not be used.

One scan/dispatch represents one physical device; quantity is not a substitute
for equipment identity.

## Confirmed workflow

```text
AVAILABLE_AT_POOL
    -> dispatch to first receiving ward
ISSUED_TO_WARD
    -> receipt outcome: usable
AVAILABLE_AT_POOL

ISSUED_TO_WARD
    -> receipt outcome: defective
UNAVAILABLE_DEFECTIVE

UNAVAILABLE_DEFECTIVE
    -> approved return-to-service action (separate permission)
AVAILABLE_AT_POOL

UNAVAILABLE_DEFECTIVE -> DECOMMISSIONED (terminal normal state)
```

- **Dispatch:** Equipment Pool operator records equipment leaving the pool for
  the first receiving ward. No named borrower or patient is recorded.
- **Receipt:** One atomic digital operation closes the dispatch and records a
  binary outcome: usable or defective. Receipt does not mean cleaning was
  completed and does not record cleaning.
- **Equipment states:** `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`,
  `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`.
- **Transaction states:** `OPEN` and `CLOSED`. There is no active due-date or
  overdue state in the confirmed workflow.
- **First receiving ward:** Historically fixed after dispatch, except through a
  narrow, authorized, audited correction action planned by Roadmap PR9.

The state names and transaction model above are confirmed target concepts. The
current MVP code migrates toward them in Roadmap PR6–PR8; do not assume every
name is implemented before those PRs merge.

## Explicit exclusions

- No patient name, HN/MRN, bed number, named borrower, or current-patient location.
- No ward-to-ward transfer tracking or live equipment-location claim.
- No cleaning state, cleaning completion, or cleaning workflow.
- No ward user entry; Equipment Pool operators record actions.
- No MEMS, preventive-maintenance, calibration, recall, or hospital-wide asset
  lifecycle workflow in the Equipment Pool scope.

## Current MVP versus confirmed future work

### Current Roadmap direction

The active 15-PR Roadmap establishes the audit, identifier, state, dispatch,
receipt, role, import, search, reporting, and hardening foundations in the order
defined by
[`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md).

Fixed routine-round values are an MVP simplification until a separately scoped
future change replaces them.

### Planned reporting shift metadata

Roadmap PR16 will distinguish:

- the actual transaction timestamp;
- `business_date`; and
- `shift`.

Day and Night are values in one model, not separate tables. Shift is
reporting/operational metadata, not an equipment lifecycle state. Every
transaction continues to record its authenticated operator. A richer Shift
Session workflow is not part of PR16 and remains subject to separate approval.

### Future Standby Snapshots

A Standby Snapshot is a manually entered, department-level count for a Day or
Night period. It is not derived from transaction history and is separate from a
Shift Session.

Future snapshot entry may record the explicitly counted categories requested by
the Equipment Pool, including ready-to-use units and extra manually counted
standby items such as charging cables, clamps, and pneumatic pumps. The future
implementation must preserve the entered counts rather than infer them from
equipment transactions. Exact schema, validation, and reporting remain for a
separately approved PR; they are not introduced by this Governance Pack.

See [`GLOSSARY.md`](GLOSSARY.md) for concise preferred terms and
[`ARCHITECTURE_DECISIONS.md`](ARCHITECTURE_DECISIONS.md) for rationale.
