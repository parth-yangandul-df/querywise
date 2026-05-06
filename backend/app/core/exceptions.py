"""Error handling with user-friendly messages.

All exceptions in this module return ONLY user-friendly messages that can be shown to clients.
Technical details are logged internally but never exposed.
"""

from fastapi import HTTPException


class AppError(Exception):
    """Base exception with HTTP status code and user-friendly message.

    Args:
        message: User-friendly message shown to client
        status_code: HTTP status code (4xx, 5xx) for categorization
    """

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def to_response_content(self) -> dict:
        return {"error": self.message, "code": self.status_code}

    def to_stream_event(self) -> dict:
        return {
            "type": "error",
            "message": self.message,
            "code": self.status_code,
        }

    def to_http_exception(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail=self.message)


class InternalServerError(AppError):
    """Unexpected server error - 500"""

    def __init__(self, message: str = "Something went wrong. Please try again."):
        super().__init__(message, status_code=500)


class NotFoundError(AppError):
    """Resource not found - 404"""

    def __init__(self, resource: str, resource_id: str = ""):
        if resource_id:
            message = f"The {resource} '{resource_id}' was not found."
        else:
            message = f"The requested {resource} was not found."
        super().__init__(message, status_code=404)


class ValidationError(AppError):
    """Bad request / validation error - 422"""

    def __init__(self, message: str = "The request data is invalid. Please check your input."):
        super().__init__(message, status_code=422)


class SQLSafetyError(AppError):
    """SQL safety violation - 403"""

    def __init__(
        self, message: str = "This query cannot be executed. It may contain unsafe operations."
    ):
        super().__init__(message, status_code=403)


class QueryTimeoutError(AppError):
    """Query timeout - 408"""

    def __init__(self, timeout_seconds: int = 30):
        message = "The query took too long and was cancelled. Try a simpler question or reduce the data range."
        super().__init__(message, status_code=408)


class RateLimitError(AppError):
    """Rate limit exceeded - 429"""

    def __init__(self, message: str = "Too many requests. Please wait a moment and try again."):
        super().__init__(message, status_code=429)


class ConnectionError(AppError):
    """Database connection error - 502"""

    def __init__(self, message: str = "Database connection failed. Please contact support."):
        super().__init__(message, status_code=502)


class ServiceUnavailableError(AppError):
    """Service unavailable - 503"""

    def __init__(self, message: str = "Service temporarily unavailable. Please try again."):
        super().__init__(message, status_code=503)


class AuthenticationError(AppError):
    """Authentication failed - 401"""

    def __init__(self, message: str = "Please log in to continue."):
        super().__init__(message, status_code=401)


class PermissionError(AppError):
    """Permission denied - 403"""

    def __init__(self, message: str = "You don't have permission to perform this action."):
        super().__init__(message, status_code=403)


class BadRequestError(AppError):
    """Bad request - 400"""

    def __init__(
        self, message: str = "Your request couldn't be processed. Please check your input."
    ):
        super().__init__(message, status_code=400)


def sanitize_error(original: Exception, fallback_message: str, status_code: int = 500) -> AppError:
    """Sanitize any exception into a user-friendly AppError.

    Args:
        original: The original exception
        fallback_message: User-friendly message to show
        status_code: HTTP status code for categorization

    Returns:
        AppError with sanitized message (original is logged separately)
    """
    return AppError(fallback_message, status_code=status_code)


def raise_if_provider_rate_limited(exc: Exception, provider_name: str) -> None:
    """Convert provider rate limit to RateLimitError."""
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        raise RateLimitError("Rate limit exceeded. Please wait a moment and try again.")

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if response_status == 429:
        raise RateLimitError("Rate limit exceeded. Please wait a moment and try again.")
