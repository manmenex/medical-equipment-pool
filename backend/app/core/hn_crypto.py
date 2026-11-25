"""Roadmap PR29 (Owner Governance 2026-11-25 D1): application-level
encryption of the optional patient HN.

The HN is the only patient datum this system may hold. It is stored ONLY as a
Fernet token (``borrow_transactions.hn_ciphertext``) using a key from the host
``.env`` (``HN_ENCRYPTION_KEY``). Without a usable key HN writes are rejected
(``HnUnavailableError``) and reveals report "unavailable"; nothing else in the
application depends on it. Nothing in this module logs a plaintext, a
ciphertext, or the key.
"""
import re

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings
from app.core.exceptions import HnUnavailableError, InvalidInputError

# Light format check: letters, digits and the two separators real hospital
# numbers use ("-", "/"), 1-20 characters. Not a validity check of the number.
HN_MAX_LENGTH = 20
HN_PATTERN = re.compile(r"^[A-Za-z0-9/-]{1,20}$")
HN_FORMAT_MESSAGE = "HN must be 1-20 characters: letters, digits, '-' or '/'."


def normalize_hn(value: str | None) -> str | None:
    """Trim; empty -> None (no HN recorded). Raises ValueError (message never
    contains the value) when the format is wrong."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if not HN_PATTERN.fullmatch(value):
        raise ValueError(HN_FORMAT_MESSAGE)
    return value


def _fernet() -> MultiFernet | None:
    raw = get_settings().HN_ENCRYPTION_KEY
    if not raw or not raw.strip():
        return None
    try:
        keys = [Fernet(k.strip().encode("ascii")) for k in raw.split(",") if k.strip()]
    except Exception:  # malformed key: treated exactly like a missing one
        return None
    return MultiFernet(keys) if keys else None


def hn_available() -> bool:
    return _fernet() is not None


def encrypt_hn(hn: str) -> str:
    f = _fernet()
    if f is None:
        raise HnUnavailableError(
            "HN cannot be saved: the server's HN encryption key is not configured. "
            "Ask the administrator to set HN_ENCRYPTION_KEY."
        )
    value = normalize_hn(hn)
    if value is None:
        raise InvalidInputError("HN is empty")
    return f.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_hn(ciphertext: str) -> str:
    f = _fernet()
    if f is None:
        raise HnUnavailableError("HN is unavailable: the server's HN encryption key is not configured.")
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        raise HnUnavailableError("HN is unavailable: it cannot be decrypted with the configured key.") from None
