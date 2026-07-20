# Known Limitations

**Purpose:** Single home for current process/tooling limitations that affect how work gets reviewed or merged, and their workarounds
**Authority:** Operational fact-tracking, not policy. A workaround here does not change `docs/PROJECT_WORKFLOW.md` or `docs/prompts/codex-pr-review.md` — it describes how to satisfy them given a current tooling constraint.
**Update trigger:** A limitation is discovered, its workaround changes, or it is resolved
**Maintainer:** Repository Owner

## GitHub Connector: `403 Resource not accessible by integration` on Pull Request Reviews

**Symptom:** When a reviewer (Codex or ChatGPT, acting through the GitHub connector) attempts to submit a Pull Request review with a native `APPROVE` or `REQUEST_CHANGES` state, the review-creation call can fail with `403 Resource not accessible by integration`, or silently downgrade to a `COMMENT`-state review — depending on the connector's granted permissions/installation scope for this repository, and independently of the separate, already-documented restriction that a reviewer acting as the same account that owns the PR can only submit `COMMENT` (`docs/prompts/codex-pr-review.md`, GitHub Review Submission Policy).

**Impact:** The GitHub UI's colored review-state label (green "Approved" / red "Changes requested") cannot be relied on alone to determine a review's actual decision. A `COMMENT`-state review is not automatically a weak or incomplete review — it may be the only state the connector's current permissions allow for an otherwise complete, decisive review.

**Workaround:**

- The reviewer always states the **substantive decision** explicitly in the first lines of the review body — e.g. `Substantive decision: APPROVE` or `Substantive decision: REQUEST_CHANGES` — regardless of which native GitHub review-state action the submission actually used.
- Readers (the Repository Owner, `docs/PROJECT_WORKFLOW.md` step 9, and any later AI session) must read the stated decision from the review body text, not infer it from the GitHub review-state badge.
- If submission itself fails (not just downgrades to `COMMENT`), the reviewer reports the failure and does not claim the review is complete, per `docs/prompts/codex-pr-review.md`'s existing verification-after-submission requirement.

**Resolution path:** Not resolved by this repository's code or governance — it depends on the GitHub App/connector installation's granted permissions (`pull_requests: write` at minimum) for this repository. Re-check when the connector installation is reconfigured.

## No branch protection / required status checks enabled yet

**Symptom:** `.github/workflows/ci.yml` exists and fails closed (see `docs/DECISION_LOG.md`, "Infrastructure — GitHub Actions CI and AI review workflow"), but the base branch has no branch-protection rule requiring it to pass before merge.

**Impact:** A merge is not technically blocked by a red or pending check; the CI gate in `docs/PROJECT_WORKFLOW.md` step 5 is currently enforced by process discipline, not repository configuration.

**Workaround:** The Repository Owner manually re-verifies CI status on the exact head SHA before merging (see `docs/AI_REVIEW_WORKFLOW.md`'s expected-head-SHA re-verification practice).

**Resolution path:** A repository-settings change the Repository Owner performs directly — see `docs/REPOSITORY_STRATEGY.md`, "Branch protection and ruleset recommendation" ("requires applicable status checks once reliable CI exists... governance tasks do not mutate them"). Tracked as `docs/TECH_DEBT.md` TD-003 (partially resolved).

## Related documents

| Concern | Document |
|---|---|
| Review submission policy this workaround supports | `docs/prompts/codex-pr-review.md` |
| Where these limitations were discovered | `docs/DECISION_LOG.md` |
| Repository settings that cannot be changed through a governance PR | `docs/REPOSITORY_STRATEGY.md` |
| Open technical debt | `docs/TECH_DEBT.md` |
