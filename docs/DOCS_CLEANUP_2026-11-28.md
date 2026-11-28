# Docs Cleanup Report (2026-11-28)

Scope: `docs/`, `knowledge/`, root markdown, `.github/PULL_REQUEST_TEMPLATE.md`. Baseline `e1e57cd` (#257). Facts come from `git log`, `docs/DECISION_LOG.md` and the code; anything unverifiable is dated "as of 2026-11-28".

## Deleted
- `docs/prompts/claude-implementation.md` - empty compatibility pointer to `tasks/README.md` and the Playbook; no inbound links except the historical archive audit table.

## Updated
- `docs/ROADMAP.md` - baseline moved from `0bca016` (#154) to `e1e57cd` (#257); added merged PR25A/B/D/E, host setup, demo sync, PR26-PR34, D17-D29 rows; PR25C-demo, sheet sync and PR25E E1 statuses corrected; PR26-34 sections marked implemented.
- `docs/BUSINESS_RULES.md` - new top section "Current rules at a glance (as of 2026-11-28)"; added "Amended by Dx" notes (D2/D3, D15/D29, D27, D25, D21/D28, D24/D26) to older sections.
- `docs/ARCHITECTURE_GUARDRAILS.md` - HN bullet now notes the D29 export exception; D28 `voided` note; status-change pointer fixed to ROADMAP.md.
- `docs/PROJECT_WORKFLOW.md` - added "How to record a rule change" checklist.
- `knowledge/PROJECT_MEMORY.md` - points to the current-rules summary; Stage 1, host, lockout and Funnel facts refreshed; `VOIDED` noted.
- `knowledge/CONTEXT.md` - baseline, current work and risks refreshed.
- `knowledge/CHANGE_HISTORY.md` - added D17-D29 entry.
- `docs/KNOWN_LIMITATIONS.md` - sheet sync now merged; E1 drills status; Funnel note.
- `docs/TECH_DEBT.md` - TD-003 status note (CI workflow exists, branch protection does not require it).
- `docs/OVERVIEW.md` - PR25B wording, PR26-34 status, CES-BCM/Funnel, lockout note.
- `docs/PROJECT_PLAYBOOK.md` - implementation reading set includes the current-rules summary.
- `docs/ENGINEERING_WORKFLOW.md` - status note: PROJECT_WORKFLOW controls roles and merge; Codex/ChatGPT historical.
- `README.md` - start-here pointers to the rules summary and PROJECT_MEMORY; layout lists knowledge/ and deployment/.
- `.github/PULL_REQUEST_TEMPLATE.md` - Codex review checklist item replaced by reviewer-agent approval.

## Kept but flagged
- `AGENTS.md` (review only, not edited): checked; it already carries the D29 export exception, no change needed.
- `docs/prompts/codex-pr-review.md` - historical filename, is the live reviewer-agent prompt; referenced in about 15 files, so not renamed.
- `docs/ROADMAP_STATUS.md` - pointer only, but linked from runbooks, audits and guardrails; kept.
- `docs/PROJECT_MEMORY.md` vs `knowledge/PROJECT_MEMORY.md` - different purposes (dated history vs current snapshot); kept both.
- `docs/GLOSSARY.md` vs `knowledge/glossary.md` - complementary, not duplicates; kept.
- `docs/ENGINEERING_WORKFLOW.md` (525 lines) - unique engineering detail; kept with a status note.
- `docs/evidence/*` - referenced by code and tests; kept.
- `.github/workflows/ci.yml` line 5 comment still mentions the "Claude -> Codex -> owner" workflow (code, not edited).
- D30 is not in DECISION_LOG on this branch (open PR #258); documented as pending.
- `docs/BUSINESS_RULES.md`: the D18-D20 section sits after "Related documents"; left in place, noted.
