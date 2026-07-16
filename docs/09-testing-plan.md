# Testing Plan

## Levels

| Level | Scope | Tooling |
|---|---|---|
| Unit | services/ business logic (borrow rules, status transitions, PM/CAL due calc) in isolation | pytest, pytest-asyncio |
| Integration | API endpoints against a real Postgres (testcontainers or docker-compose test profile) | pytest + httpx.AsyncClient |
| Contract | OpenAPI schema snapshot — fails CI if a breaking change ships unversioned | schemathesis / openapi-spec-validator |
| Frontend unit | components, hooks, store logic | Vitest + React Testing Library |
| E2E | full user flows: login → search → borrow → return; offline borrow → reconnect → sync | Playwright |
| Load | concurrency + latency targets from `07-performance-optimization.md` | k6 |
| Security | dependency scan, basic OWASP checks (authz bypass attempts, SQLi/XSS fuzz on inputs) | pip-audit, npm audit, OWASP ZAP baseline scan |

## Critical Test Cases (must-pass before release)

1. **Double-borrow race**: two concurrent `POST /borrow` for the same equipment → exactly one succeeds (DB unique partial index), the other gets `409 EQUIPMENT_NOT_AVAILABLE`
2. **Borrow blocked when not Available**: attempting to borrow equipment in `repair`/`pm`/`calibration`/`out_of_service`/`lost` status is rejected with a clear error before any DB write
3. **Return updates status correctly** for each selected condition (Available/Cleaning/PM/Calibration/Repair) and stamps `returned_at` server-side regardless of client clock
4. **RBAC enforcement**: Viewer role gets `403` on all mutating endpoints; Ward Nurse cannot access `/admin/users`
5. **Search performance**: seeded 500k equipment rows, `GET /equipment?q=...` p95 < 300ms
6. **Pagination correctness**: no duplicate/skipped rows across cursor pages under concurrent inserts
7. **Offline flow**: borrow submitted while offline queues locally, syncs automatically on reconnect, and surfaces a conflict UI if the equipment was borrowed by someone else in the meantime
8. **Audit log completeness**: every mutating endpoint produces exactly one audit row with correct before/after diff
9. **JWT expiry & refresh**: expired access token auto-refreshes transparently; revoked refresh token cannot mint new access tokens
10. **QR resolution**: scanning a QR for a non-existent/deleted asset returns a clear not-found error, not a crash

## CI Pipeline (suggested)

```
lint (ruff/eslint) → unit tests → build → integration tests (docker-compose test stack) → e2e (Playwright, headless) → security scan → build+push images
```

## Test Data

`backend/app/scripts/seed.py` generates configurable synthetic volume (`--equipment 500000 --transactions 2000000`) for realistic performance testing without production PHI/PII.
