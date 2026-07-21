# Project Memory (AI Snapshot)

**Purpose:** Long-term AI memory — a single point-in-time snapshot a new session can read to reconstruct working context without replaying history
**Authority:** Summary snapshot. Every fact below cites its authoritative source; the source controls if this snapshot drifts out of date. Not the same file as [`../docs/PROJECT_MEMORY.md`](../docs/PROJECT_MEMORY.md) — that file is the dated chronological decision log, this file is a current-state summary. See also [`CONTEXT.md`](CONTEXT.md) for the more volatile "right now" details (current PR, outstanding work, risks).
**Update trigger:** Any fact below becomes stale — check this file at the start of major work, update it at the end
**Maintainer:** Documentation/Governance Engineer

## Project purpose

The Medical Equipment Pool is a browser/PWA system used by hospital Equipment Pool operators to dispatch pool equipment (primarily infusion pumps and select shared equipment) to a first receiving ward and record its receipt back. It replaces a prior AppSheet-based spreadsheet process. It is not a patient-tracking, cleaning, maintenance, calibration, recall, or hospital-wide asset-lifecycle system.

Source: `docs/PROJECT_PLAYBOOK.md` ("Project purpose and boundary"); `knowledge/adr/ADR-001-equipment-pool-scope.md`.

## Architecture summary

- **Backend:** Async FastAPI (`backend/app/`), layered API -> services -> CRUD -> models, SQLAlchemy 2.0 async, Alembic migrations.
- **Database:** PostgreSQL (`postgres:16-alpine` in CI/dev), accessed via `asyncpg`. SQLite is used only for the fast default test run and is not sufficient evidence for PostgreSQL-specific behavior.
- **Frontend:** React/TypeScript/Vite single-page app, built as a PWA (`vite-plugin-pwa`).
- **Deployment:** Must remain portable to a managed platform; no design assumes direct access to hospital-managed servers.
- **CI:** `.github/workflows/ci.yml` — backend non-PostgreSQL tests, backend PostgreSQL-marked tests (fail-closed preflight gate, see below), standalone Alembic upgrade validation, frontend build, whitespace check. Least-privilege (`contents: read`, `persist-credentials: false`).

Source: `docs/ARCHITECTURE_DECISIONS.md`; `docs/PROJECT_WORKFLOW.md`.

## Stable business rules

See `docs/BUSINESS_RULES.md` for the full list with citations. Summary:

- Exactly four equipment states: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`.
- Cleaning is a physical activity that may happen before or after receipt is recorded; it is never represented as a state and never needs a separate workflow. A usable receipt ends at `AVAILABLE_AT_POOL`; a defective receipt ends at `UNAVAILABLE_DEFECTIVE`.
- Dispatch and receipt (`backend/app/services/borrow_service.py`) are the only paths that move equipment through `ISSUED_TO_WARD`, and the only paths that open/close a transaction (`app.crud.transaction.create()`/`close()`); administrative status maintenance is a separate, narrower path. `BorrowTransaction.status` is exactly `TransactionStatus.OPEN`/`CLOSED` (Roadmap PR7's lifecycle slice) — see `docs/BUSINESS_RULES.md`.
- Every new dispatch requires `ward_id` and `dispatch_type` (`routine_round`/`on_demand`, `DispatchType`); `routine_round` (one of the four confirmed fixed times `06:00`/`11:00`/`15:00`/`21:00`) is required exactly for `routine_round` dispatches and forbidden for `on_demand` (Roadmap PR7 7b slice, merged GitHub PR #20). `borrower_name`/`due_at`/`quantity` are rejected outright by `BorrowRequest` (`extra="forbid"`); every existing historical value is preserved — see `docs/BUSINESS_RULES.md`.
- Decommissioning must pass through `UNAVAILABLE_DEFECTIVE`; `AVAILABLE_AT_POOL` cannot skip directly to `DECOMMISSIONED`.
- No patient tracking, no ward-to-ward transfer tracking, no MEMS/PM/calibration/recall workflow.

## Stable identifiers

Exactly four, each with one fixed role — no substitution, no fifth identifier:

1. **Internal UUID** — relational primary key, never entered manually.
2. **BCM Code** — primary operator-facing identifier; the only manual-search identifier.
3. **Item No** — hospital QR-label identifier; QR lookup only; excluded from normal operator responses.
4. **Asset Number** — inventory metadata only; not searchable or scannable.

**"ME Code" is retired** and must not be used or reintroduced.

Source: `knowledge/adr/ADR-002-identifier-model.md` through `ADR-004`.

## Current workflow (requirement to merge)

```text
Requirement -> ChatGPT Architecture Review -> Claude Implementation -> Draft PR
  -> GitHub Actions CI -> Ready for review -> Codex Independent Review
  -> ChatGPT Project Governor Review -> Owner Approval -> Squash Merge
```

Claude writes code. Codex reviews code. ChatGPT governs architecture, roadmap, prompts, and review interpretation. The Owner makes business and merge decisions. No automatic merge; no Claude<->Codex repair loop; new commits invalidate prior review.

Source: `docs/PROJECT_WORKFLOW.md`.

## Current baseline

`f6f7c2ae0b12025dae2afd7f856bb489548c81cc` (branch `claude/medical-equipment-pool-0c7fz0`, squash merge of the API & Error Catalog documentation PR, GitHub PR #24) as of this snapshot. Always confirm against `knowledge/CONTEXT.md` and `docs/ROADMAP.md`, which are updated more frequently than this file.

## Completed Roadmap

Roadmap PR1-PR6 merged (security/availability foundation, structured exceptions, audit logging framework, transaction-number sequence, equipment identifier model, four-state equipment model), plus the Knowledge Layer v2 governance PR, the CI/AI-review-workflow infrastructure PR, the Knowledge & Governance Foundation PR, and both slices of Roadmap PR7 (transaction lifecycle model `OPEN`/`CLOSED`, GitHub PR #19; dispatch type/routine round/required ward_id/field cleanup, GitHub PR #20). Roadmap PR7 is now fully merged. Since then, four process/documentation-only PRs merged (no Roadmap PR number assigned, no code/business-rule/schema change): post-merge governance sync (GitHub PR #21), Test Infrastructure Cleanup (GitHub PR #22), Developer Documentation (GitHub PR #23), and the API & Error Catalog (GitHub PR #24). Full table with GitHub PR numbers and squash SHAs: `docs/ROADMAP.md`.

No Roadmap PR is currently in progress. PR8-PR15 (atomic receipt through observability/schema hygiene) are planned and not yet started — see `docs/ROADMAP.md`. Roadmap PR8 implementation has not been authorized or started; only its design document exists (`docs/design/PR8_IMPLEMENTATION_PLAN.md`, uncommitted, design-only).

## Current AI responsibilities

| Role | Responsibility |
|---|---|
| Claude | Implementation on an assigned, bounded task |
| Codex | Independent implementation review |
| ChatGPT | Architecture/roadmap governance, both before implementation and after Codex's review |

See `docs/PROJECT_WORKFLOW.md` for the full pipeline and `docs/REVIEW_CHECKLIST.md` for the shared review checklist.

## Never-change rules (do not implement without an approved Governance PR)

- Do not add a fifth equipment identifier or a fifth equipment state.
- Do not add a cleaning state, cleaning-complete action, or cleaning workflow.
- Do not add patient tracking (name, HN/MRN, bed number, named borrower).
- Do not add ward-to-ward transfer tracking.
- Do not bypass dispatch/receipt services to change equipment status.
- Do not edit merged migration history casually.
- Do not implement a later Roadmap PR ahead of its assigned order.
- Do not merge automatically, and do not run a Claude<->Codex auto-repair loop.

Full list with rationale: `docs/ARCHITECTURE_GUARDRAILS.md`.

## Current limitations

- The GitHub connector can return `403 Resource not accessible by integration` when submitting a formal Pull Request Review (not a silent downgrade). Preferred fallback: a formal `COMMENTED` review submitted through an authenticated browser session (this does satisfy review evidence). Last resort only: a PR Conversation comment, which is an incomplete status report and never counts as completed review evidence by itself.
- No branch-protection rule yet requires CI to pass before merge; enforced by process discipline instead.

Full detail and workarounds: `docs/KNOWN_LIMITATIONS.md`.
