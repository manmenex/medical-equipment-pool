# CLAUDE.md

@AGENTS.md

The file above owns every repository rule. This file only adds what Claude
Code needs to run the work locally.

## Commands

Backend (run from `backend/`):

- Install: `pip install -r requirements.txt`
- Tests (no database server): `python -m pytest -q -m "not postgres"`
- Postgres tests (need a running PostgreSQL): `python -m pytest -q -m postgres`
- Migrations: `python -m alembic upgrade head`

Frontend (run from `frontend/`):

- Install: `npm ci`
- Tests: `npm run test`
- Lint: `npm run lint`
- Build and typecheck: `npm run build`

Before finishing an implementation task, run the tests for every side the
change touches and report the real output. "Done" needs passing checks,
not a summary.

## Before a pull request

Use the `guardrail-reviewer` agent on the diff. It checks the change
against the Domain Guardrails and Scope Discipline in `AGENTS.md`. It does
not replace the Codex review in `docs/PROJECT_WORKFLOW.md`.
