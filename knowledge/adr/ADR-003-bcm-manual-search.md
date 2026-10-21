# ADR-003: BCM Manual Search

Status: Accepted

## Context

Operators need a way to find equipment when scanning a QR label (ADR-004)
is not possible. ADR-002 establishes BCM Code as the primary
operator-facing identifier; this ADR defines the search behavior built
on it.

## Decision

Manual equipment search matches BCM Code only. It never matches Item No,
equipment name, brand, model, or serial number.

Required behavior:

- Partial matching is allowed — an operator does not need to type the
  full code.
- Input is accepted with or without the BCM prefix; both forms behave
  identically for the same underlying code.
- Matching is performed against the canonical persisted form of BCM Code
  (`knowledge/architecture/identifiers.md`), so case and incidental
  whitespace in operator input do not affect results.
- A result set is bounded in size and ranks a full/exact match ahead of
  a partial match.
- An empty or too-short query returns no results rather than the entire
  equipment set.

Result disclosure:

- A suggestion exposes only the equipment's internal ID and its BCM
  Code.
- A suggestion must not expose Item No, Asset Number, serial number,
  model, brand, or equipment status.
- Once an operator has selected a specific suggestion, the application
  may then show full equipment detail appropriate to the workflow that
  triggered the search (dispatch, return, etc.) — the restriction above
  applies to the suggestion list, not to what is shown after a specific
  record is chosen.

## Consequences

- Any manual-search feature that also wants to match Item No, Asset
  Number, or free-text equipment attributes is a distinct feature from
  BCM manual search and must be justified and recorded separately — it
  does not extend this ADR by default.
- A suggestion-list response is reviewed against the disclosure rule
  above whenever it changes.

## References

- [ADR-002](ADR-002-identifier-model.md) — BCM Code's identifier role.
- [ADR-004](ADR-004-hospital-item-no-qr.md) — the QR-based alternative to
  manual search.
- `knowledge/business-rules/equipment-selection.md` — how BCM search and
  QR resolution fit together as the two ways to select equipment.
- `knowledge/architecture/api-information-boundaries.md` — the
  suggestion response's information boundary.
