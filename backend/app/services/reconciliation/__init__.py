"""Roadmap PR22C -- Deterministic Reconciliation Analysis Engine
(docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md §9-§18, §22-§27,
§34, §36). See `engine.execute_reconciliation_run` for the single
top-level entry point.

Scope boundary (this slice only): analysis execution and immutable
finding persistence. No public HTTP route, no review/disposition
service, no sign-off logic, no frontend -- see the module docstrings in
`engine`/`persistence`/each rule module for the exact boundary each one
respects.
"""

from .engine import execute_reconciliation_run
from .rule_version import PR22_RECONCILIATION_RULE_VERSION

__all__ = ["execute_reconciliation_run", "PR22_RECONCILIATION_RULE_VERSION"]
