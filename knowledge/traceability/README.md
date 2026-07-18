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

The identifier and QR architecture in this Knowledge Layer (ADR-002,
ADR-003, ADR-004) was established after an implementation attempt for
Roadmap PR5 had already been opened as a pull request. That
implementation has since been rebased onto the merged Knowledge Layer
and reconciled against it: canonicalization now matches
`../architecture/identifiers.md`, the response boundary now matches
`../architecture/api-information-boundaries.md` (Item No no longer
appears in an operator-facing response), and the retired legacy
self-generated QR scheme's runtime paths have been removed per ADR-004.
The reconciled implementation is pending its own independent review —
this note records that the reconciliation has happened, not that the
review has.
