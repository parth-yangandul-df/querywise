import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import jwt as pyjwt
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.v1.router import api_router
from app.config import settings
from app.core.csrf import CSRFMiddleware
from app.core.exception_handlers import register_exception_handlers
from app.core.limiter import limiter
from app.core.logging_config import set_request_id, setup_logging
from app.db.session import async_session_factory, engine

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Initialize logging with JSONL output to backend/logs/."""
    setup_logging(
        app_name="querywise",
        level=settings.log_level,
        file_enabled=settings.log_file_enabled,
        rotation=settings.log_rotation,
        retention=settings.log_retention,
    )


# ---------------------------------------------------------------------------
# Middleware classes
# ---------------------------------------------------------------------------


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Enforce a maximum request duration; returns 504 Gateway Timeout on expiry."""

    async def dispatch(self, request: Request, call_next):
        timeout_seconds = settings.default_query_timeout_seconds * 4
        try:
            async with asyncio.timeout(timeout_seconds):
                return await call_next(request)
        except TimeoutError:
            return Response(
                content='{"detail":"Request timeout"}',
                status_code=504,
                media_type="application/json",
            )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set browser security headers on every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate or propagate X-Request-ID and bind it to the logging context."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        set_request_id(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class MetricsAuthMiddleware(BaseHTTPMiddleware):
    """Require admin auth for /metrics endpoint in non-development environments."""

    async def dispatch(self, request: Request, call_next):
        # Open in development; only guard /metrics in production/staging
        if settings.environment == "development" or request.url.path != "/metrics":
            return await call_next(request)

        # Extract token from cookie or Authorization header
        token = request.cookies.get("access_token")
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            return Response(
                content='{"detail":"Authentication required"}',
                status_code=401,
                media_type="application/json",
            )

        # Validate token and check admin role — decode directly, no DB lookup needed
        try:
            payload = pyjwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except pyjwt.InvalidTokenError:
            return Response(
                content='{"detail":"Invalid token"}',
                status_code=401,
                media_type="application/json",
            )

        if payload.get("role") != "admin":
            return Response(
                content='{"detail":"Admin access required"}',
                status_code=403,
                media_type="application/json",
            )

        return await call_next(request)


class RequestBodySizeMiddleware(BaseHTTPMiddleware):
    """Enforce maximum request body size to prevent DOS attacks."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            max_size_bytes = settings.max_request_body_size_mb * 1024 * 1024
            if int(content_length) > max_size_bytes:
                return Response(
                    content='{"detail":"Request body too large"}',
                    status_code=413,
                    media_type="application/json",
                )
        return await call_next(request)


def _validate_production_settings() -> None:
    """Fail fast if production-secrets are still set to dev defaults."""
    if settings.environment != "development":
        if settings.encryption_key == "dev-encryption-key-change-in-production":
            raise RuntimeError("Production encryption_key must be changed from default")
        if not settings.jwt_secret or settings.jwt_secret == "change-me-to-a-random-secret":
            raise RuntimeError("Production jwt_secret must be set to a non-trivial value")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure logging FIRST — before any startup work emits log messages
    _configure_logging()

    # Validate secrets before accepting traffic
    _validate_production_settings()

    # Startup: ensure vector columns match configured dimension
    from app.services.setup_service import ensure_embedding_dimensions

    logger.info("QueryWise startup: checking embedding dimensions")
    try:
        await ensure_embedding_dimensions()
    except Exception:
        logger.warning(
            "ensure_embedding_dimensions() failed; "
            "vector search may be unavailable until DB is reachable",
            exc_info=True,
        )

    # Auto-setup sample database (only when feature flag is enabled)
    if settings.auto_setup_sample_db:
        from app.services.setup_service import auto_setup_sample_db

        logger.info("QueryWise startup: auto-setup sample DB enabled, running...")
        try:
            await auto_setup_sample_db()
            logger.info("QueryWise startup: sample DB setup complete")
        except Exception:
            logger.warning("Auto-setup sample DB failed", exc_info=True)

    # Pre-warm embedding provider — eliminates ~33s cold-start delay on first query
    # (lazy module import + client instantiation + first OpenRouter API call)
    from app.services.embedding_service import embed_text

    logger.info("QueryWise startup: pre-warming embedding provider")
    try:
        await embed_text("warmup")
        logger.info("QueryWise startup: embedding provider warmed OK")
    except Exception:
        logger.warning(
            "Embedding provider pre-warm failed; first query will pay cold-start cost",
            exc_info=True,
        )

    # Pre-warm LLM provider singleton — avoids first-call module import overhead
    from app.llm.provider_registry import get_provider

    logger.info("QueryWise startup: pre-warming LLM provider")
    try:
        get_provider(settings.default_llm_provider)
        logger.info("QueryWise startup: LLM provider warmed OK")
    except Exception:
        logger.warning("LLM provider pre-warm failed", exc_info=True)

    # Pre-compile LangGraph — eliminates graph build cost on the first query after deploy
    from app.llm.graph.graph import get_compiled_graph

    logger.info("QueryWise startup: pre-compiling LangGraph")
    try:
        get_compiled_graph()
        logger.info("QueryWise startup: LangGraph compiled OK")
    except Exception:
        logger.warning("LangGraph pre-compile failed", exc_info=True)

    # Pre-warm connection pools — eliminates cold-start latency on first query per connection
    logger.info("QueryWise startup: pre-warming connection pools")
    try:
        await _prewarm_connectors()
        logger.info("QueryWise startup: connection pools warmed OK")
    except Exception:
        logger.warning("Connection pool pre-warm failed — non-critical", exc_info=True)

    # Initialise MLflow tracing (optional — disabled if mlflow_enabled=false
    # or mlflow package not installed)
    if settings.mlflow_enabled:
        from app.core.mlflow_tracing import setup_mlflow

        logger.info("QueryWise startup: initialising MLflow tracing")
        setup_mlflow(
            tracking_uri=settings.mlflow_tracking_uri,
            experiment_name=settings.mlflow_experiment,
        )

    logger.info("QueryWise startup complete")
    yield
    # Shutdown
    from app.core.redis import close_redis

    await close_redis()
    await engine.dispose()


async def _prewarm_connectors() -> None:
    """Pre-warm database connector pools for all configured connections."""
    import asyncio

    from sqlalchemy import select

    from app.connectors.connector_registry import get_or_create_connector
    from app.db.models.connection import DatabaseConnection
    from app.services.connection_service import get_decrypted_connection_string

    async with async_session_factory() as db:
        result = await db.execute(select(DatabaseConnection))
        connections = result.scalars().all()

    if not connections:
        logger.info("No connections to pre-warm")
        return

    semaphore = asyncio.Semaphore(5)  # Limit concurrent pre-warm to 5

    async def _warm_one(conn: DatabaseConnection) -> None:
        async with semaphore:
            try:
                connection_string = get_decrypted_connection_string(conn)
                await get_or_create_connector(str(conn.id), conn.connector_type, connection_string)
                logger.debug("Pre-warmed connector for connection %s", conn.id)
            except Exception:
                logger.warning("Failed to pre-warm connector for %s", conn.id, exc_info=True)

    await asyncio.gather(*[_warm_one(c) for c in connections])
    logger.info("Pre-warmed %d connection pool(s)", len(connections))


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    # SlowAPI rate-limiting middleware
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middleware is processed in reverse registration order on inbound requests.
    # Order (inbound): CORS → MetricsAuth → CSRF → Timeout → SecurityHeaders →
    # RequestID → BodySize → app
    app.add_middleware(RequestBodySizeMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestTimeoutMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(MetricsAuthMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-CSRF-Token"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)

    # Prometheus metrics — admin-only authenticated in non-dev; open in dev
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    return app


app = create_app()
