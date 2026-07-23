# Business Rules

**Purpose:** Compact, current-state summary of approved Medical Equipment Pool business rules, for fast AI/human onboarding
**Authority:** Summary only. Each rule cites its authoritative source; the cited source controls in case of any apparent conflict with this file. This file does not add, relax, or reinterpret a rule.
**Update trigger:** A rule below is confirmed changed by an approved ADR, `docs/ARCHITECTURE_DECISIONS.md` entry, or Governance PR
**Maintainer:** Architecture Owner

Only approved, confirmed rules are listed here. Do not add a rule that has not been confirmed through the sources below.

## Four Equipment States

Equipment has exactly four states: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`. No fifth state (in particular, no cleaning-related state) exists.

- Source: `docs/HOSPITAL_DOMAIN_MODEL.md` ("Confirmed workflow"); `docs/audits/04-consolidated-implementation-plan.md` Part A; implemented by migration `0006_equipment_state_model.py` and `backend/app/models/equipment.py`.

## Cleaning is not tracked

Cleaning is a physical operational activity, not a digital one. It may occur before or after the receipt record is entered — the system does not require or assume any particular order. Cleaning is not represented as an equipment state and does not require a separate cleaning workflow: there is no cleaning state, cleaning-complete action, or cleaning-status field. Equipment receipt is one atomic digital operation with a binary outcome — a usable receipt ends at `AVAILABLE_AT_POOL`; a defective receipt ends at `UNAVAILABLE_DEFECTIVE`.

- Source: `docs/ARCHITECTURE_DECISIONS.md` ("No cleaning workflow"); `AGENTS.md` (Domain Guardrails); `docs/audits/04-consolidated-implementation-plan.md` Part B.1. The binary outcome itself is now the request/response contract's own `receipt_outcome` field (Roadmap PR8B, `knowledge/adr/ADR-006-receipt-outcome-contract.md`), not only an internal mapping.

## UUID is relational identity

The internal UUID is the permanent relational primary key for an equipment record. It is never entered manually by an operator and is the only identifier borrow/return records reference. It does not change even if BCM Code, Item No, or Asset Number are later corrected or reassigned.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/business-rules/equipment-pool.md`.

## BCM is the manual identifier

BCM Code is the primary operator-facing identifier and the only identifier accepted by manual equipment search. It is unique across all equipment; uniqueness and search matching are enforced on its canonical persisted form.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/adr/ADR-003-bcm-manual-search.md`; `knowledge/architecture/identifiers.md`.

## Item No is internal QR lookup only

Item No is the identifier encoded in the hospital's existing QR labels. It is used only for exact QR lookup, is unavailable as a manual-search identifier, and is absent from normal operator-facing response contracts — it may appear only in explicitly restricted administrative/import contexts.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/adr/ADR-004-hospital-item-no-qr.md`; `knowledge/architecture/api-information-boundaries.md`.

**"ME Code" is retired.** It does not name any current or planned identifier; any document or task still using it means BCM Code or Item No and should be corrected.

## Dispatch/Return owns transaction lifecycle

Dispatch and receipt (`backend/app/services/borrow_service.py`) are the only paths that move equipment through `ISSUED_TO_WARD`, and the only paths that open (`app.crud.transaction.create()`) or close (`app.crud.transaction.close()`) a transaction — administrative/manual equipment-status maintenance is a separate, narrower transition set that never originates or targets `ISSUED_TO_WARD` and never touches transaction status at all.

`BorrowTransaction.status` is exactly two values, `TransactionStatus.OPEN` / `TransactionStatus.CLOSED` (`backend/app/models/transaction.py`; Roadmap PR7; `knowledge/adr/ADR-005-transaction-model.md`), matching `docs/HOSPITAL_DOMAIN_MODEL.md`'s confirmed `OPEN`/`CLOSED` workflow. An overdue (`due_at` passed) transaction remains `OPEN` — the approved MVP business model has no due-date/overdue workflow at all, not a status value and not a notification. The `due_at`-driven overdue notification job (`app.worker.scheduler.check_overdue_returns`) has been removed and is not registered with the scheduler (Codex PR7a review round 1, BLOCKER: the job re-notified on every hourly tick with no de-duplication) — see `knowledge/adr/ADR-005-transaction-model.md` decision 3.

**Roadmap PR7 (7b slice), merged (GitHub PR #20):** every new dispatch (`app.schemas.transaction.BorrowRequest`) must carry a `ward_id` and a `dispatch_type` (`routine_round` or `on_demand`, `backend/app/models/transaction.py`'s `DispatchType`); a `routine_round` (one of the four confirmed fixed times `06:00`/`11:00`/`15:00`/`21:00`, `RoutineRound`) is required exactly when `dispatch_type == routine_round` and forbidden for `on_demand`. `BorrowRequest` rejects any unrecognized field outright (`extra="forbid"`), so `borrower_name`, `due_at`, and `quantity` are not merely unaccepted but actively rejected with a 422; `due_at` is also removed from `TransactionOut`. Every existing historical value for all three fields is preserved as read-only history, never erased or backfilled — `borrower_name` remains visible in `TransactionOut`; `due_at`/`quantity` remain queryable via `app.services.report_service`'s export, which reads them directly from the ORM row. An existing row's `ward_id`/`dispatch_type`/`routine_round` are never fabricated for historical data — left `NULL`. `ward_id` is validated proactively (400 `INVALID_INPUT` if it does not reference an existing ward), distinct from the 409 concurrency response used when the same equipment is dispatched twice.

- Source: `backend/app/models/transaction.py`; `backend/app/schemas/transaction.py`; `backend/app/services/borrow_service.py`; `backend/app/crud/transaction.py`; `backend/alembic/versions/0008_dispatch_fields.py`; `docs/HOSPITAL_DOMAIN_MODEL.md`; `knowledge/adr/ADR-005-transaction-model.md`; `docs/audits/04-consolidated-implementation-plan.md` Part D (PR7).

## Ward correction is audited, not a transfer

A transaction's first recorded receiving ward is normally immutable after dispatch. It may only be changed through one narrow, purpose-built action, `POST /transactions/{transaction_id}/correct-ward` (`app.services.borrow_service.correct_ward`) — never a generic transaction PATCH. This is correction of historical operational data, not ward-to-ward transfer tracking or current-location tracking; no such concept exists anywhere in this system. The action works identically whether the transaction is `open` or `closed` — no lifecycle-status precondition applies, and no equipment or transaction lifecycle state, `dispatch_type`/`routine_round`, or business-event timestamp is read or written. A same-ward submission is rejected as a no-op (`409 WARD_CORRECTION_NOOP`); a concurrent stale-read loss is rejected distinctly (`409 WARD_CORRECTION_CONFLICT`), decided by the same conditional-`UPDATE`-by-affected-rowcount shape Roadmap PR8A established for the receipt-close guard. Every successful correction writes exactly one audit entry, atomic with the ward change.

Authorization is temporarily restricted to `admin` only (`app.api.v1.deps.WARD_CORRECTION_ROLES`) — the current 5-role model has no confirmed, evidence-backed equivalent of the future "Equipment Pool Staff" role, so every other current role is denied with `403` pending Roadmap PR10's Role Model Consolidation. The frontend mirrors this as a usability-only gate (`frontend/src/hooks/useAuth.ts`'s `canCorrectTransactionWard`); the backend remains the sole authorization boundary regardless of frontend visibility.

- Source: `backend/app/services/borrow_service.py`; `backend/app/crud/transaction.py`; `backend/app/api/v1/transactions.py`; `backend/app/api/v1/deps.py`; `frontend/src/components/WardCorrectionAction.tsx`; `frontend/src/components/WardCorrectionDialog.tsx`; `docs/api/transactions.md`; Roadmap PR9 (PR9A backend, GitHub PR #33; PR9B frontend, GitHub PR #34) — see `docs/DECISION_LOG.md`.

## Decommission requires AVAILABLE -> UNAVAILABLE_DEFECTIVE -> DECOMMISSIONED

`AVAILABLE_AT_POOL` has no direct transition to `DECOMMISSIONED`. Equipment must first be marked `UNAVAILABLE_DEFECTIVE`; only `UNAVAILABLE_DEFECTIVE` may transition to `DECOMMISSIONED`. `DECOMMISSIONED` is terminal with no outgoing transition.

- Source: `backend/app/models/equipment.py` (manual-maintenance transition table); confirmed as a review finding during Roadmap PR6 (see `docs/DECISION_LOG.md`).

## Related documents

| Concern | Document |
|---|---|
| Full domain workflow narrative and terminology | `docs/HOSPITAL_DOMAIN_MODEL.md` |
| Architecture invariants that protect these rules | `docs/ARCHITECTURE_GUARDRAILS.md` |
| Per-decision rationale and history | `docs/DECISION_LOG.md`, `docs/ARCHITECTURE_DECISIONS.md` |
| Identifier/QR architecture detail | `knowledge/adr/ADR-002` through `ADR-004`, `knowledge/architecture/` |
| Transaction lifecycle decision | `knowledge/adr/ADR-005-transaction-model.md` |
| Domain entity structural reference | `docs/DOMAIN_MODEL.md` |
| Preferred terminology | `docs/GLOSSARY.md`, `knowledge/glossary.md` |
