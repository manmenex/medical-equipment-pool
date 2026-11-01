# Project Memory

**Purpose:** Compact chronological record of major evidenced decisions and supersessions
**Authority:** Historical navigation; active authorities linked from each entry control current policy
**Update trigger:** Major architecture, domain, governance, or Roadmap phase decision
**Maintainer:** Documentation/Governance Engineer

**Continued in `DECISION_LOG.md`,** which picks up from Roadmap PR5 onward
(this file's last entry is Governance Pack v1.0, immediately before Roadmap
PR5's implementation). For a current-state AI-memory snapshot rather than a
chronological log, see [`../knowledge/PROJECT_MEMORY.md`](../knowledge/PROJECT_MEMORY.md)
— same name, different purpose: that file is a point-in-time summary, this
file is the dated history.

Git history is the detailed change record. This file records only decisions
important enough to prevent future re-litigation or context loss.

## 2026-07-16 — Recall application replaced by Equipment Pool web system

- **Decision:** Use a browser-first React/PWA client, FastAPI backend, and
  PostgreSQL system of record for the Medical Equipment Pool.
- **Reason:** Replace the prior Recall application and AppSheet-like
  workflow with a transactionally safe, install-light pool system.
- **Source:** Commit `4e99466`; `ARCHITECTURE_DECISIONS.md`.
- **Status:** Implemented foundation.
- **Consequences:** Repository history includes a legacy Recall ancestor;
  application work lives under `backend/` and `frontend/`.
- **Supersedes:** Medical Device Recall Monitor application direction.

## 2026-07-16 — Equipment Pool-only domain boundary

- **Decision:** Scope is pool dispatch/receipt only; no patient tracking,
  inter-ward transfer tracking, MEMS, PM, calibration, recall, or hospital-wide
  asset lifecycle.
- **Reason:** Confirmed hospital operating boundary and privacy/scope control.
- **Source:** `AGENTS.md`; consolidated plan Parts A/B;
  `ARCHITECTURE_DECISIONS.md`.
- **Status:** Confirmed guardrail.
- **Consequences:** Ward requestors are external to application operation;
  Equipment Pool operators record the first receiving ward.

## 2026-07-16 — Cleaning excluded from system state

- **Decision:** Receipt is one atomic usable/defective outcome; cleaning is not
  a state or separate digital workflow.
- **Reason:** Hospital confirmation superseded the earlier two-step proposal.
- **Source:** Consolidated plan Part B.1; `ARCHITECTURE_DECISIONS.md`.
- **Status:** Confirmed target model.
- **Supersedes:** Workflow Audit 03's proposed pending-cleaning/two-step model.

## 2026-07-16 — Roadmap PR1 security and availability foundation

- **Decision:** Add production JWT-secret guardrails, correct dashboard database
  session lifetime, and expose security-relevant Redis failures.
- **Reason:** Resolve scope-independent Critical availability/security findings.
- **Source:** GitHub PR #2; merge commit `25b460d`.
- **Status:** Merged as Roadmap PR1.
- **Consequences:** Later work assumes this baseline rather than reimplementing it.

## 2026-07-16 — Roadmap PR2 structured exception handling

- **Decision:** Standardize database/validation/HTTP exception behavior and safe
  response envelopes.
- **Reason:** Prevent ordinary duplicate/input failures from surfacing as raw 500s.
- **Source:** GitHub PR #5; merge commit `14b4174`.
- **Status:** Merged as Roadmap PR2.

## 2026-07-16 — Reusable audit framework is Roadmap PR3

- **Decision:** PR3 owns the canonical audit writer, current endpoint coverage,
  request/correlation context, additive audit migration, bounded admin read,
  and PostgreSQL/Alembic evidence.
- **Reason:** Later Roadmap PRs need one trustworthy audit contract without
  parallel writers or per-endpoint redaction policy.
- **Source:** Governance GitHub PR #8; merge commit `1529040`;
  consolidated plan PR3; ADR-0001.
- **Status:** Governance approved; implementation remains Draft GitHub PR #7.
- **Consequences:** Actor and subject are distinct; mandatory business auditing
  shares the business transaction; broad observability remains PR15.

## 2026-07-16 — Unknown failed-login identifiers are not persisted

- **Decision:** Unknown login identifiers are neither stored raw nor as
  deterministic unkeyed hashes or any enumerable/correlatable representation.
  Actor and subject are null. Keyed HMAC requires a separate approved design and
  is not introduced by PR3.
- **Reason:** Employee codes/emails are low entropy and dictionary-enumerable.
- **Source:** Governance PR #8 correction commit `69736e7`; ADR-0001.
- **Status:** Confirmed security policy.
- **Supersedes:** Earlier governance wording that allowed a one-way correlation hash.

## Confirmed future direction — Shift Sessions

- **Decision:** Future flexible `DAY`/`NIGHT` sessions may contain work by
  multiple operators; every transaction retains its authenticated operator.
- **Reason:** Actual shifts do not align reliably to hard-coded transaction times.
- **Source:** `AGENTS.md`; `ARCHITECTURE_DECISIONS.md`.
- **Status:** Confirmed future direction; not scheduled to a Roadmap PR.
- **Consequences:** Current work must not block the model or implement it early.

## Confirmed future direction — Standby Snapshots

- **Decision:** Future Day/Night department-level counts are manually entered
  snapshots, independent of transaction history and Shift Sessions.
- **Reason:** Operational standby counts cannot be safely inferred from dispatches.
- **Source:** `AGENTS.md`; `ARCHITECTURE_DECISIONS.md`;
  `HOSPITAL_DOMAIN_MODEL.md`.
- **Status:** Confirmed future direction; not scheduled to a Roadmap PR.

## Confirmed constraint — managed deployment

- **Decision:** Production architecture must not assume direct access to
  hospital-managed servers.
- **Reason:** Deployment must remain portable to an approved managed platform.
- **Source:** `AGENTS.md`; `ARCHITECTURE_DECISIONS.md`.
- **Status:** Confirmed constraint; provider not selected.

## Governance Pack v1.0 — repository transition toward `main`

- **Decision:** Establish `main` as the target permanent default branch and
  retire temporary `claude/*` long-lived names through a separately executed,
  recoverable repository-maintenance sequence.
- **Reason:** Current default still names the legacy Recall application and
  complicates PR/base interpretation.
- **Source:** Governance Pack v1.0 source PR; `REPOSITORY_STRATEGY.md`.
- **Status:** Proposed by this Governance Pack; effective only when its PR is
  approved and merged. The repository mutation is not performed here.
- **Consequences:** Open PRs must be merged/retargeted; archive tags and rollback
  verification precede branch deletion/default change.
