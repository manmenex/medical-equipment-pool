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


# Logger name for safe_log's own fallback report -- deliberately distinct
# from any application logger name so it's never confused with a real
# business-logic or access-log event when filtering/searching logs.
_FALLBACK_LOGGER_NAME = "app.observability"


def safe_log(emit) -> None:
    """Runs a zero-arg logging callable and guarantees no exception ever
    escapes back to the caller (Roadmap PR15A architecture rule:
    observability must never influence business outcome). Every
    post-success `logger.*` call this application makes -- access-log
    emission, scheduler completion logging, import completion logging --
    must go through this, not a bare try/except with an unguarded fallback
    log call, because an *unguarded* fallback can itself raise and, if
    that happens inside a `finally` block after a successful `try`,
    silently replace a successful return value with an unhandled
    exception (or, inside an `except` block, replace the real exception
    being propagated with an unrelated logging failure).

    A failure in `emit` is reported via a best-effort fallback log call;
    if even *that* fails, it is silently discarded -- there is no further
    fallback to fall back to, and letting a third attempt raise would
    defeat the entire point of this function.
    """
    try:
        emit()
    except Exception:
        try:
            logging.getLogger(_FALLBACK_LOGGER_NAME).warning(
                "Observability logging call failed", exc_info=True
            )
        except Exception:
            pass


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
