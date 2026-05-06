import base64
import hashlib
import uuid

from cryptography.fernet import Fernet
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.connector_registry import (
    get_connector_class,
    get_or_create_connector,
    remove_connector,
)
from app.core.exceptions import NotFoundError
from app.db.models.connection import DatabaseConnection

# Derive a stable Fernet key from the configured encryption key.
# Fernet requires a 32-byte url-safe base64-encoded key.
_key_bytes = hashlib.sha256(settings.encryption_key.encode()).digest()
_fernet = Fernet(base64.urlsafe_b64encode(_key_bytes))


def _encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    return _fernet.decrypt(value.encode()).decode()


async def list_connections(db: AsyncSession) -> list[DatabaseConnection]:
    result = await db.execute(
        select(DatabaseConnection).order_by(DatabaseConnection.created_at.desc())
    )
    return list(result.scalars().all())


async def get_connection(db: AsyncSession, connection_id: uuid.UUID) -> DatabaseConnection:
    conn = await db.get(DatabaseConnection, connection_id)
    if not conn:
        raise NotFoundError("Connection", str(connection_id))
    return conn


async def create_connection(
    db: AsyncSession,
    name: str,
    connector_type: str,
    connection_string: str,
    default_schema: str = "public",
    max_query_timeout_seconds: int = 30,
    max_rows: int = 1000,
    allowed_table_names: list[str] | None = None,
) -> DatabaseConnection:
    # Validate connector type exists
    get_connector_class(connector_type)

    conn = DatabaseConnection(
        name=name,
        connector_type=connector_type,
        connection_string_encrypted=_encrypt(connection_string),
        default_schema=default_schema,
        max_query_timeout_seconds=max_query_timeout_seconds,
        max_rows=max_rows,
        allowed_table_names=allowed_table_names or None,
    )
    db.add(conn)
    await db.flush()
    return conn


async def update_connection(
    db: AsyncSession,
    connection_id: uuid.UUID,
    **updates: object,
) -> DatabaseConnection:
    conn = await get_connection(db, connection_id)

    if "connection_string" in updates and updates["connection_string"] is not None:
        conn.connection_string_encrypted = _encrypt(str(updates.pop("connection_string")))

    # allowed_table_names is a list — handle separately so empty list [] is valid (clears whitelist)
    if "allowed_table_names" in updates:
        raw = updates.pop("allowed_table_names")
        # None means "don't change"; [] means "clear whitelist"; [..] means "set whitelist"
        if raw is not None:
            conn.allowed_table_names = list(raw) if raw else None  # type: ignore[arg-type]

    for key, value in updates.items():
        if value is not None and hasattr(conn, key):
            setattr(conn, key, value)

    await db.flush()
    # Invalidate cached connector since config may have changed
    await remove_connector(str(connection_id))
    return conn


async def delete_connection(db: AsyncSession, connection_id: uuid.UUID) -> None:
    conn = await get_connection(db, connection_id)
    await remove_connector(str(connection_id))
    await db.delete(conn)
    await db.flush()


async def test_connection(db: AsyncSession, connection_id: uuid.UUID) -> tuple[bool, str]:
    conn = await get_connection(db, connection_id)
    connection_string = _decrypt(conn.connection_string_encrypted)
    try:
        connector = await get_or_create_connector(
            str(connection_id), conn.connector_type, connection_string
        )
        success = await connector.test_connection()
        return (success, "Connection successful" if success else "Connection test failed")
    except Exception as e:
        logger.error("Connection test failed for {}: {}", connection_id, e)
        return (False, "Connection test failed. Check host, port, and credentials.")


def get_decrypted_connection_string(conn: DatabaseConnection) -> str:
    return _decrypt(conn.connection_string_encrypted)
