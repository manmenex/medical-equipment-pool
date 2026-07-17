# Roadmap PR4 Architecture Kickoff

**Status:** Architecture contract — no implementation in this document or its PR.
**Source of truth:** `docs/audits/04-consolidated-implementation-plan.md`, Part D,
"PR4 — Transaction-number generation: global sequence, explicit format" (the
authoritative scope for this PR; this kickoff narrows nothing and invents
nothing beyond it). Cross-referenced against Part E (migration strategy),
Part G.1 (concurrency test matrix), `AGENTS.md`, `docs/PROJECT_PLAYBOOK.md`,
`docs/ARCHITECTURE_GUARDRAILS.md`, `docs/HOSPITAL_DOMAIN_MODEL.md`,
`docs/DEFINITION_OF_DONE.md`, and the current backend implementation.

## 1. Objective

Replace the current racy `COUNT(*) ... LIKE` transaction-number generator
(`app/crud/transaction.py::generate_transaction_no`) with a single global,
concurrency-safe PostgreSQL `SEQUENCE` (`transaction_no_seq`), and state the
resulting number format explicitly and permanently.

Business outcome: every dispatch created during a routine round — when many
Equipment Pool staff may submit dispatches for distinct equipment within the
same tight time window — receives a **guaranteed-unique** transaction number
with zero possibility of collision, regardless of concurrency. Engineering
outcome: transaction-number generation becomes O(1) (`nextval()`) instead of
O(n) (`COUNT` + `LIKE` scan), and the generation mechanism is structurally
race-free rather than race-prone-but-usually-fine.

**Explicit format decision (already made by the plan, not open for this PR
to redesign):** `TX-{YYYYMMDD}-{seq}`, where `{YYYYMMDD}` is the calendar
date of creation (cosmetic/human-readable only — plays no role in
uniqueness) and `{seq}` is the raw, zero-padded value from
`nextval('transaction_no_seq')`. The numeric portion is **globally
monotonic and never resets** — e.g. `TX-20260716-000042` may be followed
the next day by `TX-20260717-000043`, not `TX-20260717-000001`. No
daily-reset requirement has been confirmed by the hospital (Plan §14, item
11); this PR must not assume one.

## 2. Hospital Workflow

The confirmed dispatch pattern (`docs/audits/04-consolidated-implementation-plan.md`
Part A, Part C item 6; `HOSPITAL_DOMAIN_MODEL.md`) is: **exactly four fixed
routine-round times per day (06:00/11:00/15:00/21:00), plus on-demand
dispatch**. At each routine-round time, Equipment Pool staff may submit
many dispatch requests for distinct equipment in a short window — this is
close to a worst-case trigger for the current generator's race condition
(many concurrent `COUNT`+`LIKE` reads against the same date-prefixed range,
each computing `count + 1` independently, with no exclusivity between the
read and the eventual `INSERT`).

Only the **transaction-number assignment step** of the dispatch workflow is
affected by this PR. The rest of dispatch (equipment lookup, availability
check, equipment status transition, dispatch-audit event) is unchanged and
out of scope — see §3/§4.

This PR does not touch receipt, ward recording, equipment identity, or any
later-workflow concept. It has no user-visible workflow change: an operator
scanning equipment at a routine round experiences no different flow, only a
transaction number that is now guaranteed collision-free under load.

## 3. In Scope

- A new PostgreSQL `SEQUENCE transaction_no_seq`, created via an additive
  Alembic migration.
- Rewriting `app/crud/transaction.py::generate_transaction_no()` to derive
  the numeric suffix from `nextval('transaction_no_seq')` instead of a
  `COUNT(*) ... WHERE transaction_no LIKE ...` scan.
- Preserving the existing external format `TX-{YYYYMMDD}-{seq}` (same
  prefix shape callers/tests already see) while changing what `{seq}`
  means (global monotonic sequence value, not a same-day count) — this is
  a **display-format-compatible, uniqueness-semantics-changing** update,
  not a visible contract break (see §7).
- Concurrency test coverage: many simultaneous dispatch requests each
  receive a unique transaction number with zero collisions (Plan Part
  G.1); an explicit test that the numeric suffix does **not** reset across
  a simulated day boundary; a disaster-recovery test confirming a
  freshly-recreated sequence is seeded above the highest historical
  suffix.
- Deciding (with owner input — see §12) how `generate_transaction_no()`
  behaves against the non-PostgreSQL SQLite test database used by the rest
  of the suite, since a raw `nextval()` call has no SQLite equivalent.
- Documenting, in the PR itself, that the non-reset numeric format is
  intentional and permanent (Plan §14 item 11) so hospital stakeholders
  are not surprised later.

## 4. Out of Scope

- **PR5 and later roadmap work:** ME Code / identifier separation (PR5),
  the 4-state equipment model (PR6), the dispatch-record rename to
  `OPEN`/`CLOSED` plus `dispatch_type`/`routine_round`/required-`ward_id`/
  `borrower_name`-optional/`due_at`-removal (PR7), the atomic
  single-operation receipt with concurrency guard (PR8), ward correction
  (PR9), role consolidation (PR10), frontend terminology (PR11), inventory
  import (PR12), search/history/reporting (PR13), and all Group 6
  hardening/observability items (PR14/PR15). None of PR7's field-level
  changes to `BorrowTransaction` are made here — this PR touches
  transaction-number **generation** only, not the transaction model's
  other fields, states, or terminology.
- **Frontend.** No frontend file is touched; the response field name and
  shape (`transaction_no: str`) do not change.
- **Reporting.** No dashboard, search, or history behavior changes.
- **Unrelated cleanup or refactor.** `generate_transaction_no()` and its
  one call site in `app/services/borrow_service.py::borrow()` are the only
  intended touch points. The existing direct `audit_crud.create(...)` call
  in `borrow()` (not the PR3 canonical writer — see §5) is not modified,
  redesigned, or migrated onto `record_audit_event()` by this PR; that
  would be an unrelated refactor of dispatch's audit call, which belongs
  to whichever future PR actually revisits the dispatch/receipt audit
  path, not this one.
- **Daily-reset counter design.** The plan's documented fallback (a
  `transaction_number_counters` table keyed by date) is explicitly **not
  implemented** unless the hospital later confirms an actual daily-reset
  requirement (Plan §14 item 11). Do not build it speculatively.
- **Commit-boundary centralization** (Backend Audit 6.1, deferred to PR14
  per the plan) — this PR uses the existing per-function manual-commit
  pattern already in `borrow_service.py`, unchanged.
- **Any equipment state, transaction state, ward, cleaning, patient,
  MEMS, PM, calibration, or recall concept** — none of these are touched;
  see `AGENTS.md` Domain Guardrails and `ARCHITECTURE_GUARDRAILS.md`.

## 5. Existing Foundation

- **PR1 (Production Security and Availability Foundation):** JWT
  production-secret startup guard, dashboard SSE connection-lifetime fix,
  Redis fail-open logging. PR4 does not depend on or touch any of this,
  but inherits a codebase that already boots safely and doesn't leak
  dashboard connections — no interaction expected.
- **PR2 (Structured Exception Handling):** `DomainError` subclasses and
  the consistent `{detail, code, status}` envelope, `IntegrityError`
  classification (`app/core/db_errors.py`). PR4's new generator does not
  introduce a new class of client-facing error — `nextval()` cannot
  "collide" the way the old `COUNT`+`LIKE` scan could produce a duplicate
  `transaction_no` (which would previously have surfaced as a raw,
  unhandled `IntegrityError` on the `UNIQUE` constraint under a genuine
  race). If a database-level failure occurs, it should still surface
  through PR2's existing `IntegrityError`/`db_errors.py` classification
  path — PR4 does not need a new error-handling mechanism, only to keep
  using the existing one correctly.
- **PR3 (Audit Logging Framework, just merged):** `record_audit_event()` /
  `record_best_effort_audit_event()` in `app/core/audit.py` is the
  canonical audit-write path for all *new* audited actions. **PR4 does
  not add a new audit event** — see §6/§8 — so it does not call this
  framework directly. It must not introduce a second, parallel
  transaction-numbering or audit mechanism (`ARCHITECTURE_GUARDRAILS.md`:
  "Do not create parallel audit, database-access, state-transition, or
  workflow mechanisms when an authoritative path exists").
- **Equipment MissingGreenlet fix (PR #10, squash-merged into the base as
  `00e9ec3`):** `Equipment.__mapper_args__ = {"eager_defaults": True}`.
  Unrelated to `BorrowTransaction`/transaction numbering; no interaction.
- **Current `generate_transaction_no()` (the exact code this PR
  replaces):**
  ```python
  async def generate_transaction_no(db: AsyncSession) -> str:
      today = datetime.utcnow().strftime("%Y%m%d")
      prefix = f"TX-{today}-"
      count_stmt = select(func.count()).select_from(BorrowTransaction).where(
          BorrowTransaction.transaction_no.like(f"{prefix}%")
      )
      count = (await db.execute(count_stmt)).scalar_one()
      return f"{prefix}{count + 1:04d}"
  ```
  (`backend/app/crud/transaction.py:12-19`). Its one call site is
  `app/services/borrow_service.py::borrow()` line 60, called before the
  `BorrowTransaction` row is constructed, inside the same request/session
  as the rest of dispatch.

## 6. Domain Model

**No new entity.** This PR modifies only how a value is generated for an
existing column:

- `BorrowTransaction.transaction_no` (`String(30)`, `unique=True`,
  `nullable=False`, indexed) — column is unchanged; only its value's
  *source* changes.
- **New database object, not an entity:** `transaction_no_seq`, a
  PostgreSQL `SEQUENCE`. It has no ownership, no row-level representation,
  and is not itself an audited or user-facing concept — it is
  infrastructure, analogous to how a UUID primary key is generated but
  never itself audited as a business event.

**Relationships:** unchanged. `BorrowTransaction` still belongs to one
`Equipment` and (optionally) one `Ward`/`Department`/etc., per the current
(pre-PR7) model.

**State transitions:** none. This PR does not touch `BorrowTransaction.status`,
`Equipment.status`, or any state-machine logic.

**Ownership / actors:** none new. The actor who triggers dispatch (and
therefore transaction-number generation) is unchanged — the authenticated
Equipment Pool operator recorded via `borrower_user_id`/the existing
dispatch-audit `user_id`.

**Timestamps:** none new. `transaction_no`'s embedded `{YYYYMMDD}` is
derived from the same `datetime.utcnow()` call already used today; no new
timestamp column or semantics.

**Audit expectations:** **no new audit event type.** Transaction-number
generation is not itself a business action requiring its own audit
row — it is an ID-assignment mechanism. The existing dispatch action
already produces exactly one audit event (`action="borrow"`,
`entity_type="borrow_transaction"`) via `borrow_service.py`'s direct
`audit_crud.create(...)` call, whose `after_data` already includes
`transaction_no`. That event's shape, content, and call path are
**unchanged** by this PR — the value it captures simply now comes from the
new generator. Confirm this via an explicit test (§11): dispatch under the
new generator still produces exactly one audit row, with `transaction_no`
matching the returned/response value, format-unchanged from the caller's
perspective.

## 7. API Contract

**No endpoint added, removed, or renamed.** `POST /api/v1/borrow` (the
existing dispatch endpoint) is the only endpoint that calls
`generate_transaction_no()`, transitively. Its request schema is
completely unaffected. Its response schema is unaffected: `transaction_no`
remains a plain string field in the same position, matching the same
`TX-{YYYYMMDD}-{seq}` textual shape existing clients already parse/display
(4-digit zero-padded suffix in current code; §10 below covers padding-width
implications precisely).

No new query parameters, no new request/response fields, no new status
codes are introduced by this PR. The plan is explicit that this PR's "API
contract impact" is "None — the display format is visually similar to
today's, though the numeric portion's meaning changes." This kickoff does
not invent any endpoint beyond what the plan already scopes to PR4 (which
is none) — per the instruction not to invent endpoints the roadmap
doesn't define.

Existing error behavior for `POST /api/v1/borrow` (404 equipment not
found, 409 equipment unavailable, etc., per PR2) is unchanged; PR4 removes
a *possible* new failure mode (a duplicate-`transaction_no` `IntegrityError`
under a genuine race) rather than adding one.

## 8. Transaction and Audit Design

**Atomicity:** `generate_transaction_no()` continues to be called inside
the same request/session and the same `db.commit()` boundary as the rest
of `borrow()` — no new transaction boundary is introduced
(`ARCHITECTURE_GUARDRAILS.md`: "Do not move transaction/commit boundaries
casually"). The sequence `nextval()` call itself does not need to be
wrapped in anything beyond the existing session usage.

**A structural property that must be documented, not "fixed":**
PostgreSQL sequences are **non-transactional** — `nextval()`'s effect is
never rolled back, even if the surrounding transaction (e.g. a dispatch
that later fails validation, hits the equipment-availability race, or is
otherwise aborted) rolls back. This means a rolled-back dispatch attempt
permanently "burns" one sequence value, producing a gap in the numeric
suffix. **This is expected and acceptable** — the plan's own uniqueness
guarantee is about the sequence never producing a *duplicate* value, not
about the sequence being gap-free (contrast with the daily-reset
per-date-counter fallback design, which the plan explicitly does not
require). This must be stated plainly in the implementing PR's
description so nobody later treats an observed gap as a bug.

**Duplicate prevention:** guaranteed structurally by PostgreSQL's atomic
`SEQUENCE` mechanism — not by application-level locking, retries, or
optimistic concurrency control. This is a strictly simpler mechanism than
the guard the old `COUNT`+`LIKE` approach implicitly and imperfectly relied
on.

**Retry behavior:** unchanged from the existing documented stance (Plan
Part G.1, "Retry after client timeout"): this codebase has no
idempotency-key mechanism for MVP; a client retry of a dispatch request is
indistinguishable from a new request and will consume a new sequence
value if it reaches `generate_transaction_no()`. This is consistent with
PR3's established "client retries are indistinguishable from any other
new request" precedent and is not a regression this PR needs to solve.

**Required audit events:** none new — see §6. The one existing dispatch
audit event's atomicity guarantee (mandatory, same-session,
flush-then-single-commit) is unchanged by this PR.

## 9. Database and Migration Plan

**New migration:** `0003_transaction_no_seq.py` (per the existing
`000N_description` naming convention —
`backend/alembic/versions/0001_initial.py`,
`0002_audit_request_ids.py`), `down_revision = "0002_audit_request_ids"`.

**Change:** additive only — `CREATE SEQUENCE transaction_no_seq` (no
starting value assumptions beyond PostgreSQL's default of `1`, unless a
disaster-recovery reseed is required — see below). No new table, no new
column, no `ALTER` on `borrow_transactions`. No existing `transaction_no`
value is touched, backfilled, or reinterpreted — historical values remain
valid, untouched strings; only *newly generated* values come from the
sequence going forward (Plan Part E: "existing `transaction_no` values are
untouched and remain valid; the sequence only governs values generated
going forward").

**Dialect scope — flagged, not silently decided (see §12):** a raw SQL
`SEQUENCE` object is PostgreSQL-specific; SQLite (used by the rest of this
project's test suite via the shared `client`/`db_session` fixtures) has no
native equivalent. The migration itself can be dialect-gated (mirroring
the existing `if settings.DATABASE_URL.startswith("postgresql")` pattern
already used in `app/db/session.py`, and the existing
`IF NOT EXISTS`-style dialect gating already established in
`0002_audit_request_ids.py`), but **`generate_transaction_no()`'s own
runtime behavior against a non-PostgreSQL session is an open question**
this kickoff surfaces rather than resolves — see §12.

**Verification queries (per Plan Part E's existing convention):**
- `SELECT last_value FROM transaction_no_seq;` — sanity-check immediately
  after creation.
- Post-deployment: confirm no collision between any historical
  `transaction_no` and any newly-generated one (a one-time cross-check,
  not an ongoing runtime check).
- Disaster-recovery scenario: if the sequence object is ever dropped and
  recreated, it must be reseeded above
  `SELECT max(transaction_no) ...` (parsed for its numeric suffix) or an
  equivalent safe floor — this is a documented operational procedure, not
  application code, but the implementing PR should include a test proving
  the *reseed logic itself* (however it's expressed — a migration helper,
  a documented `ALTER SEQUENCE ... RESTART WITH ...` runbook step, etc.)
  does not produce a value at or below any historical maximum.

**Rollback:** the sequence can be dropped in a downgrade; dropping it does
not affect any existing `borrow_transactions` row (Plan Part E: "Sequence
can be dropped; if ever recreated, must be seeded above the highest
historical suffix already in use").

**Zero-downtime:** yes — `CREATE SEQUENCE` takes no meaningful lock and
does not block reads/writes on `borrow_transactions`.

## 10. Acceptance Criteria

Restated from the plan (Part D, PR4) as observable, testable conditions:

- Given **N simultaneous dispatch requests** for **N distinct** available
  equipment (simulating a routine-round burst, e.g. 50–200 concurrent
  requests per Plan Part G.1), when all N complete, then all N receive a
  **transaction number, and no two share the same value** — asserted as
  an explicit uniqueness check over the full result set, not merely "no
  error occurred."
- Given a transaction number is generated, when its numeric suffix is
  inspected across a simulated day boundary (e.g. two dispatches whose
  `{YYYYMMDD}` prefixes differ), then the numeric suffix **is not reset**
  to a low value on the later date — it continues monotonically from
  wherever the sequence left off.
- Given a disaster-recovery scenario where the sequence is dropped and
  recreated, when it is reseeded per the documented procedure, then the
  next generated value is strictly greater than the highest
  already-used historical `transaction_no` suffix.
- Given the existing dispatch endpoint and its existing tests (e.g.
  `test_borrow_then_return_flow`), when they run against the new
  generator, then they continue to pass unmodified in their assertions
  about response shape (only the generator's internal implementation
  changes; no test should need to change its assertions about
  `transaction_no`'s *format*, only potentially its *test harness*
  wiring — see §12).
- Given a dispatch is created, when its audit row is inspected, then
  exactly one `action="borrow"` audit event exists and its
  `after_data.transaction_no` matches the value returned in the API
  response (§6).
- Generation is **O(1)** (a single `nextval()` call), not O(n) (no
  `COUNT`/`LIKE` scan remains in the implementation).

## 11. Test Strategy

- **Unit tests:** `generate_transaction_no()` in isolation — asserts the
  returned string matches the `TX-{YYYYMMDD}-{seq}` shape; asserts
  repeated calls within the same test produce strictly increasing,
  non-colliding suffixes.
- **API tests:** `POST /api/v1/borrow` end-to-end still returns 201 with a
  well-formed `transaction_no`; existing `test_borrow.py` assertions
  continue to pass (format-compatible; see §12 for the SQLite-fixture
  question that determines whether these run unmodified or need a
  Postgres-backed variant).
- **PostgreSQL integration tests** (following the established
  `tests/test_postgres_integration.py` / `pytest.mark.postgres` pattern
  from PR2/PR3): the concurrency-burst test (N simultaneous dispatches,
  zero collisions — this is the PR's core safety property and belongs
  here, against the real `SEQUENCE` object, not an emulation), the
  no-daily-reset test, and the disaster-recovery reseed test all require
  a real PostgreSQL `SEQUENCE`, per
  `DEFINITION_OF_DONE.md`: "PostgreSQL-backed evidence exists for
  PostgreSQL-specific behavior; SQLite alone is insufficient."
- **Transaction/rollback tests:** a dispatch that fails after
  `generate_transaction_no()` is called (e.g. equipment becomes
  unavailable in the same race window) rolls back the `BorrowTransaction`
  row and its audit event as today, while the consumed sequence value is
  *not* reclaimed (documented as expected — §8 — not tested as a "bug,"
  but a test can assert the gap exists and does not break subsequent
  generation).
- **Authorization tests:** none new required — `POST /api/v1/borrow`'s
  existing role gating (Equipment Pool Staff+ can dispatch;
  Read-Only/ward-side roles cannot, per current `require_roles` wiring)
  is unaffected by this PR and does not need re-verification beyond the
  existing suite continuing to pass.
- **Duplicate/retry tests:** the existing "duplicate scan / retry" test
  pattern from the current `test_borrow.py`
  (`test_cannot_borrow_unavailable_equipment`) continues to cover the
  same-equipment-availability guard; add one explicit test asserting a
  retried dispatch (after a first success) is rejected by that guard
  before it would ever reach transaction-number generation a second time
  for the same equipment — i.e., transaction-number uniqueness is never
  the *only* thing preventing a duplicate dispatch of the same equipment.
- **Migration tests:** upgrade (`0002` → `0003`) creates the sequence on a
  fresh PostgreSQL database and on a database that already has `0002`
  applied; downgrade drops it cleanly; re-upgrade recreates it — following
  the exact `test_migration_0002_upgrade_downgrade_round_trip` pattern
  already established in `tests/test_postgres_integration.py` for PR3's
  migration, extended to `0003`.

## 12. Risks and Open Questions

### Confirmed risks (not decisions — these are known properties to design around)

- **Sequence gaps under rollback.** PostgreSQL sequences are
  non-transactional; a rolled-back dispatch permanently consumes a
  suffix value. Documented and accepted in §8 — not a defect, but must be
  stated in the implementing PR so it isn't mistaken for one later.
- **This PR does not solve concurrent double-dispatch of the same
  equipment.** That protection is a separate, existing mechanism
  (`idx_tx_one_active_borrow`, the unique-partial-index guard already in
  `app/models/transaction.py`) and is unaffected by this PR either way —
  transaction-number uniqueness and same-equipment-availability are
  independent guarantees, both already required by Plan Part G.1, and
  this PR only strengthens the first.
- **`transaction_no`'s zero-padding width.** The current implementation
  pads to 4 digits (`{count + 1:04d}`), which was adequate for a
  same-day count but may not be for a globally monotonic value that never
  resets and will eventually exceed 9999. The plan's stated final format
  (`TX-{YYYYMMDD}-{seq}`) does not specify a fixed width for `{seq}` —
  this needs an explicit width decision (fixed wide padding, e.g. 6 or 8
  digits, vs. unpadded) before implementation, since it is a
  display/parsing detail no audit finding currently covers.

### Decisions requiring owner input (this kickoff intentionally does not decide these)

1. **SQLite fallback for `generate_transaction_no()`.** The existing test
   suite's default `client`/`db_session` fixtures run against in-memory
   SQLite (see `tests/conftest.py`), and the current
   `test_borrow.py` exercises `POST /api/v1/borrow` — and therefore
   `generate_transaction_no()` — through that SQLite path today. A raw
   PostgreSQL `nextval()` call has no SQLite equivalent. Before
   implementation starts, the owner must decide one of:
   - (a) give `generate_transaction_no()` a dialect-aware fallback (e.g.
     retain a SQLite-only `COUNT`+`LIKE`-style path purely for the
     non-Postgres test/dev database, with the real `SEQUENCE` path used
     whenever the dialect is PostgreSQL — mirroring the existing
     `settings.DATABASE_URL.startswith("postgresql")` pattern in
     `app/db/session.py`), accepting that the fallback path is *not* the
     mechanism this PR is meant to fix and is dev/test-only; or
   - (b) migrate the affected dispatch tests (`test_borrow.py` and any
     other SQLite-based test that triggers dispatch) onto a
     PostgreSQL-backed fixture, consistent with `DEFINITION_OF_DONE.md`'s
     general preference for PostgreSQL evidence over SQLite for
     PostgreSQL-specific behavior — a larger test-infrastructure change
     than PR4's own scope suggests, and worth flagging explicitly rather
     than assuming.

   This directly affects implementation shape and should be resolved
   before PR4's implementation PR opens, not discovered mid-implementation.

2. **Zero-padding width for `{seq}`** (see Confirmed risks above) — needs
   an explicit choice, not an engineering default, since it's a
   permanent, hospital-visible display format per the plan's own framing
   ("the non-reset numeric format is elevated to a documented commitment,
   not an implementation detail," Plan §14 item 11's spirit).

3. **Daily-reset requirement — reconfirm it is still not needed.** The
   plan explicitly proceeds without hospital confirmation either way
   (Plan §14 item 11). This kickoff does not raise it as newly open, but
   flags that PR4's implementation is the last safe point to confirm this
   before the globally-monotonic format becomes operationally load-bearing
   and harder to change later without a data migration.

## 13. Implementation Sequence

Ordered steps for the (separate, future) implementation PR — no code is
written in this kickoff or its PR:

1. Resolve Open Question 1 (SQLite fallback strategy) and Open Question 2
   (padding width) with the Repository Owner/Architecture Owner before
   writing any code.
2. Author `backend/alembic/versions/0003_transaction_no_seq.py`
   (`down_revision = "0002_audit_request_ids"`), creating
   `transaction_no_seq`, dialect-gated per the resolution of Open
   Question 1.
3. Rewrite `generate_transaction_no()` in `app/crud/transaction.py` to
   derive `{seq}` from `nextval('transaction_no_seq')` (via
   `SELECT nextval('transaction_no_seq')` through the existing
   `AsyncSession`), applying the padding width decided in step 1, and
   the resolved dialect-fallback shape.
4. No change required to `app/services/borrow_service.py`'s call site
   (`transaction_no = await transaction_crud.generate_transaction_no(db)`)
   — the function signature and return type (`str`) are unchanged.
5. Add the migration round-trip test (upgrade fresh, upgrade from `0002`,
   downgrade, re-upgrade), following the established
   `test_migration_0002_upgrade_downgrade_round_trip` pattern.
6. Add the PostgreSQL-marked concurrency-burst test (N simultaneous
   dispatches, zero collisions, per §11).
7. Add the no-daily-reset test and the disaster-recovery reseed test.
8. Add/confirm the exactly-one-audit-event test for dispatch under the
   new generator (§6).
9. Run the full existing suite (SQLite) to confirm no unrelated
   regression, and the full PostgreSQL suite plus `-m postgres` to
   confirm the new PostgreSQL-specific behavior, following the same
   evidence discipline PR3 established (exact commands and results
   recorded, SQLite and PostgreSQL results never conflated).
10. Open the implementation PR against the current base
    (`claude/medical-equipment-pool-0c7fz0`, currently at squash commit
    `0f2ef514fd52c432b8f53dff424efd672ed0f3fd`), documenting scope,
    exclusions, evidence, and the sequence-gap/format decisions from §8
    and §12 explicitly, per `DEFINITION_OF_DONE.md`.
11. Obtain independent review (a separate agent/session — self-review is
    not sufficient per `docs/PROJECT_PLAYBOOK.md`'s Roles and
    Independence table) before merge.

## 14. Exit Criteria

PR4 is ready for independent review when:

- All Section 10 acceptance criteria are demonstrated with automated
  tests and exact recorded commands/results (per
  `docs/DEFINITION_OF_DONE.md`'s evidence-in-the-PR-description
  requirements) — SQLite and PostgreSQL results kept separate and neither
  called CI when only run locally.
- The full existing regression suite passes unmodified in its assertions
  (only internal fixture/harness wiring may change if Open Question 1 is
  resolved toward option (a)).
- The migration round-trips cleanly on a real PostgreSQL database (fresh
  upgrade, upgrade from `0002`, downgrade, re-upgrade).
- The concurrency-burst, no-daily-reset, and disaster-recovery-reseed
  tests all pass against real PostgreSQL.
- The PR description explicitly documents: the sequence-gap-under-rollback
  behavior as intentional (§8), the resolved padding width (§12), the
  resolved SQLite-fallback approach (§12), and confirms no PR5-or-later
  scope was introduced (per this document's §4).
- No test was weakened, skipped, or made result-tolerant to reach a
  passing state (`PROJECT_PLAYBOOK.md`: "Tests must not normalize known
  failure behavior").
- Independent review is obtained from a separate agent/session and
  submitted directly to the Pull Request against its exact reviewed head
  SHA, per `docs/PROJECT_PLAYBOOK.md`.

PR4 is ready for merge when the above hold **and** the independent
review's substantive decision is APPROVE with no unresolved merge-blocking
finding, and the Repository Owner marks it ready and merges per repository
policy — the same gate structure just used for PR3 (`docs/PROJECT_PLAYBOOK.md`
§ Standard workflow, steps 5–9).

**Implementation can start on Section 13's steps 1–9 immediately after this
kickoff is reviewed** — but step 1 (owner decisions) blocks steps 2–4, and
therefore blocks meaningful progress on the core generator rewrite, until
answered. Everything else in this document is derived directly from the
existing consolidated plan and current codebase, not from assumption.
