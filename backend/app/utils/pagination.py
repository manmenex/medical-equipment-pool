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
