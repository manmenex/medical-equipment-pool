"""Roadmap PR22C (docs/design/PR22_LEGACY_DATA_RECONCILIATION_PLAN.md §4)
-- the single explicit analysis rule version this engine implements.

Deliberately not a git SHA, a timestamp, or a frontend version: it is a
short, hand-assigned, monotonically-advanced string that identifies the
*semantic* ruleset a `LegacyReconciliationRun` was executed under.
`LegacyReconciliationRun.rule_version` is compared against this constant
before any analysis runs (`app.services.reconciliation.engine`) -- a run
created for a different rule version fails closed
(`UnsupportedReconciliationRuleVersionError`) rather than silently
executing under a mismatched ruleset. This constant is bumped only when
the rule set's *semantics* change in a way that would produce a
different finding set for the same input snapshot; a purely internal
refactor with unchanged semantics does not bump it.
"""

PR22_RECONCILIATION_RULE_VERSION = "pr22-v1"
