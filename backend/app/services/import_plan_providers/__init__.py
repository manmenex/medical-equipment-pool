"""Concrete `DryRunPlanProvider` implementations (Roadmap PR21-Foundation).
`app.main` imports each provider module for its registration side effect
(`register_plan_provider(...)` at module scope) -- this package itself
performs no registration.
"""
