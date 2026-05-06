"""Exception handlers - sanitize all errors to user-friendly messages."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers with sanitized output."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """Handle AppError and subclasses - already sanitized."""
        logger.warning(
            "App error on %s %s: %s (code=%s)",
            request.method,
            request.url.path,
            exc.message,
            exc.status_code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_response_content(),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Handle FastAPI HTTPException - normalize to {error, code}."""
        detail = exc.detail
        if isinstance(detail, dict):
            detail = str(detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": detail, "code": exc.status_code},
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
            content={"error": detail, "code": 422},
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
        return JSONResponse(
            status_code=500,
            content={"error": "Something went wrong. Please try again.", "code": 500},
        )
