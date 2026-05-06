"""Query Caching — hash-based cache for query results.

This module implements query caching with:
- Cache key = hash(intent + filters + sort)
- LRU eviction when max size exceeded
- TTL support (default 1 hour)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Default cache TTL in seconds (1 hour)
DEFAULT_TTL_SECONDS = 3600

#: Default max cache size
DEFAULT_MAX_SIZE = 1000


@dataclass
class CacheEntry:
    """A single cache entry with result and metadata."""

    result: dict[str, Any]
    timestamp: float
    hits: int = 0


class QueryCache:
    """In-memory query cache with LRU eviction."""

    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_size: int = DEFAULT_MAX_SIZE,
    ):
        self._cache: dict[str, CacheEntry] = {}
        self._access_order: list[str] = []  # For LRU tracking
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
        }

    def _make_key(self, intent: str, filters: list[dict], sort: list[dict]) -> str:
        """Generate cache key from intent, filters, and sort."""
        # Sort filters and sort for consistent hashing
        key_data = {
            "intent": intent,
            "filters": sorted(filters, key=lambda x: json.dumps(x, sort_keys=True)),
            "sort": sorted(sort, key=lambda x: json.dumps(x, sort_keys=True)),
        }
        key_string = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()

    def get(self, intent: str, filters: list[dict], sort: list[dict]) -> dict[str, Any] | None:
        """Get cached result if available and not expired."""
        key = self._make_key(intent, filters, sort)

        if key not in self._cache:
            self._stats["misses"] += 1
            logger.debug("Cache miss for key: %s", key[:16])
            return None

        entry = self._cache[key]

        # Check TTL
        age = time.time() - entry.timestamp
        if age > self._ttl_seconds:
            logger.debug("Cache expired for key: %s (age: %.1fs)", key[:16], age)
            del self._cache[key]
            self._access_order.remove(key)
            self._stats["misses"] += 1
            return None

        # Update access order for LRU
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        # Update hit stats
        entry.hits += 1
        self._stats["hits"] += 1

        logger.debug("Cache hit for key: %s (hits: %d)", key[:16], entry.hits)
        return entry.result

    def set(
        self, intent: str, filters: list[dict], sort: list[dict], result: dict[str, Any]
    ) -> None:
        """Store result in cache with LRU eviction."""
        key = self._make_key(intent, filters, sort)

        # Evict if at max size
        if len(self._cache) >= self._max_size and key not in self._cache:
            self._evict_lru()

        # Store entry
        self._cache[key] = CacheEntry(
            result=result,
            timestamp=time.time(),
            hits=0,
        )

        # Update access order
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        logger.debug("Cached result for key: %s", key[:16])

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._access_order:
            return

        lru_key = self._access_order.pop(0)
        del self._cache[lru_key]
        self._stats["evictions"] += 1
        logger.debug("Evicted LRU entry: %s", lru_key[:16])

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        self._access_order.clear()
        logger.info("Cache cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total_requests if total_requests > 0 else 0

        return {
            **self._stats,
            "size": len(self._cache),
            "hit_rate": hit_rate,
        }


#: Global cache instance
_query_cache = QueryCache()


def get_cached_result(
    intent: str,
    filters: list[dict],
    sort: list[dict],
) -> dict[str, Any] | None:
    """Get cached query result.

    Args:
        intent: Query intent
        filters: List of filter dicts
        sort: List of sort dicts

    Returns:
        Cached result dict or None if not found/expired
    """
    return _query_cache.get(intent, filters, sort)


def cache_result(
    intent: str,
    filters: list[dict],
    sort: list[dict],
    result: dict[str, Any],
) -> None:
    """Cache a query result.

    Args:
        intent: Query intent
        filters: List of filter dicts
        sort: List of sort dicts
        result: Result dict to cache
    """
    _query_cache.set(intent, filters, sort, result)


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics."""
    return _query_cache.get_stats()


def clear_cache() -> None:
    """Clear the query cache."""
    _query_cache.clear()


# Aliases for backwards compatibility
CacheKey = dict  # Simple dict-based key
