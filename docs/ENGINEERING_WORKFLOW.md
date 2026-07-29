# Engineering Workflow

## 1. Purpose

This document defines the standard engineering, review, merge, and governance
workflow for the Medical Equipment Pool project.

The Medical Equipment Pool is production software. It is not a prototype.
Engineering work MUST preserve business correctness, safety, reviewability,
and repository governance from design through merge.

## 2. Scope

This workflow applies to:

- design changes;
- backend implementation;
- frontend implementation;
- database migrations;
- API changes;
- security changes;
- documentation and governance synchronization.

MEMS and Recall Monitor are separate systems. Equipment Pool work MUST NOT
couple to either system unless an explicit Owner-approved architecture decision
and Roadmap change authorize it.

## 3. Roles and Responsibilities

Workflow responsibilities are authoritative. Tool names are current operating
assignments only and may change.

The current working model is:

- ChatGPT: architecture and planning;
- Claude: implementation;
- Codex: independent review.

### Architecture and Design

Architecture and design are responsible for:

- business workflow analysis;
- architecture;
- API contract;
- data model direction;
- scope control;
- identifying Owner Decisions.

Design work MUST define business workflow and semantics before UI. It MUST NOT
invent business decisions for technical convenience.

### Implementation

Implementation is responsible for:

- implementing approved design;
- tests;
- migrations;
- validation;
- keeping changes within scope.

Implementation MUST start from a merged and reviewed baseline. It MUST NOT
change lifecycle states, QR identity rules, API contracts, or business
semantics unless the approved design explicitly allows that change.

### Independent Review

Independent review is responsible for:

- correctness;
- architecture consistency;
- business-rule compliance;
- security;
- regression risks;
- documentation consistency;
- exact-head verification.

Reviewers MUST review the actual diff and the relevant surrounding code or
documents. A self-review does not satisfy the independent-review requirement.

### Repository Owner

The Repository Owner is responsible for:

- Owner Decisions;
- merge approval;
- Roadmap priority;
- resolving business-policy ambiguity.

The Repository Owner may approve exceptions, but exceptions MUST be explicit
and documented.

## 4. Standard Delivery Lifecycle

The project architecture order is:

```text
Business Workflow
-> API
-> Frontend
-> Deployment
```

Backend implementation is the source of truth for business rules. Frontend code
MUST consume backend contracts and MUST NOT duplicate or redefine backend
business rules.

Canonical delivery sequence:

1. Roadmap item selected.
2. Repository baseline confirmed.
3. Design PR created when required.
4. Independent architecture review completed.
5. Owner Decisions resolved or explicitly left open.
6. Design merged.
7. Implementation divided into independently reviewable slices.
8. Each slice receives independent review.
9. CI passes on the exact reviewed head.
10. Slice is squash-merged.
11. New merge SHA becomes the next baseline.
12. Governance synchronization occurs only after the complete Roadmap item is
    finished.

```mermaid
flowchart TD
    A["Roadmap item selected"] --> B["Merged baseline confirmed"]
    B --> C{"Design PR required?"}
    C -- "Yes" --> D["Design PR"]
    D --> E["Independent architecture review"]
    E --> F["Owner Decisions resolved or explicitly left open"]
    F --> G["Design squash merge"]
    C -- "No" --> H["Implementation slice"]
    G --> H
    H --> I["Independent implementation review"]
    I --> J["CI green on exact reviewed head"]
    J --> K["Slice squash merge"]
    K --> L{"Roadmap item complete?"}
    L -- "No" --> H
    L -- "Yes" --> M["Governance synchronization PR"]
    M --> N["New authoritative baseline"]
```

## 5. Baseline Management

Every new branch MUST start from the latest approved merged baseline.

Reviewed head SHA and merged baseline SHA are different concepts:

- reviewed head SHA identifies the exact commit reviewed before merge;
- fixed head SHA identifies a later PR head after requested changes;
- re-reviewed head SHA identifies the exact commit reviewed after fixes;
- merge SHA identifies the squash commit that becomes the authoritative
  baseline.

These values MUST NOT be confused. A pre-merge reviewed head is never the
post-merge baseline after a squash merge.

No implementation branch SHOULD start from an unmerged design head. If an
exception is required, it MUST be documented and Owner-approved.

After squash merge, the squash SHA becomes the authoritative baseline. Stale
baseline references in current-state documents such as `CONTEXT.md` or
`PROJECT_MEMORY.md` are merge blockers for governance-sync PRs.

## 6. Design PR Policy

A Design PR is required when work materially changes:

- business workflow;
- business semantics;
- lifecycle transitions;
- permissions;
- API contract;
- database model;
- reporting semantics;
- cross-module architecture;
- security or information boundaries;
- Roadmap scope.

A Design PR MUST NOT:

- contain implementation;
- create migrations;
- silently change business rules;
- perform premature governance completion.

Design documents MUST include:

- objective;
- current foundation;
- business workflow;
- canonical definitions;
- API proposal;
- backend architecture;
- frontend workflow;
- security;
- performance;
- risks;
- acceptance criteria;
- out-of-scope items;
- Owner Decisions;
- implementation slices.

## 7. Owner Decision Policy

An Owner Decision is required only for unresolved business policy.

Technical implementation details SHOULD normally be resolved by architecture
and review. Open Owner Decisions MUST be clearly documented.

Implementation depending on an open Owner Decision MUST NOT begin. Unrelated
implementation slices MAY proceed only when they are genuinely independent of
the open decision.

An open Owner Decision MUST NOT be used to falsely declare a Roadmap item
complete. Accepted Owner Decisions MUST be recorded in `docs/DECISION_LOG.md`
through an appropriate reviewed PR.

## 8. Implementation Slice Policy

Each implementation slice MUST:

- start from a merged baseline;
- have one coherent responsibility;
- be independently reviewable;
- include relevant tests;
- avoid unrelated cleanup;
- avoid future Roadmap scope;
- preserve existing contracts unless a change is explicitly approved.

Incremental implementation is preferred over a large combined PR.

Valid slice boundaries MAY include:

- domain/query foundation;
- schema and migration;
- API;
- frontend;
- governance synchronization.

These slice types are examples, not prescriptions. Boundaries MUST follow the
architecture of the work.

## 9. Pull Request Requirements

Every PR description SHOULD include:

- objective;
- baseline SHA;
- scope;
- files or modules changed;
- out-of-scope items;
- tests and validation performed;
- migrations, if any;
- API compatibility impact;
- security impact;
- rollback considerations;
- linked Roadmap item or design document.

The PR description MUST match the actual file count and scope.

Metadata-only PR description corrections do not require a commit or re-review
unless they reveal a substantive scope change.

## 10. Independent Review Policy

Reviews MUST distinguish:

- GitHub action;
- substantive decision.

Allowed substantive decisions are:

- APPROVE;
- APPROVE WITH NON-BLOCKING COMMENTS;
- REQUEST CHANGES.

If GitHub prevents `APPROVE` or `REQUEST_CHANGES` because the reviewer owns the
PR, the reviewer MAY submit `COMMENT` while stating the substantive decision
explicitly.

Review priorities are:

1. business-rule correctness;
2. architecture and contract consistency;
3. security and privacy boundaries;
4. data integrity;
5. migrations;
6. regression risk;
7. performance;
8. tests;
9. maintainability;
10. documentation consistency.

A green CI run does not override a design or correctness blocker.

## 11. Exact-Head Review and CI

Every review MUST record the exact reviewed head SHA.

CI MUST pass on that exact SHA before merge. A new commit invalidates earlier
exact-head merge readiness.

Documentation-only metadata changes outside Git history do not change the head
SHA. Merge MAY proceed only when required checks, branch protection, and review
conversations are satisfied.

## 12. Incremental Review

After requested changes, reviewers MUST:

- review the delta from the previous reviewed head to the new head;
- confirm each prior finding as resolved, partially resolved, or unresolved;
- inspect the final full PR state for contradictions;
- identify regressions introduced by the fix.

Reviewers SHOULD NOT require a full new design review when changes are narrowly
scoped. Reviewers MUST NOT skip full-state consistency checks merely because
the review is incremental.

## 13. Merge Policy

The default merge method is squash merge.

Before merge, verify:

- substantive review approval;
- exact-head CI green;
- mergeable state clean;
- required conversations resolved;
- PR description accurate;
- no unapproved scope expansion.

After merge:

- record the squash SHA as the new baseline;
- create the next branch only from that baseline;
- do not refer to a pre-merge reviewed head as the baseline.

## 14. Governance Synchronization Policy

Governance synchronization is a separate final step after a complete Roadmap
item.

It MUST update all applicable current-state documents consistently:

- `docs/ROADMAP.md`;
- `docs/ROADMAP_STATUS.md`;
- `docs/DECISION_LOG.md`;
- `knowledge/CHANGE_HISTORY.md`;
- `knowledge/CONTEXT.md`;
- `knowledge/PROJECT_MEMORY.md`.

Rules:

- do not declare a Roadmap item complete while required slices remain
  unfinished;
- do not advance the next Roadmap item while an unresolved decision still
  blocks the active item, unless an explicitly approved scope amendment exists;
- implementation sub-slices do not individually trigger Roadmap completion;
- governance documents must use the actual merged baseline and correct review
  chronology.

## 15. Testing and Validation Standards

Testing MUST be appropriate to the change.

Backend validation SHOULD include:

- unit tests;
- service/domain tests;
- API tests;
- authorization tests;
- PostgreSQL-specific tests where behavior depends on PostgreSQL;
- migration upgrade validation.

Frontend validation SHOULD include:

- rendering and interaction tests;
- API parameter serialization;
- loading, empty, and error states;
- contract compatibility;
- mobile-first behavior where relevant.

Documentation validation SHOULD include:

- `git diff --check`;
- internal consistency;
- correct SHA and PR chronology;
- no stale Roadmap or baseline claims.

Tests MUST verify business invariants, not only implementation details.

## 16. API and Schema Compatibility

Existing APIs remain unchanged unless the design explicitly approves a contract
change.

Additive fields are still contract changes and MUST be documented.
Presentation fields specific to reports SHOULD use report-specific DTOs.

Database schemas MUST never be exposed directly to the frontend. APIs SHOULD
remain versionable. Error responses and HTTP status codes MUST be consistent.
Frontend code MUST NOT duplicate backend business rules.

## 17. Database and Migration Policy

PostgreSQL is authoritative.

SQLAlchemy models and Alembic migrations MUST remain synchronized. Every schema
change requires a migration.

Migrations MUST avoid breaking existing data. Migration review MUST consider
existing data, upgrade behavior, downgrade or forward-recovery behavior, and
fresh-database convergence.

Upgrade validation is required for schema changes. Rollback or forward-recovery
strategy MUST be documented.

SQLite compatibility helpers MUST NOT accidentally redefine PostgreSQL
behavior.

## 18. Security and Privacy Review

Every relevant PR MUST consider:

- authentication;
- authorization;
- least privilege;
- role visibility;
- new information boundaries;
- PII exposure;
- historical data visibility;
- audit implications;
- sensitive logging;
- enumeration risks.

A narrower payload is not automatically safe if it creates a new directory or
lookup surface.

## 19. Scope and Roadmap Boundaries

Each PR MUST remain within its active Roadmap item.

Future Roadmap work MUST NOT be implemented early. Compatibility planning is
allowed; future implementation is not.

Printing/export functionality MUST remain in its assigned Roadmap item. MEMS
and Recall Monitor MUST NOT be coupled into Equipment Pool work.

Existing lifecycle states and QR identity rules MUST NOT be changed without
explicit Owner approval.

## 20. Definition of Ready

A work item is ready for implementation when:

- business workflow is understood;
- canonical semantics are documented;
- required Owner Decisions are resolved;
- API and architecture boundaries are clear;
- acceptance criteria are measurable;
- scope and out-of-scope are explicit;
- implementation slices are identified;
- design PR is merged when required;
- implementation baseline is confirmed.

## 21. Definition of Done

A Roadmap item is done only when:

- all approved implementation slices are merged;
- tests pass;
- CI passes on each merged slice's reviewed head;
- required Owner Decisions are recorded;
- no known merge blockers remain;
- documentation matches implementation;
- governance synchronization is merged;
- the final governance merge SHA becomes the new baseline.

## 22. Exception Policy

Exceptions require explicit documentation and Owner approval.

An exception MUST state:

- why the normal workflow cannot be followed;
- risks;
- mitigations;
- scope;
- expiration or follow-up plan.

Convenience alone is not sufficient justification.
