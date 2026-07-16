# Project Overview

This repository implements the hospital Medical Equipment Pool MVP: a
system for tracking medical equipment as it is dispatched from a central
pool to hospital wards/departments and returned, replacing a prior
AppSheet-based process.

# Repository Layout

- `backend/` — FastAPI application (async SQLAlchemy, Alembic migrations,
  pytest test suite).
- `frontend/` — React/TypeScript web client.
- `docs/audits/` — the source-of-truth documents listed below.
- `docs/prompts/` — reusable, role-specific task prompts.
- `docs/AI_WORKFLOW.md` — the recommended AI-assisted development workflow.
- `docs/ROADMAP_STATUS.md` — current status of every planned roadmap Pull
  Request, at a glance.
- `docs/ARCHITECTURE_DECISIONS.md` — confirmed project-level decisions and
  their rationale.

# Source of Truth

The following documents define the project. Read the relevant ones before
any non-trivial task:

- `docs/audits/01-database-schema-audit.md`
- `docs/audits/02-backend-architecture-audit.md`
- `docs/audits/03-hospital-equipment-pool-workflow-audit.md`
- `docs/audits/04-consolidated-implementation-plan.md`

If these documents conflict with each other, **04 (the consolidated
implementation plan) is authoritative.**

# Domain Guardrails

The confirmed hospital workflow is intentionally narrow. Any task —
implementation or review — must respect it:

- Only Equipment Pool staff record transactions (no ward-user entry).
- ME Code is the primary user-facing equipment identifier; the internal
  UUID remains the database primary key.
- Routine rounds happen on a fixed schedule; on-demand dispatch is also
  supported.
- Only the **first receiving ward** is recorded — no ward-to-ward transfer
  tracking.
- Equipment receipt is a **single atomic operation** (outcome: usable or
  defective). Receiving an item does **not** indicate cleaning is
  complete — cleaning may happen before or after receiving, and the
  system never records cleaning status.
- There is **no separate cleaning workflow or cleaning status.**
- There is **no patient tracking** (no patient name, HN/MRN, bed number,
  named borrower, or due-date/overdue workflow). Patient transfers
  between wards are not tracked.
- Ward staff do not use this application — Equipment Pool staff are its
  only users.
- There is **no MEMS integration.**
- There is **no PM (preventive maintenance) workflow.**
- There is **no calibration workflow.**
- There is **no recall workflow.**

Do not introduce any of the above unless a task explicitly asks for it.

# Confirmed Future Workflow Direction

These are confirmed hospital decisions for **future** work — not yet
scheduled to a specific roadmap Pull Request. Do not build them ahead of
their planned PR (Scope Discipline, below), but do not design current
work in a way that would contradict or block them either. See
`docs/ROADMAP_STATUS.md` for scheduling status and
`docs/ARCHITECTURE_DECISIONS.md` for the full rationale.

- **Shift Sessions.** Routine dispatch rounds still exist operationally,
  but future implementation will replace hard-coded transaction times
  with flexible DAY and NIGHT Shift Sessions: opening/closing times are
  flexible, multiple staff may create transactions within one open
  session, and every transaction must record the authenticated operator
  regardless of which session it falls under.
- **Standby Snapshots.** Future reporting will support Day and Night
  Standby Snapshots recording department-level equipment counts. A
  snapshot is a distinct, manually-recorded event — it is not derived
  automatically from transaction history.
- **Deployment constraint.** Production deployment must not assume direct
  access to hospital-managed servers. The architecture should remain
  deployable to an approved managed platform while remaining a
  browser/PWA-based application.

# Scope Discipline

- Do not introduce future roadmap work ahead of its planned Pull Request.
- Do not implement features outside the scope assigned to the current task
  or Pull Request, even if they seem related or beneficial.
- When a task's scope is ambiguous, prefer the narrower interpretation and
  say what was left out.

# Git Discipline

- Keep Pull Requests small and focused on one objective.
- Do not bundle unrelated refactoring into a feature or fix PR.
- Follow the Pull Request ordering and dependencies defined in
  `docs/audits/04-consolidated-implementation-plan.md`.

# Testing Expectations

- Every implementation Pull Request should include tests covering its
  acceptance criteria (success paths and realistic failure paths).
- Every review should inspect the tests themselves, not just trust that a
  test suite exists or that the PR description says it passed.

# AI Roles

This repository is designed to be worked on by AI assistants in general,
not any single vendor's tool. The active role for a given task is
determined by the task prompt, not by this file. Typical repository
roles include:

- Software Architect
- Implementation Engineer
- Independent Reviewer
- Security Reviewer
- Test Engineer
- Documentation Assistant

Reusable, role-specific prompts live in `docs/prompts/`. For the
recommended end-to-end development workflow across these roles, see
`docs/AI_WORKFLOW.md`.
