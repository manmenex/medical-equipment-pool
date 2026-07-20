# Decision Log

**Purpose:** Concise, evidenced record of major decisions made from Roadmap PR5 through the CI/AI-review-workflow infrastructure PR, with rationale
**Authority:** Historical navigation; the source cited by each entry controls current policy. Continues `docs/PROJECT_MEMORY.md`, which covers Roadmap PR1 through Governance Pack v1.0 (the period immediately before this log begins).
**Update trigger:** Major decision made during a Roadmap or infrastructure PR's implementation or its review-fix rounds
**Maintainer:** Documentation/Governance Engineer

## Numbering note — read this first

**Roadmap PR number** and **GitHub PR number** are different sequences and must not be conflated:

- **Roadmap PR number** (PR1, PR2, PR3, ...) is the product-sequencing number from `docs/audits/04-consolidated-implementation-plan.md` Part D. It identifies *what* is being built.
- **GitHub PR number** (`#2`, `#14`, `#16`, ...) is simply this repository's sequential Pull Request counter. It identifies *which review thread* a change went through, and does not line up 1:1 with Roadmap PR numbers — governance/infrastructure PRs (Knowledge Layer v2, the CI/AI-review-workflow PR, this Knowledge & Governance Foundation PR) consume GitHub PR numbers without being numbered items in the original 15-PR Roadmap plan.

For example, **GitHub PR #14 implemented Roadmap PR5** (equipment identifiers). It is unrelated to "Roadmap PR14" (Reliability and Performance Hardening), which is still planned and unstarted — see `docs/ROADMAP.md`.

## Roadmap PR5 — Equipment identifier model (BCM Code / Item No)

- **Decision:** Add `bcm_code` and `item_no` as distinct, canonicalized, unique equipment columns; BCM Code is the only manual-search identifier, Item No is QR-lookup-only and excluded from normal operator responses.
- **Reason:** Resolve the identifier model per `knowledge/adr/ADR-002` through `ADR-004`, retiring the earlier "ME Code" placeholder.
- **Source:** GitHub PR #14; squash commit `099f0b8`; migration `0004_equipment_item_no_bcm_code.py`, later hardened by `0005_identifier_hardening.py`.
- **Status:** Merged.
- **Consequences:** Manual search and QR resolution use distinct code paths; Item No is stripped from operator-facing API responses (`knowledge/architecture/api-information-boundaries.md`).

## Governance — Knowledge Layer v2: identifier/QR architecture and authority hierarchy

- **Decision:** Formally resolve the identifier/QR architecture (`knowledge/adr/ADR-001` through `ADR-004`) and establish the repository's Level 1-7 source-of-truth hierarchy in `docs/PROJECT_PLAYBOOK.md`, ahead of Roadmap PR5's implementation reconciling against it.
- **Reason:** An implementation attempt for Roadmap PR5 was opened before this architecture was resolved; the architecture needed to be settled first so the implementation could be reconciled against a stable target rather than a moving one.
- **Source:** GitHub PR #15; squash commit `89b1f1e`; follow-up fix commit `1433be4` (GOV-H1: full-plan "ME Code" sweep; GOV-H2: authority hierarchy correction; GOV-L1: malformed prose).
- **Status:** Merged.
- **Consequences:** `knowledge/` became the authoritative source for equipment scope, identifier model, BCM manual search, and hospital QR identification, per the Playbook's topic-ownership table.

## Roadmap PR6 — Four-state equipment model

- **Decision:** Collapse the equipment status model to exactly four states (`AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`), adding a `legacy_status` column to preserve prior history.
- **Reason:** Confirmed target model per `docs/audits/04-consolidated-implementation-plan.md` Part A; a fifth "cleaning" state was explicitly rejected (see `docs/ARCHITECTURE_DECISIONS.md`, "No cleaning workflow").
- **Source:** GitHub PR #16; squash commit `9994c27`; migration `0006_equipment_state_model.py`.
- **Status:** Merged, including three review-fix rounds on the same PR before merge:
  - **H1:** Removed the `cleaning` field from the `ReturnRequest` OpenAPI contract — the contract must not expose a concept the system does not track.
  - **H2:** Split dispatch/receipt transitions from manual/administrative status-maintenance transitions into separate transition tables, so manual maintenance can never be used to simulate a dispatch or receipt.
  - **H3:** Closed a direct `AVAILABLE_AT_POOL -> DECOMMISSIONED` skip; decommissioning must pass through `UNAVAILABLE_DEFECTIVE`.
- **Consequences:** See `docs/BUSINESS_RULES.md` ("Four Equipment States", "Dispatch/Return owns transaction lifecycle", "Decommission requires AVAILABLE -> UNAVAILABLE_DEFECTIVE -> DECOMMISSIONED") — all three fix-round findings are now standing business rules, not just review comments.

## Infrastructure — GitHub Actions CI and AI review workflow

- **Decision:** Add required CI (backend dependency install, non-PostgreSQL and PostgreSQL-marked test suites, standalone Alembic upgrade validation, frontend build, whitespace check) and formally document the Claude -> Codex -> Owner review/merge sequence.
- **Reason:** `docs/TECH_DEBT.md` TD-003 ("No required PostgreSQL CI workflow") remained open; Roadmap PR7 was about to begin and needed a reliable, documented CI/review gate first.
- **Source:** GitHub PR #17; squash commit `3a1d30b`; `.github/workflows/ci.yml`; `docs/AI_REVIEW_WORKFLOW.md`.
- **Status:** Merged, including one review-fix round before merge:
  - The PostgreSQL CI job could report green via `pytest.skip()` when the database was unreachable or lacked scratch-database privilege, rather than failing. Fixed with `backend/scripts/postgres_ci_gate.py`, a fail-closed preflight (connect/authenticate/query/scratch-privilege) plus a post-run zero-skips assertion.
  - Added `permissions: contents: read` at the workflow level and `persist-credentials: false` on every checkout step (least privilege; no job needs write access).
- **Consequences:** TD-003 is partially resolved — the required CI workflow now exists and fails closed, but branch protection requiring it has not been enabled (a repository setting, not something a governance PR mutates — see `docs/REPOSITORY_STRATEGY.md`, "Branch protection and ruleset recommendation"). TD-003 should be re-assessed, not silently closed, by whoever next reviews `docs/TECH_DEBT.md`.
- **Limitation discovered during review:** the GitHub Connector used for review submission returned `403 Resource not accessible by integration` when attempting to submit a formal Pull Request Review. See `docs/KNOWN_LIMITATIONS.md` for the workaround this log's own review cycle used (a top-level PR Conversation comment whose body states "Substantive decision: APPROVE").

## Governance — Knowledge & Governance Foundation (this PR)

- **Decision:** Add a compact, current-state documentation/knowledge layer (`docs/PROJECT_WORKFLOW.md`, `BUSINESS_RULES.md`, `DECISION_LOG.md`, `ROADMAP.md`, `REVIEW_CHECKLIST.md`, `KNOWN_LIMITATIONS.md`; `knowledge/PROJECT_MEMORY.md`, `CONTEXT.md`, `CHANGE_HISTORY.md`) that summarizes and cross-references the existing Governance Pack v1.0, rather than replacing it.
- **Reason:** The existing hierarchy (`docs/PROJECT_PLAYBOOK.md` Levels 1-7) is detailed and authoritative but requires reading several documents to reconstruct current state; a single fast-onboarding layer reduces the risk of a future AI session acting on stale or incomplete context.
- **Source:** This PR; branch `docs/pr18-knowledge-governance-foundation`; baseline `3a1d30b4560f77867dfe36e925c1f3ef97d71596`.
- **Status:** Draft, pending review, including one review-fix round before merge:
  - `docs/BUSINESS_RULES.md` presented the approved target `OPEN`/`CLOSED` transaction model (Roadmap PR7) as already implemented. Fixed to separate current implementation (`borrowed`/`returned`/`overdue`, required `borrower_name`, nullable `due_at`/`ward_id`) from the approved target, with an explicit instruction not to implement PR7 ahead of its assigned order.
  - Cleaning wording ("performed during receipt") overstated ordering. Fixed to state cleaning may occur before or after the receipt record, is never a state, and needs no separate workflow.
  - `docs/KNOWN_LIMITATIONS.md` used unsupported "silently downgrade" wording for the GitHub connector's review-submission behavior. Fixed to describe the actual observed `403` failure, the PR-Conversation-comment workaround, the unreliable browser fallback, and that reading PRs/diffs/reviews/CI is unaffected.
  - Wording implying GitHub enforces CI as a merge gate was clarified everywhere it appeared in this PR's files: CI is required by the documented process, not by branch protection, which is not yet enabled.
  - Added the Knowledge Update Policy (this section's own list of files) to `docs/PROJECT_WORKFLOW.md` and `docs/REVIEW_CHECKLIST.md`.
- **Consequences:** Every new file is written as a summary that cites its authoritative source and defers to it on conflict — see each file's own "Authority" line. `docs/ARCHITECTURE_GUARDRAILS.md` gained two invariants (no new identifiers, no bypassing dispatch/receipt services) that were true in practice but not previously written down. `AGENTS.md` was trimmed to reference this layer instead of embedding long-form guardrail rationale.
