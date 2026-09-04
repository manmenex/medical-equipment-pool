# Project Overview

This repository implements the hospital Medical Equipment Pool MVP: a
system for tracking medical equipment as it is dispatched from a central
pool to hospital wards/departments and returned, replacing a prior
AppSheet-based process.

# Repository Layout

- `backend/` — FastAPI application (async SQLAlchemy, Alembic migrations,
  pytest test suite).
- `frontend/` — React/TypeScript web client.
- `docs/` — governance, workflow, and domain documentation; see "Source of
  Truth" below.
- `knowledge/` — durable architecture decisions (`adr/`) and their
  business rules/concepts, plus the AI-memory snapshot
  (`PROJECT_MEMORY.md`, `CONTEXT.md`, `CHANGE_HISTORY.md`).
- `docs/prompts/` — reusable, role-specific task prompts.

# Source of Truth

Start with `docs/PROJECT_PLAYBOOK.md`, which defines the detailed
authority hierarchy, roles, and reading sets. For a faster single-file
orientation, start with `knowledge/PROJECT_MEMORY.md` instead — it
summarizes the same facts and cites its sources.

This file owns permanent repository-wide rules and enforcement
guardrails — the boundaries a task must not cross. It states them
compactly below and points to the document that owns the full rule,
rationale, and update history for each. Task-specific instructions may
narrow work but cannot silently override a guardrail, business rule, or
Roadmap boundary; a real conflict requires an explicit Governance PR.

| Topic | Full detail |
|---|---|
| Business rules (equipment states, identifiers, cleaning, dispatch/receipt ownership) | [`docs/BUSINESS_RULES.md`](docs/BUSINESS_RULES.md) |
| Architecture invariants ("do not" list for design/implementation/review) | [`docs/ARCHITECTURE_GUARDRAILS.md`](docs/ARCHITECTURE_GUARDRAILS.md) |
| Full requirement-to-merge workflow and AI roles | [`docs/PROJECT_WORKFLOW.md`](docs/PROJECT_WORKFLOW.md) |
| Roadmap PR scope, order, current status | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| Domain terminology and confirmed-vs-future workflow narrative | [`docs/HOSPITAL_DOMAIN_MODEL.md`](docs/HOSPITAL_DOMAIN_MODEL.md) |
| Current process/tooling limitations | [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) |
| Full authority hierarchy and topic ownership | [`docs/PROJECT_PLAYBOOK.md`](docs/PROJECT_PLAYBOOK.md) |

# Domain Guardrails (compact — see `docs/BUSINESS_RULES.md` and `docs/ARCHITECTURE_GUARDRAILS.md` for full rationale)

- Only Equipment Pool staff record transactions; ward staff are not application users.
- Exactly four equipment identifiers (UUID, BCM Code, Item No, Asset Number), each with one fixed role. "ME Code" is retired and must not be used.
- Exactly four equipment states; no cleaning state exists or may be added.
- Equipment receipt is one atomic usable/defective operation; cleaning is never tracked.
- Dispatch/receipt services own the transaction lifecycle; do not bypass them via manual status maintenance.
- Only the first receiving ward is recorded — no ward-to-ward transfer tracking.
- No patient tracking, no MEMS integration, no PM/calibration/recall workflow.

Do not introduce any of the above unless a task explicitly asks for it and cites the approving Governance PR/ADR.

# Confirmed Future Workflow Direction

Reporting metadata (`business_date` and `shift`) is planned for Roadmap PR16;
Day and Night are values in one model, not separate tables. Standby Snapshots,
any richer Shift Session workflow, and the managed-deployment constraint remain
separate future work. Do not build them ahead of their planned PR; do not
design current work to contradict or block them. See
[`docs/ROADMAP.md`](docs/ROADMAP.md) ("Confirmed future work") and
[`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md) for rationale.

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
  [`docs/ROADMAP.md`](docs/ROADMAP.md) and
  `docs/audits/04-consolidated-implementation-plan.md`.

# Testing Expectations

- Every implementation Pull Request should include tests covering its
  acceptance criteria (success paths and realistic failure paths).
- Every review should inspect the tests themselves, not just trust that a
  test suite exists or that the PR description says it passed.

# AI Roles and Workflow

Claude implements. Codex independently reviews. ChatGPT governs
architecture, roadmap, prompts, and review interpretation. The Repository
Owner makes business and merge decisions. The full requirement-to-merge
pipeline, non-negotiables (no automatic merge, no Claude<->Codex repair
loop), and reusable role-specific prompts are defined in
[`docs/PROJECT_WORKFLOW.md`](docs/PROJECT_WORKFLOW.md) and
[`docs/prompts/`](docs/prompts/).
