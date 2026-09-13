# PR14A Transaction Boundary Audit

Roadmap PR14A (Backend Audit 6.1 / 7.1). This document is the required
deliverable for PR14A's "Transaction Boundary Audit" scope item: an
inspection of every `await db.commit()` call site in the backend, and a
statement of what that inspection did and did not find.

## Conclusion

> All current transaction boundaries were inspected.
> No atomicity drift was identified.
> PR14A intentionally leaves the existing caller-owned commit architecture unchanged.
> Structural transaction-management changes remain deferred and would require a separate architecture review.

This is a point-in-time statement about the inventory below. It is not a
claim that the current architecture is the permanently accepted design,
and it does not preclude a future, separately-reviewed change to how
commits are managed.

## `get_db()` contract

`app/db/session.py::get_db()` guarantees exactly one thing: closing an
uncommitted session rolls back its transaction. It does not commit on a
clean exit, does not retry or otherwise recover from a failure, and is not
a substitute for an explicit `db.rollback()` after a caught database
error. Every commit boundary below is owned by the caller that decided
the unit of work succeeded, not by the dependency that handed out the
session.

## Commit-site inventory

Every `await db.commit()` (and the one best-effort-commit call path) in
`app/api`, `app/services`, `app/worker`, and `app/scripts`, grouped by the
kind of unit of work each one closes.

### Ordinary request/business commits

One commit per successful request, closing a single caller-owned
transaction that may include a business mutation and its audit row
together (see `app/core/audit.py::record_audit_event` — flush-only, so a
later failure in the same transaction rolls the audit row back with it).

| Site | Function |
| --- | --- |
| `app/api/v1/users.py:57` | `create_user` |
| `app/api/v1/users.py:98` | `update_user` |
| `app/api/v1/equipment.py:235` | `create_equipment` |
| `app/api/v1/equipment.py:286` | `update_equipment` |
| `app/api/v1/equipment.py:338` | `change_equipment_status` |
| `app/api/v1/equipment.py:365` | `delete_equipment` |
| `app/api/v1/master_data.py:57` | `create_department` |
| `app/api/v1/master_data.py:86` | `create_ward` |
| `app/api/v1/master_data.py:116` | `create_location` |
| `app/api/v1/master_data.py:148` | `create_category` |
| `app/api/v1/notifications.py:45` | `mark_read` |
| `app/services/import_service.py:821` | `_commit_rows` |
| `app/services/borrow_service.py:147` | `borrow` |
| `app/services/borrow_service.py:254` | `return_equipment` |
| `app/services/borrow_service.py:343` | `correct_ward` |

No atomicity drift found: each site commits after all of that request's
mutations (and its audit row, where one applies) have been staged, and
`translate_integrity_error` rolls back before translating a database
error into a domain exception — no site can leave a half-applied mutation
committed.

### Scheduler commit

| Site | Function |
| --- | --- |
| `app/worker/scheduler.py` (`await db.commit()` inside `check_pm_cal_due`) | `check_pm_cal_due` |

A single commit per scheduled run, in its own session (`AsyncSessionLocal()`
directly, not the request-scoped `get_db()`). Roadmap PR14A's N+1 fix
(recipient list loaded at most once per run) changed what is queried
before this commit, not the commit boundary itself — still exactly one
commit per run, closing every `Notification` row staged for that run
together.

### Authentication-specific best-effort commit

| Site | Function |
| --- | --- |
| `app/core/audit.py::commit_best_effort` | shared by all four call sites below |
| `app/services/auth_service.py:54` | login (failure path, before raising `InvalidCredentialsError`) |
| `app/services/auth_service.py:83` | login (success path) |
| `app/services/auth_service.py:140` | refresh |
| `app/services/auth_service.py:165` | logout |

Deliberately not an ordinary commit: `commit_best_effort` (paired with
`record_best_effort_audit_event`, which wraps its write in a `SAVEPOINT`)
catches and logs a commit failure instead of propagating it, so a
transient audit-subsystem problem can never turn a legitimate
authentication outcome into an unrelated 500. See that function's
docstring for the full rationale. This is an intentional deviation from
the ordinary-commit pattern above: authentication's commit protects a
different, narrower set of pending changes, and unlike the ordinary-commit
sites it must not fail the request just because that protection layer
(the audit write or the commit itself) had a transient problem.

**The success-path commit is not audit-only.** On a successful login
(`authenticate()`, `app/services/auth_service.py:62`), `user.last_login_at`
is set to the current time *before* the audit event is recorded and before
`commit_best_effort` runs at line 83 — so that commit closes both the
`last_login_at` update on the `User` row and the `login_success` audit row
together, as one unit. If the commit fails, `commit_best_effort` logs the
failure and rolls back, so neither `last_login_at` nor the audit row
persists for that login — but the failure is still swallowed and the
already-decided authentication outcome (a valid access/refresh token pair)
is still returned to the caller. This is the intentional, documented
trade-off of the best-effort boundary: an authenticated session can be
issued without its `last_login_at`/audit bookkeeping having landed, in
exchange for guaranteeing that a transient persistence problem in that
bookkeeping can never turn a legitimate login into a 500. Token issuance
itself never depends on this commit succeeding (see the comments in
`authenticate()`). This is a real, intentional difference from the
ordinary-commit sites above, where a failed commit does propagate and the
request does fail — not an oversight to be reconciled with them.

### Seed/script commits

| Site | Function |
| --- | --- |
| `app/scripts/seed.py:166` | `seed_reference_data`/main seeding entry point |

A one-shot operator-run script (`python -m app.scripts.seed`), not a
request or background-job code path. Its commit closes the full seed
batch in one transaction; it is not reachable from the running
application and is out of scope for request-level atomicity concerns.

## What this audit did not do

Per PR14A's scope, this audit inspected and documented the existing
commit boundaries; it did not change how or where any of them commit, did
not introduce centralized commit-on-clean-exit in `get_db()`, and did not
add a `db.rollback()` anywhere the code does not already have one. Any of
those would be a structural transaction-management change and, per the
conclusion above, requires a separate, dedicated architecture review.
