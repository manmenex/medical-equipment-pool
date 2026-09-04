"""Roadmap PR21B/PR21C -- Canonical Issue + Receive Parsers + Validation
(bounded slices).

Authoritative design: `docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`
(especially §4, §6.1-6.3, §8.1, §9, §10.1, §13-16.1, §20.1, §22, §24.2,
§28, §43, §45-47, §54), merged as GitHub PR #103 / PR21A (squash SHA
`28f0f5eabb64cf4b27294fd3df251e90b167de0a`) and GitHub PR #104 / PR21B
canonical Issue subset (squash SHA
`a8ae9fbfc571f74bad2100abf8f90bbd22a68e74`).

**This package is deliberately an internal component, not a registered
`ImportAdapter`.** Nothing in this package calls
`app.services.import_adapter.register_adapter()` for
`legacy_transaction_history` (or any dataset_type) -- a real
`ImportSession` therefore cannot reach `validated` via this package
alone (`import_validation_service.run_validation` looks up
`get_adapter(dataset_type)` and raises `ImportAdapterNotRegisteredError`
when nothing is registered). This remains intentional and load-bearing
now that BOTH canonical sides exist: PR21C adds the canonical Receive
side (`Orders คืนเครื่อง` + `ข้อมูลรับเครื่องมือ`) alongside PR21B's
Issue side, but the design's SDC-sheet field-contract ambiguity (§6.1)
remains open, and the two sides existing is deliberately NOT treated as
authorization to register a combined final adapter. That registration
-- the thing that would actually let a real `ImportSession` reach
`validated`/dry-run-ready -- is a later, separately-authorized and
explicitly-gated step once the SDC decision is closed.

`legacy_history.types` holds the shared, dataset-agnostic result shapes
(kept as separate Issue/Receive dataclasses per §9/§10/§40 of the PR21C
task -- minimal churn preferred over a shared base); `legacy_history.common`
holds shared, dataset-agnostic parsing/resolution primitives (workbook
access, timestamp normalization, Ward resolution, blank-row detection)
reused unchanged by both sides; `legacy_history.issue` implements the
Issue side; `legacy_history.receive` implements the Receive side. Each
module produces its own independent candidate/finding lists -- neither
module imports, matches, or pairs the other's output (no Issue<->Receive
reconciliation exists anywhere in this package; that is a future PR22
responsibility)."""
