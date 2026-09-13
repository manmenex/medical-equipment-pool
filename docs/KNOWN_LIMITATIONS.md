# Known Limitations

**Purpose:** Single home for current process/tooling limitations that affect how work gets reviewed or merged, and their workarounds
**Authority:** Operational fact-tracking, not policy. A workaround here does not change `docs/PROJECT_WORKFLOW.md` or `docs/prompts/codex-pr-review.md` — it describes how to satisfy them given a current tooling constraint.
**Update trigger:** A limitation is discovered, its workaround changes, or it is resolved
**Maintainer:** Repository Owner

## GitHub Connector: Pull Request Review submission may fail with `403 Resource not accessible by integration`

**Symptom:** When a reviewer (Codex or ChatGPT, acting through the GitHub connector) attempts to submit a formal Pull Request Review (an `APPROVE`, `REQUEST_CHANGES`, or `COMMENT`-state review object), the call can fail outright with `403 Resource not accessible by integration`. This is observed behavior: the review submission does not succeed. There is no silent downgrade to a `COMMENT`-state review — the connector call either creates the requested formal review object or it fails. This is independent of the separate, already-documented restriction that a reviewer acting as the same account that owns the PR can only submit a `COMMENT`-state review (`docs/prompts/codex-pr-review.md`, GitHub Review Submission Policy).

**Impact:** The affected reviewer cannot create a formal GitHub Pull Request Review object through the connector in the affected session. The connector limitation does **not** prevent reading the PR, its diff, existing reviews, or CI status — only the write path for creating a new formal review is affected.

**Fallback policy — two tiers, not interchangeable:**

1. **Formal fallback (preferred):** Submit a GitHub Pull Request Review with state `COMMENTED` through an authenticated browser session (not the connector). This **is** a formal Pull Request Review object — it satisfies the project's independent-review evidence requirement (`docs/prompts/codex-pr-review.md`) when a native `APPROVE`/`REQUEST_CHANGES` action is unavailable because the reviewer is the same account that owns the PR. It still requires the review body to state the substantive decision explicitly at the start — e.g. `Substantive decision: APPROVE` — using the same required content `docs/prompts/codex-pr-review.md` specifies for a review body.
2. **Last-resort status reporting (only when the formal fallback is also unavailable):** A top-level PR Conversation comment. This is **not** a Pull Request Review and must never be described as satisfying the formal review policy. It may only be used to record findings and report the tool failure when **neither** connector review submission **nor** browser review submission is available. The Repository Owner must not treat a Conversation comment alone as completed independent-review evidence.

**Workaround:**

- Always attempt the connector review submission first.
- If it fails with `403` (or any other error), attempt the formal browser fallback (tier 1) before falling back further.
- Only if the browser fallback is also unavailable or fails does the reviewer fall back to a Conversation comment (tier 2) — and the reviewer must state plainly, in that comment, that this is an incomplete status report, not a completed formal review, and why.
- Readers (the Repository Owner, `docs/PROJECT_WORKFLOW.md` step 9, and any later AI session) check the formal GitHub Reviews list first. A Conversation comment is read only as a status report of what was attempted and why formal review submission was not completed — never as review evidence by itself.
- The reviewer reports which tier was actually used and does not claim the review is complete unless a formal Review object (tier 1, or a successful connector submission) exists, per `docs/prompts/codex-pr-review.md`'s existing verification-after-submission requirement.

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
