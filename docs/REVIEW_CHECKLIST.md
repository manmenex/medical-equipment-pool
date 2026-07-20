# Review Checklist

**Purpose:** Common checklist shared by Codex (Independent Review) and ChatGPT (Project Governor Review) — see `docs/PROJECT_WORKFLOW.md` steps 7-8
**Authority:** Summary. `docs/prompts/codex-pr-review.md` remains authoritative for Codex's detailed review format, severity definitions, and GitHub review submission policy. This file does not replace it — it is the shared subset both reviewers check, plus each reviewer's distinct focus.
**Update trigger:** A shared review criterion changes, or a review-role's focus changes
**Maintainer:** Documentation/Governance Engineer

## Shared checklist (both reviewers)

- [ ] Exact base SHA and head SHA recorded; head SHA matches the PR's actual current head at review time.
- [ ] Scope matches the assigned Roadmap PR or task — no later Roadmap work implemented early, no unrelated refactor bundled in.
- [ ] Tests are listed with exact commands and results; local and CI evidence are not conflated (`docs/DEFINITION_OF_DONE.md`, Evidence and claim policy).
- [ ] Migration impact is stated (none, or upgrade/downgrade evidence against PostgreSQL).
- [ ] Rollback/forward-fix plan is proportionate to risk.
- [ ] Out-of-scope items are explicitly listed, not silently omitted.
- [ ] All required GitHub Actions checks (`.github/workflows/ci.yml`) are green on the exact reviewed head SHA.
- [ ] No secret, credential, or sensitive value appears in the diff, logs, fixtures, or PR description.
- [ ] PR description matches the actual final diff.
- [ ] No domain guardrail is violated — check against `docs/BUSINESS_RULES.md` and `docs/ARCHITECTURE_GUARDRAILS.md` even if not explicitly called out by the task.

## Codex focus — implementation review

Full detail: `docs/prompts/codex-pr-review.md`.

- [ ] Correctness: logic, state transitions, error handling, async/session/transaction behavior.
- [ ] Security: authN/authZ, injection, secret handling, fail-open/fail-closed behavior.
- [ ] Database and transaction safety: rollback correctness, atomicity, migration upgrade/downgrade safety.
- [ ] Test quality: success and failure paths, whether tests could pass with the bug still present.
- [ ] Regression risk to existing API/auth/database/frontend behavior.

## ChatGPT focus — Project Governor review

- [ ] Architecture consistency: the change matches `knowledge/adr/` decisions in effect; no ADR is silently contradicted.
- [ ] Roadmap sequencing: the change does not depend on, or implement, a Roadmap PR later than the one assigned (`docs/ROADMAP.md`).
- [ ] Guardrail conformance: no `docs/ARCHITECTURE_GUARDRAILS.md` prohibition is crossed.
- [ ] Business rule conformance: no `docs/BUSINESS_RULES.md` rule is contradicted or silently reinterpreted.
- [ ] Documentation consistency: any doc/knowledge file the change touches cross-references correctly and does not duplicate another file's rules.
- [ ] Governance process conformance: `docs/PROJECT_WORKFLOW.md`'s non-negotiables were followed (no auto-merge, no repair loop, review is against the exact current head).

## Decision and submission

Both reviewers select a substantive decision — `APPROVE`, `REQUEST_CHANGES`, or `COMMENT` — per `docs/prompts/codex-pr-review.md`'s GitHub Review Submission Policy, and state it explicitly in the review body even when the GitHub review-state action itself is constrained to `COMMENT` (see `docs/KNOWN_LIMITATIONS.md`). Neither reviewer merges, marks the PR ready, or applies a fix directly.
