"""Tracing utilities — MLflow-backed spans for LLM agents.

Replaces the old LangSmith no-op stubs with real MLflow spans.
All functions remain backward-compatible so existing import sites
don't need changes.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Iterator
from typing import Any


def is_traced_run() -> bool:
    """Returns True when MLflow tracing is active."""
    try:
        import mlflow  # noqa: PLC0415

        return mlflow.get_current_active_span() is not None
    except Exception:
        return False


def configure_langsmith() -> bool:
    """No-op — LangSmith has been removed."""
    return False


@contextlib.contextmanager
def trace_span(
    name: str,
    *,
    run_type: str = "chain",
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    force: bool = False,
) -> Iterator[None]:
    """No-op span context manager (synchronous callers)."""
    yield None


@contextlib.contextmanager
def trace_graph_run(
    name: str,
    *,
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[None]:
    """No-op graph run context manager."""
    yield None


def traceable(
    name: str | None = None,
    run_name: str | None = None,
    span_type: str = "CHAIN",
) -> Any:
    """Decorator that wraps an async method as a named MLflow span.

    Drop-in replacement for the old LangSmith ``@traceable`` no-op.
    Falls back to calling the function untraced when MLflow is unavailable.
    """

    def decorator(func: Any) -> Any:
        span_name = name or run_name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                import mlflow  # noqa: PLC0415

                with mlflow.start_span(name=span_name, span_type=span_type):
                    return await func(*args, **kwargs)
            except Exception:
                return await func(*args, **kwargs)

        return wrapper

    return decorator


def trace_llm_call(
    provider: str,
    model: str,
    operation: str,
    metadata: dict[str, Any] | None = None,
    force: bool = False,
) -> Any:
    """No-op context manager for LLM call tracing."""
    return contextlib.nullcontext()
