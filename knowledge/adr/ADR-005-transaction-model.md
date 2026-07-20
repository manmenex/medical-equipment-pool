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
3. **"Overdue" is a notification concern, not a status.** A transaction
   whose `due_at` has passed remains `OPEN`; `check_overdue_returns`
   notifies engineers but no longer writes a status value, since a third
   status value would violate decision 1.
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
- `app.worker.scheduler.check_overdue_returns` notifies but does not
  transition status; a future change reintroducing a status write there
  would violate decision 3.
- The partial unique index enforcing "at most one OPEN transaction per
  equipment" (`idx_tx_one_active_borrow`) is defined against `status =
  'open'`; any future change to the status domain must update it in the
  same migration, exactly as this decision's own migration did for the
  prior `status = 'borrowed'` predicate.
- `due_at`, `borrower_name`, `ward_id` (nullable), `quantity`,
  `dispatch_type`, and `routine_round` are unaffected by this decision and
  remain open items for a later PR completing Roadmap PR7's full plan
  entry — this ADR does not imply they have been decided or implemented.

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
