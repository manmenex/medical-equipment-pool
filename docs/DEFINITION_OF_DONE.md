# Definition of Done

**Purpose:** Reusable risk-based completion standard
**Authority:** Minimum completion evidence; assigned Roadmap acceptance criteria remain controlling
**Update trigger:** Quality-gate, evidence, or release-readiness policy change
**Maintainer:** Architecture Owner

Apply only the sections affected by the change. “Not applicable” requires a
reason; it is not a shortcut. Severity definitions and the detailed independent
review format remain authoritative in
[`prompts/codex-pr-review.md`](prompts/codex-pr-review.md).

## Universal requirements

- [ ] Purpose, assigned scope, acceptance criteria, and explicit exclusions match.
- [ ] No later Roadmap work or unrelated refactor was introduced.
- [ ] Changed files are necessary and reviewable; generated/local files are absent.
- [ ] Automated, manual, inspection-only, reported, and unknown evidence are distinguished.
- [ ] Exact test/lint/build commands and results are recorded.
- [ ] Backward-compatibility impact is stated for API, data, configuration, and users.
- [ ] Security/privacy impact and secret/log handling are stated.
- [ ] Known limitations and out-of-scope discoveries are documented without weakening tests.
- [ ] Rollback or forward-fix plan is proportionate to risk.
- [ ] Monitoring/verification after deployment or merge is identified, or marked not applicable.
- [ ] PR description matches the final diff and commit set.
- [ ] Independent review completed by someone other than the implementing agent/session.
- [ ] Critical/High findings are resolved or the Repository Owner explicitly blocks merge.
- [ ] Repository Owner gives final approval and performs/authorizes merge.

## Backend and API

- [ ] Success, validation, authorization, dependency-failure, and regression paths are tested.
- [ ] Status codes and error envelopes remain intentional and documented.
- [ ] Async code does not add blocking I/O/CPU work or unbounded resource lifetimes.
- [ ] Pagination and result bounds exist for collection endpoints.
- [ ] Authentication actor, authorization role, and resource subject are not conflated.
- [ ] Business and audit side effects are verified, including absence on failure.
- [ ] Existing clients are compatible or the contract change and migration path are explicit.

## Database and migrations

- [ ] PostgreSQL-backed evidence exists for PostgreSQL-specific behavior; SQLite alone is insufficient.
- [ ] Upgrade executes against a pre-change schema and a fresh database where relevant.
- [ ] Downgrade executes where reasonably supported, or its limitation is explicit.
- [ ] Existing rows are preserved; backfill, nullability, constraints, and indexes are justified.
- [ ] Migration history is not edited casually; dependency and revision order are correct.
- [ ] Lock duration, table rewrite, transaction size, and legacy-data risks are assessed.
- [ ] Mandatory business writes and audit writes share the intended transaction boundary.
- [ ] Audit helpers flush without independently committing when atomicity is required.
- [ ] Failure tests prove rollback leaves neither partial business data nor orphan audit rows.
- [ ] Row counts, constraints, and key invariants have post-migration verification queries.

## Frontend

- [ ] User-visible behavior matches confirmed terminology and workflow.
- [ ] Loading, empty, error, unauthorized, retry, and success states are handled.
- [ ] Keyboard, focus, labels, contrast, and touch-target impacts are checked proportionately.
- [ ] Responsive/browser/PWA behavior affected by the change is manually or automatically verified.
- [ ] API type/contract changes are reflected without hiding backend failures.
- [ ] No patient data, misleading current-location claim, or cleaning-state workflow is introduced.
- [ ] Build and relevant component/E2E tests pass with exact evidence.

## Security

- [ ] Authentication and authorization are enforced server-side for every affected route.
- [ ] No credentials, passwords, hashes, PATs, JWTs, cookies, API keys, or secret material enter
  tracked files, fixtures, logs, screenshots, PR descriptions, or audit payloads.
- [ ] Unknown failed-login identifiers are neither stored raw nor as deterministic unkeyed hashes
  or any enumerable/correlatable representation.
- [ ] Input length/charset/type constraints and output/error disclosure are assessed.
- [ ] Fail-open/fail-closed behavior is intentional, documented, and tested.
- [ ] Audit actor and subject semantics are correct; unauthenticated failures have no actor.
- [ ] Dependency changes are focused and assessed for reachability and regression risk.
- [ ] A Security Reviewer independently reviews auth, secret, audit, or privacy-sensitive changes.

## Documentation-only PR

- [ ] Documentation authority and new/replacement pointers are explicit.
- [ ] Links, headings, and referenced file paths resolve.
- [ ] No Roadmap scope or architecture decision changed accidentally.
- [ ] Historical audits remain historically accurate.
- [ ] Duplicate/conflicting wording is removed or clearly classified as legacy.
- [ ] Normal task reading sets remain within three or four core documents.
- [ ] No application, tests, migrations, runtime configuration, Docker, dependency, or CI files changed.
- [ ] `git diff --check`, changed-file review, and available Markdown/link checks pass.

## Hotfix

- [ ] Incident/severity and emergency authority are recorded.
- [ ] Change is the smallest safe containment/correction.
- [ ] Known-good release/base and rollback point are recorded before mutation.
- [ ] Targeted regression and security/data-integrity verification runs despite expedited timing.
- [ ] Independent review occurs before merge when possible, otherwise immediately after containment.
- [ ] Monitoring signals and rollback thresholds are explicit.
- [ ] Deferred full tests, cleanup, root-cause analysis, debt, and governance work have owners/triggers.

## Evidence in the PR description

Include:

1. Roadmap/task reference and objective.
2. In-scope and out-of-scope lists.
3. Files/modules and API/database/security impacts.
4. Exact local test results and separate CI results; never combine them.
5. PostgreSQL/Alembic evidence when applicable.
6. Rollback, monitoring, known limitations, and deferred follow-ups.
7. Independent review status and final owner decision.

Passing local tests demonstrates only that stated local environment. “Production
ready” additionally requires deployment, operational, recovery, and monitoring
evidence relevant to the release; a PR alone does not establish it.
