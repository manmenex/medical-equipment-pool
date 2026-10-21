import base64
import json
from datetime import datetime
from typing import Any

from app.core.exceptions import InvalidInputError


def encode_cursor(created_at: datetime, id_: str) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": id_})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    # PR68-Blocker3: a client-supplied cursor is untrusted input -- invalid
    # Base64, non-UTF8 bytes, malformed JSON, a missing "t"/"id" field, or an
    # unparseable timestamp must surface as a normal 400 INVALID_INPUT
    # (the same DomainError this module's callers already raise for their
    # own input validation, e.g. business_date_from > business_date_to on
    # the report endpoints), never as an uncaught exception reaching the
    # generic 500 handler. `binascii.Error`, `UnicodeDecodeError`, and
    # `json.JSONDecodeError` are all `ValueError` subclasses, so this single
    # except clause covers every expected parsing failure without a bare
    # `except Exception` that would also swallow genuine programming bugs.
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data: dict[str, Any] = json.loads(raw)
        return datetime.fromisoformat(data["t"]), data["id"]
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidInputError("Invalid or malformed pagination cursor.") from exc


def encode_alpha_cursor(sort_value: str, id_: str) -> str:
    """Roadmap PR17 Slice 2 (`app.crud.user.list_operators`): the same
    base64/JSON cursor technique as `encode_cursor` above, for a query
    ordered by a string column (`full_name ASC, id ASC`) rather than
    `created_at DESC, id DESC` -- a distinct ordering basis (§10.4), not a
    second incompatible pagination implementation."""
    raw = json.dumps({"v": sort_value, "id": id_})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_alpha_cursor(cursor: str) -> tuple[str, str]:
    # Same malformed-input handling as decode_cursor above -- see that
    # function's comment for why this exact except clause is sufficient.
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data: dict[str, Any] = json.loads(raw)
        return data["v"], data["id"]
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidInputError("Invalid or malformed pagination cursor.") from exc


def encode_int_cursor(sort_value: int, id_: str) -> str:
    """Roadmap PR19A2 (`app.crud.import_job.list_findings`): the same
    base64/JSON cursor technique as `encode_cursor`/`encode_alpha_cursor`
    above, for a query ordered by an integer column -- `ImportRowError`
    has no `created_at` to sort by (§4.4), so `GET /{id}/errors` orders by
    a row-number-derived integer instead. A distinct ordering basis, not a
    second incompatible pagination implementation."""
    raw = json.dumps({"n": sort_value, "id": id_})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_int_cursor(cursor: str) -> tuple[int, str]:
    # Same malformed-input handling as decode_cursor above.
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data: dict[str, Any] = json.loads(raw)
        sort_value = data["n"]
        if not isinstance(sort_value, int) or isinstance(sort_value, bool):
            raise ValueError("cursor's integer sort field is not an integer")
        return sort_value, data["id"]
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidInputError("Invalid or malformed pagination cursor.") from exc
