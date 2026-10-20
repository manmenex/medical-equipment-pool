# Known Limitations

**Purpose:** Single home for current process/tooling limitations that affect how work gets reviewed or merged, and their workarounds
**Authority:** Operational fact-tracking, not policy. A workaround here does not change `docs/PROJECT_WORKFLOW.md` or the reviewer-agent prompt `docs/prompts/codex-pr-review.md`; it describes how to satisfy them given a current tooling constraint.
**Update trigger:** A limitation is discovered, its workaround changes, or it is resolved
**Maintainer:** Repository Owner

## No branch protection / required status checks enabled yet

**Symptom:** `.github/workflows/ci.yml` exists and fails closed (see `docs/DECISION_LOG.md`, "Infrastructure — GitHub Actions CI and AI review workflow"), but the base branch has no branch-protection rule requiring it to pass before merge.

**Impact:** A merge is not technically blocked by a red or pending check; the CI gate in `docs/PROJECT_WORKFLOW.md` (step 4) is currently enforced by process discipline, not repository configuration.

**Workaround:** The orchestrator re-verifies CI status on the exact head SHA immediately before merging, and merges with an expected-head-SHA guard (`docs/PROJECT_WORKFLOW.md`).

**Resolution path:** A repository-settings change the Repository Owner performs directly — see `docs/REPOSITORY_STRATEGY.md`, "Branch protection and ruleset recommendation" ("requires applicable status checks once reliable CI exists... governance tasks do not mutate them"). Tracked as `docs/TECH_DEBT.md` TD-003 (partially resolved).

## Offline adoption (PR25E S5b) deferrals

**Symptom / limits:** (1) The "รายการค้างของผู้ใช้อื่น" panel appears only on `/sync-review`; there is no badge or link elsewhere (status chip, nav) pointing to other users' leftover items. (2) Only `pending`/`sending` rows can be adopted; another user's `conflict`, `rejected` and `held` rows are not adoptable (they hold later ops on the same equipment instead). (3) The design 8.3 "Check other users' recent entries (48 h)" recovery action (verify other users' journal and re-queue unknown ones) is not built. (4) There is no offline-logout warning about unsynced items.

**Impact:** Stranded items are only found by a pool user who opens the review page; restore-recovery of other users' journal entries stays manual.

**Resolution path:** Follow-up slices after S5b, to be scheduled in `docs/ROADMAP.md`.

## Related documents

| Concern | Document |
|---|---|
| Pipeline, roles, and merge rules | `docs/PROJECT_WORKFLOW.md` |
| Reviewer-agent prompt | `docs/prompts/codex-pr-review.md` |
| Where these limitations were discovered | `docs/DECISION_LOG.md` |
| Repository settings that cannot be changed through a governance PR | `docs/REPOSITORY_STRATEGY.md` |
| Open technical debt | `docs/TECH_DEBT.md` |
