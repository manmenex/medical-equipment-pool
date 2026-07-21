# Context

**Purpose:** Current project state — the most volatile document in the knowledge layer
**Authority:** Point-in-time status only. Does not restate rules or rationale — see `knowledge/PROJECT_MEMORY.md` for the stable snapshot this file assumes.
**Update trigger:** Every merged PR, and whenever a risk or outstanding item changes
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`f6f7c2ae0b12025dae2afd7f856bb489548c81cc` — squash commit of the API & Error Catalog documentation PR, GitHub PR #24, on branch `claude/medical-equipment-pool-0c7fz0`.

## Current PR

None. Since Roadmap PR7 (7b slice) merged as GitHub PR #20, four process/documentation-only PRs merged in order, none touching production code, business rules, or schema:

- **GitHub PR #21** (`0ed6598`) — post-merge governance sync: brought `docs/ROADMAP.md`, `docs/DECISION_LOG.md`, `docs/BUSINESS_RULES.md`, and this knowledge layer up to date after PR #20 merged.
- **GitHub PR #22** (`06a736c`) — Test Infrastructure Cleanup: consolidated duplicated/inconsistent test helper functions (`auth_headers`, `create_ward`, `on_demand_borrow_payload`) into `backend/tests/conftest.py` as a single shared implementation. No test behavior change — verified via full local `pytest -m "not postgres"` (273 passed) and `pytest -m postgres` (78 passed) runs before merge.
- **GitHub PR #23** (`2e403fb`) — Developer Documentation: added `docs/development/{SETUP,TESTING,MIGRATIONS,CODE_REVIEW,CONTRIBUTING}.md`, written from direct inspection of current CI/Compose/Alembic config.
- **GitHub PR #24** (`f6f7c2a`) — API & Error Catalog: added `docs/api/{ERROR_CODES,dispatch,receipt,equipment,transactions}.md`, documenting the current request/response contracts and the full HTTP-status/error-code taxonomy from direct inspection of the current backend code.

Roadmap PR7 (both slices, GitHub PR #19/#20) remains the most recent Roadmap-numbered work merged. See `knowledge/adr/ADR-005-transaction-model.md`, `docs/DOMAIN_MODEL.md`, and `docs/DECISION_LOG.md` for PR7 itself.

## Next planned PR

Roadmap PR8 (Atomic Single-Operation Equipment Receipt with concurrency guard) — not yet started. Concurrent-receipt protection remains mandatory before pilot deployment.

## Outstanding work

- Roadmap PR8 through PR15 (atomic receipt, ward correction, role consolidation, frontend terminology, inventory import, search/reporting, reliability/performance hardening, observability/schema hygiene) are planned and not started.
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
