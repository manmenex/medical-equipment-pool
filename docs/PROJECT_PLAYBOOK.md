# Project Playbook

**Purpose:** Compact entry point for Project Governance Pack v1.0
**Authority:** Navigation, role, workflow, evidence, and change-control policy
**Update trigger:** Governance baseline, workflow, authority, or role-policy change
**Maintainer:** Documentation/Governance Engineer with Repository Owner approval

## Project purpose and boundary

The Medical Equipment Pool is a browser/PWA system used by Equipment Pool
operators to dispatch pool equipment to a first receiving ward and record its
receipt. It is not a patient-tracking, cleaning, maintenance, calibration,
recall, or hospital-wide asset-lifecycle system. Confirmed terminology and
current-versus-future workflow live in
[`HOSPITAL_DOMAIN_MODEL.md`](HOSPITAL_DOMAIN_MODEL.md).

## Source-of-truth hierarchy

| Level | Authority | Governs |
|---|---|---|
| 1 | [`AGENTS.md`](../AGENTS.md) | Permanent repository-wide rules and non-negotiable domain guardrails |
| 2 | [`ARCHITECTURE_DECISIONS.md`](ARCHITECTURE_DECISIONS.md), `docs/adr/`, and [`../knowledge/adr/`](../knowledge/README.md) | Active confirmed architecture and security decisions (durable ADRs — two ADR sets, one hierarchy; see the topic-ownership table below for which set governs which topic) |
| 3 | [`../knowledge/architecture/`](../knowledge/architecture/) and [`../knowledge/business-rules/`](../knowledge/business-rules/) | Durable architecture concepts and operational business rules that implement a Level 2 decision, for the topics assigned to the Knowledge Layer below |
| 4 | [`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md) | Roadmap PR scope, order, dependencies, and acceptance criteria not already governed by Level 2 or 3 |
| 5 | [`ROADMAP_STATUS.md`](ROADMAP_STATUS.md) | Current status only; it does not redefine scope |
| 6 | Task-specific instructions | The authorized task inside the boundaries above |
| 7 | Archived audits, legacy documents and design plans (`archive/`), and [`../knowledge/traceability/`](../knowledge/traceability/README.md) | Historical evidence, rationale, and non-authoritative implementation traceability — never current policy |

Use the narrowest interpretation that satisfies all higher authorities. A task
cannot silently override confirmed domain guardrails, security policy, or
Roadmap scope. A real conflict requires an explicit Governance PR and, for an
architecture change, an Architecture Decision update. Implementation PRs may
not rewrite governance merely to legitimize their implementation.

Level 2 and Level 3 are not "the Knowledge Layer always wins" — they are topic
ownership. A topic not yet assigned to the Knowledge Layer keeps whatever
document already governed it (typically `ARCHITECTURE_DECISIONS.md` at Level 2
or `HOSPITAL_DOMAIN_MODEL.md` as a Level-3-equivalent domain reference until
migrated). The table below is the single, explicit map from topic to owning
document; do not infer ownership from a document's own claims about itself.

### Topic ownership

| Topic | Owning document | Level |
|---|---|---|
| Repository-wide rules and domain guardrails | [`AGENTS.md`](../AGENTS.md) | 1 |
| Pipeline, agent roles, merge rules | [`PROJECT_WORKFLOW.md`](PROJECT_WORKFLOW.md) | — (process, not a domain topic) |
| Governance hierarchy and change control | This Playbook | — |
| Equipment Pool scope boundary | [`knowledge/adr/ADR-001`](../knowledge/adr/ADR-001-equipment-pool-scope.md) | 2 |
| Equipment identifier model (UUID / BCM Code / Item No / Asset Number) | [`knowledge/adr/ADR-002`](../knowledge/adr/ADR-002-identifier-model.md) | 2 |
| BCM manual search | [`knowledge/adr/ADR-003`](../knowledge/adr/ADR-003-bcm-manual-search.md) | 2 |
| Hospital QR identification | [`knowledge/adr/ADR-004`](../knowledge/adr/ADR-004-hospital-item-no-qr.md) | 2 |
| Identifier canonicalization | [`knowledge/architecture/identifiers.md`](../knowledge/architecture/identifiers.md) | 3 |
| QR resolution flow | [`knowledge/architecture/qr-identification.md`](../knowledge/architecture/qr-identification.md) | 3 |
| API information boundaries (what a response may/must not contain) | [`knowledge/architecture/api-information-boundaries.md`](../knowledge/architecture/api-information-boundaries.md) | 3 |
| Equipment Pool operational rules | [`knowledge/business-rules/equipment-pool.md`](../knowledge/business-rules/equipment-pool.md) | 3 |
| Equipment selection (search + QR) rules | [`knowledge/business-rules/equipment-selection.md`](../knowledge/business-rules/equipment-selection.md) | 3 |
| Borrow/return equipment-selection integration | [`knowledge/business-rules/borrow-return-selection.md`](../knowledge/business-rules/borrow-return-selection.md) | 3 |
| Shared terminology for the topics above | [`knowledge/glossary.md`](../knowledge/glossary.md) | 3 |
| Audit-write atomicity and failed-login identifiers | `docs/adr/ADR-0001` (indexed from `ARCHITECTURE_DECISIONS.md`) | 2 |
| All other confirmed architecture/security decisions not listed above | [`ARCHITECTURE_DECISIONS.md`](ARCHITECTURE_DECISIONS.md) | 2 |
| Dispatch/receipt workflow, equipment states, transaction states | [`HOSPITAL_DOMAIN_MODEL.md`](HOSPITAL_DOMAIN_MODEL.md) | domain reference, until migrated |
| Terminology not covered by `knowledge/glossary.md` above | [`GLOSSARY.md`](GLOSSARY.md) | domain reference, until migrated |
| Roadmap PR scope, order, dependencies, acceptance criteria | [`audits/04-consolidated-implementation-plan.md`](audits/04-consolidated-implementation-plan.md) | 4 |
| Roadmap PR current status | [`ROADMAP_STATUS.md`](ROADMAP_STATUS.md) | 5 |
| Implementation-to-decision mapping and current implementation status | [`knowledge/traceability/`](../knowledge/traceability/README.md) (non-authoritative) | 7 |
| Superseded/historical requirement text | Git history, or a document's own clearly marked historical appendix | 7 |

When a topic is migrated into the Knowledge Layer, the document that
previously owned it is updated in the same change to point here instead of
continuing to state the topic independently — see "Scope and change control"
below.

## Roles and workflow

The pipeline, the agent roles (orchestrator, implementer, reviewer, helper),
the merge rules, and the loop limit are owned by
[`PROJECT_WORKFLOW.md`](PROJECT_WORKFLOW.md) (Owner decision, 2026-10-13) and
are not restated here. In short: implementer agents build one PR each;
CI must be fully green on the exact head SHA; the reviewer agent reviews that
SHA ([`prompts/codex-pr-review.md`](prompts/codex-pr-review.md) is its
prompt); the orchestrator squash-merges the approved SHA and reports to the
Repository Owner, who sets direction and alone authorizes Production
deployment.

Playbook-level principles that complement it:

- Bound each task against the relevant Roadmap PR or approved exception, on a
  focused branch; do not mix governance or unrelated refactors.
- Self-review is not independent review. The same agent/session must not be the
  reviewer of its own implementation.
- Review-only tasks never modify files; their sole permitted GitHub write is
  one direct Pull Request review submission. Fixes are a separate task.
- Record exact evidence (see "Evidence and claim policy"), and update status
  documents after merge, not before.

See [`REPOSITORY_STRATEGY.md`](REPOSITORY_STRATEGY.md),
[`DEFINITION_OF_DONE.md`](DEFINITION_OF_DONE.md), and the compact exception
flows below.

## Minimum reading sets

| Task | Mandatory reads | Conditional reads |
|---|---|---|
| Implementation | `AGENTS.md`; this Playbook; assigned Roadmap section; task prompt | DoD sections for affected layer; ADR/guardrail linked by scope |
| Review (reviewer agent) | `AGENTS.md`; this Playbook; [`prompts/codex-pr-review.md`](prompts/codex-pr-review.md); PR diff and assigned Roadmap section | DoD/ADR for affected risk |
| Governance | `AGENTS.md`; this Playbook; affected authoritative documents | Repository strategy, memory, or ADR index |
| Focused bugfix | `AGENTS.md`; this Playbook; task/issue; affected code | DoD and technical-debt item |
| Hotfix/incident | `AGENTS.md`; this Playbook; repository strategy; incident context | Security, migration, rollback, or deployment authority |
| Repository maintenance | `AGENTS.md`; this Playbook; repository strategy | Open PR/branch metadata and recovery tags |

Normal tasks therefore require no more than three or four core reads. Do not
load every audit, prompt, or governance document by default.

## Scope and change control

- Roadmap scope changes require a separate Governance PR.
- Architecture changes require an Architecture Decision update; detailed ADRs
  are used only for cross-cutting or high-risk decisions.
- Status changes update `ROADMAP_STATUS.md` after the external event occurs.
- Historical audits are not rewritten to hide or modernize past findings.
- Major governance changes must be reviewed before implementation depends on them.
- Out-of-scope defects found during a PR are documented, severity-assessed, and
  routed to a focused follow-up. Tests must not normalize known failure behavior.
- Scope expands immediately only when necessary to prevent an active safety,
  security, or data-integrity failure, and the expansion must be explicit.

## Evidence and claim policy

PRs and reviews distinguish:

- **Automated test:** command, environment, and result recorded.
- **Manual verification:** exact steps and observed result recorded.
- **Code inspection:** behavior inferred from the diff/surrounding code.
- **Reported, not reproduced:** evidence supplied by another party.
- **Deferred or unknown:** not yet established.

Do not say “verified,” “CI passed,” or “production-ready” without matching
evidence. Local state is not CI. Never include credentials, tokens, passwords,
secret values, or sensitive screenshots/logs in evidence.

## Exception workflows

- **Governance PR:** inventory authority → propose map → edit docs/templates only
  → validate links/duplication → Draft PR → reviewer-agent review → orchestrator merge.
- **Focused bugfix:** reproduce → bound regression → smallest fix → targeted and
  regression tests → Draft PR → reviewer-agent review.
- **Security hotfix:** contain exposure → preserve evidence safely → focused fix
  → security review → expedited merge with explicit Owner authorization → follow-up analysis.
- **Migration emergency:** stop rollout → protect/backup data → run approved
  downgrade or forward fix → verify row counts/invariants → document outcome.
- **Production incident:** stabilize → record timeline/evidence → restore service
  → create focused corrective work → update governance only if a process gap exists.
- **Dependency vulnerability:** assess reachability/severity → update the minimum
  dependency set → test impacted surfaces; do not perform an automatic broad upgrade.

## Documentation map

| Document | Purpose / authority | Read | Update trigger | Owner role |
|---|---|---|---|---|
| `AGENTS.md` | Permanent repository rules | Mandatory | Guardrail/repository-rule change | Architecture Owner |
| This Playbook | Entry point, hierarchy, and change control | Mandatory | Governance baseline change | Governance Engineer |
| `PROJECT_WORKFLOW.md` | Pipeline, agent roles, merge rules | Mandatory for process questions | Pipeline/role change (rides in the PR it serves) | Repository Owner |
| `ENGINEERING_WORKFLOW.md` | Engineering detail: design PRs, baselines, slicing, governance-sync | Conditional | Engineering process change | Governance Engineer |
| `REPOSITORY_STRATEGY.md` | Git/PR/release/cleanup policy | Conditional | Repository policy change | Repository Owner |
| `DEFINITION_OF_DONE.md` | Risk-based completion standard | Conditional | Quality-gate change | Architecture Owner |
| `ARCHITECTURE_GUARDRAILS.md` | Prohibitions and invariants | Conditional | Guardrail change | Architecture Owner |
| `HOSPITAL_DOMAIN_MODEL.md` | Confirmed domain reference | Conditional | Approved domain change | Architecture Owner |
| `GLOSSARY.md` | Preferred terminology | Conditional | Term ambiguity/change | Governance Engineer |
| `ARCHITECTURE_DECISIONS.md` / `adr/` | Active decisions/index and selected detail | Conditional | Architecture decision | Architecture Owner |
| `../knowledge/adr/` | Durable ADRs for topics assigned in the topic-ownership table above | Conditional (assigned topics mandatory) | Architecture decision, focused Governance PR | Architecture Owner |
| `../knowledge/architecture/`, `../knowledge/business-rules/` | Durable concepts/rules implementing a `knowledge/adr/` decision | Conditional (assigned topics mandatory) | Companion to the ADR it elaborates | Architecture Owner |
| `../knowledge/glossary.md` | Terminology for topics assigned to the Knowledge Layer | Conditional | Term ambiguity/change within assigned topics | Governance Engineer |
| `../knowledge/traceability/` | Non-authoritative implementation-to-decision mapping | Conditional | Implementation change affecting a mapped decision | Implementation Engineer |
| `audits/04-...` | Roadmap scope/order | Assigned section mandatory | Governance-approved Roadmap change | Architecture Owner |
| `ROADMAP_STATUS.md` | Current state | Conditional | PR/status event | Governance Engineer |
| `PROJECT_MEMORY.md` | Major chronological decisions | Conditional | Major decision/phase | Governance Engineer |
| `TECH_DEBT.md` | Evidence-based deferred defects | Conditional | Debt discovered/closed | Architecture Owner |
| `prompts/` | Reusable task/review instructions | Task-dependent | Workflow/template change | Governance Engineer |
| `archive/audits/` (01–03, 05–06) | Historical findings | Conditional | Never for policy alignment | Historical |

## Size and version targets

Governance Pack version: **v1.0**. The source PR becomes its effective record;
minor wording fixes do not increment the version. Major incompatible governance
baselines do. Detailed change history remains in Git; major milestones are
summarized in `PROJECT_MEMORY.md`.

| File type | Rough target |
|---|---:|
| Playbook / Repository Strategy | 150–220 lines |
| DoD / Guardrails / Domain Model / Memory | 80–180 lines each |
| Glossary / ADR / diagrams / debt register | 60–160 lines each |
| Reusable task template collection | Under 200 lines |

Review governance when scope, architecture, branch policy, deployment model, a
major workflow, or a production incident changes—or when a conflict is found.
Arbitrary monthly review is not required.
