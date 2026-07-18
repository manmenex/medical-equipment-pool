"""Equipment identifier canonicalization. See ADR-002 and
knowledge/architecture/identifiers.md for the full rules; this module
implements them, it does not restate them.
"""
from app.core.exceptions import InvalidInputError

BCM_PREFIX = "BCM"


def strip_bcm_prefix(raw: str) -> str:
    """Trim and remove an optional leading "BCM" prefix (case-insensitive).

    Shared by canonicalization (normalize_bcm_code) and manual-search query
    normalization (app.crud.equipment._normalize_bcm_query) so a
    prefix-omitted and prefix-supplied input are always treated
    identically. See ADR-002 / ADR-003.
    """
    token = raw.strip()
    if token[: len(BCM_PREFIX)].upper() == BCM_PREFIX:
        token = token[len(BCM_PREFIX) :]
    return token.strip()


def normalize_bcm_code(raw: str) -> str:
    """Canonical persisted form for BCM Code (See ADR-002): trimmed,
    optional prefix normalized away and reapplied, uppercase, digit width
    after the prefix preserved exactly (leading zeros are significant).
    Applied identically at create and update.
    """
    token = strip_bcm_prefix(raw)
    if not token:
        raise InvalidInputError("BCM Code must contain at least one character after the prefix.")
    return f"{BCM_PREFIX}{token.upper()}"


def normalize_item_no(raw: str) -> str:
    """Canonical persisted form for Item No (See ADR-002): trimmed only —
    case and internal formatting are preserved exactly as scanned. Applied
    identically at create and update.
    """
    token = raw.strip()
    if not token:
        raise InvalidInputError("Item No cannot be empty.")
    return token
