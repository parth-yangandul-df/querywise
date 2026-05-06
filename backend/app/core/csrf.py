"""CSRF double-submit cookie middleware.

Validates that mutating requests (POST, PUT, PATCH, DELETE) include an
X-CSRF-Token header matching the csrf_token cookie set during authentication.

Safe methods (GET, HEAD, OPTIONS, TRACE) and auth cookie-management endpoints
are exempt from validation.
"""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

# Paths that set or clear cookies — no CSRF token exists yet or is being removed
CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/cookie",
    "/api/v1/auth/logout",
}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Enforce double-submit cookie CSRF protection on mutating requests."""

    async def dispatch(self, request: Request, call_next):
        # Skip in development for curl/Postman convenience
        if settings.environment == "development":
            return await call_next(request)

        # Safe methods don't mutate state — no CSRF risk
        if request.method in SAFE_METHODS:
            return await call_next(request)

        # Auth endpoints set/clear cookies — exempt
        if request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Double-submit cookie validation (timing-safe comparison)
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = request.headers.get("x-csrf-token")

        if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            return Response(
                content='{"detail":"CSRF token missing or invalid"}',
                status_code=403,
                media_type="application/json",
            )

        return await call_next(request)
