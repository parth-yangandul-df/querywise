import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, require_role
from app.api.v1.schemas.connection import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionTestResult,
    ConnectionUpdate,
)
from app.db.models.user import User  # noqa: F401
from app.db.session import get_db
from app.services import connection_service

router = APIRouter(prefix="/connections", tags=["connections"])


def _to_response(c: object) -> ConnectionResponse:
    """Convert a DatabaseConnection ORM object to a ConnectionResponse."""
    return ConnectionResponse(
        id=c.id,  # type: ignore[attr-defined]
        name=c.name,  # type: ignore[attr-defined]
        connector_type=c.connector_type,  # type: ignore[attr-defined]
        default_schema=c.default_schema,  # type: ignore[attr-defined]
        max_query_timeout_seconds=c.max_query_timeout_seconds,  # type: ignore[attr-defined]
        max_rows=c.max_rows,  # type: ignore[attr-defined]
        is_active=c.is_active,  # type: ignore[attr-defined]
        has_connection_string=bool(c.connection_string_encrypted),  # type: ignore[attr-defined]
        last_introspected_at=c.last_introspected_at,  # type: ignore[attr-defined]
        created_at=c.created_at,  # type: ignore[attr-defined]
        updated_at=c.updated_at,  # type: ignore[attr-defined]
        allowed_table_names=c.allowed_table_names,  # type: ignore[attr-defined]
    )


@router.get("", response_model=list[ConnectionResponse])
async def list_connections(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    connections = await connection_service.list_connections(db)
    return [_to_response(c) for c in connections]


@router.post("", response_model=ConnectionResponse, status_code=201)
async def create_connection(
    body: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    conn = await connection_service.create_connection(
        db,
        name=body.name,
        connector_type=body.connector_type,
        connection_string=body.connection_string,
        default_schema=body.default_schema,
        max_query_timeout_seconds=body.max_query_timeout_seconds,
        max_rows=body.max_rows,
        allowed_table_names=body.allowed_table_names,
    )
    await db.refresh(conn)
    return _to_response(conn)


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    conn = await connection_service.get_connection(db, connection_id)
    return _to_response(conn)


@router.put("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    conn = await connection_service.update_connection(
        db, connection_id, **body.model_dump(exclude_none=True)
    )
    await db.refresh(conn)
    return _to_response(conn)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    await connection_service.delete_connection(db, connection_id)


@router.post("/{connection_id}/test", response_model=ConnectionTestResult)
async def test_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    success, message = await connection_service.test_connection(db, connection_id)
    return ConnectionTestResult(success=success, message=message)
