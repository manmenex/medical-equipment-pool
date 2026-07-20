# Project Workflow

**Purpose:** Compact, current-state statement of the full requirement-to-merge pipeline and role boundaries, for fast AI/human onboarding
**Authority:** Summary. `docs/PROJECT_PLAYBOOK.md` remains the authoritative role/workflow/evidence hierarchy; `docs/AI_REVIEW_WORKFLOW.md` remains authoritative for the Draft-PR-to-merge mechanics (CI gating, SHA verification, squash policy). This document does not redefine either — it is the single page that shows how they compose end to end, including the architecture-review step that precedes implementation.
**Update trigger:** Change to the agreed pipeline, a new/changed role, or a new/changed non-negotiable
**Maintainer:** Repository Owner

## The pipeline

```text
Requirement
  -> ChatGPT Architecture Review
  -> Claude Implementation
  -> Draft PR
  -> GitHub Actions CI
  -> Ready for review
  -> Codex Independent Review
  -> ChatGPT Project Governor Review
  -> Owner Approval
  -> Squash Merge
```

1. **Requirement.** The Repository Owner states an objective, scope, and explicit exclusions — directly, or via an authorized task prompt.
2. **ChatGPT Architecture Review.** Before implementation starts, ChatGPT checks the requirement against `docs/ARCHITECTURE_GUARDRAILS.md`, `knowledge/adr/`, `docs/ROADMAP.md`, and confirmed business rules (`docs/BUSINESS_RULES.md`). Ambiguous or conflicting requirements are resolved here, not during implementation. A requirement that would violate a guardrail or skip an unmet Roadmap dependency is corrected or escalated to the Owner at this step.
3. **Claude Implementation.** Claude implements the confirmed, bounded scope on a new branch created from the exact required baseline SHA. See `docs/PROJECT_PLAYBOOK.md`'s Scope Discipline.
4. **Draft PR.** Claude opens a Draft PR targeting the base branch, with a description matching `.github/PULL_REQUEST_TEMPLATE.md` (base SHA, scope, tests, migration impact, rollback, out-of-scope).
5. **GitHub Actions CI.** The checks defined in `.github/workflows/ci.yml` must all be green on the exact head SHA before the PR proceeds. A red or pending check blocks the next step.
6. **Ready for review.** Claude marks the PR Ready for review only after CI is green on that head SHA.
7. **Codex Independent Review.** Codex reviews the exact head SHA against `docs/prompts/codex-pr-review.md` and `docs/REVIEW_CHECKLIST.md`'s shared checklist — implementation correctness, security, database/transaction safety, test quality. Codex does not modify code.
8. **ChatGPT Project Governor Review.** ChatGPT checks the same head SHA for architecture/roadmap conformance — consistency with `knowledge/adr/`, `docs/ARCHITECTURE_GUARDRAILS.md`, `docs/BUSINESS_RULES.md`, and `docs/ROADMAP.md` sequencing — using `docs/REVIEW_CHECKLIST.md`'s shared checklist. ChatGPT does not modify code and does not merge.
9. **Owner Approval.** The workflow stops for the Repository Owner's explicit review and decision. Nothing merges automatically once both reviews are posted.
10. **Squash Merge.** The Owner (or a task the Owner has explicitly authorized) squash-merges against the exact approved head SHA, re-verified immediately beforehand. See `docs/REPOSITORY_STRATEGY.md`'s Draft PR and merge policy.

## Roles

| Role | Responsibility | Does not |
|---|---|---|
| Claude | Writes code and tests on an assigned, bounded task; opens and updates the Draft PR | Merge; expand scope; self-certify as independent review |
| Codex | Independent implementation review (correctness, security, database/transaction safety, test quality) | Modify code, commit, push, merge, or mark ready |
| ChatGPT | Governs architecture, Roadmap sequencing, prompts, and review interpretation — both before implementation (step 2) and after Codex (step 8) | Modify code, implement, or merge |
| Repository Owner | Confirms requirements; makes business decisions; gives final merge approval and performs/authorizes the merge | Delegate final merge authority |

This mirrors `docs/PROJECT_PLAYBOOK.md`'s role table (Architecture Owner, Implementation Engineer, Independent Reviewer, Repository Owner) — see that table for the full definition. ChatGPT here spans the Playbook's Architecture Owner and part of its Documentation/Governance Engineer responsibilities; Codex is the Playbook's Independent Reviewer.

## Non-negotiables

- **Claude writes code. Codex reviews code. ChatGPT governs architecture, roadmap, prompts, and review interpretation. The Owner makes business and merge decisions.** No role substitutes for another.
- **No automatic merge.** Nothing in CI, either review, or any agent's tooling merges a PR on its own. Merge is always a distinct, explicitly requested, owner-authorized action.
- **No Claude <-> Codex repair loop.** Codex's findings are not auto-applied by Claude and auto-resubmitted to Codex. Each fix round is a distinct, explicitly requested task; the resulting head is independently re-reviewed (by both Codex and ChatGPT) before merge is reconsidered.
- **New commits invalidate prior review.** A commit pushed after Codex or ChatGPT review — including a fix for that review's own findings — requires a new review of the new head SHA before merge.
- **Merge uses squash with an expected-head-SHA guard.** The approved head SHA is re-verified immediately before merging; a head that changed after approval is never merged unreviewed.

## Related documents

| Concern | Document |
|---|---|
| Detailed role/evidence/change-control hierarchy | `docs/PROJECT_PLAYBOOK.md` |
| Draft-PR-to-merge mechanics (CI gate, SHA-guard practice, squash policy) | `docs/AI_REVIEW_WORKFLOW.md` |
| Shared Codex/ChatGPT review checklist | `docs/REVIEW_CHECKLIST.md` |
| Detailed independent-review format and severity definitions | `docs/prompts/codex-pr-review.md` |
| Git/branch/merge/release policy | `docs/REPOSITORY_STRATEGY.md` |
| Known process limitations (e.g. review-submission permission errors) | `docs/KNOWN_LIMITATIONS.md` |
