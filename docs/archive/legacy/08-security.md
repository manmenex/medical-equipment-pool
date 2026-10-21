# Security Best Practices

> **Status: Legacy design reference.** Some proposals and scale targets in
> this document predate confirmed guardrails and may be superseded. Use
> `AGENTS.md`, `PROJECT_PLAYBOOK.md`, `ARCHITECTURE_DECISIONS.md`, and the
> consolidated implementation plan for current authority.

## Authentication & Authorization
- **JWT** access tokens (15 min TTL, signed HS256 with `JWT_SECRET_KEY`, rotate secret via env update) + refresh tokens (7 days, stored **httpOnly, Secure, SameSite=Strict** cookie — never in localStorage, mitigates XSS token theft)
- Refresh tokens tracked server-side (Redis, `refresh:{jti}` → user_id) so `/auth/logout` and admin-forced logout actually revoke sessions
- **RBAC**: every endpoint declares required role(s) via a FastAPI dependency (`require_roles("admin", "biomedical_engineer")`); permissions matrix in `03-api-specification.md`
- Password hashing: `bcrypt` (direct `bcrypt` package), cost factor 12
- Login rate-limited (Redis, 5 attempts / 15 min per account+IP) to blunt brute force

## Transport & Infrastructure
- **HTTPS everywhere** — Nginx terminates TLS 1.2+/1.3 only, HSTS header, redirect all HTTP→HTTPS
- Internal service-to-service traffic (backend↔postgres/redis/minio) stays on the Docker private network, never exposed publicly
- Secrets via environment variables / Docker secrets — never committed to git (`.env` is git-ignored; `.env.example` has placeholders only)

## Data Protection
- Sensitive columns (e.g. phone numbers) — access limited by role; audit log records every read of PII-heavy admin views
- Object storage (photos/signatures) served via short-lived presigned URLs, bucket not publicly listable
- Database encryption at rest via disk-level encryption (LUKS/cloud-provider EBS encryption) — application-level column encryption not required for this data classification, but structure allows adding `pgcrypto` on specific columns later if needed

## Application-layer
- All input validated by Pydantic schemas (type + length + enum constraints) — rejects malformed payloads before touching the DB
- SQLAlchemy ORM / parameterized queries only — no raw string-built SQL, eliminates SQL injection
- CORS locked to `ALLOWED_ORIGINS` allowlist (hospital domains only)
- File upload validation: MIME-type allowlist (jpeg/png/webp for photos), max size (5MB), re-encoded server-side (strips EXIF/GPS metadata, defuses embedded payloads)
- Security headers via Nginx/FastAPI middleware: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy`, `Referrer-Policy: strict-origin-when-cross-origin`

## Audit Trail
- Every create/update/delete/status-change on `equipment`, `borrow_transactions`, and `users` writes an `audit_logs` row: **who** (user_id), **what** (action, entity, before/after JSON diff), **when** (timestamptz), **from where** (IP address + user agent) — implemented as a service-layer hook, not client-trusted
- Audit log is append-only (no UPDATE/DELETE grants for the application DB role on that table)

## Dependency & Container Hygiene
- `pip-audit` / `npm audit` run in CI on every PR
- Backend/frontend Docker images built `FROM` pinned minor versions, multi-stage builds so final image has no build toolchain
- Containers run as non-root user

## Incident Response
- Structured JSON logs (request id, user id, latency, status) shipped to a log aggregator; failed-auth spikes and 5xx spikes alertable
- `audit_logs` + Postgres WAL retention give point-in-time forensic reconstruction of any data change
