# Architecture: API Information Boundaries

Elaborates [ADR-002](../adr/ADR-002-identifier-model.md),
[ADR-003](../adr/ADR-003-bcm-manual-search.md), and
[ADR-004](../adr/ADR-004-hospital-item-no-qr.md). Defines which
identifiers may appear in which class of response. This is a contract
boundary, not a route inventory — it applies to every current and future
surface that falls into one of these categories.

## Operator-facing equipment data

Any response an operator-facing workflow (manual search, QR-scan
resolution, dispatch, return, equipment browsing, dashboards) returns
about equipment:

- May include the equipment's internal opaque ID.
- May include BCM Code and other operational display fields (name,
  status, and similar attributes appropriate to the workflow).
- Must not include Item No, in any form, at any point in the response.

This applies uniformly to a manual-search suggestion, the equipment
detail shown after a suggestion is selected, and the result of QR
resolution. There is no operator-facing surface where Item No is an
acceptable field to return, even if unused by the client that receives
it — the boundary is about what the response contains, not about
whether something reads that field afterward.

## QR resolution specifically

QR resolution accepts a scanned value through a non-manual scan flow (it
is not a manual-search input, even though it is text). It resolves that
value to equipment internally and returns operator-safe equipment data
as defined above. It must not echo the Item No it resolved unless the
caller is using a restricted administrative/import contract as described
below.

## Restricted administrative/import contracts

A separate contract, explicitly distinct from operator-facing contracts,
may access and return Item No when an administrative or import task
genuinely requires it (for example, reviewing or correcting Equipment
Master data). This contract must not be the same response shape reused
for operator-facing purposes — reusing one shape for both is exactly the
condition this document exists to prevent, because it makes the boundary
depend on which fields a particular client happens to read rather than
on what the server is willing to return.

## Consequence for change review

A change that adds a field to an operator-facing response is checked
against this document before merge. A change that makes Item No reachable
from an operator-facing surface — directly, or by widening a shared
schema also used by a restricted contract — does not conform to this
architecture regardless of intent.
