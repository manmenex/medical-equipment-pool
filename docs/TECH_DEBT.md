# Technical Debt Register

**Purpose:** Single home for evidenced deferred defects and structural risk
**Authority:** Debt tracking only; not a Roadmap or feature backlog
**Update trigger:** Debt discovered, severity/status changed, or closure verified
**Maintainer:** Architecture Owner

Roadmap work is not technical debt merely because it is unimplemented. Accepted
limitations are labeled explicitly. A debt item closes only after its stated
verification passes.

## Register

| ID | Title | Severity | Status | First identified | Related work | Owner role | Last reviewed |
|---|---|---|---|---|---|---|---|
| TD-001 | Equipment update/status response `MissingGreenlet` | High | Open | PR #7 test-writing | Draft PR #7 known limitation #6 | Backend Engineer | 2026-07-17 |
| TD-002 | `0001_initial.py` uses current ORM metadata | High | Open | PR #7 migration review | `0001_initial.py`; Governance PR #8 | Database Engineer | 2026-07-17 |
| TD-003 | No required PostgreSQL CI workflow | Medium | Open | PR #7 evidence review | PostgreSQL tests exist; `.github/workflows` absent | Repository Owner | 2026-07-17 |
| TD-004 | Naive `datetime.utcnow()` usage | Low | Open | Governance Pack inventory | Multiple backend models/services | Backend Engineer | 2026-07-17 |
| TD-005 | Temporary default/long-lived branch structure | Medium | Open | Repository cleanup assessment | Recall default; `claude/*` active base | Repository Owner | 2026-07-17 |

## TD-001 — Equipment update/status response `MissingGreenlet`

- **Description:** Existing equipment update and status-change endpoints can
  commit successfully and then return HTTP 500 when serialization touches an
  expired `updated_at` value outside the async greenlet context.
- **Operational impact:** Clients see failure after a successful mutation and
  may retry, causing confusion or duplicate user intent.
- **Why deferred:** Discovered while testing audit behavior; unrelated to the
  focused PR3 audit framework and explicitly left out of Draft PR #7.
- **Resolution trigger:** Focused backend bugfix PR before workflow/UI relies on
  these responses.
- **Verification to close:** API tests prove success response, committed row,
  exactly one audit event, and safe retry behavior for update/status endpoints.

## TD-002 — `0001_initial.py` uses current ORM metadata

- **Description:** Migration `0001_initial.py` calls
  `Base.metadata.create_all()`, so its result changes with current ORM models
  instead of remaining a frozen historical schema.
- **Operational impact:** Fresh-database and incremental upgrade paths differ;
  later revisions need defensive idempotency and downgrade testing.
- **Why deferred:** Rewriting migration history inside PR3 would broaden scope
  and risk existing databases.
- **Resolution trigger:** Dedicated migration-baseline strategy approved before
  migration complexity materially increases.
- **Verification to close:** Rehearse fresh install, pre-baseline upgrade,
  downgrade, and data preservation on PostgreSQL; document the cutover and
  retained compatibility path.

## TD-003 — No required PostgreSQL CI workflow

- **Description:** PostgreSQL-backed tests exist, but the repository currently
  has no tracked GitHub Actions workflow requiring them on PRs.
- **Operational impact:** PR descriptions may report local PostgreSQL evidence,
  but the repository does not independently enforce it.
- **Why deferred:** CI infrastructure is outside Roadmap PR3 and this Governance
  Pack; local evidence is still useful when labeled accurately.
- **Resolution trigger:** Repository Owner approves CI design and stable test
  service setup.
- **Verification to close:** Protected default branch requires a successful
  PostgreSQL job that runs real migrations and relevant integration tests.

## TD-004 — Naive `datetime.utcnow()` usage

- **Description:** Models/services/scheduler use `datetime.utcnow()`, which
  produces naive UTC values and is deprecated in modern Python guidance.
- **Operational impact:** Future runtime warnings and timezone ambiguity during
  comparison/serialization.
- **Why deferred:** Mechanical replacement across many modules is unrelated to
  current focused PRs and needs regression coverage.
- **Resolution trigger:** Focused datetime/timezone hardening PR or runtime
  upgrade that makes warnings blocking.
- **Verification to close:** Timezone-aware UTC tests pass across auth,
  transactions, audit, equipment deletion, and scheduler behavior.

## TD-005 — Temporary default/long-lived branch structure

- **Description:** GitHub default still names the legacy Recall application;
  active Equipment Pool work uses a temporary `claude/*` base.
- **Operational impact:** Confusing clone defaults, PR bases, branch protection,
  and repository identity.
- **Why deferred:** PR #7 remains open and default-branch mutation requires a
  separate recoverable maintenance operation.
- **Resolution trigger:** Governance Pack and active PRs complete; Repository
  Owner executes `REPOSITORY_STRATEGY.md` transition plan.
- **Verification to close:** `main` is protected/default, open PRs are correctly
  based, archive tags exist, legacy branches pass retention checks, and rollback
  is documented.
