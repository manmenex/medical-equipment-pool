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

## Offline operation (PR25E) limitations

Design and rationale: `docs/design/PR25D_OFFLINE_OPERATION_PLAN.md` (see 18.1); guides: `docs/runbooks/PR25E_OPERATOR_GUIDE_TH.md`, `docs/runbooks/PR25E_REVIEWER_GUIDE_TH.md`. Not yet exercised on real devices (slice E1).

1. **Duplicate dispatch when the network drops mid-submit.** If a request commits on the server but the response is lost, the client keeps the row and re-sends the same `op_id`; this is idempotent. But if the operator, seeing "pending", re-enters the same dispatch as a new entry, it becomes a second operation. The server records it as a `conflict` (equipment no longer available) for review, and a local double-entry guard blocks the repeat on the same device. A repeat from another device is only caught by review.
2. **Shared device: receipt of another user's unsent dispatch.** A receipt can be keyed on a device against a dispatch another user recorded there and has not yet sent. The two operations belong to different users' queues; the receipt waits (`DEPENDENCY_MISSING`, 48 h) until the dispatch is sent or adopted, otherwise it lands in review.
3. **Adoption (S5b).** (a) The "รายการค้างของผู้ใช้อื่น" panel is on `/sync-review` only; no badge elsewhere. (b) Only `pending`/`sending` rows can be adopted, not `conflict`, `rejected` or `held`. (c) The design 8.3 "Check other users' recent entries (48 h)" action is not built. (d) No offline-logout warning about unsynced items.
4. **Timeline scan cap.** The per-equipment timeline reads at most 2000 reviewable ledger rows (`MAX_SCAN_ROWS`); beyond that older rows are not shown.
5. **Clock offset via the `Date` header.** The client refines its clock offset from the `Date` response header. Browsers expose it to scripts only for same-origin responses (or when the server lists it in `Access-Control-Expose-Headers`); on a cross-origin deployment the offset updates from snapshot `server_time` only, which is less frequent.
6. **`auth_time` after deploy.** Adoption requires the JWT `auth_time` claim (password login within 15 minutes). Tokens issued before the release that added it have no `auth_time` and are treated as not fresh (fail closed): affected users log in again before adopting. Token refresh does not renew `auth_time`.
7. **Business time is resolution time.** Operations applied by a reviewer (Apply now, Apply sequence) count at the time of resolution, not the time of the event, in PR16 `business_date`/`shift` reporting; only `OP_TOO_OLD` items keep their stored time.
8. **No automatic resolution.** `SYNC_AUTO_SEQUENCE` is not implemented; every conflict needs a human (Owner decisions D7, D8). Collision statistics and CSV are the evidence for the post-pilot decision.
9. **Scope.** QR scanning and Item No / Asset Number search are online only; no offline admin, master data or reports; no sync while the app is closed (iOS does not allow it); unsynced data is protected only by the device screen lock; `transaction_no` is hidden offline and may be reissued after a restore.

**Impact:** Items 1 to 3 and 7 are handled by the review page; the rest are accepted for the pilot.

**Resolution path:** Follow-up slices after the pilot, to be scheduled in `docs/ROADMAP.md`.

## Related documents

| Concern | Document |
|---|---|
| Pipeline, roles, and merge rules | `docs/PROJECT_WORKFLOW.md` |
| Reviewer-agent prompt | `docs/prompts/codex-pr-review.md` |
| Where these limitations were discovered | `docs/DECISION_LOG.md` |
| Repository settings that cannot be changed through a governance PR | `docs/REPOSITORY_STRATEGY.md` |
| Open technical debt | `docs/TECH_DEBT.md` |
