# Migrations (Alembic)

**Purpose:** How schema migrations are authored, named, tested, and applied in this repository.
**Authority:** Operational guide. `docs/TECH_DEBT.md` (TD-002) remains authoritative for the `0001_initial.py` caveat described below; `docs/REPOSITORY_STRATEGY.md` remains authoritative for rollback/forward-fix policy.
**Update trigger:** The migration tooling, naming convention, or CI migration job changes.
**Maintainer:** Repository Owner

## Layout

```text
backend/alembic/
  env.py              Alembic environment — reads app.core.config.settings.DATABASE_URL
  script.py.mako       Revision template
  versions/            One file per migration, applied in dependency order
```

Current revisions (`backend/alembic/versions/`), oldest first:

| Revision | Summary |
|---|---|
| `0001_initial` | Initial schema, built from `Base.metadata.create_all()` |
| `0002_audit_request_ids` | Audit log request/correlation ID fields |
| `0003_transaction_no_seq` | Transaction number sequence |
| `0004_equipment_item_no_bcm_code` | Equipment `item_no` + `bcm_code` identifiers |
| `0005_identifier_hardening` | Nullable `qr_code_value`, canonical BCM uniqueness |
| `0006_equipment_state_model` | Four-state `EquipmentStatus` model |
| `0007_transaction_lifecycle` | OPEN/CLOSED transaction lifecycle model |
| `0008_dispatch_fields` | `dispatch_type`, `routine_round`; relaxed `borrower_name` |

Check `backend/alembic/versions/` directly for the current tip — this table is a snapshot and will fall behind as new migrations are added.

## Revision naming and chaining

- Filename and `revision` identifier: `NNNN_short_description` (four-digit zero-padded sequence number, e.g. `0009_next_change`), matching every existing revision in `versions/`.
- `down_revision` must point at the exact current tip (the highest-numbered existing revision) at the time the new migration is authored — a linear chain, no branching, consistent with the table above.
- Generate the skeleton with Alembic's own revision command rather than hand-writing the header, so `revision`/`down_revision`/`Create Date` stay consistent with `script.py.mako`:

  ```bash
  cd backend
  alembic revision -m "short description" --rev-id 0009_short_description
  ```

- Every existing migration includes a module docstring explaining *why* the change is needed and citing the Roadmap PR / ADR it implements (e.g. `0008_dispatch_fields.py` cites Roadmap PR7b and `knowledge/adr/ADR-005-transaction-model.md`). Follow the same pattern — the "why", not just the "what", since the diff already shows the what.

## Writing upgrade/downgrade

- `upgrade()` and `downgrade()` must both be implemented — do not leave `downgrade()` as `pass` for a migration that changes schema, unless the change is genuinely irreversible and that is stated explicitly in the docstring.
- Prefer additive, backward-compatible changes (new nullable column, new `CHECK` constraint on a column with a value domain already satisfied by all existing rows) over destructive ones, matching every migration merged so far (`0008_dispatch_fields`, for example, is purely additive).
- When a migration must remap or narrow existing data (see `0007_transaction_lifecycle`'s status remap), the `upgrade()` path should: preflight-check current data, perform the remap, then verify the result before adding any new constraint — and `downgrade()` should reverse each step in the opposite order.
- Some migrations guard against non-PostgreSQL dialects at the top of `downgrade()` (e.g. `0006_equipment_state_model.py` returns immediately if `bind.dialect.name != "postgresql"`) because certain constraint operations are PostgreSQL-specific and the non-PostgreSQL pytest suite runs against SQLite. Follow this pattern for any migration using PostgreSQL-specific DDL.

## The TD-002 caveat: `0001_initial.py` is not a frozen snapshot

`0001_initial.py` calls `Base.metadata.create_all()` rather than declaring an explicit, historically-frozen schema. This means:

- A **fresh** database (never migrated before, running `alembic upgrade head` from empty) gets a schema built from *today's* SQLAlchemy models via `0001`, then whatever later revisions add.
- An **existing** database that already ran `0001` in the past keeps whatever `0001` produced *at that time* — any subsequent ORM model change is only reflected there if a later revision explicitly migrates it.

This has already caused one real bug (see `docs/DECISION_LOG.md`'s "Migration 0007 schema convergence" entry: a `status` column ended up `VARCHAR(20)` on some databases and `VARCHAR(10)` on others, depending on when `0001` had run relative to an ORM model edit). **When authoring a migration, do not assume every target database's current physical schema matches what `Base.metadata` says today** — if your migration depends on a column's exact prior type/constraint, verify and normalize it explicitly (preflight-check, then fix if needed) rather than assuming `0001` already produced the current model's shape everywhere. See `docs/TECH_DEBT.md` TD-002 for the full tracked item and its resolution trigger.

## Testing a migration

Every migration needs both:

1. **CI's fresh-database upgrade check** (`migrations` job in `.github/workflows/ci.yml`): `alembic upgrade head` against a brand-new `postgres:16-alpine` database, proving the full chain applies cleanly in order. This does not test `downgrade()` or any non-trivial data remap.
2. **A dedicated round-trip test in `backend/tests/test_postgres_integration.py`** (`pytest -m postgres`): upgrade to the new revision, assert the resulting schema/data, downgrade, assert the prior state is restored. Follow the pattern of the existing migration tests in that file — they use a real scratch PostgreSQL database (via `_recreate_scratch_database`/`_drop_scratch_database` helpers) so `CREATEDB` privilege is required for the connecting role (see `TESTING.md`'s local PostgreSQL setup).

Run both locally before opening a PR:

```bash
cd backend
source .venv/bin/activate

# Fresh-database upgrade check (mirrors CI's migrations job)
DATABASE_URL="postgresql+asyncpg://mep_test:mep_test_password@localhost:5432/<a-fresh-db>" \
    python -m alembic upgrade head

# Migration round-trip tests
POSTGRES_TEST_DATABASE_URL="postgresql+asyncpg://mep_test:mep_test_password@localhost:5432/mep_test_db" \
    python -m pytest -q -m postgres
```

## Applying migrations

- **Docker Compose:** `docker compose exec backend alembic upgrade head` (see `SETUP.md`).
- **Direct/local:** `cd backend && alembic upgrade head`, with `DATABASE_URL` pointing at the target database (`backend/app/core/config.py`'s default, or an override).
- Alembic reads `settings.DATABASE_URL` (see `backend/alembic/env.py`) — there is no separate hardcoded connection string in the migration tooling itself.

## Rollback

Migration-specific rollback is `alembic downgrade <target-revision>`, but treat this as a last resort in a running environment with real data — see `docs/REPOSITORY_STRATEGY.md`'s Rollback flow for the full process (stop further deploys, identify the known-good commit/migration, protect data before changing schema, verify afterward). A forward-fix migration is usually safer than downgrading a production database.
