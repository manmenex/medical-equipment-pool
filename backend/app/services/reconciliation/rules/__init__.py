"""Roadmap PR22C §9/§12 -- one module per finding code. Each module
exposes a single `evaluate(context: ReconciliationContext) ->
tuple[FindingCandidate, ...]` function: a pure function over the
immutable `ReconciliationContext`, no DB access, no mutation, fully
deterministic for a given context. `app.services.reconciliation.engine`
is the only caller of these functions, and
`app.services.reconciliation.persistence` is the only place their
output is ever written to the database.
"""
