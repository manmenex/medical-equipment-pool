# ADR-004: Hospital Item-No QR

Status: Accepted

## Context

The hospital's equipment already carries physical QR labels; those
labels encode Item No (ADR-002). Before this decision, the repository's
only QR scheme was one the application generated for itself, unrelated
to any hospital-issued label.

## Decision

- The hospital's existing QR labels, encoding Item No, are the only
  supported equipment QR format.
- The application's own previously self-generated QR format is
  intentionally retired. Compatibility with it is not required.
- No relabeling project is required: the hospital's Item-No QR labels
  already exist on the equipment.
- QR scanning resolves the scanned Item No to the equipment's internal
  UUID via an exact match. There is no partial or fuzzy QR match.
- Item No remains unavailable for manual search (ADR-003) regardless of
  how it is obtained.

**This is an intentional, approved architecture cutover, not an
accidental regression.** Equipment that was only identifiable through
the retired scheme needs a hospital-issued QR label, or a BCM Code entry,
going forward — that consequence is accepted as correct, not treated as
a defect to route around.

This ADR states the accepted target architecture. It does not assess
whether current code conforms to it — that is implementation status, and
implementation status is tracked outside this document
(`knowledge/traceability/`), never inside it.

## Consequences

- Any QR-handling code path is measured against "resolves hospital
  Item-No labels by exact match, and only that" — a design that
  continues to also resolve the retired scheme, or that does partial
  Item No matching, does not conform to this ADR.
- A QR-resolution response follows the operator-facing information
  boundary (`knowledge/architecture/api-information-boundaries.md`): it
  does not echo Item No back to the caller unless that caller is using an
  explicitly authorized administrative/import contract.
- If the hospital's physical label format is later found to differ from
  what this ADR assumes (i.e. that the label's content is directly usable
  as Item No), that is a correction to this ADR, not a silent
  implementation workaround.

## References

- [ADR-002](ADR-002-identifier-model.md) — Item No's identifier role.
- [ADR-003](ADR-003-bcm-manual-search.md) — why Item No is not a
  manual-search identifier.
- `knowledge/architecture/qr-identification.md` — QR resolution flow.
- `knowledge/business-rules/equipment-selection.md` — QR resolution
  alongside BCM search as the two ways to select equipment.
