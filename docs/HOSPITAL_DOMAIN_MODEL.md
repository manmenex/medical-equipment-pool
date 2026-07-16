# Hospital Domain Model

**Purpose:** Concise reference for confirmed Equipment Pool terminology and workflow
**Authority:** Domain summary; `AGENTS.md`, active decisions, and the Roadmap govern changes
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
- **ME Code:** The required, user-facing hospital equipment identifier planned
  by Roadmap PR5. It is distinct from the UUID, Asset ID, Item Number, Serial
  Number, and QR payload.
- **Asset ID / Item Number / Serial Number:** Separate inventory metadata. Do
  not merge or infer one from another without an approved mapping.

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

### Future Shift Sessions

Future work will model flexible `DAY` and `NIGHT` Shift Sessions:

- opening/closing times are flexible;
- multiple operators may work during one open session;
- every transaction still records its actual authenticated operator;
- a session does not replace operator attribution.

Shift Sessions are confirmed direction but not scheduled to an active Roadmap PR.

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
