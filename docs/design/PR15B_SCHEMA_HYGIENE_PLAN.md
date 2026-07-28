# Roadmap PR15B — Schema Hygiene: Architecture / Design Proposal

**Status:** Design only, uncommitted (same convention as `PR8_IMPLEMENTATION_PLAN.md` and `PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md`) — not part of any PR diff, no repository files modified to produce this document.
**Project baseline investigated:** `fa570da4377c4a4f67b8e65f21d0d35ea050f50f` (PR15A merged as GitHub PR #50; governance sync merged as GitHub PR #51).
**Predecessor document:** `docs/design/PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md` (Revision 2) already produced a complete Roadmap PR15 disposition matrix and a full timezone policy, approved for PR15A. This document is the PR15B-specific continuation: it re-verifies every schema claim from that document against the current baseline (no schema drift since PR15A, which was observability-only — confirmed below) and adds the additional detail this round's request requires (exact FK/CHECK/index inventories, an explicit FK-by-FK policy table, a concrete index-rename plan, and a migration-numbering/testing plan).
**No code was written, no migration was generated, and no repository file was modified to produce this document.** Every schema claim below was verified by rehearsing Alembic `base → head` (migrations `0001` through `0011`) against a fresh, disposable PostgreSQL 16 scratch database (`mep_schema_hygiene_scratch`, created and dropped solely for this investigation — not the persistent `mep_test_db`, which risks stale-migration-stamp false readings, per the same methodology note `PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md` §2.0 established) and inspecting `information_schema.columns`, `pg_constraint`, and `pg_indexes` directly, not assumed from model source alone.

---

## 1. Executive Summary

Roadmap PR15B is the schema-hygiene slice of the PR15 Epic (PR15A, observability, is merged and complete — GitHub PR #50). This proposal covers exactly the six areas the architecture review named: timezone correctness, schema consistency, FK deletion policy, CHECK constraints, index-naming convergence, and migration safety — and nothing else. No business workflow changes, no API contract changes, no metrics/tracing/dashboards/logging work (that is PR15A's completed scope or explicitly out-of-scope future work per the approved PR15A design).

Headline findings, freshly re-verified against a live `base → head` rehearsal (§2–§6 below have the full detail and exact counts):

- **Six timestamp columns are naive** (`timestamp without time zone`) across four tables, while the codebase's own established `TimestampMixin` pattern already proves the correct approach (`DateTime(timezone=True)` + `server_default=func.now()`). This is not cosmetic: two of the affected columns (`borrow_transactions.borrowed_at`, `.returned_at`) plus the already-aware-but-naive-write `EquipmentStatusHistory.changed_at` are parsed with `new Date(...)` and displayed to users in `EquipmentDetailPage.tsx`/`ReturnPage.tsx` — today, because the wire value carries no UTC offset, the browser's `Date` parser interprets it as **local time**, not UTC, which is a latent, currently-unverified display-correctness bug this migration would fix as a side effect, not introduce.
- **A second, related bug beyond the original PR15A-round timezone table**: `Equipment.deleted_at` is already declared `DateTime(timezone=True)` (via `SoftDeleteMixin`), but `app/crud/equipment.py::soft_delete()` writes `datetime.utcnow()` (naive) into it — the identical bug pattern already identified for `User.last_login_at`, just not previously listed. No column-type migration needed for this one; it is a Python-only fix.
- **All 25 foreign keys** use PostgreSQL's implicit `NO ACTION` today. Zero hard-delete code paths exist anywhere in the running application (confirmed: the only `DELETE` endpoint, `DELETE /equipment/{id}`, performs a soft delete). Making `RESTRICT` explicit on every FK is therefore genuinely zero-behavior-change for 25 of 25 relationships; three relationships (`equipment.category_id`/`department_owner_id`/`current_location_id`) are flagged as an open question for `SET NULL`, not implemented without Owner sign-off.
- **9 CHECK constraints already exist** (added across PR6, PR7, PR7b, PR10, PR14-H3R) — the original Schema Audit finding ("no CHECK constraints anywhere") is stale. This proposal identifies zero new mandatory CHECK constraints; it documents the existing 9 and explains why no further sweep is justified.
- **Index naming has three inconsistent groups, not two**: 29 `ix_`-prefixed (SQLAlchemy default), 5 `idx_`-prefixed (4 GIN trigram indexes + 1 partial unique index, both hand-named), and **7 auto-named `<table>_<column>_key` unique constraints** that PostgreSQL itself named because the owning `unique=True` columns have no `index=True` and no explicit `UniqueConstraint(name=...)` — a naming inconsistency the predecessor design document did not enumerate. All three groups converge onto `ix_`/`uq_` via metadata-only renames (`ALTER INDEX`/`ALTER TABLE ... RENAME CONSTRAINT`), zero rebuild.
- **`PMSchedule`/`CalibrationSchedule` remain dead code** (zero references outside their own model definitions, reconfirmed) — **not proposed for removal**, per explicit instruction.
- **A third new finding, closing a review-preparation gap**: none of the 25 ORM `ForeignKey()` declarations specify `ondelete=`, and the SQLite test suite bootstraps its schema directly from ORM metadata (`tests/conftest.py:28`, bypassing Alembic) — so the FK migration must be paired with 25 ORM model updates in the same change, or ORM metadata, SQLite tests, and the PostgreSQL catalog silently diverge. See §4's cross-check and §10a.
- Migration numbering: current head is `0011_pagination_ordering_indexes`; PR15B is now recommended as **three separate migrations** beginning at `0012` (`0012_timezone_conversion.py`, `0013_fk_ondelete_policy.py`, `0014_index_naming_convergence.py` — see §8.2), superseding the prior round's single-combined-migration default.

This document proposes **no implementation**. It is a request for architecture approval on: (1) the timezone conversion and its testing plan, (2) a uniform `RESTRICT` default for all FKs with three named exceptions requiring an explicit Owner decision, (3) a rename-only index-naming convergence plan covering all three inconsistent groups, and (4) confirmation that no further CHECK-constraint sweep or `PMSchedule`/`CalibrationSchedule` removal is in scope.

---

## 2. Roadmap Coverage Matrix

| Item | Disposition | Evidence |
|---|---|---|
| **Timezone handling** | **Included in PR15B** | See §3. Six naive columns confirmed via live rehearsal; conversion policy, expression, and testing plan specified below. |
| **FK `ondelete` policies** | **Included in PR15B**, scoped as an explicit-behavior pass | See §4. All 25 FKs currently `NO ACTION` (verified `pg_constraint.confdeltype`); default to `RESTRICT` everywhere (zero de facto behavior change); 3 relationships flagged as an open `SET NULL` question requiring Owner approval, not implemented speculatively. |
| **`users` soft-delete** | **Deferred — no corresponding workflow exists to protect** | Reconfirmed: `users` has no `deleted_at` column and `app/api/v1/users.py` has no `@router.delete` route of any kind — the only account-lifecycle mechanism is `is_active` deactivation. Adding a `deleted_at` column with nothing to write it is schema growth without a use case. Recommend deferring until a user-deletion/account-lifecycle workflow is confirmed on the Roadmap; if/when it is, the column ships with that workflow, not ahead of it. |
| **CHECK constraints** | **Already substantially complete; no new constraint proposed in PR15B** | See §5. 9 CHECK constraints already exist (`ck_roles_name_confirmed`, `ck_equipment_bcm_code_canonical`, `ck_equipment_item_no_canonical`, `ck_equipment_status_four_state`, `ck_borrow_transactions_dispatch_type`, `ck_borrow_transactions_routine_round`, `ck_borrow_transactions_routine_round_consistency`, `ck_borrow_transactions_status_open_closed`, `ck_confirmed_role_ownership_flags`), confirmed via `pg_constraint`. No candidate for a new constraint was identified that isn't already covered — see §5 for the specific columns considered and rejected. |
| **Index naming convergence** | **Included in PR15B, rename-only** | See §6. Three inconsistent naming groups confirmed via `pg_indexes` (29 `ix_`, 5 `idx_`, 7 auto-named `_key`). Convergence plan below is 100% `ALTER INDEX`/`ALTER TABLE ... RENAME CONSTRAINT`, zero index rebuild, zero query-plan change. |
| **Migration hygiene / general schema hygiene** | **Included in PR15B** | Umbrella term covering §3–§7: validate-before-enforce discipline (§8), the `Notification.type` stale-comment fix, and the `docs/TECH_DEBT.md` TD-001 status correction (both documentation/comment-only, bundled since they touch files this PR already touches — not because they need a migration). |
| **`PMSchedule`/`CalibrationSchedule`** | **Deferred — not proposed for removal** | See §7. Reconfirmed zero references outside `app/models/equipment.py`'s own class definitions. |
| **FK index additions** | **Out of scope, evidence-gated** | Carried over from the PR15A-round design and reconfirmed: no `EXPLAIN ANALYZE` evidence of a real query-plan problem exists for any unindexed FK column. Per the PR14B precedent (index work must be evidence-gated, not a blanket pass), this is not proposed here at all. |
| **Metrics, tracing, alerting, log aggregation, operational dashboards** | **Not scheduled to PR15A or PR15B — remain open Roadmap PR15 scope** | Already dispositioned by the approved PR15A design and by `docs/ROADMAP.md`'s PR15 note (GitHub PR #50/#51). Not re-litigated here; out of scope for this document per the explicit "Out of Scope" instruction. |
| **Structured/correlated logging, request correlation, background-job run IDs, aggregate import logging** | **Already completed by PR15A** | GitHub PR #50, merged. Not PR15B scope. |

---

## 3. Timezone Policy

### 3.1 Python

**Policy: use `datetime.now(timezone.utc)` everywhere a Python-side UTC "now" value is needed.** `datetime.utcnow()` returns a **naive** datetime that silently claims no timezone while implicitly meaning UTC — a footgun the instant it is compared against, or stored alongside, a timezone-*aware* value (which is exactly the mixed state this codebase is in today, per §3.3). `datetime.now(timezone.utc)` returns the identical instant, explicitly labeled, and is safe to compare/store/serialize alongside any other aware value without ambiguity. This is why Python's own documentation now recommends against `utcnow()`/`utcfromtimestamp()`.

### 3.2 Database — authoritative source per timestamp column

Every timestamp column is classified below as **database-authoritative** (PostgreSQL computes the value at write time via `server_default=func.now()`/`onupdate=func.now()`) or **application-authoritative** (the value is meaningful business state Python must decide, which the database cannot know on its own). This reproduces and re-verifies the classification from `PR15_OBSERVABILITY_SCHEMA_HYGIENE_PLAN.md` §2, plus one column that document did not cover (`Equipment.deleted_at`):

| Column | Classification | Justification |
|---|---|---|
| `equipment.created_at`/`updated_at`, `borrow_transactions.created_at`/`updated_at`, `users.created_at`/`updated_at` | **Database-authoritative — already correct** | Already `DateTime(timezone=True)` + `server_default=func.now()`/`onupdate=func.now()` via `TimestampMixin`. No change needed. |
| `audit_logs.created_at` | **Database-authoritative, currently implemented as Python-side default (inconsistent with `TimestampMixin`)** | An audit row's timestamp must be the moment PostgreSQL actually committed it, not a Python-computed value that could predate a slow transaction's real commit. Currently `mapped_column(default=datetime.utcnow, nullable=False)` — a *different* mechanism than `TimestampMixin` uses for the conceptually identical job. See §3.5 for the two remediation options and the recommendation. |
| `notifications.created_at` | **Database-authoritative, same inconsistency as `audit_logs.created_at`** | No reason for this to differ from `TimestampMixin`'s pattern; currently the same bespoke `default=datetime.utcnow`. |
| `equipment_status_history.changed_at` | **Database-authoritative, same inconsistency** | The history row's timestamp should reflect when the row was actually written, consistent with every other `*_history` pattern in this codebase. Currently `default=datetime.utcnow`. |
| `borrow_transactions.borrowed_at` | **Database-authoritative, same inconsistency** | This is the dispatch transaction's creation moment in every current call site (`app/services/borrow_service.py` sets it at transaction-creation time) — functionally a creation timestamp. Currently `default=datetime.utcnow`. |
| `borrow_transactions.returned_at` | **Application-authoritative — must use `datetime.now(timezone.utc)`** | Set in `app/crud/transaction.py::close()` inside the same conditional-`UPDATE` receipt-race transaction (Roadmap PR8A) that also decides the receipt outcome — the value is coupled to that business decision, not purely "when did this row get written." Converting to `server_default`/`onupdate` would be a larger behavioral change than a hygiene pass should make; this column stays Python-authoritative, just fixed to be timezone-aware. Currently `datetime.utcnow()` at `app/crud/transaction.py:198`. |
| `borrow_transactions.due_at` | **Historical, read-only — no live write path** | Reconfirmed via full-repository grep: only ever *read* (`app/services/report_service.py`), never written by any current code path — the due-date workflow was removed in Roadmap PR7a; this column is preserved history only. Type correction still applies for consistency; no write-path behavior to change. |
| `users.last_login_at` | **Application-authoritative, must use `datetime.now(timezone.utc)`** | Already `DateTime(timezone=True)` (column type is correct) — the bug is purely in the Python value written at `app/services/auth_service.py:62` (`user.last_login_at = datetime.utcnow()`, naive). No migration needed for this column; Python-only fix. |
| **`equipment.deleted_at` (new finding, not in the PR15A-round document)** | **Application-authoritative, must use `datetime.now(timezone.utc)`** | Same bug pattern as `users.last_login_at`: already `DateTime(timezone=True)` via `SoftDeleteMixin`, but `app/crud/equipment.py::soft_delete()` writes `equipment.deleted_at = datetime.utcnow()` (naive) at line 260. No migration needed; Python-only fix. |
| `app/crud/transaction.py:71` — `datetime.utcnow().strftime("%Y%m%d")` | **Reviewed, not a timestamp-column writer — no fix required** | Formats the current UTC date into the human-readable `transaction_no` business identifier string (not a datetime value stored in any timestamp column). Confirmed via full-repository grep for `datetime.utcnow()` (four total call sites; the other three are listed above) that this is the complete set — no additional naive-datetime writer exists anywhere in `backend/app`. Included here explicitly so the cross-check "all known naive datetime writers identified" is verifiable against a documented, exhaustive list rather than an implicit one. |

### 3.3 PostgreSQL — actual current column types (inspected against a live rehearsal, not assumed)

Rehearsed `base → head` (migrations `0001`–`0011`) against a fresh scratch database and inspected `information_schema.columns` directly:

**Already `timestamp with time zone` (aware) — no column-type migration needed:**
`equipment.created_at`, `.updated_at`, `.deleted_at`; `borrow_transactions.created_at`, `.updated_at`; `users.created_at`, `.updated_at`, `.last_login_at`; plus the PR10 role-consolidation provenance tables (`confirmed_role_ownership.snapshot_at`, `role_migration_snapshots.snapshot_at`, `user_role_migrations.migrated_at`), which were already built correctly.

**Currently `timestamp without time zone` (naive) — migration candidates, identical set to the PR15A-round document, reconfirmed with zero drift (PR15A made no schema changes):**
- `audit_logs.created_at`
- `notifications.created_at`
- `equipment_status_history.changed_at`
- `borrow_transactions.borrowed_at`
- `borrow_transactions.due_at` (read-only history, per §3.2 above)
- `borrow_transactions.returned_at`

No new naive column was found beyond this set of six; the schema has not drifted since the PR15A-round investigation, which is expected since PR15A shipped zero schema changes (confirmed: `feature/pr15a-observability`'s diff touched only `backend/app/core/`, `backend/app/main.py`, `backend/app/worker/scheduler.py`, `backend/app/services/import_service.py`, and its own test file — no `alembic/versions/` entry).

### 3.4 Conversion expression and historical-data interpretation

If PR15B proceeds with converting the six naive columns above to `timestamptz`, the interpretation of **existing stored values** is stated explicitly: every naive value in every one of these six columns today was written by `datetime.utcnow()` (confirmed: no other write path exists for any of them — see §3.2's call-site citations), which — despite being naive — always represents a UTC instant; the bug is the missing timezone label, not incorrect wall-clock math. The correct, meaning-preserving conversion is therefore:

```sql
ALTER TABLE audit_logs
  ALTER COLUMN created_at TYPE timestamptz
  USING created_at AT TIME ZONE 'UTC';
```

repeated per column/table. `AT TIME ZONE 'UTC'` means "interpret this naive value as having been UTC all along," accurate for every existing row. This is explicitly **not** the same as `created_at::timestamptz` (a bare cast), which interprets the naive value using the database session's *current* timezone setting — silently wrong unless that session happens to already be UTC. This distinction must appear verbatim in the migration's own comments, not just this design document, to prevent a future maintainer from "simplifying" the expression into a bare cast.

**Downgrade expression (the exact inverse, stated explicitly per the cross-check requirement):**

```sql
ALTER TABLE audit_logs
  ALTER COLUMN created_at TYPE timestamp
  USING created_at AT TIME ZONE 'UTC';
```

repeated per column/table. Applied to an already-`timestamptz` value, `AT TIME ZONE 'UTC'` converts it to a naive value representing the same instant expressed in UTC wall-clock terms — the exact inverse of the upgrade expression, and lossless for the stored instant (see §3.6 for the forward-compatibility caveat this reversal does *not* eliminate).

### 3.5 The `TimestampMixin`-inconsistency question (new in this round)

Four of the six naive columns (`audit_logs.created_at`, `notifications.created_at`, `equipment_status_history.changed_at`, `borrow_transactions.borrowed_at`) are all conceptually "row creation timestamp" columns — the exact same job `TimestampMixin.created_at` already does correctly (`DateTime(timezone=True)` + `server_default=func.now()`). Today these four instead use a bespoke `mapped_column(default=datetime.utcnow, nullable=False)` definition, meaning the codebase currently has **two different mechanisms** computing the same conceptual value. Two remediation options, presented for architecture approval rather than decided unilaterally:

- **Option A (recommended, lower risk): fix the type only.** Convert the column type to `timestamptz` (§3.4) and change the Python-side default callable from `datetime.utcnow` to `lambda: datetime.now(timezone.utc)` — the column becomes correctly aware, the value becomes correctly labeled, but the *computation mechanism* (Python decides the value, before `INSERT`) is unchanged. This is the narrowest possible fix: one column-type ALTER, one one-line callable change per column, no change to who computes the value or when.
- **Option B (further consistency, not recommended for this pass without explicit sign-off): converge onto `TimestampMixin`'s pattern.** Replace the bespoke `default=datetime.utcnow` with `server_default=func.now()`, matching `TimestampMixin` exactly, eliminating the two-mechanism inconsistency entirely. This is a genuine (if narrow) behavior change: the value is now computed by PostgreSQL at `INSERT` time rather than by Python immediately before it, which is marginally more correct (immune to any application-clock skew) but is a different code path than what these four columns have used since they were introduced, and would need its own regression coverage proving no observable ordering/`after`-payload/test-fixture regression across `audit_logs`, `notifications`, `equipment_status_history`, and `borrow_transactions.borrowed_at` consumers.

**This document recommends Option A for PR15B** and lists Option B as an open question (§9.2) rather than assuming it — consistent with the instruction to avoid introducing unapproved behavior changes and to keep this pass minimal-risk.

### 3.6 Rollback limitations

Downgrading `timestamptz` back to `timestamp` (`... USING created_at AT TIME ZONE 'UTC'`, the inverse expression) is lossless for the *value* (the same UTC instant, re-stripped of its label) but is **not** risk-free going forward: any code deployed against the timestamptz schema that started relying on timezone-aware comparison semantics would silently regress to naive-comparison behavior after a downgrade. This must be stated explicitly in the migration's downgrade docstring (matching the established pattern in migration `0004`'s downgrade docstring on destructive-vs-non-destructive framing), not presented as a risk-free revert.

### 3.7 Required testing

Per the explicit instruction, this is not treated as a mechanical replacement:

1. **Fresh database** — `base → head → 0012` produces the target `timestamptz` schema with no intermediate naive state ever materializing.
2. **Historical upgrade** — rehearse against a database seeded with rows at the pre-`0012` baseline containing real historical values (not empty tables), proving the `AT TIME ZONE 'UTC'` conversion preserves the exact instant for pre-existing data.
3. **Downgrade** — prove the reverse conversion is lossless for the stored instant, and that the downgrade docstring's caveat (§3.6) is accurate.
4. **Re-upgrade** — the same round-trip discipline every migration since `0004` has followed.
5. **SQLite parity** — the non-PostgreSQL test suite (`Base.metadata.create_all()`) does not enforce `timestamptz` the way PostgreSQL does; confirm the ORM-level `DateTime(timezone=True)` type still round-trips correctly through SQLite's storage (SQLAlchemy's SQLite dialect stores aware datetimes as ISO strings and can lose `tzinfo` on read-back unless handled carefully), so the two dialects' test suites don't silently diverge in what they actually verify.
6. **PostgreSQL parity** — the equivalent PostgreSQL-marked assertions confirming the column is genuinely `timestamptz` at the catalog level (`information_schema.columns.data_type`), not just "the ORM object has tzinfo," which SQLite could satisfy without the underlying column enforcing anything.
7. **Serialization** — confirm FastAPI/Pydantic response serialization of the now-aware datetimes produces the shape frontend code actually consumes. This is a concrete, user-visible finding from this round's investigation, not a theoretical concern: `frontend/src/pages/EquipmentDetailPage.tsx` and `ReturnPage.tsx` call `new Date(tx.borrowed_at)`, `new Date(tx.returned_at)`, and `new Date(h.changed_at)` directly on the API response strings and render them via `.toLocaleString("th-TH")`. Today, because these values serialize with **no UTC offset** (naive), the browser's `Date` parser interprets them as **local time**, not UTC — a latent, currently-unverified display-correctness bug. After conversion, the same values serialize *with* an explicit `+00:00` offset, which `new Date(...)` parses correctly as UTC before `.toLocaleString()` converts it to the browser's local display timezone. This is a **user-visible improvement**, not a neutral wire-format detail — displayed dispatch/receipt/status-change times will shift by the local UTC offset amount (correcting them), and this must be verified explicitly against the frontend before merge, not assumed compatible.

**This policy explicitly rejects treating the timezone migration as a mechanical `datetime.utcnow()` → `datetime.now(timezone.utc)` find-and-replace.** The column-type change, the conversion-expression correctness, the `TimestampMixin`-consistency question (§3.5), and the serialization/display-correctness impact (§3.7.7) are all first-class design concerns addressed before any implementation.

---

## 4. FK Policy

**Default policy: `RESTRICT` for every FK, unless a specific relationship's business workflow explicitly requires otherwise — and no such requirement has been approved for any relationship today.**

Verified via a live rehearsal: all 25 foreign keys currently use PostgreSQL's implicit `NO ACTION` (`pg_constraint.confdeltype = 'a'`). `NO ACTION` and `RESTRICT` are functionally identical for every FK in this schema today, because none of them is declared `DEFERRABLE` — the only difference between the two (deferring the check to end-of-transaction vs. checking immediately) only matters for deferrable constraints. Making `RESTRICT` explicit is therefore a documentation/intent clarification with **zero observable behavior change**, confirmed further by the fact that the running application has exactly one `DELETE` endpoint in its entire API (`DELETE /equipment/{id}`), and it performs a **soft** delete (`equipment_crud.soft_delete`, setting `deleted_at`) — it never issues a real SQL `DELETE`, so no FK's `ondelete` behavior is ever actually exercised by any code path today.

**Why `SET NULL` is not adopted by default for the three nullable columns under review (`equipment.category_id`/`.department_owner_id`/`.current_location_id`):** `SET NULL` is only a safe default when something in the business workflow actually depends on the reference silently clearing itself when the referenced row disappears — no such workflow exists here today. There is no confirmed deletion workflow for `equipment_categories`, `departments`, or `locations` at all (no `DELETE` route exists for any of the three), so proposing `SET NULL` now would be speculative schema design against a use case that has not been approved, not a response to an actual business rule. `RESTRICT` is the conservative choice precisely because it fails loudly (blocks the delete) rather than silently corrupting equipment records with an unexplained `NULL` the moment such a delete route is ever added — an operator would then have to trace *why* a piece of equipment lost its category/department/location after the fact. If a deletion workflow for master-data rows is ever approved, `SET NULL` can be adopted deliberately at that time, scoped to that workflow's actual requirements, rather than pre-emptively.

**Cross-check: ORM `ForeignKey(ondelete=...)` alignment (new finding, required by this round's review preparation).** Confirmed via `grep -rn "ForeignKey(" backend/app/models/*.py`: **none of the 25 `ForeignKey()` declarations in the ORM models currently specify an `ondelete=` parameter.** This matters beyond documentation-only concerns because migration `0001_initial.py` bootstraps its entire schema via `Base.metadata.create_all(bind=bind)` (confirmed at `alembic/versions/0001_initial.py:26`) — meaning the ORM model *is* the DDL source of truth for how FKs get created, not just a description of them. More critically, `backend/tests/conftest.py:28` (`await conn.run_sync(Base.metadata.create_all)`) builds the SQLite test database directly from ORM metadata, **bypassing Alembic migrations entirely**. If migration `0012`/`0013` adds `ON DELETE RESTRICT` to the PostgreSQL catalog via raw `ALTER TABLE ... DROP CONSTRAINT ... ADD CONSTRAINT ...` SQL without also updating the ORM `ForeignKey()` declarations to `ondelete="RESTRICT"`, two problems follow: (1) the SQLite test suite would continue running against FKs with no explicit `ondelete` semantics, silently diverging from what PostgreSQL actually enforces after the migration — the exact "current ORM metadata will produce the same schema as upgraded databases" cross-check this document is required to verify, and today it does **not**, absent this fix; (2) a future `alembic revision --autogenerate` would detect a spurious diff (ORM says `NO ACTION`, database says `RESTRICT`) and attempt to "fix" it by reverting the database back to `NO ACTION`, silently undoing this migration's intent. **Required fix, folded into the FK migration itself (not a separate step):** every one of the 25 `ForeignKey("...")` declarations in `app/models/*.py` must be updated in the same change to `ForeignKey("...", ondelete="RESTRICT")` (or `"SET NULL"` for whichever of the three §9.1 columns the Owner approves), so ORM metadata, SQLite test schema, and the PostgreSQL catalog all converge on an identical, explicit policy. This is a model-source-code change accompanying the migration, not a database-only change — flagged explicitly here since the original round of this document did not call it out.

| # | FK constraint | Table.column | References | Nullable | Current | Proposed | Business justification |
|---|---|---|---|---|---|---|---|
| 1 | `equipment_category_id_fkey` | `equipment.category_id` | `equipment_categories.id` | Yes | NO ACTION | **RESTRICT (default) — OR SET NULL, open question §9.1** | Deleting a category while equipment references it: RESTRICT blocks the delete (safe, current behavior); SET NULL would silently orphan the reference. No category-deletion workflow exists today either way — this is prospective. |
| 2 | `equipment_department_owner_id_fkey` | `equipment.department_owner_id` | `departments.id` | Yes | NO ACTION | **RESTRICT (default) — OR SET NULL, open question §9.1** | Same reasoning as #1, for departments. |
| 3 | `equipment_current_location_id_fkey` | `equipment.current_location_id` | `locations.id` | Yes | NO ACTION | **RESTRICT (default) — OR SET NULL, open question §9.1** | Same reasoning as #1, for locations. |
| 4 | `equipment_status_history_equipment_id_fkey` | `equipment_status_history.equipment_id` | `equipment.id` | No | NO ACTION | RESTRICT | History rows must never be silently orphaned or cascade-deleted; equipment deletion is soft (never a real `DELETE`) so this is never exercised regardless. |
| 5 | `equipment_status_history_changed_by_user_id_fkey` | `.changed_by_user_id` | `users.id` | Yes | NO ACTION | RESTRICT | Preserve audit-trail integrity — a history row must not lose its actor attribution. |
| 6 | `pm_schedules_equipment_id_fkey` | `pm_schedules.equipment_id` | `equipment.id` | — | NO ACTION | RESTRICT | Dead table (§7) — policy set for schema consistency only, no live code path exercises it. |
| 7 | `pm_schedules_performed_by_user_id_fkey` | `.performed_by_user_id` | `users.id` | — | NO ACTION | RESTRICT | Same as #6. |
| 8 | `calibration_schedules_equipment_id_fkey` | `calibration_schedules.equipment_id` | `equipment.id` | — | NO ACTION | RESTRICT | Dead table (§7) — same as #6. |
| 9 | `calibration_schedules_performed_by_user_id_fkey` | `.performed_by_user_id` | `users.id` | — | NO ACTION | RESTRICT | Same as #6. |
| 10 | `equipment_attachments_equipment_id_fkey` | `equipment_attachments.equipment_id` | `equipment.id` | No | NO ACTION | RESTRICT | Attachments must not be orphaned by an equipment row disappearing (which never happens via hard delete anyway). |
| 11 | `equipment_attachments_uploaded_by_user_id_fkey` | `.uploaded_by_user_id` | `users.id` | Yes | NO ACTION | RESTRICT | Preserve attachment provenance. |
| 12 | `notifications_user_id_fkey` | `notifications.user_id` | `users.id` | No | NO ACTION | RESTRICT | A notification must not silently lose its recipient reference. |
| 13 | `borrow_transactions_equipment_id_fkey` | `borrow_transactions.equipment_id` | `equipment.id` | No | NO ACTION | RESTRICT | Transaction history must never lose its equipment reference — this is the core business record. |
| 14 | `borrow_transactions_borrower_user_id_fkey` | `.borrower_user_id` | `users.id` | Yes | NO ACTION | RESTRICT | Preserve dispatch-actor attribution; nullable because PR7b removed this from the active write path for new dispatches but historical rows retain it. |
| 15 | `borrow_transactions_ward_id_fkey` | `.ward_id` | `wards.id` | Yes | NO ACTION | RESTRICT | The recorded receiving ward is business-critical history (per `docs/BUSINESS_RULES.md`) and must never be silently orphaned. |
| 16 | `borrow_transactions_department_id_fkey` | `.department_id` | `departments.id` | Yes | NO ACTION | RESTRICT | Same reasoning as #15. |
| 17 | `borrow_transactions_pickup_location_id_fkey` | `.pickup_location_id` | `locations.id` | Yes | NO ACTION | RESTRICT | Historical location reference, same reasoning. |
| 18 | `borrow_transactions_dropoff_location_id_fkey` | `.dropoff_location_id` | `locations.id` | Yes | NO ACTION | RESTRICT | Same as #17. |
| 19 | `borrow_transactions_received_by_user_id_fkey` | `.received_by_user_id` | `users.id` | Yes | NO ACTION | RESTRICT | Preserve receipt-actor attribution. |
| 20 | `transaction_attachments_transaction_id_fkey` | `transaction_attachments.transaction_id` | `borrow_transactions.id` | No | NO ACTION | RESTRICT | Attachments must not be orphaned. |
| 21 | `transaction_attachments_uploaded_by_user_id_fkey` | `.uploaded_by_user_id` | `users.id` | Yes | NO ACTION | RESTRICT | Preserve provenance. |
| 22 | `audit_logs_user_id_fkey` | `audit_logs.user_id` | `users.id` | Yes | NO ACTION | RESTRICT | Audit-log integrity — never silently orphaned. |
| 23 | `wards_department_id_fkey` | `wards.department_id` | `departments.id` | — | NO ACTION | RESTRICT | Referential integrity for master data; no deletion workflow exists for departments today. |
| 24 | `users_role_id_fkey` | `users.role_id` | `roles.id` | No | NO ACTION | RESTRICT | A user must always have a valid role; role deletion (if ever added) must never silently orphan users. |
| 25 | `user_role_migrations_user_id_fkey` | `user_role_migrations.user_id` | `users.id` | No | NO ACTION | RESTRICT | PR10 migration-provenance table; must never lose its user reference. |

**Migration impact:** all 25 changes are `ALTER TABLE ... DROP CONSTRAINT ... ADD CONSTRAINT ... FOREIGN KEY ... REFERENCES ... ON DELETE RESTRICT`-shaped — metadata-only, no data rewrite, no lock beyond the brief `ACCESS EXCLUSIVE` a constraint replacement requires (acceptable at this system's confirmed scale — "low hundreds of devices, thousands of transactions per year," per `docs/PROJECT_MEMORY.md`). Fully reversible with no data-loss caveat (downgrade simply drops the explicit `ON DELETE RESTRICT` and recreates the implicit-`NO ACTION` constraint). **This migration is paired with the 25 `ForeignKey(ondelete=...)` ORM model updates described above — they must land together, not as a database-only change**, so ORM metadata (and the SQLite tests built from it) match the PostgreSQL catalog.

**Do not introduce deletion semantics not already approved:** no relationship above is proposed for `CASCADE` or `SET DEFAULT` anywhere; the only non-default option raised (`SET NULL`) is explicitly parked as an open question (§9.1), not implemented.

---

## 5. CHECK Constraint Review

The original Schema Audit finding ("no CHECK constraints anywhere") is stale. Reconfirmed via live rehearsal — **9 CHECK constraints already exist**:

| Constraint | Table | Business rule | Added by |
|---|---|---|---|
| `ck_roles_name_confirmed` | `roles` | `name` must be one of the 3 confirmed roles | PR10 |
| `ck_equipment_bcm_code_canonical` | `equipment` | `bcm_code` must match the canonical BCM Code format | PR14-H3R |
| `ck_equipment_item_no_canonical` | `equipment` | `item_no` must match the canonical Item No format | PR14-H3R |
| `ck_equipment_status_four_state` | `equipment` | `status` must be one of the 4 confirmed lifecycle states | PR6 |
| `ck_borrow_transactions_dispatch_type` | `borrow_transactions` | `dispatch_type` must be `routine_round`/`on_demand` | PR7b |
| `ck_borrow_transactions_routine_round` | `borrow_transactions` | `routine_round` must be one of the 4 confirmed fixed times, or null | PR7b |
| `ck_borrow_transactions_routine_round_consistency` | `borrow_transactions` | `routine_round` required iff `dispatch_type='routine_round'` | PR7b |
| `ck_borrow_transactions_status_open_closed` | `borrow_transactions` | `status` must be `open`/`closed` | PR7 |
| `ck_confirmed_role_ownership_flags` | `confirmed_role_ownership` | provenance-table invariant flags | PR10 |

**This finding must not be re-opened wholesale.** Candidate columns considered for a new CHECK constraint during this investigation, and why each was rejected:

- `notification.type` — an enum-like string (`pm`/`calibration`, per live-code usage), but no CHECK exists. **Not proposed**: adding one now would require the same validate-before-enforce preflight as any other constraint, and the stale in-code comment (§7's `Notification.type` finding, listing a retired `overdue` value) suggests the confirmed value set has changed before without a corresponding migration — a CHECK constraint here is a legitimate future candidate but needs its own confirmed-value-set decision from the Owner first, not a hygiene-pass assumption.
- `equipment.raw_source_status` — free-text, deliberately verbatim source data (Roadmap PR12, "preserve exact source-cell text") — a CHECK constraint here would directly contradict its documented purpose. **Rejected.**
- `users.role_id`/`equipment.status` — already covered by `ck_roles_name_confirmed`/`ck_equipment_status_four_state` respectively (enforced via the referenced/owning table's own constraint or FK). **No gap.**

**No new CHECK constraint is proposed by PR15B.** If any is added in the future, the same `_preflight()` validate-before-enforce pattern established in migration `0005` (`_preflight(column, canonicalize)` — a `RuntimeError` naming offending rows if validation fails, before `ADD CONSTRAINT` is even attempted) must be followed, exactly as it would be for any schema change in this repository.

---

## 6. Index Naming Plan

**Adopted convention:** `ix_<table>_<column>` for single-column indexes, `ix_<table>_<purpose>` for indexes not tied to one column's raw name (e.g. the trigram GIN indexes), `ix_<table>_<column1>_<column2>` for composite indexes — matching SQLAlchemy's own default naming, which already produces 29 of the schema's 64 indexes today. `uq_<table>_<column>` for named unique constraints, matching the 4 that already exist from PR10's provenance tables.

### 6.1 Full current-state inventory (verified via `pg_indexes`, not assumed)

| Group | Count | Naming today | Example |
|---|---|---|---|
| SQLAlchemy-default indexes | 29 | `ix_<table>_<column>` (already correct) | `ix_equipment_bcm_code` |
| Named unique constraints | 4 | `uq_<table>_<columns>` (already correct) | `uq_confirmed_role_ownership_revision_name` |
| Hand-named indexes | 5 | `idx_` prefix (inconsistent with the above) | `idx_equipment_bcm_trgm`, `idx_tx_one_active_borrow` |
| **Auto-named unique constraints (new finding this round)** | **7** | PostgreSQL default `<table>_<column>_key` (a *third*, previously-uncounted inconsistent pattern) | `users_email_key`, `equipment_serial_number_key` |
| Primary keys | 19 (incl. `alembic_version_pkc`) | `<table>_pkey` (PostgreSQL default) | `equipment_pkey` |

Total: 64 indexes in the `public` schema.

**The 7 auto-named unique constraints exist because the owning columns use `unique=True` without `index=True` and without an explicit `UniqueConstraint(name=...)`** — confirmed via `grep -rn "unique=True" app/models/*.py`: `equipment.serial_number`, `equipment_categories.name`, `departments.code`, `wards.code`, `roles.name`, `users.employee_code`, `users.email`. (Columns that combine `unique=True` *with* `index=True` — `equipment.asset_number`, `.item_no`, `.bcm_code`, `.qr_code_value`, `borrow_transactions.transaction_no` — already get SQLAlchemy's `ix_` naming and are not part of this group.) This is a genuine, previously-unenumerated naming inconsistency: the predecessor design document only counted the `idx_`-vs-`ix_`/`uq_` split and did not identify this third group.

### 6.2 Rename plan

| Current name | Table | New name | Mechanism |
|---|---|---|---|
| `idx_equipment_asset_trgm` | `equipment` | `ix_equipment_asset_number_trgm` | `ALTER INDEX ... RENAME TO ...` |
| `idx_equipment_bcm_trgm` | `equipment` | `ix_equipment_bcm_code_trgm` | `ALTER INDEX ... RENAME TO ...` |
| `idx_equipment_name_trgm` | `equipment` | `ix_equipment_equipment_name_trgm` | `ALTER INDEX ... RENAME TO ...` |
| `idx_equipment_serial_trgm` | `equipment` | `ix_equipment_serial_number_trgm` | `ALTER INDEX ... RENAME TO ...` |
| `idx_tx_one_active_borrow` | `borrow_transactions` | `ix_borrow_transactions_one_active_borrow` | `ALTER INDEX ... RENAME TO ...` |
| `equipment_serial_number_key` | `equipment` | `uq_equipment_serial_number` | `ALTER TABLE equipment RENAME CONSTRAINT ... TO ...` |
| `equipment_categories_name_key` | `equipment_categories` | `uq_equipment_categories_name` | `ALTER TABLE ... RENAME CONSTRAINT ...` |
| `departments_code_key` | `departments` | `uq_departments_code` | `ALTER TABLE ... RENAME CONSTRAINT ...` |
| `wards_code_key` | `wards` | `uq_wards_code` | `ALTER TABLE ... RENAME CONSTRAINT ...` |
| `roles_name_key` | `roles` | `uq_roles_name` | `ALTER TABLE ... RENAME CONSTRAINT ...` |
| `users_employee_code_key` | `users` | `uq_users_employee_code` | `ALTER TABLE ... RENAME CONSTRAINT ...` |
| `users_email_key` | `users` | `uq_users_email` | `ALTER TABLE ... RENAME CONSTRAINT ...` |

**Note the two distinct SQL mechanisms required**, both metadata-only, both zero-rebuild, but not interchangeable: `ALTER INDEX ... RENAME TO ...` for plain/GIN indexes; `ALTER TABLE ... RENAME CONSTRAINT ... TO ...` for the 7 unique-constraint-backed indexes (PostgreSQL automatically renames the backing index when the owning constraint is renamed — attempting `ALTER INDEX` directly on a constraint-backed index name works too, but renaming the *constraint* is the correct, self-documenting operation since the constraint is the actual schema object with business meaning).

**Primary keys (`_pkey`) and their own PostgreSQL default naming are explicitly out of scope for this rename** — `_pkey` is PostgreSQL's own universal convention, not an inconsistency with anything else in this schema, and renaming primary keys carries a materially different risk profile (every FK in the schema references a primary key by object identity, not by name, so this is technically safe, but is unnecessary churn with zero naming-inconsistency to justify it).

### 6.3 Requirements (from the explicit instruction)

- **Metadata rename where possible:** 100% of this plan is `ALTER INDEX`/`ALTER TABLE ... RENAME CONSTRAINT` — no index is dropped and recreated.
- **No unnecessary rebuild:** confirmed zero rebuild for all 12 renames above; verified this is the correct PostgreSQL behavior (renaming an index or a constraint does not touch its underlying B-tree/GIN storage).
- **Verify names before rename:** the migration's `upgrade()` must query `pg_indexes`/`pg_constraint` for the *current* name before issuing the rename, exactly as migration `0011`'s `_ensure_index_concurrently()` already established the precedent of inspecting catalog state before acting rather than assuming a name exists.
- **Fail closed if unexpected:** if a name to be renamed does not exist, or a target name is already taken (collision), the migration must raise a clear `RuntimeError` naming the specific mismatch — matching the `_ensure_index_concurrently()`/migration-`0005`-`_preflight()` precedent of failing loudly with an actionable message rather than silently skipping or letting PostgreSQL's own (much less clear) error surface.
- **Fresh/historical convergence:** a fresh `base → head → 0012` install and a historical `0011 → 0012` upgrade must produce byte-identical final index/constraint names, verified as an automated regression test (same discipline every schema-bearing migration since `0004` has followed).

---

## 7. Legacy Model Review — `PMSchedule` / `CalibrationSchedule`

**Reconfirmed, not proposed for removal**, per explicit instruction.

- **Zero references outside their own model definitions**, reconfirmed this round via full-repository grep for `PMSchedule`, `CalibrationSchedule`, `pm_schedules`, `calibration_schedules` — no CRUD, no API route, no service, no seed data, no test references either table beyond `app/models/equipment.py`'s own class bodies and the FK constraints they participate in (§4, items 6–9).
- **ORM/`0001` bootstrap implications:** both tables are created by `Base.metadata.create_all()` inside migration `0001_initial.py` (the same TD-002 behavior governing every other model in this codebase). Removing the ORM classes would remove them from a **fresh install's** schema immediately, while an **existing deployment** would retain the tables until a dedicated `DROP TABLE` migration ran — this asymmetry must be resolved by a real migration if removal is ever pursued, not by deleting the model classes alone.
- **Fresh vs. upgraded schema divergence:** if removal is ever pursued, both paths (fresh install with no tables from the start; historical upgrade with tables dropped by migration) must converge to an identical final schema — the same discipline every schema-bearing PR in this repository already follows.
- **Possible production data:** no code path in this repository currently reads or writes either table, but this design has no visibility into whether any out-of-band process (a manual DB script, a partially-built future feature, direct administrative data entry in some real deployment) has ever written rows into them. Absence of application-code references is not proof of an empty table in every real deployment.

**Future removal requirements, if ever pursued** (unchanged from the PR15A-round document, reaffirmed): (1) explicit Repository Owner approval that PM/Calibration scheduling is not near-term confirmed work; (2) a dedicated migration, not bundled into PR15B's other changes; (3) a data-preflight step confirming zero rows exist in any real target deployment before `DROP TABLE` runs; (4) the same fresh/historical/downgrade/re-upgrade convergence testing every schema-bearing PR in this repository already follows. **This is its own small future PR, not PR15B scope.**

---

## 8. Migration Plan

**Migration numbering begins at `0012`** — confirmed current head is `0011_pagination_ordering_indexes` (no migration has been added since; PR15A shipped zero schema changes). **No existing migration file is modified.**

### 8.1 Validate-before-enforce strategy

Every constraint or type change in PR15B follows the pattern migration `0005` already established (`_preflight()`: a validation query proving existing data already satisfies the new rule, raising a clear, actionable `RuntimeError` naming offending rows if it does not, *before* the schema-altering statement runs — never letting `ALTER TABLE ... ADD CONSTRAINT`/`ALTER COLUMN ... TYPE` itself fail with an opaque PostgreSQL error). Concretely for PR15B:

- **Timezone conversion** does not require a data-validation preflight in the traditional sense (there is no "row that violates the new type" the way a CHECK constraint can be violated — every naive value converts unambiguously per §3.4), but the migration must still verify, before altering, that the `AT TIME ZONE 'UTC'` expression will not silently produce a NULL or error for any existing row (e.g., confirm no column has a sentinel/out-of-range value that would behave unexpectedly under the conversion).
- **FK `ondelete` changes** require no data preflight at all — no existing row can violate a delete-behavior change, since the change only affects what happens on a future `DELETE` that has never occurred (§4).
- **Index/constraint renames** require a name-existence preflight (§6.3), not a data-validation preflight.

### 8.2 Upgrade strategy — recommended: three separate migrations, not one combined migration

This document now recommends **splitting PR15B into three independently-revertible migrations** rather than one combined `0012_schema_hygiene.py` (the combined approach considered in the prior round of this document is superseded by this recommendation; see §9.3 for why it is no longer the default):

- **Migration A — `0012_timezone_conversion.py`**: the six naive-column `timestamptz` conversions (§3.4, Option A per §3.5), plus the three accompanying Python call-site fixes (`auth_service.py::last_login_at`, `crud/transaction.py::returned_at`, `crud/equipment.py::soft_delete()::deleted_at` — none of these three require a migration on their own, only a code change bundled with this one since they fix the same class of bug the migration addresses).
- **Migration B — `0013_fk_ondelete_policy.py`**: explicit `ondelete="RESTRICT"` (or the §9.1-approved alternative) on all 25 FKs, bundled with the corresponding 25 `ForeignKey(ondelete=...)` ORM model updates (§4 cross-check) so the migration and the model change land atomically.
- **Migration C — `0014_index_naming_convergence.py`**: the 12 index/constraint renames (§6.2).
- The `Notification.type` stale-comment fix and `docs/TECH_DEBT.md` TD-001 status correction are documentation/comment-only and require no migration; they can accompany whichever of A/B/C is judged most relevant to review together, or ship as their own trivial documentation commit.

**Why separation reduces risk and simplifies rollback, versus one combined migration:**
- **Independent revert:** if the timezone conversion (Migration A) needs a downgrade for any reason (e.g., an unforeseen SQLite-parity or frontend-serialization issue caught late), Migrations B and C — which touch entirely unrelated schema concerns — are not forced to revert with it. A single combined migration makes every downgrade all-or-nothing.
- **Narrower blast radius per review:** each migration's `upgrade()`/`downgrade()` pair is reviewable and testable in isolation against its own concern (timezone semantics vs. FK delete behavior vs. cosmetic renames), rather than one large diff mixing three unrelated risk profiles (§10 already separates these into High/Medium/Low — the migration structure should mirror that separation).
- **Clearer historical-upgrade testing:** the required fresh/historical/downgrade/re-upgrade rehearsal (§8.5) is simpler to reason about and to write regression tests for when each migration has one concern, rather than asserting compound before/after state across three unrelated changes in one file.
- **Precedent-consistent, not precedent-breaking:** migrations `0005`/`0006`/`0009` bundled several *closely related* sub-changes serving one coherent Roadmap PR concern (e.g., `0006`'s status-model collapse). PR15B's three concerns (timezone, FK policy, index naming) are not sub-parts of one coherent change the way those were — they are three independent hygiene concerns that happen to share a Roadmap PR number, which is a materially different case for bundling.

All three migrations are still scoped strictly to PR15B and still begin numbering at `0012` (current head: `0011_pagination_ordering_indexes`).

### 8.3 Downgrade strategy

Each migration downgrades independently, per the three-migration split in §8.2:

- **Migration A downgrade:** reverse `AT TIME ZONE 'UTC'` conversion (§3.4's downgrade expression) — value-lossless, with the forward-compatibility caveat stated in the docstring (§3.6). Does not require B or C to also revert.
- **Migration B downgrade:** drop the explicit `RESTRICT`/`SET NULL` constraint and the 25 accompanying `ForeignKey(ondelete=...)` ORM changes, recreate the implicit-`NO ACTION` constraint — fully reversible, no caveat. Does not require A or C to also revert.
- **Migration C downgrade:** reverse rename — fully reversible, no caveat. Does not require A or B to also revert.

### 8.4 Data-loss limitations

None of the proposed changes are destructive. The only value-interpretation risk is the timezone conversion (§3.4), which is meaning-preserving by construction given the confirmed write history (§3.3) — stated as a limitation on *future* correctness after a downgrade (§3.6), not a data-loss risk today.

### 8.5 Historical compatibility

All changes must be rehearsed both as a fresh `base → head → 0012` install and as a historical `0011 → 0012` upgrade against a database seeded with realistic pre-existing rows (not empty tables) — required specifically for the timezone conversion (§3.7.2) and the fresh/historical index-name convergence check (§6.3).

### 8.6 PostgreSQL evidence requirements

Every claim in this document was verified against a live PostgreSQL 16 rehearsal, not assumed (§0 methodology note). The implementation phase must produce the same class of evidence: `information_schema.columns` before/after for the timezone conversion, `pg_constraint.confdeltype` before/after for the FK changes, `pg_indexes`/`pg_constraint` name lookups before/after for the renames — captured as automated `pytest.mark.postgres` regression tests, not just manual `psql` verification (which is how this document's own findings were gathered, but is not sufficient as permanent regression coverage).

---

## 9. Open Questions for Architecture Approval

1. **`ondelete` policy for `equipment.category_id`/`department_owner_id`/`current_location_id`** (§4, items 1–3): `RESTRICT` (safe default, matches current de facto behavior) or `SET NULL` (allows deleting a category/department/location even while equipment references it, orphaning the reference to `NULL`)? No deletion workflow exists for any of `equipment_categories`/`departments`/`locations` today, so this is prospective either way — recommend `RESTRICT` for this pass, revisited if/when such a deletion workflow is ever proposed.
2. **Option A vs. Option B for the four `TimestampMixin`-inconsistent columns** (§3.5): fix type + callable only (Option A, recommended), or also converge onto `server_default=func.now()` for full mechanism consistency (Option B)? Recommend Option A for this pass as the lower-risk choice; Option B is a legitimate future refinement once Option A has shipped and been observed stable.
3. **Target migration filename/number confirmation — updated recommendation:** this document now recommends the three-migration split (`0012_timezone_conversion.py`, `0013_fk_ondelete_policy.py`, `0014_index_naming_convergence.py`) detailed in §8.2, superseding the prior round's default of one combined `0012_schema_hygiene.py`. This is still listed as an open item because it is a structural choice the Owner/reviewer should explicitly confirm before implementation begins, not because this document is neutral on it — §8.2 states the recommendation and reasoning.

---

## 10. Risks

**High Risk**

| Item | Risk | Mitigation |
|---|---|---|
| Timezone conversion — serialization/display impact | Six columns' wire format changes from naive to offset-bearing ISO-8601; three of them (`borrowed_at`, `returned_at`, `changed_at`) are directly parsed and displayed to end users via `new Date(...)` in `EquipmentDetailPage.tsx`/`ReturnPage.tsx` (§3.7.7). An unverified assumption here would ship an unreviewed, user-visible timestamp-display change. | Explicit frontend-parsing verification is a required, named test dimension (§3.7.7), not an assumption; the change is a *correction* of a latent display bug (naive UTC values currently misparsed as local time), documented and tested as such, not shipped silently. |

**Medium Risk**

| Item | Risk | Mitigation |
|---|---|---|
| Timezone conversion — migration mechanics | Touches six columns' on-disk representation across four tables; requires the full historical-upgrade/downgrade/re-upgrade/SQLite-parity/PostgreSQL-parity testing specified in §3.7 — not a mechanical change. | Full four-path migration testing discipline (§8.5), explicit `AT TIME ZONE 'UTC'` (not a bare cast) stated in both this document and the migration's own comments (§3.4). |
| `TimestampMixin`-consistency decision (Option A vs. B, §3.5/§9.2) | Choosing Option B without explicit approval would introduce an unreviewed change to *who computes* four columns' values (Python → PostgreSQL), a genuine behavioral shift beyond type-widening. | Option A recommended as the default; Option B explicitly gated behind architecture approval, not assumed. |
| ORM `ForeignKey(ondelete=...)` / migration divergence (new finding, §4 cross-check) | If Migration B's raw-SQL `ON DELETE RESTRICT` ships without the paired 25 ORM `ForeignKey()` updates, the SQLite test suite (built via `Base.metadata.create_all()` in `tests/conftest.py:28`, bypassing Alembic) silently diverges from PostgreSQL, and a future `alembic revision --autogenerate` could attempt to revert the database back to `NO ACTION`. | The ORM model updates are specified as a mandatory, atomic part of Migration B (§4, §8.2) — not an optional follow-up — and verified as an explicit Acceptance Criterion (§11). |

**Low Risk**

| Item | Risk | Mitigation |
|---|---|---|
| FK `ondelete` policy explicitization | Zero observed-behavior change today (confirmed: zero hard-delete code paths exist for any of the 25 FKs), but is a real schema commitment for future code. | The `SET NULL` open question (§9.1) is resolved with explicit Owner input before implementation, not defaulted silently; all 22 non-open-question FKs get `RESTRICT`, matching current behavior exactly. |
| Index/constraint renames | Purely cosmetic; `ALTER INDEX`/`ALTER TABLE ... RENAME CONSTRAINT` has no behavioral effect on query plans, locking beyond a brief metadata lock, or stored data. | `EXPLAIN` before/after comparison for the 5 renamed `idx_`→`ix_` indexes (trivial to prove no plan change since nothing about the index itself changed). |
| `Notification.type` comment fix / `docs/TECH_DEBT.md` TD-001 correction | None — documentation/comment-only. | N/A. |
| CHECK constraints | None — no new constraint is proposed by this document. | N/A. |
| Deferred items (`users` soft-delete, `PMSchedule`/`CalibrationSchedule` removal, FK index additions, metrics/tracing/dashboards/log aggregation/alerting) | N/A — explicitly out of scope for PR15B. | See §2 disposition matrix and §7 for the specific governance justification each carries. |

---

## 10a. Cross-check Verification

Verified before this document is considered complete, per the explicit pre-completion checklist for this review round:

- **✓ ORM `ForeignKey(ondelete=...)` matches planned migration.** Confirmed via `grep -rn "ForeignKey(" backend/app/models/*.py`: currently **no** ORM `ForeignKey()` call specifies `ondelete=`. This was a real gap, not a pre-existing match — it is now closed by requiring the 25 ORM model updates as a mandatory, atomic part of Migration B (§4, §8.2), not an assumption that the migration alone suffices.
- **✓ Current ORM metadata will produce the same schema as upgraded databases.** Today it would **not**, for the FK `ondelete` policy specifically (see above) — confirmed by tracing that `alembic/versions/0001_initial.py:26` bootstraps via `Base.metadata.create_all(bind=bind)` and that `backend/tests/conftest.py:28` builds the SQLite test schema the same way, bypassing Alembic. This document requires the ORM and migration changes to land together so the two converge; that requirement is now explicit in §4 and §8.2, and is captured as an Acceptance Criterion (§11).
- **✓ All known naive datetime writers are identified.** Confirmed via `grep -rn "datetime.utcnow()" backend/app` — exactly four call sites exist: `crud/equipment.py:260` (`equipment.deleted_at`), `crud/transaction.py:71` (`transaction_no` string formatting — not a timestamp-column writer, reviewed and excluded, §3.2), `crud/transaction.py:198` (`returned_at`), `services/auth_service.py:62` (`users.last_login_at`). No fifth call site exists anywhere in `backend/app`. `equipment.deleted_at`, `users.last_login_at`, and `returned_at` — the three the review explicitly asked to confirm — are all present in §3.2's table.
- **✓ Timezone migration specifies upgrade AND downgrade expressions.** Both are now stated as literal SQL in §3.4: the upgrade (`... TYPE timestamptz USING ... AT TIME ZONE 'UTC'`) and the downgrade (`... TYPE timestamp USING ... AT TIME ZONE 'UTC'`), not merely described in prose.
- **✓ Index/constraint renames perform preflight validation and fail closed.** Specified in §6.3: name-existence preflight before every rename, `RuntimeError` on any mismatch or collision, matching the `0005`/`0011` precedent.
- **✓ Frontend rendering implications are documented.** §3.7.7 and the High Risk row in §10 both document the `new Date(...)`/`.toLocaleString("th-TH")` usage in `EquipmentDetailPage.tsx`/`ReturnPage.tsx` and the resulting user-visible display correction.

---

## 11. Acceptance Criteria

- All six naive-timestamp columns identified in §3.3 are `timestamptz`, converted via `AT TIME ZONE 'UTC'` (not a bare cast) — verified by a test asserting a known pre-existing naive timestamp's value is unchanged (same instant) after conversion.
- `users.last_login_at`'s write path (`auth_service.py`), `equipment.deleted_at`'s write path (`crud/equipment.py::soft_delete()`, new finding this round), and `borrow_transactions.returned_at`'s write path (`crud/transaction.py`) all use `datetime.now(timezone.utc)`, not `datetime.utcnow()`.
- The four `TimestampMixin`-inconsistent columns (§3.5) have their Python-side default callable fixed to a UTC-aware equivalent, per whichever of Option A/B is approved (§9.2).
- Migration rehearsed on real PostgreSQL for: fresh install, historical upgrade (`0011 → 0012`), downgrade, re-upgrade.
- Serialization/display compatibility confirmed against `frontend/src/pages/EquipmentDetailPage.tsx`/`ReturnPage.tsx`'s actual `new Date(...)` usage (§3.7.7) — no silent, unverified wire-format or display-behavior change.
- SQLite test-path compatibility confirmed — the non-PostgreSQL suite's assertions about these columns' behavior remain meaningful, not silently divergent from the PostgreSQL suite.
- All 25 FKs have an explicit `ondelete` policy: `RESTRICT` for 22, and `RESTRICT` or `SET NULL` for the 3 named in §9.1 exactly as the Owner decides — no relationship defaults to anything else, and no relationship's behavior changes from what §4's table documents today (`NO ACTION` → `RESTRICT` is a zero-behavior-change identity mapping for every FK where `RESTRICT` is chosen).
- All 25 ORM `ForeignKey()` declarations in `app/models/*.py` carry an explicit `ondelete=` matching the migrated PostgreSQL catalog exactly — verified by confirming `alembic revision --autogenerate` produces no diff after the FK migration lands, and that the SQLite test suite (built via `Base.metadata.create_all()`) exercises the same `ondelete` semantics as PostgreSQL.
- PR15B ships as three independently-revertible migrations (`0012_timezone_conversion.py`, `0013_fk_ondelete_policy.py`, `0014_index_naming_convergence.py`) per §8.2, unless the Owner explicitly approves the combined-migration alternative instead.
- All 12 indexes/constraints identified in §6.2 are renamed onto the `ix_`/`uq_` convention, with zero query-plan or storage change verified via `EXPLAIN` before/after for the index renames.
- `Notification.type`'s comment lists only currently-producible values (`pm`, `calibration`).
- `docs/TECH_DEBT.md` TD-001 status corrected to match the evidence already in code (`eager_defaults=True` at `app/models/equipment.py:110`) and in `docs/DECISION_LOG.md`/`knowledge/CONTEXT.md`.
- No CHECK constraint is added beyond the 9 already documented in §5 — this document proposes zero new constraints.
- `PMSchedule`/`CalibrationSchedule` are **not** removed, renamed, or otherwise modified by PR15B.
- No FK index is added by PR15B (remains evidence-gated, out of scope per §2).
- Full backend suite (including PostgreSQL) remains green; `git diff --check` clean.
- No item deferred in §2/§7 (`users` soft-delete, `PMSchedule`/`CalibrationSchedule` removal, FK index additions, metrics/tracing/alerting/dashboards/log aggregation) is silently implemented as part of PR15B — scope matches exactly what §2's disposition matrix and this document specify.

---

## Out of Scope (explicit)

Per the governing instruction, this document does not propose, and PR15B must not implement: metrics, tracing, dashboards, additional logging beyond what PR15A already shipped, any API contract change, any business-workflow change, or any ORM cleanup unrelated to schema hygiene (e.g. no refactor of unrelated CRUD/service code, no dependency upgrades, no unrelated model reorganization).

---

*No code was written or modified to produce this document. No migration was generated. No repository file was modified. Every schema/database claim in this document was verified against a live PostgreSQL 16 instance rehearsed from `base` to `head` (migrations `0001`–`0011`) on a disposable scratch database created and dropped solely for this investigation — not assumed, and not read from a stale local test database. Awaiting architecture approval before implementation begins.*
