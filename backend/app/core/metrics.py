"""Prometheus metrics for the query pipeline."""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import Any

from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

NODE_DURATION = Histogram(
    "query_pipeline_node_duration_seconds",
    "Time spent in each LangGraph node",
    ["node"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

LLM_CALLS = Counter(
    "query_pipeline_llm_calls_total",
    "Number of LLM calls made by the pipeline",
    ["node", "provider", "model"],
)

CACHE_HITS = Counter(
    "query_pipeline_cache_hits_total",
    "Number of cache hits in the pipeline",
    ["type"],
)

COALESCE_HITS = Counter(
    "query_pipeline_coalesce_hits_total",
    "Number of requests that were coalesced with a leader",
    [],
)

PIPELINE_DURATION = Histogram(
    "query_pipeline_total_duration_seconds",
    "End-to-end query pipeline duration",
    ["outcome"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 20.0, 30.0, 45.0, 60.0],
)

LLM_CALL_DURATION = Histogram(
    "query_pipeline_llm_call_duration_seconds",
    "Time spent in individual LLM calls by provider and model",
    ["node", "provider", "model"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)


def timed_node(node_name: str) -> Callable[[Callable], Callable]:
    """Decorator to time a LangGraph node and record to prometheus."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                return await func(*args, **kwargs)
            finally:
                NODE_DURATION.labels(node=node_name).observe(time.monotonic() - start)

        return wrapper

    return decorator


def record_llm_call(node: str, provider: str, model: str, duration: float) -> None:
    """Record an LLM call to Prometheus metrics.

    Args:
        node: Graph node name (e.g. 'compose_sql', 'resolve_turn').
        provider: LLM provider identifier (e.g. 'openrouter', 'anthropic').
        model: Model name (e.g. 'deepseek/deepseek-v3.2', 'openai/gpt-4.1-nano').
        duration: Call duration in seconds.
    """
    LLM_CALLS.labels(node=node, provider=provider, model=model).inc()
    LLM_CALL_DURATION.labels(node=node, provider=provider, model=model).observe(duration)
