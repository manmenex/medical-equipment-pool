# Context

**Purpose:** Current project state, kept short; `docs/ROADMAP.md` owns the detailed status
**Authority:** Point-in-time status only; `docs/ROADMAP.md`,
`docs/BUSINESS_RULES.md`, and accepted ADRs control
**Update trigger:** Every merged PR and any change to current work, risk, or
ordering
**Maintainer:** Documentation/Governance Engineer

## Current baseline

`80f61d6` (GitHub PR #150) on `claude/medical-equipment-pool-0c7fz0`. The
baseline chain, merged-PR list and per-PR history are in
[`docs/ROADMAP.md`](../docs/ROADMAP.md) and `docs/DECISION_LOG.md`; they are
not repeated here.

## Current work

- Roadmap PR1-PR23 are complete. PR24 (deployment) is in progress; PR24E
  (UAT), PR24F (Pilot) and PR24G (Go-Live) have not started.
- Production target is the Owner-designated department host (Governance
  2026-10-13), replacing managed cloud. Managed-Staging evidence is
  superseded; local Windows Staging/UAT evidence exists.
- Stage 1 comes next, in order: PR25A (hourly backup to Google Drive), PR25B
  (read-only export API for Nsmart Realtime), PR25C (Cloudflare Tunnel +
  Access, host hardening), PR25D (offline operation design), PR25E (offline
  implementation after PR25D approval). All not started. Stage 2 is a
  direction only; Stage 3 is out of scope.
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
