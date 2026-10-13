# Business Rules: Equipment Selection

Elaborates [ADR-003](../adr/ADR-003-bcm-manual-search.md) and
[ADR-004](../adr/ADR-004-hospital-item-no-qr.md). There are exactly two
ways an operator selects a specific equipment record: scanning its
hospital QR label, or manually searching by BCM Code. This document
states the rules that apply across both, and the rules specific to each.

## Common rules

- Both paths resolve to exactly one equipment record (or a clear "not
  found"/"no matches" outcome) — neither path ever returns an
  unbounded, unfiltered listing of equipment.
- Both paths respect the information boundary in
  `knowledge/architecture/api-information-boundaries.md`: Item No is
  never disclosed by either path.
- Neither path is a substitute for the other. A feature that needs QR
  resolution must not silently fall back to BCM search, and vice versa.

## QR scan (primary)

- Exact Item No match only ([ADR-004](../adr/ADR-004-hospital-item-no-qr.md)).
- A malformed scan and a well-formed-but-unmatched Item No are distinct,
  clearly distinguishable outcomes.

## BCM manual search (fallback)

- Used when scanning is not possible.
- BCM Code only, partial matching allowed, prefix-optional input
  ([ADR-003](../adr/ADR-003-bcm-manual-search.md)).
- Returns a bounded, minimal suggestion list; the operator then selects
  one specific result.

## Item No is never a selection path of its own

Item No exists only to be resolved from a QR scan. There is no rule,
under any workflow, that lets an operator type or paste an Item No to
select equipment directly — that would make it a second manual-search
identifier, which ADR-002 and ADR-003 do not permit.
