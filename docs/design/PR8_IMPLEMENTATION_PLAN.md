# Roadmap PR8 Implementation Plan — Atomic Receipt & Concurrency Protection

**Status:** Design only. Nothing in this document has been implemented.
**Prepared against baseline:** `d0e888f3095c9a794928a9bd7d68b60907654522` — squash commit of Roadmap PR7 (7b slice), GitHub PR #20, on branch `claude/medical-equipment-pool-0c7fz0`. (A documentation-only governance sync, GitHub PR #21, is open against the same baseline and does not change any file this plan depends on.)
**Roadmap authority:** `docs/audits/04-consolidated-implementation-plan.md` Part D, "PR8 — Atomic single-operation equipment receipt with concurrency guard" (the authoritative scope, acceptance criteria, and test-matrix source for this plan); `docs/HOSPITAL_DOMAIN_MODEL.md` ("Confirmed workflow"); `knowledge/adr/ADR-005-transaction-model.md`.
**Governance documents read before drafting this plan:** `AGENTS.md`, `docs/PROJECT_PLAYBOOK.md`, `docs/ROADMAP.md`, `docs/BUSINESS_RULES.md`, `docs/ARCHITECTURE_GUARDRAILS.md`, `knowledge/PROJECT_MEMORY.md`, `knowledge/CONTEXT.md`, `docs/DECISION_LOG.md`, `knowledge/adr/ADR-005-transaction-model.md`, plus the current backend implementation (`backend/app/models/transaction.py`, `backend/app/services/borrow_service.py`, `backend/app/crud/transaction.py`, `backend/app/crud/equipment.py`, `backend/app/api/v1/borrow.py`, `backend/app/schemas/transaction.py`, `backend/app/core/exceptions.py`, `backend/app/core/db_errors.py`) and its existing test suite.

---

## 1. Executive Summary

**What PR8 solves.** The current receipt (return) path has no concurrency guard. `borrow_service.return_equipment()` reads a transaction's status with a plain `SELECT`, checks `tx.status != OPEN` in Python, and only then writes the closed state — a classic read-then-write race. Two concurrent receipt requests for the same dispatch (a duplicate button tap, a retried request after a slow response, two staff members processing the same device) can both pass the status check before either commits, and both then proceed to close the transaction, change the equipment status, and write an audit row. Nothing in the database schema (`backend/app/models/transaction.py`) prevents this today — unlike the *dispatch* side, which already has a real guard (`idx_tx_one_active_borrow`, a partial unique index enforcing at most one `OPEN` transaction per equipment). Backend Audit Finding 14.1 (Critical) is the authoritative source for this defect; `docs/audits/04-consolidated-implementation-plan.md` Part C ranks it P0 with the note "silently losing a 'defective' report is a patient-safety-adjacent risk."

**Why it exists.** A hospital's Equipment Pool records exactly one authoritative outcome per dispatch: usable or defective. If a race allows a second, uncoordinated receipt request to silently overwrite or duplicate the first, the equipment's true condition becomes ambiguous — a defective device could end up marked available, or an audit trail could show two conflicting outcomes for one dispatch with no way to tell which is authoritative. PR8 closes this gap the same way PR6/PR7 already closed the equivalent dispatch-side gap: a database-level guard that makes "exactly one receipt succeeds" true by construction, not by hoping the application layer never races. It also completes the confirmed target contract for receipt — `docs/HOSPITAL_DOMAIN_MODEL.md`'s "Confirmed workflow" has always defined receipt as "one atomic digital operation ... a binary outcome: usable or defective," but the code today still accepts a 4-value `condition` string (`available`/`pm`/`calibration`/`repair`) that collapses to the binary outcome only inside `RETURN_CONDITION_TO_STATUS`, not in the contract itself.

**Why it comes after PR20 (Roadmap PR7, both slices).** PR8 depends on exactly the two things PR7 shipped: the `OPEN`/`CLOSED` transaction lifecycle (7a slice, GitHub PR #19) that gives PR8 a single boolean condition to guard (`status = 'open'`), and the completed dispatch-side field contract (7b slice, GitHub PR #20) that stabilized `BorrowRequest`/`TransactionOut` so PR8's changes are additive to `ReturnRequest`/receipt only, not entangled with dispatch-field cleanup still in flight. `docs/audits/04-consolidated-implementation-plan.md` states this dependency explicitly ("Dependencies: PR6, PR7 — needs the 4-state model and OPEN/CLOSED transaction model in place first"). Attempting PR8 before PR7 merged would have meant guarding a three-value `borrowed`/`returned`/`overdue` status instead of a clean two-value one, and building the fix on top of a still-changing request contract.

---

## 2. Current Flow

```text
Borrow (POST /api/v1/borrow)
  |
  v
Open Transaction                    app.crud.transaction.create()
  status = OPEN (column default)    -- sole opener, per ADR-005 decision 2
  equipment.status: AVAILABLE_AT_POOL -> ISSUED_TO_WARD
  guarded by idx_tx_one_active_borrow (partial unique index, DB-level)
  |
  v
Equipment State: ISSUED_TO_WARD
  |
  v
Receipt (POST /api/v1/return/{transaction_id})
  |
  v
Closed Transaction                  app.crud.transaction.close()
  status = CLOSED
  equipment.status: ISSUED_TO_WARD -> AVAILABLE_AT_POOL | UNAVAILABLE_DEFECTIVE
  guarded by: NOTHING — no unique index, no conditional UPDATE,
              no optimistic-lock version column
```

**Current receipt implementation, exactly as it runs today** (`backend/app/services/borrow_service.py::return_equipment`, `backend/app/crud/transaction.py::close`, `backend/app/crud/equipment.py::change_status_for_dispatch_receipt`):

1. `tx = await transaction_crud.get_by_id(db, transaction_id)` — a plain `SELECT ... WHERE id = :id`, no `FOR UPDATE`, no version check.
2. `if tx is None: raise TransactionNotFoundError` (404).
3. `if tx.status != TransactionStatus.OPEN: raise TransactionAlreadyReturnedError` (409) — a Python-level check against the value read in step 1, not a database-enforced condition.
4. `new_status = RETURN_CONDITION_TO_STATUS.get(condition)` — maps the request's `condition` string (`available`/`pm`/`calibration`/`repair`) to one of two `EquipmentStatus` values; an unrecognized string raises `InvalidInputError` (400).
5. `transaction_crud.close(db, tx, ...)` — sets `tx.status = CLOSED`, `tx.returned_at`, `tx.condition_on_return`, `tx.received_by_user_id` on the already-loaded ORM object, then `await db.flush()`. This is an ordinary `UPDATE ... WHERE id = :id` with **no `WHERE status = 'open'` predicate** — it succeeds unconditionally regardless of what the row's current status actually is at flush time.
6. `equipment_crud.change_status_for_dispatch_receipt(...)` — writes an `EquipmentStatusHistory` row and updates `Equipment.status`, again with no locking.
7. `audit_crud.create(...)` — writes the audit row on the same session (flush only, no independent commit — this part already follows the mandatory-audit-atomicity pattern from `docs/ARCHITECTURE_GUARDRAILS.md`).
8. `await db.commit()` — the first point at which anything in steps 3–7 is actually durable.

**Highlighted weaknesses (no recommendations yet — analysis only):**

- **Read-then-write race across the whole function.** Step 3's check and step 5's write are separated by non-trivial work (steps 4–7) with no lock held across them. Two requests that both execute step 1 before either reaches step 8's commit will both pass step 3.
- **The `UPDATE` in step 5 has no conditional predicate.** Even if the check in step 3 were somehow made atomic with the read, the actual `UPDATE` statement SQLAlchemy emits for `close()` does not include `WHERE status = 'open'` — it updates by primary key only, so it cannot detect at the SQL level that another transaction already closed the row.
- **No unique index or version column exists to make a double-close physically rejectable**, unlike the dispatch side's `idx_tx_one_active_borrow`.
- **The error message for the "already closed" case is identical regardless of cause.** `TransactionAlreadyReturnedError`'s message ("This transaction has already been returned") is accurate for a request that genuinely arrives after a real prior receipt, but would be actively misleading if it were the *product* of an unguarded race — the requester did nothing wrong; the response ends up conflating "you made a mistake" with "you lost a timing race." `docs/audits/04-consolidated-implementation-plan.md` Part G.2 flags this exact wording problem as its own required test case.
- **The receipt `condition` field is not the confirmed binary outcome.** Four raw strings (`available`/`pm`/`calibration`/`repair`) are accepted and reduced to two equipment statuses only inside a dict lookup (`RETURN_CONDITION_TO_STATUS`) — the contract itself does not express "this is a binary decision," so nothing prevents a future caller/typo/new condition string from silently falling into the `InvalidInputError` branch instead of a clearly binary choice at the type level.
- **No test in the current suite exercises real concurrent receipt requests.** `tests/test_borrow.py::test_closing_an_already_closed_transaction_is_rejected` proves *sequential* double-close is rejected (correct, but says nothing about a race), and `tests/test_postgres_integration.py` — the only file in this repository capable of proving real PostgreSQL concurrency, per its own docstring and the precedent set by `test_concurrent_dispatch_burst_produces_unique_transaction_numbers_on_postgres` for the dispatch side — has no equivalent receipt-side test at all today.

---

## 3. Concurrency Analysis

Every scenario below is analyzed against the **current** code (Section 2). No fix is proposed in this section.

| # | Scenario | Current behavior | Expected behavior |
|---|---|---|---|
| 1 | **Double receipt** — two requests for the same OPEN transaction arrive close enough together that both read `status = OPEN` before either commits. | Both proceed through steps 4–8. Both write an `EquipmentStatusHistory` row and an audit row; both call `db.commit()`. Depending on commit interleaving, the second commit can silently overwrite the first's `condition_on_return`/`returned_at`/`received_by_user_id`/equipment status with its own values, and the equipment ends up in whichever status happened to commit last — not necessarily the first (or "correct") one. No error is guaranteed to surface to either caller. | Exactly one request succeeds. The other is rejected with a clear, non-misleading error (not "you already returned this" when the real cause is a race) and produces **zero** side effects — no equipment status change, no status-history row, no audit row, no altered `returned_at`/`condition_on_return`/`received_by_user_id` on the transaction the losing request thought it was writing. |
| 2 | **Refresh after receipt** — a staff member's browser reloads/re-submits the receipt form after a receipt already succeeded (e.g. a slow network response the UI didn't clearly acknowledge, followed by a manual retry). | Reaches step 3 with `tx.status == CLOSED` (already updated by the first, completed request) and is correctly rejected today — this specific ordering (fully sequential, not a race) already works. | Same as today: rejected, no side effects. This case is not broken; it is included here to distinguish it from scenario 1, which looks identical to the *user* but is not identical to the *system*. |
| 3 | **Two users receiving simultaneously** — two different Equipment Pool staff, on two different devices, scan/select the same in-transit equipment and submit a receipt within the same request window. | Same failure mode as scenario 1 — this is the concrete real-world instance of the double-receipt race, not a separate defect. | Same as scenario 1: exactly one receipt succeeds; the other party sees a clear rejection, ideally distinguishable from "stale data" (e.g., "this device was just received by someone else — refresh to see the current record") so the losing staff member understands what happened rather than assuming they made an error. |
| 4 | **Retry after timeout** — the client's HTTP request to `POST /return/{id}` times out on the network before a response arrives, and the client (or the operator) retries the identical request. If the first attempt actually succeeded server-side despite the client-side timeout, this becomes a same-payload double-submission. | Same failure mode as scenario 1 if the retry races the original server-side completion; behaves like scenario 2 (correctly rejected) if the retry arrives after the original fully committed. | The race window is closed by the same fix as scenario 1. No dedicated idempotency-key mechanism is required for MVP — `docs/audits/04-consolidated-implementation-plan.md` Part G.1 explicitly defers `Idempotency-Key` to P2 for the analogous dispatch-side retry case, and the receipt side has no stronger requirement than the dispatch side already accepted. A concurrency-safe conditional write makes a retry naturally rejected the same way a genuine second receipt is, with no separate mechanism needed. |
| 5 | **Duplicate API call** — a scripted client, an automated test, or a double-tap on a slow UI issues two near-simultaneous, distinct HTTP requests for the same transaction (mechanically identical to scenario 1, called out separately because it is the literal test scenario, not just the narrative one). | Same failure mode as scenario 1. | Same as scenario 1. This is the primary scenario the required concurrency test matrix (`docs/audits/04-consolidated-implementation-plan.md` Part G.2) exercises directly. |
| 6 | **Browser back button** — a staff member completes a receipt, the success screen renders, they press Back, and the browser re-renders the pre-submission form (e.g. from cache) with the submit control still active; they submit again. | Reaches the service function after the original commit has already landed (this is inherently sequential from the server's point of view — the "back" navigation happens entirely client-side after the first request's response arrived). Behaves like scenario 2: correctly rejected today. | Same as scenario 2 — already correct, not a target of PR8's guard itself. Worth a defensive frontend note (Section 6) so the second submission at least surfaces the "already received" rejection cleanly instead of a confusing generic error, but this is a UI-polish concern, not a concurrency defect. |
| 7 | **Optimistic UI retry** — the frontend optimistically shows a "receiving..." state and, per its own retry policy (e.g. on a 5xx or network blip), automatically re-sends the same receipt request without operator action. | Same failure mode as scenario 1 if the retry races an in-flight original request that actually succeeds server-side; behaves like scenario 2 if the original request had already fully failed (nothing to race) or fully succeeded before the retry fires. | Covered by the same fix as scenario 1 — an automatic retry is indistinguishable, at the database level, from a manual duplicate call, and must be rejected the same safe way. |
| 8 | **Receipt with no OPEN dispatch for the equipment** — a receipt is attempted for equipment that has no `OPEN` `BorrowTransaction` at all (e.g., a stale link, a manually-constructed request, or a transaction ID for equipment already received through a different path). | `transaction_crud.get_by_id` looks up by transaction ID, not by equipment — if the ID exists and is `CLOSED`, this is scenario 2's `TransactionAlreadyReturnedError`; if the ID does not exist at all, `TransactionNotFoundError` (404) fires correctly today. | No behavior change required here beyond what the guard already does — included in the matrix (`docs/audits/04-consolidated-implementation-plan.md` Part G.2) as an explicit "clear rejection, no side effects" case to keep as a regression check while the receipt path is rewritten. |
| 9 | **Receipt of the wrong transaction** — a request targets a transaction ID that is not the equipment's *current* open one (only reachable defensively, since the one-open-dispatch-per-equipment invariant means a given piece of equipment has at most one genuinely current `OPEN` transaction at any time). | Not reachable through normal use today; if attempted directly against a `CLOSED` transaction ID, behaves like scenario 2. | Tested defensively per the audit's explicit instruction, even though the invariant makes it unreachable through the UI — a regression here would be a silent invariant violation elsewhere in the system, worth guarding against directly rather than trusting the invariant forever. |

**Cross-cutting root cause (not a separate scenario, the common thread through 1, 3, 4, 5, 7):** every problematic scenario reduces to the same defect — the absence of a database-level condition on the `close()` write. Any fix must make "close only if currently OPEN" an atomic, server-enforced fact, not a pre-check performed in application code with a gap before the write.

---

## 4. Atomic Boundary

**Where the one database transaction should begin:** immediately before the conditional close write (the step that must observe and act on the transaction's current `status` in a single database round trip) — i.e., at the start of `borrow_service.return_equipment()`'s mutating section, functionally where `transaction_crud.close()` is invoked today. It does not need to begin any earlier than that, because the read in step 1 (loading the transaction/equipment for validation and to know *which* dispatch is being received) is not itself the race-sensitive operation — the race is entirely in "check status, then later write status" without a lock or condition connecting the two.

**Where it should commit:** unchanged from today — after the audit-log write, exactly once, per the existing mandatory-audit-atomicity pattern (`docs/ARCHITECTURE_GUARDRAILS.md`: "Mandatory audit writers use the caller's `AsyncSession`, flush without an independent commit... the caller commits once after both writes"). PR8 must not introduce a second commit point or split the receipt into two separately-committed steps — that would reintroduce exactly the kind of two-step design the hospital's confirmed requirements explicitly rejected (`docs/audits/04-consolidated-implementation-plan.md` Part B.1: "the return/receipt operation is one atomic action ... not two").

**Writes that belong inside the one atomic boundary** (must all succeed or all roll back together, exactly as today, with the addition of the new conditional guard):

- The conditional transaction-close write itself (`BorrowTransaction.status`, `returned_at`, `condition_on_return`/outcome field, `received_by_user_id`, `notes`) — this is the write the new guard mechanism directly protects.
- `EquipmentStatusHistory` insert and `Equipment.status` update (`change_status_for_dispatch_receipt`) — must reflect the *same* successful receipt, never a partial or inconsistent one.
- The audit-log row (`audit_crud.create`, action `"return"`) — must exist if and only if the receipt actually succeeded; per Part G.2's explicit test requirement, a losing/rejected concurrent request must produce **no** audit row.

**Writes that must never occur outside this boundary:**

- Nothing about `Equipment.status` or `EquipmentStatusHistory` may be written before the conditional transaction-close write is known to have actually applied (i.e., before confirming, at the database level, that this request — not a concurrent one — was the one that transitioned the row from `OPEN` to `CLOSED`). Writing the equipment status first and only then discovering the transaction-close lost the race would leave equipment status changed with no corresponding closed transaction — the exact "equipment condition becomes ambiguous" failure PR8 exists to prevent (Section 1).
- The audit-log write must never occur for a request that ultimately loses the race, even if that request got partway through building the audit payload before the conflict was detected — no audit event for a mutation that didn't actually happen, matching the existing mandatory-audit-atomicity rule.
- No response should be returned to the caller (success or otherwise) before the surrounding `db.commit()` has completed — unchanged from today's structure, but worth stating explicitly since a guard mechanism that "detects" a win/loss before commit is not itself proof the write is durable.

---

## 5. Locking Strategy Options

### Option A — Conditional `UPDATE ... WHERE status = 'open'`, checked by affected-row-count

The close write becomes a single SQL statement equivalent to `UPDATE borrow_transactions SET status = 'closed', returned_at = ..., ... WHERE id = :id AND status = 'open'`, and the calling code inspects the number of rows the database reports as affected. Exactly one concurrent request will see `rowcount == 1`; every other concurrent request against the same row will see `rowcount == 0` (because by the time its own `UPDATE` runs, the predicate `status = 'open'` no longer matches — the winner already flipped it). No `SELECT ... FOR UPDATE` is strictly required beforehand, because the atomicity comes from the single conditional `UPDATE` statement itself, which PostgreSQL (and SQLite, for the test suite) execute as one indivisible operation per row.

- **Pros:** No new column, no schema migration. Directly mirrors the dispatch side's existing philosophy of "make the invalid state unreachable at the database level" (there, a partial unique index; here, a conditional predicate + rowcount check) — same spirit, adapted because uniqueness doesn't apply to a single-row transition the way it does to "at most one OPEN row per equipment." Simple to reason about: one statement, one boolean outcome (did it affect a row or not). Works identically on PostgreSQL and SQLite, so the existing fast SQLite-backed test suite can exercise the *logic* (rowcount-zero handling) even though only `tests/test_postgres_integration.py` can prove true concurrent-request behavior.
- **Cons:** Requires the ORM call site to actually inspect the affected-row count, which SQLAlchemy's ORM-object-attribute-mutation style (`tx.status = CLOSED; await db.flush()`) does not naturally expose — the close operation would need to move to (or be paired with) a Core-style `update()` statement or an equivalent `session.execute(update(...).where(...))` call whose `CursorResult.rowcount` is inspected, a real (if small) change in how `crud/transaction.py::close()` is implemented, not just an added check.
- **Complexity:** Low-medium. The mechanism itself is simple; the main work is restructuring `close()` to use a rowcount-checked statement instead of attribute mutation, and propagating a "did not affect a row" outcome back up to `borrow_service.return_equipment()` as a distinct, clearly-worded error rather than reusing the ORM object's (now stale) in-memory `status`.
- **Compatibility:** Fully compatible with the existing OPEN/CLOSED model and the existing commit-once pattern in Section 4. No interaction with `idx_tx_one_active_borrow` (that index guards a different transition — dispatch, not receipt — and is unaffected either way).

### Option B — Optimistic locking via a version column

Add an integer `version` (or reuse a timestamp-based token) column to `BorrowTransaction`. Every read of the row for update captures the version it saw; the close write becomes `UPDATE ... SET version = version + 1, ... WHERE id = :id AND version = :expected_version`. A rowcount of zero means someone else updated the row (and therefore incremented its version) since it was read, regardless of what specifically changed.

- **Pros:** A generic mechanism that would also protect *any other* future concurrent-write scenario on the same row (not just receipt), if one is ever added. Well-understood, widely-used pattern (e.g., SQLAlchemy's built-in `version_id_col` support).
- **Cons:** Requires a new nullable-then-backfilled or defaulted column and therefore a migration — the audit's own PR8 entry frames migration as optional ("Database migration impact: None new beyond PR6/PR7's columns... mechanism choice deferred to implementation"), and a version column would spend that option's "no migration" slot on a general-purpose mechanism this specific problem does not actually need (the only concurrent write receipt has ever needed to guard against is "did someone else already close this," which `status` itself already encodes — a dedicated version counter is solving a more general problem than exists here). Slightly more moving parts for reviewers and future maintainers to understand (two columns effectively encoding overlapping information: `status` and `version`).
- **Complexity:** Medium. Requires a migration (additive, low risk, but still a new revision file, `Base.metadata` change, and the associated TD-002 schema-convergence considerations every migration in this repository has had to account for per `docs/TECH_DEBT.md`).
- **Compatibility:** Fully compatible, but introduces a column with no read-path consumer anywhere else in the system (unlike, say, `dispatch_type`, which both writes and reads care about) — a maintenance surface with a single, narrow purpose that Option A achieves without it.

### Option C — Current behavior (do nothing / baseline for comparison)

Keep the plain `SELECT` + Python-level status check + unconditional `UPDATE` exactly as it is today.

- **Pros:** No implementation cost. Simplest possible code.
- **Cons:** This is the defect PR8 exists to fix — every scenario in Section 3 marked "same failure mode as scenario 1" remains exploitable. Not viable as a real option; included only for completeness/comparison, per this section's own "no implementation" instruction.
- **Complexity:** None (already exists).
- **Compatibility:** Trivially compatible with everything, because nothing changes — which is exactly the problem.

### Recommendation

**Option A (conditional `UPDATE` with rowcount check).** It fixes every scenario in Section 3 with no new schema, mirrors the existing architectural pattern this codebase already established for the analogous dispatch-side guard (a database-enforced condition rather than an application-level check), and matches the audit's own framing of "no migration beyond PR6/PR7's columns" as the expected outcome. Option B is not wrong, but it solves a more general problem than PR8 actually has, at the cost of a migration this specific fix does not need. This recommendation is a starting point for implementation-phase review, not a final decision — restating this document's own header: **no implementation occurs from this plan.**

---

## 6. API Impact

| Endpoint | Current request | Current response | Expected behavior after PR8 |
|---|---|---|---|
| `POST /api/v1/return/{transaction_id}` | `ReturnRequest { condition: string (free-form, validated only against a runtime dict lookup — "available"\|"pm"\|"calibration"\|"repair"), notes: string \| null }` | `TransactionOut` (200) on success; `404 TRANSACTION_NOT_FOUND`; `409 TRANSACTION_ALREADY_RETURNED` (used today for both a genuine repeat request *and*, if raced, an unguarded double-close); `400 INVALID_INPUT` for an unrecognized `condition` string. | Request contract narrows to the confirmed binary outcome (`docs/HOSPITAL_DOMAIN_MODEL.md`: "records a binary outcome: usable or defective") — the exact field name/shape (e.g. `outcome: "usable" \| "defective"` vs. keeping `condition` but constraining its domain) is an implementation-phase decision, not fixed by this plan. `404`/`400` behavior for not-found/malformed input is unchanged. The `409` case must be reachable via **two distinguishable causes** at the application level even if the HTTP status stays 409 for both: a transaction that was already closed *before this request was ever made* (today's genuine case), and a transaction whose close this specific request *lost a race for* (new — see Section 3's cross-cutting note on misleading messaging). Whether that distinction becomes a different error `code`, a different `detail` message, or additional response metadata is an implementation-phase decision. |
| `POST /api/v1/borrow` | Unchanged. | Unchanged. | **Not touched by PR8.** Included here only to state explicitly that PR8's guard is scoped to the `ISSUED_TO_WARD -> CLOSED` receipt transition; the existing dispatch-side guard (`idx_tx_one_active_borrow`) already protects `AVAILABLE_AT_POOL -> ISSUED_TO_WARD` and needs no change. |
| `GET /api/v1/borrow/active` | Unchanged. | Unchanged — lists `OPEN` transactions. | Not touched. A transaction that loses the receipt race remains correctly `OPEN` (nothing about it changed), so it continues to appear here exactly as it did before the losing request — no new inconsistency introduced. |
| `GET /api/v1/equipment/{id}` and equipment status/history reads | Unchanged. | Unchanged. | Not touched directly, but their *correctness* is exactly what PR8 protects: today, a raced double-receipt could leave `Equipment.status`/`EquipmentStatusHistory` reflecting whichever request committed last rather than a single well-defined outcome. |

No code is written or proposed for any of the above in this document.

---

## 7. Database Impact

- **Tables:** `borrow_transactions` (the row being conditionally closed) and `equipment_status_history`/`equipment` (written immediately after, inside the same atomic boundary — Section 4). No new table.
- **Indexes:** No new index is required for the recommended approach (Option A, Section 5). `idx_tx_one_active_borrow` (existing, dispatch-side) is unaffected and unchanged.
- **Constraints:** No new `CHECK`, `UNIQUE`, or `FOREIGN KEY` constraint is required for Option A — the guard is enforced by the conditional `UPDATE` predicate at write time, not by a standing schema constraint. (If Option B were chosen instead, it would require a new nullable-or-defaulted `version` column and no new constraint beyond that column's own type.)
- **Migration required:** No, under the recommended Option A.

**No schema migration required.**

(This is conditional on the Locking Strategy recommendation in Section 5. If a future implementation phase chooses Option B instead, that choice would require one new additive migration for the `version` column, following this repository's established additive-migration conventions — e.g. `backend/alembic/versions/0009_*.py` — but that is not what this plan recommends.)

---

## 8. Test Plan

No test code is written here — this is a checklist of what implementation-phase tests must cover, organized the same way this repository's existing suites are (`backend/tests/test_borrow.py`, `test_equipment.py`, `test_exception_handling.py` for SQLite-backed unit/API coverage; `backend/tests/test_postgres_integration.py` for real-concurrency/PostgreSQL-only evidence, per that file's own documented scope).

**Unit**
- [ ] `crud/transaction.py`'s new conditional-close function returns a clear "did not affect a row" signal (not a silent no-op, not an exception masquerading as success) when the target row is not currently `OPEN`.
- [ ] The signal from the point above is distinguishable, at the Python level, between "already closed before this call" and "lost a race during this call" if the implementation phase decides to expose that distinction (Section 6).
- [ ] Every valid `outcome`/`condition` value maps to the correct `EquipmentStatus` (`usable -> AVAILABLE_AT_POOL`, `defective -> UNAVAILABLE_DEFECTIVE`), mirroring the existing `RETURN_CONDITION_TO_STATUS`-style test coverage.
- [ ] An unrecognized outcome value is rejected with the existing `InvalidInputError` (400) pattern, not a 500.

**Integration (SQLite-backed, `pytest -m "not postgres"`)**
- [ ] Full dispatch -> receipt happy path still returns `200`/closes the transaction/updates equipment status (regression coverage for `test_borrow_then_return_flow`, `test_receipt_closes_the_transaction_and_records_outcome`).
- [ ] Sequential double-receipt (`test_closing_an_already_closed_transaction_is_rejected`'s existing scenario) still returns `409` and is unaffected by the new guard mechanism.
- [ ] Receipt with no matching `OPEN` transaction still returns `404`/`409` as appropriate, with zero side effects.
- [ ] `test_defective_receipt_transitions_to_unavailable_defective` and `test_return_condition_cleaning_is_rejected_not_silently_accepted` (existing) still pass unmodified in behavior, adjusted only for the new outcome-field shape if the contract narrows.
- [ ] `test_openapi_return_request_does_not_advertise_cleaning` (existing) still passes — the new contract must not reintroduce or imply a cleaning-related value.

**PostgreSQL (`pytest -m postgres`, real concurrency — the only environment that can prove this)**
- [ ] **Two simultaneous receipt requests for the same OPEN transaction: exactly one succeeds.** (Direct implementation of Part G.2's primary scenario, mirroring `test_concurrent_dispatch_burst_produces_unique_transaction_numbers_on_postgres`'s existing pattern for the dispatch side.)
- [ ] The losing request's response is asserted to be a clear, non-misleading error — explicitly checked to not be (or not solely be) the plain "already returned" wording when the actual cause was a race, per Part G.2's explicit instruction.
- [ ] After a simulated race, each of the following six is asserted **independently** (per Part G.2's explicit "not just 'the transaction ended up closed'" instruction): (1) `condition_on_return`/outcome, (2) `returned_at`, (3) `received_by_user_id`, (4) `Equipment.status`, (5) the `EquipmentStatusHistory` row, (6) the audit-log row — all reflect the winning request only, with no trace of the losing request's payload.
- [ ] Exactly one audit-log row exists for the transaction after the race (not zero, not two).
- [ ] Receipt of equipment that is (somehow) `DECOMMISSIONED` does not reactivate it — both the dispatch-time block (already covered) and, redundantly, that the receipt path itself has no code path capable of producing that transition.

**Concurrency (explicit matrix from Part G.2, cross-referenced with above so nothing is double-counted)**
- [ ] Two simultaneous receipts, same dispatch → exactly one succeeds. *(listed above under PostgreSQL — included here for matrix completeness)*
- [ ] Receipt when no `OPEN` dispatch exists for the equipment → clear rejection, no side effects.
- [ ] Receipt of the wrong transaction (defensive; attempt to close a transaction ID that is not the equipment's current open one) → rejected.
- [ ] Retry-after-timeout and duplicate-submission scenarios (Section 3, #4/#5/#7) → all reduce to and are covered by the same "exactly one succeeds" assertion above; no separate idempotency-key mechanism implemented or tested (explicitly out of scope, matching the dispatch-side precedent).

**API**
- [ ] Every response envelope for every new/changed status code follows the existing `{detail, code, status}` shape (`docs/ARCHITECTURE_GUARDRAILS.md`'s evidence/consistency expectations; matches the pattern every other endpoint in this repository already follows).
- [ ] OpenAPI schema for `ReturnRequest`/the new outcome field reflects only the confirmed 2-value domain — no leaked `pm`/`calibration`/`repair`/`cleaning` values, mirroring `test_openapi_return_request_does_not_advertise_cleaning`'s existing enforcement style for the analogous PR6 concern.

**Regression**
- [ ] Every existing `test_borrow.py`/`test_equipment.py`/`test_exception_handling.py`/`test_postgres_integration.py` test that touches receipt/return continues to pass, updated only for the outcome-field contract change where applicable (not for concurrency-guard-related behavior, which should be purely additive).
- [ ] `report_service.py`'s CSV/XLSX export (reads `condition_on_return` directly from the ORM row) continues to produce a value for historical rows regardless of whether the live field name changes — historical data must remain exportable exactly as PR7b preserved `borrower_name`/`due_at`/`quantity`.
- [ ] `app/scripts/seed.py`'s direct-ORM-construction seed path (`condition_on_return="available"`) is reviewed for whether it needs updating to the new outcome domain, or remains valid as historical-shaped seed data.

**CI**
- [ ] `pytest -m "not postgres"` — zero failures.
- [ ] `pytest -m postgres` — zero failures, zero infrastructure skips (matching the fail-closed PostgreSQL CI gate `docs/DECISION_LOG.md` documents for the "Infrastructure — GitHub Actions CI" entry).
- [ ] `alembic upgrade head` from a fresh database — clean, only if Option B (migration) is ultimately chosen; not applicable under the Option A recommendation.
- [ ] `npm run build` (frontend) — clean, once the receipt outcome selector's shape is finalized in implementation.
- [ ] `git diff --check` — clean.

---

## 9. Out of Scope

PR8 will **not** include any of the following:

- Reservation
- Patient tracking
- Cleaning workflow
- Transfer workflow (ward-to-ward)
- Shift Session
- Standby Snapshot
- Deployment
- Role redesign
- Inventory import
- Terminology redesign (the full Dispatch/Receiving Ward/Routine Round/On-Demand/Return-to-Pool UI terminology pass is Roadmap PR11's scope; PR8 touches only the receipt outcome field/selector, not the surrounding page's wording or labels)
- Dashboard
- Search redesign
- Any future roadmap work not explicitly listed above

Additionally, and specific to this PR's boundary (not merely restating the general list above):

- **Ward correction** (Roadmap PR9) is not implemented here, even though it is the next PR in sequence.
- **Role model consolidation** (Roadmap PR10) is not implemented here; PR8's authorization continues to use the currently-active role set, unchanged.
- **Dispatch-side concurrency** is not touched — `idx_tx_one_active_borrow` and the dispatch guard already shipped (PR6/PR7) and need no change.
- **A general-purpose optimistic-locking/versioning mechanism** for the whole `BorrowTransaction` model is not adopted (Section 5, Option B rejected in favor of the narrower Option A) — PR8 solves the receipt-close race specifically, not concurrent-write safety for every future field on this row.
- **Idempotency-Key support** is not implemented — explicitly deferred to P2 for the analogous dispatch-side case (`docs/audits/04-consolidated-implementation-plan.md` Part G.1) and not elevated to a requirement for receipt either.

---

## 10. Risk Assessment

**Implementation risks:**

- **Getting the "distinguish race-loss from genuine repeat" requirement wrong.** Part G.2 requires this distinction be tested; if the implementation reuses the exact same error code/message for both without at least a clearer message, the acceptance criterion is not actually met even though the concurrency bug itself is fixed. This is a documentation/UX-precision risk more than a data-safety one, but it is explicitly called out by the authoritative test matrix and should not be treated as optional polish.
- **Restructuring `crud/transaction.py::close()` away from ORM-attribute mutation.** The current pattern (`tx.status = CLOSED; await db.flush()`) is simple and matches the style of every other mutator in this codebase (`change_status`, `create`). Moving to a rowcount-checked `UPDATE` (Option A) is a structural change to that one function's implementation style — low risk in isolation, but it is the first place in this codebase that would need this pattern, so it sets a precedent worth getting right (naming, error-signal shape, whether other future guards follow the same style).
- **Frontend/backend contract-shape mismatch during the transition.** If the outcome-field rename/narrowing (`condition` -> a 2-value outcome) and the concurrency guard are not coordinated carefully, a frontend deployed against an old contract could send a shape the new backend rejects, or vice versa — the same category of risk PR7b's `BorrowRequest` narrowing already navigated successfully (extra-field rejection, coordinated frontend update) and can reuse that precedent for.
- **Under-testing the "six-things-independently-asserted" requirement.** Part G.2's requirement that outcome/`returned_at`/`received_by_user_id`/equipment-status/status-history/audit-log each be asserted independently after a simulated race is unusually specific; a shortcut ("the transaction ended up closed, therefore fine") would not actually satisfy the acceptance criteria even if it looks like adequate coverage.

**Rollback strategy:**

Per the audit's own framing (`docs/audits/04-consolidated-implementation-plan.md` PR8 entry): "Revert; the OPEN/CLOSED and 4-state models from PR6/PR7 remain valid and usable by the prior (superseded) return logic if a true rollback is needed, though the concurrency defect would return with it — recommend forward-fix over rollback for this specific PR given the severity of what it fixes." Concretely:

- Under the recommended Option A (no migration), rollback is a pure code revert — no `alembic downgrade` step is needed, since no schema changed.
- If Option B were chosen instead, rollback would additionally need `alembic downgrade` to the pre-PR8 revision, following the same fail-closed, tested-downgrade discipline every migration in this repository already follows (`docs/ARCHITECTURE_GUARDRAILS.md`: "Do not edit applied migration history casually. Use additive-first revisions, preserve rows, and test real upgrade/downgrade paths").
- Reverting PR8 restores the known-vulnerable-but-functional prior behavior — acceptable as a short-term emergency rollback, but the recommendation (matching the audit's own text) is to forward-fix any implementation defect discovered after merge rather than roll back and reintroduce the race, given the patient-safety-adjacent framing of the underlying finding.

**Potential production impact:**

- **Positive (the point of this PR):** Eliminates a real, currently-exploitable data-integrity defect with patient-safety-adjacent framing (a defective device silently ending up marked available due to a lost race, or an audit trail with two conflicting outcomes for one dispatch).
- **Neutral, if implemented as recommended:** No schema migration means no downtime/lock-window risk from a `borrow_transactions` `ALTER TABLE` at deploy time.
- **Risk to watch:** Any legitimate-but-unusual timing pattern in real pilot usage (e.g., a staff member's device losing connectivity mid-receipt and a second device completing the receipt while the first device's request is still in flight) must resolve to "exactly one succeeds, the other gets a clear message" — not to a hung request or an unhandled exception surfacing as a 500. This is exactly what the PostgreSQL concurrency test matrix (Section 8) exists to catch before merge, not after.

---

## 11. Estimated File Changes

Predicted only — nothing below has been created, edited, or touched by this planning task.

**Backend**
- `backend/app/crud/transaction.py` — new/changed conditional-close function (Option A: rowcount-checked `UPDATE` replacing or wrapping the current `close()`).
- `backend/app/services/borrow_service.py` — `return_equipment()` updated to call the new conditional-close path and translate a "lost the race" outcome into a distinguishable error (Section 6); `RETURN_CONDITION_TO_STATUS` narrowed to the 2-value outcome domain.
- `backend/app/schemas/transaction.py` — `ReturnRequest` contract change (outcome field shape, per Section 6 — exact form is an implementation-phase decision).
- `backend/app/core/exceptions.py` — possibly a new/adjusted exception (or adjusted message on the existing `TransactionAlreadyReturnedError`) to support the race-vs-genuine-repeat distinction, if that path is chosen over a shared message.
- `backend/app/api/v1/borrow.py` — likely no structural change (the `/return/{transaction_id}` route already calls `borrow_service.return_equipment()`; only the request/response types it passes through change indirectly via the schema update above).

**Frontend**
- `frontend/src/pages/ReturnPage.tsx` — outcome selector narrowed from the current 4-option condition radio group to a 2-choice usable/defective control, per the audit's own stated frontend impact for PR8 ("simplified to a single-step form with a two-choice outcome selector, no condition radio group"). This is a minimum functional change to the *options*, not the terminology/workflow redesign reserved for Roadmap PR11 — existing Thai labels/wording patterns are expected to carry forward except where the option set itself changes.
- `frontend/src/services/borrow.ts` — `ReturnPayload`/`createReturn` updated for the new outcome field shape.
- `frontend/src/types/index.ts` — `TransactionOut`/return-payload types updated to match.

**Tests**
- `backend/tests/test_borrow.py` — existing receipt tests adjusted for the new outcome-field contract; no wholesale rewrite expected, since the surrounding dispatch/audit assertions are unaffected.
- `backend/tests/test_equipment.py` — existing receipt-adjacent tests (`test_return_condition_cleaning_is_rejected_not_silently_accepted`, `test_defective_receipt_transitions_to_unavailable_defective`, `test_openapi_return_request_does_not_advertise_cleaning`, and others) adjusted for the new contract shape.
- `backend/tests/test_postgres_integration.py` — new dedicated receipt-concurrency test(s), mirroring the existing dispatch-burst test's structure and rigor (Section 8).
- `backend/tests/test_exception_handling.py` — reviewed for any receipt-path exception-envelope assertions that reference the old `condition` field.

**Migration**
- **None**, under the Option A recommendation (Section 5/7).
- Conditional: one new additive Alembic revision (e.g. `backend/alembic/versions/0009_*.py`) only if a future implementation phase chooses Option B instead.

**Documentation**
- `docs/BUSINESS_RULES.md` — "Dispatch/Return owns transaction lifecycle" section would need a new paragraph once PR8 actually merges (mirroring how PR7b's merge was reflected there), not part of this planning task.
- `docs/DOMAIN_MODEL.md` — "Transaction" section's receipt-outcome description would move from confirmed-target-but-not-yet-implemented to implemented.
- `knowledge/adr/ADR-005-transaction-model.md` — likely needs either a further addendum (mirroring its existing "Addendum (Roadmap PR7 7b slice)" section) or a new dedicated ADR, since a concurrency-guard mechanism is an architecture-level decision per `docs/PROJECT_PLAYBOOK.md`'s change-control policy ("Architecture/security invariant change -> Architecture Decision update and, when cross-cutting or high-risk, a detailed ADR") — PR8 is explicitly framed by the audit as "the most safety-critical PR in the plan," which argues for at least an ADR addendum, decided at implementation time, not here.
- `docs/ROADMAP.md`, `knowledge/PROJECT_MEMORY.md`, `knowledge/CONTEXT.md`, `knowledge/CHANGE_HISTORY.md`, `docs/DECISION_LOG.md` — the same post-merge governance-sync pattern already established for PR7a/PR7b (GitHub PR #21 is the most recent example) would apply after PR8 merges; not part of this planning task.

---

*This document is a design artifact only. No production code, migration, test, or other documentation file was created or modified as part of preparing it, per this task's explicit instructions.*
