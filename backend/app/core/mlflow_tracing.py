"""MLflow tracing and observability for the QueryWise pipeline.

Initialises MLflow at startup and exposes helpers used across the pipeline:

  - ``setup_mlflow()``           — call once in lifespan; configures tracking URI,
                                    experiment, and enables LangGraph autolog.
  - ``@mlflow_span``             — async decorator that wraps a function as a named
                                    MLflow span; drop-in companion to ``@timed_node``.
  - ``trace_query_pipeline()``   — async context manager that opens a root trace for
                                    the full NL→SQL pipeline and attaches metadata.

All MLflow calls are wrapped with ``try/except`` so that a misconfigured or
unreachable MLflow server never crashes the main request path.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import helpers — mlflow is an optional dep (part of the [llm] extra)
# ---------------------------------------------------------------------------

_mlflow_available: bool | None = None  # None = not yet checked


def _mlflow() -> Any:
    """Return the mlflow module, or None if not installed."""
    global _mlflow_available
    if _mlflow_available is None:
        try:
            import mlflow  # noqa: PLC0415

            _mlflow_available = True
            return mlflow
        except ImportError:
            _mlflow_available = False
            logger.warning(
                "mlflow not installed — tracing disabled. "
                "Install with: pip install mlflow[langchain]"
            )
            return None
    if _mlflow_available:
        import mlflow  # noqa: PLC0415

        return mlflow
    return None


# ---------------------------------------------------------------------------
# One-time setup
# ---------------------------------------------------------------------------


def setup_mlflow(
    tracking_uri: str = "http://localhost:5001",
    experiment_name: str = "querywise",
) -> bool:
    """Configure MLflow tracking and enable LangGraph/LangChain autolog.

    Args:
        tracking_uri: MLflow tracking server URL (or a local ``mlruns/`` path).
        experiment_name: MLflow experiment to log traces under.

    Returns:
        ``True`` if setup succeeded, ``False`` if mlflow is unavailable.
    """
    mlflow = _mlflow()
    if mlflow is None:
        return False

    try:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment_name)

        # Autolog captures every LangGraph node as a child span automatically.
        # run_tracer_inline=True fixes async context propagation (required for ainvoke).
        mlflow.langchain.autolog(run_tracer_inline=True)

        logger.info(
            "MLflow tracing enabled — tracking_uri=%s experiment=%s",
            tracking_uri,
            experiment_name,
        )
        return True

    except Exception:
        logger.warning("MLflow setup failed — tracing disabled", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Root trace context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def trace_query_pipeline(
    question: str,
    connection_id: str,
    session_id: str | None = None,
    user_id: str | None = None,
) -> AsyncGenerator[Any, None]:
    """Open a root MLflow trace that wraps the full NL→SQL pipeline.

    All LangGraph autolog spans are nested under this root span, giving a
    single cohesive trace per user query in the MLflow UI.

    Usage::

        async with trace_query_pipeline(question, connection_id) as trace:
            result = await graph.ainvoke(state)

    Args:
        question: The user's natural language question.
        connection_id: UUID string of the database connection being queried.
        session_id: Chat session ID (used as MLflow thread_id for session grouping).
        user_id: Authenticated user ID for filtering in the MLflow UI.
    """
    mlflow = _mlflow()
    if mlflow is None:
        yield None
        return

    tags: dict[str, str] = {"connection_id": connection_id}
    if session_id:
        tags["mlflow.trace.session_id"] = session_id  # enables Session tab in UI
    if user_id:
        tags["user_id"] = user_id

    try:
        with mlflow.start_span(
            name="query_pipeline",
            span_type="CHAIN",
            inputs={"question": question},
        ) as span:
            span.set_attributes(tags)
            try:
                yield span
            except Exception as exc:
                span.set_status("ERROR")
                span.set_attributes({"error": str(exc)})
                raise
    except Exception:
        # Never let MLflow crash the pipeline
        logger.debug("MLflow trace_query_pipeline context failed", exc_info=True)
        yield None


# ---------------------------------------------------------------------------
# Span decorator
# ---------------------------------------------------------------------------


def mlflow_span(
    name: str | None = None,
    span_type: str = "UNKNOWN",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable[[Callable], Callable]:
    """Async decorator that wraps a function as a named MLflow span.

    Mirrors ``@timed_node`` but adds MLflow tracing on top.  Can be stacked::

        @timed_node("embedding")
        @mlflow_span("embed_text", span_type="EMBEDDING")
        async def embed_text(text: str) -> list[float]: ...

    Args:
        name: Span name shown in the MLflow UI. Defaults to the function name.
        span_type: MLflow span type (CHAT_MODEL, CHAIN, TOOL, EMBEDDING, RETRIEVER, …).
        capture_input: Record positional / keyword args as span inputs.
        capture_output: Record the return value as span output.
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            mlflow = _mlflow()
            if mlflow is None:
                return await func(*args, **kwargs)

            inputs: dict[str, Any] = {}
            if capture_input and kwargs:
                inputs = {k: str(v)[:500] for k, v in kwargs.items()}

            try:
                with mlflow.start_span(
                    name=span_name,
                    span_type=span_type,
                    inputs=inputs if inputs else None,
                ) as span:
                    try:
                        result = await func(*args, **kwargs)
                        if capture_output and result is not None:
                            # Truncate large outputs (e.g. SQL context strings)
                            out = result
                            if isinstance(out, str) and len(out) > 1000:
                                out = out[:1000] + "…"
                            span.set_outputs({"result": out})
                        return result
                    except Exception as exc:
                        span.set_status("ERROR")
                        span.set_attributes({"error": str(exc)})
                        raise
            except Exception:
                # If MLflow span creation itself failed, run the function untraced
                logger.debug("MLflow span '%s' failed — running untraced", span_name, exc_info=True)
                return await func(*args, **kwargs)

        return wrapper

    return decorator
