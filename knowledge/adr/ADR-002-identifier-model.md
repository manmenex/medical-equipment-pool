# ADR-002: Identifier Model

Status: Accepted

## Context

Equipment needs both a stable relational identity and identifiers
hospital staff can use in practice. Earlier governance material used a
single placeholder identifier ("ME Code") for every user-facing role —
manual search, QR lookup, and general reference — without distinguishing
those roles. That placeholder is retired by this ADR.

## Decision

Equipment has exactly four identifiers, each with one role. No
identifier substitutes for another.

1. **Internal UUID**
   - The relational primary key.
   - Never entered manually by an operator.
   - The only identifier borrow/return records reference.

2. **BCM Code**
   - The primary operator-facing identifier.
   - The only identifier accepted by manual equipment search (ADR-003).
   - Unique across all equipment.
   - Canonical persisted form and normalization rules:
     `knowledge/architecture/identifiers.md`.

3. **Item No**
   - The identifier encoded in the hospital's existing QR labels.
   - Used only for exact QR lookup (ADR-004).
   - Unavailable as a manual-search identifier.
   - Absent from normal operator-facing response contracts; it may
     appear only in explicitly restricted administrative/import
     contracts (`knowledge/architecture/api-information-boundaries.md`).
   - Unique across all equipment.

4. **Asset Number**
   - Retained as inventory metadata only.
   - Not a supported QR identifier and not a manual-search identifier.
   - Not merged with, or inferred from, BCM Code or Item No.

**"ME Code" is retired.** It does not name any current or planned
identifier. Where a document still uses it, that document is
out of date and should be corrected to BCM Code or Item No, whichever
role it meant.

Cardinality: one equipment record has exactly one value (or none, before
that identifier has been assigned) for each of BCM Code, Item No, and
Asset Number. No identifier is shared across equipment records.

## Consequences

- A feature that needs to identify equipment by human input uses BCM
  Code. A feature that needs to identify equipment from a scanned label
  uses Item No. Neither substitutes for the other.
- Uniqueness is enforced on the canonical persisted form of each
  identifier (`knowledge/architecture/identifiers.md`), not on the raw
  input form.
- Any roadmap or requirements text that still specifies a separate ME
  Code field, ME Code lookup, or ME Code reconciliation process is
  superseded by this ADR and must not be treated as an active
  requirement.

## References

- [ADR-001](ADR-001-equipment-pool-scope.md) — equipment identity's role
  in overall scope.
- [ADR-003](ADR-003-bcm-manual-search.md) — BCM Code's manual-search role.
- [ADR-004](ADR-004-hospital-item-no-qr.md) — Item No's QR role.
- `knowledge/architecture/identifiers.md` — canonicalization rules.
- `knowledge/architecture/api-information-boundaries.md` — where each
  identifier may appear in a response.
