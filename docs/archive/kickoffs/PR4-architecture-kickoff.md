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
(4-digit zero-padded suffix in current code; §12 covers the padding-width
decision — padding itself is mandatory per the plan, only its width is open).

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

**Uniqueness guarantees — two distinct guarantees, not one.** An earlier
version of this document conflated these; independent review (PR #12,
finding PR4-A1) correctly identified that only the first is automatic:

1. **Forward uniqueness (automatic, intrinsic to `SEQUENCE`):** no two
   values generated by `nextval('transaction_no_seq')` after the sequence
   exists are ever identical to each other. This requires no extra design
   — it is what a PostgreSQL sequence structurally guarantees under any
   level of concurrency.
2. **Historical uniqueness (NOT automatic — depends entirely on correct
   seeding):** no value generated by the sequence ever collides with a
   `transaction_no` that already exists in `borrow_transactions` from
   *before* the sequence went live. This guarantee holds **only if** the
   sequence is seeded from the true historical maximum at cutover, per
   §9's "Cutover and initialization requirement." A sequence created at
   PostgreSQL's default start value of `1` provides guarantee 1 but
   actively **violates** guarantee 2 the moment any historical
   `transaction_no` with a numeric suffix `>= 1` already exists — which is
   true for essentially any non-empty deployment, not just an edge case.

Both guarantees together are what the plan means by "uniqueness is
guaranteed entirely by the sequence" (Plan Part D, PR4) — a design that
only supplies guarantee 1 does not meet that bar.

**Concurrency expectations:**

- **Steady state (sequence already live and correctly seeded):**
  concurrent dispatch requests calling `nextval()` simultaneously always
  receive distinct values, with no read-then-write window, no row-level
  locking, and no retry logic required — this is the property that makes
  the design safe under a routine-round burst (§2), and it is what
  replaces the old `COUNT`+`LIKE` scan's race.
- **Cutover (the moment `transaction_no_seq` is created and
  `generate_transaction_no()` swaps from `COUNT`+`LIKE` to `nextval()`):**
  the old and new generators must never both be live for the same
  identifier space at the same time. If the legacy `COUNT`+`LIKE` path can
  still write a `transaction_no` *after* the new sequence has been seeded
  from the historical maximum but *before* the seeded sequence's value is
  actually ahead of that new write, the seeding computation is stale and
  guarantee 2 above can still be violated. This is a deployment-ordering
  requirement, not just a migration-content requirement — see §9's
  "Cutover and initialization requirement" for the precise rule this
  implies for how the migration and the code-path swap must be sequenced
  relative to live traffic.

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

**Change:** additive only — `CREATE SEQUENCE transaction_no_seq`. No new
table, no new column, no `ALTER` on `borrow_transactions`. No existing
`transaction_no` value is touched, backfilled, or reinterpreted —
historical values remain valid, untouched strings; only *newly generated*
values come from the sequence going forward (Plan Part E: "existing
`transaction_no` values are untouched and remain valid; the sequence only
governs values generated going forward").

**Cutover and initialization requirement — mandatory, not an
implementation detail.** An earlier version of this document assumed the
sequence could simply be created at PostgreSQL's default start value of
`1`, treating reseeding as a disaster-recovery-only concern. Independent
review (PR #12, finding PR4-A1, High) correctly identified this as unsafe:
this is not a fresh-database-only project — PR4 lands into a running
system that has already been generating `TX-{YYYYMMDD}-{seq}` values
(variable-length numeric suffix — see step 2 below) via the legacy
`COUNT`+`LIKE` generator, on every date up to and including the
date of cutover itself. A sequence created at `1` would make its first
`nextval()` call reproduce an already-existing historical suffix,
colliding with the `UNIQUE` constraint on `transaction_no` and failing the
very next dispatch after deployment. This corrects the document; it does
not conflict with the Roadmap plan, which never mandates a default-`1`
start — Part D only requires uniqueness "guaranteed entirely by the
sequence," and Part E's own verification-query column already anticipates
a collision check between historical and newly-generated values. Restating
that requirement as a **pre-traffic seeding rule** rather than a
**post-deployment check** is a strengthening within PR4's existing scope,
not a Roadmap contradiction requiring a Governance PR.

**The rule:** `transaction_no_seq` must never be assumed to start from
`1`. Its initial value must be derived from **persistent database
state** — specifically, the migration that creates the sequence must:

1. Scan all existing `transaction_no` values in `borrow_transactions`
   (across every date, not only the deployment date — see "Same-day
   deployment behavior" below).
2. Parse each value's trailing numeric suffix per the
   `TX-{YYYYMMDD}-{seq}` shape, where `{seq}` is a **variable-length
   numeric suffix, not a fixed four-digit field**. The legacy generator's
   `{count + 1:04d}` formatting sets a *minimum* width of 4 via
   zero-padding, not a maximum — once the same-day count exceeds `9999`,
   the legacy value is 5+ digits (e.g. `10000`), and the sequence-based
   generator's own values are permanently unbounded in width once the
   count is high enough (see §12's padding-width discussion, and §3's
   note that the global count never resets). An earlier version of this
   document's parser description implied an exact four-digit `NNNN`
   field; independent review (PR #12, finding PR4-N2, Medium) correctly
   flagged that an implementation matching only exactly 4 digits could
   silently skip a valid, higher-value historical suffix and compute an
   unsafe (too-low) seed. The parser must match `TX-` + an 8-digit date +
   `-` + **one or more digits** (any length, no upper or lower bound
   beyond "at least the legacy minimum width of 4"), and must not reject
   or truncate a longer suffix. Any value that does not match this shape
   at all (a malformed or non-conforming legacy-format value) is
   **skipped**, not treated as an error and not treated as `0` — it must
   not be allowed to either abort the migration or silently suppress a
   real historical maximum. This is a concrete, present-day case, not a
   hypothetical: this project's own `tests/test_borrow.py` fixture already
   uses non-conforming values such as `transaction_no="TX-TEST-0001"`,
   whose trailing token `"0001"` is numeric but whose middle token is not
   a date — the parser must be explicit about exactly which shape it
   accepts (date portion **and** variable-length numeric portion both
   required) so such values are deliberately and correctly excluded from
   the max computation, not accidentally included or excluded.
3. Compute the maximum successfully-parsed suffix across that full scan
   (or `0` if no row parses, i.e. a genuinely fresh database).
4. Create the sequence with `START WITH` (or, if the sequence already
   exists from a prior partial attempt, `ALTER SEQUENCE ... RESTART WITH`)
   set **strictly above** that computed maximum, before the migration
   completes and before any application code path can call `nextval()`
   on it.

A fresh, empty database naturally computes a maximum of `0` and the
sequence effectively starts at `1` — the "start at 1" outcome is still
correct for that case, but it must be the *result* of the seeding rule
applied to empty state, never a *hardcoded default* applied unconditionally.

**Same-day deployment behavior.** The scan in step 1 above must **not**
be scoped to "today's" date prefix only. Deployment can occur at any point
during an active business day — including between routine rounds, or
mid-way through one — at which point `borrow_transactions` may already
contain rows with **today's own `{YYYYMMDD}` prefix**, written by the
legacy generator earlier that same day, before cutover. If the seeding
scan were limited to historical dates *before* today (an easy mistake,
since "historical" intuitively suggests "past dates"), it would miss
exactly the rows most likely to collide — same-day rows share the
sequence's own date prefix and are the closest, most probable collision
candidates. The scan must consider the entire `borrow_transactions` table,
including rows created on the deployment date itself, with no date
filtering of any kind.

**Restart behavior.** Two distinct scenarios both use the same
seed-from-persistent-state mechanism described above, not two different
mechanisms:

- **Initial cutover** (this migration's own `CREATE SEQUENCE`): seed per
  the rule above, using the historical maximum at the moment the migration
  runs.
- **Disaster recovery** (the sequence object is later dropped and must be
  recreated, e.g. after a restore from an earlier backup): the exact same
  rule applies — recompute the historical maximum from
  `borrow_transactions` as it exists at *that* moment (which may now
  include rows generated by the sequence itself before it was lost) and
  restart strictly above it. There is no separate "disaster recovery only"
  code path; the same seeding logic is correct and required in both cases,
  and should be implemented once, not duplicated.

**Concurrency expectations for cutover itself.** Per §8's "Concurrency
expectations," the historical-maximum scan and the sequence's creation
must happen with no concurrent writer still using the legacy
`COUNT`+`LIKE` path once the sequence is live — otherwise a write that
lands between "scan computed the max" and "new code path takes over"
re-introduces exactly the collision this rule exists to prevent. The
implementing PR must therefore also specify (or explicitly defer as its
own decision, without silently assuming zero-risk) a deployment sequencing
approach — e.g. a single atomic release that applies the migration and
swaps `generate_transaction_no()`'s implementation together with no
rolling/mixed-version window, or an equivalent brief write-pause for
dispatch creation during cutover — rather than assuming application
traffic and the migration can safely interleave. This is flagged as Open
Question 4 in §12, since it affects deployment tooling, not just
application code.

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

**Verification queries (per Plan Part E's existing convention, corrected
to check the seed is safe *before* traffic, not merely absence of
collision *after* the fact):**
- Immediately after the migration's seeding step, before it commits:
  `SELECT last_value FROM transaction_no_seq;`, cross-checked to be
  strictly greater than the parsed maximum computed in step 3 of the
  "Cutover and initialization requirement" above — this is the
  authoritative pre-traffic safety check, not the older
  "confirm no collision after the fact" framing this document previously
  used, which is too late to prevent the failure the review identified.
- As an additional, non-authoritative sanity check only (defense in
  depth, not the primary control): post-deployment, confirm no collision
  actually occurred between any historical `transaction_no` and any
  newly-generated one.
- Disaster-recovery/restart scenario: the same pre-traffic check applies
  — verify the recomputed seed exceeds the recomputed historical maximum
  before the sequence is reintroduced to live traffic (see "Restart
  behavior" above).

**Rollback:** the sequence can be dropped in a downgrade; dropping it does
not affect any existing `borrow_transactions` row. If it is later
recreated (whether as a genuine downgrade-then-upgrade or a disaster
recovery), the same "Cutover and initialization requirement" seeding rule
applies again in full — recomputed against `borrow_transactions` as it
exists at that later moment, never assumed to still match the original
cutover's computed maximum (Plan Part E: "Sequence can be dropped; if ever
recreated, must be seeded above the highest historical suffix already in
use").

**Zero-downtime — conditional, not unconditional.** An earlier version of
this document stated "Zero-downtime: yes" without qualification, reasoning
only from `CREATE SEQUENCE` taking no meaningful table lock. Independent
review (PR #12, finding PR4-A2, High) correctly identified this as
contradicting "Concurrency expectations for cutover itself" above: the
statement was true for the *migration's own lock footprint* but ignored
the *scan-to-generator-swap window*, which is where this document's own
safety requirement actually lives. An implementer reading only "yes" could
reasonably conclude no special handoff is needed and let old-version
(`COUNT`+`LIKE`) writes continue after the historical maximum has been
computed — precisely the collision PR4-A1's fix exists to prevent. The
corrected statement:

- **The migration statement itself (`CREATE SEQUENCE ... START WITH ...`)
  is zero-downtime** in the narrow sense that it takes no meaningful lock
  and does not block reads/writes on `borrow_transactions`.
- **The overall cutover is zero-downtime only if the deployment handoff
  resolved under Open Question 4 (§12) actually prevents any old-version
  writer from using the legacy `COUNT`+`LIKE` path after the historical
  maximum has been scanned.** If the implementing team's deployment
  tooling can guarantee a single atomic release with no old/new
  mixed-version window (e.g. no rolling deploy across this specific code
  path), the cutover as a whole is genuinely zero-downtime. If it cannot
  make that guarantee, a **bounded dispatch-write pause** during cutover
  is required instead, and the cutover is *not* zero-downtime — it has a
  short, explicit, planned interruption to `POST /api/v1/borrow` only,
  not to the rest of the application.
- This document does not itself decide which of those two applies (that
  is Open Question 4); it requires the implementing PR to state explicitly
  which one was chosen and to prove the choice actually prevents a mixed
  old/new writer window, not merely assert it.

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
- **(PR4-A1) Given a PostgreSQL database populated with pre-existing
  `transaction_no` values for the current calendar date** (simulating
  deployment/cutover occurring mid-way through an active business day,
  after some dispatches have already been recorded that day by the legacy
  `COUNT`+`LIKE` generator — including at least one row whose numeric
  suffix is 5+ digits (proving the parser is not limited to exactly 4
  digits — see §9 step 2) and at least one row whose `transaction_no`
  does not match the `TX-{YYYYMMDD}-{seq}` shape at all, to prove
  malformed legacy values don't break or silently pass the seeding
  computation), **when the PR4 migration runs and the new generator is
  exercised immediately afterward — including under a simulated
  concurrent routine-round burst occurring right after cutover — then no
  generated transaction number ever equals, or ever collides with, any
  `transaction_no` value that existed before the migration ran**, and the
  first post-cutover generated value is strictly greater than the highest
  pre-existing same-day suffix. This criterion exists specifically to
  prove same-day deployment cannot produce a duplicate transaction number
  — see §9 "Cutover and initialization requirement" and "Same-day
  deployment behavior," and the corresponding test in §11.
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
- **(PR4-A1) Same-day/populated-cutover migration test — mandatory,
  added per independent review:** against a real PostgreSQL database,
  pre-populate `borrow_transactions` with `transaction_no` rows dated to
  the *current* date (not an earlier date — this is the specific gap the
  review identified), including:
  - at least one row with a numeric suffix of 5 or more digits (e.g.
    `TX-{today}-10000`), to prove the parser in §9 step 2 correctly
    handles a variable-length suffix and does not silently skip or
    misparse a valid historical value wider than the legacy generator's
    4-digit minimum padding (PR4-N2); and
  - at least one row with a non-conforming `transaction_no` value (e.g.
    matching the existing `test_borrow.py`-style `"TX-TEST-0001"`
    fixture shape) to prove the parser correctly skips it without
    corrupting the computed maximum.

  Then:
  1. Run the `0003` migration and assert (via
     `SELECT last_value FROM transaction_no_seq`) that the seeded value
     exceeds every parsed pre-existing same-day suffix.
  2. Immediately generate a burst of new transaction numbers (reusing the
     concurrency-burst harness from the PostgreSQL integration test
     above, run *right after* cutover rather than against an
     already-seeded, previously-used sequence) and assert none of them
     equal or collide with any pre-existing `transaction_no` value,
     seeded or historical.
  3. Repeat with a database populated using multiple distinct dates
     including today's, to confirm the scan is not accidentally
     date-filtered (§9 "Same-day deployment behavior").

  This test is the acceptance evidence for §10's PR4-A1 criterion and
  must exist before this PR4 kickoff is treated as addressing the
  reviewed finding — it is listed here as a required test for the future
  implementation PR, not implemented in this documentation-only PR.

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
- **`transaction_no`'s zero-padding width.** The plan (Part D, PR4) is
  explicit that `{seq}` is "the raw, **zero-padded** value from
  `nextval('transaction_no_seq')`" — zero-padding itself is not optional
  and is not this kickoff's decision to make (an earlier version of this
  document incorrectly offered "unpadded" as an alternative; independent
  review, PR #12 finding PR4-N1, correctly flagged this as
  Roadmap-noncompliant, and it is corrected here). The current legacy
  implementation pads to 4 digits (`{count + 1:04d}`), which was adequate
  for a same-day count but is not necessarily wide enough for a globally
  monotonic value that never resets and will eventually exceed `9999`.
  **What remains genuinely open is only the padding *width*** (e.g. 6 vs.
  8 digits) — not whether to pad at all.

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

2. **Zero-padding width for `{seq}`** (see Confirmed risks above — padding
   itself is mandatory per the plan; only the width is open) — needs an
   explicit choice, not an engineering default, since it's a permanent,
   hospital-visible display format per the plan's own framing ("the
   non-reset numeric format is elevated to a documented commitment, not
   an implementation detail," Plan §14 item 11's spirit).

3. **Daily-reset requirement — reconfirm it is still not needed.** The
   plan explicitly proceeds without hospital confirmation either way
   (Plan §14 item 11). This kickoff does not raise it as newly open, but
   flags that PR4's implementation is the last safe point to confirm this
   before the globally-monotonic format becomes operationally load-bearing
   and harder to change later without a data migration.

4. **Deployment/cutover sequencing for the migration and the generator
   swap.** §9's "Concurrency expectations for cutover itself" requires
   that the legacy `COUNT`+`LIKE` path and the new `nextval()`-based path
   never both be live for the same identifier space concurrently, but
   this kickoff does not choose the specific deployment mechanism that
   guarantees that (a single atomic release with no mixed-version
   window, vs. a brief write-pause for dispatch creation during cutover,
   vs. some other equivalent guarantee). That choice depends on this
   project's actual deployment tooling/process, which is outside this
   document's knowledge, and must be resolved — and stated explicitly in
   the implementing PR — before that PR can claim the same-day-deployment
   acceptance criterion (§10, PR4-A1) is actually satisfied in a real
   rollout, not just in an isolated test.

## 13. Implementation Sequence

Ordered steps for the (separate, future) implementation PR — no code is
written in this kickoff or its PR:

1. Resolve Open Question 1 (SQLite fallback strategy), Open Question 2
   (padding width), and Open Question 4 (deployment/cutover sequencing)
   with the Repository Owner/Architecture Owner before writing any code.
2. Author `backend/alembic/versions/0003_transaction_no_seq.py`
   (`down_revision = "0002_audit_request_ids"`), implementing the full
   "Cutover and initialization requirement" from §9: scan
   `borrow_transactions` for the existing historical maximum
   `transaction_no` suffix (skipping non-conforming values, across all
   dates including the deployment date), and create
   `transaction_no_seq` seeded strictly above that computed maximum —
   never at PostgreSQL's unconditional default of `1` — dialect-gated per
   the resolution of Open Question 1.
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
8. **Add the same-day/populated-cutover migration test (§10 PR4-A1, §11)
   — mandatory, not optional:** pre-populate same-day and malformed
   `transaction_no` rows, run the migration, and prove the seeded
   sequence and its first generated values cannot collide with any
   pre-existing value.
9. Add/confirm the exactly-one-audit-event test for dispatch under the
   new generator (§6).
10. Run the full existing suite (SQLite) to confirm no unrelated
    regression, and the full PostgreSQL suite plus `-m postgres` to
    confirm the new PostgreSQL-specific behavior, following the same
    evidence discipline PR3 established (exact commands and results
    recorded, SQLite and PostgreSQL results never conflated).
11. Open the implementation PR against the current base
    (`claude/medical-equipment-pool-0c7fz0`, currently at squash commit
    `0f2ef514fd52c432b8f53dff424efd672ed0f3fd`), documenting scope,
    exclusions, evidence, the sequence-gap/format decisions from §8 and
    §12, and the resolved cutover-sequencing approach (Open Question 4)
    explicitly, per `DEFINITION_OF_DONE.md`.
12. Obtain independent review (a separate agent/session — self-review is
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
- **The same-day/populated-cutover test (§10 PR4-A1, §11) passes against
  real PostgreSQL**, proving a migration seeded from a database already
  containing today-dated (and at least one malformed) legacy
  `transaction_no` values cannot produce a colliding value — this is the
  specific evidence required to close independent review finding PR4-A1
  and must not be treated as covered by the general concurrency-burst or
  disaster-recovery tests alone, since neither of those, by themselves,
  proves the *initial* seed is safe against *pre-existing same-day* data.
- The PR description explicitly documents: the sequence-gap-under-rollback
  behavior as intentional (§8), the two uniqueness guarantees and which
  one the seeding rule protects (§8), the resolved padding width (§12,
  padding itself is mandatory), the resolved SQLite-fallback approach
  (§12), the resolved cutover/deployment-sequencing approach (§12, Open
  Question 4), and confirms no PR5-or-later scope was introduced (per
  this document's §4).
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
