"""Shared async Redis client singleton with connection pooling."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


async def get_redis() -> Redis:
    """Return the shared async Redis client, creating it on first call."""
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
            max_connections=50,
        )
        logger.info("Redis client connected to %s", settings.redis_url)
    return _redis_client


async def close_redis() -> None:
    """Gracefully close the Redis connection pool."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis client disconnected")


async def redis_health() -> bool:
    """Ping Redis to verify connectivity."""
    try:
        client = await get_redis()
        await client.ping()
        return True
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False
