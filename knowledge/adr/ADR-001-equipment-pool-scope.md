# ADR-001: Equipment Pool Scope

Status: Accepted

## Context

The Medical Equipment Pool repository exists to support one hospital
operation: a central pool that dispatches equipment to wards and
receives it back. Earlier governance material considered a broader
asset-management and device-safety surface; that broader surface was
rejected in favor of a narrow, confirmed operational scope.

## Decision

The repository's scope is Equipment Pool operation only:

- Equipment Master data and identification.
- BCM manual search and hospital QR identification.
- Dispatch (borrow) and return.
- Equipment availability and status.
- Dashboards and operational reporting.
- Inventory import/export.
- Operational and audit history.

No equipment-ownership or equipment-assignment table is part of this
architecture. Do not introduce `EquipmentAssignment`,
`DepartmentAssignment`, `LocationAssignment`, `PoolAssignment`, or an
equivalent model — equipment already belongs to the pool by default; no
separate assignment relationship is required to express that.

The internal equipment UUID remains the sole relational identity for
equipment. All other identifiers (ADR-002) are business-facing
attributes of that identity, never a replacement for it.

Device-safety alerting, recall management, and external regulatory
reporting are not part of this system and are not planned. This
repository does not track or integrate with any such process.

## Consequences

- A proposal to add ownership/assignment modeling must revise this ADR
  first; it is not a routine schema addition.
- A proposal to add device-safety alerting or regulatory-reporting
  functionality is out of scope for this repository regardless of how it
  is framed.
- Scope questions for a given change are resolved by checking this ADR
  before checking any other document.

## References

- [ADR-002](ADR-002-identifier-model.md) — equipment identity detail.
- `knowledge/business-rules/equipment-pool.md` — operational rules that
  follow from this scope.
