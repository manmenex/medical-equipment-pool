import io

import qrcode


def build_qr_value(asset_number: str) -> str:
    return f"MEP:{asset_number}"


def generate_qr_png(value: str) -> bytes:
    img = qrcode.make(value)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
