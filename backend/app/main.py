import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import InsecureConfigurationError, settings, validate_production_secrets
from app.core.exceptions import DomainError
from app.core.log_context import correlation_id_var, request_id_var
from app.core.logging import configure_logging, safe_log
from app.worker.scheduler import start_scheduler, stop_scheduler

# Imported for its module-level `register_adapter(...)` side effect (Roadmap
# PR20C) -- this is the only place a concrete `ImportAdapter` implementation
# is guaranteed to load before the app serves any request. Add a further
# `import app.services.import_adapters.<x>` line here for each future
# dataset-type adapter (Roadmap PR21+); do not register adapters lazily
# inside a request handler.
import app.services.import_adapters.equipment_master  # noqa: E402,F401

# Roadmap PR21-Foundation. Imported for its module-level
# `register_plan_provider(...)` side effect -- the internal
# `DryRunPlanProvider` registry (`app.services.import_plan_provider`) is
# deliberately separate from the adapter registry above, but follows the
# same "import here for the registration side effect, never lazily inside
# a request handler" discipline. Add a further
# `import app.services.import_plan_providers.<x>` line here for each
# future dataset-type plan provider.
import app.services.import_plan_providers.equipment_master  # noqa: E402,F401

# Stable, safe codes for FastAPI/Starlette's own HTTPException, keyed by
# status code. Anything not listed falls back to the generic HTTP_ERROR code
# — this intentionally stays a small, fixed set rather than trying to name
# every HTTP status.
_HTTP_EXCEPTION_CODES = {
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}

configure_logging(settings.DEBUG)

logger = logging.getLogger(__name__)
# Dedicated logger for the one-per-request access-log event (Roadmap
# PR15A) -- kept distinct from `logger` (used for application/exception
# events above) so an operator can filter access-log noise separately,
# mirroring the common "app" vs "access" logger split (e.g. uvicorn's own
# uvicorn.error/uvicorn.access split).
access_logger = logging.getLogger("app.access")

# audit_logs.request_id/correlation_id are String(64) (see
# app/models/audit.py) — an inbound X-Request-ID/X-Correlation-ID header is
# client-controlled and must never be trusted as-is: an oversized value
# would fail the INSERT on PostgreSQL (VARCHAR(64)), and an unconstrained
# charset could put control characters or other unsafe content into a
# permanent audit record. Only a value that already fits the column and a
# conservative safe charset is reused verbatim; anything else falls back to
# a freshly generated ID exactly as if the header had been absent.
#
# Matched with fullmatch(), not match(): `$` (without re.MULTILINE) matches
# either the end of the string or just before a trailing "\n" — so
# match(r"^...$") on "valid_id\n" incorrectly succeeds and would let a
# newline reach the database. fullmatch() requires the whole string to
# match with no such exception.
_SAFE_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _safe_inbound_id(value: str | None) -> str | None:
    if value and _SAFE_REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return None


def _log_context(request: Request) -> dict:
    # Read from request.state, not the ContextVar: the catch-all Exception
    # handler below runs inside Starlette's ServerErrorMiddleware, which
    # sits *outside* request_context_middleware -- by the time it runs for
    # a genuinely unhandled exception, that middleware's `finally` block has
    # already reset the ContextVar (see app.core.log_context's
    # RequestContextFilter docstring). request.state survives regardless,
    # so every handler here uses this instead of relying on the ambient
    # ContextVar value being present.
    return {
        "request_id": getattr(request.state, "request_id", None),
        "correlation_id": getattr(request.state, "correlation_id", None),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    try:
        validate_production_secrets(settings)
    except InsecureConfigurationError:
        logger.critical(
            "Refusing to start: insecure production configuration detected. "
            "See the exception message below for the specific issue."
        )
        raise

    app = FastAPI(
        title=settings.PROJECT_NAME,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(SecurityHeadersMiddleware)

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        # Every request gets a request_id; correlation_id defaults to the
        # same value but lets an upstream caller group several requests
        # (e.g. a retry) under one correlation id via the header. Inbound
        # header values are validated (see _safe_inbound_id) before reuse.
        request_id = _safe_inbound_id(request.headers.get("x-request-id")) or uuid.uuid4().hex
        correlation_id = _safe_inbound_id(request.headers.get("x-correlation-id")) or request_id
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        # Roadmap PR15A: make the same IDs available to every log call in
        # this request's async call chain (service/CRUD-layer code has no
        # access to `request.state`) via ContextVar, not a second ID
        # mechanism. Tokens are reset in `finally` unconditionally -- an
        # unreset ContextVar would leak this request's IDs into whatever
        # runs next on this task/worker, including a later, unrelated
        # request if the ASGI server reuses the task.
        request_id_token = request_id_var.set(request_id)
        correlation_id_token = correlation_id_var.set(correlation_id)
        start = time.monotonic()
        status_code = 500  # only surfaces in the access log if call_next itself raises past FastAPI's own exception handling
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            # Logging must never become a dependency for request success: a
            # failure while building/emitting the access-log line must
            # never mask the real response (or the real exception, if one
            # is propagating past this finally block) -- an *unguarded*
            # fallback log call inside a bare except would itself be able
            # to raise here and, since this runs inside `finally` after a
            # successful `try`, silently replace a good response with an
            # unhandled exception. safe_log() guarantees nothing raised
            # inside it is ever allowed to propagate.
            def _emit_access_log() -> None:
                latency_ms = (time.monotonic() - start) * 1000
                # Route *template* (e.g. "/api/v1/equipment/{equipment_id}"),
                # not the raw URL: request.scope["route"] is populated by
                # Starlette's router before the endpoint runs, so it's
                # available here once call_next returns. Using the raw path
                # would make every equipment/transaction/user detail
                # request a distinct high-cardinality log key. No route
                # matches (e.g. a 404) fall back to a fixed "unmatched"
                # label rather than the raw path, for the same reason.
                route = request.scope.get("route")
                route_template = getattr(route, "path", None) or "unmatched"
                access_logger.info(
                    "request completed",
                    extra={
                        "http_method": request.method,
                        "http_route": route_template,
                        "http_status": status_code,
                        "latency_ms": round(latency_ms, 2),
                    },
                )

            safe_log(_emit_access_log)
            request_id_var.reset(request_id_token)
            correlation_id_var.reset(correlation_id_token)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        # Application/domain errors are expected, handled outcomes (duplicate
        # keys, not-found, invalid input, business-rule conflicts) — logged
        # at INFO with just enough context to spot patterns, no traceback.
        logger.info(
            "Handled application error: code=%s status=%s path=%s",
            exc.code,
            exc.status_code,
            request.url.path,
            extra=_log_context(request),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code, "status": exc.status_code},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI/Pydantic-level request validation (bad types, missing
        # required fields, failed schema constraints) — never reached the
        # domain layer. Each error's raw `input`/`ctx` is intentionally
        # dropped: Pydantic v2 includes the offending value there verbatim,
        # which would otherwise reflect back anything the client submitted
        # to a field, including passwords or other sensitive values.
        logger.info("Request validation failed: path=%s", request.url.path, extra=_log_context(request))
        errors = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ()) if part != "body"),
                "message": err.get("msg", "Invalid value"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Request validation failed.",
                "code": "VALIDATION_ERROR",
                "status": 422,
                "errors": errors,
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Registered on the base Starlette HTTPException (not just
        # fastapi.HTTPException) so this also catches exceptions Starlette's
        # own routing raises directly, e.g. 405 Method Not Allowed. Replaces
        # FastAPI's default handler, which returns {"detail": ...} only —
        # this brings it into the same {detail, code, status} contract as
        # every other error response. `exc.headers` (e.g. WWW-Authenticate on
        # a 401) is forwarded unchanged; authorization behavior itself is
        # untouched, this only changes the response body shape.
        logger.info(
            "HTTP exception: status=%s path=%s", exc.status_code, request.url.path, extra=_log_context(request)
        )
        detail = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        code = _HTTP_EXCEPTION_CODES.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail, "code": code, "status": exc.status_code},
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Genuinely unexpected errors (not a DomainError, not FastAPI's own
        # HTTPException/RequestValidationError, which keep their own more
        # specific handlers). The full exception is logged server-side for
        # diagnosis; the client only ever sees a safe, generic envelope —
        # never the exception message, type, or a stack trace.
        logger.exception("Unhandled exception on path=%s", request.url.path, extra=_log_context(request))
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred.", "code": "INTERNAL_ERROR", "status": 500},
        )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = create_app()
