# Roadmap PR24 — Production Deployment & Go-Live Architecture Planning

**Status:** DESIGN COMPLETE; PR24B (DEPLOYMENT FOUNDATION) COMPLETE;
PR24C (BACKUP & RESTORE) COMPLETE; PR24D (CI/CD & STAGING) CODE/TOOLING
COMPLETE, MERGED — OPERATIONAL STAGING EVIDENCE PENDING (see below).
No production infrastructure is provisioned, no cloud account, paid
resource, domain, or DNS record is created, by this document, the
Owner Decision Closure round, PR24B, PR24C, or PR24D. No Pilot or
Production execution has occurred. **PR24 (this document) is merged**
(GitHub PR #129, squash SHA `599478992de363e1eda2fe8005ff79d565dee76d`,
including Fix Round 1's §15A liveness/readiness contract). **The PR24
Owner Decision Closure round is also merged** (GitHub PR #130, squash
SHA `f64f7d148ba956adef43c5d363ad52680398541c`) — all six Owner
Decisions (OD-PR24-1 through OD-PR24-6, §28) are Owner-approved.
**PR24B (Deployment Foundation) is merged** (GitHub PR #131, squash SHA
`d4a40349f62d76d129dcc6f1feea3e7e8fc8f28d`), implementing the
fail-closed readiness endpoint (§15A), the production-safe admin
bootstrap script (§17), the scheduler single-instance deployment
invariant (§15), and fail-closed production configuration checks
(§16). **PR24C (Backup & Restore) is merged** (GitHub PR #132, squash
SHA `cd9764ef5ba5e56062ee41266c8d96e50f1152c0`), implementing the
`pg_dump`/`pg_restore`/prune tooling and operator runbook designed in
§11 — proven via a real round trip against ephemeral CI-provisioned
PostgreSQL, not yet a real Staging-class rehearsal. **PR24D (CI/CD &
Staging) is merged and code/tooling-complete** (GitHub PR #133, squash
SHA `84144f096aacb9e2687422c7cd84cc1354346aa7`), implementing the
immutable-artifact build/scan/migrate/deploy/verify mechanism designed
in §18, including two independent-review fix rounds (CRITICAL image
scan hardened into a structural pre-migration gate with digest-pinned
immutable artifact identity; a `workflow_dispatch` input
shell-injection path closed) — see §29 for exact scope and what remains
explicitly out of it (PR24E onward, real infrastructure provisioning,
and provider selection). **Operational Staging evidence remains
pending: the manual `cd-staging.yml` workflow has not yet been
executed even once, no hosting provider has been selected, no real
persistent Staging environment exists, and the real PR24C
backup/restore rehearsal has not yet been performed.**

**Baseline (PR24D — CI/CD & Staging):**
`84144f096aacb9e2687422c7cd84cc1354346aa7` — the real squash-merge SHA
of GitHub PR #133 (PR24D — CI/CD & Staging). **Roadmap PR23 (Cutover
Readiness) is fully implementation-complete; PR24's own architecture,
all six Owner Decisions, PR24B, PR24C, and PR24D's code/tooling are
complete**, as of this baseline. Real Pilot execution, Production
cutover, AppSheet's actual read-only transition, a selected commercial
provider, a rehearsed backup/restore procedure, a real Staging
environment, and even a single manual execution of `cd-staging.yml`
have **not** occurred — PR24D built the CD mechanism and proved it
against an ephemeral, CI-provisioned target only; it does not provision
real infrastructure, select a provider, or create any paid resource.
PR24E (UAT Readiness) remains not started, gated on real Staging
availability and sufficient operational deployment/backup evidence.

**Prior baseline (PR24C — Backup & Restore):**
`cd9764ef5ba5e56062ee41266c8d96e50f1152c0` — the real squash-merge SHA
of GitHub PR #132 (PR24C — Backup & Restore), now historical/
superseded by the baseline above.

**Prior baseline (PR24B — Deployment Foundation):**
`d4a40349f62d76d129dcc6f1feea3e7e8fc8f28d` — the real squash-merge SHA
of GitHub PR #131 (PR24B — Deployment Foundation), now historical/
superseded by the baseline above.

**Earlier baseline (PR24B — Deployment Foundation):**
`f64f7d148ba956adef43c5d363ad52680398541c` — the real squash-merge SHA
of GitHub PR #130 (PR24 Owner Decision Closure), now historical/superseded.

**Earliest baseline (Owner Decision Closure round):**
`599478992de363e1eda2fe8005ff79d565dee76d` — the real squash-merge SHA
of GitHub PR #129 (PR24 — Production Deployment & Go-Live Architecture
Planning, including Fix Round 1), now historical/superseded.

**Purpose:** Design the production deployment and go-live architecture
needed to move this repository from "the PR23 cutover-readiness
*capability* exists" to "the system can safely enter UAT, Pilot, and
eventually Production." This document answers *what* the production
architecture should look like and *what remains an Owner Decision* — it
does not provision anything.

---

## 1. Repository Authority Check

### 1.1 Is Roadmap PR24 already formally defined?

**Partially.** `docs/audits/04-consolidated-implementation-plan.md`
Part D names it explicitly:

> #### PR24 — Go-live / deployment
> - **Objective:** Perform approved production deployment and cutover.
> - **Dependencies:** PR23. Legacy migration and reconciliation are
>   mandatory before this work begins.

This is a **one-line placeholder** — a title, a one-sentence objective,
and a dependency, with **no architecture, no scope decomposition, no
acceptance criteria, and no implementation slices**. `docs/ROADMAP.md`'s
own Completed table already carries a matching row: `"PR24 | Go-live /
deployment, blocked by PR19–PR23"` — now unblocked at the dependency
level (PR19–PR23 are all complete), but with the same lack of internal
detail.

This is architecturally identical to the situation `docs/design/
PR23_CUTOVER_READINESS_PLAN.md` (PR23A) resolved for "PR23 — Cutover
Readiness" before any PR23 implementation began: a named-but-undesigned
Roadmap item. This document plays the same role for PR24 that PR23A
played for PR23 — it is the architecture/Owner-Decision round that a
later implementation slice sequence can be scoped against, **not an
implementation itself.**

### 1.2 What this means for this round

Per repository precedent (`docs/design/PR23_CUTOVER_READINESS_PLAN.md`
§27's own governing pattern) and the task's own explicit instruction:
no PR24 implementation slice may begin until the architecture
decisions this document raises are Owner-resolved. This document is
numbered `PR24_...` because PR24 already exists as a named, dependency-
satisfied Roadmap item in repository authority — this is not a
prematurely invented number; it is the same "write the architecture
document under the already-named Roadmap item" pattern PR23A used.

---

## 2. Governance Sync — PR23F Merge

This is the first legitimate governance touch after GitHub PR #128's
merge (the real squash SHA, `f35fe716d57c51042d86a661657f679799b6a9e3`,
was only knowable after that merge completed — per this repository's
standing process, no separate self-referential "baseline adoption" PR
is created for it). This planning round folds that sync in:

- **Baseline at the time this PR24 planning round began (historical):**
  `f35fe716d57c51042d86a661657f679799b6a9e3` (GitHub PR #128, PR23F).
  The repository's current authoritative baseline is now
  `84144f096aacb9e2687422c7cd84cc1354346aa7` (GitHub PR #133, PR24D —
  CI/CD & Staging) — see `docs/ROADMAP.md`'s "Current baseline" section
  for the live value, which has advanced multiple times since this
  planning round (PR24 Owner Decision Closure, PR24B, PR24C, PR24D).
- **PR23A–PR23F:** merged and complete.
- **Roadmap PR23:** implementation complete.
- **Pilot:** **not executed.**
- **Production cutover:** **not executed.**
- **AppSheet operational read-only transition:** **not yet executed.**
- **Production deployment target:** **not selected** (this document's
  own §6/§28 raises the Owner Decision to select one).
- **Backup/restore rehearsal:** **not yet completed** (this document's
  §10 designs what rehearsal must prove; it does not perform it).
- **UAT/Pilot/Production sign-off:** **not yet obtained.**

See §29 (Governance Files Updated) for the exact files this sync
touches.

---

## 3. Objective of This Planning Round

Move the repository's documented, reviewable state from "PR23
cutover-readiness capability exists" to "the system can safely enter
UAT, Pilot, and eventually Production" — by designing the production
deployment architecture first, before any infrastructure exists.

**Explicitly not in scope for this document:** provisioning any real
infrastructure, creating any credential, registering any DNS record,
mutating any cloud account, or writing any deployment automation code.
Those are implementation-slice concerns for after the Owner Decisions
below are resolved.

**Design order preserved, per this repository's own established
discipline:** Business Workflow → API/application requirements →
Deployment architecture → Operational rollout. Technology is chosen to
serve the confirmed business/operational constraints (§4), not for its
own convenience.

---

## 4. Business / Operational Constraints

Restated from the task's own framing and cross-checked against
repository authority (`docs/ARCHITECTURE_DECISIONS.md`):

- Hospital staff use browsers only — the application is already
  **browser/PWA-based by confirmed architecture decision**
  (`docs/ARCHITECTURE_DECISIONS.md`, "Browser-first application",
  "Progressive Web App direction") specifically so it can be reached
  over HTTPS without installing software on any client machine. This
  constraint is already satisfied by the existing frontend; production
  deployment must not regress it (no native app requirement, no client
  agent).
- **Production must not assume direct/privileged access to a
  hospital-managed server** (`docs/ARCHITECTURE_DECISIONS.md`, "Managed
  deployment preferred" — a confirmed constraint, not new to this
  document).
- PostgreSQL remains the system of record (unchanged — no
  architecture in this document questions this).
- FastAPI backend, React/Vite frontend — unchanged, no redesign
  proposed anywhere in this document (§34).
- Approximately 8 initial staff users, with the expectation that
  future growth (additional wards, more Equipment Pool staff) must
  remain supportable without a re-architecture.
- The system holds operational medical-equipment data (inventory,
  dispatch/receipt transactions) — **no patient tracking, no PHI**
  (`docs/ARCHITECTURE_DECISIONS.md`, "No patient tracking" — confirmed,
  unchanged).
- The existing hospital QR / Item Number identity model is unchanged
  (§33).

**Consequence for architecture selection:** a small, predictable,
low-maintenance production footprint is more valuable here than
horizontal scalability headroom the current user count does not need.
Simplicity is preferred over hyperscale capability (§6, §31).

---

## 5. Current Deployment State (as-built, inspected at this baseline)

Before comparing options, this is what already exists in the
repository, verified directly against source, not assumed:

- **`docker-compose.yml`** — development-only compose file: Postgres
  16, Redis 7, MinIO, backend (`uvicorn`), frontend (`nginx`), all with
  host-mapped ports and default/placeholder credentials. Explicitly a
  development convenience, not a production target
  (`docs/ARCHITECTURE_DECISIONS.md`, "Managed deployment preferred").
- **`docker-compose.prod.yml`** — a **partial** production overlay
  already exists in this repository: `backend` replicas=3, no exposed
  backend port (frontend/nginx fronts it), `postgres`/`redis` ports
  closed, Redis persisted with `appendonly yes`, frontend exposes
  443/80 with a certs volume mount. **Its own top comment states the
  shipped `frontend/nginx.conf` only terminates plain HTTP — a TLS
  server block must be added before this overlay is usable.** This
  overlay is evidence of prior intent toward a VPS/self-managed-Docker
  deployment class (§6, Option B), but was never completed, never
  rehearsed, and is not itself a decision this document treats as
  binding.
- **`backend/Dockerfile`** — multi-stage-free Python 3.12-slim image,
  filters test-only dependencies (`aiosqlite`, `pytest`, etc.) out of
  the production install, runs as a non-root `appuser`, ships a
  `HEALTHCHECK` against `GET /api/v1/health`, starts
  `uvicorn app.main:app --workers 2`.
- **`frontend/Dockerfile`** — Node 22 build stage → `nginx:1.27-alpine`
  runtime, serves the Vite production build as static files.
- **`frontend/nginx.conf`** — HTTP only (port 80), gzip, cache headers
  for `/assets/`, `X-Content-Type-Options`/`X-Frame-Options`/
  `Referrer-Policy` security headers, and a same-origin reverse proxy
  from `/api/` to the backend container — meaning frontend and backend
  are already designed to be served from **one origin**, avoiding a
  cross-origin CORS requirement in production if co-located behind one
  edge.
- **`backend/app/core/config.py`** — `Settings` (pydantic-settings)
  already has a **fail-closed production-secret guard**
  (`validate_production_secrets`): refuses to boot with
  `ENVIRONMENT=production` if `JWT_SECRET_KEY` is unset, is the
  publicly-documented default value, or is under 32 characters. This
  is a genuine, already-implemented safety net this document relies on
  rather than re-designs.
- **`GET /api/v1/health`** (`backend/app/api/v1/health.py`) — already
  exists, unauthenticated, checks both `SELECT 1` against the database
  and a Redis `PING`, returning `{"status": "ok", "db": ..., "redis":
  ...}` in the response body. **Confirmed by inspection: this endpoint
  always returns HTTP 200, even when the `db` or `redis` field in its
  own body reports `"error"`** — the route never sets a non-2xx status
  code based on the dependency checks it performs. It is suitable as a
  **liveness** signal (the process is up and serving HTTP) and as a
  **diagnostic** endpoint (a human or dashboard can read the body), but
  it is **not, by itself, a safe status-code-only production readiness
  probe** — see §15A (Liveness vs. Readiness) for what this requires
  before it is used to gate production traffic routing.
- **Object storage (MinIO/S3):** `S3_ENDPOINT`/`S3_BUCKET`/
  `S3_ACCESS_KEY`/`S3_SECRET_KEY` are declared in `Settings` and in
  `docker-compose.yml`'s `minio` service, **but a repository-wide
  search found zero actual runtime usage** — no `boto3`/`minio`/S3
  client import anywhere in `backend/app`, and no dependency on any S3
  SDK in `backend/requirements.txt`. The actual persisted-file
  mechanism (`ImportSourceBlob.content`, `backend/app/models/
  import_session.py`) stores upload content directly in PostgreSQL as
  `LargeBinary` (`BYTEA`). **MinIO/S3 is vestigial configuration with
  no genuine production dependency** (§11).
- **Redis:** genuinely used, but for two **non-critical, fail-open**
  purposes only (`backend/app/core/redis.py`): (1) an optional response
  cache (`cache_get`/`cache_set`, gated by `CACHE_ENABLED`, silently
  returns/no-ops on any Redis error); (2) refresh-token storage and
  revocation (`store_refresh_token`/`revoke_refresh_token`/
  `is_refresh_token_valid`) — **`is_refresh_token_valid` explicitly
  fails *open*** (treats a token as valid) if Redis is unreachable, so
  application availability never depends on Redis, but **refresh-token
  revocation silently stops working** if Redis is down or absent (§12).
- **In-process scheduler:** `backend/app/worker/scheduler.py` starts an
  `AsyncIOScheduler` inside the FastAPI process lifespan
  (`app/main.py`'s `lifespan`), running a daily 06:00 cron
  (`check_pm_cal_due`) that creates `Notification` rows for
  PM/calibration-due equipment. **There is no leader-election or
  single-instance guard** — every process that boots the app starts its
  own scheduler instance. Combined with the Dockerfile's
  `--workers 2` and `docker-compose.prod.yml`'s `replicas: 3`, a
  literal deployment of that overlay would run this job **up to 6
  times** at 06:00, creating duplicate notifications. This is a
  genuine, currently-latent operational risk this document surfaces
  (§14, §21) — **not fixed here** (no runtime code change), but a
  concrete constraint the recommended process model must account for.
- **Admin bootstrap:** `POST /users` (`backend/app/api/v1/users.py`)
  is `administrator`-only — there is no way to create the *first*
  administrator through the API. The only existing mechanism is
  `backend/app/scripts/seed.py`, which creates a **hardcoded** account
  (`ADMIN001` / `Admin@12345`) alongside sample/demo data. This is a
  development/demo convenience, explicitly unsafe as a production
  bootstrap mechanism (§16).
- **Logging/observability:** structured JSON logging to stdout with
  request/correlation IDs and one access-log event per request already
  exists (Roadmap PR15A, merged). **Metrics, tracing, dashboards, log
  aggregation, and alerting remain open, unscheduled Roadmap PR15
  scope** (`docs/ROADMAP.md`'s own PR15 note, confirmed unchanged at
  this baseline) — this document treats them as genuine Production
  blockers to close before go-live, not as already delivered (§21).
- **CI (`​.github/workflows/ci.yml`):** PR-validation only — non-
  PostgreSQL backend tests, PostgreSQL-marked backend tests, Alembic
  upgrade validation, a backend production-Docker-image smoke test
  (build + boot + migrate + seed + one PDF-export round-trip), a
  frontend build, and `git diff --check`. **There is no CD stage**:
  no image registry push, no staging deploy, no production deploy,
  no manual-approval gate. §17 designs one; none exists today.
- **Backup/restore:** no procedure, script, or rehearsal evidence
  exists anywhere in this repository — confirmed already by
  `docs/audits/04-consolidated-implementation-plan.md` §14 item 7 and
  reiterated in `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §17. This
  document's §10 is the first place this repository designs what that
  procedure must contain.

---

## 6. Deployment Architecture Options

Per the task's own explicit instruction: **no provider is assumed or
recommended by name in this document.** The comparison below is by
architecture *class*.

### Option A — Managed application/container platform + managed PostgreSQL

A platform-as-a-service class of provider that runs a container/image
built from `backend/Dockerfile`/`frontend/Dockerfile` (or a combined
build), handles TLS termination, health-check-based restarts, and
offers a managed PostgreSQL add-on with automated backups, alongside a
deploy-from-image or deploy-from-git workflow.

| Dimension | Assessment |
|---|---|
| Operational complexity | **Low.** No OS patching, no manual TLS renewal, no server admin. |
| Cost predictability | **Low–Medium**, usually a per-service/per-resource tier; scales down cleanly for ~8 users. |
| Backup/restore | Managed PostgreSQL add-ons typically include automated daily backups and point-in-time recovery as a built-in feature — restore rehearsal still required (§10), but the mechanism itself is not hand-built. |
| PostgreSQL management | Managed — version upgrades, connection limits, and storage are the provider's responsibility within its published limits. |
| TLS/HTTPS | Typically automatic (managed certificate issuance/renewal). |
| Secret management | Platform-native environment/secret store, no `.env` file on a server. |
| Deployment automation | Usually git-push or image-push triggered; supports the immutable-artifact model (§17/§19). |
| Monitoring/logging | Basic log streaming and uptime/health monitoring is typically built in; may still leave metrics/alerting gaps (§21) needing a lightweight external service. |
| Rollback | Typically one-command/one-click rollback to a prior deploy — matches §20's immutable-artifact rollback model well. |
| Availability | Single-region managed offerings are normally sufficient at this scale; multi-region is over-engineering for ~8 users. |
| Data residency / network | Varies by specific provider/region choice — a genuine input to §33 and OD-PR24-1/§7. |
| Vendor lock-in | Moderate — mitigated by keeping the app itself in standard Docker images with no platform-proprietary SDK dependency (already true: nothing in `backend/app` imports a platform-specific SDK). |
| Maintenance burden | **Lowest of the four options** — best fit for a single project owner. |
| Hospital IT involvement | Minimal — mainly DNS delegation for the production hostname (§8) and, if chosen, network-access decisions (§7). |
| Browser/mobile access | Fully supported — no change from the existing browser-first design. |
| Scalability | Horizontal scaling (more replicas) is typically a configuration change, not a re-architecture. |

### Option B — Managed VPS / VM with Docker Compose

A rented virtual machine (from a cloud provider, not the hospital) that
the project owner administers directly, running the existing
`docker-compose.yml` + `docker-compose.prod.yml` overlay (already
partially built in this repository, see §5).

| Dimension | Assessment |
|---|---|
| Operational complexity | **Medium–High.** OS patching, Docker/Compose upgrades, TLS certificate renewal (e.g. certbot), and firewall configuration all become the project owner's responsibility. |
| Cost predictability | Generally a flat, low monthly VM cost — often the cheapest raw option, but with more owner time cost. |
| Backup/restore | Must be hand-built (`pg_dump`/WAL archiving to off-VM storage) — this repository has never designed this (§10 must design it explicitly, since no managed layer provides it). |
| PostgreSQL management | Self-managed inside the same VM (or a separate managed DB add-on layered on top, which would blur this into a hybrid of A/B). |
| TLS/HTTPS | Owner-managed (certbot/Let's Encrypt cron renewal) — `docker-compose.prod.yml`'s own top comment already flags the shipped `nginx.conf` needs a TLS block added first. |
| Secret management | `.env` file on the VM (or a secret manager bolted on separately) — higher risk of accidental exposure than a platform-native store. |
| Deployment automation | Must be hand-built (SSH + `docker compose pull && up -d`, or a small CI runner with SSH access) — no such automation exists today. |
| Monitoring/logging | Nothing built in beyond what's already in the app (§5) — an external agent/service must be added. |
| Rollback | Re-tag and redeploy a prior image; requires the owner's own tooling/discipline, not a platform feature. |
| Availability | Single VM = single point of failure unless the owner builds redundancy — disproportionate effort at this scale. |
| Data residency / network | Owner picks the cloud region directly — most flexible of the four, but requires evaluating the provider's own regional offerings. |
| Vendor lock-in | **Lowest** — plain Docker Compose, portable to any VPS provider. |
| Maintenance burden | Meaningfully higher than Option A for one project owner over time (patch cadence, cert renewal, backup cron reliability). |
| Hospital IT involvement | Same as Option A (DNS only) plus none for the VM itself (it is not hospital-managed). |
| Browser/mobile access | Same as Option A. |
| Scalability | Vertical scaling (bigger VM) is easy; horizontal scaling requires the owner to build a load balancer + multi-VM setup — real effort, not needed yet. |

### Option C — Hospital-managed / on-premises server

Evaluated **only as a constraint comparison**, per the task's own
instruction, since this repository's own confirmed architecture
decision already rules this class out as the preferred path
(`docs/ARCHITECTURE_DECISIONS.md`, "Managed deployment preferred":
"Production deployment must not assume direct access to
hospital-managed servers").

| Dimension | Assessment |
|---|---|
| Feasibility | **Not assumed feasible** — no confirmed hospital IT commitment to provide, patch, back up, or network-expose a server exists anywhere in repository authority. |
| Operational complexity | Would require hospital IT involvement for every deployment, patch, and backup — a dependency this project has no visibility into or control over. |
| Cost | Potentially zero incremental infrastructure cost to the project, but a real (unquantified) cost to hospital IT's own time. |
| TLS/network | Entirely dependent on the hospital's own network/certificate infrastructure — unknown at this baseline. |
| Consequence | Not recommended as the default path; would require an explicit hospital IT commitment this document cannot manufacture. Left as a documented option only, per OD-PR24-1 below, in case the Owner has hospital IT capacity this document is not aware of. |

### Option D — Other (e.g. fully serverless/functions, or Kubernetes)

- **Kubernetes:** explicitly not recommended per the task's own
  instruction and this document's own analysis — nothing about ~8
  initial users, one PostgreSQL database, and one stateful in-process
  scheduler justifies orchestration complexity. Would be pure
  operational overhead for a single project owner.
- **Fully serverless (functions-per-endpoint):** would require
  re-architecting the FastAPI app (currently one long-running ASGI
  process with an in-process scheduler and Redis-backed refresh-token
  state) into a stateless-per-invocation model — genuinely out of
  scope for this document (§34: no backend redesign) and disproportionate
  to the actual requirement.
- **Conclusion:** Option D is not recommended; not evaluated further.

---

## 7. Recommended Architecture Class

**Recommendation: Option A — a managed application/container platform
with a managed PostgreSQL add-on**, as the *architecture class*. This
is the simplest production-grade class that satisfies every constraint
in §4 (no client software install, no hospital-server assumption,
reliable PostgreSQL, HTTPS, safe secrets, backups, predictable
deploy/rollback, maintainable by one owner, room to scale beyond 8
users) with the **least** ongoing operational burden — the dimension
this document weights most heavily per the task's own §31/§32
instruction to favor simplicity and maintainability over raw
capability for an internal ~8-user hospital application.

**No specific commercial provider is selected in this document** — per
the task's own explicit instruction (§31 of the task, "No provider
marketing decision"), naming a vendor now would skip an Owner Decision.
See **OD-PR24-1** (§28) for provider selection within this architecture
class, including the concrete alternative of Option B if the Owner's
own operational preference or existing vendor relationships favor it.

**`docker-compose.prod.yml`'s existing partial overlay is not wasted
work under this recommendation** — Option B remains a live alternative
in OD-PR24-1, and even under Option A, the same container images
(`backend/Dockerfile`/`frontend/Dockerfile`) are what the managed
platform builds and runs; the two options share the same application
artifacts, differing only in *who operates the surrounding
infrastructure*.

---

## 8. Network / Access Model

| Model | Assessment |
|---|---|
| Public HTTPS + authenticated application | Simplest to operate; relies entirely on the existing JWT auth (`backend/app/core/security.py`) as the access boundary. No hospital-network dependency. |
| Hospital-network-only access | Requires hospital IT to expose the application only within their network (or a VPN into it) — a real, currently-unconfirmed hospital IT capability. |
| VPN / private access | Adds a client-side VPN requirement, which risks violating §4's "no client software install" constraint unless the hospital already mandates VPN for other systems staff use. |
| IP allowlisting | Feasible with Option A/B if the hospital's outbound IP ranges are known and stable — a concrete, low-effort hardening layer *on top of* public HTTPS, not a replacement for authentication. |
| Identity-aware proxy | Disproportionate complexity for ~8 users and a single application; not recommended. |

**This document does not assume hospital-network capability that has
not been confirmed anywhere in repository authority.** The
recommendation is **public HTTPS with the existing authenticated
application as the access boundary**, optionally hardened with IP
allowlisting if the hospital can supply a stable IP range — see
**OD-PR24-2** (§28).

---

## 9. Domain / TLS

- **Production hostname:** not invented here — use a placeholder
  (`https://mep.<hospital-domain-placeholder>.example`) until a real
  domain is selected. **Per OD-PR24-5's Owner-approved
  hostname-deferral policy (§28, fully resolved — not open):** the
  Owner currently has no custom production domain; the HTTPS hostname
  supplied by the selected managed provider (OD-PR24-1) is an approved,
  sufficient hostname for Staging and for the Deployment Foundation
  (PR24B) slice — the lack of a custom domain does **not** block PR24B.
  The real custom production hostname is a **Production-Go-Live
  execution/configuration input** — it must be selected, DNS-delegated,
  and TLS-validated **before Production Go-Live** (§27), but selecting
  it does not reopen OD-PR24-5. TLS/HTTPS remains mandatory at every
  stage regardless of which hostname is in use.
- **HTTPS/TLS:** mandatory, no plain-HTTP production traffic.
  `frontend/nginx.conf` currently terminates HTTP only —
  `docker-compose.prod.yml`'s own comment already flags this gap.
  Under Option A (§7), TLS issuance/renewal is typically automatic;
  under Option B, a certbot-style renewal cron must be added.
- **Certificate lifecycle:** automatic renewal preferred (avoids a
  manual, easy-to-miss operational task); if self-managed (Option B),
  the renewal job itself needs monitoring (§21).
- **HTTP → HTTPS redirect:** required at the edge (nginx or
  platform-level) so no request is ever served in cleartext.
- **Secure cookies / token transport:** the existing refresh-token
  cookie logic (`backend/app/api/v1/auth.py`) already reads
  `settings.ENVIRONMENT` to decide the `secure` cookie flag — this
  must be `production` in the deployed environment for that flag to
  take effect; a deployment-configuration checklist item, not a code
  change.
- **CORS origins:** `ALLOWED_ORIGINS` must be set to the exact
  production hostname(s) only — never a wildcard, never the
  development defaults (`http://localhost*`).
- **Frontend API base URL:** the frontend and backend are already
  designed to be served from one origin via `frontend/nginx.conf`'s
  `/api/` reverse-proxy block (§5) — the simplest production
  configuration keeps this pattern (one hostname, nginx/platform edge
  routes `/api/*` to the backend service), avoiding a separate
  API subdomain and the extra CORS/cookie-domain complexity that would
  introduce.

---

## 10. Production Database (PostgreSQL)

- **Managed vs. self-managed:** managed PostgreSQL (via Option A's own
  add-on, or a separate managed DB service under Option B) is
  recommended over self-managed-inside-a-VM, specifically because
  backup/restore (§11) is the one gap this repository has never
  closed — a managed offering typically provides this as a built-in
  feature rather than something the project owner must build and
  maintain by hand.
- **Version policy:** match the version already used in development
  (`postgres:16-alpine`, `docker-compose.yml`) unless the chosen
  provider's supported versions require otherwise; any difference must
  be verified against `backend/alembic/versions/**` for
  version-specific DDL assumptions before selection.
- **Storage:** sized for the confirmed low-hundreds-of-equipment,
  low-thousands-of-transactions-per-year scale
  (`docs/audits/04-consolidated-implementation-plan.md` §14 item 1) —
  not provisioned for large-scale growth speculatively.
- **Backups:** see §11 — this section only states that *managed*
  backups are preferred over hand-built ones as the default
  recommendation.
- **Point-in-time recovery (PITR):** preferred if the selected managed
  offering supports it, since it materially improves the RPO
  achievable (§11) beyond periodic full-dump backups alone; not
  assumed available until a specific provider is selected
  (OD-PR24-1).
- **Connection limits / pooling:** `backend/app/db/session.py`'s
  connection-pool configuration must be sized against the selected
  provider's actual connection limit, not assumed — a concrete
  pre-go-live verification item (§24), not designed further here since
  it depends on the provider selected in OD-PR24-1.
- **Migration procedure:** see §19.
- **Migration rollback strategy:** see §19/§20 — forward-fix
  preferred, matching this repository's own established discipline
  (`docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §10).
- **Production restore test:** see §11 — required evidence before
  Production go-live, never assumed.
- **Least-privilege DB credentials:** the application's own database
  role should hold only the privileges the ORM/migrations actually
  need (DML on application tables, DDL only for the migration-runner
  identity if that is kept separate) — a concrete provisioning-time
  configuration item, not a schema change.
- **No SQLite in production** — already true (`DATABASE_URL` defaults
  to `postgresql+asyncpg://...`; SQLite is exercised only by the
  non-PostgreSQL CI test lane, per `backend/tests/`'s own dual-database
  test strategy) — this document changes nothing here, only reaffirms
  it as a hard requirement.
- **No public PostgreSQL exposure** — `docker-compose.prod.yml`
  already closes the Postgres port (`ports: []`); this must remain
  true for whatever hosting class is selected — the database is reached
  only from the backend service's private network, never the public
  Internet.

---

## 11. Backup / Restore — Closing the Open Gap

This is the gap `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §17 correctly
left open. This section designs what must exist; it does not perform
any of it.

**Tooling implemented in PR24C:** `backend/scripts/backup_postgres.py`
(logical `pg_dump --format=custom` backup, SHA-256-checksummed,
timestamped filename + JSON manifest sidecar), `backend/scripts/
restore_postgres.py` (checksum verification, a hard restore-target
guard that refuses a `production`-labeled or source-identical target
with no override flag, `pg_restore`, then Alembic-revision and
representative-row-count verification), and `backend/scripts/
prune_backups.py` (30-day retention cleanup, never deletes the newest
backup). Operator procedure and the rehearsal evidence template are in
`docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md`. **This still does not
constitute a completed rehearsal** — see that runbook's own explicit
"CI proves tooling, Staging rehearsal proves operational readiness"
distinction, and the "This document does not claim a rehearsal has
happened" paragraph below, which remains true until PR24D provisions a
real Staging-class environment and the rehearsal is actually run
against it.

- **What is backed up:** the production PostgreSQL database in full
  (all application tables, including `import_source_blobs`'s binary
  content — since §5 confirms all persisted file content lives in
  Postgres, a database backup *is* the complete backup; no separate
  object-storage backup is needed given §12's finding).
- **Backup frequency:** at minimum daily full backups; if the selected
  provider supports continuous WAL archiving/PITR (§10), that is
  preferred over frequency alone.
- **Retention:** must be set explicitly by the Owner (§28, OD-PR24-3)
  — this repository has no existing retention policy to reuse for
  *infrastructure* backups (its existing retention policies, e.g.
  `IMPORT_RETENTION_DAYS`, govern *application-level* evidence
  redaction, a different concern entirely — never conflated with
  database backup retention).
- **Encryption:** backups must be encrypted at rest, at minimum via
  whatever the selected provider offers by default; if self-managed
  (Option B), encryption must be configured explicitly, not assumed.
- **Restore procedure:** documented, versioned steps to restore a
  backup into a **separate, non-production** database instance —
  never restored directly over the live production database as the
  "test."
- **Restore-test environment:** a disposable staging-class database
  instance, torn down after each rehearsal — never the actual
  production or Pilot database.
- **RPO/RTO targets:** **not determinable from repository authority**
  — no existing document states an acceptable data-loss window or
  recovery-time target for this application. Raised as **OD-PR24-3**
  (§28); this document does not invent a number.
- **Responsibility:** the "Database/backup contact" role already named
  in `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §1's contact matrix is the
  natural owner of this procedure — no new role is introduced.
- **Evidence required to mark rehearsal PASS:** (1) a real backup was
  taken from a real (staging-class, non-production) database instance
  seeded with representative data; (2) that backup was restored into a
  fresh, separate instance; (3) row counts and a sample of known
  records were verified to match between source and restored instance;
  (4) the actual wall-clock time taken was recorded and compared
  against the Owner-set RTO target; (5) the restored instance was
  destroyed afterward.
- **How rehearsal is recorded:** using the exact evidence-slot
  template already defined in `docs/runbooks/PR23_CUTOVER_RUNBOOK.md`
  §17 (`Backup/restore procedure reference` / `Backup rehearsal date` /
  `Restore rehearsal result` / `Responsible person`) — this document
  does not duplicate that template, it defines what must be true before
  that template's fields can honestly be filled in.

**This document does not claim a rehearsal has happened.** It remains
an execution-time gate, per `docs/runbooks/PR23_CUTOVER_RUNBOOK.md`
§16/§17's own fail-closed rule: Production GO must remain blocked until
real rehearsal evidence exists.

---

## 12. Object Storage / MinIO Disposition

Per §5's inspection: **MinIO/S3 is not genuinely required in
production.** `S3_ENDPOINT`/`S3_BUCKET`/`S3_ACCESS_KEY`/`S3_SECRET_KEY`
are declared in `Settings` and `docker-compose.yml`, but zero backend
code path (`backend/app`) actually constructs an S3/MinIO client or
reads/writes through one. The one persisted-file mechanism this
repository has (`ImportSourceBlob.content`) stores content directly in
PostgreSQL as `BYTEA`.

**Recommendation:** do **not** deploy MinIO, or provision any
S3-compatible object storage, for Production. `docker-compose.yml`
including a `minio` service is a development-environment artifact, not
evidence of a genuine production dependency — repository runtime truth
decides, per the task's own explicit instruction. If a genuine
file-storage need is identified in a future Roadmap slice (outside this
document's scope), that would be a new, separately-designed decision,
not something this document pre-approves.

**Retention/backup implications:** none, given the above — no separate
object-storage backup stream needs to be designed; §11's PostgreSQL
backup already covers everything actually persisted.

---

## 13. Redis Disposition

Per §5's inspection, Redis is genuinely used for two purposes, both
already fail-open/non-critical to availability:

- **Optional response cache** (`CACHE_ENABLED`) — silently degrades to
  "no cache" on any Redis error.
- **Refresh-token storage/revocation** — token *validity checking*
  fails open (treats a token as valid) if Redis is unreachable, but
  **token revocation (logout, forced session termination) silently
  stops working** without Redis. This is a real, if narrow, security
  property that depends on Redis being present.

**Recommendation:** include Redis in the production architecture (it
is cheap, already used, and its absence has a real — if narrow —
security consequence for refresh-token revocation), but do **not**
treat it as a hard availability dependency, since the application
itself already tolerates its absence by design. Under Option A, a
small managed Redis add-on is the natural fit; under Option B, the
existing `docker-compose.prod.yml` Redis service (with
`--appendonly yes` for persistence) is already provisioned for this.
**No queue, session-store, or SSE/pub-sub usage of Redis exists** in
this codebase — nothing beyond cache + refresh-token storage needs to
be designed for.

---

## 14. Frontend Hosting

**Recommendation: serve the frontend from the same managed
application platform/edge that serves the backend** (§7), reusing the
existing `frontend/Dockerfile` (Vite build → `nginx:1.27-alpine`) and
`frontend/nginx.conf`'s already-built `/api/` reverse-proxy pattern
(§9) — this is the **minimal-operational-complexity** option (one
deployable artifact set, one TLS certificate, one hostname, no
separate CDN account/configuration to manage) and directly matches
§4's "browser-first, no client install" constraint without any change.

A dedicated static-hosting/CDN service remains a valid *future*
optimization if load or geographic distribution ever justifies it, but
is not justified for ~8 initial users and is **not recommended now**,
consistent with §31's simplicity-first instruction. **No frontend
redesign, and no PWA/offline scope expansion, is proposed anywhere in
this document** (§34) — browser-first, online-first access remains
sufficient for V1, exactly as already decided.

---

## 15. FastAPI Production Runtime

- **Process model:** **enforced in PR24B** — `backend/Dockerfile`'s CMD
  now runs `uvicorn app.main:app --workers 1` (was `--workers 2`), and
  `docker-compose.prod.yml`'s backend service now sets `replicas: 1`
  (was `3`), both with a comment recording this as a hard deployment
  invariant, not a tunable, until a leader-election or distributed-lock
  mechanism is added to `app/worker/scheduler.py` (still a future
  implementation-slice item — not built in PR24B) — trading a small
  amount of request-handling headroom for correctness of the daily
  PM/CAL notification job, given the confirmed ~8-user scale does not
  need multiple workers for throughput reasons alone.
- **Worker strategy:** single-worker as above until the scheduler gap
  is closed; horizontal scale-out (more replicas) remains available
  for request-handling capacity once the scheduler is made
  safely multi-instance.
- **Health checks:** `GET /api/v1/health` already exists and already
  checks both DB and Redis (§5) — suitable as the platform's **liveness**
  probe target as-is. **It must not be used directly as a status-code-
  only production readiness probe without additional fail-closed
  semantics** — see §15A (Liveness vs. Readiness — Production Probe
  Contract) immediately below for the required design.
- **Startup migration behavior:** migrations are **not** run
  automatically on application boot (confirmed — `app/main.py`'s
  `lifespan` only starts/stops the scheduler); they are applied as an
  explicit, separate deployment step (§19), matching the existing CI
  pattern (`.github/workflows/ci.yml`'s own `migrations` job runs
  `alembic upgrade head` as a distinct step, and the Docker
  smoke-test job applies migrations *inside* the running container as
  a separate step after startup, not as part of boot).
- **Graceful shutdown:** `uvicorn`'s default SIGTERM handling combined
  with the `lifespan` context's `stop_scheduler()` call is adequate;
  the selected platform's own deploy mechanism (§7) should give the
  old instance a grace period before killing it, standard for any
  managed-platform or container-orchestrated rolling deploy.
- **Timeout policy:** should be set at the edge (nginx/platform proxy)
  to a value that comfortably exceeds this application's slowest known
  operation (PDF export, per the existing CI Docker-smoke-test's own
  "Log in and request a PDF export end to end" step) without allowing
  an indefinitely-hanging request to hold a worker forever.
- **Proxy headers / trusted hosts:** `frontend/nginx.conf` already
  forwards `X-Real-IP`/`X-Forwarded-For`/`X-Forwarded-Proto` to the
  backend (§5) — the backend's own request-context middleware
  (`app/main.py`) should be confirmed to trust these only from the
  known reverse-proxy hop, not from arbitrary clients, as a
  pre-go-live configuration check (§24), not a code redesign here.
- **Upload/body limits:** should be set explicitly at the edge to a
  size appropriate for the largest legitimate import workbook this
  repository's own import framework (PR19–PR21) is designed to accept
  — a configuration value, not an architecture change.
- **Logging output:** already structured JSON to stdout (§5/§21) —
  production deployment should route container stdout/stderr to
  whatever log-collection mechanism the selected platform provides,
  not to a file inside the container.

**Development-server behavior is not used as production design
anywhere in this section** — every recommendation above builds on the
already-Dockerized, already-non-root, already-health-checked
production image (`backend/Dockerfile`), not `uvicorn --reload`.

---

## 15A. Liveness vs. Readiness — Production Probe Contract

**Added in Fix Round 1**, following an independent review finding
(P1, blocking): the original draft of this document treated
`GET /api/v1/health` as directly usable as a production readiness
probe without qualification. That was incorrect — see below.

### Definitions

- **Liveness** answers: *"Is the application process running and able
  to serve HTTP at all?"* A liveness check exists to tell the platform
  when to **restart** an instance (it has hung, deadlocked, or crashed
  internally). It does not need to reflect whether the instance's
  dependencies are healthy — an instance whose database connection is
  temporarily down is still *alive* (the process is fine and can
  recover once the database returns); restarting it would not help and
  would just add churn.
- **Readiness** answers: *"Can this instance safely receive production
  traffic right now?"* A readiness check exists to tell the platform's
  load balancer/router when to **include or exclude** an instance from
  traffic routing. An instance that cannot reach a dependency required
  for normal operation (§15A.3) must be excluded from traffic — serving
  requests it cannot actually complete correctly is worse than serving
  none.

**These are never interchangeable in this design.** A single endpoint
that conflates them (always returns HTTP 200 regardless of dependency
state) can only ever safely answer the liveness question — using it to
answer the readiness question means a load balancer keeps routing
production traffic to an instance whose database is unreachable, which
defeats the entire purpose of a readiness gate.

### §15A.1 — Current `/api/v1/health` is not a safe readiness probe

Confirmed by direct inspection of `backend/app/api/v1/health.py`
(§5): the endpoint checks `SELECT 1` against the database and a Redis
`PING`, reports the result of each in its **response body**
(`{"status": "ok", "db": ..., "redis": ...}`), but **always returns
HTTP 200** regardless of what those checks find — there is no code
path that sets a non-2xx status based on `db`/`redis` failing. Most
production platform readiness probes (managed-platform health checks,
container orchestrators, load balancers) are **status-code-based** —
they treat any 2xx as healthy and never parse the response body. Given
that, **this endpoint, used as-is, would tell every such platform the
instance is ready even while its database is unreachable.**

**Normative rule for this document and any later PR24 implementation
slice: `GET /api/v1/health` MUST NOT be relied upon as a status-code-
only production readiness probe without one of the two changes in
§15A.2.** It remains valid, unmodified, as a liveness probe and as a
human/dashboard diagnostic endpoint.

### §15A.2 — Required fail-closed strategy (pick one)

**Option A — Dedicated readiness endpoint (recommended).**

A new route, e.g. `GET /api/v1/ready` (exact path a repository-
consistent implementation detail, not fixed by this document):

- Returns HTTP 200 **only** when every dependency required for normal
  production request handling (§15A.3) is reachable.
- Returns a non-2xx status — **HTTP 503 Service Unavailable**
  preferred — when a required dependency is unavailable.
- May still return a structured body describing per-component status,
  for human/dashboard consumption, but the **HTTP status code is the
  contract the platform's probe actually depends on**, not the body.
- Is backend-owned: the backend decides what "ready" means, the
  platform only asks the question.
- `GET /api/v1/health` is left unmodified, continuing to serve
  liveness/diagnostic purposes — no existing client of the current
  endpoint (if any exists) is broken by this addition.

**Option B — Existing health endpoint gains fail-closed status
semantics.**

If a future implementation slice deliberately chooses to keep exactly
one endpoint rather than add a second:

- `GET /api/v1/health`'s own status code must change to non-2xx when a
  required dependency check fails — no longer unconditionally 200.
- A **separate** liveness signal must still exist for the platform if
  it needs pure process-liveness detection independent of dependency
  state (e.g. a orchestrator that would otherwise restart an instance
  merely because a dependency is briefly down) — collapsing liveness
  and readiness into the same status code reintroduces the exact
  failure mode this section exists to prevent, just from the opposite
  direction (an instance killed for a transient dependency blip that
  would have recovered on its own).

**This document does not pick between Option A and Option B on the
implementation team's behalf** — that remained a genuine, narrowly
scoped implementation decision for the slice that builds it (§29,
PR24B). **Option A is the recommendation** (§15A.4), and PR24B
implements it exactly: `GET /api/v1/ready`
(`backend/app/api/v1/health.py`), leaving `GET /api/v1/health`
byte-for-byte unmodified.

### §15A.3 — Required-dependency policy (do not over-block)

Readiness must fail only when a dependency **required for normal
application operation** is unavailable — not merely because some
integration is checked at all. Applying this repository's own actual
runtime behavior (§5, §13), not a blanket "check everything":

- **PostgreSQL — required.** Nearly every endpoint depends on the
  database; the application cannot correctly serve normal traffic
  without it. A readiness check **must** fail closed when PostgreSQL
  is unreachable.
- **Redis — optional, must NOT unconditionally block readiness.**
  Confirmed in `backend/app/core/redis.py` (§13): every Redis-dependent
  code path in this codebase is already deliberately fail-open or
  fail-soft — `cache_get`/`cache_set` silently degrade to "no cache" on
  any Redis error, and `is_refresh_token_valid` explicitly treats a
  token as valid (fails open) when Redis is unreachable, precisely so
  the application keeps working without it. A readiness check that
  hard-fails on Redis being down would contradict the application's
  own already-established fail-open design for that dependency, and
  would take an otherwise-fully-functional instance out of rotation
  over a non-blocking integration. **Recommendation: Redis health may
  still be reported in the readiness response body as a degraded/
  warning-level signal for observability (§22), but must not by itself
  flip the overall HTTP status to non-2xx.**
- **No other mandatory auth/session/cache dependency exists** in this
  codebase beyond PostgreSQL and the already-covered Redis case — no
  additional required-dependency check is proposed.

If a future implementation genuinely needs to treat some other
integration as hard-required, that determination should be made
against that integration's own actual fail-open/fail-closed behavior
in code, the same way this section resolved PostgreSQL vs. Redis —
never assumed merely because a health check currently touches it.

### §15A.4 — Recommendation

**Dedicated fail-closed readiness endpoint (§15A.2, Option A) +
unmodified liveness endpoint (`GET /api/v1/health` as-is).**

Rationale: standard cloud/container/managed-platform probes understand
HTTP status codes natively (§15A.5) — this needs no custom body
parsing on the platform side, keeps alerting and load-balancer
integration simple, cleanly separates the liveness and readiness
concerns (§15A per its own definitions), and does not touch or risk
breaking any existing behavior or caller of `GET /api/v1/health`.
**Implemented in PR24B** as `GET /api/v1/ready`
(`backend/app/schemas/health.py`'s `ReadinessOut`, `backend/app/api/v1/
health.py`) — HTTP 200 with `status: "ready"` when PostgreSQL is
reachable, HTTP 503 with `status: "not_ready"` otherwise; `redis` is
reported (`"ok"`/`"degraded"`) but never changes the HTTP status, per
§15A.3. Covered by `backend/tests/test_pr24b_readiness.py`.

### §15A.5 — Body-aware probe fallback (only if Option A/B is not adopted)

If a future implementation instead keeps `GET /api/v1/health`
completely unmodified (status always 200) and relies on the deployment
platform to inspect the response body directly, the platform's probe
configuration must be **explicitly body-aware** — e.g. a rule requiring
HTTP 200 **and** `body.db == "ok"` **and** (per §15A.3) treating
`body.redis` as informational only, never itself gating readiness.

This fallback is **not preferred**: it is less portable across
platforms (many managed-platform/load-balancer health checks support
status-code-only probing, not arbitrary JSON-body assertions), it
creates a hidden coupling between the exact response schema and the
platform's probe configuration, and it does not resolve the underlying
problem for any consumer of the endpoint that only checks the status
code (§15A.1). It is documented here only as an explicit trade-off, not
as this document's recommendation.

### §15A.6 — Startup / migration readiness state

Readiness must also fail closed — not merely on dependency
reachability, but on the instance's own completeness — during:

- Application startup that has not yet finished initializing (the
  process is listening on the HTTP port before it is actually able to
  serve correct responses is a real failure mode this section exists
  to prevent — "process listening" and "ready for traffic" are not the
  same claim).
- A running instance whose database schema is not compatible with the
  application version it is running (e.g. mid-rollout, before the
  corresponding migration has been applied — §20).
- Any other mandatory startup initialization that failed.

**Verifying migration-schema compatibility at the readiness-check
level is explicitly out of this document's scope to design in detail**
— §20's own migration deployment procedure already sequences
migrations as a separate, verified step *before* an application
version is exposed to traffic, which is the primary control for this
risk. If a future implementation slice wants an additional, defense-
in-depth compatibility check inside the readiness endpoint itself
(e.g. comparing the running application's expected Alembic head
against the database's actual `alembic_version`), that is a genuine
option for a future slice to design and build. **PR24B's own `GET
/api/v1/ready` implementation does not include this check** — it
verifies PostgreSQL connectivity (`SELECT 1`) only, exactly as
designed above; schema-compatibility-at-readiness remains explicitly
out of scope, not silently added, and not fabricated here.

### §15A.7 — Security / exposure constraints

Whichever endpoint(s) implement liveness/readiness must never expose,
in their response body or logs:

- Credentials, connection strings, or any secret value.
- Raw exception text or stack traces.
- Infrastructure topology beyond what an operator needs to diagnose a
  failure (e.g. "database unreachable" is appropriate; the database's
  hostname/port/credentials are not).

Bounded, structured status only (matching the existing endpoint's own
`{"status": ..., "db": ..., "redis": ...}` shape). **No authentication
requirement is invented for these endpoints by this document** —
whether a platform's probe mechanism can supply credentials at all
varies by platform, and inventing an auth requirement without first
confirming the selected platform's actual probe capability (a genuine
dependency of OD-PR24-1) would risk designing something the eventual
platform cannot satisfy; if authentication is later found necessary,
that is a narrow addition for the implementing slice, not a decision
this document makes speculatively.

### §15A.8 — Platform independence

This design is deliberately **not** written for one vendor. The
recommended approach (§15A.4, status-code-based readiness) works
identically against common reverse proxies, load balancers, container
orchestrators, and managed application platforms — it depends on
nothing beyond standard HTTP semantics. This is itself part of why
Option A is preferred over the body-aware fallback (§15A.5): a
platform-specific body-parsing rule is exactly the kind of coupling
this document otherwise avoids when comparing architecture options
(§6/§7) without committing to a vendor.

### §15A.9 — Interaction with Owner Decisions

This section's **recommendation** (dedicated, status-code-based,
fail-closed readiness endpoint) does not require a new Owner Decision
— it is derived directly from this codebase's own already-implemented
fail-open/fail-closed behavior (§15A.3) and from standard, platform-
agnostic HTTP probe semantics (§15A.8), the same class of
directly-derivable finding as §12's MinIO/S3 disposition and §13's
Redis disposition, neither of which was escalated to an Owner Decision
either. It does not silently resolve **OD-PR24-1** (hosting/provider
selection) — the recommendation is deliberately platform-independent
specifically so it does not depend on that decision's outcome. If the
Owner ultimately selects a platform genuinely incapable of ordinary
HTTP-status-code probing (uncommon, but not this document's to rule
out), the body-aware fallback (§15A.5) — already documented as a
trade-off, not invented fresh at that point — would need to be
revisited against that platform's actual capability.

---

## 16. Secret Management

- **JWT/application secret:** `validate_production_secrets` (§5)
  already refuses to boot in production with a missing, default, or
  short `JWT_SECRET_KEY` — the deployment procedure must generate one
  with `python -c "import secrets; print(secrets.token_urlsafe(64))"`
  (the exact command the codebase's own `.env.example` and error
  messages already recommend) and store it only in the selected
  platform's secret store, never in a committed file.
- **Database credentials:** issued by the selected managed PostgreSQL
  provider (§10) or generated at VM-provisioning time (Option B);
  never the `docker-compose.yml` development defaults
  (`mep_user`/`mep_password`). **Enforced in PR24B, hardened in PR24B
  Fix Round 1 and Fix Round 2:** `validate_production_secrets` refuses
  to boot in production when `DATABASE_URL`'s connection identity
  (username, password, host, and database name, parsed independently —
  not a closed set of full-URL literals) matches every component of a
  repository-shipped default: username `mep_user`, database `mep_db`,
  host `localhost` (the non-Docker local-dev default) or `postgres`
  (`docker-compose.yml`'s service name), and password `mep_password`
  (`docker-compose.yml`'s own native default with no `.env` override at
  all) or `change-me` (`.env.example`'s copy-paste placeholder) — this
  covers all three ways the repository can resolve an insecure
  `DATABASE_URL` without a new literal needing to be added for each. The
  error message intentionally does not echo the connection string, since
  `DATABASE_URL` commonly carries a password. `ALLOWED_ORIGINS` is
  refused when it resolves — after order/whitespace/duplicate-
  independent parsing — entirely to the shipped `http://localhost*`
  development pattern (§9's own "never the development defaults"
  requirement), regardless of which of the repository's own literal
  orderings it happens to ship in. The same fail-closed pattern as the
  JWT secret check above, not a new mechanism; `JWT_SECRET_KEY` itself is
  checked against both of its own known shipped placeholder literals
  (config.py's/docker-compose.yml's wording and `.env.example`'s
  separate wording) for the same reason.
- **Object-storage credentials:** not applicable — §12 recommends not
  deploying object storage at all.
- **Deployment secrets** (e.g. a platform API token used by CI to
  trigger deploys): stored in the CI provider's own secret store
  (GitHub Actions Environment secrets), scoped to the production
  deployment job only (§17), never exposed to PR-triggered jobs.
- **Admin bootstrap secret:** see §17 — the first Administrator's
  credential is generated at bootstrap time, never a checked-in value.

**Requirements enforced throughout:** never commit secrets to Git (no
new secret file is added by this document — none of §5's placeholders
are real values); no default production secrets (already enforced in
code, §5); environment/provider secret store only; a rotation
procedure exists for the JWT secret (rotate the value, which
invalidates all outstanding access/refresh tokens — an accepted,
already-implied consequence of HS256 single-secret signing, not a new
design); least privilege for every credential (§10's DB role, any
future deploy-token scope). **No real credential of any kind is
created by this document.**

---

## 17. Admin Bootstrap

Per §5's finding: today, the only path to a first Administrator account
is `backend/app/scripts/seed.py`'s hardcoded `ADMIN001`/`Admin@12345`
— explicitly a development/demo mechanism, unsafe for production.

**Implemented in PR24B** as `python -m app.scripts.bootstrap_admin`
(`backend/app/scripts/bootstrap_admin.py`), matching every requirement
originally designed here:

1. A dedicated, one-time bootstrap procedure — distinct from
   `app.scripts.seed` (which also creates unrelated sample
   equipment/transaction data never appropriate for a real production
   database) — that creates exactly one `administrator` account with a
   **freshly generated random password** (`secrets.token_urlsafe`),
   never a hardcoded literal.
2. The generated password is printed once to the operator's terminal at
   bootstrap time and never logged or stored anywhere persistent.
3. No forced-credential-change-on-first-login flag exists on the `User`
   model today, and this slice does not invent one (§28's own
   non-goal) — the script instead prints an explicit operational
   instruction to rotate the password immediately using the existing
   `PATCH /users/{id}` password-update capability
   (`UserUpdate.password`, `backend/app/schemas/master_data.py`).
4. The script refuses to run if an `administrator` account already
   exists, serialized against concurrent invocations via a `SELECT ...
   FOR UPDATE` lock on the (already-seeded-by-migration-0009)
   `administrator` role row — the same PostgreSQL-conditional locking
   convention every other concurrency-sensitive CRUD module in this
   codebase already follows (e.g. `app/crud/legacy_reconciliation.py`,
   `app/crud/equipment.py`), not a new locking primitive. A defensive
   `IntegrityError` catch (unique `employee_code`/`email`) backs this
   up and never leaves partial state.
5. **Audit:** each bootstrap records an `AuditLog` row
   (`action="ADMIN_BOOTSTRAP"`) with `user_id=None` — a deliberate,
   non-fabricated actor, since `AuditLog.user_id` is nullable exactly
   for the case where no authenticated User exists yet. Never audits
   the plaintext password.

Covered by `backend/tests/test_pr24b_admin_bootstrap.py` (SQLite:
creation, refusal, no demo data, password never persisted in
plaintext, audit shape, rollback on identifier collision) and
`backend/tests/test_pr24b_postgres.py` (PostgreSQL-marked: two
concurrent bootstrap attempts produce exactly one administrator, never
two, never a crash).

---

## 18. CI/CD

Today's `.github/workflows/ci.yml` (§5) is PR-validation only. Proposed
staged pipeline, **not implemented by this document**:

**Mechanism implemented in PR24D:** `.github/workflows/cd-staging.yml`
(manual `workflow_dispatch` trigger, a trusted-ref check via `git
merge-base --is-ancestor`, an image build/push to GHCR tagged by commit
SHA for traceability, with the registry **digest** each build returns
captured and validated as the actual immutable artifact identity —
Fix Round 1, independent review, P1-B: a commit-SHA tag is a mutable
registry pointer, not itself an immutable reference — informational
dependency scanning + CRITICAL-blocking image scanning of the
digest-pinned images, and a `migrate-and-verify` job, gated on the image
scan succeeding (Fix Round 1, P1-A), that runs `backend/scripts/
deploy_migrate.py` — the explicit, fail-closed migration step — against
the digest-pinned image, then `backend/scripts/staging_smoke_check.py`
— the readiness-gated post-deploy verification) against an
**ephemeral, CI-provisioned** PostgreSQL database and container run on
the Actions runner. **This proves the CD mechanism, not a real Staging
deployment** — no hosting provider has been selected (OD-PR24-1
approves only the architecture class) and no external/paid resource is
provisioned by PR24D. See `docs/runbooks/PR24_STAGING_DEPLOYMENT_RUNBOOK.md`
§3 for the full artifact-identity contract (Git SHA = source
provenance; registry digest = immutable release artifact) and the
operator procedure once a real Staging environment exists.

```
PR opened → existing CI (unchanged: backend tests ×2, migrations, Docker smoke test, frontend build, git diff --check)
   ↓ (on merge to the default/integration branch)
Build immutable artifact/image (tagged by commit SHA, matching this
  repository's own squash-SHA-as-baseline discipline)
   ↓
Deploy to Staging/UAT environment (§18)
   ↓
Run migration check against Staging DB (alembic upgrade head, non-destructive)
   ↓
Run smoke tests against the deployed Staging environment (reuse/extend
  the existing Docker-smoke-test's own login + core-workflow pattern)
   ↓
Manual production-approval gate (a human, not automatic)
   ↓
Deploy to Production (image already built and smoke-tested — no
  rebuild at this step, preserving immutability)
   ↓
Post-deploy readiness/verification check (the fail-closed readiness
  endpoint per §15A — not GET /api/v1/health's status code alone —
  plus a minimal smoke check, before traffic is fully routed to the
  new instance)
```

**Production is never deployed automatically on every merge** — the
manual-approval gate above is mandatory, matching the task's own
explicit instruction. **Immutable, commit-SHA-tagged build artifacts
are preferred over "rebuild at deploy time"** — this both matches this
repository's own squash-SHA-based baseline/governance discipline (every
prior PR23 round recorded and verified an exact deployed SHA) and
avoids the class of bug where a Production deploy silently picks up a
dependency-version drift a Staging deploy did not have.

---

## 19. Environment Topology

| Environment | Purpose | Data |
|---|---|---|
| **Development** | Local `docker-compose.yml`, developer machines and CI test runs. | Synthetic/seeded only (`app.scripts.seed`) — never real hospital data. |
| **Staging/UAT** | Production-like deployment (same images, same architecture class) used to prove UAT readiness (§24) and rehearse backup/restore (§11) before each Production deploy. | Synthetic/representative data only, generated the same way as Development — **never a casual copy of real production data**, per the task's own explicit instruction. |
| **Production** | The real, operational system once Go-Live occurs. | Real hospital operational equipment/transaction data. |

**Pilot environment question:** should Pilot (`docs/runbooks/
PR23_CUTOVER_RUNBOOK.md` §12) run against a scoped subset of the real
Production environment/data (one Ward, real equipment) or a fully
separate Pilot environment? **This repository's own approved Pilot
model (OD-PR23-5) already implies Production-environment, scoped-data
Pilot** — Pilot is defined as "one controlled Pilot Ward" using real
Ward master data and real equipment issued/received through the
ordinary workflow, which only makes operational sense against the real
Production database (a separate Pilot environment would require a
second, disconnected copy of Equipment Master data, contradicting
Gate B/E's own already-approved evidence model). **Recommendation: no
separate Pilot environment — Pilot runs in Production, scoped to one
Ward, exactly as `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §12 already
describes.** This is not a new decision; it is a direct, non-optional
consequence of OD-PR23-5's own already-Owner-approved design.

**No environment is duplicated without operational value** — exactly
three environments (Development, Staging/UAT, Production) are
proposed, matching the task's own "do not over-fragment" instruction.

---

## 20. Migration Deployment Procedure

Extends `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §5 (T1/T2) with the
infrastructure-level mechanics that runbook deliberately left as
"the existing PR21E0 identity model" / "Gates B-C evidence" — this
section is about **deploying schema changes**, a different concern from
that runbook's **operational cutover evidence**.

Before running any production migration:

- [ ] Record the exact application baseline SHA being deployed.
- [ ] Record the database's current Alembic revision
      (`alembic_version` table).
- [ ] Record the expected target revision (the new SHA's own Alembic
      head).
- [ ] Confirm a recent backup exists (§11) — evidence, not assumption.

Execution:

- [ ] Run `alembic upgrade head` as an explicit, separate deployment
      step — never automatically on application boot (§15).
- [ ] Verify the resulting `alembic_version` matches the expected
      target revision.
- [ ] Run a basic schema-shape verification (e.g. confirm a known
      table/column introduced by the new revision exists) before
      routing production traffic to the new application version.
- [ ] Only then complete the application deployment (§18's staged
      pipeline).

**Failure handling:** if a migration fails partway, this repository's
own existing migration discipline (every migration in
`backend/alembic/versions/**` reviewed under PR15B's convergence-
verification precedent) already favors additive, reversible-by-design
migrations — **prefer forward-fix** (fix the migration, re-run) over
automatic destructive rollback, matching `docs/runbooks/
PR23_CUTOVER_RUNBOOK.md` §10's own established forward-fix-by-default
principle for production data. **This document does not implement an
automatic destructive-rollback mechanism**, per the task's own explicit
instruction.

---

## 21. Application Rollback

**Deliberately separate from PR23's operational cutover rollback**
(`docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §9/§10, which governs the
AppSheet-vs-application source-of-truth boundary) — this section is
about rolling back the **application's own deployed version**, a
different, narrower concern:

- **Rolling back the application image/version:** under the immutable-
  artifact model (§18), rollback means redeploying the prior known-good
  release's **digest-pinned** image reference (`docs/runbooks/
  PR24_STAGING_DEPLOYMENT_RUNBOOK.md` §3) — no rebuild, no code change,
  just pointing traffic back at a known-good previously-built artifact.
  The commit SHA and its registry tag identify the source revision for
  traceability; the registry digest recorded in that release's evidence
  is the actual artifact redeployed, since a SHA tag is a mutable
  registry pointer and must not be treated as the rollback target
  itself (Fix Round 1, independent review, P1-B).
- **Database compatibility constraint:** an application rollback is
  only safe if the prior application version is compatible with the
  **current** database schema. If the failed deployment included a
  migration, rolling back the application code alone does **not**
  roll back the schema — this is exactly why §20 recommends
  forward-fixing migrations rather than a blind revert.
- **What happens if code rolls back but schema cannot:** the prior
  application version must be able to run against the newer schema
  (this is why this repository's migrations are additive-first, per
  `docs/audits/04-consolidated-implementation-plan.md` Part E's own
  "General rule applied throughout" — new columns/objects alongside
  old ones, removal deferred to a later cleanup migration) — if a
  specific migration ever breaks this additive-compatibility
  assumption, that migration's own review must flag it explicitly
  before it merges, a standing repository discipline this document
  does not change.
- **Immutable deployment artifact identification:** the commit SHA
  used to build the artifact is the same SHA this repository's entire
  governance process already tracks as the "real squash-merge SHA" for
  every PR — no new identification scheme is introduced.

**This is never conflated with AppSheet source-of-truth rollback** —
an application-version rollback (this section) can happen at any time,
for any deployed version, entirely independent of whether a real
cutover has occurred; the PR23 runbook's rollback sections only apply
once T0 (stopping AppSheet writes) has actually happened.

---

## 22. Observability Gaps

Per §5: structured JSON logging with request/correlation IDs already
exists (PR15A). **The following remain open, unscheduled Roadmap PR15
scope, and are treated by this document as genuine Production
blockers, not already-delivered capability:**

- Application metrics (request rates, latencies, error rates).
- Distributed tracing.
- Dashboards.
- Centralized log aggregation (today, logs go to container stdout only
  — durable only as long as the selected platform retains them).
- Alerting (no mechanism today notifies anyone of an error spike, a
  failed health check, a failed backup, or the scheduler-duplication
  risk in §5 actually firing).
- Database health/capacity alerting (connection-pool exhaustion,
  storage nearing capacity).
- Backup-failure alerting — directly required to make §11's
  "responsible person" role actually effective (a silent backup
  failure with no alert defeats the entire backup design).

**Recommendation:** close the minimum viable subset before Production
go-live (not before this document's own merge): uptime monitoring
against the liveness endpoint (`GET /api/v1/health`, §15) **and**
against the fail-closed readiness endpoint (§15A) with alerting on
either failing, and backup-failure alerting (§11) at minimum — both of which
most Option A managed platforms provide as a built-in or low-effort
add-on, reducing the amount of new engineering this actually requires.
Metrics/tracing/dashboards remain valuable but are not blocking at
~8-user scale and can be deferred to a genuine future PR15 slice,
consistent with `docs/ROADMAP.md`'s own existing note that this scope
is "pending a future slice or an explicit governance decision to
remove them."

---

## 23. Security Requirements

- **HTTPS only** — §9, no exceptions.
- **Secure secret configuration** — §16, already partly enforced in
  code (`validate_production_secrets`).
- **CORS** — §9, exact production origin(s) only.
- **Auth token security** — the existing JWT access/refresh model
  (`backend/app/core/security.py`, `backend/app/api/v1/auth.py`) is
  unchanged by this document; production deployment must set
  `ENVIRONMENT=production` so the refresh-token cookie's `secure` flag
  actually takes effect (§9).
- **Rate limiting** — not currently implemented anywhere in this
  codebase; at ~8 users, not a blocking gap, but worth a lightweight
  edge-level rate limit (many Option A platforms offer this
  natively) as defense-in-depth against credential-stuffing on the
  login endpoint specifically — a low-effort addition, not a new
  subsystem.
- **Security headers** — `frontend/nginx.conf` already sets
  `X-Content-Type-Options`/`X-Frame-Options`/`Referrer-Policy` (§5); a
  `Content-Security-Policy` and `Strict-Transport-Security` header
  should be added at the production edge once the real hostname/TLS
  setup (§9) is finalized — deferred, not designed in full here, since
  a CSP's exact value depends on the final hosting class's own
  asset-serving specifics.
- **Dependency/image scanning** — not currently part of
  `.github/workflows/ci.yml`; a low-effort addition to the CI pipeline
  (§18) worth including in the same PR that builds the CD pipeline,
  not a separate large effort.
- **DB network exposure** — §10, never public.
- **Backup encryption** — §11.
- **Least privilege** — §10 (DB role), §16 (every credential).
- **Admin access** — §17's bootstrap design already builds in
  least-exposure (one account, generated secret, forced rotation
  recommended).
- **Audit retention** — §26, unchanged from existing PR3/PR20-23
  contracts.

**No security theater is added** — every item above traces to a
concrete threat already implied by "internet-facing application
handling operational hospital equipment data," not a generic checklist
item without justification, per the task's own explicit instruction.

---

## 24. Data Retention

No existing retention contract is changed or shortened by this
document:

- **Audit records** — retained per the existing audit framework
  (`docs/ARCHITECTURE_DECISIONS.md`, "Reusable audit framework
  boundary") — unchanged.
- **Import source artifacts** (`ImportSourceBlob`) — retained per
  PR19–PR21's own existing retention design
  (`IMPORT_RETENTION_DAYS`, currently 180 days post-terminal,
  deployment-configurable) — unchanged.
- **Legacy evidence** (`LegacyMigrationAuthority`, reconciliation
  runs/findings/sign-offs) — permanent, per PR21-PR22's own established
  evidence-permanence discipline — unchanged.
- **Cutover evidence** (`CutoverReadinessRun`, `CutoverGoNoGoDecision`)
  — permanent/immutable, per PR23B-D's own established discipline —
  unchanged.
- **Operational transaction history** — permanent, no deletion
  mechanism exists or is proposed.
- **Logs** — retention depends on the selected platform's own log
  ingestion/storage policy (§22) — a configuration choice at
  provider-selection time (OD-PR24-1), not a new application-level
  retention contract.
- **Backups** — retention is the one genuinely new retention question
  this document raises, and it is explicitly escalated as **OD-PR24-3**
  (§28), not invented here.

**This document proposes deleting nothing** that any existing PR20-23
contract requires to be kept.

---

## 25. Staging / UAT Plan

Before Pilot may begin, the following must be proven against a
Staging/UAT deployment (§19) — **not claimed passed by this document**:

- [ ] Production-like deployment (same images, same architecture
      class as the Production target).
- [ ] Migrations apply cleanly (`alembic upgrade head`, §20).
- [ ] `GET /api/v1/health` (liveness) reports healthy.
- [ ] The fail-closed readiness endpoint (§15A) returns 200 when
      dependencies are healthy, and a non-2xx status when PostgreSQL
      is made unreachable in a controlled Staging test — proving the
      fail-closed contract actually holds, not merely that the happy
      path returns 200.
- [ ] Login and role-based authorization correct for all three roles.
- [ ] BCM Code lookup.
- [ ] Item Number QR lookup.
- [ ] Issue workflow.
- [ ] Receive (usable) workflow → `AVAILABLE_AT_POOL`.
- [ ] Receive (defective) workflow → `UNAVAILABLE_DEFECTIVE`, verified
      only through the approved non-production procedure
      (`docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §15) — never a
      fabricated defective event even in Staging.
- [ ] Import/reconciliation visibility (PR20-22 frontend).
- [ ] Cutover-readiness UI (PR23E) reachable and functional.
- [ ] Go/No-Go workflow (PR23D/E) exercised end-to-end in Staging at
      least once, against Staging's own evidence — not Production's.
- [ ] Audit records generated for every action above.
- [ ] Concurrency tests (the existing PostgreSQL-marked backend test
      suite) pass against the Staging database configuration.
- [ ] Backup + restore rehearsal performed against Staging (§11) —
      this is the actual rehearsal referenced throughout this
      document; Staging is where it happens, never Production.

**UAT PASS is not declared by this document.** This checklist defines
what must be true; execution is a future, separate activity.

---

## 26. Pilot Deployment Plan

Consumes `docs/runbooks/PR23_CUTOVER_RUNBOOK.md` §12 as the
authoritative Pilot business procedure — **this document does not
restate or alter its business rules** (one controlled Pilot Ward, no
fixed calendar duration, exit-by-evidence, no fabricated defective
events). This section adds only the deployment-specific considerations
the runbook itself does not cover:

- **Environment:** Production (§19) — no separate Pilot environment,
  scoped by Ward, per §19's own derivation from OD-PR23-5.
- **Access URL:** the real production hostname (§9), once assigned —
  no separate Pilot-only URL, since Pilot runs in Production.
- **Support coverage:** the "Equipment Pool lead" and "Pilot Ward
  contact" roles already named in the runbook's own contact matrix are
  the first line of support; the "Incident escalation contact" role
  (also already named there) is the deployment-level escalation path
  if a genuine application/infrastructure incident occurs during
  Pilot.
- **Logging:** the same production logging/observability stack (§22)
  applies during Pilot — no separate Pilot-only logging configuration.
- **Rollback of application version:** governed by §21 (application
  rollback), entirely independent of the runbook's own operational
  rollback (§9/§10 there), since Pilot occurs *after* T4 (application
  already activated) in the runbook's own T0-T4 sequencing.
- **Incident handling:** any genuine application/infrastructure
  incident during Pilot follows §21 (if it's a deployed-version
  problem) or the runbook's own §10 forward-fix procedure (if it's an
  operational/data problem) — this document does not create a third,
  competing incident process.

**Pilot is not executed by this document.**

---

## 27. Production Go-Live Plan — Mapping to PR23 T0–T4

This document keeps **infrastructure deployment** and **operational
cutover** as two explicitly separate concerns, per the task's own
instruction, and does not rewrite `docs/runbooks/
PR23_CUTOVER_RUNBOOK.md`'s own business rules:

```
[Infrastructure deployment — this document's own scope]
  Production environment provisioned (§7, per OD-PR24-1)
  → Secrets configured (§16)
  → Database migrated to the intended head (§20)
  → Application deployed and readiness-verified (§15, §15A, §18 — the
    fail-closed readiness endpoint reports 200, not merely the
    liveness endpoint)
  → Backup/restore rehearsed against Staging at least once (§11, §25)
  → Observability minimum viable subset in place (§22)
  (Application infrastructure MAY be deployed before T0 — the runbook's
  T0 is about stopping AppSheet writes, not about when the new
  application's infrastructure first exists.)

[Operational cutover — docs/runbooks/PR23_CUTOVER_RUNBOOK.md's own scope, unchanged]
  T0 — stop AppSheet writes
  T1 — capture final legacy data (if needed)
  T2 — final validation (Gates B-E)
  T3 — Go/No-Go decision (Gate G)
  T4 — activate operational use
```

**This document does not alter the runbook's T0-T4 procedure, its
Gates A-F/G semantics, its rollback boundary (OD-PR23-4), its Pilot
rules (OD-PR23-5), or any other PR23 business rule.** It only clarifies
that the infrastructure the runbook's T0-T4 sequence *runs on top of*
must already exist, be migrated, and be verified **ready** (§15A —
the fail-closed readiness endpoint, not merely a liveness check)
**before** T0 is even attempted — Gate A (`docs/design/PR23_CUTOVER_READINESS_PLAN.md`
§12) already requires exactly this ("required PRs merged... CI green
on the exact deployed head, database migrations applied and verified...
production configuration validated... backup/restore procedure
validated"), and this document is what finally gives Gate A's
backup/restore and production-configuration clauses a concrete design
to be validated against.

---

## 28. Owner Decisions Raised by This Round

Following this repository's `OD-PR<n>-<m>` numbering convention (not
the task prompt's own illustrative `OD-NEXT-*` placeholders), scoped
to Roadmap PR24 exactly as OD-PR23-1 through OD-PR23-6 were scoped to
PR23. **This document, as originally written, did not approve any of
these itself. The PR24 Owner Decision Closure round (below) records
the Owner's approval of all six.**

- **OD-PR24-1 — Production hosting architecture/provider selection.**
  *Question:* Within the recommended architecture class (§7, Option A
  — managed application platform + managed PostgreSQL), which specific
  provider should be used? Or does the Owner prefer Option B (managed
  VPS/VM with the existing `docker-compose.prod.yml` overlay) instead,
  e.g. due to cost preference or an existing vendor relationship?
  *Options:* Option A (recommended, §7); Option B (viable alternative,
  §6); Option C (not recommended without a confirmed hospital IT
  commitment, §6); Option D (not recommended, §6).
  *Trade-offs:* see the comparison tables in §6.
  *Recommendation:* Option A; a specific provider is not recommended
  by this document (§31's own instruction against provider marketing
  bias) — provider research is a genuine next step *after* this
  Owner Decision confirms the architecture class.
  *Consequence if unresolved:* no infrastructure can be provisioned;
  §17/§29's proposed "Deployment Foundation" slice has no concrete
  target to build against.
  *Status:* **RESOLVED / OWNER APPROVED** (PR24 Owner Decision
  Closure round).
  *Approved choice:* **Option A — Managed Application Platform +
  Managed PostgreSQL**, exactly per Recommendation. This approves the
  architecture *class*, not a specific commercial provider — provider
  evaluation/selection may happen during the Deployment Foundation
  (PR24B) work, provided the selected provider stays within this
  approved architecture class. Do not silently substitute a
  self-managed VPS, a hospital-managed server, Kubernetes, or
  unmanaged PostgreSQL for this approved class unless a future,
  explicit Owner Decision changes it.

- **OD-PR24-2 — Production access/network model.**
  *Question:* Is public HTTPS with the existing authenticated
  application sufficient, or does the hospital require network-level
  restriction (VPN, IP allowlisting, hospital-network-only access)?
  *Options:* public HTTPS only (recommended default, §8); public HTTPS
  + IP allowlisting (viable hardening layer if the hospital can supply
  a stable IP range); VPN-gated access (adds a client-side requirement,
  §8); hospital-network-only (requires unconfirmed hospital IT
  capability).
  *Recommendation:* public HTTPS, optionally IP-allowlisted.
  *Consequence if unresolved:* the network/firewall configuration for
  whichever provider is selected under OD-PR24-1 cannot be finalized.
  *Status:* **RESOLVED / OWNER APPROVED** (PR24 Owner Decision
  Closure round).
  *Approved choice:* **Public HTTPS with the existing application
  authentication**, exactly per Recommendation, as the baseline
  production access model. IP allowlisting may be added later as
  optional hardening if the hospital supplies stable source IP ranges.
  VPN, a native client, installed hospital software, or
  hospital-network-only access are **not** required unless a future,
  explicit operational requirement changes this decision. HTTPS
  remains mandatory regardless (§9).

- **OD-PR24-3 — Backup RPO/RTO and retention targets.**
  *Question:* What is an acceptable data-loss window (RPO) and
  recovery-time target (RTO) for this application, and how long must
  backups be retained?
  *Options:* cannot be enumerated from repository authority — a pure
  operational/risk-tolerance input, the same category §26 of
  `docs/design/PR23_CUTOVER_READINESS_PLAN.md` used for OD-PR23-5's
  Pilot-duration question (not derivable from source code).
  *Recommendation:* none — genuinely an Owner input.
  *Consequence if unresolved:* §11's backup design has evidence
  fields with no target to be measured against; Gate A's "backup/
  restore procedure validated" clause has no pass/fail criterion.
  *Status:* **RESOLVED / OWNER APPROVED — targets only** (PR24 Owner
  Decision Closure round).
  *Approved choice:* **RPO ≤ 1 hour; RTO ≤ 4 hours; backup retention
  30 days.** These are targets, not a claim that they are already met
  — **Production GO remains blocked until a real backup/restore
  rehearsal (§11, PR24C) is completed and its evidence demonstrates
  the restore procedure actually meets the approved RTO target.** No
  rehearsal has occurred as of this closure round, and current
  infrastructure is not claimed to already satisfy these targets.

- **OD-PR24-4 — Staging/UAT environment topology confirmation.**
  *Question:* Does the Owner agree with §19's recommendation of
  exactly three environments (Development, Staging/UAT, Production),
  with Pilot running inside Production per OD-PR23-5's own already-
  approved model (no separate Pilot environment)?
  *Options:* accept §19's three-environment recommendation
  (recommended); introduce a fourth, dedicated Pilot environment
  (not recommended — would require a disconnected second copy of
  Equipment Master data, contradicting Gate B/E's evidence model,
  §19).
  *Recommendation:* accept §19 as designed.
  *Consequence if unresolved:* the CI/CD pipeline (§18) has an
  ambiguous number of deploy targets to build.
  *Status:* **RESOLVED / OWNER APPROVED** (PR24 Owner Decision
  Closure round).
  *Approved choice:* **Three environments — Development, Staging/UAT,
  Production** — exactly per Recommendation, no dedicated fourth Pilot
  environment. Pilot runs inside Production, scoped to the approved
  controlled Pilot Ward model from OD-PR23-5. Pilot is not
  reinterpreted as synthetic-only testing, a separate database, or a
  fourth environment; the existing PR23 Pilot business rules (§26)
  remain unchanged.

- **OD-PR24-5 — Production domain/DNS ownership.**
  *Question:* What is the real production hostname, and who controls
  the DNS zone it will be delegated from (the hospital's own domain,
  or a domain the project owner controls)?
  *Options:* cannot be enumerated from repository authority — genuinely
  unconfirmed.
  *Recommendation:* none — Owner/hospital-IT input required.
  *Consequence if unresolved:* §9's TLS/domain design has only a
  placeholder to work with; go-live cannot proceed without a real,
  resolvable hostname.
  *Status:* **RESOLVED / OWNER APPROVED — explicit hostname-deferral
  policy** (PR24 Owner Decision Closure round). The Owner Decision
  itself — the *policy* governing production hostname strategy and
  timing — is fully resolved, not partially open; only the *concrete
  hostname value* is deferred, and that deferral is itself the
  resolution, not a symptom of the decision remaining unresolved.
  *Approved choice:* The Owner approves an explicit hostname-deferral
  policy:
  - The provider-managed HTTPS hostname (from the architecture
    selected under OD-PR24-1) is acceptable for Staging and for the
    initial Deployment Foundation (PR24B) — no custom domain is
    required to begin PR24B, PR24C, or PR24D.
  - The Owner currently has no custom production domain; this policy
    does not invent, purchase, register, or configure one.
  - The **concrete future production hostname is a Production-Go-Live
    execution/configuration input, not an unresolved architecture or
    Owner Decision.** It must be selected, DNS-delegated, TLS-
    validated, and recorded as evidence **before Production Go-Live**
    (§27) — this is a Go-Live *execution prerequisite*, distinct from,
    and never conflated with, the Owner-Decision implementation gate
    this §28 governs.
  - Selecting that concrete hostname later, under this already-
    approved policy, does **not** reopen OD-PR24-5 and requires no
    further Owner approval — a new Owner Decision would only be
    needed if a future proposal changed the underlying architecture
    itself (e.g. abandoning managed-provider hosting, requiring
    VPN-only or hospital-network-only access, or dropping mandatory
    HTTPS), none of which this policy does.
  - TLS/HTTPS remains mandatory at every stage (§9) regardless of
    which hostname is in use.
  *Rationale:* the architecture decision is the hostname *strategy and
  timing boundary* (provider hostname now, custom hostname required
  before Go-Live) — the concrete DNS name itself is an operational
  value supplied later under that already-resolved policy, exactly as
  OD-PR24-1 resolves the hosting *architecture class* without resolving
  the eventual concrete provider account.

- **OD-PR24-6 — Production support/incident ownership.**
  *Question:* Beyond the operational roles `docs/runbooks/
  PR23_CUTOVER_RUNBOOK.md` §1 already names for the cutover event
  itself, who is the ongoing, ordinary-business-hours (and after-hours,
  if applicable) support/incident owner for the *deployed application*
  once it is in continuous Production use — distinct from the one-time
  cutover contact list?
  *Options:* cannot be determined from repository authority.
  *Recommendation:* none — Owner input required; likely the same
  individual(s) already named as "Deployment/technical contact" and
  "Incident escalation contact" in the runbook's contact matrix, but
  this must be explicitly confirmed as an *ongoing* responsibility, not
  assumed to end when the cutover event itself concludes.
  *Consequence if unresolved:* §22's alerting design has no confirmed
  recipient; an incident could fire an alert nobody is designated to
  receive.
  *Status:* **RESOLVED / OWNER APPROVED** (PR24 Owner Decision
  Closure round).
  *Approved choice:* **The project Owner is the Primary Technical /
  Support / Incident Owner** for the Medical Equipment Pool system —
  recorded as an ongoing *operational* responsibility, not as a new
  application role, a new authorization role, or a database user type;
  the existing application roles (§17 and elsewhere) are unchanged.
  After-hours or deputy coverage is not yet defined and is **not**
  fabricated here — the Primary Technical Owner is confirmed as the
  first-line ongoing technical and incident responsibility; any
  after-hours/deputy scheme remains a future, explicit decision if and
  when it becomes necessary.

**No new Owner Decision is raised for object storage (§12) or Redis
(§13)** — both are resolved directly by repository runtime evidence,
not by operational/risk-tolerance judgment, so they do not meet this
repository's own "only decisions that materially affect architecture
and cannot be derived from source" bar (the same bar
`docs/design/PR23_CUTOVER_READINESS_PLAN.md` §26 applied).

**Implementation authorization gate (fail-closed):** No PR24B or later
implementation slice may begin until all six Owner Decisions above are
resolved. **OD-PR24-1 through OD-PR24-6 are Owner-approved above, and
the PR24 Owner Decision Closure round is itself merged** (GitHub PR
#130, squash SHA `f64f7d148ba956adef43c5d363ad52680398541c`) — per this
repository's standing process (mirroring `docs/design/
PR23_CUTOVER_READINESS_PLAN.md` §27's own governing pattern), this gate
is satisfied and **PR24B is authorized to proceed from that baseline**,
governed by this §28 together with the approved choices recorded
above. **This gate and OD-PR24-5's Production-Go-Live hostname
prerequisite are two distinct checkpoints, never conflated:** the
**Owner-Decision Gate** (this paragraph) controls whether PR24B
implementation may begin, and is satisfied in full by this closure
round's merge — the still-undetermined concrete production hostname
does **not** re-block it. The **Production-Go-Live Prerequisite**
(OD-PR24-5, §27) separately controls whether PR24G / actual Production
Go-Live may proceed, and requires the concrete hostname to be selected,
DNS-delegated, and TLS-validated by that later point. The
readiness/liveness probe contract (§15A) and the PostgreSQL/Redis
readiness semantics it defines are unchanged by this closure round and
are not reopened here.

---

## 29. Proposed Roadmap Sequence

**Per the task's own explicit instruction, this document proposes a
new Roadmap sequence — it does not assume PR24 was previously
authoritative beyond the one-line placeholder confirmed in §1.**

Because no PR24 implementation contract may begin before OD-PR24-1
through OD-PR24-6 are resolved (mirroring PR23's own fail-closed
"all Owner Decisions before any PR23B+ slice" gate,
`docs/design/PR23_CUTOVER_READINESS_PLAN.md` §26), the smallest
maintainable next sequence this document proposes is:

- **PR24 (this document)** — Production Deployment & Go-Live
  Architecture Planning. Design and Owner Decisions only. **Merged**
  (GitHub PR #129, squash SHA
  `599478992de363e1eda2fe8005ff79d565dee76d`, including Fix Round 1's
  §15A liveness/readiness contract). **All six Owner Decisions
  (OD-PR24-1 through OD-PR24-6) are Owner-approved (§28) and the PR24
  Owner Decision Closure round is itself merged** (GitHub PR #130,
  squash SHA `f64f7d148ba956adef43c5d363ad52680398541c`). **PR24
  overall (architecture + Owner Decisions) is complete** — PR24B is
  eligible to start from that baseline (§28's own fail-closed gate,
  now released).
- **PR24B — Deployment Foundation** *(complete — GitHub PR #131, squash
  SHA `d4a40349f62d76d129dcc6f1feea3e7e8fc8f28d`)*: configures secrets
  (§16), builds the safe admin-bootstrap mechanism (§17), builds the
  fail-closed readiness endpoint (§15A) alongside the existing liveness
  endpoint, closes the scheduler single-instance gap (§15) at the
  deployment-configuration level (`backend/Dockerfile` `--workers 1`,
  `docker-compose.prod.yml` `replicas: 1`). Redis remains retained but
  non-critical to readiness (§13, §15A.3); no MinIO/S3 production
  dependency (§12); the provider-supplied HTTPS hostname remains
  acceptable (OD-PR24-5). **Provisioning the selected architecture's
  actual infrastructure (OD-PR24-1) was explicitly out of this slice's
  scope** — no cloud account, paid resource, domain, or DNS record was
  created by PR24B; it prepared the deployable configuration only. No
  Pilot/Production traffic was served by this slice.
- **PR24C — Backup & Restore** *(complete — GitHub PR #132, squash SHA
  `cd9764ef5ba5e56062ee41266c8d96e50f1152c0`)*: built and proved the
  backup/restore/prune tooling (§11) — a real `pg_dump`/`pg_restore`
  round trip against ephemeral CI-provisioned PostgreSQL databases,
  plus the operator runbook and rehearsal evidence template
  (`docs/runbooks/PR24_BACKUP_RESTORE_RUNBOOK.md`), and a Fix Round 1
  correcting the same-source restore guard to be unconditional
  (manifest-derived, not gated on an optional CLI flag). **This proved
  the tooling, not operational readiness** — a real rehearsal against a
  genuine Staging-class environment remains deferred until PR24D's own
  Staging environment is real (§13 of this document's proposed
  sequence), matching every existing PR20-23 evidence/retention
  contract (§24) unchanged.
- **PR24D — CI/CD & Staging** *(code/tooling complete — merged, GitHub
  PR #133, squash SHA `84144f096aacb9e2687422c7cd84cc1354346aa7`)*:
  built the immutable-artifact CD mechanism (§18), including two
  independent-review fix rounds (CRITICAL image-scan hard-gating +
  digest-pinned artifact identity; a `workflow_dispatch` shell-injection
  fix), and proved it against an ephemeral, CI-provisioned target — the
  environment PR24C's tooling will genuinely be rehearsed against once
  real Staging infrastructure is provisioned under a selected provider
  (OD-PR24-1's architecture class is approved; the specific vendor is
  not yet selected). **This does not itself stand up real, persistent
  Staging infrastructure, and the manual `cd-staging.yml` workflow has
  not yet been executed even once** — see `docs/runbooks/
  PR24_STAGING_DEPLOYMENT_RUNBOOK.md` §0's explicit "CD mechanism proof"
  vs. "real Staging environment exists" distinction.
- **PR24E — UAT Readiness** *(proposed, not started)*: execute and
  record the §25 checklist against Staging — the first point at which
  this repository can honestly claim UAT evidence exists.
- **PR24F — Pilot Execution** *(proposed, not started; operational
  execution, likely governance/runbook-tracked rather than a
  code-changing PR)*: execute Pilot per `docs/runbooks/
  PR23_CUTOVER_RUNBOOK.md` §12 and this document's §26.
- **PR24G — Production Go-Live Governance** *(proposed, not started;
  operational execution)*: execute T0-T4 per the runbook, using the
  infrastructure PR24B-D established.

**This sequence does not combine architecture selection and live
production provisioning into one giant PR**, per the task's own
explicit instruction — PR24 (this document) is architecture/decisions
only; PR24B is the first slice that touches real infrastructure, and
only after OD-PR24-1 is resolved.

**This is a proposal, subject to Owner approval — not a binding
commitment**, exactly as `docs/design/PR23_CUTOVER_READINESS_PLAN.md`
§27 itself states about its own slice sequence. Repository needs
discovered during PR24B may justify collapsing or further splitting
these.

---

## 30. Non-Goals

- No production infrastructure is provisioned by this document.
- No credential, secret, or DNS record is created.
- No cloud account is mutated.
- No commercial provider is selected (§7, §28 OD-PR24-1).
- No backend, frontend, or migration code is changed.
- No new Owner Decision is raised for choices repository evidence
  already resolves (§12, §13, §28's own closing note).
- No PWA/offline scope is added (§14).
- No frontend or backend redesign (§34).
- No Ward-transfer workflow, MEMS, Recall Monitor, patient tracking,
  or QR redesign is introduced or implied anywhere in this document
  (§33/§34 — unchanged from every prior PR23-round commitment).
- Pilot and Production execution are not performed by this document —
  only planned for.

---

## 31. Acceptance Criteria for This Round

This document (and its accompanying governance sync, §2) is complete
when:

- Repository authority for PR24 is quoted exactly and its
  "placeholder only, no architecture" status is explicit (§1).
- The PR23F merge is recorded as the new baseline across every
  governance file this repository's own process requires (§2, §29 of
  the design-doc-writing task itself — enumerated in the PR).
- Every one of the task's required design areas (§4-§26 of this
  document) is addressed with either a concrete recommendation or an
  explicit Owner Decision, never a fabricated claim of completion.
- No runtime file is touched (verified via `git status`/`git diff
  --check`).
- No real credential, domain, or provider selection appears anywhere
  in this document.
- The proposed Roadmap sequence (§29) is explicitly marked as a
  proposal, not an authoritative commitment.
