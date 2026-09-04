# Compact Task Prompt Templates

Customize bracketed inputs. These templates reference permanent governance
instead of copying it. Add only task-specific facts, permissions, commands, and
deliverables.

## Implementation PR

```text
Role: Implementation Engineer
Task/Roadmap PR: [number and objective]
Base/branch: [base] / [branch]
Minimum reads: AGENTS.md; docs/PROJECT_PLAYBOOK.md; assigned Roadmap section; this task
Scope: [included]
Out of scope: [excluded]
Write permission: [code/tests/migrations/docs explicitly allowed]
Validation: [targeted tests]; [full suite]; PostgreSQL/Alembic when applicable
Deliverables: focused commit, pushed branch, Draft PR, evidence and rollback
Stop: after Draft PR; do not self-approve, mark ready, or merge
```

## Focused bugfix

```text
Role: Implementation Engineer
Defect/evidence: [issue, reproduction, severity]
Minimum reads: AGENTS.md; docs/PROJECT_PLAYBOOK.md; affected code; relevant debt/ADR
Scope: reproduce and fix [one defect]; preserve unrelated behavior
Write permission: affected implementation and regression tests only
Validation: failing-before/passing-after test; targeted and regression commands
Deliverables: root cause, changed files, evidence, known limitations, rollback, Draft PR
Stop: document other defects as follow-ups; do not broaden or merge
```

## Governance PR

```text
Role: Documentation/Governance Engineer
Governance objective: [authority/change]
Minimum reads: AGENTS.md; docs/PROJECT_PLAYBOOK.md; affected authoritative documents
Scope: documentation/templates only; list exact allowed files
Authority impact: [Roadmap / architecture / repository / terminology / status]
Validation: links; duplication/conflicts; git diff checks; documentation-only file list
Deliverables: document map, changed authority, before/after reading set, Draft PR
Stop: do not change runtime/repository settings, mark ready, or merge
```

## Independent review

```text
Role: Independent Reviewer
PR: [number/URL]
Minimum reads: AGENTS.md; docs/PROJECT_PLAYBOOK.md; docs/prompts/codex-pr-review.md;
assigned Roadmap section; actual PR diff/tests/surrounding code
Boundary: review only; no file, commit, push, PR metadata, ready, merge, close,
or fix mutations
Evidence focus: distinguish executed tests, manual checks, inspection, reports, unknowns
GitHub write: exactly one review submission under docs/prompts/codex-pr-review.md,
with optional focused inline comments
Deliverable: authoritative review submitted directly to the target PR; verify the
PR number, exact reviewed head SHA, reviewer identity, and action after posting
Stop: after verified submission; self-review must use COMMENT and be labeled clearly
```

## Corrective rereview

```text
Role: Independent Reviewer
PR and prior findings: [PR]; [finding IDs]
Minimum reads: AGENTS.md; docs/PROJECT_PLAYBOOK.md; docs/prompts/codex-pr-review.md;
prior review; corrective diff/tests
Boundary: verify each finding and detect regressions in changed surface; follow the
authoritative review-only write restrictions and submission policy
Deliverable: resolved/unresolved/new findings, evidence, and verified GitHub review
Stop: after verified submission; do not apply fixes, mark ready, or merge
```

## Repository maintenance

```text
Role: Repository Maintenance Engineer
Objective: [branch/default/tag/PR cleanup]
Minimum reads: AGENTS.md; docs/PROJECT_PLAYBOOK.md; docs/REPOSITORY_STRATEGY.md
Assessment inputs: current default; all branches/tags; all open/merged PR bases/heads
Mutation permission: [assessment-only OR exact authorized actions]
Safety: record SHAs/reachability; archive/recovery plan; no force push
Validation: post-action refs, PR bases, default branch, clean worktree, rollback anchors
Deliverable: actions/evidence/remaining risks
Stop: immediately after authorized repository operation
```

## Security hotfix

```text
Role: Implementation Engineer with Security Reviewer
Incident/severity: [summary]
Known-good base/tag: [ref]
Minimum reads: AGENTS.md; docs/PROJECT_PLAYBOOK.md; docs/REPOSITORY_STRATEGY.md;
relevant ADR/incident context
Scope: smallest safe containment/correction
Validation: security regression; targeted suite; rollback and monitoring thresholds
Deliverables: evidence-safe Draft/hotfix PR, residual exposure, follow-up owner
Stop: merge only with explicit Repository Owner emergency authorization
```
