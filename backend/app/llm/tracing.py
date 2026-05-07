"""LangSmith tracing utilities for QueryWise.

This module provides LangSmith integration for observability:
- Automatic tracing of LLM calls with rich metadata
- Trace context propagation through the query pipeline
- Configurable via LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGSMITH_TRACING_ENABLED
"""

import contextlib
import logging
from collections.abc import Iterator
from functools import wraps
from typing import Any, TypeVar

from app.config import settings

T = TypeVar("T")

logger = logging.getLogger(__name__)

_langsmith_configured: bool = False
_langsmith_client: Any | None = None


def _ensure_langsmith_configured() -> bool:
    """Ensure LangSmith is configured and return whether it's ready."""
    global _langsmith_client, _langsmith_configured
    if _langsmith_configured:
        return True

    if not settings.langsmith_tracing_enabled or not settings.langsmith_api_key:
        return False

    try:
        from langsmith.client import Client  # type: ignore[import-not-found]

        _langsmith_client = Client(
            api_key=settings.langsmith_api_key,
            auto_batch_tracing=False,
        )
        _langsmith_configured = True
        return True
    except Exception as exc:
        logger.warning("LangSmith client configuration failed: %s", exc, exc_info=True)
        return False


def configure_langsmith() -> bool:
    """Configure LangSmith tracing and log a clear startup status."""
    configured = _ensure_langsmith_configured()
    if configured:
        logger.info("LangSmith tracing configured for project: %s", settings.langsmith_project)
    else:
        logger.info("LangSmith tracing disabled or unavailable")
    return configured


@contextlib.contextmanager
def trace_span(
    name: str,
    *,
    run_type: str = "chain",
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Create a LangSmith span, or a no-op span when tracing is disabled."""
    if not _ensure_langsmith_configured():
        yield None
        return

    from langsmith import trace  # type: ignore[import-not-found]
    from langsmith.run_helpers import tracing_context  # type: ignore[import-not-found]

    with tracing_context(
        enabled=True,
        project_name=settings.langsmith_project,
        client=_langsmith_client,
    ):
        with trace(
            name,
            run_type=run_type,
            inputs=_serialize_for_trace(inputs or {}),
            metadata=metadata or {},
            project_name=settings.langsmith_project,
            client=_langsmith_client,
        ) as run:
            yield run


def traceable(
    name: str | None = None,
    run_name: str | None = None,
) -> Any:
    """Decorator to add LangSmith tracing to async functions.

    Args:
        name: Trace name (defaults to function's qualified name)
        run_name: Custom run name for the trace

    Returns:
        Decorated function with LangSmith tracing

    Example:
        @traceable("compose_sql")
        async def compose_sql(...):
            ...
    """

    def decorator(func: Any) -> Any:
        trace_name = name or f"{func.__module__}.{func.__qualname__}"
        run_name_final = run_name or func.__name__

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            with trace_span(
                trace_name,
                run_type="chain",
                inputs=_safe_function_inputs(args, kwargs),
                metadata={"run_name": run_name_final},
            ) as run:
                try:
                    result = await func(*args, **kwargs)
                    if run is not None:
                        run.end(outputs={"result": _serialize_for_trace(result)})
                    return result
                except Exception as e:
                    if run is not None:
                        run.end(outputs={"error": str(e)})
                    raise

        return async_wrapper

    return decorator


def trace_llm_call(
    provider: str,
    model: str,
    operation: str,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Context manager for tracing LLM calls with detailed metadata.

    Args:
        provider: LLM provider (anthropic, openai, openrouter, groq, ollama)
        model: Model identifier
        operation: Operation type (complete, stream, embed)
        metadata: Additional metadata for the trace

    Returns:
        Context manager for the trace

    Example:
        with trace_llm_call("openrouter", "deepseek/deepseek-v3.2", "complete") as cb:
            response = await provider.complete(messages, config)
            cb.end(outputs={"response": response.content})
    """
    trace_name = f"{provider}.{operation}.{model}"
    meta = {
        "provider": provider,
        "model": model,
        "operation": operation,
        **(metadata or {}),
    }

    if not _ensure_langsmith_configured():
        return contextlib.nullcontext()

    run_type = "llm" if operation != "embed" else "retriever"
    return trace_span(trace_name, run_type=run_type, metadata=meta)


def serialize_messages_for_trace(messages: list[Any]) -> list[dict[str, str]]:
    """Serialize LLM messages for trace output (truncated for privacy)."""
    serialized = []
    for msg in messages:
        if hasattr(msg, "role") and hasattr(msg, "content"):
            content = msg.content
            if len(content) > 500:
                content = content[:500] + "... [truncated]"
            serialized.append({"role": msg.role, "content": content})
    return serialized


def _serialize_for_trace(obj: Any) -> Any:
    """Serialize objects for LangSmith trace output."""
    if obj is None or isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, str):
        return obj if len(obj) <= 1000 else f"{obj[:1000]}... [truncated]"
    if isinstance(obj, dict):
        serialized = {}
        for k, v in obj.items():
            key = str(k)
            secret_keys = ("key", "secret", "token", "password", "connection_string")
            if any(secret in key.lower() for secret in secret_keys):
                serialized[key] = "[redacted]"
            else:
                serialized[key] = _serialize_for_trace(v)
        return serialized
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_trace(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: _serialize_for_trace(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)


def _safe_function_inputs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return small, non-sensitive function input metadata for generic decorators."""
    return {
        "args_count": max(len(args) - 1, 0),  # skip self for bound methods
        "kwargs_keys": sorted(kwargs.keys()),
    }
