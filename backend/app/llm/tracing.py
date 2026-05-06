"""LangSmith tracing utilities for QueryWise.

This module provides LangSmith integration for observability:
- Automatic tracing of LLM calls with rich metadata
- Trace context propagation through the query pipeline
- Configurable via LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGSMITH_TRACING_ENABLED
"""

from functools import wraps
from typing import Any, TypeVar

from app.config import settings

T = TypeVar("T")

_langsmith_configured: bool = False


def _ensure_langsmith_configured() -> bool:
    """Ensure LangSmith is configured and return whether it's ready."""
    global _langsmith_configured
    if _langsmith_configured:
        return True

    if not settings.langsmith_tracing_enabled or not settings.langsmith_api_key:
        return False

    try:
        from langsmith.client import Client  # type: ignore[import-not-found]

        Client.configure(
            api_key=settings.langsmith_api_key,
            project=settings.langsmith_project,
        )
        _langsmith_configured = True
        return True
    except Exception:
        return False


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
        from langsmith import traceable as langsmith_traceable

        trace_name = name or f"{func.__module__}.{func.__qualname__}"
        run_name_final = run_name or func.__name__

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            if not _ensure_langsmith_configured():
                return await func(*args, **kwargs)

            with langsmith_traceable(run_name=run_name_final, name=trace_name) as cb:
                try:
                    result = await func(*args, **kwargs)
                    cb.end(
                        outputs={"result": _serialize_for_trace(result)},
                        metadata={"success": True},
                    )
                    return result
                except Exception as e:
                    cb.end(
                        outputs={"error": str(e)},
                        metadata={"success": False, "error_type": type(e).__name__},
                    )
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
    if not _ensure_langsmith_configured():
        import contextlib

        return contextlib.nullcontext()

    from langsmith import traceable as langsmith_traceable

    trace_name = f"{provider}.{operation}.{model}"
    meta = {
        "provider": provider,
        "model": model,
        "operation": operation,
        **(metadata or {}),
    }

    return langsmith_traceable(name=trace_name, metadata=meta)


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
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)