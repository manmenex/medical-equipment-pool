# Known Limitations

**Purpose:** Single home for current process/tooling limitations that affect how work gets reviewed or merged, and their workarounds
**Authority:** Operational fact-tracking, not policy. A workaround here does not change `docs/PROJECT_WORKFLOW.md` or `docs/prompts/codex-pr-review.md` — it describes how to satisfy them given a current tooling constraint.
**Update trigger:** A limitation is discovered, its workaround changes, or it is resolved
**Maintainer:** Repository Owner

## GitHub Connector: Pull Request Review submission may fail with `403 Resource not accessible by integration`

**Symptom:** When a reviewer (Codex or ChatGPT, acting through the GitHub connector) attempts to submit a formal Pull Request Review (an `APPROVE`, `REQUEST_CHANGES`, or `COMMENT`-state review object, as opposed to a plain PR Conversation comment), the call can fail outright with `403 Resource not accessible by integration`. This is observed behavior, not a downgrade — the review submission does not succeed. It is independent of the separate, already-documented restriction that a reviewer acting as the same account that owns the PR can only submit a `COMMENT`-state review (`docs/prompts/codex-pr-review.md`, GitHub Review Submission Policy).

**Impact:** The affected reviewer cannot create a formal GitHub Pull Request Review object at all in the affected session — not `APPROVE`, not `REQUEST_CHANGES`, and not even `COMMENT`-state via the review-submission endpoint. The connector limitation does **not** prevent reading the PR, its diff, existing reviews, or CI status — only the write path for creating a new formal review is affected.

**Workaround:**

- The reviewer posts the review as a **top-level PR Conversation comment** instead of a formal Review object, stating the substantive decision explicitly at the start — e.g. `Substantive decision: APPROVE` or `Substantive decision: REQUEST_CHANGES` — using the same required content `docs/prompts/codex-pr-review.md` specifies for a review body.
- This is a manual workaround: it requires deliberately choosing the comment-submission path instead of the review-submission path when the latter is unavailable.
- A browser-based fallback (submitting the review manually through the GitHub web UI) may be available in some sessions, but is not guaranteed — it can be unavailable or fail depending on the session's environment. Do not assume it as a reliable substitute.
- Readers (the Repository Owner, `docs/PROJECT_WORKFLOW.md` step 9, and any later AI session) must check for the stated decision in PR Conversation comments, not only in the formal GitHub Reviews list, when this limitation was in effect for a given review round.
- If neither the formal review nor the comment workaround succeeds, the reviewer reports the failure and does not claim the review is complete, per `docs/prompts/codex-pr-review.md`'s existing verification-after-submission requirement.

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
