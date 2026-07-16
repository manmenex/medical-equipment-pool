"""
Small validation / environment-check helpers used across services.

FUNCTION 12 - ERROR HANDLING support: internet connectivity detection and
Excel file sanity checks live here so every caller reports errors
consistently instead of leaking raw stack traces to the UI.
"""

from __future__ import annotations

import socket
from pathlib import Path

from app.utils.exceptions import InvalidExcelFileError, NetworkUnavailableError

VALID_EXCEL_EXTENSIONS = {".xlsx", ".xls"}


def check_internet_connection(host: str = "8.8.8.8", port: int = 53, timeout: float = 3.0) -> bool:
    """Best-effort check that the machine currently has internet access."""
    try:
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((host, port))
        return True
    except OSError:
        return False


def require_internet_connection() -> None:
    """Raise `NetworkUnavailableError` if there is no internet connection."""
    if not check_internet_connection():
        raise NetworkUnavailableError(
            "No internet connection detected. Check the network cable/Wi-Fi and try again."
        )


def validate_excel_path(path: str | Path) -> Path:
    """Validate that `path` points to a readable, non-empty Excel file.

    Raises `InvalidExcelFileError` with a human-readable reason otherwise.
    """
    p = Path(path)
    if not p.exists():
        raise InvalidExcelFileError(f"File not found: {p}")
    if p.suffix.lower() not in VALID_EXCEL_EXTENSIONS:
        raise InvalidExcelFileError(
            f"Unsupported file type '{p.suffix}'. Expected one of {sorted(VALID_EXCEL_EXTENSIONS)}"
        )
    if p.stat().st_size == 0:
        raise InvalidExcelFileError(f"File is empty: {p}")
    return p


def normalize_text(value: object) -> str:
    """Normalize a cell value to a trimmed string, treating NaN/None as ''."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text
