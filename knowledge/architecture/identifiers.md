# Architecture: Identifier Canonicalization

Elaborates [ADR-002](../adr/ADR-002-identifier-model.md). Defines the one
durable, canonical stored form for each write-facing identifier, so that
uniqueness and lookup are always comparing the same representation of a
value regardless of how it was entered or scanned.

Canonicalization applies identically whether an identifier is being set
when equipment is created or changed later — there is no separate,
looser rule for updates.

## BCM Code

- Leading and trailing whitespace is trimmed before any other rule is
  applied.
- Logical identity is case-insensitive: two inputs that differ only in
  letter case name the same code.
- The canonical persisted form is uppercase.
- The canonical persisted form always carries the "BCM" prefix. Input
  supplied without the prefix is normalized to include it; input
  supplied with the prefix, in any case, normalizes to the same result.
- Digits after the prefix preserve their original width — leading zeros
  are significant and are never dropped or reinterpreted numerically.
- Uniqueness is enforced on the canonical persisted form. Two inputs
  that normalize to the same canonical form are the same code and
  cannot both be assigned to different equipment.

## Item No

- Leading and trailing whitespace is trimmed before any other rule is
  applied.
- Leading zeros and internal formatting are preserved exactly —
  Item No is never reinterpreted numerically.
- Case is preserved exactly as provided. Item No is obtained by scanning
  a hospital-issued label, not by an operator typing it from memory, so
  there is no typing-variance problem to normalize away, and the
  hospital's own labeling scheme may treat case as meaningful. This is
  the opposite rule from BCM Code, deliberately: BCM Code is normalized
  to smooth out human typing variance, Item No is preserved to stay
  faithful to a machine-read source.
- Exact QR lookup compares the trimmed scanned value against the
  canonical persisted value with the same trim rule applied — no other
  transformation is applied to either side of the comparison.
- Uniqueness is enforced on the canonical persisted form.

## Asset Number

Retained as existing inventory metadata (ADR-002); this document does
not change its handling.
