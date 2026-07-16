# Repository Strategy

**Purpose:** Authoritative Git, Pull Request, release, retention, and recovery policy
**Authority:** Repository process; does not redefine product or Roadmap scope
**Update trigger:** Default branch, merge, retention, release, or protection-policy change
**Maintainer:** Repository Owner

## Default branch and transition

The target default branch is `main`. Temporary long-lived `claude/*` branches
are migration-era names, not the permanent model. Create `main` from the latest
approved Medical Equipment Pool base only after active PRs are merged or safely
retargeted. Changing the default branch is a separate repository-maintenance
operation; this Governance Pack documents but does not perform it.

- No direct commits to `main`.
- Every change uses a focused branch and Pull Request.
- Do not delete the previous default/base until open PRs, automation, links, and
  recovery tags have been verified.
- Do not encode local paths, credentials, or one operator's machine commands as policy.

## Branch naming

| Change | Pattern | Example |
|---|---|---|
| Feature/Roadmap | `feature/<short-scope>` | `feature/pr4-transaction-number` |
| Documentation/governance | `docs/<short-scope>` | `docs/project-governance-pack-v1` |
| Focused defect | `fix/<short-defect>` | `fix/equipment-update-response` |
| Security/production emergency | `hotfix/<incident-or-defect>` | `hotfix/token-validation` |
| Test-only improvement | `test/<short-scope>` | `test/postgres-migration-roundtrip` |

Use lowercase kebab-case. A Roadmap number identifies product sequencing; a
GitHub PR number does not replace it.

## Commit and history policy

- Commit title: `type(optional-scope): imperative summary`, normally under 72
  characters; explain why in the body when the change is non-obvious.
- Never force-push without explicit emergency authorization from the Repository
  Owner. Never rewrite history owned or consumed by others.
- Prefer a new corrective commit during active review. Interactive cleanup is
  allowed only before sharing a branch and when no history consumer exists.
- Do not mix generated artifacts, local environment state, or unrelated refactors.

## Draft PR and merge policy

1. Open all normal changes as Draft PRs.
2. The author may self-review, but independent review is still required.
3. Mark ready only after applicable Definition of Done evidence and review fixes exist.
4. Repository Owner chooses and performs the merge.

**Default merge method:** squash a focused PR into one coherent commit. Use a
merge commit when preserving a meaningful multi-commit topology, governance
history, or release branch relationship has explicit value. Rebase merge is
acceptable only for a private linear branch with owner approval; it must not be
used to rewrite shared history.

If squash merging, the PR remains the primary review record. Before deleting a
head with unique commit identities that must remain directly addressable, create
an archive tag. Tree equality with the squash commit proves content inclusion;
it does not make the original commit objects reachable.

## Branch cleanup and retention

- Retain merged branch heads for **14 calendar days** unless an incident,
  rollback, release, or audit requires longer retention.
- After the retention period, delete merged heads only when the PR is merged,
  no open PR targets or depends on the branch, and content/recovery checks pass.
- Closed-unmerged branches require owner confirmation; unique commits are never
  deleted merely because the branch looks stale.
- Long-lived migration/default branches receive an archive tag and a documented
  rollback path before deletion.
- Run remote pruning only after GitHub state has been inspected.

### Archive and recovery tags

Use annotated tags:

- `archive/<purpose>-<date-or-version>` for branch/default cutovers or unique
  squash heads that require direct recovery.
- `release/<version>-rollback` only for a release-specific recovery anchor.

Record the reason, source branch, and related PR in the tag message. Push and
verify the tag before deleting a branch. Tags are recovery anchors, not a way to
avoid normal release versioning.

## Releases and hotfixes

- Release tags use semantic versioning: `vMAJOR.MINOR.PATCH`.
- A release tag points to an approved commit on `main`; never move or reuse it.
- Hotfix branches start from the affected production release or current `main`,
  whichever the incident decision names.
- Hotfixes remain focused, include the minimum safe verification, receive
  expedited independent/security review, and merge back to `main`.
- After stabilization, reconcile release notes, tests, debt, and incident-driven
  governance gaps through normal PRs.

## PR retargeting

Before changing a base branch:

1. Fetch current refs and record old base/head SHAs.
2. Ensure the new base contains the old base or document the intentional divergence.
3. Preview the recalculated diff and commit list.
4. Re-run relevant checks because retargeting changes the review surface.
5. Do not retarget a migration PR whose head is identical to the new base; close
   it as superseded after the replacement branch is established.

## Rollback flow

1. Stop further merges/deployments.
2. Identify the exact known-good commit/tag and affected data migrations.
3. Prefer a revert PR when history is already shared.
4. For database changes, follow the migration-specific rollback/forward-fix
   plan and protect data before changing schema.
5. Verify API health, data invariants, auth, audit writes, and the original failure.
6. Record the result and create focused follow-up work.

Never use `reset --hard`, force-push, or branch deletion as a production rollback.

## Branch protection and ruleset recommendation

Protect `main` with a repository ruleset that:

- requires a Pull Request and at least one independent approval;
- dismisses stale approvals after substantive changes;
- blocks force pushes and deletion;
- requires conversation resolution;
- requires applicable status checks once reliable CI exists;
- permits emergency bypass only for named Repository Owners with an audit trail.

Do not claim checks are required until the workflows actually exist and are
stable. This document recommends settings; governance tasks do not mutate them.

## Recommended label taxonomy

Use only labels that add routing value; not every PR needs every dimension.

- **Type:** `type:bug`, `type:feature`, `type:docs`, `type:security`,
  `type:governance`, `type:refactor`, `type:test`
- **Area:** `area:backend`, `area:frontend`, `area:database`, `area:migration`,
  `area:audit`, `area:auth`, `area:workflow`, `area:infrastructure`
- **Status:** `status:draft`, `status:needs-review`, `status:changes-requested`,
  `status:blocked`, `status:ready`, `status:deferred`
- **Risk:** `risk:critical`, `risk:high`, `risk:medium`, `risk:low`
- **Roadmap:** `roadmap:pr1` through `roadmap:pr15`

Do not create near-duplicate labels or create labels automatically from this policy.

## Repository cleanup safety checklist

- [ ] Current default branch and `origin/HEAD` identified
- [ ] Local worktree clean; remote refs fetched/pruned deliberately
- [ ] Every local and remote branch inventoried
- [ ] Every open PR base/head recorded
- [ ] Merged heads checked for graph reachability and squash tree equivalence
- [ ] Unique/unclear commits tagged or assigned for investigation
- [ ] New default contains the approved project history
- [ ] Open PRs merged or retargeted and diffs rechecked
- [ ] Branch protection/ruleset ready for the new default
- [ ] Legacy/default recovery tags pushed and verified
- [ ] Retention period elapsed
- [ ] Deletion commands reviewed branch by branch; no wildcard deletion
- [ ] Rollback procedure tested or inspectable before final cleanup
