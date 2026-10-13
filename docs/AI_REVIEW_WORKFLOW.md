# AI Review Workflow

**Purpose:** Pointer to the current review and merge workflow
**Authority:** Superseded. `docs/PROJECT_WORKFLOW.md` is authoritative for the pipeline, agent roles, review, and merge rules.
**Update trigger:** None; update `docs/PROJECT_WORKFLOW.md` instead
**Maintainer:** Repository Owner

This document used to describe the Claude -> Codex -> Owner review and merge
sequence, with no automatic merge and no Claude <-> Codex repair loop.
On 2026-10-13 the Owner replaced that pipeline: Codex and ChatGPT are no
longer part of this project, an Opus reviewer agent reviews every
CI-green PR, the orchestrator merges approved PRs and reports them to the
Owner, and a loop limit replaces the ban on repair loops. See
`docs/PROJECT_WORKFLOW.md` and the 2026-10-13 entry in
`docs/DECISION_LOG.md`.

What carries over unchanged: CI must be green on the exact head SHA before
review; new commits invalidate a review; merge is a squash against the
reviewed head SHA, re-verified immediately beforehand.
