import uuid

from app.core.exceptions import InvalidInputError


def parse_uuid(value: str | None, field_name: str) -> uuid.UUID | None:
    """Parse a user-supplied identifier string into a UUID, or raise a safe 400.

    Several request paths accept identifiers as plain strings (query params,
    or body fields not yet worth tightening into a Pydantic UUID type) and
    previously passed them straight into uuid.UUID(...), which raises a bare
    ValueError — surfacing as an unhandled 500 — for anything malformed.
    """
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError) as exc:
        raise InvalidInputError(f"'{field_name}' is not a valid identifier") from exc
