# ADR-005: Transaction Model

Status: Accepted

## Context

`BorrowTransaction` (`app/models/transaction.py`) is the record of one
equipment dispatch through its receipt. Before this decision it used a
three-value `status` (`borrowed`, `returned`, `overdue`), where `overdue`
was written by a scheduled job (`app.worker.scheduler.check_overdue_returns`)
based on a `due_at` deadline. `docs/HOSPITAL_DOMAIN_MODEL.md`'s confirmed
workflow has never included an active due-date or overdue *state* — only
two transaction states, `OPEN` and `CLOSED` (`docs/audits/04-consolidated-
implementation-plan.md` Part D, Roadmap PR7's entry).

Roadmap PR7's full scope in that plan also includes `dispatch_type`,
`routine_round`, making `ward_id` required, and removing `borrower_name`/
`due_at` from the write path — the plan itself notes PR7 "recommend[s]
splitting further into 7a ... and 7b ... if the reviewing team prefers
smaller units." This ADR and its implementation are that 7a split: the
transaction lifecycle model only. `borrower_name`, `due_at`, `ward_id`
(nullable), and `quantity` are unchanged and remain in scope for a later
PR completing PR7's full plan entry.

## Decision

1. **Exactly two transaction states: `OPEN` and `CLOSED`.** No third
   status value exists or may be written. `TransactionStatus` (`app/models/
   transaction.py`) is the domain model for this — a `(str, enum.Enum)`
   mirroring `app.models.equipment.EquipmentStatus`'s shape (Roadmap PR6
   precedent), persisting lowercase `.value`s (`"open"`/`"closed"`) via the
   same `values_callable` technique PR6 established.
2. **Dispatch opens a transaction; receipt closes it.** These are the only
   two lifecycle transitions and the only two entry/exit points:
   `app.crud.transaction.create()` (open) and `app.crud.transaction.close()`
   (close) are the sole authorized mutators of `status`, called only from
   `app.services.borrow_service`. This mirrors `app.crud.equipment`'s
   `change_status_for_dispatch_receipt`/`change_status_for_manual_lifecycle`
   split (Roadmap PR6-H2 precedent): a narrow, purpose-built function per
   lifecycle concern, not a generic setter.
3. **"Overdue" is not tracked at all — no status, no notification.** A
   transaction whose `due_at` has passed remains `OPEN`; the approved MVP
   business model has no due-date/overdue *workflow* of any kind. The
   original implementation of this ADR kept a `due_at`-driven hourly
   notification job (`app.worker.scheduler.check_overdue_returns`) that
   only stopped writing a status value; Codex's PR7a review (round 1,
   BLOCKER) found that job re-selected every OPEN, overdue transaction on
   every hourly tick with no de-duplication, generating a fresh
   notification for the same transaction every hour indefinitely. The
   fix is to disable the workflow, not deduplicate a deprecated feature:
   `check_overdue_returns` has been removed and is no longer registered
   with the scheduler (`app.worker.scheduler.start_scheduler`). `due_at`
   itself is unaffected (see decision 4/Consequences) — it remains a
   plain, unread-by-notification column pending PR7b's field cleanup.
4. **`legacy_status` preserves history.** Every row remapped by migration
   `0007_transaction_lifecycle.py` keeps its exact pre-migration
   value (`borrowed`, `returned`, or `overdue`) in a new nullable
   `legacy_status` column — historical/rollback metadata only, never read
   by any workflow or eligibility check. Mirrors `Equipment.legacy_status`
   (Roadmap PR6 precedent) exactly.
5. **Legacy-to-target mapping:** `borrowed -> open`, `returned -> closed`,
   `overdue -> open` (an overdue transaction was always still open — it had
   not been received).

This ADR states the accepted target architecture for the transaction
*lifecycle* only. It does not restate or change `docs/BUSINESS_RULES.md`'s
"Dispatch/Return owns transaction lifecycle" rule (dispatch/receipt already
owned `ISSUED_TO_WARD` transitions before this decision) — it resolves that
rule's previously-documented current-vs-planned gap for the status values
themselves. It does not decide `dispatch_type`, `routine_round`,
`ward_id`-required, or `borrower_name`/`due_at` removal — those remain
Roadmap PR7's outstanding scope, tracked in `docs/audits/04-consolidated-
implementation-plan.md`'s PR7 entry and `docs/ROADMAP.md`.

## Consequences

- Any code path that reads or writes `BorrowTransaction.status` is measured
  against "exactly `OPEN` or `CLOSED`, mutated only via `create()`/`close()`"
  — a design that reintroduces a third status value, or that mutates
  `status` outside those two functions, does not conform to this ADR.
- `app.worker.scheduler.check_overdue_returns` no longer exists and the
  scheduler no longer registers any job that reads `due_at` or writes an
  "overdue" notification; a future change reintroducing either a status
  write or a due-date notification job would violate decision 3 and
  requires a new Governance PR, not a routine implementation change.
- The partial unique index enforcing "at most one OPEN transaction per
  equipment" (`idx_tx_one_active_borrow`) is defined against `status =
  'open'`; any future change to the status domain must update it in the
  same migration, exactly as this decision's own migration did for the
  prior `status = 'borrowed'` predicate.
- `due_at`, `borrower_name`, `ward_id` (nullable), `quantity`,
  `dispatch_type`, and `routine_round` are unaffected by this decision and
  remain open items for a later PR completing Roadmap PR7's full plan
  entry — this ADR does not imply they have been decided or implemented.

## Addendum (Roadmap PR7 7b slice)

This ADR's Decision and Consequences sections above are left as originally
accepted for the 7a lifecycle-model slice — they are not rewritten here.
`dispatch_type`, `routine_round`, `ward_id`-required, and `borrower_name`/
`due_at`/`quantity` removal, called out above as this ADR's explicit
non-decisions and PR7's outstanding scope, have since been implemented by
Roadmap PR7's 7b slice (migration `0008_dispatch_fields.py`, currently a
Draft PR pending review) exactly along the lines this ADR anticipated: as a
later PR completing Roadmap PR7's full plan entry, not a new architectural
decision requiring its own ADR. See `docs/BUSINESS_RULES.md`, `docs/
DOMAIN_MODEL.md`, and `docs/DECISION_LOG.md` ("Roadmap PR7 (7b slice)") for
the resulting current-state rules and rationale.

## References

- `docs/HOSPITAL_DOMAIN_MODEL.md` — confirmed workflow, OPEN/CLOSED
  transaction states.
- `docs/audits/04-consolidated-implementation-plan.md` Part D — Roadmap
  PR7's full entry (this ADR covers a 7a-style subset).
- `docs/BUSINESS_RULES.md` — "Dispatch/Return owns transaction lifecycle."
- `docs/ARCHITECTURE_GUARDRAILS.md` — "Do not bypass the dispatch/receipt
  services to change equipment status" (the transaction-side analogue is
  decision 2 above).
- `app/models/equipment.py`'s `EquipmentStatus`/`legacy_status`
  (Roadmap PR6) — the precedent this decision mirrors throughout.
- `docs/DOMAIN_MODEL.md` — where this model sits among the system's other
  domain concepts.
