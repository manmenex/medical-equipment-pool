# FastAPI Backend Architecture Audit — Medical Equipment Pool

**Reviewer:** Principal Backend Architect
**Scope:** `backend/app/` — API layer, service layer, CRUD layer, ORM usage, transaction/session management, auth/authz, background jobs. Read in full; every finding below is traced to a specific file/line, not inferred from documentation.
**Constraint honored:** No code was changed. This is analysis only.

---

## Executive Summary

The backend is cleanly layered (API → services → CRUD → models) and gets the *easy* concurrency case right — the borrow-side double-booking race is correctly closed with a DB-level partial unique index. But the audit surfaced **four Critical findings**, two of which are concrete, reproducible data-integrity bugs in the core borrow/return workflow (not hypotheticals), one is a connection-pool exhaustion bug that can take the entire API down under a very ordinary hospital usage pattern (a wall-mounted dashboard), and one is a shipped insecure default that permits full authentication bypass if a single environment variable is forgotten at deploy time. There is also a systemic gap: only two of the ~15 mutating write paths in this codebase produce an audit log entry, which undermines the compliance posture the project's own security documentation promises.

None of these require a rewrite — they're each a localized fix — but several of them should block a production go-live.

---

## 1. API Design

**Finding 1.1 — Inconsistent error envelope across endpoints**
- **Severity:** High
- **Location:** `app/api/v1/users.py` (`create_user`, `update_user`) uses raw `fastapi.HTTPException(status_code=400/404, detail=...)`; every other module uses the `DomainError` subclasses caught by the global handler in `app/main.py:42-47`.
- **Root Cause:** Two competing error-signaling mechanisms exist in the codebase and were applied inconsistently — `DomainError` (produces `{detail, code, status}`) vs. plain `HTTPException` (produces `{detail}` only).
- **Business Impact:** Any client code (including the shipped frontend's own `apiErrorMessage()` helper, which is written against the `{detail, code, status}` contract) cannot reliably distinguish error types for user-management errors specifically. Support/ops tooling built against `code` will silently misclassify these.
- **Technical Impact:** Contract drift between the documented API spec and the actual implementation; will worsen as more endpoints are added by different contributors following different examples.
- **Suggested Fix:** Standardize on the `DomainError` hierarchy for all domain-level errors; reserve raw `HTTPException` only for truly generic HTTP semantics.
- **Migration Risk:** None — code-only change, no schema/data impact.

**Finding 1.2 — Local (function-body) import breaks module-level readability convention**
- **Severity:** Low
- **Location:** `app/api/v1/transactions.py:40` imports `TransactionNotFoundError` inside `get_transaction()` instead of at module top, inconsistent with every other route module.
- **Root Cause:** Likely an artifact of incremental editing, not a deliberate circular-import workaround (no actual cycle exists here).
- **Business Impact:** None directly.
- **Technical Impact:** Minor readability/consistency debt.
- **Suggested Fix:** Move the import to the top of the file.
- **Migration Risk:** None.

---

## 2. Dependency Injection

**Finding 2.1 — Authorization dependency re-queries the database on every request instead of trusting the JWT claim**
- **Severity:** Medium
- **Location:** `app/api/v1/deps.py:40-57` — both `get_current_role_name()` and `require_roles()` independently run `select(Role).where(Role.id == user.role_id)` on every single protected call, even though `create_access_token()` (`app/core/security.py:35-41`) already embeds `role` in the signed JWT payload.
- **Root Cause:** The role claim in the token is written but never read back; authorization is re-derived from the DB from scratch every request instead of trusting the already-cryptographically-verified claim.
- **Business Impact:** At the documented 100+ concurrent-user target, this adds one guaranteed synchronous DB round-trip to *every single authenticated request* purely to re-fetch information already available for free.
- **Technical Impact:** Extra connection-pool pressure and query volume that scales linearly with request volume, for zero additional security benefit (the JWT is already integrity-protected; role staleness is bounded by the 15-minute access-token TTL either way).
- **Suggested Fix:** Read `role` directly from the decoded JWT payload in `get_current_user`/`require_roles`; only hit the DB for role information where the code path doesn't already have a token (e.g., none currently — all protected routes go through `get_current_user`).
- **Migration Risk:** None — behavior-preserving optimization.

**Finding 2.2 — Dead dependency output**
- **Severity:** Low
- **Location:** `app/api/v1/deps.py:36` sets `request.state.current_user = user`; grep confirms this is never read anywhere else in the codebase.
- **Root Cause:** Leftover from an earlier design (likely intended for logging/middleware that was never built).
- **Business Impact:** None.
- **Technical Impact:** Minor dead code.
- **Suggested Fix:** Remove, or wire it into the request-logging middleware this report separately recommends (§20).
- **Migration Risk:** None.

---

## 3. Service Layer

**Finding 3.1 — `return_equipment()` treats *any* non-`borrowed` status as "already returned," including the scheduler's own `overdue` status**
- See **§14 Race Conditions / Business Workflow Consistency** for the full analysis — this is the single most severe functional bug in the service layer. Flagged here because it's a service-layer design defect (an incomplete state machine), not just a race condition.

**Finding 3.2 — Business logic mixed with cache-invalidation and audit concerns inside the same function, with no clear separation between "what must be atomic" and "what can fail independently"**
- **Severity:** Low
- **Location:** `app/services/borrow_service.py:96-99, 148-152` — `cache_delete_prefix()` calls happen *after* `db.commit()`, correctly outside the atomic boundary (good), but there's no explicit comment/contract documenting *why* this ordering matters, so a future edit could easily move a cache call before the commit and silently reintroduce a cache-poisoning-before-durability bug.
- **Root Cause:** Correct behavior today, but undocumented as an invariant.
- **Business Impact:** None today; latent risk for future regressions.
- **Technical Impact:** Maintainability/tribal-knowledge risk.
- **Suggested Fix:** A short comment stating "cache invalidation must happen after commit, never before" would prevent this from regressing.
- **Migration Risk:** None.

---

## 4. CRUD Layer

**Finding 4.1 — PATCH-style `update()` functions cannot clear a field to `null`; explicit `null` is silently treated as "field omitted"**
- **Severity:** Medium
- **Location:** `app/crud/equipment.py:91-96` (`for key, value in data.items(): if value is not None: setattr(...)`) and `app/crud/user.py:46-57` (same pattern, e.g. `if data.get("phone") is not None: ...`).
- **Root Cause:** The CRUD layer conflates two distinct PATCH semantics — "key not present in payload" (already filtered by `model_dump(exclude_unset=True)` at the API layer) and "key present with value `null`" (a legitimate request to clear the field) — by treating both identically.
- **Business Impact:** An admin can never clear `equipment.brand`, `equipment.model`, `equipment.serial_number`, or `user.phone` back to empty via the API once set — e.g., correcting a data-entry mistake where a serial number was entered against the wrong asset requires a direct DB edit, not achievable through the product UI.
- **Technical Impact:** Violates standard partial-update (PATCH/JSON-Merge-Patch-adjacent) semantics; will confuse any API consumer familiar with the convention.
- **Suggested Fix:** Distinguish "unset" from "set to null" at the schema layer (Pydantic's `exclude_unset` already gives you this at the API boundary) and pass that distinction through to the CRUD layer instead of using truthiness/`is not None` as a proxy for "was this field intentionally provided."
- **Migration Risk:** None — application logic only.

**Finding 4.2 — `generate_transaction_no()` uses a racy `COUNT + LIKE` pattern instead of a proper sequence**
- See **§14 Race Conditions** for full detail (Location/Impact/Fix) — flagged here because the *architectural* fix belongs in the CRUD/data-access layer (introduce a real sequence), not the service layer.

---

## 5. SQLAlchemy Usage

**Finding 5.1 — No optimistic locking (`version_id_col`) on `BorrowTransaction` or `Equipment`, despite both being subject to concurrent mutation**
- **Severity:** High
- **Location:** `app/models/transaction.py`, `app/models/equipment.py` — neither model declares `__mapper_args__ = {"version_id_col": ...}`.
- **Root Cause:** The team solved the *borrow* concurrency problem with a DB-level unique constraint (a good, correct pattern) but never applied an equivalent safeguard to *any other* mutable row, including the same `BorrowTransaction` row on its return path.
- **Business Impact:** Directly enables the double-return bug (§14.1) and would similarly allow a lost-update on any other concurrent equipment mutation (e.g., two admins editing the same equipment record simultaneously — the second `PATCH` silently overwrites the first with no conflict signal to either user).
- **Technical Impact:** SQLAlchemy's default unit-of-work `UPDATE` statement is `UPDATE ... WHERE id = :id` with no additional predicate — it cannot detect that the row changed between when it was read and when it's written, unless a version column or explicit `WHERE` guard is added.
- **Suggested Fix:** Add optimistic locking (`version_id_col`) to `BorrowTransaction` at minimum (highest-value target given the return-race finding), and consider it for `Equipment` as usage grows.
- **Migration Risk:** Medium — additive `version` column, backfill default `1`, requires updating every write path in `equipment_crud`/`transaction_crud` to handle `StaleDataError`.

**Finding 5.2 — Exact `SELECT COUNT(*)` computed on every paginated list request, in addition to the row fetch**
- **Severity:** High
- **Location:** `app/crud/equipment.py:60-61`, `app/crud/transaction.py:76-79`.
- **Root Cause:** Cursor-based pagination was implemented, but an exact running total (`total`) was kept alongside it, requiring a second full-predicate scan on every request.
- **Business Impact:** At the documented 500,000+ equipment / 2,000,000+ transaction scale target, this doubles the cost of every search request and is the single largest concrete threat to the stated "<300ms search" requirement.
- **Technical Impact:** `COUNT(*)` under a broad/unfiltered predicate cannot be satisfied by an index-only scan efficiently at that row count without a covering index specifically for this purpose, and none exists.
- **Suggested Fix:** Drop the exact count in favor of a "has more" boolean (which cursor pagination doesn't strictly need `total` for), or compute `total` only on the *first* page of a given filter combination and cache it.
- **Migration Risk:** None (query/response-shape change only) — note the frontend currently renders `total` as a results-count label, so this is a coordinated frontend+backend change, not backend-only.

**Finding 5.3 — Correct, well-targeted use of `selectinload()` prevents N+1 on transaction reads (positive finding)**
- **Severity:** N/A (informational)
- **Location:** `app/crud/transaction.py:35, 52, 81` — every read path that returns `BorrowTransaction` with a nested `equipment` object explicitly eager-loads it.
- Worth stating explicitly: this is the correct pattern and should be the template for any new relationship-loading code, not an area needing remediation.

---

## 6. Transaction Boundaries

**Finding 6.1 — Commit boundaries are correct on the happy path but rely entirely on convention, not enforcement**
- **Severity:** Medium
- **Location:** Every mutating endpoint manually calls `await db.commit()` as the last line of its own function (`app/api/v1/equipment.py`, `borrow_service.py`, `users.py`, `master_data.py`, `auth_service.py`, `notifications.py` — 17 call sites total, confirmed by grep).
- **Root Cause:** There is no centralized "commit once at the end of the request, rollback on exception" pattern in `get_db()` (`app/db/session.py:15-17`) — every author is individually responsible for remembering to call `commit()`, and for calling it *after* every write that logically belongs in the same atomic unit, not before.
- **Business Impact:** Today's write paths happen to get this right (verified: `borrow()` and `return_equipment()` each perform all their writes — transaction row, equipment status, audit log — before a single terminal `commit()`, so they are correctly atomic). But this correctness is *accidental per-author discipline*, not structurally guaranteed. A future contributor adding a new mutating endpoint has no scaffolding stopping them from committing too early, splitting a logical unit across two commits, or forgetting to commit at all (which would silently no-op the write with no error — the request would return 200 with data that was never persisted, since `get_db()`'s implicit close()-triggered rollback would discard the uncommitted flush).
- **Technical Impact:** This is the root architectural cause behind Finding 3.1's blast radius being as large as it is — there's no session-level safety net catching "you forgot to keep these writes in the same transaction."
- **Suggested Fix:** Move the commit boundary into `get_db()` itself (commit on clean generator exit, rollback on exception), so route/service authors only ever call `db.flush()` and the transaction boundary is enforced structurally rather than by convention.
- **Migration Risk:** Medium — touches every mutating endpoint's control flow (removing their individual `db.commit()` calls); needs a full regression pass across the test suite, but is a well-understood, mechanical refactor.

---

## 7. Rollback Safety

**Finding 7.1 — Manual rollback is applied in exactly one place; every other exception path relies on implicit cleanup, and this asymmetry is undocumented**
- **Severity:** Medium
- **Location:** `app/services/borrow_service.py:79-81` explicitly calls `await db.rollback()` before re-raising on `IntegrityError`; no other exception path in the entire codebase does this.
- **Root Cause:** `AsyncSession.close()` (invoked implicitly when `get_db()`'s `async with` block unwinds on any exception) does perform a rollback internally, so the other paths are *not* actually unsafe today — but nothing in the code documents this as the relied-upon safety net, and the one place that *does* roll back manually gives the misleading impression that manual rollback is required everywhere, which it is not (and doing so inconsistently is itself a source of future bugs, e.g. a future author adding a second manual rollback inside a `try/except` that also lets the exception propagate to `get_db()`'s cleanup, calling rollback twice on an already-closed session).
- **Business Impact:** None currently observable — flagged as a maintainability/correctness-clarity risk, not a live bug.
- **Technical Impact:** Verified via code reading, not testing, that this assumption holds for the current session lifecycle configuration; it would silently break if `get_db()` were ever changed to reuse a session across requests or to swallow exceptions before they reach the `async with` boundary.
- **Suggested Fix:** Document the rollback-on-close contract explicitly (a comment on `get_db()` stating "any exception raised from within a request results in an implicit rollback via session.close() — do not add manual rollback calls except where you need to continue using the session after catching a specific expected error, as in borrow_service.borrow()").
- **Migration Risk:** None.

---

## 8. Concurrency Handling

**Finding 8.1 — Architecture is correctly stateless and horizontally scalable, but the connection pool is a single, unguarded shared resource with no per-endpoint budget**
- **Severity:** Critical
- **Location:** `app/db/session.py:7-9` (`pool_size=20, max_overflow=10` = 30 total connections per backend instance) combined with `app/api/v1/dashboard.py:31-39` (see §17 for full detail).
- This is the architectural root cause of the Session Lifetime finding below — flagged here at the "concurrency handling" level because it represents a missing design principle (long-lived/streaming endpoints must not share the same bounded resource pool as short-lived transactional endpoints) rather than a single-line bug.
- **Suggested Fix:** See §17.

---

## 9. Exception Handling

**Finding 9.1 — Only one exception type (`DomainError`) has a global handler; multiple code paths deliberately raise other exception types that are consequently unhandled and surface as raw 500s**
- **Severity:** High
- **Location:** `app/main.py:42-47` registers a handler for `DomainError` only. Three concrete, easily-triggered gaps:
  1. **`sqlalchemy.exc.IntegrityError`** — unhandled in `app/api/v1/equipment.py:132` (`create_equipment`), `app/api/v1/users.py:40` (`create_user`), and all four `create_*` handlers in `app/api/v1/master_data.py` (departments/wards/locations/categories). Any duplicate `asset_number`, `employee_code`, `email`, department `code`, etc. produces an unhandled exception.
  2. **Bare `ValueError`** — `app/services/borrow_service.py:122` raises plain `ValueError(f"Unknown condition '{condition}'")` when `ReturnRequest.condition` (typed as unconstrained `str` in `app/schemas/transaction.py:23`, no `Literal`/enum validation) doesn't match one of the five known values. Also `uuid.UUID(equipment_id)` in `borrow_service.borrow()` raises bare `ValueError` for a malformed (non-UUID) `equipment_id` string, since `BorrowRequest.equipment_id` is typed as plain `str` with no format validation.
  3. **Inconsistent `HTTPException` usage** — see Finding 1.1.
- **Root Cause:** The exception-handling strategy was designed around the `DomainError` hierarchy but never extended to cover exceptions raised by SQLAlchemy itself or by ad-hoc `raise ValueError(...)` calls that were added later as a convenience.
- **Business Impact:** A ward nurse submitting a return with an unexpected `condition` value (e.g., a frontend bug, a stale client build, or a manual API call) gets a generic server error instead of a clear "invalid condition" message. Any duplicate-registration attempt (extremely common in practice — biomedical staff re-scanning an asset that's already in the system) produces a 500 instead of a clean 409.
- **Technical Impact:** 500 responses are indistinguishable from genuine server faults in monitoring/alerting, polluting error-rate metrics with what are actually ordinary client-input mistakes; no traceback control (depends on deployment `DEBUG` setting whether internals leak to the client).
- **Suggested Fix:** Add handlers for `IntegrityError` (map to a generic `409 DUPLICATE` using the existing `DuplicateError` class, which is already defined in `app/core/exceptions.py:30-32` but never raised anywhere), constrain `ReturnRequest.condition` to a `Literal`/enum at the Pydantic layer (rejects bad input before it reaches the service layer at all), and validate `equipment_id`/other UUID-typed string fields with Pydantic's UUID type instead of plain `str`.
- **Migration Risk:** None — additive validation and exception handling.

---

## 10. Authentication

**Finding 10.1 — Insecure default `JWT_SECRET_KEY` ships in source with no production-time guard**
- **Severity:** Critical
- **Location:** `app/core/config.py:21` — `JWT_SECRET_KEY: str = "change-me-in-production-use-a-random-64-byte-value"`.
- **Root Cause:** Pydantic Settings silently falls back to this literal string if the `JWT_SECRET_KEY` environment variable is unset at runtime; there is no startup assertion rejecting the default value when `ENVIRONMENT=production`.
- **Business Impact:** If a deployment (very plausible in a hospital IT environment without dedicated DevOps, per this project's own stated context) forgets to set this one environment variable, **any party with knowledge of this default string — which is now public in this exact source tree — can forge a valid, signed JWT for any user ID and any role, including `admin`,** and gain full unauthenticated access to every protected endpoint, including user management and equipment status manipulation. This is a complete authentication bypass, not a degraded-security scenario.
- **Technical Impact:** `jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")` (`app/core/security.py:32`) is symmetric-key signing; possession of the key is possession of full forgery capability.
- **Suggested Fix:** Add a startup check that raises immediately if `ENVIRONMENT == "production"` and `JWT_SECRET_KEY` equals the known default (or is below a minimum entropy/length threshold); fail closed, not open.
- **Migration Risk:** None — this is a guard-rail addition, not a data change. (Any environment currently running with the default key does need an out-of-band secret rotation once addressed — that invalidates all outstanding tokens, which is the correct/expected behavior.)

**Finding 10.2 — No rate limiting on `/auth/login`, despite being explicitly documented as a designed control**
- **Severity:** High
- **Location:** `app/api/v1/auth.py:26-30`; grepped the entire codebase for rate-limiting middleware/libraries (`slowapi`, custom limiter) — none exists.
- **Root Cause:** `docs/08-security.md` states "Login rate-limited (Redis, 5 attempts / 15 min per account+IP)" as part of the security design, but this was never implemented.
- **Business Impact:** The login endpoint is open to unlimited-attempt online brute-force/credential-stuffing against any known `employee_code`. Combined with Finding 12.1 (no login audit trail), a sustained brute-force attempt would be both unthrottled and invisible.
- **Technical Impact:** `bcrypt` (cost factor 12, ~100ms+ per attempt) provides some natural throttling per-request, but at typical attacker concurrency this is not a meaningful defense.
- **Suggested Fix:** Implement the Redis-backed rate limit exactly as documented, keyed on `identifier + client IP`.
- **Migration Risk:** None.

**Finding 10.3 — Refresh-token revocation fails open, silently, if Redis is unreachable**
- **Severity:** High
- **Location:** `app/core/redis.py:47-55` (`is_refresh_token_valid`) — `except Exception: return True`, with an explicit comment documenting the fail-open decision, but **no logging of the exception that triggered it**.
- **Root Cause:** A deliberate availability-over-strict-security tradeoff (documented in-code), but implemented with zero observability — if this path is hit in production, nothing surfaces it.
- **Business Impact:** If an admin revokes a compromised user's session (logout / forced revocation) while Redis is down or momentarily unreachable, the stolen refresh token continues to mint valid access tokens until it naturally expires (`JWT_REFRESH_EXPIRE_DAYS`, default 7 days) — the revocation silently does not take effect, and no one is alerted that it didn't.
- **Technical Impact:** Same root cause as the general Redis error-swallowing pattern (§20), but this specific instance has direct security consequences rather than just a performance/cache-miss consequence.
- **Suggested Fix:** Log at `WARNING`/`ERROR` level whenever this fail-open path is taken, and consider alerting on it; evaluate whether a shorter refresh-token TTL better bounds the blast radius of this tradeoff.
- **Migration Risk:** None.

---

## 11. Authorization

**Finding 11.1 — Correctly enforced RBAC, no bypass found — but two design gaps worth noting**
- **Severity:** Medium
- **Location:** `app/api/v1/deps.py:46-57` (`require_roles`).
- Verified: every mutating endpoint declares an explicit role requirement matching the documented permission matrix (`docs/03-api-specification.md`), and the checker correctly returns 403 for an unlisted role. No route was found missing an authorization dependency where one should exist.
- **Gap 1:** Authorization is role-based only — there is no resource-level check anywhere (e.g., nothing stops a `ward_nurse` from returning equipment on behalf of a transaction they had no involvement in, which may be intentional for this domain, but is worth confirming against actual hospital policy rather than being an implicit consequence of the schema).
- **Gap 2:** `notifications.py:41-46` (`mark_read`) is the *only* endpoint in the codebase that enforces row-level ownership (`if notification and notification.user_id == user.id`) — and notably, it does so by silently no-op'ing (returning `{"detail": "ok"}`) rather than returning 403/404 when the notification belongs to someone else, which leaks no information but also gives a false-positive success response to a client trying to mark another user's notification as read.
- **Business Impact:** Low as currently used; worth flagging as the pattern doesn't generalize if row-level ownership checks are needed elsewhere later.
- **Suggested Fix:** No action required for current scope; if resource-level authorization is later needed elsewhere, don't copy the silent-no-op pattern — return an explicit 403/404.
- **Migration Risk:** None.

---

## 12. Audit Logging

**Finding 12.1 — Zero audit trail for user/role management: user creation, role changes, password resets, and account deactivation are completely unaudited**
- **Severity:** Critical
- **Location:** `app/api/v1/users.py:33-63` (`create_user`, `update_user`) — neither calls `audit_crud.create()` at any point; grep confirms `app/crud/audit.py` is imported nowhere in `users.py`.
- **Root Cause:** Audit logging was implemented per-endpoint by copy-paste from `equipment.py`'s pattern and was never extended to the user-management module.
- **Business Impact:** In a hospital system, the ability to create an Admin account, silently escalate another account's role, or reset any user's password is the single most security-sensitive capability in the application — and none of it leaves a trace. If an Admin credential is compromised or a malicious insider abuses access, there is no way to answer "who created this account" or "who changed this person's role to Admin and when," which is precisely the question a security incident investigation or compliance audit needs answered. This directly contradicts the project's own stated security design (`docs/08-security.md`: "Every create/update/delete/status-change on ... users writes an audit_logs row").
- **Technical Impact:** The `audit_logs` schema and `audit_crud.create()` function already fully support this — it is a call-site gap, not a design gap.
- **Suggested Fix:** Add `audit_crud.create()` calls to `create_user` and `update_user`, capturing role/`is_active` changes explicitly (and treating password resets as an auditable event without logging the password itself).
- **Migration Risk:** None — additive.

**Finding 12.2 — No audit trail for authentication events or master-data mutations**
- **Severity:** High
- **Location:** `app/api/v1/auth.py` (login/logout/refresh — no audit calls at all) and `app/api/v1/master_data.py` (all four `create_*` handlers — no audit calls).
- **Root Cause:** Same as 12.1 — audit logging exists only where it was manually copy-pasted (`equipment.py`, `borrow_service.py`).
- **Business Impact:** No record of login attempts (successful or failed), no record of who created a department/ward/location/category or when. Lower severity than 12.1 because these are lower-privilege operations, but still a real compliance gap against the project's own documented commitment.
- **Suggested Fix:** Same pattern as 12.1, extended to these modules; consider a lightweight decorator or service-layer hook so future endpoints get audit logging by default rather than requiring every author to remember it (this recurring gap across independent modules suggests the "remember to call audit_crud.create()" convention doesn't scale).
- **Migration Risk:** None.

**Finding 12.3 — Automated/system-driven state changes bypass the audit trail entirely**
- **Severity:** Medium
- **Location:** `app/worker/scheduler.py:88-89` — `check_overdue_returns()` sets `tx.status = TX_STATUS_OVERDUE` directly, with no corresponding `equipment_status_history` or `audit_logs` entry.
- **Root Cause:** The scheduler was written against the transaction row directly, bypassing the service-layer functions (`equipment_crud.change_status`, `audit_crud.create`) that every user-initiated path goes through.
- **Business Impact:** The "who/what/when" audit trail has a blind spot for every automated transition — an equipment item's overdue flag appears with no traceable cause in the audit log, only inferable by cross-referencing `due_at` against `updated_at`.
- **Suggested Fix:** Route scheduler-driven mutations through the same audited service functions, using a documented "system actor" convention (ties to the schema-review finding on nullable `changed_by_user_id`).
- **Migration Risk:** None.

---

## 13. Performance

Covered in depth across §5 (SQLAlchemy usage — `COUNT(*)` cost), §16 (N+1), §17 (session lifetime / connection pool exhaustion), and below:

**Finding 13.1 — Synchronous, CPU-bound work executed directly on the async event loop with no threadpool offload**
- **Severity:** High
- **Location:**
  - `bcrypt.hashpw` / `bcrypt.checkpw` (`app/core/security.py:13-18`), called directly inside `authenticate()`. bcrypt at cost factor 12 is deliberately ~100–300ms of pure CPU work.
  - `openpyxl` `Workbook`/`ws.append`/`wb.save()` (`app/services/report_service.py:59-69`), building an in-memory workbook for up to 50,000 rows.
  - `qrcode.make()` (`app/services/qr_service.py`), smaller magnitude but same pattern.
  - Confirmed via grep: no use of `asyncio.to_thread` or Starlette's `run_in_threadpool` anywhere in the codebase.
- **Root Cause:** FastAPI's async model gives you concurrency across I/O-bound `await` points, but a synchronous CPU-bound call inside an `async def` blocks the *entire* single-threaded event loop for its full duration — every other in-flight request on that worker process stalls until it completes.
- **Business Impact:** Directly threatens the documented "100+ concurrent users" requirement. A shift-change login burst (many nurses authenticating within the same minute — a very realistic hospital pattern) serializes on bcrypt cost, degrading response time for every concurrent user on that worker, not just the ones logging in. A single large report export blocks the entire process for the duration of the Excel build.
- **Technical Impact:** No exception is raised, no error surfaces — this is a silent, load-dependent latency/availability degradation, which makes it harder to diagnose in production than a hard failure.
- **Suggested Fix:** Wrap these specific calls in `asyncio.to_thread(...)` (or run the whole endpoint as a sync `def` for FastAPI's automatic threadpool dispatch, for the report-export endpoint specifically).
- **Migration Risk:** None — code-only, behavior-preserving.

---

## 14. Race Conditions

**Finding 14.1 — CRITICAL: A `BorrowTransaction` can be returned twice concurrently, with the second return silently overwriting the first**
- **Severity:** Critical
- **Location:** `app/services/borrow_service.py:114-118` — `tx = await transaction_crud.get_by_id(...)`, then `if tx.status != TX_STATUS_BORROWED: raise TransactionAlreadyReturnedError(...)`, then unconditional mutation and `db.commit()` at line 148.
- **Root Cause:** This is a classic check-then-act (TOCTOU) race with **no database-level guard**. Contrast with the borrow side, which is correctly protected by the `idx_tx_one_active_borrow` partial unique index (`app/models/transaction.py:17-25`) — that same category of protection was never applied to the return path. SQLAlchemy's default ORM `UPDATE` statement is `UPDATE borrow_transactions SET status=..., returned_at=... WHERE id = :id` — it has no `AND status = 'borrowed'` guard and no version column (§5.1), so it cannot detect that another transaction already returned this row between the `SELECT` and the `UPDATE`.
- **Concrete sequence:**
  1. Two concurrent `POST /return/{id}` requests for the same transaction (e.g., a nurse double-tapping "Confirm Return" on a slow connection, or two staff members both scanning the same item).
  2. Both read `tx.status == 'borrowed'` (Postgres READ COMMITTED default — neither has committed yet, so both see the same pre-update state).
  3. Both proceed past the status check, both call `equipment_crud.change_status()` (creating **two** `equipment_status_history` rows for the same transition), both call `audit_crud.create()` (**two** audit entries for one physical event), both commit.
  4. The second `UPDATE` to commit wins with no conflict signal — the equipment's final status reflects whichever request's `condition` value happened to commit last, and the *first* returning user's condition report (e.g., "repair needed") can be silently discarded in favor of the second's ("available").
- **Business Impact:** For medical equipment, silently losing a "this needs repair" or "needs calibration" condition report in favor of a later, possibly erroneous "available" report is a direct patient-safety-adjacent risk — the equipment re-enters the available pool marked usable when the first (correct) report said otherwise.
- **Technical Impact:** No exception, no log signal distinguishing this from a normal single return — the double-processing is invisible unless someone specifically audits for duplicate `equipment_status_history` rows against one transaction.
- **Suggested Fix:** Apply the same class of fix used for the borrow side — either a `WHERE status = 'borrowed'` clause on the update combined with checking the affected-row count (reject if zero), or optimistic locking (§5.1), or a unique-index-backed application-level guard equivalent to `idx_tx_one_active_borrow`.
- **Migration Risk:** Low-Medium depending on approach — a conditional-update pattern is code-only; optimistic locking requires an additive column.

**Finding 14.2 — CRITICAL (business-workflow): once a transaction is marked `overdue` by the scheduler, the equipment can never be returned through the normal API again**
- **Severity:** Critical
- **Location:** `app/worker/scheduler.py:89` sets `tx.status = TX_STATUS_OVERDUE`; `app/services/borrow_service.py:117-118` checks `if tx.status != TX_STATUS_BORROWED: raise TransactionAlreadyReturnedError(...)`.
- **Root Cause:** The return-eligibility check treats **any** status other than `'borrowed'` as "already returned." The scheduler introduces a third status value (`'overdue'`) that the return-eligibility check was never updated to account for.
- **Concrete sequence:**
  1. A `BorrowTransaction` is created with a `due_at` in the past (or one that later lapses).
  2. `check_overdue_returns()` runs (hourly cron) and flips `tx.status` to `'overdue'`.
  3. A ward nurse or transport staff member tries to actually return the equipment: `POST /return/{transaction_id}`.
  4. `return_equipment()` sees `tx.status == 'overdue' != 'borrowed'` and raises `TransactionAlreadyReturnedError("This transaction has already been returned")` — a **false and actively misleading** error, since the equipment was never returned at all; it's the exact opposite state.
  5. The equipment is now stuck: it shows as `equipment.status == 'borrowed'` indefinitely, and the primary return workflow used by Ward Nurses/Transport Staff can never process it again. Only an Admin/Biomedical Engineer using the separate manual `POST /equipment/{id}/status` endpoint can manually correct it — an undocumented, non-obvious workaround for what should be routine equipment turnover.
- **Business Impact:** Every overdue loan silently becomes un-returnable through the normal workflow the moment the scheduler marks it overdue — for a hospital equipment pool, this means any equipment that runs late (which is exactly the population most likely to need to come back into circulation urgently) effectively vanishes from the available pool until manual admin intervention is discovered and applied. This is very likely to be encountered in real operation, not an edge case.
- **Technical Impact:** The `BorrowTransaction.status` state machine was designed as a two-state system (`borrowed` → `returned`) but a third automated state (`overdue`) was added later without updating the one piece of code that gates the terminal transition.
- **Suggested Fix:** Change the eligibility check to explicitly test for the states that *are* returnable (`status in (TX_STATUS_BORROWED, TX_STATUS_OVERDUE)`) rather than testing for the one state that is not (`status != TX_STATUS_RETURNED`), and reserve `TransactionAlreadyReturnedError` specifically for `status == TX_STATUS_RETURNED`.
- **Migration Risk:** None — pure logic fix, no schema change required.

**Finding 14.3 — HIGH: Concurrent borrow attempts on *different* equipment can collide on `transaction_no` and misreport the cause**
- **Severity:** High
- **Location:** `app/crud/transaction.py:12-19` (`generate_transaction_no`) + `app/services/borrow_service.py:79-81` (blanket `except IntegrityError`).
- **Root Cause:** `generate_transaction_no()` computes the next sequence number via `COUNT(*) WHERE transaction_no LIKE 'TX-{today}-%'` — a read-then-derive pattern with no locking. Two concurrent borrows (of two *different* pieces of equipment, so the equipment-level unique index doesn't apply) can compute the identical "next" number before either commits. The second `INSERT` then fails on the *separate* `transaction_no` `UNIQUE` constraint — but the surrounding `except IntegrityError` block unconditionally reinterprets **any** `IntegrityError` as `EquipmentNotAvailableError("Equipment was just borrowed by someone else")`.
- **Business Impact:** A legitimate borrow of genuinely-available equipment can be rejected with a misleading "someone else just borrowed it" error purely due to an unrelated numbering collision with a *different* concurrent borrow — under realistic load (e.g., simultaneous morning equipment checkout across several wards), this produces confusing, hard-to-explain failures and forces the user to retry for no real reason (there is no automatic retry).
- **Technical Impact:** The error-handling code cannot distinguish which constraint fired, so it cannot recover correctly from this specific case.
- **Suggested Fix:** Replace the `COUNT`-derived numbering scheme with a proper database `SEQUENCE` (race-free, O(1)) instead of relying on catch-and-reinterpret error handling to paper over a preventable race.
- **Migration Risk:** Medium — introduces a new sequence object; existing transaction numbers remain valid, only the generation mechanism changes going forward.

---

## 15. Deadlock Risks

**Finding 15.1 — No classic multi-row lock-ordering deadlock pattern found (informational, verified negative)**
- **Severity:** N/A (informational — stated explicitly rather than manufacturing a finding)
- Every write path in this codebase touches, at most, one contested row (one `Equipment` row, one `BorrowTransaction` row) plus pure inserts (audit log, status history). No code path acquires locks on two independently-contested rows in an order that could reverse with another concurrent transaction, which is the precondition for a classic database deadlock. The actual concurrency risks in this codebase (§14) are lost-update races, not deadlocks — this distinction matters for how they're fixed (constraints/locking versions vs. lock-ordering discipline).

**Finding 15.2 — Application-level "deadlock-equivalent": pool exhaustion can make new requests hang indefinitely**
- **Severity:** Critical (cross-reference — same root cause as §17.1, not double-counted in the summary table)
- **Location:** `app/db/session.py:7-9` combined with `app/api/v1/dashboard.py:31-39`.
- If the connection pool (30 total connections) is exhausted by long-lived SSE connections (§17.1), a new request's `get_db()` call blocks waiting for a pool checkout. This isn't a database-level deadlock, but it is functionally indistinguishable to an end user: the API appears to hang. See §17.1 for full detail and fix.

---

## 16. N+1 Queries

**Finding 16.1 — Both scheduled background jobs re-run the "which engineers/admins are active" query once per affected row instead of once per job run**
- **Severity:** High
- **Location:** `app/worker/scheduler.py:18-25` (`_notify_engineers`) is called from inside a `for eq in pm_due:` loop (line 44) and a `for eq in cal_due:` loop (line 62) in `check_pm_cal_due()`, and from inside a `for tx in overdue:` loop (line 90) in `check_overdue_returns()`. Each call independently executes `SELECT User.id ... JOIN Role ... WHERE Role.name IN (...) AND is_active`.
- **Root Cause:** The recipient list (active Admins/Biomedical Engineers) doesn't change during a single job run, but it's re-queried for every equipment/transaction row that needs a notification instead of being fetched once before the loop.
- **Business Impact:** This runs unattended in production (`check_pm_cal_due` daily at 06:00, `check_overdue_returns` hourly) — a hospital with several hundred pieces of equipment approaching PM/CAL deadlines would generate hundreds of redundant `SELECT` round-trips per run, purely as background load. Not user-facing, so it degrades DB headroom rather than causing a visible outage, but it's pure waste that scales with equipment count.
- **Technical Impact:** Classic N+1 — O(n) queries where O(1) suffices.
- **Suggested Fix:** Fetch the recipient list once at the top of each job function and pass it into `_notify_engineers` (or inline the notification-creation loop against the pre-fetched list), and batch the resulting `Notification` inserts.
- **Migration Risk:** None.

**Finding 16.2 — No N+1 found in user-facing list/search endpoints (positive finding)**
- **Severity:** N/A (informational)
- `equipment.py`'s list endpoint serializes only scalar columns (§5.3 already confirmed eager-loading discipline on the transaction side) — no lazy-relationship access was found on any hot read path.

---

## 17. Session Lifetime

**Finding 17.1 — CRITICAL: The Server-Sent Events dashboard endpoint holds one database connection open for the entire lifetime of the browser tab, with no upper bound**
- **Severity:** Critical
- **Location:** `app/api/v1/dashboard.py:31-39`:
  ```
  async def stream(db: AsyncSession = Depends(get_db), ...):
      async def event_generator():
          while True:
              data = await dashboard_service.get_summary(db)
              yield f"data: {json.dumps(data)}\n\n"
              await asyncio.sleep(15)
      return StreamingResponse(event_generator(), ...)
  ```
- **Root Cause:** The `db` session is acquired once via the normal per-request `Depends(get_db)` dependency, but then held and reused inside an infinite `while True` loop for the entire duration of the SSE connection — potentially hours, for as long as a browser tab stays open. This is a fundamentally different resource-lifetime pattern than every other endpoint in the codebase (which acquire a session, do one bounded unit of work, and release it), but it uses the exact same acquisition mechanism and the exact same bounded pool.
- **Business Impact:** The connection pool is configured for `pool_size=20, max_overflow=10` — **30 total connections per backend instance**. Every browser tab with the Dashboard page open (a very common real-world pattern in a hospital — e.g., a status board on a wall-mounted monitor in a ward, or staff simply leaving the tab open) permanently pins one of those 30 slots for as long as the tab stays open. Once 30 dashboard tabs are open simultaneously across the hospital, **every other request of any kind — including the core borrow/return workflow — will hang waiting for a connection that will not free up**, because the SSE loops never release theirs. Given the product's own stated target of "100+ concurrent users," this is not a remote edge case; it's a highly plausible way to take the entire application down using entirely normal usage (no attack required).
- **Technical Impact:** SQLAlchemy's async pool checkout will eventually time out (`pool_timeout`, default 30s) and raise, but by then every concurrent request across every endpoint is failing — a full outage, not a degraded state.
- **Suggested Fix:** The SSE endpoint must not hold a single long-lived session. Acquire a fresh, short-lived session for each 15-second poll iteration (open, query, close, immediately release back to the pool) instead of holding one for the connection's lifetime; alternatively, move to the Redis Pub/Sub push design already described in the architecture docs (`01-architecture.md`) instead of the current poll-in-a-loop implementation, which was never actually built despite being documented.
- **Migration Risk:** None — this is a bug fix, not a data change, and should be treated as a pre-launch blocker.

---

## 18. Async Safety

Covered in depth in §13.1 (synchronous CPU-bound work on the event loop). One additional note:

**Finding 18.1 — `requests`/blocking-I/O libraries were not found in any async path (positive finding)**
- **Severity:** N/A (informational)
- No blocking network I/O (e.g., the synchronous `requests` library, or a blocking DB driver) was found inside any `async def` — the SQLAlchemy layer correctly uses `asyncpg`/`aiosqlite`, and Redis usage correctly uses `redis.asyncio`. The async-safety issues in this codebase are exclusively the CPU-bound-on-event-loop class (§13.1), not blocking-I/O-on-event-loop.

---

## 19. Error Responses

Covered in depth in §9 (Exception Handling) and §1.1 — one additional cross-cutting observation:

**Finding 19.1 — Validation errors for malformed UUID path/query parameters produce FastAPI's default 422, which is inconsistent in shape with the app's own `{detail, code, status}` domain-error contract**
- **Severity:** Low
- **Location:** Any endpoint taking a `uuid.UUID`-typed path parameter (e.g., `app/api/v1/equipment.py:86` `equipment_id: uuid.UUID`) — a malformed UUID in the URL produces FastAPI's standard Pydantic-validation 422 response shape, which has neither `code` nor `status` fields.
- **Root Cause:** This is FastAPI's built-in behavior for path/query parameter validation, which sits outside the app's custom `DomainError` handler entirely.
- **Business Impact:** Minor — malformed IDs in URLs are a rare client bug, and the response is still a reasonable 422 with a clear Pydantic error message; flagged only for completeness against the "every error should look the same" contract goal.
- **Suggested Fix:** Optionally add a handler for `RequestValidationError` that reshapes it into the same envelope, purely for consistency; low priority relative to the other findings in this report.
- **Migration Risk:** None.

---

## 20. Logging

**Finding 20.1 — Every Redis interaction in the application silently swallows its own exceptions with no logging at all**
- **Severity:** High
- **Location:** `app/core/redis.py` — `cache_get` (line 25), `cache_set` (line 35), `store_refresh_token` (line 43), `is_refresh_token_valid` (line 52), `revoke_refresh_token` (line 62), `cache_delete_prefix` (line 73) — every single one is `except Exception: pass` (or, for `is_refresh_token_valid`, `except Exception: return True`), with zero calls to `logger.warning`/`logger.error` anywhere in the file.
- **Root Cause:** The cache-aside pattern was implemented with the correct instinct ("a down cache shouldn't break the app"), but the exception handling was written to hide the failure completely rather than degrade gracefully *and* surface the condition to operators.
- **Business Impact:** A sustained Redis outage would be **completely invisible in application logs**. This is most serious for the security-relevant instance already flagged in §10.3 (refresh-token revocation fail-open), but even for the purely-performance instances, an on-call engineer investigating "why did dashboard/search suddenly get slower" has no log signal pointing at Redis as the cause — they'd have to independently think to check Redis's own health directly.
- **Technical Impact:** No metrics, no alerting hook, no diagnostic trail for an entire class of infrastructure dependency failure.
- **Suggested Fix:** Log at `WARNING` on every caught exception in this module, with enough context (operation, key) to be actionable; consider a circuit-breaker or health-check-driven `CACHE_ENABLED` toggle instead of per-call try/except if Redis outages are expected to be more than transient.
- **Migration Risk:** None.

**Finding 20.2 — No request-level structured logging: no request ID, no per-request latency/status logging, no way to correlate a log line to a specific HTTP request or user**
- **Severity:** Medium
- **Location:** `app/core/logging.py:5-11` — bare `logging.basicConfig(...)`, no middleware registered in `app/main.py` beyond `SecurityHeadersMiddleware` (which only adds response headers, doesn't log).
- **Root Cause:** Logging was set up as a minimal baseline and never extended to request-scoped structured logging, despite this being explicitly promised in `docs/08-security.md` ("Structured JSON logs (request id, user id, latency, status)").
- **Business Impact:** Incident investigation ("what did user X do at 14:32") requires cross-referencing the (incomplete — see §12) audit log with application logs that have no shared correlation ID, making reconstruction slow and error-prone exactly when it matters most.
- **Suggested Fix:** Add request-scoped logging middleware that generates/propagates a request ID, logs method/path/status/latency/user ID (where available) per request, and switches to structured (JSON) log output as documented.
- **Migration Risk:** None.

---

## Business Workflow Consistency — Named Scenarios

| Scenario | Verdict | Evidence |
|---|---|---|
| **Borrow succeeds but Audit fails** | **Not reproducible as stated.** | `borrow()` performs the transaction insert, equipment status change, and audit log write inside one session, committed exactly once at `app/services/borrow_service.py:96`. If the audit insert itself fails (e.g., a bug or constraint violation), the whole operation rolls back atomically — there is no partial-success path. This hypothesis was checked and disproven for the current code. |
| **Return succeeds twice** | **Confirmed, reproducible bug.** | See Finding 14.1 (Critical) — no DB-level guard exists on the return path, unlike the borrow path. |
| **Equipment status mismatches transaction status** | **Confirmed, but via a different mechanism than a simple mismatch: return becomes permanently blocked, not merely "mismatched."** | See Finding 14.2 (Critical). On the happy path, equipment/transaction status are kept consistent atomically within one commit. The actual defect is that the scheduler's `overdue` transition breaks the return-eligibility check entirely. |
| **Transaction rollback scenarios** | **Generally safe on the paths exercised, with one clarity gap.** | See Finding 6.1 / 7.1 — rollback-on-exception is correctly handled via the implicit `session.close()` behavior in `get_db()`, but this safety net is undocumented and inconsistently reinforced (only one manual rollback exists in the whole codebase), which is a maintainability risk rather than a currently-observable bug. |
| **Duplicate transaction creation** | **Partially confirmed, distinct from a simple duplicate-submit.** | Accidental double-submission of the *same* borrow request is well-protected by the equipment-status check itself (naturally idempotent for repeat attempts on the same equipment). However, Finding 14.3 (High) shows a genuine duplicate/collision risk on `transaction_no` generation across *different* concurrent borrows, which is misreported as an equipment-availability error. Separately, the documented `Idempotency-Key` header (`docs/03-api-specification.md`, intended for the offline-first PWA's retry-after-reconnect flow) was **not found implemented anywhere** in `app/api/v1/borrow.py` — a real gap against the stated offline architecture, Medium severity, not covered elsewhere in this report. |

**Additional workflow-consistency finding not in the user's example list:**

**Finding W.1 — `quantity` is unvalidated end-to-end (API layer and DB layer both accept zero/negative values)**
- **Severity:** Medium
- **Location:** `app/schemas/transaction.py:17` (`quantity: int = 1`, no `gt=0` constraint) and no `CHECK` constraint at the DB layer (confirmed in the prior schema review).
- **Business Impact:** A borrow request with `quantity: 0` or a negative value would be accepted end-to-end and persisted, silently corrupting any future utilization/quantity-based reporting.
- **Suggested Fix:** Add `Field(gt=0)` at the Pydantic layer (cheapest, closest-to-source fix).
- **Migration Risk:** None.

---

## Severity Summary

| # | Finding | Severity | Section |
|---|---|---|---|
| 1 | Return can be processed twice concurrently — no DB guard on the return path | **Critical** | 14.1 |
| 2 | Return becomes permanently blocked once a transaction is marked `overdue` | **Critical** | 14.2 |
| 3 | `/dashboard/stream` holds one DB connection per open tab indefinitely — pool exhaustion can hang the entire API | **Critical** | 17.1, 15.2, 8.1 |
| 4 | Insecure default `JWT_SECRET_KEY` with no production guard — full auth bypass if unset | **Critical** | 10.1 |
| 5 | Zero audit trail for user/role management (account creation, role escalation, password resets) | **Critical** | 12.1 |
| 6 | `IntegrityError` / bare `ValueError` unhandled across multiple create/return endpoints → raw 500s | High | 9.1 |
| 7 | No optimistic locking anywhere; root enabler of Finding 1 | High | 5.1 |
| 8 | Exact `COUNT(*)` on every paginated search request | High | 5.2 |
| 9 | Synchronous bcrypt/openpyxl/qrcode block the event loop | High | 13.1 |
| 10 | N+1 recipient-lookup query in both scheduled jobs | High | 16.1 |
| 11 | No audit trail for auth events and master-data mutations | High | 12.2 |
| 12 | No login rate limiting despite being documented | High | 10.2 |
| 13 | Refresh-token revocation fails open silently on Redis outage | High | 10.3 |
| 14 | `generate_transaction_no()` race → misattributed errors, blocked legitimate borrows | High | 14.3 |
| 15 | All Redis errors silently swallowed with zero logging | High | 20.1 |
| 16 | Inconsistent error envelope (`HTTPException` vs `DomainError`) | High | 1.1 |
| 17 | Authorization re-queries DB every request instead of trusting JWT claim | Medium | 2.1 |
| 18 | PATCH cannot clear fields to `null` | Medium | 4.1 |
| 19 | Commit-boundary discipline relies on per-author convention, not structural enforcement | Medium | 6.1 |
| 20 | Rollback safety net is implicit/undocumented and applied inconsistently | Medium | 7.1 |
| 21 | Automated scheduler transitions bypass the audit trail | Medium | 12.3 |
| 22 | No request-level structured/correlated logging | Medium | 20.2 |
| 23 | Row-level authorization inconsistently modeled (silent no-op pattern) | Medium | 11.1 |
| 24 | `quantity` unvalidated at both API and DB layers | Medium | W.1 |
| 25 | Documented `Idempotency-Key` header not implemented | Medium | Business Workflow table |
| 26 | Minor: dead `request.state.current_user`, local import style, 422 shape inconsistency | Low | 2.2, 1.2, 19.1 |

**Positive findings worth preserving as-is:** the borrow-side double-booking guard (partial unique index), `selectinload()` discipline on transaction reads, and the absence of any classic multi-row deadlock pattern.

No code was modified as part of this review, per your instructions.
