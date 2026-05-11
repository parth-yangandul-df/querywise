"""Redis-backed schema cache for connection-level metadata.

Caches the full schema (tables, columns, relationships, dictionary entries)
for a connection_id to avoid repeated DB round trips during context building.

Cache key: `schema:{connection_id}`
TTL: 5 minutes (300s)
Invalidation: triggered automatically after schema introspection.
Graceful degradation: cache failures are logged and ignored.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_SCHEMA_CACHE_PREFIX = "schema"
_SCHEMA_CACHE_TTL_SECONDS = 300


def _build_key(connection_id: str) -> str:
    return f"{_SCHEMA_CACHE_PREFIX}:{connection_id}"


async def get_cached_schema(connection_id: str | uuid.UUID) -> dict[str, Any] | None:
    """Fetch the full schema for a connection from Redis.

    Returns a dict with keys:
    - tables: list[dict] — serialized CachedTable objects with columns
    - relationships: list[dict] — serialized CachedRelationship objects
    - dictionary: list[dict] — serialized DictionaryEntry objects
    Returns None on cache miss or Redis failure.
    """
    try:
        redis = await get_redis()
        key = _build_key(str(connection_id))
        raw = await redis.get(key)
        if raw:
            logger.debug("Schema cache hit for connection=%s", connection_id)
            return json.loads(raw)
    except Exception:
        logger.debug("Schema cache read failed — non-critical", exc_info=True)
    return None


async def set_cached_schema(
    connection_id: str | uuid.UUID,
    schema: dict[str, Any],
) -> None:
    """Store the full schema for a connection in Redis."""
    try:
        redis = await get_redis()
        key = _build_key(str(connection_id))
        await redis.setex(
            key,
            _SCHEMA_CACHE_TTL_SECONDS,
            json.dumps(schema, default=_json_default),
        )
        logger.info(
            "Schema cache stored for connection=%s ttl=%ds tables=%d",
            connection_id,
            _SCHEMA_CACHE_TTL_SECONDS,
            len(schema.get("tables", [])),
        )
    except Exception:
        logger.warning("Schema cache write failed — non-critical", exc_info=True)


async def invalidate_schema_cache(connection_id: str | uuid.UUID) -> None:
    """Evict the schema cache for a connection (called after introspection)."""
    try:
        redis = await get_redis()
        key = _build_key(str(connection_id))
        await redis.delete(key)
        logger.info("Schema cache invalidated for connection=%s", connection_id)
    except Exception:
        logger.warning("Schema cache invalidation failed — non-critical", exc_info=True)


def _json_default(obj: Any) -> Any:
    """Serialize non-JSON types (UUID, datetime, Decimal)."""
    if isinstance(obj, uuid.UUID):
        return str(obj)
    from datetime import date, datetime
    from decimal import Decimal
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj) if obj % 1 else int(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
