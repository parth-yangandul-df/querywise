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
        category: Dot-namespaced error category for client routing
        retryable: Whether the client should show a retry button
        retry_after_seconds: Seconds to wait before retrying (null when not applicable)
    """

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        *,
        category: str = "pipeline.unknown",
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.category = category
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)

    def to_response_content(self) -> dict:
        return {
            "error": self.message,
            "code": self.status_code,
            "category": self.category,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
        }

    def to_stream_event(self) -> dict:
        return {
            "type": "error",
            "message": self.message,
            "code": self.status_code,
            "category": self.category,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
        }

    def to_http_exception(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail=self.message)


class InternalServerError(AppError):
    """Unexpected server error - 500"""

    def __init__(self, message: str = "Something went wrong. Please try again."):
        super().__init__(message, status_code=500, category="pipeline.unknown", retryable=False)


class NotFoundError(AppError):
    """Resource not found - 404"""

    def __init__(self, resource: str, resource_id: str = ""):
        if resource_id:
            message = f"The {resource} '{resource_id}' was not found."
        else:
            message = f"The requested {resource} was not found."
        super().__init__(message, status_code=404, category="resource.not_found", retryable=False)


class ValidationError(AppError):
    """Bad request / validation error - 422"""

    def __init__(self, message: str = "The request data is invalid. Please check your input."):
        super().__init__(message, status_code=422, category="input.validation", retryable=False)


class SQLSafetyError(AppError):
    """SQL safety violation - 403"""

    def __init__(
        self, message: str = "This query cannot be executed. It may contain unsafe operations."
    ):
        super().__init__(message, status_code=403, category="db.safety_violation", retryable=False)


class QueryTimeoutError(AppError):
    """Query timeout - 408"""

    def __init__(self, timeout_seconds: int = 30):
        message = (
            "The query took too long and was cancelled. "
            "Try a simpler question or reduce the data range."
        )
        super().__init__(
            message,
            status_code=408,
            category="db.query_timeout",
            retryable=True,
            retry_after_seconds=5,
        )


class RateLimitError(AppError):
    """Rate limit exceeded - 429"""

    def __init__(self, message: str = "Too many requests. Please wait a moment and try again."):
        super().__init__(message, status_code=429, category="llm.rate_limited", retryable=True)


class ConnectionError(AppError):
    """Database connection error - 502"""

    def __init__(self, message: str = "Database connection failed. Please contact support."):
        super().__init__(
            message,
            status_code=502,
            category="db.connection",
            retryable=True,
            retry_after_seconds=3,
        )


class ServiceUnavailableError(AppError):
    """Service unavailable - 503"""

    def __init__(self, message: str = "Service temporarily unavailable. Please try again."):
        super().__init__(
            message,
            status_code=503,
            category="service.unavailable",
            retryable=True,
            retry_after_seconds=5,
        )


class PoolExhaustedError(ServiceUnavailableError):
    """Database connection pool exhausted - 503"""

    def __init__(self, message: str = "The database is busy. Please wait a moment and try again."):
        super().__init__(message)
        self.category = "db.pool_exhausted"


class SchemaCacheStaleError(ServiceUnavailableError):
    """Schema cache is stale - 503 (auto-retry triggers refresh)"""

    def __init__(
        self, message: str = "Schema information needs to be refreshed. Please try again."
    ):
        super().__init__(message)
        self.category = "db.schema_stale"


class EmbeddingError(ServiceUnavailableError):
    """Embedding generation failed - 503"""

    def __init__(self, message: str = "Search indexing failed. Please try again."):
        super().__init__(message)
        self.category = "llm.embedding_failed"


class AuthenticationError(AppError):
    """Authentication failed - 401"""

    def __init__(self, message: str = "Please log in to continue."):
        super().__init__(message, status_code=401, category="auth.unauthorized", retryable=False)


class PermissionError(AppError):
    """Permission denied - 403"""

    def __init__(self, message: str = "You don't have permission to perform this action."):
        super().__init__(message, status_code=403, category="auth.forbidden", retryable=False)


class BadRequestError(AppError):
    """Bad request - 400"""

    def __init__(
        self, message: str = "Your request couldn't be processed. Please check your input."
    ):
        super().__init__(message, status_code=400, category="input.bad_request", retryable=False)


def sanitize_error(original: Exception, fallback_message: str, status_code: int = 500) -> AppError:
    """Sanitize any exception into a user-friendly AppError.

    Args:
        original: The original exception
        fallback_message: User-friendly message to show
        status_code: HTTP status code for categorization

    Returns:
        AppError with sanitized message (original is logged separately)
    """
    return AppError(
        fallback_message,
        status_code=status_code,
        category="pipeline.unknown",
        retryable=False,
    )


def _extract_status(exc: Exception) -> int | None:
    """Extract HTTP status code from an exception."""
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _extract_body(exc: Exception) -> str | None:
    """Extract response body text from an exception."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    return getattr(response, "text", None) or str(response)


def raise_if_provider_rate_limited(exc: Exception, provider_name: str) -> None:
    """Classify LLM API error into the right AppError subclass."""
    status = _extract_status(exc)
    body = _extract_body(exc)

    match status:
        case 408:
            raise QueryTimeoutError(30)
        case 429:
            raise RateLimitError(
                f"{provider_name} rate limit exceeded. "
                "Please wait a moment and try again."
            )
        case 402:
            raise BadRequestError("Insufficient credits. Please check your billing details.")
        case 401 | 403:
            raise AuthenticationError("Authentication failed. Please check your API key.")
        case 502 | 503 | 529:
            raise ServiceUnavailableError(
                "LLM service is temporarily unavailable. Please try again."
            )

    if body and "overloaded" in body.lower():
        raise ServiceUnavailableError("LLM provider is currently overloaded. Please try again.")
