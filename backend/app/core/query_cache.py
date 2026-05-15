"""Redis-backed SQL result cache and request coalescing for the query pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Any

from app.config import settings
from app.core.metrics import CACHE_HITS, COALESCE_HITS
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_SQL_CACHE_PREFIX = "qw:sql_cache"
_COALESCE_PREFIX = "qw:coalesce"
_COALESCE_RESULT_PREFIX = "qw:coalesce_result"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _build_cache_key(
    connection_id: str,
    question: str,
    user_role: str | None = None,
    resource_id: int | None = None,
    employee_id: str | None = None,
) -> str:
    q_hash = _hash_text(question)
    role = user_role or "none"
    rid = str(resource_id) if resource_id is not None else "none"
    eid = employee_id or "none"
    return f"{_SQL_CACHE_PREFIX}:{connection_id}:{q_hash}:{role}:{rid}:{eid}"


def _build_coalesce_key(
    connection_id: str,
    question: str,
    user_role: str | None = None,
    resource_id: int | None = None,
    employee_id: str | None = None,
) -> str:
    q_hash = _hash_text(question)
    role = user_role or "none"
    rid = str(resource_id) if resource_id is not None else "none"
    eid = employee_id or "none"
    return f"{_COALESCE_PREFIX}:{connection_id}:{q_hash}:{role}:{rid}:{eid}"


async def get_cached_sql(
    connection_id: str,
    question: str,
    user_role: str | None = None,
    resource_id: int | None = None,
    employee_id: str | None = None,
) -> dict[str, Any] | None:
    """Return cached SQL metadata if present in Redis, else None."""
    try:
        redis = await get_redis()
        key = _build_cache_key(connection_id, question, user_role, resource_id, employee_id)
        raw = await redis.get(key)
        if raw:
            logger.debug("SQL cache hit for key=%s", key)
            CACHE_HITS.labels(type="sql").inc()
            return json.loads(raw)
    except Exception:
        logger.warning("SQL cache read failed — falling through to pipeline", exc_info=True)
    return None


async def delete_cached_sql(
    connection_id: str,
    question: str,
    user_role: str | None = None,
    resource_id: int | None = None,
    employee_id: str | None = None,
) -> None:
    """Evict a specific question from the SQL cache (e.g. after prompt or glossary changes)."""
    try:
        redis = await get_redis()
        key = _build_cache_key(connection_id, question, user_role, resource_id, employee_id)
        await redis.delete(key)
        logger.debug("SQL cache evicted key=%s", key)
    except Exception:
        logger.warning("SQL cache eviction failed — non-critical", exc_info=True)


async def set_cached_sql(
    connection_id: str,
    question: str,
    sql: str,
    explanation: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    user_role: str | None = None,
    resource_id: int | None = None,
    employee_id: str | None = None,
) -> None:
    """Store successful SQL generation result in Redis with TTL."""
    try:
        redis = await get_redis()
        key = _build_cache_key(connection_id, question, user_role, resource_id, employee_id)
        value = json.dumps(
            {
                "sql": sql,
                "explanation": explanation,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
            }
        )
        await redis.setex(key, settings.cache_ttl_seconds, value)
        logger.debug("SQL cache stored for key=%s ttl=%ds", key, settings.cache_ttl_seconds)
    except Exception:
        logger.warning("SQL cache write failed — non-critical", exc_info=True)


async def try_coalesce_leader(
    connection_id: str,
    question: str,
    user_role: str | None = None,
    resource_id: int | None = None,
    employee_id: str | None = None,
) -> tuple[bool, str]:
    """Attempt to become the leader for this query. Returns (is_leader, coalesce_key)."""
    try:
        redis = await get_redis()
        coalesce_key = _build_coalesce_key(connection_id, question, user_role, resource_id, employee_id)
        result_key = f"{_COALESCE_RESULT_PREFIX}:{coalesce_key}"

        # NX = set only if not exists; TTL prevents stuck locks
        acquired = await redis.set(
            coalesce_key,
            "1",
            nx=True,
            ex=settings.request_coalesce_timeout_seconds,
        )
        if acquired:
            logger.debug("Coalesce leader acquired: %s", coalesce_key)
            return True, result_key

        logger.debug("Coalesce follower waiting: %s", coalesce_key)
        return False, result_key
    except Exception:
        logger.warning("Coalesce check failed — falling through to normal pipeline", exc_info=True)
        return True, ""  # treat as leader on Redis failure


async def publish_coalesce_result(result_key: str, result: dict[str, Any]) -> None:
    """Publish the result so followers can read it."""
    try:
        redis = await get_redis()
        await redis.setex(
            result_key,
            settings.request_coalesce_timeout_seconds,
            json.dumps(result, default=_json_default),
        )
        logger.debug("Coalesce result published: %s", result_key)
    except Exception:
        logger.warning("Coalesce publish failed — non-critical", exc_info=True)


async def wait_for_coalesce_result(
    result_key: str,
    poll_interval: float = 1.0,
    max_wait: float | None = None,
) -> dict[str, Any] | None:
    """Poll Redis for the leader's result. Returns None if timed out."""
    if max_wait is None:
        max_wait = settings.request_coalesce_timeout_seconds
    try:
        redis = await get_redis()
        waited = 0.0
        while waited < max_wait:
            raw = await redis.get(result_key)
            if raw:
                logger.debug("Coalesce result received: %s", result_key)
                COALESCE_HITS.inc()
                return json.loads(raw)
            await asyncio.sleep(poll_interval)
            waited += poll_interval

        logger.warning("Coalesce wait timed out after %.1fs: %s", waited, result_key)
    except Exception:
        logger.warning("Coalesce wait failed — falling through", exc_info=True)
    return None


def _json_default(value: object) -> str:
    import decimal
    from datetime import date, datetime

    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)  # type: ignore[return-value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()  # type: ignore[return-value]
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
