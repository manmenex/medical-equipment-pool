# Business Rules: Borrow/Return Equipment Selection

Elaborates `equipment-selection.md` for the two workflows that need it:
dispatch (borrow) and return.

## Rule

Both dispatch and return begin with equipment selection
(`equipment-selection.md`) and then continue into their own,
separately-governed workflow once a specific equipment record is
resolved. Equipment selection is a shared front door; it does not alter
dispatch or return semantics, eligibility rules, or state transitions,
which remain governed by the confirmed domain workflow (see the domain
model reference this document does not duplicate).

## Consequence

A change to how equipment is selected (adding a matching rule, changing
what a suggestion shows, changing QR validation) must not be justified
by, or bundled with, a change to dispatch/return eligibility or state
behavior. They are reviewed as separate concerns even when they land in
the same change.
