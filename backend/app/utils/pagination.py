import base64
import json
from datetime import datetime
from typing import Any


def encode_cursor(created_at: datetime, id_: str) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": id_})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    data: dict[str, Any] = json.loads(raw)
    return datetime.fromisoformat(data["t"]), data["id"]


def encode_alpha_cursor(sort_value: str, id_: str) -> str:
    """Roadmap PR17 Slice 2 (`app.crud.user.list_operators`): the same
    base64/JSON cursor technique as `encode_cursor` above, for a query
    ordered by a string column (`full_name ASC, id ASC`) rather than
    `created_at DESC, id DESC` -- a distinct ordering basis (§10.4), not a
    second incompatible pagination implementation."""
    raw = json.dumps({"v": sort_value, "id": id_})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_alpha_cursor(cursor: str) -> tuple[str, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    data: dict[str, Any] = json.loads(raw)
    return data["v"], data["id"]
