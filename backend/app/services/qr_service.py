# See ADR-004: the hospital's own physical Item-No QR label is the only
# supported QR format. The application does not generate its own QR labels.
_MAX_ITEM_NO_LENGTH = 64

# Exact prefix of the retired, self-generated legacy scheme (see ADR-004,
# "MEP:{asset_number} intentionally retired"). Checked explicitly so a
# scanned legacy label is rejected with a distinct, controlled response
# instead of being silently treated as if it were a valid (but unknown)
# Item No.
_LEGACY_QR_PREFIX = "MEP:"


def extract_item_no_from_qr(raw: str) -> str:
    """Extracts the internal Item No from a scanned QR payload.

    Deterministic and narrow by design: trim whitespace, then require a
    non-empty result no longer than the item_no column, that does not look
    like a URL, and that is not the retired legacy `MEP:{asset_number}`
    format (a scanner will decode *any* QR code it's pointed at, including
    an unrelated web-linked one or one of this application's own
    now-retired legacy labels -- "://" and the "MEP:" prefix are safe,
    cheap signals that this payload isn't a bare hospital item number,
    which also keeps a payload that could carry an external tracking URL
    out of anything a caller might log or persist).

    Raises ValueError on anything that fails those checks; callers are
    expected to translate that into a MalformedQrCodeError. No partial or
    fuzzy extraction is performed -- the trimmed payload is either a
    plausible Item No outright, or this raises.
    """
    candidate = raw.strip()
    if not candidate:
        raise ValueError("Scanned QR payload is empty.")
    if len(candidate) > _MAX_ITEM_NO_LENGTH:
        raise ValueError("Scanned QR payload is too long to be a valid Item No.")
    if "://" in candidate:
        raise ValueError("Scanned QR payload looks like a URL, not an Item No.")
    if candidate.startswith(_LEGACY_QR_PREFIX):
        raise ValueError(
            "Scanned QR uses the retired legacy format and is not a supported hospital Item No."
        )
    return candidate
