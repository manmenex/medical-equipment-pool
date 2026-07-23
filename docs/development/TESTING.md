# Testing

**Purpose:** How to run this repository's backend and frontend checks locally, and what CI runs on every Pull Request.
**Authority:** Operational guide. `.github/workflows/ci.yml` is the source of truth for what actually gates merge; this document explains and mirrors it.
**Update trigger:** A test command, marker, CI job, or fixture convention changes.
**Maintainer:** Repository Owner

## Backend: two pytest suites

The backend test suite (`backend/tests/`) is split by a `postgres` marker into two independently runnable groups. Both must pass; CI runs them as two separate jobs.

### 1. Non-PostgreSQL suite (default, fast)

```bash
cd backend
source .venv/bin/activate
python -m pytest -q -m "not postgres"
```

`backend/tests/conftest.py` sets `DATABASE_URL=sqlite+aiosqlite:///:memory:` and `CACHE_ENABLED=false` via `os.environ.setdefault(...)` before the app is imported, so this requires no environment configuration and no running database. This is the suite CI's `backend-tests` job runs, and the one every Roadmap PR in this repository reports as its primary evidence.

### 2. PostgreSQL-marked suite (`tests/test_postgres_integration.py`)

SQLite does not enforce foreign key constraints by default, so it cannot exercise this backend's `IntegrityError` → domain-error SQLSTATE classification (`backend/app/core/db_errors.py`). `tests/test_postgres_integration.py` runs the same kind of assertions against a real PostgreSQL 16 database instead, and also contains the migration upgrade/downgrade/round-trip tests.

```bash
cd backend
source .venv/bin/activate
POSTGRES_TEST_DATABASE_URL="postgresql+asyncpg://mep_test:mep_test_password@localhost:5432/mep_test_db" \
    python -m pytest -q -m postgres
```

If `POSTGRES_TEST_DATABASE_URL` is unset, the suite falls back to that same default URL. Every fixture in this file calls `pytest.skip()` if PostgreSQL is unreachable or the connecting role lacks `CREATEDB` privilege (needed for the scratch-database migration round-trip tests) — by design, so this command is always safe to run locally even without PostgreSQL installed. It will simply skip.

**Setting up a local PostgreSQL matching CI's credentials:**

```bash
sudo -u postgres psql -c "CREATE ROLE mep_test WITH LOGIN PASSWORD 'mep_test_password' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE mep_test_db OWNER mep_test;"
```

`CREATEDB` is required, not optional — the migration round-trip tests create and drop scratch databases under this role.

### Running everything

```bash
cd backend
source .venv/bin/activate
python -m pytest -q
```

This runs both groups in one process (postgres-marked tests still skip individually if PostgreSQL isn't reachable).

## What CI actually runs

`.github/workflows/ci.yml` defines five jobs against every Pull Request targeting `claude/medical-equipment-pool-0c7fz0`:

| Job | What it does |
|---|---|
| `backend-tests` | `python -m pytest -q -m "not postgres"` — no external services. |
| `backend-postgres-tests` | Starts a `postgres:16-alpine` service container, runs `scripts/postgres_ci_gate.py preflight` (proves the CI database is actually reachable/authenticatable/writable — not just that the TCP port is open), then `python -m pytest -q -m postgres --junitxml=postgres-results.xml`, then `scripts/postgres_ci_gate.py assert-no-skips postgres-results.xml` (fails the build if any postgres-marked test was skipped, since a skip there means broken infrastructure, not an intentional exclusion). |
| `migrations` | `alembic upgrade head` against a fresh `postgres:16-alpine` database — proves every migration in `backend/alembic/versions/` applies cleanly and in order. See `MIGRATIONS.md`. |
| `frontend` | `npm ci && npm run build` — `package.json`'s `build` script is `tsc -b && vite build`, so this is both the TypeScript check and the production build in one command. |
| `whitespace-check` | `git diff --check` against the PR's base SHA — catches trailing whitespace and conflict markers. |

CI uses only hardcoded, non-secret, test-only credentials (see the comment block at the top of `ci.yml`); no repository secret or production configuration is required to run it.

### Fail-closed PostgreSQL gate

`backend/scripts/postgres_ci_gate.py` exists because `pg_isready` (or an equivalent basic connectivity check) only proves the PostgreSQL *process* is accepting TCP connections — it does not prove the configured credentials can authenticate, reach the configured database, or hold the `CREATEDB` privilege the migration round-trip tests depend on. Without this gate, a misconfigured CI service container could make `pytest -m postgres` report a false "0 failures" via silent `pytest.skip()` calls. The gate closes that gap with two checks: `preflight` (run before pytest) and `assert-no-skips` (run after, parsing the JUnit XML report).

## Frontend

`npm run build` (TypeScript check + Vite production build) remains the only frontend check CI runs (`.github/workflows/ci.yml`'s `frontend` job). Roadmap PR8B's frontend slice (`knowledge/adr/ADR-006-receipt-outcome-contract.md`, `docs/TECH_DEBT.md` TD-006) added a Vitest test runner (`vite.config.ts`'s `test` block, `src/test/setup.ts`), but **`npm run test` is not yet wired into CI** — run it locally before submitting a frontend change, same as `npm run lint`:

```bash
cd frontend
npm ci
npm run lint
npm run test
npm run build
```

Frontend tests use Vitest + `@testing-library/react` (jsdom environment). `src/test/setup.ts` registers `@testing-library/jest-dom`'s matchers and explicit DOM cleanup after each test (this project keeps Vitest's `globals: false`, so the library's cleanup auto-registration — which depends on detecting a global `afterEach` — is done by hand instead). Test files sit next to the module they cover (`src/services/borrow.test.ts`, `src/pages/ReturnPage.test.tsx`), not in a separate `__tests__/` tree.

## Test file conventions

- `backend/tests/conftest.py` holds the shared pytest fixtures (`db_engine`, `db_session`, `seeded_users`, `client`) used by the non-PostgreSQL suite, plus shared helper functions (`login`, `auth_headers`, `create_ward`, `on_demand_borrow_payload`) reused across multiple test modules. Prefer importing an existing helper from `conftest.py` over writing a near-duplicate in a single test file — this repository has previously accumulated (and then consolidated) several slightly-inconsistent copies of the same helper.
- `backend/tests/test_postgres_integration.py` is self-contained: it defines its own `pg_engine`/`pg_session`/`pg_seeded_users` fixtures rather than reusing the SQLite-oriented ones in `conftest.py`, because it needs a real PostgreSQL connection and its own scratch-database lifecycle for migration tests.
- `backend/tests/identifier_vectors.py` holds shared, immutable BCM Code / Item No test vectors reused by both runtime and migration regression tests, so the two never silently drift apart.
- Every test file that exercises authenticated endpoints marks its module with `pytestmark = pytest.mark.asyncio` (pytest-asyncio, async mode).
- No linter (flake8/isort/ruff/black) is currently wired into backend CI; import ordering and formatting are not machine-enforced, only reviewed.
- Frontend: a component test that renders a page depending on `react-router-dom` hooks (`useSearchParams`, etc.) wraps it in `MemoryRouter` with an explicit `initialEntries`, not the real browser router. Mock sibling components/services that are unrelated to the behavior under test (e.g. `ReturnPage.test.tsx` mocks `QRScanner`/`BcmSearchInput` — camera/debounced-search concerns — rather than exercising them incidentally).

## Reporting test evidence in a PR

Per `.github/PULL_REQUEST_TEMPLATE.md` and `docs/REVIEW_CHECKLIST.md`, always distinguish **local** evidence from **CI** evidence explicitly, and never describe a local run as CI evidence. Include the exact command and its final summary line (e.g. `273 passed, 78 deselected in ...`).
