# Medical Equipment Pool

Browser/PWA application for hospital Equipment Pool operators to dispatch
pool-owned equipment to a first receiving ward and record its receipt. The
system uses a React/TypeScript frontend, FastAPI backend, and PostgreSQL system
of record.

This project does **not** track patients, beds, later ward transfers, cleaning,
PM, calibration, recalls, or the hospital-wide asset lifecycle. See
[`AGENTS.md`](AGENTS.md) for permanent guardrails.

## Start here

1. [`docs/OVERVIEW.md`](docs/OVERVIEW.md) — what the system is, what it does
   and does not do, and where the project stands (non-technical, Thai)
2. [`docs/ROADMAP.md`](docs/ROADMAP.md) — single source of project status,
   baseline, and PR ordering
3. [`AGENTS.md`](AGENTS.md) — permanent guardrails and rules for contributors
   and AI agents

Then, as needed:

- [`docs/PROJECT_PLAYBOOK.md`](docs/PROJECT_PLAYBOOK.md) — authority hierarchy,
  roles, and task reading sets
- [`docs/PROJECT_WORKFLOW.md`](docs/PROJECT_WORKFLOW.md) — requirement-to-merge
  pipeline and agent team
- [`docs/HOSPITAL_DOMAIN_MODEL.md`](docs/HOSPITAL_DOMAIN_MODEL.md) — confirmed
  terminology and current/future workflow boundary
- [`docs/audits/04-consolidated-implementation-plan.md`](docs/audits/04-consolidated-implementation-plan.md)
  — authoritative Roadmap PR scope and order

Superseded design documents are kept under `docs/archive/` as historical
evidence only. They may describe proposals superseded by current guardrails
and are not governance authority.

## Repository layout

```text
backend/    FastAPI, SQLAlchemy, Alembic, pytest
frontend/   React, TypeScript, Vite PWA
docs/       governance, domain, Roadmap, decisions, prompts, and historical audits
.github/    Pull Request and issue templates
```

## Local development

Use development-only values derived from `.env.example`; never commit a real
`.env` file or credentials.

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

- Backend API documentation: `http://localhost:8000/api/docs`
- Frontend through the local Compose stack: `http://localhost`

Exact environment/test commands and supported behavior should be verified
against current code and the assigned task. Local Docker state is not CI or
production evidence.

## Governance and contribution

- Follow [`docs/REPOSITORY_STRATEGY.md`](docs/REPOSITORY_STRATEGY.md) for
  branches, Draft PRs, merge, retention, tags, releases, and rollback.
- Follow [`docs/DEFINITION_OF_DONE.md`](docs/DEFINITION_OF_DONE.md) for
  risk-appropriate completion evidence.
- Use [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)
  and compact task prompts under [`docs/prompts/tasks/`](docs/prompts/tasks/).

No license has been granted in this repository; treat it as internal project
material unless the Repository Owner states otherwise.
