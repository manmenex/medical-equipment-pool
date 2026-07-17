import io

import qrcode

# Roadmap PR5 (docs/kickoffs/PR5-equipment-master-bcm-search.md): the
# hospital's existing physical equipment QR labels are a *different* scheme
# from build_qr_value/MEP: below -- this app's own self-generated labels for
# equipment that never had one. The existing labels' raw decoded payload IS
# the Item No, with no prefix or structure of its own. Matches
# Equipment.item_no's column width; a payload longer than this cannot be a
# real item_no.
_MAX_ITEM_NO_LENGTH = 64


def build_qr_value(asset_number: str) -> str:
    return f"MEP:{asset_number}"


def generate_qr_png(value: str) -> bytes:
    img = qrcode.make(value)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def extract_item_no_from_qr(raw: str) -> str:
    """Extracts the internal Item No from a scanned QR payload.

    Deterministic and narrow by design: trim whitespace, then require a
    non-empty result no longer than the item_no column and that does not
    look like a URL (a scanner will decode *any* QR code it's pointed at,
    including an unrelated web-linked one, and "://" is a safe, cheap
    signal that this payload isn't a bare hospital item number -- this
    also keeps a payload that could carry an external tracking URL out of
    anything a caller might log or persist).

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
    return candidate
