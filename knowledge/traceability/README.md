# Traceability (Non-Authoritative)

This directory maps durable decisions (`../adr/`, `../architecture/`,
`../business-rules/`) to their implementation. **Nothing in this
directory is authoritative.** If a traceability document and an ADR or
business-rule document disagree, the ADR or business-rule document is
correct, and the traceability document is out of date and should be
fixed.

## Why this directory is separate

`../adr/`, `../architecture/`, and `../business-rules/` describe durable
decisions and constraints — the kind of content that should still be
true regardless of which code implements it, when it was implemented, or
whether it has been implemented yet. Mixing implementation inventory
(file paths, function names, endpoint routes, migration identifiers, PR
numbers, current implementation status) into those documents makes them
drift out of date every time the code changes, and makes it ambiguous
whether a passage is a decision or a status report. This directory is
where that implementation inventory belongs instead — reviewed and
updated independently, without touching the decisions themselves.

## Required dependency direction

```
ADR / Business Rule
        |
        v
Implementation
        |
        v
Tests
```

Implementation code may reference the decision it follows with a short
pointer comment (for example, "See ADR-002"). It must not restate the
architecture or business rule at length in a code comment — the ADR or
business-rule document is the one place that explanation lives.

## Current status note

The identifier and QR architecture (ADR-002, ADR-003, ADR-004) is implemented
and merged (Roadmap PR5 and later). This directory holds implementation
inventory only; for current project status see `docs/ROADMAP.md`.
