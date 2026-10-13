# Project Workflow

**Purpose:** The requirement-to-merge pipeline, the AI agent team that runs it, and its non-negotiables
**Authority:** Authoritative for the pipeline, the agent roles, and the merge rules. Where `docs/PROJECT_PLAYBOOK.md`, `docs/prompts/`, or any older document still describes the earlier Claude -> Codex -> ChatGPT -> Owner pipeline, this document supersedes it (Owner decision, 2026-10-13; see `docs/DECISION_LOG.md`).
**Update trigger:** Change to the pipeline, the agent team, or a non-negotiable
**Maintainer:** Repository Owner

## Why it changed

The earlier pipeline routed every PR through Codex, ChatGPT, and the Owner
before merge, and required a separate Governance PR for any process change.
The Owner had become the gateway for every step, and backend CI alone took
24-29 minutes per push. Codex and ChatGPT are no longer part of this project.
The Owner now sets direction and decides what happens next; the agent team
below carries a PR from requirement to merge and reports what it did.

## The pipeline

```text
Owner request
  -> Orchestrator (Claude) plans and splits the work
  -> Implementer agents build on separate branches, one PR each
  -> GitHub Actions CI (must be fully green)
  -> Reviewer agent reviews the exact green head SHA
  -> Squash merge (by the orchestrator, against that SHA)
  -> Report to the Owner
```

1. **Owner request.** The Owner states what they want. The orchestrator
   asks only when a decision is genuinely the Owner's (business rules,
   scope trade-offs); otherwise it chooses and states the choice.
2. **Plan.** The orchestrator checks the request against
   `docs/BUSINESS_RULES.md`, `docs/ARCHITECTURE_GUARDRAILS.md`,
   `knowledge/adr/`, and `docs/ROADMAP.md`, and splits it into PR-sized
   tasks.
3. **Implement.** Implementer agents work in parallel, each in its own git
   worktree and branch, each producing one PR. Two agents never edit the
   same files at the same time.
4. **CI.** Every check in `.github/workflows/ci.yml` must be green on the
   exact head SHA. A red check goes straight back to the implementer, not
   to review.
5. **Review.** The reviewer agent reviews the green head SHA against
   `docs/DEFINITION_OF_DONE.md`: correctness, security, database and
   transaction safety, test quality, and conformance to the business rules
   and guardrails. A process or governance change is reviewed in the same
   PR as the work it serves; no separate Governance PR is needed.
6. **Merge.** On approval, the orchestrator squash-merges against the
   reviewed head SHA, re-verified immediately beforehand.
7. **Report.** The Owner is told, for every merged PR: what changed, the
   test and CI results, and anything still unproven or risky. The Owner
   decides what to do next.

## The agent team

| Agent | Model | At most | Does | Does not |
|---|---|---|---|---|
| Orchestrator | Claude (the session the Owner talks to) | 1 | Plans, assigns, merges, reports | Skip CI or review; merge its own unreviewed code |
| Implementer | Sonnet, low effort | 3 at once | Code and tests for one PR in its own worktree | Merge; review its own PR; touch another agent's files |
| Reviewer | Opus, low effort | 1 | Reviews green PRs; approves or returns findings | Write the fix it asks for; review a red or pending head |
| Helper | Haiku, low effort | 5 at once | Read-only and mechanical work: searching code, summarising CI logs, checking links and wording | Write application code or tests that merge without the reviewer |

The Repository Owner sets direction, makes business decisions, and alone
authorizes Production deployment.

## Non-negotiables

- **CI is the hard gate.** Implementer and reviewer are models from the
  same family and can share blind spots; the test suite is the check that
  does not. Nothing merges unless every CI check is green on the exact head
  SHA. The reviewer never approves a red or pending head.
- **Loop limit.** If one problem has taken 5 fix rounds, stop that
  approach: write down what was tried and why it failed, then change
  approach. If the new approach also fails after 5 rounds, stop and report
  to the Owner instead of continuing.
- **New commits invalidate review.** A commit pushed after review needs a
  new review of the new head SHA before merge.
- **Squash merge with an expected-head-SHA guard.**
- **Production deployment is the Owner's decision.** Merging to the base
  branch is not a deployment; nothing in this pipeline deploys to
  Production or marks it GO.
- **Domain guardrails are unchanged.** The rules in `AGENTS.md`,
  `docs/BUSINESS_RULES.md`, and `docs/ARCHITECTURE_GUARDRAILS.md` still
  bind every agent. An agent does not change them unless the Owner asks.
- **Report honestly.** Every report states what was verified and what was
  not, including evidence class (for example, that a local rehearsal is not
  Managed-Staging evidence).

## Knowledge Update Policy

Before merge, every PR must assess whether it needs updates to any of:

- `knowledge/PROJECT_MEMORY.md`
- `knowledge/CONTEXT.md`
- `knowledge/CHANGE_HISTORY.md`
- `docs/DECISION_LOG.md`
- `docs/ROADMAP.md`
- `docs/BUSINESS_RULES.md`
- `docs/ARCHITECTURE_GUARDRAILS.md`

Only update the files a PR actually affects. The reviewer re-checks this
assessment.

## Related documents

| Concern | Document |
|---|---|
| Review checklist | `docs/DEFINITION_OF_DONE.md` |
| Review format and severity definitions | `docs/prompts/codex-pr-review.md` (used by the reviewer agent) |
| Git/branch/merge/release policy | `docs/REPOSITORY_STRATEGY.md` |
| Known process limitations | `docs/KNOWN_LIMITATIONS.md` |
