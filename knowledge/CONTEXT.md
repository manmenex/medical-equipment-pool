# Context

**Purpose:** Current project state — the most volatile document in the knowledge layer
**Authority:** Point-in-time status only. Does not restate rules or rationale — see `knowledge/PROJECT_MEMORY.md` for the stable snapshot this file assumes.
**Update trigger:** Every merged PR, and whenever a risk or outstanding item changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`d3e027b5a4ee7d99b38dfd0d263dc460c74eb5c5` — squash commit of Roadmap PR8B's frontend slice, GitHub PR #29, on branch `claude/medical-equipment-pool-0c7fz0`. This sits on top of `da4d76a640548e5a1d38ff3d7690695f950c85fe` (PR8B's backend slice, GitHub PR #28).

## Current PR

None. Since Roadmap PR7 (7b slice) merged as GitHub PR #20, five process/documentation-only or governance PRs merged in order, plus three production code changes (PR8A, PR8B backend, PR8B frontend):

- **GitHub PR #21** (`0ed6598`) — post-merge governance sync: brought `docs/ROADMAP.md`, `docs/DECISION_LOG.md`, `docs/BUSINESS_RULES.md`, and this knowledge layer up to date after PR #20 merged.
- **GitHub PR #22** (`06a736c`) — Test Infrastructure Cleanup: consolidated duplicated/inconsistent test helper functions (`auth_headers`, `create_ward`, `on_demand_borrow_payload`) into `backend/tests/conftest.py` as a single shared implementation. No test behavior change — verified via full local `pytest -m "not postgres"` (273 passed) and `pytest -m postgres` (78 passed) runs before merge.
- **GitHub PR #23** (`2e403fb`) — Developer Documentation: added `docs/development/{SETUP,TESTING,MIGRATIONS,CODE_REVIEW,CONTRIBUTING}.md`, written from direct inspection of current CI/Compose/Alembic config.
- **GitHub PR #24** (`f6f7c2a`) — API & Error Catalog: added `docs/api/{ERROR_CODES,dispatch,receipt,equipment,transactions}.md`, documenting the current request/response contracts and the full HTTP-status/error-code taxonomy from direct inspection of the current backend code.
- **GitHub PR #25** (`a308515`) — post-merge governance sync after PR21-PR24: brought `docs/ROADMAP.md` and this knowledge layer up to date.
- **GitHub PR #26** (`4820dba`) — **Roadmap PR8A, Atomic Receipt Concurrency Guard.** `app.crud.transaction.close()` now performs a single PostgreSQL conditional `UPDATE`, predicated on transaction ID plus `status = 'open'`, and decides the concurrency winner solely by the statement's affected rowcount — not by the pre-existing Python status check, which remains only as a fast-path for a genuine sequential repeat. Exactly one concurrent receipt request wins; every losing request rolls back **before** any business side effect (no equipment-status change, no status-history row, no audit row) and receives the existing `TRANSACTION_ALREADY_RETURNED` response — no new error code was introduced. The winning request's ORM object is explicitly refreshed from the persisted row before the equipment transition and the response are built, so the response always reflects committed state, never a stale in-memory value. Proven with deterministic PostgreSQL concurrency tests that force genuine contention across bursts of 1, 2, 5, 10, and 50 requests. No API contract, schema, or frontend change.
- **GitHub PR #28** (`da4d76a`) — **Roadmap PR8B, backend slice: receipt outcome contract narrowing.** `ReturnRequest.condition` (a four-value free-form string) is replaced entirely by `receipt_outcome: ReceiptOutcome` (`"usable" | "defective"`, `extra: "forbid"`, no compatibility alias). The backend alone maps `receipt_outcome` to an `EquipmentStatus` (`RECEIPT_OUTCOME_TO_STATUS`). Response splits into two mutually-exclusive fields, `receipt_outcome` (current) and `legacy_condition_on_return` (pre-PR8B history). No database migration. See `knowledge/adr/ADR-006-receipt-outcome-contract.md` and `docs/DECISION_LOG.md` ("Roadmap PR8 (PR8B slice)").
- **GitHub PR #29** (`d3e027b`) — **Roadmap PR8B, frontend slice: adopt `receipt_outcome`.** `frontend/src/types/index.ts`, `services/borrow.ts`, and `pages/ReturnPage.tsx` now submit `receipt_outcome` (a two-choice usable/defective selector) instead of the retired `condition` field; no lifecycle-state mapping added to the frontend. Deployed together with GitHub PR #28 per the coordinated-release requirement. `docs/TECH_DEBT.md` TD-006, which tracked the frontend/backend gap, is now `Closed`. **Roadmap PR8's remaining scope, distinguishing a race-loss rejection from a genuine repeat rejection, is separately named Roadmap PR8 (PR8C slice) and has not been started.**

Roadmap PR7 (both slices, GitHub PR #19/#20) and Roadmap PR8 (PR8A + PR8B, both slices of PR8B) are the most recent *fully complete* Roadmap-numbered work; Roadmap PR8 as a whole is not complete until PR8C also merges (not started). See `knowledge/adr/ADR-005-transaction-model.md`, `docs/DOMAIN_MODEL.md`, and `docs/DECISION_LOG.md` for PR7, PR8A, and PR8B.

## Next planned PR

Roadmap PR8 (PR8C slice) — distinguishable race-loss-vs-genuine-repeat receipt rejection (error message/code) — **not started**. Both causes currently share `409 TRANSACTION_ALREADY_RETURNED` until PR8C lands. See `knowledge/adr/ADR-006-receipt-outcome-contract.md` ("Not decided here") and `docs/ROADMAP.md`.

## Outstanding work

- Roadmap PR8 (PR8C slice, not started) through PR15 (race-vs-repeat distinction, ward correction, role consolidation, frontend terminology, inventory import, search/reporting, reliability/performance hardening, observability/schema hygiene) are planned, none merged yet.
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
