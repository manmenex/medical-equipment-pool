import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import InsecureConfigurationError, settings, validate_production_secrets
from app.core.exceptions import DomainError
from app.core.logging import configure_logging
from app.worker.scheduler import start_scheduler, stop_scheduler

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
        logger.info("Request validation failed: path=%s", request.url.path)
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
        logger.info("HTTP exception: status=%s path=%s", exc.status_code, request.url.path)
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
        logger.exception("Unhandled exception on path=%s", request.url.path)
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
