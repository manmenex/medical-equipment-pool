# Code Review

**Purpose:** Quick-reference entry point to this repository's review process, for anyone opening or reviewing a Pull Request.
**Authority:** Summary only. `docs/PROJECT_WORKFLOW.md` is authoritative for the pipeline, the agent roles, and the merge rules; `docs/DEFINITION_OF_DONE.md` for the completion and review checklist; and `docs/prompts/codex-pr-review.md` (the reviewer-agent prompt; the filename is historical) for the full review format and severity definitions. This document does not redefine any of them.
**Update trigger:** The review pipeline, roles, or checklist changes at the source documents above.
**Maintainer:** Repository Owner

## The pipeline, in one line

```text
Owner request -> Orchestrator plans -> Implementer agents (one PR each) -> CI fully green
  -> Reviewer agent reviews the exact green head SHA -> Orchestrator squash-merges -> Report to Owner
```

Roles (orchestrator, implementer, reviewer, helper), the loop limit, and the
rule that only the Owner authorizes Production deployment are in
`docs/PROJECT_WORKFLOW.md`.

## What a reviewer checks

The checklist is `docs/DEFINITION_OF_DONE.md` plus the review areas in `docs/prompts/codex-pr-review.md`. At a glance:

- Base/head SHA recorded and current.
- Scope matches the assigned task: no later Roadmap work implemented early, no unrelated refactor bundled in.
- Tests listed with exact commands and results; local and CI evidence not conflated.
- Migration impact stated (none, or upgrade/downgrade evidence against PostgreSQL).
- Rollback plan proportionate to risk; out-of-scope items explicitly listed.
- All `.github/workflows/ci.yml` checks green on the exact reviewed head SHA.
- No secret/credential in the diff, logs, fixtures, or description.
- PR description matches the actual final diff.
- No `docs/BUSINESS_RULES.md` or `docs/ARCHITECTURE_GUARDRAILS.md` guardrail violated.
- Knowledge Update Policy assessed (`docs/PROJECT_WORKFLOW.md`): did this PR need to update `knowledge/PROJECT_MEMORY.md`, `knowledge/CONTEXT.md`, `knowledge/CHANGE_HISTORY.md`, `docs/DECISION_LOG.md`, `docs/ROADMAP.md`, `docs/BUSINESS_RULES.md`, or `docs/ARCHITECTURE_GUARDRAILS.md`, and did it?

The reviewer additionally goes deep on implementation correctness, security (OWASP-style review), database/transaction safety, async/performance, maintainability, and test quality. Severity definitions (Critical/High/Medium/Low) and the required output format are in `docs/prompts/codex-pr-review.md`.

## Non-negotiables (see `docs/PROJECT_WORKFLOW.md` for the full list)

- CI is the hard gate: nothing merges unless every check is green on the exact head SHA.
- The implementer does not self-certify as the reviewer.
- A commit pushed after review, including a fix for that review's own findings, invalidates the prior approval; the new head needs a new review.
- One problem gets at most 5 fix rounds before the approach must change.
- Merge uses squash, against the exact approved head SHA, re-verified immediately before merging.

## Opening a PR for review

1. Fill out `.github/PULL_REQUEST_TEMPLATE.md` completely: base SHA, scope (included/explicitly out of scope), change surface, evidence table with commands and results, operations (rollback/monitoring/known limitations), and both checklists.
2. Open as **Draft**. Do not mark Ready for review until CI is green on the exact head SHA.
3. Wait for the reviewer agent's review of that SHA; the orchestrator then merges.

## Where to look next

| Question | Document |
|---|---|
| What's the full requirement-to-merge pipeline? | `docs/PROJECT_WORKFLOW.md` |
| What does a reviewer check, in full? | `docs/DEFINITION_OF_DONE.md`, `docs/prompts/codex-pr-review.md` |
| Git branch naming, commit style, merge method, retention | `docs/REPOSITORY_STRATEGY.md` (also see `CONTRIBUTING.md`) |
| What counts as sufficient evidence for a change of a given risk level? | `docs/DEFINITION_OF_DONE.md` |
| Known process limitations | `docs/KNOWN_LIMITATIONS.md` |
