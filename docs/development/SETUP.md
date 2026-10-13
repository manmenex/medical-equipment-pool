# Developer Setup

**Purpose:** Get a clean checkout running locally — full Docker stack, or backend/frontend run directly for fast iteration.
**Authority:** Operational guide. Does not redefine Git/PR process (`docs/REPOSITORY_STRATEGY.md`, `CONTRIBUTING.md`), the review workflow (`docs/PROJECT_WORKFLOW.md`), or test/migration mechanics (`TESTING.md`, `MIGRATIONS.md`) — it only gets a machine ready to use them.
**Update trigger:** A prerequisite, environment variable, or startup command changes.
**Maintainer:** Repository Owner

## Prerequisites

| Tool | Version used by this repository | Where it's pinned |
|---|---|---|
| Docker + Docker Compose | Any recent version supporting the Compose v2 CLI | `docker-compose.yml` |
| Python | 3.12 | `.github/workflows/ci.yml` (`PYTHON_VERSION`), `backend/Dockerfile` |
| Node.js | 22 | `.github/workflows/ci.yml` (`NODE_VERSION`) |
| PostgreSQL | 16 | `docker-compose.yml` (`postgres:16-alpine`), `.github/workflows/ci.yml` service containers |

You do not need Python/Node/PostgreSQL installed locally if you only run the app through Docker Compose. You do need a local Python 3.12 environment and a local PostgreSQL 16 instance to run the backend test suite directly (see `TESTING.md`) or to iterate on the backend without rebuilding a container each time.

## Option A — full stack via Docker Compose

This is the path documented in the repository root `README.md` and is the fastest way to get every service (backend, frontend, PostgreSQL, Redis, MinIO) running together.

```bash
cp .env.example .env
# Edit .env with development-only values. Never commit a real .env file
# or production credentials — see .env.example's own header comment.
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

- Backend API docs (Swagger UI): `http://localhost:8000/api/docs`
- Frontend (through the Compose-built Nginx image): `http://localhost`

`docker-compose.yml` defines four services plus the backend:

| Service | Purpose | Local port |
|---|---|---|
| `postgres` | System-of-record database (PostgreSQL 16) | 5432 |
| `redis` | Cache backend (`REDIS_URL`, `CACHE_ENABLED`) | 6379 |
| `minio` | S3-compatible object storage for attachments | 9000 (API), 9001 (console) |
| `backend` | FastAPI app, built from `backend/Dockerfile` | 8000 |
| `frontend` | React/Vite PWA, built and served via Nginx | 80 |

`docker-compose.prod.yml` is the production-oriented Compose file; local development should use the plain `docker-compose.yml` shown above unless a task explicitly asks you to exercise the production configuration.

## Option B — run backend/frontend directly (faster iteration)

Useful when you're actively editing backend or frontend code and don't want a full image rebuild per change. Requires a database — either point at the Compose-managed `postgres` service (`docker compose up -d postgres`) or a local PostgreSQL 16 instance.

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# DATABASE_URL defaults to postgresql+asyncpg://mep_user:mep_password@localhost:5432/mep_db
# (see backend/app/core/config.py); override via .env or an exported env var
# if your local PostgreSQL uses different credentials.
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend:**

```bash
cd frontend
npm ci
npm run dev
```

## Environment variables

`backend/app/core/config.py` defines the full set via `pydantic-settings`, reading from `backend/.env` (`env_file=".env"`) with process environment variables taking precedence. `.env.example` at the repository root documents the Compose-oriented values; the table below is the authoritative current field list (see `config.py` for defaults):

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development` or `production` only — anything else fails startup (`validate_production_secrets`) |
| `DATABASE_URL` | SQLAlchemy async URL, e.g. `postgresql+asyncpg://user:pass@host:5432/db` |
| `REDIS_URL`, `CACHE_ENABLED` | Cache backend and on/off switch |
| `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_ACCESS_EXPIRE_MINUTES`, `JWT_REFRESH_EXPIRE_DAYS` | Auth token signing/expiry. In production, a missing, default, or too-short (`<32` chars) `JWT_SECRET_KEY` aborts startup. |
| `ALLOWED_ORIGINS` | Comma-separated CORS allow-list |
| `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Attachment object storage (MinIO locally) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFICATION_FROM_EMAIL` | Notification email (Phase 2 — not yet wired into a running feature) |
| `PM_DUE_SOON_DAYS`, `CAL_DUE_SOON_DAYS` | Due-soon thresholds for future PM/calibration reporting |

Never commit a populated `.env` file or a real secret to the repository.

## Verifying the setup

- Backend: `GET http://localhost:8000/api/docs` should render Swagger UI.
- Frontend: `http://localhost` (Docker) or the Vite dev server URL printed by `npm run dev` should load the app shell.
- Database: `alembic upgrade head` (from `backend/`) should complete without error against whichever `DATABASE_URL` is active.

For running the automated test suite, see `TESTING.md`. For migration authoring/rollback conventions, see `MIGRATIONS.md`.
