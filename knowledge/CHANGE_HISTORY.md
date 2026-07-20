# Change History

**Purpose:** Record important conceptual (mental-model) changes, distinct from per-PR decisions
**Authority:** Historical navigation. Each entry cites the decision that made it authoritative — see `docs/DECISION_LOG.md` for the full rationale behind each change.
**Update trigger:** A concept this project uses is added, retired, or redefined
**Maintainer:** Documentation/Governance Engineer

This file tracks *what changed in the shared mental model* over time, one line of context per concept. For the PR-by-PR rationale behind each change, see `docs/DECISION_LOG.md` (from Roadmap PR5 onward) and `docs/PROJECT_MEMORY.md` (Roadmap PR1 through Governance Pack v1.0).

## Cleaning status removed

A cleaning status/workflow was proposed early (a two-step "Return Received" / "Cleaning Confirmed" process, `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §6.1) and explicitly superseded before implementation: the hospital confirmed receipt is one atomic usable/defective operation, and the system never tracks cleaning. See `docs/ARCHITECTURE_DECISIONS.md` ("No cleaning workflow").

## ME Code retired

An earlier placeholder identifier, "ME Code," was used for every user-facing equipment-identification role (manual search, QR lookup, general reference) without distinguishing them. `knowledge/adr/ADR-002-identifier-model.md` retired it and replaced it with four distinct identifiers, each with one role. Any document still saying "ME Code" is out of date.

## BCM adopted

BCM Code was confirmed as the primary operator-facing identifier and the only identifier accepted by manual search, replacing the "ME Code" placeholder's search role. Implemented in Roadmap PR5 (GitHub PR #14). See `knowledge/adr/ADR-002-identifier-model.md`, `ADR-003-bcm-manual-search.md`.

## Item No visibility reduced

Item No (the hospital QR-label identifier) was confirmed as QR-lookup-only and explicitly excluded from normal operator-facing API responses — it may appear only in explicitly restricted administrative/import contexts. Implemented in Roadmap PR5; the API information-boundary rule is in `knowledge/architecture/api-information-boundaries.md`.

## Four-state model introduced

The equipment status model was collapsed to exactly four states (`AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`), retiring an earlier, wider set of statuses (preserved for history in a `legacy_status` column). Implemented in Roadmap PR6 (GitHub PR #16), migration `0006_equipment_state_model.py`.

## Dispatch/receipt and manual maintenance transitions separated

Roadmap PR6's review found that the equipment-status transition table did not distinguish dispatch/receipt-driven transitions from administrative/manual status maintenance, creating a path where manual maintenance could simulate a dispatch or receipt without going through the actual transaction lifecycle. Split into two transition tables; manual maintenance can never open or close a transaction. See `docs/BUSINESS_RULES.md` ("Dispatch/Return owns transaction lifecycle").

## Decommission path closed

Roadmap PR6's review also found `AVAILABLE_AT_POOL` could skip directly to `DECOMMISSIONED`. Closed: decommissioning must now pass through `UNAVAILABLE_DEFECTIVE`. See `docs/BUSINESS_RULES.md`.

## Process-required CI introduced

Through Roadmap PR3/PR4/PR5/PR6, PostgreSQL-backed integration tests existed but no GitHub Actions workflow ran them on a PR at all (`docs/TECH_DEBT.md` TD-003). The CI/AI-review-workflow infrastructure PR (GitHub PR #17) added a workflow required by the documented project process (`docs/PROJECT_WORKFLOW.md`), later hardened to fail closed rather than silently pass via skipped tests when PostgreSQL infrastructure is unusable. GitHub branch protection does not yet enforce this workflow as a required status check (`docs/KNOWN_LIMITATIONS.md`).

## Governance layer consolidated

The Knowledge & Governance Foundation PR (GitHub PR #18) is itself a conceptual change: it introduces a compact, cross-referenced quick-reference layer (`docs/PROJECT_WORKFLOW.md` and friends, `knowledge/PROJECT_MEMORY.md` and friends) alongside the existing detailed Governance Pack v1.0 (`docs/PROJECT_PLAYBOOK.md`'s Level 1-7 hierarchy), rather than replacing it.

## OPEN/CLOSED transaction lifecycle introduced

`BorrowTransaction.status` was collapsed from a three-value `borrowed`/`returned`/`overdue` field to an exactly-two-value `TransactionStatus` (`OPEN`/`CLOSED`), retiring "overdue" entirely — not just as a status value, but as a workflow: the `due_at`-driven hourly notification job (`app.worker.scheduler.check_overdue_returns`) was removed after Codex's PR7a review found it re-notified on every OPEN, overdue transaction on every hourly tick with no de-duplication (a BLOCKER). The approved MVP business model has no due-date/overdue workflow at all. The prior status is preserved for history in a `legacy_status` column, mirroring the four-state equipment model's pattern — with one refinement a second review round required: a row that genuinely had a pre-PR7 value (`borrowed`/`returned`/`overdue`) keeps that exact value, while a row already `open`/`closed` before the migration ran (no real legacy value exists for it) gets a canonical compatibility marker equal to its own status, never a fabricated legacy value — so downgrade remains possible for every database regardless of which population its rows started in. Implemented as Roadmap PR7's lifecycle slice ("7a"), migration `0007_transaction_lifecycle.py`, merged as GitHub PR #19. See `knowledge/adr/ADR-005-transaction-model.md`, `docs/DOMAIN_MODEL.md`, `docs/DECISION_LOG.md`.

## Dispatch type and routine round introduced; borrower_name/due_at/quantity retired from the write path

Roadmap PR7's remaining scope ("7b") added a `dispatch_type` domain (`routine_round`/`on_demand`) and a `routine_round` domain (the four confirmed fixed times `06:00`/`11:00`/`15:00`/`21:00`, an explicit MVP simplification pending a future, not-yet-scheduled Shift Sessions redesign) to `BorrowTransaction`, and made `ward_id` required for every new dispatch at the application layer. `borrower_name`, `due_at`, and `quantity` were retired as active write-path fields — no longer accepted by `BorrowRequest`, and `due_at` also dropped from `TransactionOut` — while every existing historical value for all three is preserved unmodified and remains readable (`borrower_name` still visible in `TransactionOut`; `due_at`/`quantity` still exportable via `app.services.report_service`). Both new columns and the relaxed `borrower_name` `NOT NULL` constraint are additive, non-destructive changes at the database level (migration `0008_dispatch_fields.py`); no existing row's `ward_id`, `dispatch_type`, or `routine_round` was fabricated or auto-assigned. See `knowledge/adr/ADR-005-transaction-model.md`, `docs/DOMAIN_MODEL.md`, `docs/DECISION_LOG.md`.
