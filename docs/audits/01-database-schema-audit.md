# PostgreSQL Schema Review — Medical Equipment Pool

**Reviewer:** Senior Backend Engineer
**Scope:** `backend/app/models/*.py` + `backend/alembic/versions/0001_initial.py` (schema quality only — no functional/feature review)
**Method:** Read every model file and the migration directly; verified all claims below against actual code (`grep`), not against the design docs.

Severity scale: **Critical** (data corruption/security risk) · **High** (will bite in production at documented scale) · **Medium** (real gap, not urgent) · **Low** (style/hygiene)

---

## 1. Table Normalization (1NF–3NF)

Overall the schema is properly normalized — master data (`departments`, `wards`, `locations`, `equipment_categories`) is correctly extracted, and there's no repeating-group violation anywhere. Two issues:

### 1.1 — `borrow_transactions.department_id` duplicates `wards.department_id`
- **Severity:** Medium
- **Why it's a problem:** `department_id` on the transaction is a denormalized copy of the department reachable via `ward_id → wards.department_id`. Nothing in the schema keeps them in sync — if a ward is reassigned to a different department after transactions exist, historical `department_id` values silently diverge from the ward's current department, and there's no trigger, generated column, or CHECK tying them together.
- **Proposed fix:** Either (a) drop the column and derive department via a join on `ward_id` at query time, or (b) if kept for reporting-performance reasons, document it explicitly as a point-in-time snapshot (not "current department of this ward") and consider a `CHECK`/trigger only if strict consistency is required.
- **Migration impact:** Low if dropping (column removal, update 2 call sites in `crud/transaction.py`/`borrow_service.py`); zero if just documenting.

### 1.2 — `equipment.metadata` (JSONB catch-all)
- **Severity:** Low (informational)
- **Why it's a problem:** Acceptable as an escape hatch today (unused by any current query), but if teams start putting structured, filterable business data in there instead of real columns, it erodes the benefit of the relational schema around it.
- **Proposed fix:** No action now; revisit if a concrete field needs to be promoted out of it.
- **Migration impact:** None today.

---

## 2. Foreign Key Consistency

### 2.1 — `equipment.qr_code_value` is a derived duplicate of `asset_number` with no enforced link
- **Severity:** Medium
- **Why it's a problem:** `qr_code_value` is always computed as `"MEP:" + asset_number"` (`qr_service.build_qr_value`), but it's stored as an independent `UNIQUE` column with no DB-level relationship to `asset_number`. Nothing stops the two from drifting apart if any future code path updates one without the other (today's `PATCH /equipment/{id}` happens to not allow editing `asset_number`, but that's an application-layer accident, not a schema guarantee).
- **Proposed fix:** Convert `qr_code_value` to a PostgreSQL generated column: `GENERATED ALWAYS AS ('MEP:' || asset_number) STORED`, or at minimum add a `CHECK (qr_code_value = 'MEP:' || asset_number)`.
- **Migration impact:** Medium — requires a migration to convert the column type and backfill; low risk since the invariant already holds for all existing rows.

### 2.2 — `audit_logs.entity_id` has no foreign key (polymorphic reference)
- **Severity:** Low (informational, expected tradeoff for a generic audit table)
- **Why it's a problem:** Cannot be validated by the DB; relies entirely on `entity_type` + `entity_id` being set correctly by application code.
- **Proposed fix:** No schema fix recommended (this is a standard, acceptable pattern for audit tables). Just noting it as a conscious tradeoff, not an oversight.
- **Migration impact:** None.

*(Naming inconsistency between `equipment.department_owner_id` and `borrow_transactions.department_id`/`wards.department_id` for the same conceptual target is covered in §7, not repeated here.)*

---

## 3. Missing Indexes

Checked every FK and every WHERE/ORDER BY/GROUP BY clause in `crud/` and `services/` against the actual index declarations in the models.

| Column | Used in | Indexed? | Severity |
|---|---|---|---|
| `equipment.category_id` | `?category_id=` filter (`crud/equipment.py search()`) | **No** | High |
| `equipment.department_owner_id` | `?department_id=` filter | **No** | High |
| `equipment.current_location_id` | not queried yet, but FK with zero index | **No** | Medium |
| `users.role_id` | FK from every user row to its role; no query filters by it today, but every FK should be indexed as a matter of course (join cost, parent-row lock cost on update/delete) | **No** | Medium |
| `borrow_transactions.department_id` | not currently filtered by API, but exists as a reportable column | **No** | Low |
| `borrow_transactions.borrower_user_id` | not currently filtered | **No** | Low |
| `wards.department_id` | not currently filtered | **No** | Low |
| `equipment_status_history.changed_at` | `get_history()` orders by this column | **No** | Medium (see §4.6) |
| `audit_logs.entity_id` | not exposed via API today, but the natural "audit trail for this equipment" query needs it | **No** | Medium |

**Proposed fix:** Add `index=True` (or explicit composite indexes, see §4) to the columns above, prioritizing `category_id`, `department_owner_id` (both directly hit by the live search endpoint with no index at all — this is the most concrete "missing index" finding in the review).

**Migration impact:** Low — pure additive `CREATE INDEX` statements, no data changes, no downtime with `CREATE INDEX CONCURRENTLY` in production.

### 3.1 — `pm_schedules` / `calibration_schedules` are unused by any code path
- **Severity:** Medium (schema hygiene, not a bug)
- **Why it's a problem:** Verified via grep — no `crud/`, `service/`, or `api/` module reads or writes `PMSchedule`/`CalibrationSchedule` anywhere. The application derives PM/CAL "due soon" entirely from `equipment.pm_due_date`/`cal_due_date` instead. These two tables exist in the schema, ship in the migration, and carry FKs/columns that nothing maintains — dead schema is a maintenance and index-planning liability (e.g., anyone reviewing "should this have an index" is reviewing a table with no real query pattern to design against).
- **Proposed fix:** Not a "new feature" — just a schema-quality call: either wire these tables in when the PM/CAL history feature is built, or drop them from the migration until that's ready, so the live schema only contains tables actually in use.
- **Migration impact:** Low to drop now (no data yet); becomes a real migration later if data has accumulated.

---

## 4. Composite Indexes

### 4.1 — Documented partial indexes were never actually implemented
- **Severity:** High
- **Why it's a problem:** `docs/02-database-schema.md §2` explicitly specifies:
  ```sql
  CREATE INDEX idx_equipment_status ON equipment (status) WHERE deleted_at IS NULL;
  CREATE INDEX idx_equipment_pm_due ON equipment (pm_due_date) WHERE deleted_at IS NULL;
  CREATE INDEX idx_equipment_cal_due ON equipment (cal_due_date) WHERE deleted_at IS NULL;
  ```
  But the actual models only declare plain `index=True` on `status`, `pm_due_date`, `cal_due_date` — SQLAlchemy emits **non-partial** indexes auto-named `ix_equipment_status`, `ix_equipment_pm_due_date`, `ix_equipment_cal_due_date`. Every real query against these columns also filters `deleted_at IS NULL` (confirmed in `crud/equipment.py` and `dashboard_service.py`), so the index carries every soft-deleted row forever — larger index, worse cache locality, and it doesn't match the documented design at all.
- **Proposed fix:** Replace the three plain indexes with partial indexes matching the documented design (`postgresql_where=text("deleted_at IS NULL")` in the `mapped_column`/`Index(...)` declaration), and rename to match the `idx_` convention used elsewhere in the schema (see §7.1).
- **Migration impact:** Low — drop 3 indexes, create 3 partial indexes. No data changes.

### 4.2 — `get_borrow_trend()` wraps `borrowed_at` in `func.date(...)`, defeating its own index
- **Severity:** High
- **Why it's a problem:** `dashboard_service.py`:
  ```python
  select(func.date(BorrowTransaction.borrowed_at), func.count())
  .where(func.date(BorrowTransaction.borrowed_at) >= since)
  .group_by(func.date(BorrowTransaction.borrowed_at))
  ```
  Wrapping the column in `date()` makes the existing plain btree index on `borrowed_at` non-sargable — Postgres can't use it to satisfy this predicate. This chart is fetched on every Dashboard page load and every 60s thereafter (`refetchInterval: 60000` in the frontend). At the documented target of 2M+ transaction rows, this becomes a full sequential scan on every refresh, directly threatening the "< 300ms" performance requirement in `docs/07`.
- **Proposed fix:** Add an expression index `CREATE INDEX ON borrow_transactions (date(borrowed_at))` (schema-level fix, matches this review's scope), **or** rewrite the query to a half-open range (`borrowed_at >= since AND borrowed_at < since + interval '1 day' * range`) so the existing plain index on `borrowed_at` is used directly — the latter is a query change, not a schema change, but is worth noting since a schema-only fix (expression index) is treating a symptom.
- **Migration impact:** Low (additive expression index) if going the index route.

### 4.3 — `notifications` has two single-column indexes instead of one composite
- **Severity:** Low
- **Why it's a problem:** The only query against this table is `WHERE user_id = ? ORDER BY created_at DESC LIMIT 50`. `user_id` is indexed; `created_at` is separately indexed at the mixin/column level for other tables but not composed with `user_id` here. A single composite `(user_id, created_at DESC)` index serves this exact access pattern far better than two independent single-column indexes.
- **Proposed fix:** Replace the single-column `user_id` index with a composite `(user_id, created_at DESC)`.
- **Migration impact:** Low.

### 4.4 — `transactions` list endpoint has no composite covering `(ward_id, created_at)` or `(status, created_at)`
- **Severity:** Medium
- **Why it's a problem:** `crud/transaction.py search()` filters by `ward_id`/`equipment_id`/`status` individually and always orders by `created_at DESC, id DESC` for keyset pagination. Single-column indexes exist on each filter but not composed with the sort key, so Postgres has to intersect an index scan with a separate sort step rather than walking one index in order.
- **Proposed fix:** Add `(ward_id, created_at DESC)` as the highest-value composite (matches the "this ward's history" report pattern implied by the spec); `(status, created_at DESC)` as a secondary candidate if status-filtered views become common.
- **Migration impact:** Low.

### 4.5 — `borrow_transactions (equipment_id) WHERE status='borrowed'` — correctly designed
- **Severity:** N/A (positive finding)
- Worth noting explicitly: the existing `idx_tx_one_active_borrow` partial unique index does double duty as both the double-borrow integrity guard *and* the ideal index for `get_active_borrow_for_equipment()`/`list_active()`. This is good design and shouldn't be touched.

### 4.6 — `equipment_status_history` timeline query has no composite
- **Severity:** Low-Medium
- **Why it's a problem:** `get_history()` does `WHERE equipment_id = ? ORDER BY changed_at DESC`; `equipment_id` is indexed but `changed_at` is not, so Postgres finds the matching rows via the index and then sorts in memory. Fine at today's low per-asset row counts, but grows unbounded platform-wide over the system's lifetime.
- **Proposed fix:** Composite `(equipment_id, changed_at DESC)`.
- **Migration impact:** Low.

---

## 5. Nullable Fields

### 5.1 — `borrow_transactions.borrower_user_id` is nullable but the application never leaves it null
- **Severity:** Medium
- **Why it's a problem:** Every call site (`borrow_service.borrow()`) sets this to the authenticated user's ID. Leaving the column nullable is looser than the actual invariant the application maintains — a future direct-DB write path or a code regression could silently create an unaccountable transaction, which matters for a hospital audit trail.
- **Proposed fix:** Make `NOT NULL` to match the real invariant.
- **Migration impact:** Medium — requires backfill check (should be zero-risk since the app never produces nulls) then `ALTER COLUMN ... SET NOT NULL`.

### 5.2 — `equipment_status_history.changed_by_user_id` nullable, and the scheduler's overdue transition never writes to this table at all
- **Severity:** Medium
- **Why it's a problem:** `worker/scheduler.py`'s `check_overdue_returns()` flips `BorrowTransaction.status` directly but never calls `equipment_crud.change_status()` — so automated transitions bypass the status-history table entirely, meaning `changed_by_user_id IS NULL` currently has *no* actual occurrence in the table despite being nullable, and the audit trail has a silent gap for scheduler-driven changes. (Flagging this as evidence for the nullability question — the actual scheduler logic fix is out of scope for a schema-only review.)
- **Proposed fix:** If system/automated changes are meant to be representable, keep it nullable but add a `changed_by_system BOOLEAN NOT NULL DEFAULT false` discriminator so "null actor" is an intentional, queryable state rather than ambiguous. Otherwise make it `NOT NULL` and require the scheduler to write a system-actor row.
- **Migration impact:** Low (additive column) for the discriminator option.

### 5.3 — `equipment.rfid_tag` nullable with no uniqueness constraint
- **Severity:** Medium (forward-looking)
- **Why it's a problem:** Marked "Future" in the spec and unused today, so low urgency — but as written, nothing would stop two equipment rows from sharing one physical RFID tag once the feature ships.
- **Proposed fix:** Add `unique=True` now (nullable-unique is safe — Postgres allows multiple NULLs), same pattern already correctly used for `serial_number`.
- **Migration impact:** Low.

### 5.4 — `wards.department_id` is nullable — is an "orphan ward" a valid state?
- **Severity:** Medium (needs domain confirmation, not a unilateral fix)
- **Why it's a problem:** If every ward must organizationally belong to a department (likely, given the hospital domain), allowing `NULL` here weakens a relationship that should probably be mandatory.
- **Proposed fix:** Confirm with domain owner; if mandatory, make `NOT NULL`.
- **Migration impact:** Medium — requires backfilling any existing null rows before adding the constraint.

### 5.5 — `borrow_transactions.due_at` is nullable, which silently excludes those loans from overdue tracking
- **Severity:** Medium-High
- **Why it's a problem:** `check_overdue_returns()` explicitly filters `due_at.is_not(None)`. Any borrow created without a due date can never be flagged overdue — given "Overdue Return" is an explicit product requirement, this is a nullability decision with direct functional consequence, not just a data-modeling nicety.
- **Proposed fix:** Either require `due_at` at creation (defaulted from a per-category/department loan period), or explicitly document "no due date = indefinite loan, excluded from overdue tracking by design" so it's a conscious choice, not an oversight.
- **Migration impact:** Low if just adding a default at the application layer; Medium if backfilling and enforcing `NOT NULL`.

### 5.6 — Correctly-nullable fields (no action needed)
- `pm_schedules.performed_by_user_id` / `calibration_schedules.performed_by_user_id` — correctly nullable (a PM/CAL can be scheduled long before it's performed).
- `equipment.serial_number` nullable + `UNIQUE` — correctly modeled (multiple NULLs don't collide in Postgres); flagging only because this is a common mistake elsewhere and it's done right here.

---

## 6. Enum Usage

- **Severity:** High (single grouped finding — same root cause across all affected columns)
- **Why it's a problem:** Only `equipment.status` has any enum-like wrapper, and even that is declared with `native_enum=False`, which renders it as a plain `VARCHAR(30)` with **zero database-level constraint**. Every other "closed vocabulary" column is a bare `String` with the valid values living only as Python-level constants/dict keys, never enforced by the database:

  | Column | Valid values (enforced only in app code) |
  |---|---|
  | `equipment.status` | `EquipmentStatus` enum, but `native_enum=False` ⇒ no DB constraint |
  | `borrow_transactions.status` | `TX_STATUS_*` constants in `transaction.py` |
  | `borrow_transactions.condition_on_return` | keys of `borrow_service.RETURN_CONDITION_TO_STATUS` |
  | `pm_schedules.status` / `calibration_schedules.status` | undocumented, default `"scheduled"` only |
  | `notifications.type` | `pm`/`calibration`/`overdue`/`broken` (comment only) |
  | `transaction_attachments.kind` | `photo`/`signature` (comment only) |

  Any raw SQL, migration mistake, manual data fix, or future ORM bypass can insert an invalid value (typo, trailing whitespace, wrong case) and Postgres will accept it silently — there is no CHECK constraint or native ENUM type anywhere in the schema.
- **Proposed fix:** Pick one consistent strategy and apply it uniformly: either (a) switch to real PostgreSQL `ENUM` types (`native_enum=True`) for all of the above, or (b) keep `VARCHAR` but add explicit `CHECK (col IN (...))` constraints. Option (b) is generally easier to evolve (adding a value is a metadata-only `ALTER` vs. `ALTER TYPE ... ADD VALUE` quirks with native enums inside transactions) and is the pragmatic recommendation here.
- **Migration impact:** Medium — additive `CHECK` constraints on existing columns; safe if a one-time data audit confirms no existing rows violate the proposed constraint (very likely true today given the app is the only writer so far).

---

## 7. Naming Consistency

### 7.1 — Mixed index-naming convention (`idx_*` vs `ix_*`)
- **Severity:** High
- **Why it's a problem:** `docs/02-database-schema.md` documents every index with an `idx_` prefix. In the actual code, the *one* hand-declared `Index(...)` (`idx_tx_one_active_borrow` in `transaction.py`) follows that convention — but every other index is produced by SQLAlchemy's `index=True` shorthand, which auto-generates `ix_<table>_<column>` names (e.g. `ix_equipment_status`, `ix_borrow_transactions_ward_id`). The live schema has two competing naming conventions for the same kind of object, purely as an artifact of which declaration style was used, making it harder to audit/grep indexes later and contradicting the documented scheme.
- **Proposed fix:** Set an explicit `naming_convention` on `Base.metadata` (e.g. `{"ix": "idx_%(table_name)s_%(column_0_name)s"}`) so all future auto-generated indexes match the documented `idx_` prefix, and rename the existing `ix_*` indexes in a migration to match.
- **Migration impact:** Low — index renames only (`ALTER INDEX ... RENAME TO ...`), no data impact, can be done online.

### 7.2 — `equipment_metadata` (Python) vs `metadata` (DB column) name divergence
- **Severity:** Low-Medium
- **Why it's a problem:** `mapped_column("metadata", ...)` is a necessary workaround since `metadata` collides with SQLAlchemy's reserved `Base.metadata` attribute — but it means anyone querying the raw table sees a column called `metadata`, while anyone reading the ORM model sees `equipment_metadata`. This is a footgun for hand-written SQL/BI tooling against the database.
- **Proposed fix:** Rename the physical column to something unambiguous (e.g. `custom_fields` or `extra_attributes`) so the Python attribute and DB column name match 1:1 and the reserved-word workaround disappears entirely.
- **Migration impact:** Low (`ALTER TABLE equipment RENAME COLUMN metadata TO custom_fields`), but requires updating the `mapped_column("metadata", ...)` override and any dashboards/reports that might reference the old column name.

### 7.3 — `department_owner_id` (on `equipment`) vs `department_id` (on `wards`, `borrow_transactions`) for the same conceptual FK target
- **Severity:** Low-Medium
- **Why it's a problem:** Two different naming patterns are used for "foreign key to `departments`" depending on which table it's on, with no clear semantic reason (the "_owner" qualifier isn't disambiguating from a second department relationship, since `equipment` only has one).
- **Proposed fix:** Standardize on one pattern. If "owner" vs. "current user" semantics are intentionally meaningful, name both sides explicitly (e.g. `owner_department_id` and `borrower_department_id`) rather than leaving one generic and one qualified.
- **Migration impact:** Low (column rename) if simplifying to a single consistent name.

### 7.4 — `*_by_user_id` family is consistent except one outlier
- **Severity:** Low
- **Why it's a problem:** `changed_by_user_id`, `performed_by_user_id`, `received_by_user_id`, `uploaded_by_user_id` all follow `<verb>_by_user_id`; `borrower_user_id` is a noun form instead. Minor, arguably reads more naturally as-is — flagging only for completeness.
- **Proposed fix:** Optional; rename to `borrowed_by_user_id` only if strict consistency is valued over readability. Judgment call, not a strong recommendation.
- **Migration impact:** Low if done.

---

## 8. Cascade Rules

### 8.1 — No FK in the entire schema declares an `ondelete` policy
- **Severity:** High
- **Why it's a problem:** Verified by grep — `ondelete` appears zero times across all models. Every FK relies on PostgreSQL's default (`NO ACTION`, effectively blocking the delete if referencing rows exist). This happens to be *harmless by accident* today because `Equipment` uses soft-delete and nothing in the app hard-deletes rows with dependents — but it's an implicit behavior, not a declared one, and it will surface as a confusing raw "foreign key violation" error the first time anyone (admin script, data-cleanup task, GDPR erasure request) tries to hard-delete a row that has history.
- **Proposed fix:** Declare `ondelete` explicitly everywhere based on intent (see 8.2–8.4 for the breakdown by relationship type), rather than relying on the undeclared default.
- **Migration impact:** Medium — `ondelete` changes require dropping and recreating each FK constraint; can be done as a single migration, no data loss, brief lock per table.

### 8.2 — `users` has no soft-delete column despite ~9 tables referencing it for audit/actor tracking
- **Severity:** High
- **Why it's a problem:** `borrow_transactions` (×2 columns), `equipment_status_history`, `pm_schedules`, `calibration_schedules`, `equipment_attachments`, `transaction_attachments`, `audit_logs`, `notifications` all FK into `users.id`. Unlike `Equipment`, `User` has no `SoftDeleteMixin`. Combined with 8.1, this means a user with any history literally cannot be deleted (blocked by FK), and if someone "fixes" that by adding a blanket `CASCADE`, it would silently destroy audit/compliance history — the worst possible outcome for a hospital system.
- **Proposed fix:** Add `SoftDeleteMixin` (or an `is_active`-only policy, which the schema already partially has via `users.is_active`) and treat `is_active=false` as the deactivation mechanism; never hard-delete users with history. Document this explicitly since it's currently an accidental consequence of missing `ondelete`, not a designed policy.
- **Migration impact:** Low (additive `deleted_at` column) if adopting the soft-delete pattern; zero migration if just formalizing the existing `is_active` flag as the intended mechanism.

### 8.3 — Nullable actor-reference columns should declare `ondelete='SET NULL'`
- **Severity:** Medium
- **Why it's a problem:** `changed_by_user_id`, `performed_by_user_id` (×2), `uploaded_by_user_id` (×2), `received_by_user_id` are all nullable — the nullability signals "this can lose its actor reference," but without `ondelete='SET NULL'` declared, the DB doesn't actually implement that intent; it just blocks the delete instead (per 8.1).
- **Proposed fix:** Add explicit `ondelete='SET NULL'` to these FKs to match their nullable design.
- **Migration impact:** Low, bundled with 8.1's migration.

### 8.4 — Equipment/transaction detail tables should CASCADE from their parent
- **Severity:** Medium
- **Why it's a problem:** `equipment_status_history`, `pm_schedules`, `calibration_schedules`, `equipment_attachments` (parent: `equipment`) and `transaction_attachments` (parent: `borrow_transactions`) have no independent meaning without their parent row — they're detail/child records, not independent entities. Low risk today since `Equipment` is soft-deleted in practice, but the schema doesn't express this relationship's true nature.
- **Proposed fix:** `ondelete='CASCADE'` on these specific child-to-parent FKs, while keeping `RESTRICT`/no-cascade on FKs to independent master-data/actor entities (departments, wards, locations, categories, users) where cascading deletes would be dangerous data loss.
- **Migration impact:** Low, bundled with 8.1's migration.

---

## 9. Constraints

### 9.1 — No `CHECK` constraints anywhere in the schema
- **Severity:** High (grouped finding)
- **Why it's a problem:** Confirmed via grep — zero `CheckConstraint` usage. Beyond the enum-domain gaps (§6), several other invariants that the application logically relies on are entirely unenforced at the DB level:
  - `borrow_transactions.quantity` has no `> 0` check — a 0 or negative quantity would silently corrupt utilization/report math.
  - `borrow_transactions.returned_at >= borrowed_at` and `due_at >= borrowed_at` (when not null) are not enforced — a bug could write a return timestamp earlier than the borrow timestamp, silently corrupting SLA/downtime reports that depend on this delta.
  - `pm_schedules.completed_date >= scheduled_date` / same for `calibration_schedules` — not enforced (low priority given §3.1, these tables are currently unused).
- **Proposed fix:** Add the temporal-ordering checks on `borrow_transactions` as the highest-value addition (directly protects report accuracy); add `quantity > 0`; defer the PM/CAL table checks until those tables are actually wired up.
- **Migration impact:** Medium — safe additive constraints if a one-time audit confirms no existing violating rows (expected, since the app is the sole writer today).

### 9.2 — Business-key columns (`asset_number`, `serial_number`, `qr_code_value`) are case/whitespace-sensitive unique constraints
- **Severity:** Medium
- **Why it's a problem:** These are human-typed or barcode-scanned identifiers. `"AST-0001"`, `"ast-0001"`, and `"AST-0001 "` are currently three distinct values to Postgres's plain `UNIQUE` constraint, risking accidental duplicate equipment records for what a human/scanner considers the same asset.
- **Proposed fix:** Add a functional unique index on a normalized form (e.g. `UNIQUE (UPPER(TRIM(asset_number)))`) in addition to/instead of the plain constraint, and normalize on write at the application layer.
- **Migration impact:** Medium — requires confirming no existing near-duplicates before adding the constraint.

### 9.3 — `roles.name` / `equipment_categories.name` are case-sensitive unique
- **Severity:** Low-Medium
- **Why it's a problem:** "Admin" and "admin" could coexist as two different roles — for an RBAC table specifically, an accidental near-duplicate role name is security-relevant (permission assignment confusion in the admin UI).
- **Proposed fix:** Functional unique index on `lower(name)`, or the `citext` extension for these specific columns.
- **Migration impact:** Low.

### 9.4 — `equipment_status_history` has no guard against no-op transitions (`from_status = to_status`)
- **Severity:** Low
- **Proposed fix:** Optional `CHECK (from_status IS DISTINCT FROM to_status)`.
- **Migration impact:** Low.

*(`users.email` format is correctly left unvalidated at the DB level — that belongs at the application layer. Not a finding.)*

---

## 10. Potential Performance Issues

### 10.1 — Exact `COUNT(*)` on every equipment search request
- **Severity:** High
- **Why it's a problem:** `crud/equipment.py search()` runs a full `SELECT COUNT(*) ... WHERE <filters>` on **every** search call, in addition to the separate `LIMIT`-ed row fetch — two scans per request instead of one. For an unfiltered or broad query at the documented 500k+-row target, this `COUNT(*)` is a real cost paid on every debounced keystroke-driven search, directly threatening the documented "< 300ms search" requirement more than almost any other single issue in this review.
- **Proposed fix:** Drop the exact running total in favor of a "has more" flag (the frontend already just renders `total` as a label; cursor-based UIs don't strictly need an exact count), or use `pg_class.reltuples` as an approximate count for the unfiltered case.
- **Migration impact:** None (query/application change, not schema) — flagged here because it's the single most consequential item for the system's stated scale target, even though the fix itself lives outside the schema layer.

### 10.2 — `generate_transaction_no()` uses `COUNT + LIKE` instead of a sequence
- **Severity:** Medium-High
- **Why it's a problem:** Computing "next transaction number" via `COUNT(*) WHERE transaction_no LIKE 'TX-{today}-%'` is O(n) per call (n = today's transaction count) and race-prone under concurrency (two simultaneous borrows can compute the same "next number" before either commits; correctness today only survives because the `UNIQUE` constraint rejects the loser, not because the generation logic avoids the collision).
- **Proposed fix:** Use a real PostgreSQL `SEQUENCE` (reset daily via a scheduled job, or simply not date-partitioned — a monotonic global sequence with the date embedded for display is simpler and race-free) instead of a derived `COUNT`.
- **Migration impact:** Medium — introduces a new `SEQUENCE` object and changes the number-generation code path; no impact to existing data (existing transaction numbers remain valid, just not generated the same way going forward).

### 10.3 — Random UUIDv4 primary keys undercut the documented rationale for using UUIDs
- **Severity:** Medium-High
- **Why it's a problem:** `docs/01-architecture.md` argues UUID primary keys "distribute insert load better than serial" for multi-instance writers — true for avoiding a single auto-increment bottleneck, but `uuid.uuid4()` (fully random) is actually close to worst-case for btree insert locality: each insert lands at a random point in the PK index, causing index page splits/bloat and poor buffer-cache hit rates as the table grows. This directly works against the 500k+/2M+-row performance targets in `docs/07`.
- **Proposed fix:** Switch to UUIDv7 (time-ordered) or ULID for primary keys — both remain globally unique and client-generatable without coordination (preserving the original multi-writer rationale) while keeping insert locality roughly sequential, closer to a serial key's index behavior.
- **Migration impact:** High if changing after data exists (every PK and every FK referencing it must be regenerated or the change limited to new rows going forward with a mixed-format transition period). **Recommend deciding this now, while the dataset is still small/pre-production** — it becomes significantly more expensive to change later.

### 10.4 — JSONB columns have no GIN index
- **Severity:** Low (informational only)
- **Why it's a problem:** `equipment.metadata`, `roles.permissions`, `audit_logs.before_data/after_data`, `notifications.payload` are JSONB with no GIN index — fine today since no code path queries inside them, but worth flagging so it isn't forgotten if that changes.
- **Proposed fix:** No action now (YAGNI) — add a GIN index only when a concrete query pattern into these columns exists.
- **Migration impact:** None today.

---

## Summary — Priority Order

| # | Finding | Severity | Section |
|---|---|---|---|
| 1 | Documented partial indexes (`WHERE deleted_at IS NULL`) never implemented | High | 4.1 |
| 2 | No `CHECK` constraints anywhere; status/type/condition columns fully unenforced at DB level | High | 6, 9.1 |
| 3 | No `ondelete` policy declared on any FK | High | 8.1 |
| 4 | `users` has no soft-delete despite 9 tables referencing it for audit history | High | 8.2 |
| 5 | Exact `COUNT(*)` on every equipment search request | High | 10.1 |
| 6 | `func.date(borrowed_at)` defeats index on dashboard trend query | High | 4.2 |
| 7 | Mixed `idx_*`/`ix_*` index naming convention | High | 7.1 |
| 8 | Missing indexes on `equipment.category_id`/`department_owner_id` (live search filters) | High | 3 |
| 9 | Random UUIDv4 PKs work against stated insert-scale rationale | Medium-High | 10.3 |
| 10 | `generate_transaction_no()` uses racy `COUNT`+`LIKE` instead of a sequence | Medium-High | 10.2 |
| 11 | `due_at` nullable silently excludes loans from overdue tracking | Medium-High | 5.5 |
| 12 | Remaining Medium/Low findings | — | 1, 2, 3.1, 4.3–4.6, 5.1–5.4, 7.2–7.4, 8.3–8.4, 9.2–9.4, 10.4 |

No code was modified as part of this review, per your instructions.
