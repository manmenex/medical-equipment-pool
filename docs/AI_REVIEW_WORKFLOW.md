# AI Review Workflow

**Purpose:** Record the agreed Claude → Codex → owner review and merge workflow
**Authority:** Process description for how the roles in `docs/PROJECT_PLAYBOOK.md` (Implementation Engineer, Independent Reviewer, Repository Owner) are staffed by Claude, Codex, and the human Repository Owner on this repository. Does not redefine those roles, `docs/prompts/codex-pr-review.md`'s reviewer checklist, or `docs/REPOSITORY_STRATEGY.md`'s branch-protection recommendation — it describes how they compose end to end.
**Update trigger:** Change to the agreed AI review/merge sequence
**Maintainer:** Repository Owner

## Why this document exists

This repository is implemented by Claude and independently reviewed by Codex,
with the human Repository Owner (and, where used, ChatGPT) making the final
merge decision. Before Roadmap PR7 begins, this document fixes the exact
sequence so every future PR follows the same, predictable process — including
what each participant is *not* authorized to do.

## The workflow

1. **Owner confirms requirements.** The Repository Owner (or a task prompt the
   Owner has authorized) states the objective, scope, and any explicit
   exclusions before implementation starts.
2. **Claude implements on a new branch**, created from the exact required
   baseline SHA, scoped to the confirmed requirements only (see
   `docs/PROJECT_PLAYBOOK.md`'s Scope Discipline).
3. **Claude opens a Draft PR** targeting the base branch, with a description
   that states baseline SHA, scope, tests, migration impact, rollback, and
   out-of-scope items (see the pull request template).
4. **CI must pass.** The GitHub Actions checks defined in
   `.github/workflows/ci.yml` must all be green on the exact head SHA before
   the PR proceeds to review. A red or pending check blocks the next step.
5. **Claude marks the PR Ready for review** only after CI is green on that
   head SHA.
6. **Codex reviews the exact head SHA.** Codex acts as the Independent
   Reviewer defined in `docs/prompts/codex-pr-review.md`, verifying the
   Pull Request and its current head SHA immediately before submitting, and
   never approving an unreviewed head.
7. **The workflow stops for Owner + ChatGPT review.** Once Codex has posted
   its review, nothing merges automatically — the Repository Owner (using
   ChatGPT where applicable) reads Codex's findings and the diff before
   deciding how to proceed.

## Non-negotiable boundaries

- **Codex does not modify code.** Codex's only permitted GitHub write is
  submitting one Pull Request review (optionally with inline comments), per
  the GitHub Review Submission Policy in `docs/prompts/codex-pr-review.md`.
  It does not commit, push, edit files, change PR metadata, mark the PR
  ready, or merge/close it.
- **Claude does not merge.** Implementation sessions push fixes and update
  the Draft PR; the decision to merge, and the merge action itself, belong
  to the Repository Owner (or a task the Owner has explicitly authorized to
  perform the merge on their behalf after approval is confirmed).
- **New commits invalidate the previous approval.** Any commit pushed after
  a Codex review — including a fix for that review's own findings —
  requires a new Codex review of the new head SHA before merge. An approval
  is valid only for the exact SHA it was submitted against.
- **Merge requires explicit owner approval.** No PR merges on CI passing or
  Codex approval alone; the Repository Owner's explicit go-ahead is required
  every time, consistent with `docs/PROJECT_PLAYBOOK.md`'s role table
  ("Repository Owner: Decide readiness, merge, release, and emergency
  authority").
- **Merge uses squash and expected-head SHA protection.** The merge method is
  squash, and the merge is performed against the exact approved head SHA
  (verified immediately beforehand), so a head that changed after approval
  is never merged unreviewed.
- **No automatic Claude↔Codex repair loop.** Codex's findings are not
  auto-applied by Claude and re-submitted to Codex in a closed loop. Each
  fix round is a distinct, explicitly requested task; each resulting head is
  independently re-reviewed before merge is considered again.
- **No automatic merge.** Nothing in CI, the review workflow, or either
  agent's tooling merges a Pull Request on its own. Merge is always a
  distinct, explicitly requested, owner-authorized action.

## How this relates to existing documents

| Topic | Owning document |
|---|---|
| Roles (Implementation Engineer, Independent Reviewer, Repository Owner) and the standard workflow steps | `docs/PROJECT_PLAYBOOK.md` |
| Independent reviewer checklist, GitHub review submission policy, self-review labeling | `docs/prompts/codex-pr-review.md` |
| Branch protection / status-check recommendations (a repository setting, not something this workflow or its CI changes) | `docs/REPOSITORY_STRATEGY.md` |
| CI jobs that must pass before Ready for review | `.github/workflows/ci.yml` |
| Per-PR checklist evidence (base SHA, scope, tests, migration impact, rollback, out-of-scope, CI status, reviewed head SHA, Codex review, owner approval) | `.github/PULL_REQUEST_TEMPLATE.md` |

This document does not change any of those documents' authority; it states
how the roles they define are currently staffed and sequenced.
