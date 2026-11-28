# Context

**Purpose:** Current project state, kept short; `docs/ROADMAP.md` owns the detailed status
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`e1e57cd` (GitHub PR #257) on `claude/medical-equipment-pool-0c7fz0`, as of
2026-11-28. The baseline chain, merged-PR list and per-PR history are in
[`docs/ROADMAP.md`](../docs/ROADMAP.md) and `docs/DECISION_LOG.md`; they are
not repeated here. The rules in force are summarized in `docs/BUSINESS_RULES.md`
("Current rules at a glance").

## Current work

- Roadmap PR1-PR23 are complete. PR25A, PR25B, PR25D, the PR25E code slices
  and PR26-PR34 are merged. PR25C (Cloudflare), PR24E (UAT), PR24F (Pilot)
  and PR24G (Go-Live) are not complete; no Production Go is authorized.
- Owner decisions D1-D31 are merged in `docs/DECISION_LOG.md` (D30
  long-outstanding read-only report; D31 HN retention 2 years and monthly
  backups 12 months).
- The system runs on the CES-BCM Windows host (`C:\MEP\app`,
  `deployment/local-staging`, Tailscale Funnel); updates use
  `update-online.ps1` with a GitHub ZIP; the legacy Google Sheet sync runs
  alongside the app; login lockout is off by Owner decision (#191).
- Workflow: Orchestrator + Sonnet implementers + Opus reviewer; Codex and
  ChatGPT are no longer used (`docs/PROJECT_WORKFLOW.md`).

## Current scope boundaries

- Product: Medical Equipment Pool, not MEMS or Recall Monitor.
- States: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`,
  `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`; cleaning is not a state.
- Shift: reporting/operational metadata in one model, not separate Day/Night
  tables and not a lifecycle state.
- Version 1 legacy history: equipment receive-data and equipment issue-data
  sheets only; Equipment Verify Checklist history excluded.
- QR: preserve existing hospital QR codes; do not redesign the QR system.
- Rules: backend/service/API authorities own business behavior; frontend gates
  are usability only.

## Current risks and unresolved design details

- RPO <= 1h is a target, not yet proven: the hourly backup is local until
  PR25A adds off-host copies, and the host is a single machine.
- Production Go is not authorized; the Owner alone authorizes it.
- Cloudflare external access (PR25C) is not built; the demo host uses Tailscale Funnel with no identity gate in front of the app login and lockout off (accepted risk).
- Branch protection is not enabled; required CI remains a documented manual
  merge gate. The default branch still has a temporary `claude/*` name.
- PR18A Owner Decision #2 (branding configuration ownership) remains open;
  every export format uses the same neutral fallback until it is resolved.
- Broader PR15 metrics/tracing/dashboards/aggregation/alerting work is still
  unscheduled.

## Related documents

- `docs/ROADMAP.md` - detailed order, scope and current status.
- `docs/OVERVIEW.md` - non-technical overview.
- `knowledge/PROJECT_MEMORY.md` - stable current-state orientation.
- `knowledge/CHANGE_HISTORY.md` - conceptual history.
