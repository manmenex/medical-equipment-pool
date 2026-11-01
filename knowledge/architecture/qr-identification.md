# Architecture: QR Identification

Elaborates [ADR-004](../adr/ADR-004-hospital-item-no-qr.md). Describes the
QR resolution flow as a durable concept, independent of how it is
implemented.

## Flow

1. A scan produces a raw value from the hospital's Item-No QR label.
2. The raw value is validated as a plausible Item No before any lookup
   is attempted. A value that is empty, unreasonably long, or shaped
   like something other than a bare identifier (for example, a web
   address) is rejected as malformed — scanning equipment does not
   guarantee the scanner was pointed at a hospital equipment label, and
   a malformed value must never be treated as a valid, simply-unmatched,
   Item No.
3. A validated value is compared, using the canonicalization rule in
   `identifiers.md`, against equipment Item No values for an **exact**
   match only. There is no partial or fuzzy match at this step.
4. A match resolves to that equipment's internal UUID and returns
   operator-safe equipment data (`api-information-boundaries.md`). No
   match returns a distinct, clear "not found" outcome.

## Required distinctions

- "Malformed scan" (step 2) and "well-formed but unmatched Item No"
  (step 4) are different outcomes and must be distinguishable by
  whatever consumes the resolution result. Collapsing them into one
  generic failure hides which situation actually occurred.
- QR resolution and BCM manual search (ADR-003) are independent: a QR
  resolution never falls back to BCM matching, and BCM search never
  matches on Item No.

## Handling the raw scanned value

A raw scan may contain more than a bare identifier if the scanner reads
an unrelated or malformed code (for example, an external web address).
The raw value is treated as potentially sensitive/unbounded input: it is
validated before use and is not persisted or logged in a form that could
retain such incidental content.
