# Medical Equipment Pool

Browser/PWA application for hospital Equipment Pool operators to dispatch
pool-owned equipment to a first receiving ward and record its receipt. The
system uses a React/TypeScript frontend, FastAPI backend, and PostgreSQL system
of record.

This project does **not** track patients, beds, later ward transfers, cleaning,
PM, calibration, recalls, or the hospital-wide asset lifecycle. See
[`AGENTS.md`](AGENTS.md) for permanent guardrails.

## Start here

- [`docs/PROJECT_PLAYBOOK.md`](docs/PROJECT_PLAYBOOK.md) — compact governance
  entry point, authority hierarchy, roles, workflow, and task reading sets
- [`docs/HOSPITAL_DOMAIN_MODEL.md`](docs/HOSPITAL_DOMAIN_MODEL.md) — confirmed
  terminology and current/future workflow boundary
- [`docs/ROADMAP_STATUS.md`](docs/ROADMAP_STATUS.md) — current Roadmap status
- [`docs/audits/04-consolidated-implementation-plan.md`](docs/audits/04-consolidated-implementation-plan.md)
  — authoritative Roadmap PR scope and order

Legacy design documents under `docs/01-...` through `docs/10-...` are retained
for reference and history. They may describe proposals superseded by current
guardrails and are not governance authority.

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
