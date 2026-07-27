import json
import logging
import sys
from datetime import datetime, timezone

from app.core.log_context import RequestContextFilter

# Deliberately explicit allowlist, not `record.__dict__` passthrough: a
# passthrough would silently emit anything anyone ever passes via
# `extra={...}` at any future call site, including by accident (e.g. a
# stray field that turns out to hold request-body or credential data).
# New fields must be added here on purpose, matching this repository's
# "never log request bodies/credentials/identifiers" discipline (Roadmap
# PR15A) the same way `_redact()` (app/core/redis.py) is deliberate about
# what it exposes.
_EXTRA_FIELDS = (
    "http_method",
    "http_route",
    "http_status",
    "latency_ms",
    "duration_ms",
    "total_rows",
    "succeeded",
    "failed",
    "skipped",
    "attempted_rows",
    "update_existing",
)


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter (Roadmap PR15A).

    Replaces the prior plain-text format, matching the structured-logging
    design documented in docs/08-security.md. Only the fixed set of fields
    below is ever emitted -- see _EXTRA_FIELDS' docstring.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for id_field in ("request_id", "correlation_id", "job_run_id"):
            value = getattr(record, id_field, None)
            if value is not None:
                payload[id_field] = value
        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestContextFilter())

    # `logging.basicConfig(handlers=[handler])` is a silent no-op once the
    # root logger already has *any* handler, unless force=True -- so
    # whichever of Uvicorn, pytest, or this module happens to run first
    # would otherwise decide, by accident of import order, whether
    # application logs come out as JSON or as whatever that other caller
    # installed. Explicitly clearing the root logger's existing handlers
    # before adding this one makes the end state deterministic regardless
    # of import order, and calling this twice never leaves more than the
    # one handler installed here (idempotent).
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
