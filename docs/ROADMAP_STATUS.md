# Roadmap Status

Current status of every Pull Request in the implementation plan
(`docs/audits/04-consolidated-implementation-plan.md`, Part D — the
authoritative source for scope, ordering, and acceptance criteria). This
document tracks **status only**; it does not duplicate the plan itself.

Last updated: after Roadmap PR2 merged.

---

PR1
Status:
Merged

Summary:
Production Security Foundation — JWT secret startup guard, dashboard SSE
connection-lifetime fix, Redis failure logging.

----------------------

PR2
Status:
Merged

Summary:
Structured Exception Handling — IntegrityError/SQLSTATE classification,
RequestValidationError and HTTPException envelopes, WWW-Authenticate
preservation.

----------------------

PR3
Status:
Next

Summary:
User, Role, and Master-Data Audit Logging.

----------------------

PR4
Status:
Planned

Summary:
Transaction-Number Generation (global PostgreSQL sequence).

----------------------

PR5
Status:
Planned

Summary:
Equipment Identifier Model (ME Code, identifier separation).

----------------------

PR6
Status:
Planned

Summary:
Equipment State Model Migration (4 states).

----------------------

PR7
Status:
Planned

Summary:
Dispatch Record Model (OPEN/CLOSED, dispatch type, routine round, field
cleanup).

----------------------

PR8
Status:
Planned

Summary:
Atomic Single-Operation Equipment Receipt with concurrency guard.

----------------------

PR9
Status:
Planned

Summary:
Ward Correction Action (audited).

----------------------

PR10
Status:
Planned

Summary:
Role Model Consolidation (3 roles).

----------------------

PR11
Status:
Planned

Summary:
Frontend Terminology and Workflow UI Pass.

----------------------

PR12
Status:
Planned

Summary:
Inventory Import.

----------------------

PR13
Status:
Planned

Summary:
Search, History, and Reporting Adjustments.

----------------------

PR14
Status:
Planned

Summary:
Reliability and Performance Hardening.

----------------------

PR15
Status:
Planned

Summary:
Observability and Schema Hygiene.

---

## Completed Milestones

- **PR1 — Production Security Foundation.** Merged.
- **PR2 — Structured Exception Handling.** Merged.

## Current Milestone

- **PR3 — User, Role, and Master-Data Audit Logging.** Next up; completes
  Group 1 (Security and Availability Foundation).

## Upcoming Milestone

- **Group 2 — Concurrency and Data Integrity** (PR4 Transaction-Number
  Sequence, PR5 ME Code Identifier Model, PR6 Equipment State Model). These
  three land the domain-model foundation that every later workflow PR
  (Group 3 onward) depends on.

## Known Future Workflow Items

Confirmed hospital decisions for work **beyond** the current 15-PR plan —
not yet scheduled to a specific PR. Do not implement ahead of a dedicated
future PR; see `AGENTS.md` ("Confirmed Future Workflow Direction") for the
guardrail statement and `docs/ARCHITECTURE_DECISIONS.md` for rationale.

- **Shift Sessions** — flexible DAY/NIGHT sessions replacing hard-coded
  routine-round times; multiple staff per open session; every transaction
  records its authenticated operator.
- **Standby Snapshots** — Day/Night department-level equipment-count
  reports, recorded independently of transaction history.
- **Managed deployment** — production architecture must not assume direct
  access to hospital-managed servers; stays deployable to an approved
  managed platform as a browser/PWA application.

## Related Documents

- `docs/audits/04-consolidated-implementation-plan.md` — authoritative
  scope, ordering, dependencies, and acceptance criteria for every PR
  listed above.
- `AGENTS.md` — permanent repository-wide guardrails and confirmed future
  direction.
- `docs/ARCHITECTURE_DECISIONS.md` — confirmed project-level decisions.
