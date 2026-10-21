"""Immutable BCM Code / Item No canonicalization test vectors (ADR-002).

Deliberately data-only -- no import of app.services.identifiers, no
import of any alembic migration module, and no canonicalization logic of
its own. This file exists so tests/test_equipment.py (exercising the
live runtime API) and tests/test_postgres_integration.py (exercising the
real migration via the alembic CLI) can be checked against the exact
same set of inputs and expected outcomes without either test suite
importing the other's implementation -- see PR5's "shared test vectors,
separate implementations" requirement. If the runtime and the migration
ever disagree on one of these vectors, that disagreement is a bug in one
of them, not a gap in test coverage.

Each vector is (raw_input, expected_canonical_or_None). A canonical value
means the input must be ACCEPTED and produce exactly that stored value.
None means the input must be REJECTED -- as a controlled response by
whichever system is being tested (never a 500, never a raw database
error, never a silent rewrite into some other value).
"""

# ---------------------------------------------------------------------------
# BCM Code
# ---------------------------------------------------------------------------

BCM_VALID_VECTORS: list[tuple[str, str]] = [
    ("001", "BCM001"),
    ("BCM001", "BCM001"),
    ("bcm001", "BCM001"),
    (" BCM001 ", "BCM001"),
    ("00042", "BCM00042"),  # leading zeros preserved
    ("BCM00042", "BCM00042"),  # leading zeros preserved, prefix supplied
]

BCM_INVALID_VECTORS: list[tuple[str, str]] = [
    # (raw_input, human-readable rejection category)
    ("BCM", "prefix_only_empty_body"),
    ("", "empty"),
    ("   ", "whitespace_only"),
    ("BCM 001", "embedded_whitespace_after_prefix"),
    (" BCM 001 ", "embedded_whitespace_after_prefix"),
    ("BC M001", "embedded_whitespace_no_prefix_match"),
    ("001 002", "embedded_whitespace_no_prefix_match"),
    ("9" * 64, "overlength_after_canonicalization"),  # fits raw; "BCM" + 64 chars = 67
]

# ---------------------------------------------------------------------------
# Item No
# ---------------------------------------------------------------------------

ITEM_NO_VALID_VECTORS: list[tuple[str, str]] = [
    ("ITEM01", "ITEM01"),
    ("  ITEM01  ", "ITEM01"),  # surrounding whitespace trimmed
    ("MiXed-Case-001", "MiXed-Case-001"),  # case preserved exactly
    ("00042", "00042"),  # leading zeros preserved
]

ITEM_NO_INVALID_VECTORS: list[tuple[str, str]] = [
    ("", "empty"),
    ("   ", "whitespace_only"),
    ("I" * 65, "overlength"),
]
