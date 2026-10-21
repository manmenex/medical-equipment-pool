# Glossary

Authoritative definitions for terms used across `knowledge/`. Where
another repository document defines one of these terms differently, this
glossary is correct for it, and the other document should be corrected
or pointed here.

| Term | Definition | Do not confuse with |
|---|---|---|
| Equipment Pool | The central unit that dispatches and receives pool equipment | Not a hospital-wide asset-management system — [ADR-001](adr/ADR-001-equipment-pool-scope.md) |
| Internal UUID | The relational identity of one equipment record | Not a business-facing identifier; never entered manually |
| BCM Code | The primary operator-facing equipment identifier; the only identifier manual search matches | Not Item No, Asset Number, or a QR payload — [ADR-002](adr/ADR-002-identifier-model.md) |
| Item No | The identifier encoded in the hospital's existing QR labels; used only for exact QR lookup | Not BCM Code; never a manual-search identifier — [ADR-002](adr/ADR-002-identifier-model.md), [ADR-004](adr/ADR-004-hospital-item-no-qr.md) |
| Asset Number | Retained inventory metadata | Not a supported QR or manual-search identifier |
| ~~ME Code~~ | Retired placeholder name; superseded by BCM Code and Item No | Do not use — [ADR-002](adr/ADR-002-identifier-model.md) |
| Manual search | Operator-initiated equipment lookup by typed input | BCM Code only — [ADR-003](adr/ADR-003-bcm-manual-search.md) |
| QR resolution | Resolving a scanned label to one equipment record by exact Item No match | Not partial matching; not BCM Code matching — [ADR-004](adr/ADR-004-hospital-item-no-qr.md) |
| Operator-facing response | Any response returned to an equipment-selection or dispatch/return workflow | Never includes Item No — [`architecture/api-information-boundaries.md`](architecture/api-information-boundaries.md) |
| Restricted administrative/import contract | A response explicitly separate from operator-facing contracts, permitted to include Item No | Not the same shape as an operator-facing response |

For domain terms outside equipment identification (dispatch, receipt,
equipment states, Shift Sessions, and similar), the existing project
glossary and domain model remain the reference until migrated here.
