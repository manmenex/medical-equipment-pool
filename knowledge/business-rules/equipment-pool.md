# Business Rules: Equipment Pool

Elaborates [ADR-001](../adr/ADR-001-equipment-pool-scope.md).

## Scope

Equipment Master data, identification, dispatch, return, availability,
dashboards, inventory import/export, and operational/audit history are
in scope. See ADR-001 for the full boundary and its rationale.

## Equipment ownership

Equipment belongs to the pool by default. No operator action assigns
equipment to a department, location, or owner as a distinct relational
fact — existing descriptive metadata (department/location association)
is informational, not an ownership record, and no assignment workflow or
approval step is required to "give" equipment to the pool.

## Identity

The internal equipment identity (its UUID) is permanent for the life of
the record. Business-facing identifiers (BCM Code, Item No, Asset
Number — [ADR-002](../adr/ADR-002-identifier-model.md)) may be absent,
corrected, or reassigned without changing which physical device a record
represents.
