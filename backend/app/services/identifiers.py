"""Equipment identifier canonicalization. See ADR-002 and
knowledge/architecture/identifiers.md for the full rules; this module
implements them, it does not restate them.
"""
from app.core.exceptions import InvalidInputError

BCM_PREFIX = "BCM"

# Matches Equipment.bcm_code / Equipment.item_no column width
# (backend/app/models/equipment.py) -- the canonical persisted form must
# fit this, not just the raw user input.
IDENTIFIER_MAX_LENGTH = 64


def strip_bcm_prefix(raw: str) -> str:
    """Lenient prefix/whitespace stripping for manual-search *query*
    tokens only (app.crud.equipment.search_bcm / _normalize_bcm_query).

    NOT used for canonicalization (see normalize_bcm_code below) --
    search tolerates a stray space between a typed "BCM" and the digits
    because it only builds a partial-match pattern, never a value that
    gets persisted or compared for uniqueness. Canonicalization is
    stricter: ADR-002 / identifiers.md does not define embedded
    whitespace after the prefix as equivalent to no whitespace, so
    normalize_bcm_code must not invent that equivalence.
    """
    token = raw.strip()
    if token[: len(BCM_PREFIX)].upper() == BCM_PREFIX:
        token = token[len(BCM_PREFIX) :]
    return token.strip()


def normalize_bcm_code(raw: str) -> str:
    """Canonical persisted form for BCM Code (See ADR-002 /
    identifiers.md), applied identically at create and update:

    1. Trim leading/trailing whitespace.
    2. Remove exactly one optional case-insensitive "BCM" prefix.
    3. Uppercase the remaining body -- digit width preserved exactly,
       leading zeros are significant and never reinterpreted.
    4. Persist "BCM" + that body.

    Deliberately does NOT strip whitespace exposed between a removed
    prefix and the body (e.g. "bcm 001") into the same form as "bcm001"
    -- ADR-002 does not define that equivalence, so such input is
    rejected with a clear error rather than silently normalized or
    silently persisted as a non-canonical value with an embedded space.
    Also rejects a final canonical value that would not fit the
    database column, so an overlength prefixless input (which only
    becomes overlength once "BCM" is prepended) fails as a controlled
    400, never a database-level truncation/DataError.
    """
    token = raw.strip()
    if token[: len(BCM_PREFIX)].upper() == BCM_PREFIX:
        token = token[len(BCM_PREFIX) :]
    if not token:
        raise InvalidInputError("BCM Code must contain at least one character after the prefix.")
    if any(ch.isspace() for ch in token):
        raise InvalidInputError("BCM Code must not contain whitespace after the prefix.")
    canonical = f"{BCM_PREFIX}{token.upper()}"
    if len(canonical) > IDENTIFIER_MAX_LENGTH:
        raise InvalidInputError(
            f"BCM Code exceeds the maximum length of {IDENTIFIER_MAX_LENGTH} characters "
            "once normalized."
        )
    return canonical


def normalize_item_no(raw: str) -> str:
    """Canonical persisted form for Item No (See ADR-002 /
    identifiers.md), applied identically at create and update: trimmed
    only -- case and internal formatting are preserved exactly as
    scanned. Also rejects a trimmed value that would not fit the
    database column.
    """
    token = raw.strip()
    if not token:
        raise InvalidInputError("Item No cannot be empty.")
    if len(token) > IDENTIFIER_MAX_LENGTH:
        raise InvalidInputError(f"Item No exceeds the maximum length of {IDENTIFIER_MAX_LENGTH} characters.")
    return token
