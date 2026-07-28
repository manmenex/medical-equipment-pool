# Documentation Audit

**Audit date:** 2026-07-28
**Repository baseline reviewed:** `4b0d422`
**Scope:** tracked Markdown/text/diagram documentation in the repository root,
`.github/`, `docs/`, and `knowledge/`
**Change boundary:** documentation only; no application code, migration, API,
frontend, database schema, or business rule was changed

## Method

Every tracked documentation file was inventoried. Last-commit dates came from
`git log -1 --format=%cs -- <file>`. References were checked with repository
text search using each filename and known path aliases. Content was compared
with the merged history through GitHub PR #52, current architecture and Version
1 boundaries, the authoritative Roadmap/implementation plan, and later
decisions.

`Yes*` in the Referenced column means the file is primarily reached through a
directory/index link or is a repository convention rather than by frequent
direct links. `Historical` means the file is intentionally retained as
point-in-time evidence and must not be treated as current policy.

## Inventory

| File | Purpose | Last Commit | Referenced | Authoritative | Current | Classification | Finding | Action |
|---|---|---:|---|---|---|---|---|---|
| `.github/PULL_REQUEST_TEMPLATE.md` | PR evidence template | 2026-07-20 | Yes | Process | Yes | Stable process | Complete and still used | KEEP |
| `AGENTS.md` | Repository guardrails/orientation | 2026-07-20 | Yes | Yes | Updated | Dynamic authority | Shift wording was unscheduled/session-oriented | UPDATE |
| `README.md` | Repository entry point | 2026-07-17 | Yes | Summary | Updated | Dynamic entry point, >7 days | Pointed to stale Roadmap Status and legacy `10-roadmap` | UPDATE |
| `docs/01-architecture.md` | Original architecture proposal | 2026-07-17 | Yes | Historical | No, labelled | Legacy evidence | Contains superseded scale/deployment assumptions but has a clear legacy banner and audit citations | KEEP |
| `docs/02-database-schema.md` | Original schema proposal | 2026-07-21 | Yes | Historical | No, labelled | Legacy evidence | Contains retired lifecycle values; retained for audit provenance | KEEP |
| `docs/03-api-specification.md` | Original API proposal | 2026-07-21 | Yes | Historical | Partial, labelled | Legacy evidence | Not the live API contract; current API docs supersede it | KEEP |
| `docs/04-ui-mockups.md` | Original UI wireframes | 2026-07-17 | No | Historical | No, labelled | Legacy evidence | Contains obsolete cleaning/PM UI but is clearly non-authoritative | KEEP |
| `docs/05-folder-structure.md` | Original layout proposal | 2026-07-17 | No | Historical | Partial, labelled | Legacy evidence | Useful origin record; current repository is the source of truth | KEEP |
| `docs/06-deployment-guide.md` | Original deployment proposal | 2026-07-17 | No | Historical | No, labelled | Legacy evidence | Direct-server assumptions are superseded; retained as evidence | KEEP |
| `docs/07-performance-optimization.md` | Original performance proposal | 2026-07-20 | Yes | Historical | Partial, labelled | Legacy evidence | Scale targets are proposals; later evidence audit controls | KEEP |
| `docs/08-security.md` | Original security proposal | 2026-07-17 | Yes | Historical | Partial, labelled | Legacy evidence | Later audits/guardrails supersede promises not implemented | KEEP |
| `docs/09-testing-plan.md` | Original testing proposal | 2026-07-17 | No | Historical | No, labelled | Legacy evidence | Contains retired lifecycle outcomes; retained only as history | KEEP |
| `docs/10-roadmap.md` | Compatibility pointer to newer Roadmap | 2026-07-17 | No | No | Superseded | Duplicate pointer, >7 days | No inbound dependency; useful links already exist in README/playbook | DELETE |
| `docs/AI_REVIEW_WORKFLOW.md` | Detailed AI review workflow | 2026-07-20 | Yes | Process | Yes | Stable process | Distinct from short compatibility pointer | KEEP |
| `docs/AI_WORKFLOW.md` | Compatibility pointer | 2026-07-17 | Yes | No | Yes | Compatibility document | Small and still has an inbound architecture-decision link | KEEP |
| `docs/ARCHITECTURE_DECISIONS.md` | Cross-cutting architecture decisions | 2026-07-18 | Yes | Yes | Updated | Stable authority with dynamic decision | Shift model contradicted newly approved metadata direction | UPDATE |
| `docs/ARCHITECTURE_GUARDRAILS.md` | Architecture invariants | 2026-07-20 | Yes | Yes | Yes | Stable authority | Lifecycle/frontend ownership guardrails remain correct | KEEP |
| `docs/BUSINESS_RULES.md` | Current business rules | 2026-07-24 | Yes | Yes | Yes | Stable authority | Four states and no-cleaning rule correct | KEEP |
| `docs/DECISION_LOG.md` | Decision history from PR5 onward | 2026-07-28 | Yes | Historical navigation | Updated | Dynamic traceability | Needed the audit/numbering/migration decision | UPDATE |
| `docs/DEFINITION_OF_DONE.md` | Completion evidence standard | 2026-07-17 | Yes | Process | Yes | Stable process, >7 days | Age does not imply staleness | KEEP |
| `docs/design/PR15B_SCHEMA_HYGIENE_PLAN.md` | Approved PR15B design | 2026-07-28 | No direct | Design authority | Yes | Current approved design | Merged by GitHub PR #52; implementation not started | KEEP |
| `docs/DOMAIN_MODEL.md` | Current structural domain reference | 2026-07-23 | Yes | Yes | Yes | Stable authority | Matches current entities/states | KEEP |
| `docs/GLOSSARY.md` | Preferred terminology | 2026-07-18 | Yes | Yes | Yes | Stable authority, >7 days | No conflicting Version 1 terminology found | KEEP |
| `docs/HOSPITAL_DOMAIN_MODEL.md` | Confirmed workflow/domain boundary | 2026-07-18 | Yes | Yes | Updated | Stable authority with future-work section | Shift Sessions wording no longer matched approved PR16 model | UPDATE |
| `docs/KNOWN_LIMITATIONS.md` | Current tooling/process limits | 2026-07-20 | Yes | Yes | Yes | Dynamic status, >7 days | Limitations remain evidenced and current | KEEP |
| `docs/PROJECT_MEMORY.md` | Early chronological decision record | 2026-07-20 | Yes | Historical | Yes for period | Historical traceability, >7 days | Distinct from knowledge snapshot; no merge needed | KEEP |
| `docs/PROJECT_PLAYBOOK.md` | Authority hierarchy and reading sets | 2026-07-18 | Yes | Yes | Yes | Stable authority, >7 days | Roadmap Status now again fulfills its assigned live-status role | KEEP |
| `docs/PROJECT_WORKFLOW.md` | Requirement-to-merge workflow | 2026-07-20 | Yes | Yes | Yes | Stable process | No stale implementation state | KEEP |
| `docs/REPOSITORY_STRATEGY.md` | Branch/release strategy | 2026-07-17 | Yes | Yes | Yes | Stable process, >7 days | Temporary default-branch limitation still current | KEEP |
| `docs/REVIEW_CHECKLIST.md` | Review checklist | 2026-07-20 | Yes | Process | Yes | Stable process | No scope conflict | KEEP |
| `docs/ROADMAP.md` | Detailed Roadmap and ordering | 2026-07-28 | Yes | Yes | Updated | Dynamic authority | Stopped at PR15A and called merged PR15B design uncommitted | UPDATE |
| `docs/ROADMAP_STATUS.md` | Concise live status dashboard | 2026-07-20 | Yes | Status summary | Updated | Dynamic document, >7 days | Frozen at PR3 despite being cited as current | UPDATE |
| `docs/TECH_DEBT.md` | Technical debt register | 2026-07-23 | Yes | Yes | Yes | Dynamic register | Open/closed items match current evidence | KEEP |
| `docs/adr/ADR-0001-canonical-audit-and-failed-login-identifiers.md` | Accepted audit/security ADR | 2026-07-17 | Yes | Yes | Yes | Accepted ADR, >7 days | Must be retained for decision evidence | KEEP |
| `docs/api/ERROR_CODES.md` | Current API error catalog | 2026-07-23 | Yes | Contract reference | Yes | Stable API doc | No lifecycle/ownership conflict | KEEP |
| `docs/api/dispatch.md` | Current dispatch API | 2026-07-24 | Yes | Contract reference | Yes | Stable API doc | Backend remains authoritative | KEEP |
| `docs/api/equipment.md` | Current equipment API | 2026-07-24 | Yes | Contract reference | Yes | Stable API doc | Four-state terminology correct | KEEP |
| `docs/api/receipt.md` | Current receipt API | 2026-07-24 | Yes | Contract reference | Yes | Stable API doc | Binary receipt outcome and backend mapping correct | KEEP |
| `docs/api/transactions.md` | Current transaction/history API | 2026-07-24 | Yes | Contract reference | Yes | Stable API doc | Existing filters accurately documented | KEEP |
| `docs/architecture/README.md` | Architecture diagram index | 2026-07-17 | Yes | Supporting | Yes | Stable index, >7 days | Distinct diagram audience; no duplicate authority | KEEP |
| `docs/audits/01-database-schema-audit.md` | Point-in-time schema audit | 2026-07-16 | Yes | Historical | N/A | Audit evidence, >7 days | Findings are dated evidence, not live schema docs | KEEP |
| `docs/audits/02-backend-architecture-audit.md` | Point-in-time backend audit | 2026-07-16 | Yes | Historical | N/A | Audit evidence, >7 days | Later PRs resolve many findings; preserve original evidence | KEEP |
| `docs/audits/03-hospital-equipment-pool-workflow-audit.md` | Point-in-time workflow audit | 2026-07-16 | Yes | Historical | N/A | Audit evidence, >7 days | Includes superseded proposals but is explicitly cited history | KEEP |
| `docs/audits/04-consolidated-implementation-plan.md` | Authoritative PR scope/order/acceptance | 2026-07-27 | Yes | Yes | Updated | Dynamic implementation plan | Ended at PR15 and placed migration assumptions after Go-live gates | UPDATE |
| `docs/audits/05-pr14a-transaction-boundary-audit.md` | PR14A audit evidence | 2026-07-27 | Yes | Historical evidence | Yes | Completed audit | Retain for traceability | KEEP |
| `docs/audits/06-pr14b-pagination-index-evidence.md` | PR14B performance evidence | 2026-07-27 | Yes | Historical evidence | Yes | Completed audit | Retain for traceability | KEEP |
| `docs/development/CODE_REVIEW.md` | Developer review guide | 2026-07-21 | Yes | Process | Yes | Stable developer doc | No stale Roadmap claims | KEEP |
| `docs/development/CONTRIBUTING.md` | Contribution guide | 2026-07-21 | Yes | Process | Yes | Stable developer doc | No conflict | KEEP |
| `docs/development/MIGRATIONS.md` | Alembic guide | 2026-07-21 | Yes | Technical convention | Yes | Stable developer doc | No migration performed by this task | KEEP |
| `docs/development/SETUP.md` | Local setup guide | 2026-07-21 | Yes | Technical guide | Yes | Stable developer doc | No obsolete deployment claim found | KEEP |
| `docs/development/TESTING.md` | Test guide | 2026-07-23 | Yes | Technical guide | Yes | Stable developer doc | Current test split documented | KEEP |
| `docs/kickoffs/PR4-architecture-kickoff.md` | Completed PR4 kickoff | 2026-07-17 | No direct | Historical evidence | N/A | Completed plan, >7 days | Decision provenance; do not delete | KEEP |
| `docs/kickoffs/PR5-equipment-master-bcm-search.md` | Completed PR5 kickoff | 2026-07-19 | No direct | Historical evidence | N/A | Completed plan, >7 days | Identifier/QR decision provenance | KEEP |
| `docs/prompts/claude-implementation.md` | Compatibility prompt pointer | 2026-07-17 | No direct | No | Yes | Compatibility file, >7 days | Small pointer; retained to avoid external-link breakage | KEEP |
| `docs/prompts/codex-pr-review.md` | Detailed review prompt | 2026-07-18 | Yes | Process | Yes | Stable prompt, >7 days | Still authoritative for review role | KEEP |
| `docs/prompts/tasks/README.md` | Compact prompt template index | 2026-07-17 | Yes | Process | Yes | Stable template index, >7 days | Distinct from detailed role prompts | KEEP |
| `knowledge/CHANGE_HISTORY.md` | Conceptual change history | 2026-07-28 | Yes | Historical navigation | Updated | Dynamic traceability | Needed reporting/migration mental-model entry | UPDATE |
| `knowledge/CONTEXT.md` | Volatile current-state snapshot | 2026-07-28 | Yes | Status summary | Updated | Dynamic status | Stopped at PR15A and said PR15B design uncommitted | UPDATE |
| `knowledge/PROJECT_MEMORY.md` | Stable current-state AI snapshot | 2026-07-28 | Yes | Summary | Updated | Dynamic snapshot | Needed baseline and approved sequence correction | UPDATE |
| `knowledge/README.md` | Knowledge-layer index | 2026-07-18 | Yes | Supporting | Yes | Stable index, >7 days | Ownership distinctions remain correct | KEEP |
| `knowledge/adr/ADR-001-equipment-pool-scope.md` | Equipment Pool scope ADR | 2026-07-18 | Yes | Yes | Yes | Accepted ADR, >7 days | Explicitly excludes MEMS/Recall scope | KEEP |
| `knowledge/adr/ADR-002-identifier-model.md` | Identifier ADR | 2026-07-18 | Yes | Yes | Yes | Accepted ADR, >7 days | BCM/Item No/existing QR model remains authoritative | KEEP |
| `knowledge/adr/ADR-003-bcm-manual-search.md` | BCM search ADR | 2026-07-18 | Yes | Yes | Yes | Accepted ADR, >7 days | Still correct | KEEP |
| `knowledge/adr/ADR-004-hospital-item-no-qr.md` | Hospital QR ADR | 2026-07-18 | Yes | Yes | Yes | Accepted ADR, >7 days | Explicitly supports preserving hospital QR codes | KEEP |
| `knowledge/adr/ADR-005-transaction-model.md` | Transaction model ADR | 2026-07-21 | Yes | Yes | Yes | Accepted ADR | OPEN/CLOSED model remains correct | KEEP |
| `knowledge/adr/ADR-006-receipt-outcome-contract.md` | Receipt outcome ADR | 2026-07-23 | Yes | Yes | Yes | Accepted ADR | Usable/defective contract remains correct | KEEP |
| `knowledge/architecture/api-information-boundaries.md` | API ownership boundary | 2026-07-18 | Yes | Yes | Yes | Stable architecture, >7 days | Backend-owned rule remains correct | KEEP |
| `knowledge/architecture/identifiers.md` | Identifier canonicalization | 2026-07-18 | Yes | Yes | Yes | Stable architecture, >7 days | Supports migration matching without QR redesign | KEEP |
| `knowledge/architecture/qr-identification.md` | QR flow summary | 2026-07-18 | Yes | Yes | Yes | Stable architecture, >7 days | Existing hospital QR flow remains correct | KEEP |
| `knowledge/business-rules/borrow-return-selection.md` | Legacy-named selection rule summary | 2026-07-18 | Yes | Supporting | Yes | Stable rule summary, >7 days | Filename is historical terminology; content boundary remains correct | KEEP |
| `knowledge/business-rules/equipment-pool.md` | Pool scope rule summary | 2026-07-18 | Yes | Supporting | Yes | Stable rule summary, >7 days | No MEMS/Recall inclusion | KEEP |
| `knowledge/business-rules/equipment-selection.md` | Selection/identifier rules | 2026-07-18 | Yes | Supporting | Yes | Stable rule summary, >7 days | No conflict | KEEP |
| `knowledge/glossary.md` | Knowledge-layer compact glossary | 2026-07-18 | Yes | Supporting | Yes | Stable glossary, >7 days | Distinct compact audience from `docs/GLOSSARY.md` | KEEP |
| `knowledge/traceability/README.md` | PR5 traceability record | 2026-07-19 | Yes | Historical evidence | N/A | Traceability, >7 days | Must be retained | KEEP |
| `docs/DOCUMENTATION_AUDIT.md` | This inventory and audit evidence | 2026-07-28 | Yes* | Audit record | Yes | New required deliverable | No prior audit file existed | KEEP |

## Dynamic documents older than seven days

The following dynamic or entry-point documents were older than seven days and
were explicitly compared with merged PRs and later decisions:

- `README.md` — stale Roadmap Status link corrected.
- `docs/ROADMAP_STATUS.md` — fully replaced as a concise live dashboard.
- `docs/ARCHITECTURE_DECISIONS.md` — shift direction aligned to PR16.
- `docs/HOSPITAL_DOMAIN_MODEL.md` — shift direction aligned to PR16.
- `AGENTS.md` — future-work wording aligned.
- `docs/PROJECT_PLAYBOOK.md` — unchanged; its ownership model is correct now
  that Roadmap Status is live again.
- `docs/KNOWN_LIMITATIONS.md` — unchanged; limitations remain current.
- `docs/PROJECT_MEMORY.md` — unchanged because it is a closed historical
  decision record, not the volatile knowledge snapshot.

`PROJECT_STATUS.md` and `IMPLEMENTATION_PLAN.md` do not exist. Their roles are
served by `docs/ROADMAP_STATUS.md` and
`docs/audits/04-consolidated-implementation-plan.md`.

## Cleanup summary

### Deleted files

- `docs/10-roadmap.md` — safe to delete because it was an unreferenced
  compatibility pointer, was not authoritative or historical evidence, and
  contained only links already preserved in `README.md`, `docs/ROADMAP.md`,
  `docs/ROADMAP_STATUS.md`, and the playbook.

### Archived files

None. Historical ADRs, audits, kickoffs, legacy design documents, change
history, decision logs, and traceability evidence were retained in place
because active documents cite them or their original paths carry evidentiary
value.

### Merged or consolidated files

- The duplicated Roadmap roles were consolidated by responsibility:
  `docs/ROADMAP.md` owns detail/order and `docs/ROADMAP_STATUS.md` owns only the
  concise current dashboard.
- No content-bearing historical document was merged destructively.

### Updated files

`AGENTS.md`, `README.md`, `docs/ARCHITECTURE_DECISIONS.md`,
`docs/DECISION_LOG.md`, `docs/HOSPITAL_DOMAIN_MODEL.md`, `docs/ROADMAP.md`,
`docs/ROADMAP_STATUS.md`,
`docs/audits/04-consolidated-implementation-plan.md`,
`knowledge/CHANGE_HISTORY.md`, `knowledge/CONTEXT.md`,
`knowledge/PROJECT_MEMORY.md`, and this audit report.

### Unchanged authoritative files

The inventory marks each unchanged authority `KEEP`. In particular, the
business rules, architecture guardrails, current API catalog, accepted ADRs,
identifier/QR architecture, developer conventions, and process documents
remain correct and were not changed merely because of age.

## Consistency results

- Project identity remains Medical Equipment Pool, not MEMS or Recall Monitor.
- The only equipment lifecycle states are `AVAILABLE_AT_POOL`,
  `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, and `DECOMMISSIONED`.
- Cleaning is not a lifecycle state.
- Frontend usability gates do not own business rules; backend/API/service
  authorities remain unchanged.
- Existing hospital QR codes are preserved; no QR redesign is planned.
- AppSheet today/yesterday sheet behavior is not carried into the target
  reporting model.
- Roadmap and GitHub PR numbers are explicitly separated.
- Legacy migration is scheduled before Go-live.

## Unresolved inconsistencies and questions

No unresolved contradiction blocks this documentation PR. Implementation
design still needs to resolve the following within the assigned Roadmap item,
without changing the approved scope:

- exact `shift` value set/validation and `business_date` rollover rules;
- source-column mappings and approved normalization dictionaries for legacy
  Ward/BME values;
- the later user-mapping procedure for preserved BME names;
- reconciliation tolerances/sign-off ownership;
- production deployment provider and cutover window;
- scheduling or explicit removal of the remaining broad PR15 observability
  topics.

## Assumptions made

- The repository's Roadmap numbering is preserved. Therefore PR16–PR18 are the
  reporting sequence, PR19–PR23 are migration/cutover, and PR24 is Go-live.
- “BME name preservation” means retaining the legacy source value and mapping
  it later; this audit does not define user identities or mapping rules.
- Equipment Verify Checklist history is excluded from Version 1 migration
  because no existing approved document requires it.
- The approved PR15B design at GitHub PR #52 is current work, but its
  implementation has not started.

## Follow-up actions

1. Implement and review PR15B from its approved design.
2. Produce focused designs and acceptance tests for PR16–PR18 reporting work.
3. Obtain representative legacy Equipment Master, Receive, and Issue samples
   before PR19/PR20 implementation.
4. Define import manifests, traceability identifiers, validation reports, and
   reconciliation sign-off for PR19–PR23.
5. Do not begin PR24 Go-live/deployment until PR19–PR23 are complete.
