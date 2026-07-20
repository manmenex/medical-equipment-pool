## Reference and purpose

- Roadmap PR / task / issue:
- Purpose:
- Draft or ready status: **Draft**

## Scope

**Included**

-

**Explicitly out of scope**

-

## Change surface

- Files/modules:
- API impact: None / describe
- Database/migration impact: None / describe
- Security/privacy impact: None / describe
- Documentation impact: None / describe

## Evidence

Clearly label local, CI, manual, inspection-only, reported, and unknown evidence.

| Check | Environment | Result |
|---|---|---|
| Targeted tests | | |
| Regression suite | | |
| PostgreSQL/Alembic (if applicable) | | |
| Frontend build/E2E (if applicable) | | |
| CI checks | | |

<details>
<summary>Exact commands and relevant output</summary>

```text

```

</details>

## Operations

- Rollback/forward-fix plan:
- Monitoring or post-merge verification:
- Known limitations:
- Deferred follow-ups:

## Merge readiness checklist

See `docs/AI_REVIEW_WORKFLOW.md` for the full Claude → Codex → owner sequence
this checklist supports.

- [ ] Base SHA recorded (see Reference and purpose)
- [ ] Scope stated (see Scope)
- [ ] Tests listed (see Evidence)
- [ ] Migration impact stated (see Change surface)
- [ ] Rollback stated (see Operations)
- [ ] Out-of-scope stated (see Scope)
- [ ] CI passing (all required GitHub Actions checks green on the current head SHA)
- [ ] Reviewed head SHA recorded
- [ ] Codex review completed for the exact reviewed head SHA
- [ ] Owner approval recorded before merge

## Author checklist

- [ ] Scope matches the assigned task/Roadmap section
- [ ] Later Roadmap work was not implemented early
- [ ] Acceptance criteria are covered
- [ ] No secrets or sensitive identifiers appear in code, logs, fixtures, screenshots, or audit data
- [ ] Local evidence is not described as CI evidence
- [ ] Migration upgrade/downgrade and PostgreSQL evidence are included when applicable
- [ ] PR description matches the final diff
- [ ] Rollback and monitoring are proportionate to risk
- [ ] PR remains Draft until independent review and fixes are complete

## Reviewer checklist

- [ ] Actual diff, tests, and surrounding code reviewed
- [ ] Scope and exclusions verified
- [ ] Authorization, transaction, migration, and secret-handling risks checked where applicable
- [ ] Evidence claims match what was executed
- [ ] Critical/High findings resolved before merge
- [ ] Final Repository Owner decision recorded
