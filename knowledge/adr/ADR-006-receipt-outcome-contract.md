# ADR-006: Receipt Outcome Contract

Status: Accepted

## Context

`docs/HOSPITAL_DOMAIN_MODEL.md`'s confirmed workflow has always described
receipt as "one atomic digital operation ... a binary outcome: usable or
defective," using the literal phrase "receipt outcome: usable" / "receipt
outcome: defective." Before this decision, the actual request contract
(`ReturnRequest.condition`, `backend/app/schemas/transaction.py`) did not
express that binary domain: it accepted any of four free-form strings
(`available`/`pm`/`calibration`/`repair`), reduced to two `EquipmentStatus`
values only inside an internal dict lookup
(`RETURN_CONDITION_TO_STATUS`, `backend/app/services/borrow_service.py`).
The contract itself did not say "this is a binary business decision" —
nothing at the type level prevented a future caller, typo, or new
condition string from silently falling into the generic `InvalidInputError`
branch instead of a clearly binary choice. `docs/design/
PR8_IMPLEMENTATION_PLAN.md` (design-only, uncommitted) split Roadmap PR8
into two slices along the same PR7a/PR7b precedent: PR8A (the database-level
concurrency guard, GitHub PR #26, merged) and PR8B (this decision) — the
API contract narrowing.

A second problem existed alongside the vocabulary mismatch: the four raw
strings are equipment-status-*shaped* names (`available`, `pm`,
`calibration`, `repair` read like maintenance categories, not business
outcomes), which invited a caller to reason about the request in terms of
the equipment lifecycle it should never need to know about directly. The
four confirmed equipment states (`AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`,
`UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`) are an internal state machine
owned exclusively by `app.crud.equipment.change_status_for_dispatch_receipt`
(`docs/ARCHITECTURE_GUARDRAILS.md`: "Do not bypass the dispatch/receipt
services to change equipment status") — a request contract that even
resembled those state names risked a future implementation letting a
client submit a lifecycle state directly, collapsing the separation between
"what the operator observed" (a business outcome) and "what the system
decided to do about it" (a lifecycle transition).

## Decision

1. **Single business term: `receipt_outcome`.** `ReturnRequest.condition`
   (`backend/app/schemas/transaction.py`) is replaced entirely by
   `receipt_outcome: ReceiptOutcome` — not renamed alongside a kept alias.
   The only consumer of this endpoint is this project's own frontend
   (`frontend/src/services/borrow.ts`), which this decision does not
   update (see "Not decided here"); no third-party or external client
   integration against the receipt endpoint is known to exist, so no
   compatibility layer was introduced (see "Alternatives considered"
   below).
2. **Exactly two allowed values: `usable` and `defective`.**
   `ReceiptOutcome` (`app/models/transaction.py`) is a `(str, enum.Enum)`
   mirroring `TransactionStatus`/`DispatchType`/`RoutineRound`'s shape and
   persisted-lowercase-`.value` convention. The values are the confirmed
   domain vocabulary itself (`docs/HOSPITAL_DOMAIN_MODEL.md`'s "receipt
   outcome: usable"/"receipt outcome: defective"), not invented. Pydantic
   validates this at the request-schema layer — an unrecognized value is
   now `422 VALIDATION_ERROR`, not the pre-PR8B `400 INVALID_INPUT` a
   free-form string needed a runtime dict-lookup miss to detect.
3. **The backend alone maps `receipt_outcome` to an `EquipmentStatus`.**
   `RECEIPT_OUTCOME_TO_STATUS` (`backend/app/services/borrow_service.py`)
   is the sole translation point: `usable -> AVAILABLE_AT_POOL`,
   `defective -> UNAVAILABLE_DEFECTIVE`. This mapping is total over
   `ReceiptOutcome`'s two members — there is no "unknown outcome" branch
   left to guard, unlike the pre-PR8B four-value dict, which needed one.
   **The frontend must never submit a lifecycle state directly** — it
   submits only the business outcome the operator observed, and the
   backend decides the resulting equipment state, exactly as
   `app.crud.equipment.change_status_for_dispatch_receipt` already is the
   only path permitted to write `Equipment.status` for a receipt.
4. **No new database column or migration.** `BorrowTransaction.
   condition_on_return` (`String(30)`, unconstrained) is unchanged —
   Option A from `docs/design/PR8_IMPLEMENTATION_PLAN.md` Section 5
   explicitly needs no schema change. A new `receipt_outcome` property on
   `BorrowTransaction` is a plain passthrough over that same column,
   exposed under the frozen business-term name in
   `TransactionOut.receipt_outcome` (`string | null`, not a strict
   `ReceiptOutcome`-typed field) so a transaction closed **before** this
   contract narrowed still reads back its genuine historical value
   (`available`/`pm`/`calibration`/`repair`), preserved and never
   remapped — mirroring how Roadmap PR7b preserved `borrower_name`/
   `due_at`/`quantity`, and how `TransactionOut.status` is itself a plain
   `str`, not a strict enum, for the same reason.
5. **Cleaning remains impossible to express.** Roadmap PR6 / owner-confirmed
   cleaning retirement already excluded `"cleaning"` from the pre-PR8B
   four-value domain; the binary `usable`/`defective` domain has no room
   for it either, by construction rather than by an explicit rejection
   rule.

## Alternatives considered

- **Keep `condition`, narrow its accepted values.** Rejected: this would
  have kept a field name that reads as an equipment-status-shaped
  maintenance category, working against decision 3's separation between
  business outcome and lifecycle state, for no benefit — no external
  client depends on the name `condition` specifically.
- **Accept both `condition` and `receipt_outcome` (a compatibility
  alias/dual-field period).** Rejected per this task's explicit instruction
  and this project's own precedent: Roadmap PR7b's Codex review established
  that a removed/renamed request field should be a hard rejection
  (`extra: "forbid"`), not a silently-tolerated legacy alias — a
  compatibility layer is only justified by a demonstrated migration
  requirement (e.g. a live external integration this project does not
  have), and introducing one preemptively would keep the ambiguous
  equipment-status-shaped vocabulary alive indefinitely instead of
  resolving it.
- **A new database column/migration for the outcome domain (Option B,
  `docs/design/PR8_IMPLEMENTATION_PLAN.md` Section 5).** Rejected for the
  same reason PR8A rejected it: no new column is needed to enforce a
  two-value domain at the request-schema layer, and `condition_on_return`
  already tolerates historical values without a migration.

## Not decided here

This decision narrows the request/response **contract**. It does not
implement a distinguishable error message or code for a race-loss
rejection versus a genuine repeat-request rejection (`docs/ROADMAP.md`'s
PR8B description names both; only the contract-narrowing half is decided
and implemented by this ADR). Both causes continue to share
`409 TRANSACTION_ALREADY_RETURNED` (`docs/api/receipt.md`,
`docs/api/ERROR_CODES.md`) until a follow-up change addresses that
remaining gap.

This decision also does not touch the frontend
(`frontend/src/services/borrow.ts`, `frontend/src/types/index.ts`,
`frontend/src/pages/ReturnPage.tsx`), which still submits the pre-PR8B
`condition` shape, or any authentication/authorization behavior — both
were explicitly out of scope for the task this ADR documents. Until a
follow-up frontend change adopts `receipt_outcome`, the deployed
frontend's receipt flow receives `422 VALIDATION_ERROR` for every
submission against a backend running this contract
(`docs/TECH_DEBT.md` TD-006).

## Consequences

- Any code path that builds or validates a receipt request is measured
  against "exactly `usable` or `defective`, via `receipt_outcome`" — a
  design that reintroduces a free-form `condition` string, or that lets a
  caller submit an `EquipmentStatus` value directly, does not conform to
  this ADR.
- `RECEIPT_OUTCOME_TO_STATUS` is the only place a receipt outcome is
  translated into an equipment status; `app.crud.equipment.
  change_status_for_dispatch_receipt` remains the only path permitted to
  write `Equipment.status` for a receipt (`docs/ARCHITECTURE_GUARDRAILS.md`).
- `docs/api/receipt.md` and `docs/api/ERROR_CODES.md` are the frozen,
  current documentation of this contract; `docs/design/
  PR8_IMPLEMENTATION_PLAN.md` (uncommitted, design-only) remains a
  historical planning artifact, not a live contract reference.
- The frontend is now contract-mismatched with the backend until a
  follow-up change updates it (see "Not decided here" above) — this is a
  known, deliberately accepted, temporary regression in the deployed
  system's usability, not an oversight.

## References

- `docs/HOSPITAL_DOMAIN_MODEL.md` — confirmed workflow, "receipt outcome:
  usable"/"receipt outcome: defective" vocabulary this decision adopts
  verbatim as the contract's value domain.
- `docs/design/PR8_IMPLEMENTATION_PLAN.md` — Section 5's Option A/B
  comparison and the PR8A/PR8B split this ADR's Decision 4 and Context
  build on.
- `docs/DECISION_LOG.md` — "Roadmap PR8 (PR8A slice)" (the concurrency
  guard this contract sits on top of) and "Roadmap PR8 (PR8B slice)" (this
  decision's own governance entry).
- `docs/ARCHITECTURE_GUARDRAILS.md` — "Do not bypass the dispatch/receipt
  services to change equipment status" (decision 3's separation of
  business outcome from lifecycle state exists to protect this guardrail).
- `app/models/transaction.py`'s `TransactionStatus`/`DispatchType`/
  `RoutineRound` — the persisted-lowercase-`.value` enum precedent
  `ReceiptOutcome` mirrors.
- `docs/api/receipt.md` — the frozen request/response contract this
  decision produces.
