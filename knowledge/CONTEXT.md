# Context

**Purpose:** Current project state — the most volatile document in the knowledge layer
**Authority:** Point-in-time status only. Does not restate rules or rationale — see `knowledge/PROJECT_MEMORY.md` for the stable snapshot this file assumes.
**Update trigger:** Every merged PR, and whenever a risk or outstanding item changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`f923f0aec8aa79fb4c33d2c1b0c05c08a057fe17` — squash commit of Roadmap PR8C, GitHub PR #31, on branch `claude/medical-equipment-pool-0c7fz0`. This sits on top of `4af6a4c623f24718f37241105c90425276e5ce7a` (post-PR8B documentation sync, GitHub PR #30), which sits on top of `d3e027b5a4ee7d99b38dfd0d263dc460c74eb5c5` (PR8B's frontend slice, GitHub PR #29) and `da4d76a640548e5a1d38ff3d7690695f950c85fe` (PR8B's backend slice, GitHub PR #28). **Roadmap PR8 (PR8A, PR8B, and PR8C) is now fully complete.**

## Current PR

None. Since Roadmap PR7 (7b slice) merged as GitHub PR #20, six process/documentation-only or governance PRs merged in order, plus four production code changes (PR8A, PR8B backend, PR8B frontend, PR8C):

- **GitHub PR #21** (`0ed6598`) — post-merge governance sync: brought `docs/ROADMAP.md`, `docs/DECISION_LOG.md`, `docs/BUSINESS_RULES.md`, and this knowledge layer up to date after PR #20 merged.
- **GitHub PR #22** (`06a736c`) — Test Infrastructure Cleanup: consolidated duplicated/inconsistent test helper functions (`auth_headers`, `create_ward`, `on_demand_borrow_payload`) into `backend/tests/conftest.py` as a single shared implementation. No test behavior change — verified via full local `pytest -m "not postgres"` (273 passed) and `pytest -m postgres` (78 passed) runs before merge.
- **GitHub PR #23** (`2e403fb`) — Developer Documentation: added `docs/development/{SETUP,TESTING,MIGRATIONS,CODE_REVIEW,CONTRIBUTING}.md`, written from direct inspection of current CI/Compose/Alembic config.
- **GitHub PR #24** (`f6f7c2a`) — API & Error Catalog: added `docs/api/{ERROR_CODES,dispatch,receipt,equipment,transactions}.md`, documenting the current request/response contracts and the full HTTP-status/error-code taxonomy from direct inspection of the current backend code.
- **GitHub PR #25** (`a308515`) — post-merge governance sync after PR21-PR24: brought `docs/ROADMAP.md` and this knowledge layer up to date.
- **GitHub PR #26** (`4820dba`) — **Roadmap PR8A, Atomic Receipt Concurrency Guard.** `app.crud.transaction.close()` now performs a single PostgreSQL conditional `UPDATE`, predicated on transaction ID plus `status = 'open'`, and decides the concurrency winner solely by the statement's affected rowcount — not by the pre-existing Python status check, which remains only as a fast-path for a genuine sequential repeat. Exactly one concurrent receipt request wins; every losing request rolls back **before** any business side effect (no equipment-status change, no status-history row, no audit row) and receives the existing `TRANSACTION_ALREADY_RETURNED` response — no new error code was introduced. The winning request's ORM object is explicitly refreshed from the persisted row before the equipment transition and the response are built, so the response always reflects committed state, never a stale in-memory value. Proven with deterministic PostgreSQL concurrency tests that force genuine contention across bursts of 1, 2, 5, 10, and 50 requests. No API contract, schema, or frontend change.
- **GitHub PR #28** (`da4d76a`) — **Roadmap PR8B, backend slice: receipt outcome contract narrowing.** `ReturnRequest.condition` (a four-value free-form string) is replaced entirely by `receipt_outcome: ReceiptOutcome` (`"usable" | "defective"`, `extra: "forbid"`, no compatibility alias). The backend alone maps `receipt_outcome` to an `EquipmentStatus` (`RECEIPT_OUTCOME_TO_STATUS`). Response splits into two mutually-exclusive fields, `receipt_outcome` (current) and `legacy_condition_on_return` (pre-PR8B history). No database migration. See `knowledge/adr/ADR-006-receipt-outcome-contract.md` and `docs/DECISION_LOG.md` ("Roadmap PR8 (PR8B slice)").
- **GitHub PR #29** (`d3e027b`) — **Roadmap PR8B, frontend slice: adopt `receipt_outcome`.** `frontend/src/types/index.ts`, `services/borrow.ts`, and `pages/ReturnPage.tsx` now submit `receipt_outcome` (a two-choice usable/defective selector) instead of the retired `condition` field; no lifecycle-state mapping added to the frontend. Deployed together with GitHub PR #28 per the coordinated-release requirement. `docs/TECH_DEBT.md` TD-006, which tracked the frontend/backend gap, is now `Closed`.
- **GitHub PR #30** (`4af6a4c`) — post-merge documentation sync after Roadmap PR8B: closed TD-006, updated ADR-006/DECISION_LOG/ROADMAP to reflect PR8B's completion.
- **GitHub PR #31** (`f923f0a`) — **Roadmap PR8C: race-loss-vs-genuine-repeat receipt rejection.** A losing receipt request now receives one of two distinguishable, machine-readable codes — `TRANSACTION_ALREADY_RETURNED` (genuine sequential repeat) or `RECEIPT_RACE_LOST` (this request's own read observed the transaction OPEN, but it lost the conditional-close race) — both still `409 Conflict`. `RECEIPT_RACE_LOST`'s wording attributes the outcome to another *request*, not another person. The frontend (`ReturnPage.tsx`) branches on the response's `code` field, never on free-text `detail`. No lifecycle, schema, migration, or request-contract change.

Roadmap PR7 (both slices, GitHub PR #19/#20) and Roadmap PR8 (all three slices, GitHub PR #26/#28/#29/#31) are now the most recent *fully completed* Roadmap-numbered items. See `knowledge/adr/ADR-005-transaction-model.md`, `knowledge/adr/ADR-006-receipt-outcome-contract.md`, `docs/DOMAIN_MODEL.md`, and `docs/DECISION_LOG.md` for PR7, PR8A, PR8B, and PR8C.

## Next planned PR

None from Roadmap PR8. The next unstarted item is Roadmap PR9 — Ward Correction Action (audited). See `docs/ROADMAP.md`.

## Outstanding work

- Roadmap PR9 through PR15 (ward correction, role consolidation, frontend terminology, inventory import, search/reporting, reliability/performance hardening, observability/schema hygiene) are planned, none merged yet.
- Confirmed future work not yet scheduled to a Roadmap PR: Shift Sessions, Standby Snapshots, managed-deployment target selection (`docs/ROADMAP.md`).
- `docs/TECH_DEBT.md` open items: TD-001 (equipment update/status `MissingGreenlet`), TD-002 (`0001_initial.py` uses current ORM metadata), TD-003 (CI now exists and fails closed, but branch protection requiring it is not enabled — partially resolved, needs re-assessment), TD-004 (naive `datetime.utcnow()`), TD-005 (temporary default/long-lived branch structure).

## Current risks

- **Branch protection is not enabled.** CI failing does not technically block a merge yet; the Repository Owner must manually re-verify CI status before every merge (`docs/KNOWN_LIMITATIONS.md`).
- **GitHub review-submission permission limitation.** Connector submission of a formal Pull Request Review can fail with `403 Resource not accessible by integration` (not a silent downgrade). Preferred fallback is a formal `COMMENTED` review submitted through an authenticated browser session, which does satisfy review evidence; a PR Conversation comment is only a last-resort, incomplete status report and never counts as completed review evidence by itself (`docs/KNOWN_LIMITATIONS.md`).
- **Default branch is still a temporary `claude/*` name**, not `main` (TD-005); repository-maintenance cutover is a separate, not-yet-executed operation (`docs/REPOSITORY_STRATEGY.md`).

## Related documents

| Concern | Document |
|---|---|
| Stable, less volatile snapshot | `knowledge/PROJECT_MEMORY.md` |
| Full roadmap detail | `docs/ROADMAP.md` |
| Conceptual change history | `knowledge/CHANGE_HISTORY.md` |
| Per-decision rationale | `docs/DECISION_LOG.md` |
