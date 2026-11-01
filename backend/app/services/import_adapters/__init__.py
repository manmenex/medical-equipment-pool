"""Concrete `ImportAdapter` implementations for real legacy dataset types
(Roadmap PR20/PR21). `app.main` imports each adapter module for its
registration side effect (`register_adapter(...)` at module scope) -- this
package itself performs no registration.
"""
