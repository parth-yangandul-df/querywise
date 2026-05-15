"""Exception handlers - sanitize all errors to user-friendly messages."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.core._log_errors import log_db_error
from app.core.exceptions import (
    AppError,
    BadRequestError,
    ConnectionError,
    InternalServerError,
    NotFoundError,
    PoolExhaustedError,
    QueryTimeoutError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

# Attempt to import optional DB/HTTP dependencies
try:
    import asyncpg
except ImportError:
    asyncpg = None

try:
    import httpx
except ImportError:
    httpx = None


def _make_unknown_response(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": "Something went wrong. Please try again.",
            "code": 500,
            "category": "pipeline.unknown",
            "retryable": False,
            "retry_after_seconds": None,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers with sanitized output."""

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        """Handle NotFoundError - generic message, log details server-side."""
        logger.warning(
            "NotFound: %s %s -> %s",
            request.method,
            request.url.path,
            exc.message,
        )
        return JSONResponse(
            status_code=404,
            content=exc.to_response_content(),
        )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """Handle AppError and subclasses - already sanitized."""
        logger.warning(
            "App error on %s %s: %s (code=%s, category=%s)",
            request.method,
            request.url.path,
            exc.message,
            exc.status_code,
            exc.category,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_response_content(),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Handle FastAPI HTTPException - normalize to error object."""
        detail = exc.detail
        if isinstance(detail, dict):
            detail = str(detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": detail,
                "code": exc.status_code,
                "category": "http." + str(exc.status_code),
                "retryable": False,
                "retry_after_seconds": None,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Handle Pydantic validation errors - user-friendly message."""
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = " → ".join(str(part) for part in first.get("loc", []) if part != "body")
            msg = first.get("msg", "Invalid input")
            detail = f"Invalid input in {loc}: {msg}" if loc else "Invalid input"
        else:
            detail = "Request validation failed"
        return JSONResponse(
            status_code=422,
            content={
                "error": detail,
                "code": 422,
                "category": "input.validation",
                "retryable": False,
                "retry_after_seconds": None,
            },
        )

    if DBAPIError is not None:

        @app.exception_handler(DBAPIError)
        async def dbapi_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
            """Handle SQLAlchemy DBAPIError - classify by underlying DB exception."""
            orig = exc.orig
            sqlstate = getattr(orig, "sqlstate", None) if orig else None
            pgcode = getattr(orig, "pgcode", None) if orig else None

            log_db_error(
                logger,
                exc,
                sqlstate=sqlstate or "?",
                pgcode=pgcode or "?",
                query=request.url.path,
            )

            if asyncpg is not None and orig is not None:
                if isinstance(orig, asyncpg.exceptions.QueryCanceledError):
                    app_exc: AppError = QueryTimeoutError(30)
                elif isinstance(orig, asyncpg.exceptions.ConnectionDoesNotExistError):
                    app_exc = ConnectionError()
                elif "Pool" in type(orig).__name__ or "timeout" in str(orig).lower():
                    app_exc = PoolExhaustedError()
                else:
                    app_exc = InternalServerError()
            elif "timeout" in str(exc).lower():
                app_exc = QueryTimeoutError(30)
            else:
                app_exc = InternalServerError()

            return JSONResponse(
                status_code=app_exc.status_code,
                content=app_exc.to_response_content(),
            )

    if httpx is not None:

        @app.exception_handler(httpx.HTTPStatusError)
        async def httpx_status_error_handler(
            request: Request, exc: httpx.HTTPStatusError
        ) -> JSONResponse:
            """Handle httpx HTTP status errors - route by status code."""
            status = exc.response.status_code
            match status:
                case 408:
                    app_exc = QueryTimeoutError(30)
                case 429:
                    from app.core.exceptions import RateLimitError

                    app_exc = RateLimitError(
                        "Rate limit exceeded. Please wait a moment and try again."
                    )
                case 401 | 403:
                    from app.core.exceptions import AuthenticationError

                    app_exc = AuthenticationError(
                        "Authentication failed. Please check your API key."
                    )
                case 502 | 503 | 529:
                    app_exc = ServiceUnavailableError(
                        "Service temporarily unavailable. Please try again."
                    )
                case _:
                    app_exc = BadRequestError(f"Upstream service returned status {status}")
            return JSONResponse(
                status_code=app_exc.status_code,
                content=app_exc.to_response_content(),
            )

        @app.exception_handler(httpx.ConnectError)
        async def httpx_connect_error_handler(
            request: Request, exc: httpx.ConnectError
        ) -> JSONResponse:
            """Handle httpx connection errors."""
            logger.warning("HTTP connection error on %s %s", request.method, request.url.path)
            app_exc = ConnectionError("Failed to connect to upstream service.")
            return JSONResponse(
                status_code=app_exc.status_code,
                content=app_exc.to_response_content(),
            )

        @app.exception_handler(httpx.TimeoutException)
        async def httpx_timeout_error_handler(
            request: Request, exc: httpx.TimeoutException
        ) -> JSONResponse:
            """Handle httpx timeouts."""
            app_exc = QueryTimeoutError(30)
            return JSONResponse(
                status_code=app_exc.status_code,
                content=app_exc.to_response_content(),
            )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Catch-all - NEVER leak technical details to client."""
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return _make_unknown_response(request)
