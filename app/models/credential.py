"""Credential metadata model.

The actual secret (password) is never held in a dataclass instance that
could be logged or serialized carelessly - it is written straight to the
OS credential vault by `app.services.credential_service` and read back on
demand. This model only carries non-secret metadata for display in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class CredentialInfo:
    service_name: str
    username: str
    last_updated: Optional[datetime] = None
    is_configured: bool = False
