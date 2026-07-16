# Deployment Guide

## 1. Prerequisites
- Docker Engine 24+ and Docker Compose v2
- A server/VM with ≥ 4 vCPU, 8GB RAM for ~100 concurrent users (scale horizontally beyond that)
- Domain + TLS certificate (or use `certbot` container / hospital's internal CA)

## 2. Local Development

```bash
cp .env.example .env          # edit secrets (DB password, JWT secret, etc.)
docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed   # demo data (optional)
```

- Backend: http://localhost:8000/api/docs (Swagger)
- Frontend: http://localhost:5173 (Vite dev server) or http://localhost (via nginx in compose)

## 3. Production Deployment

```bash
cp .env.example .env.prod      # set strong secrets, real DB creds, ALLOWED_ORIGINS, etc.
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose exec backend alembic upgrade head
```

`docker-compose.prod.yml` overrides:
- `backend` scaled to N replicas (`deploy.replicas` or manual `docker compose up --scale backend=3`)
- Nginx configured with TLS (mount cert files) and upstream load-balance across backend replicas
- Postgres volume on durable storage; enable `wal_level=replica` if adding a read replica later
- Redis with `appendonly yes` for durability of rate-limit/session data (cache data itself is safely rebuildable)

## 4. Environment Variables (see `.env.example`)

| Variable | Description |
|---|---|
| `POSTGRES_*` | DB name/user/password/host/port |
| `REDIS_URL` | e.g. `redis://redis:6379/0` |
| `JWT_SECRET_KEY` | random 64-byte secret, rotate periodically |
| `JWT_ACCESS_EXPIRE_MINUTES` / `JWT_REFRESH_EXPIRE_DAYS` | token lifetimes |
| `ALLOWED_ORIGINS` | CORS whitelist, comma-separated |
| `S3_ENDPOINT` / `S3_BUCKET` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | object storage for photos/signatures |
| `SMTP_*` | outbound email for notifications |
| `ENVIRONMENT` | `development` \| `staging` \| `production` |

## 5. Database Backup

```bash
docker compose exec postgres pg_dump -U mep_user mep_db | gzip > backup_$(date +%F).sql.gz
# restore:
gunzip -c backup_2026-07-16.sql.gz | docker compose exec -T postgres psql -U mep_user mep_db
```
Schedule nightly via host cron; retain 30 days on-site + weekly off-site copy.

## 6. Zero-downtime Migration Rollout

1. Alembic migrations must be backward-compatible with the currently-running backend version (additive columns/tables first)
2. `docker compose up -d --build backend` — Compose replaces containers one at a time when `deploy.update_config` is set, or run `docker compose up -d --no-deps --build backend` per replica manually
3. Run `alembic upgrade head` once (idempotent, safe to run before or after new containers are up for additive changes)

## 7. Health Checks

- `GET /api/v1/health` → `{status: "ok", db: "ok", redis: "ok"}` — wired into Docker `HEALTHCHECK` and Nginx upstream checks
- `docker compose ps` should show all services `healthy`

## 8. Scaling Checklist (as data/users grow)

| Trigger | Action |
|---|---|
| > 100 concurrent users | add backend replicas, put PgBouncer in front of Postgres |
| > 1M borrow_transactions rows | enable monthly partitioning (migration provided in `alembic/versions/`, currently no-op until invoked) |
| Read-heavy dashboard load | add Postgres read replica, point `/dashboard/*` reads at it |
| Multi-site hospital network | move to Kubernetes, externalize Redis/Postgres to managed services |
