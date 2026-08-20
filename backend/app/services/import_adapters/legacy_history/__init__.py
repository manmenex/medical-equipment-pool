"""Roadmap PR21B -- Canonical Issue Parser + Validation (bounded slice).

Authoritative design: `docs/design/PR21_LEGACY_TRANSACTION_HISTORY_IMPORT_PLAN.md`
(especially §4, §6.1-6.3, §8.1, §9, §10.1, §13-16.1, §20.1, §22, §24.2,
§28, §43, §45-47, §54), merged as GitHub PR #103 / PR21A (squash SHA
`28f0f5eabb64cf4b27294fd3df251e90b167de0a`).

**This package is deliberately an internal component, not a registered
`ImportAdapter`.** Nothing in this package calls
`app.services.import_adapter.register_adapter()` for
`legacy_transaction_history` (or any dataset_type) -- a real
`ImportSession` therefore cannot reach `validated` via this package
alone (`import_validation_service.run_validation` looks up
`get_adapter(dataset_type)` and raises `ImportAdapterNotRegisteredError`
when nothing is registered). This is intentional and load-bearing: PR21B
implements only the canonical Issue side (`Orders ยืมเครื่อง` +
`ข้อมูลส่งเครื่องมือ`); PR21C's Receive side has not been implemented,
and the design's SDC-sheet field-contract ambiguity (§6.1) remains
open. The full PR21 dataset adapter -- the thing that would actually be
registered -- is a later, separately-authorized slice's responsibility,
once both sides exist and the combined adapter is explicitly reviewed.

`legacy_history.types` holds the shared, dataset-agnostic result shapes;
`legacy_history.common` holds shared, dataset-agnostic parsing/
resolution primitives (workbook access, timestamp normalization, Ward
resolution, blank-row detection) that a future PR21C Receive parser can
reuse without duplicating; `legacy_history.issue` implements the Issue
side only -- no Receive-side branch exists anywhere in this package."""
