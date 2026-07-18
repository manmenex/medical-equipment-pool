# Architecture Decisions

A running log and index of confirmed project-level decisions. Short decisions
remain here; detailed records are added only for cross-cutting, security-
sensitive, costly-to-reverse, or migration-sensitive choices.

Detailed ADRs use stable, zero-padded numbers and are never renumbered. A
superseding ADR records the replacement instead of rewriting history.

**Topic ownership:** as of the Knowledge Layer (`../knowledge/`), some
topics are owned by a second ADR set at `../knowledge/adr/` instead of this
file — see `PROJECT_PLAYBOOK.md`'s topic-ownership table for the definitive,
single-source map of which document governs which topic. This file remains
authoritative for every decision below and for any topic the Playbook's
table does not assign elsewhere.

| ADR | Status | Decision |
| --- | --- | --- |
| [ADR-0001](adr/ADR-0001-canonical-audit-and-failed-login-identifiers.md) | Accepted | Canonical audit writes and failed-login identifier non-persistence |

---

## Browser-first application

**Decision:** The system is a browser-based web application, not a native
desktop or mobile app.

**Status:** Implemented.

**Rationale:** Replaces a prior AppSheet-based process; Equipment Pool
staff need a lightweight, install-free client reachable from ordinary
hospital workstations and mobile browsers during rounds.

**Impact:** `frontend/` is a React/TypeScript/Vite single-page app (see
`AGENTS.md`, Repository Layout). No native app shell is planned.

---

## Progressive Web App direction

**Decision:** The frontend is built and configured as a Progressive Web
App (PWA).

**Status:** Implemented.

**Rationale:** Equipment Pool staff need a fast, installable,
offline-tolerant experience for a floor-based, mobile-first workflow
(scanning equipment QR labels during rounds) without requiring an
app-store distribution channel.

**Impact:** `frontend/vite.config.ts` configures `vite-plugin-pwa` with a
web manifest. This also constrains deployment: the app must remain
servable over standard HTTPS from a normal web host (see "Managed
deployment preferred," below) — it cannot depend on a native install
mechanism.

---

## PostgreSQL

**Decision:** PostgreSQL is the system of record.

**Status:** Implemented.

**Rationale:** Needs real relational integrity (foreign keys, unique
constraints, partial indexes for the one-open-dispatch guard) and
production-grade concurrency behavior — not available from the prior
spreadsheet/AppSheet-based process. See "No Spreadsheet database," below.

**Impact:** `docker-compose.yml` runs `postgres:16-alpine`; the backend
connects via `asyncpg`. `docs/audits/01-database-schema-audit.md` and
`docs/audits/04-consolidated-implementation-plan.md` Part E (Migration
Strategy) govern schema evolution. The test suite's PostgreSQL-backed
tests (see `backend/tests/test_postgres_integration.py`) verify behavior
— like foreign-key and SQLSTATE-based constraint enforcement — that
SQLite (used for the fast default test run) does not.

---

## FastAPI backend

**Decision:** The backend is an async FastAPI application.

**Status:** Implemented.

**Rationale:** Async I/O suits the read-heavy dashboard/search workload
alongside bursty write patterns (routine-round dispatch bursts four times
daily); FastAPI's typed request/response contract and automatic OpenAPI
docs reduce integration risk between backend and frontend.

**Impact:** `backend/app/` — layered API → services → CRUD → models
(SQLAlchemy 2.0 async). `docs/audits/02-backend-architecture-audit.md`
covers the architectural review; PR1/PR2 (both merged) hardened its
security and error-handling foundations.

---

## No Spreadsheet database

**Decision:** The hospital's existing spreadsheet/AppSheet-based process
is replaced, not extended or kept as a fallback system of record.

**Status:** Implemented (application layer); inventory **import** from
the existing spreadsheet is still planned (Roadmap PR12).

**Rationale:** A spreadsheet cannot enforce the concurrency guarantees
this workflow needs (one open dispatch per equipment item, one receipt
per open dispatch, unique equipment identifiers per
[`../knowledge/adr/ADR-002-identifier-model.md`](../knowledge/adr/ADR-002-identifier-model.md)) —
see `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §9.

**Impact:** The hospital's existing inventory spreadsheet is a one-time
**data source** for import (see the consolidated plan Part F), not an
ongoing system. No spreadsheet-sync or dual-write mechanism is planned.

---

## Equipment Pool only

**Decision:** Scope is the Equipment Pool's own operation — dispatch and
receipt of pool-owned equipment — not a hospital-wide asset-management
system.

**Status:** Confirmed, implemented. Detailed record:
[`../knowledge/adr/ADR-001-equipment-pool-scope.md`](../knowledge/adr/ADR-001-equipment-pool-scope.md)
(also covers the confirmed exclusion of any equipment-ownership/
assignment model).

**Rationale:** Confirmed hospital scope: "Equipment Pool only (primarily
infusion pumps and select shared equipment)." No MEMS, no hospital-wide
asset lifecycle management.

**Impact:** Directly shapes data-volume assumptions used to prioritize
findings in `docs/audits/04-consolidated-implementation-plan.md` (e.g.
downgrading the exact-`COUNT(*)` and JWT-claim-lookup findings from
High/Medium to P2/P3 — see Part B.2). Also excludes MEMS integration from
the roadmap entirely (`AGENTS.md`, Domain Guardrails).

---

## No patient tracking

**Decision:** The system never stores patient identifiers (name, HN,
MRN, bed number) and does not track patient movement.

**Status:** Confirmed, implemented as a guardrail.

**Rationale:** Out of scope by hospital confirmation; also a data-privacy
boundary — conflating equipment dispatch records with patient data would
create compliance exposure well beyond this system's purpose.

**Impact:** No `borrower_name` or equivalent named-individual field is
required or accepted (removed per Roadmap PR7). Ward-to-ward patient
transfers are explicitly not tracked. Enforced as a standing guardrail in
`AGENTS.md` and checked by the reviewer prompt
(`docs/prompts/codex-pr-review.md`).

---

## No cleaning workflow

**Decision:** The application does not model cleaning as a tracked state
or a separate workflow step.

**Status:** Confirmed, implemented as a guardrail.

**Rationale:** Cleaning is a physical process that may happen before or
after the digital receipt entry; splitting receipt into a two-step
"Return Received" / "Cleaning Confirmed" process (as originally proposed
in `docs/audits/03-hospital-equipment-pool-workflow-audit.md` §6.1) was
explicitly superseded by the hospital's confirmation of a single atomic
receipt operation — see the consolidated plan Part B.1.

**Impact:** Equipment receipt (Roadmap PR8) is one atomic action with a
binary usable/defective outcome. No `PENDING_CLEANING` state, no cleaning
status field, no cleaning-confirmation endpoint exists or is planned.

---

## Shift Session planned

**Decision:** Future implementation will support flexible DAY/NIGHT Shift
Sessions in place of hard-coded routine-round transaction times.

**Status:** Planned — confirmed direction, not yet scheduled to a
specific Pull Request.

**Rationale:** Fixed clock-time rounds (06:00/11:00/15:00/21:00) are an
intentional MVP simplification (Roadmap PR7). The hospital has since
confirmed that actual shift boundaries are flexible in practice, and that
multiple staff may operate within one open shift, each transaction
recording its own authenticated operator rather than relying on the
round-time enum alone.

**Impact:** PR7 is **not** reworked to anticipate this — see the
consolidated plan's PR7 entry for the explicit forward-compatibility
note. A dedicated Shift Session PR will be scheduled once prioritized;
until then, no Shift Session model, endpoint, or migration exists.

---

## Standby Snapshot planned

**Decision:** Future reporting will support Day and Night Standby
Snapshots — department-level equipment-count records.

**Status:** Planned — confirmed direction, not yet scheduled to a
specific Pull Request.

**Rationale:** Operationally distinct from transaction history: a
snapshot is a point-in-time count taken by staff, not something the
system can safely infer by aggregating dispatch/receipt records after
the fact.

**Impact:** No snapshot model, endpoint, or report exists yet. When
scheduled, it will be additive to the reporting surface (Roadmap PR13
territory) rather than a change to the dispatch/receipt transaction
model itself.

---

## Managed deployment preferred

**Decision:** Production deployment must not assume direct access to
hospital-managed servers.

**Status:** Confirmed constraint; current Docker Compose setup (local
Postgres/Redis/MinIO/backend/frontend containers) is a development
convenience, not the confirmed production target.

**Rationale:** Hospital IT environments commonly restrict direct server
access for outside-managed applications; the architecture needs to run on
an approved managed platform (e.g. managed container hosting, managed
Postgres) without requiring privileged access to hospital infrastructure.

**Impact:** No deployment design currently assumes SSH/server access to a
hospital-owned host. The application remains browser/PWA-based (see
above) specifically so it can be hosted on a managed platform and simply
reached over HTTPS. No specific managed platform has been selected yet —
this decision constrains the *shape* of future deployment work, not its
target provider.

---

## Reusable audit framework boundary

**Decision:** Roadmap PR3 owns the reusable audit-logging framework, not
only audit calls for User and master-data endpoints. Its boundary includes
one canonical audit writer; current authentication, User, master-data, and
Equipment coverage; actor-versus-subject attribution; recursive centralized
secret redaction; validated request/correlation IDs; bounded sanitized
User-Agent and direct-peer IP metadata; an additive audit migration;
same-transaction audit atomicity for mandatory business mutations; a
documented persistence strategy for failed-login events; and an
Administrator-only, bounded, deterministically paginated audit read path.

**Status:** Confirmed for Roadmap PR3; implementation is in progress in
Draft GitHub PR #7 and is not yet approved or merged.

**Rationale:** Later roadmap work (ward correction, role consolidation,
inventory import, and future mutating endpoints) needs one trustworthy audit
contract. Per-call-site redaction or parallel writers would make secret
handling, attribution, atomicity, and duplicate-event prevention depend on
each future endpoint author. Request/correlation values are part of that
audit contract because they must be safely persisted and returned, while a
failed login requires an explicit transaction strategy so the failure itself
remains auditable.

**Impact:** Current in-scope endpoints use the shared framework and later
roadmap PRs reuse it. Mandatory business mutations and their audit event use
the same `AsyncSession`; the audit writer flushes without independently
committing, so both commit or roll back together. Login failures have no
actor; a known account may be the subject. For an unknown submitted
identifier, actor and subject/entity ID remain null, and no raw,
deterministic unkeyed-hash, enumerable, or correlatable representation is
persisted. A keyed HMAC would require a separately approved secret-management
and retention design and is not introduced by Roadmap PR3. See
[ADR-0001](adr/ADR-0001-canonical-audit-and-failed-login-identifiers.md).
Client-supplied IDs are allowlisted and limited to 64 characters. Migration
evidence must cover PostgreSQL upgrade/downgrade and the fresh-database
behavior caused by `0001_initial.py` creating from current ORM metadata.

**Scope boundary:** PR3 does not add missing Role CRUD, User DELETE, or
master-data UPDATE/DELETE endpoints. It does not implement transaction
numbers, the equipment identifier model, equipment-state or
dispatch/receipt redesign, Shift Sessions, DAY/NIGHT or Standby work,
inventory import, frontend/reporting, broad observability, mandatory CI,
deployment, or unrelated refactoring.
PR15 retains structured cross-service logging/correlation, metrics, tracing,
alerting, centralized log aggregation, dashboards, and production
observability CI/infrastructure; it must build on PR3's IDs rather than
introducing a second request-context mechanism.

---

## Roadmap-driven development

**Decision:** All implementation work follows the sequenced Pull Request
plan in `docs/audits/04-consolidated-implementation-plan.md`, one PR at a
time, in dependency order.

**Status:** Implemented as a process.

**Rationale:** The domain model has several PRs with hard dependencies
(e.g. the equipment-receipt concurrency fix depends on the 4-state model
landing first); implementing out of order risks rework or an inconsistent
intermediate state during a live pilot.

**Impact:** Enforced via `AGENTS.md` (Scope Discipline, Git Discipline)
and `docs/AI_WORKFLOW.md` (Architecture → Implementation → Draft PR →
Independent Review → Fixes → Final Architecture Review → Merge). Current
status of every PR is tracked in `docs/ROADMAP_STATUS.md`.
