# Code Review

**Purpose:** Quick-reference entry point to this repository's review process, for anyone opening or reviewing a Pull Request.
**Authority:** Summary only. `docs/PROJECT_WORKFLOW.md` is authoritative for the end-to-end pipeline, `docs/AI_REVIEW_WORKFLOW.md` for Draft-PR-to-merge mechanics, `docs/REVIEW_CHECKLIST.md` for the shared reviewer checklist, and `docs/prompts/codex-pr-review.md` for the full independent-review format and severity definitions. This document does not redefine any of them — read those documents for the authoritative detail.
**Update trigger:** The review pipeline, roles, or checklist changes at the source documents above.
**Maintainer:** Repository Owner

## The pipeline, in one line

```text
Requirement -> Architecture Review -> Implementation -> Draft PR -> CI -> Ready for review
  -> Independent Review (Codex) -> Governor Review (ChatGPT) -> Owner Approval -> Squash Merge
```

Full detail: `docs/PROJECT_WORKFLOW.md`.

## Roles (who does what)

| Role | Does | Does not |
|---|---|---|
| Implementer (Claude, or a human) | Writes code/tests on a bounded, assigned task; opens and updates the Draft PR | Merge; expand scope; self-certify as independent review |
| Independent Reviewer (Codex) | Reviews correctness, security, database/transaction safety, test quality | Modify code, commit, push, merge, or mark the PR ready |
| Project Governor (ChatGPT) | Checks architecture/Roadmap/guardrail conformance | Modify code, implement, or merge |
| Repository Owner | Confirms requirements; final review; merge decision and action | Delegate final merge authority |

## What a reviewer checks

`docs/REVIEW_CHECKLIST.md` is the single checklist shared by both the Independent Reviewer and the Project Governor. At a glance, it covers:

- Base/head SHA recorded and current.
- Scope matches the assigned task — no later Roadmap work implemented early, no unrelated refactor bundled in.
- Tests listed with exact commands and results; local and CI evidence not conflated.
- Migration impact stated (none, or upgrade/downgrade evidence against PostgreSQL).
- Rollback plan proportionate to risk.
- Out-of-scope items explicitly listed.
- All `.github/workflows/ci.yml` checks green on the exact reviewed head SHA.
- No secret/credential in the diff, logs, fixtures, or description.
- PR description matches the actual final diff.
- No `docs/BUSINESS_RULES.md` or `docs/ARCHITECTURE_GUARDRAILS.md` guardrail violated.
- Knowledge Update Policy assessed (`docs/PROJECT_WORKFLOW.md` — did this PR need to update `knowledge/PROJECT_MEMORY.md`, `knowledge/CONTEXT.md`, `knowledge/CHANGE_HISTORY.md`, `docs/DECISION_LOG.md`, `docs/ROADMAP.md`, `docs/BUSINESS_RULES.md`, or `docs/ARCHITECTURE_GUARDRAILS.md`, and did it?).

The Independent Reviewer additionally goes deep on implementation correctness, security (OWASP-style review), database/transaction safety, async/performance, maintainability, and test quality — the full breakdown, including severity definitions (Critical/High/Medium/Low) and the required review output format, is in `docs/prompts/codex-pr-review.md`.

## Non-negotiables (see `docs/PROJECT_WORKFLOW.md` for the full list)

- No role substitutes for another — the implementer does not self-certify as independent review.
- Nothing merges automatically. Merge is always a distinct, explicitly owner-authorized action.
- No Claude ↔ Codex repair loop: each fix round is its own task, and the resulting head is independently re-reviewed before merge is reconsidered.
- A commit pushed after review — including a fix for that review's own findings — invalidates the prior approval; the new head needs a new review.
- Merge uses squash, against the exact approved head SHA, re-verified immediately before merging.

## Opening a PR for review

1. Fill out `.github/PULL_REQUEST_TEMPLATE.md` completely — base SHA, scope (included/explicitly out of scope), change surface, evidence table with commands and results, operations (rollback/monitoring/known limitations), and both checklists.
2. Open as **Draft**. Do not mark Ready for review until CI is green on the exact head SHA (`docs/AI_REVIEW_WORKFLOW.md` step 4-5).
3. Wait for the Independent Reviewer and Project Governor review before requesting owner approval.

## Where to look next

| Question | Document |
|---|---|
| What's the full requirement-to-merge pipeline? | `docs/PROJECT_WORKFLOW.md` |
| What exactly must be true before a PR can be marked Ready / merged? | `docs/AI_REVIEW_WORKFLOW.md` |
| What does a reviewer check, in full? | `docs/REVIEW_CHECKLIST.md`, `docs/prompts/codex-pr-review.md` |
| Git branch naming, commit style, merge method, retention | `docs/REPOSITORY_STRATEGY.md` (also see `CONTRIBUTING.md`) |
| What counts as sufficient evidence for a change of a given risk level? | `docs/DEFINITION_OF_DONE.md` |
| Known process limitations (e.g. review-submission fallback) | `docs/KNOWN_LIMITATIONS.md` |
