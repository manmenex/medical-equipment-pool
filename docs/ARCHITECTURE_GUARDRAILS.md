# Architecture Guardrails

**Purpose:** Concise prohibitions and invariants for design, implementation, and review
**Authority:** Summary of `AGENTS.md`, active decisions, and Roadmap boundaries; linked sources control detail
**Update trigger:** Approved domain, architecture, security, or Roadmap-boundary change
**Maintainer:** Architecture Owner

## Scope and domain

- Do not implement a later Roadmap PR early. Use the assigned section of
  [`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md).
- Do not create missing Role CRUD, User delete, or master-data update/delete
  endpoints solely to obtain audit coverage.
- Do not mix patient tracking into the Equipment Pool: no patient name, HN/MRN,
  bed number, named borrower, or patient movement.
- Do not track inter-ward transfers. Record only the first receiving ward.
- Do not treat ward staff/requestors as application users. Authenticated
  Equipment Pool operators record transactions.
- Do not add a cleaning state, cleaning-complete action, or cleaning workflow.
- Do not change confirmed equipment states, transaction states, Shift Session,
  or Standby Snapshot concepts without approved governance.
- Do not infer current workflow from confirmed future work. Current/future
  boundaries are defined in [`HOSPITAL_DOMAIN_MODEL.md`](HOSPITAL_DOMAIN_MODEL.md).

## Architecture and data integrity

- Do not create parallel audit, database-access, state-transition, or workflow
  mechanisms when an authoritative path exists.
- Do not move transaction/commit boundaries casually. Identify all business,
  status-history, and audit writes that must succeed or fail together.
- Mandatory audit writers use the caller's `AsyncSession`, flush without an
  independent commit, and preserve atomic rollback.
- Do not edit applied migration history casually. Use additive-first revisions,
  preserve rows, and test real upgrade/downgrade paths.
- Do not rely on `Base.metadata.create_all()` as proof that historical Alembic
  revisions work; the current `0001_initial.py` behavior is tracked debt.
- Do not add unbounded collection reads, client-controlled stored values, or
  nondeterministic pagination.
- Do not invent server, network, SSH, database, or deployment access to
  hospital-managed infrastructure. Production must remain managed-platform portable.
- Do not include unrelated refactoring in a focused feature, fix, migration, or security PR.

## Security and privacy

- Never commit credentials, PATs, JWTs, database passwords, private keys, or
  secret values. Examples and fixtures use clearly non-production placeholders.
- Never expose secrets through PR descriptions, logs, screenshots, test output,
  exception payloads, or audit before/after data.
- Central secret redaction is recursive and mandatory; endpoint authors are not
  the sole control.
- Unknown failed-login identifiers are not stored raw, deterministically hashed,
  or persisted in any enumerable/correlatable form. Actor and subject remain
  null for an unknown account. A keyed HMAC requires a separately approved
  secret-management and retention design and is not part of Roadmap PR3.
- Client request/correlation IDs and request metadata are bounded, validated,
  and safe for persistence. Do not trust proxy-forwarding headers without an
  explicit trusted-proxy design.

See the detailed audit decision in
[`adr/ADR-0001-canonical-audit-and-failed-login-identifiers.md`](adr/ADR-0001-canonical-audit-and-failed-login-identifiers.md).

## Evidence and environment

- Do not claim CI evidence when only local commands ran.
- Do not call SQLite evidence PostgreSQL evidence.
- Do not call code inspection an executed test.
- Do not claim deployment or production readiness without the corresponding
  environment, recovery, monitoring, and approval evidence.
- Machine-specific absolute paths, credentials, and transient environment state
  do not belong in permanent project instructions.
- Docker/test credentials remain development-only and untracked.
- Dependency vulnerabilities receive focused assessment; do not automatically
  broaden upgrades across unrelated packages.

## Change control

- Roadmap scope change → Governance PR.
- Architecture/security invariant change → Architecture Decision update and,
  when cross-cutting or high-risk, a detailed ADR.
- Status change → `ROADMAP_STATUS.md` after the event.
- Historical finding → retain it; add current resolution elsewhere.
- Out-of-scope defect → document, assess severity, and route to a focused
  follow-up. Do not weaken tests or silently expand the current PR.

The full repository-wide domain list remains in [`AGENTS.md`](../AGENTS.md);
active rationale remains in
[`ARCHITECTURE_DECISIONS.md`](ARCHITECTURE_DECISIONS.md).
