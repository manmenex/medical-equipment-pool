# Performance Optimization

> **Status: Legacy design reference.** Some proposals and scale targets in
> this document predate confirmed guardrails and may be superseded. Use
> `AGENTS.md`, `PROJECT_PLAYBOOK.md`, `ARCHITECTURE_DECISIONS.md`, and the
> consolidated implementation plan for current authority.

## Frontend
- **Code-splitting** per route (`React.lazy` + Vite dynamic import) → first paint only ships Login/Dashboard bundle
- **Virtualized lists** (`@tanstack/react-virtual`) for Equipment List → renders only visible rows even at 500k+ records
- **Debounced search** (150ms) + **AbortController** cancels stale in-flight requests when user keeps typing
- **Service Worker precache** of app shell (Workbox `generateSW`) → repeat loads and offline both serve instantly from cache
- **Optimistic UI**: Borrow/Return buttons update local state immediately, reconcile with server response, roll back on error — perceived latency ~0ms
- **Image optimization**: photos captured client-side are resized/compressed (canvas, max 1280px, WebP) before upload
- **HTTP/2 + Brotli** via Nginx, long-lived `Cache-Control: immutable` on hashed static assets

## Backend
- **Async I/O everywhere** (FastAPI + asyncpg) → one worker process handles thousands of concurrent waiting connections without blocking threads
- **Connection pooling**: SQLAlchemy async pool (`pool_size=20, max_overflow=10` per instance) + optional PgBouncer in transaction-pooling mode in front of Postgres for > 100 concurrent users
- **Redis cache-aside** for hot reads: dashboard summary (15s TTL), equipment search results (30s TTL keyed by normalized query+filters), invalidated immediately on writes via Pub/Sub
- **Cursor pagination** everywhere — never `OFFSET` on large tables (avoids O(n) scan cost growing with page depth)
- **Selective columns**: list endpoints return a lean DTO (no full history/joins); detail endpoint loads relations only on demand
- **Batch writes**: bulk import/seed uses `COPY`/`executemany`, not row-by-row ORM inserts

## Database
- Targeted indexes for every query pattern (see `02-database-schema.md §6`)
- `pg_trgm` GIN indexes make `ILIKE '%term%'` searches index-backed instead of sequential scans
- Partial indexes (`WHERE deleted_at IS NULL`, `WHERE status='open'`) keep index size small and fast
- `EXPLAIN ANALYZE` reviewed for the 5 hottest queries (search, dashboard summary, active-borrow lookup, PM/CAL due list, transaction history) before each release
- Monthly partitioning plan for `borrow_transactions` ready to activate once volume passes ~1M rows, keeping recent-month queries fast regardless of historical size
- `autovacuum` tuned (lower scale factor) on high-churn tables (`equipment`, `borrow_transactions`)

## Caching Strategy Summary

| Data | Store | TTL | Invalidation |
|---|---|---|---|
| Dashboard summary | Redis | 15s | passive expiry (cheap to recompute) |
| Equipment search results | Redis | 30s | passive expiry + explicit purge on equipment write |
| Equipment detail | Redis | 60s | explicit purge on update/status change |
| JWT blocklist / session | Redis | token TTL | explicit on logout |
| Static assets | Browser + Nginx | 1y (hashed filenames) | new deploy = new hash |
| App shell | Service Worker | until new SW version | `skipWaiting` + `clientsClaim` on deploy |

## Load Testing Targets (k6 / Locust)

| Scenario | Target |
|---|---|
| 100 concurrent users browsing + searching | p95 search latency < 300ms |
| 100 concurrent users, 10 borrow/return per minute each | p95 write latency < 1s, zero double-borrow violations |
| Cold home-page load, empty cache | < 1s to interactive on 4G |
| 500,000 equipment rows, 2M transactions seeded | search and dashboard still meet above targets |
