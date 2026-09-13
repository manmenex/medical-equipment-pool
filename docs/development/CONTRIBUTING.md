# Contributing

**Purpose:** Practical, day-to-day Git/PR mechanics for making a change in this repository — branch naming, commits, opening a Draft PR, and getting it merged.
**Authority:** Summary. `docs/REPOSITORY_STRATEGY.md` is authoritative for branch/PR/merge/release/retention policy; `AGENTS.md` is authoritative for domain guardrails and Scope Discipline; `docs/PROJECT_WORKFLOW.md`/`CODE_REVIEW.md` are authoritative for the review sequence. This document does not redefine any of them.
**Update trigger:** The branch/commit/PR mechanics described here change at the source documents above.
**Maintainer:** Repository Owner

## Before you start

1. Read `AGENTS.md` for the permanent domain guardrails (what this project does and explicitly does not do) and Scope Discipline (implement only the confirmed, bounded task — no later Roadmap work started early, no unrelated refactor bundled in).
2. Confirm the exact requirement, scope, and explicit exclusions (`docs/PROJECT_WORKFLOW.md` step 1).
3. Set up your environment per `SETUP.md`.

## Branching

Branch from the exact required baseline SHA — normally the current tip of the target base branch — never stacked on another in-flight, unmerged branch unless the task explicitly requires it.

| Change type | Pattern | Example |
|---|---|---|
| Feature/Roadmap | `feature/<short-scope>` | `feature/pr4-transaction-number` |
| Documentation/governance | `docs/<short-scope>` | `docs/project-governance-pack-v1` |
| Focused defect | `fix/<short-defect>` | `fix/equipment-update-response` |
| Security/production emergency | `hotfix/<incident-or-defect>` | `hotfix/token-validation` |
| Test-only improvement | `test/<short-scope>` | `test/postgres-migration-roundtrip` |

Use lowercase kebab-case. Full detail: `docs/REPOSITORY_STRATEGY.md` (Branch naming).

## Commits

- Title format: `type(optional-scope): imperative summary`, normally under 72 characters. Explain *why* in the body when the change isn't obvious from the diff alone.
- Never force-push without explicit emergency authorization from the Repository Owner. Never rewrite shared history.
- Prefer a new corrective commit during active review over amending, unless the change hasn't been shared yet.
- Don't mix generated artifacts, local environment state, or unrelated refactors into the same commit/PR.

## Opening a Pull Request

1. Open as **Draft** — this is the default for every normal change (`docs/REPOSITORY_STRATEGY.md`, Draft PR and merge policy).
2. Fill out `.github/PULL_REQUEST_TEMPLATE.md` completely: base SHA, scope (included / explicitly out of scope), change surface (files, API/database/security/documentation impact), evidence table (with exact commands and results, local vs. CI clearly labeled), operations (rollback plan, monitoring, known limitations, deferred follow-ups), and both checklists.
3. Push and wait for `.github/workflows/ci.yml` to run — see `TESTING.md` for what each job checks.
4. Mark **Ready for review** only once CI is green on the exact head SHA you want reviewed (`docs/AI_REVIEW_WORKFLOW.md`).
5. An independent reviewer (Codex) and, where used, a Project Governor review (ChatGPT) follow — see `CODE_REVIEW.md`. Any commit pushed after a review invalidates that review's approval; the new head needs re-review.
6. The Repository Owner gives final approval and performs (or explicitly authorizes) the merge. Nothing in this repository merges automatically.

## Knowledge Update Policy

Before merge, assess whether the change needs an update to any of: `knowledge/PROJECT_MEMORY.md`, `knowledge/CONTEXT.md`, `knowledge/CHANGE_HISTORY.md`, `docs/DECISION_LOG.md`, `docs/ROADMAP.md`, `docs/BUSINESS_RULES.md`, `docs/ARCHITECTURE_GUARDRAILS.md`. Only update the files the PR actually affects — don't create an empty or artificial entry just to satisfy this check. Full detail: `docs/PROJECT_WORKFLOW.md`.

## Merge method and cleanup

- **Default:** squash merge into one coherent commit, against the exact approved head SHA (re-verified immediately before merging).
- Merged branch heads are retained for 14 calendar days by default before cleanup; see `docs/REPOSITORY_STRATEGY.md` for the full retention, archive-tag, and rollback policy.

## What not to do

- Do not implement scope beyond the confirmed task, even if it seems like an obvious next step — see `AGENTS.md` Scope Discipline.
- Do not self-certify your own implementation as the independent review.
- Do not merge on CI passing or a single review alone — explicit Owner approval is always required.
- Do not commit a populated `.env` file, a real secret, or hospital/production credentials.

## Where to look next

| Question | Document |
|---|---|
| How do I get a local environment running? | `SETUP.md` |
| How do I run the test suite? | `TESTING.md` |
| How do I write/test a database migration? | `MIGRATIONS.md` |
| What does review actually check, and by whom? | `CODE_REVIEW.md` |
| Full branch/commit/merge/release/retention policy | `docs/REPOSITORY_STRATEGY.md` |
| Domain guardrails and Scope Discipline | `AGENTS.md` |
