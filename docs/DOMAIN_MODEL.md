# Domain Model

**Purpose:** Structural reference for the system's core domain entities — identity, state, relationships, and where each is implemented
**Authority:** Summary. Each entity's state machine and identity rules cite their authoritative ADR/business-rule source, which controls on conflict. Complements `docs/HOSPITAL_DOMAIN_MODEL.md` (workflow narrative and terminology) rather than restating it.
**Update trigger:** A domain entity's state machine, identity model, or lifecycle ownership changes
**Maintainer:** Architecture Owner

## Equipment

One physical device. Identity and state are two separate concerns.

**Identity** — four identifiers, each with one fixed role (`knowledge/adr/ADR-002-identifier-model.md`):

| Identifier | Role | Nullable |
|---|---|---|
| Internal UUID | Relational primary key; the only identifier transactions reference | No |
| BCM Code | Primary operator-facing identifier; manual-search only | Yes (backfill) |
| Item No | Hospital QR-label identifier; QR lookup only | Yes (backfill) |
| Asset Number | Inventory metadata only | No |

**State** — exactly four values, `EquipmentStatus` (`app/models/equipment.py`), each with one fixed role (`docs/BUSINESS_RULES.md` "Four Equipment States"):

```text
AVAILABLE_AT_POOL -> ISSUED_TO_WARD              (dispatch)
ISSUED_TO_WARD    -> AVAILABLE_AT_POOL            (receipt: usable)
ISSUED_TO_WARD    -> UNAVAILABLE_DEFECTIVE        (receipt: defective)
AVAILABLE_AT_POOL -> UNAVAILABLE_DEFECTIVE        (manual maintenance)
UNAVAILABLE_DEFECTIVE -> AVAILABLE_AT_POOL        (manual maintenance)
UNAVAILABLE_DEFECTIVE -> DECOMMISSIONED           (manual maintenance)
```

Two disjoint transition tables enforce which caller may reach which edge:
`DISPATCH_RECEIPT_TRANSITIONS` (only `app.crud.equipment.
change_status_for_dispatch_receipt`, called only by `app.services.
borrow_service`) and `MANUAL_LIFECYCLE_TRANSITIONS` (only the admin/BME
manual status endpoint). Neither table grants `DECOMMISSIONED` an outgoing
edge, and only `MANUAL_LIFECYCLE_TRANSITIONS` can reach it — always via
`UNAVAILABLE_DEFECTIVE`, never directly from `AVAILABLE_AT_POOL`
(`docs/BUSINESS_RULES.md` "Decommission requires AVAILABLE ->
UNAVAILABLE_DEFECTIVE -> DECOMMISSIONED").

`legacy_status` (nullable) preserves the exact pre-Roadmap-PR6 value for
any row remapped by migration `0006_equipment_state_model.py` — historical
metadata only, never read by any workflow.

## Transaction

One dispatch record, from opening through receipt/closure. Modeled by
`BorrowTransaction` (`app/models/transaction.py`).

**Lifecycle** — exactly two states, `TransactionStatus` (`knowledge/adr/
ADR-005-transaction-model.md`):

```text
(create) -> OPEN -> CLOSED   (receipt)
```

`app.crud.transaction.create()` is the only path that opens a transaction
(relies on the `TransactionStatus.OPEN` column default); `app.crud.
transaction.close()` is the only path that closes one. Both are called
only from `app.services.borrow_service`, which also owns moving the
associated `Equipment` through `ISSUED_TO_WARD` in the same business
transaction (`docs/BUSINESS_RULES.md` "Dispatch/Return owns transaction
lifecycle"). At most one `OPEN` transaction may exist per equipment,
enforced by a database-level partial unique index
(`idx_tx_one_active_borrow`, predicate `status = 'open'`) — the real guard
against a double-dispatch race, not merely an application-level check.

`legacy_status` (nullable) preserves the exact pre-Roadmap-PR7 value
(`borrowed`, `returned`, or `overdue`) for any row remapped by migration
`0007_transaction_lifecycle.py` — historical metadata only.

**Dispatch fields** (Roadmap PR7 7b slice, currently a Draft PR pending
review — per `docs/audits/04-consolidated-implementation-plan.md` Part D):
every new dispatch carries a `dispatch_type` (`DispatchType`: `routine_round`
or `on_demand`) and a required `ward_id`. `routine_round` (`RoutineRound`:
one of the four confirmed fixed times `06:00`/`11:00`/`15:00`/`21:00`, per
`docs/HOSPITAL_DOMAIN_MODEL.md` and `docs/audits/
03-hospital-equipment-pool-workflow-audit.md`'s §12 acceptance criteria) is
required exactly when `dispatch_type == routine_round` and forbidden
otherwise — enforced by `BorrowRequest`'s validator and, in PostgreSQL, by
migration `0008_dispatch_fields.py`'s `ck_borrow_transactions_
routine_round_consistency` CHECK constraint (defense in depth). Both
columns are nullable at the database level: an existing row from before
this migration has no reliable classification and is left `NULL`, never
fabricated. `ward_id`-required is enforced at the application layer only
(`BorrowRequest`), not a database `NOT NULL` — an existing `NULL` `ward_id`
row is never auto-assigned a ward.

`borrower_name`, `due_at`, and `quantity` are no longer accepted by
`BorrowRequest`, and `due_at` is also removed from `TransactionOut`. All
three columns and every existing value are unchanged in the database and
remain readable as history — `borrower_name` stays visible in
`TransactionOut`; `due_at`/`quantity` remain queryable/exportable via
`app.services.report_service`, which reads both directly from the ORM row.
The approved MVP business model still has no due-date/overdue workflow, so
an `OPEN` transaction simply stays `OPEN` regardless of `due_at`
(`app.worker.scheduler`'s `due_at`-driven notification job was removed; see
`knowledge/adr/ADR-005-transaction-model.md` decision 3).

**Receipt outcome** (Roadmap PR8B, `knowledge/adr/ADR-006-receipt-outcome-contract.md`):
receipt is recorded via `receipt_outcome` (`ReceiptOutcome`: `usable` or
`defective`), a single business term the backend alone maps to an
`EquipmentStatus` (`usable -> AVAILABLE_AT_POOL`, `defective ->
UNAVAILABLE_DEFECTIVE`) — the frontend never submits a lifecycle state
directly. Replaces the pre-PR8B four-value `condition` string entirely, no
compatibility alias kept. The underlying `condition_on_return` column and
every existing pre-PR8B value are unchanged and remain readable as
history, exposed through the same `receipt_outcome` name via a passthrough
property on `BorrowTransaction`.

## Relationships

```text
Equipment (1) ----< (many) Transaction
```

A `Transaction.equipment_id` references exactly one `Equipment`. An
`Equipment` may have many `Transaction` rows over its lifetime, but at most
one may be `OPEN` at a time (the partial unique index above). Equipment
identity (UUID) is permanent for the record's life; `Transaction` rows
reference it by UUID only, never by BCM Code or Item No
(`knowledge/business-rules/equipment-pool.md`).

## Related documents

| Concern | Document |
|---|---|
| Workflow narrative and terminology | `docs/HOSPITAL_DOMAIN_MODEL.md` |
| Approved business rules (summary form) | `docs/BUSINESS_RULES.md` |
| Equipment identifier model decision | `knowledge/adr/ADR-002-identifier-model.md` |
| Transaction lifecycle decision | `knowledge/adr/ADR-005-transaction-model.md` |
| Architecture invariants protecting both models | `docs/ARCHITECTURE_GUARDRAILS.md` |
