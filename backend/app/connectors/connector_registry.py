import time

from loguru import logger

from app.connectors.base_connector import BaseConnector, ConnectorType
from app.connectors.postgresql.connector import PostgreSQLConnector
from app.core.exceptions import ValidationError as AppValidationError

# Registry of connector classes by type
_CONNECTOR_CLASSES: dict[ConnectorType, type[BaseConnector]] = {
    ConnectorType.POSTGRESQL: PostgreSQLConnector,
}

# Lazy-register SQL Server only when aioodbc is installed
try:
    from app.connectors.sqlserver.connector import SQLServerConnector

    _CONNECTOR_CLASSES[ConnectorType.SQLSERVER] = SQLServerConnector
except ImportError:
    pass

# Cache of active connector instances by connection ID
_active_connectors: dict[str, BaseConnector] = {}

# LRU tracking: last-accessed timestamp per connection ID
_last_accessed: dict[str, float] = {}

# Call counter for periodic cleanup triggering
_call_count: int = 0

MAX_CACHED_CONNECTORS = 50


def get_connector_class(connector_type: str) -> type[BaseConnector]:
    """Get the connector class for a given type string."""
    try:
        ct = ConnectorType(connector_type)
    except ValueError as exc:
        raise AppValidationError(
            f"Unknown connector type: '{connector_type}'. "
            f"Available: {[t.value for t in ConnectorType]}"
        ) from exc
    cls = _CONNECTOR_CLASSES.get(ct)
    if cls is None:
        raise AppValidationError(
            f"Connector type '{connector_type}' is installed but not available "
            f"(missing optional dependency)."
        )
    return cls


def register_connector(connector_type: ConnectorType, cls: type[BaseConnector]) -> None:
    """Register a new connector class (plugin system)."""
    _CONNECTOR_CLASSES[connector_type] = cls


async def _evict_lru() -> None:
    """Remove the least-recently-used connector when cache is at capacity."""
    if not _last_accessed:
        return
    lru_id = min(_last_accessed, key=lambda k: _last_accessed[k])
    connector = _active_connectors.pop(lru_id, None)
    _last_accessed.pop(lru_id, None)
    if connector is not None:
        try:
            await connector.disconnect()
        except Exception:
            logger.exception("Failed to disconnect evicted connector %s", lru_id)


async def cleanup_stale_connectors(max_age_seconds: int = 3600) -> None:
    """Remove connectors not accessed within max_age_seconds."""
    cutoff = time.monotonic() - max_age_seconds
    stale_ids = [cid for cid, ts in _last_accessed.items() if ts < cutoff]
    for cid in stale_ids:
        connector = _active_connectors.pop(cid, None)
        _last_accessed.pop(cid, None)
        if connector is not None:
            try:
                await connector.disconnect()
            except Exception:
                logger.exception("Failed to disconnect stale connector %s", cid)


async def get_or_create_connector(
    connection_id: str,
    connector_type: str,
    connection_string: str,
) -> BaseConnector:
    """Get a cached connector or create a new one."""
    global _call_count
    _call_count += 1

    # Periodic stale cleanup every 100 calls
    if _call_count % 100 == 0:
        await cleanup_stale_connectors()

    if connection_id in _active_connectors:
        connector = _active_connectors[connection_id]
        if await connector.test_connection():
            _last_accessed[connection_id] = time.monotonic()
            return connector
        # Connection is stale, remove it
        await connector.disconnect()
        del _active_connectors[connection_id]
        _last_accessed.pop(connection_id, None)

    # Evict LRU entry if cache is at capacity
    if len(_active_connectors) >= MAX_CACHED_CONNECTORS:
        await _evict_lru()

    cls = get_connector_class(connector_type)
    connector = cls()
    await connector.connect(connection_string)
    _active_connectors[connection_id] = connector
    _last_accessed[connection_id] = time.monotonic()
    return connector


async def remove_connector(connection_id: str) -> None:
    """Disconnect and remove a cached connector."""
    if connection_id in _active_connectors:
        await _active_connectors[connection_id].disconnect()
        del _active_connectors[connection_id]
        _last_accessed.pop(connection_id, None)
