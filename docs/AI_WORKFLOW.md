# AI-Assisted Development Workflow

This document describes the recommended workflow for using AI assistants
in this repository. It is written around roles, not tools, so it applies
regardless of which AI assistant is doing the work — see `AGENTS.md` for
the full list of roles and `docs/prompts/` for reusable, role-specific
task prompts.

## Workflow

```
Architecture
     |
     v
Implementation
     |
     v
Draft Pull Request
     |
     v
Independent Review
     |
     v
Fixes
     |
     v
Final Architecture Review
     |
     v
Merge
```

### 1. Architecture

A **Software Architect** role decides what the next Pull Request should
contain: its scope, boundaries, and how it fits the plan in
`docs/audits/04-consolidated-implementation-plan.md`. Output is a clear,
bounded assignment for one Pull Request — not code.

### 2. Implementation

An **Implementation Engineer** role implements exactly that one Pull
Request's scope, including tests, following the discipline in
`docs/prompts/claude-implementation.md`. Nothing from a later Pull
Request is implemented early.

### 3. Draft Pull Request

The change is pushed as a **Draft** Pull Request, not a ready-for-review
one. The description states scope, files changed, tests executed, risks,
and any deferred work, so a reviewer can assess it without re-deriving
context.

### 4. Independent Review

An **Independent Reviewer** role — and, where the change touches
authentication, data integrity, or secrets, a **Security Reviewer**
role — reviews the Draft PR without having implemented it, using
`docs/prompts/codex-pr-review.md`. The reviewer inspects the actual diff
and tests, not just the PR description, and does not modify files,
commit, push, or merge.

### 5. Fixes

The Implementation Engineer role addresses the review's findings and
pushes corrective commits, keeping the same discipline as the original
implementation (scope control, tests, git discipline).

### 6. Final Architecture Review

Before merge, confirm the finished Pull Request still matches its
original assignment and the implementation plan's Pull Request
boundaries — no scope drift accumulated across the fix cycle.

### 7. Merge

Only after review, fixes, and the final check pass does the Pull Request
get marked ready for review and merged.

## Principles

- **One Pull Request = one purpose.** Do not mix unrelated changes into a
  single Pull Request.
- **Review before merge.** No Pull Request merges without an independent
  review pass by a role that did not implement it.
- **Tests before merge.** Every Pull Request includes tests for its
  acceptance criteria, and the full existing suite must pass.
- **Small, incremental delivery.** Prefer several small, reviewable Pull
  Requests over one large one.
- **Respect implementation plan ordering.** Follow the Pull Request
  sequence and dependencies defined in
  `docs/audits/04-consolidated-implementation-plan.md`; do not implement
  later work ahead of its planned order.

## Related Documents

- `AGENTS.md` — permanent repository-wide rules and role definitions.
- `docs/prompts/` — reusable, role-specific task prompts.
- `docs/audits/04-consolidated-implementation-plan.md` — authoritative
  Pull Request plan and ordering.
