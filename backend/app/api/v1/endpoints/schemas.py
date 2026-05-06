import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, require_role
from app.api.v1.schemas.schema import (
    AvailableTableEntry,
    ColumnResponse,
    IntrospectionResult,
    RelationshipCreate,
    RelationshipResponse,
    TableDetailResponse,
    TableResponse,
)
from app.connectors.base_connector import ConnectorType
from app.core.exceptions import ValidationError as AppValidationError
from app.db.models.schema_cache import CachedRelationship, CachedTable
from app.db.models.user import User
from app.db.session import get_db
from app.services import schema_service
from app.services.connection_service import get_connection
from app.services.setup_service import launch_background_embeddings

router = APIRouter(tags=["schemas"])


@router.post(
    "/connections/{connection_id}/introspect",
    response_model=IntrospectionResult,
)
async def introspect_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    result = await schema_service.introspect_and_cache(db, connection_id)
    launch_background_embeddings(connection_id)
    return IntrospectionResult(**result)


@router.get(
    "/connections/{connection_id}/available-tables",
    response_model=list[AvailableTableEntry],
    summary="List available dbo tables for SQL Server connections",
    description=(
        "Returns all tables in the dbo schema (after auto-exclusion of backup tables only) "
        "directly from the live database — does NOT update the schema cache. "
        "Only available for SQL Server connections. Used by the Table Manager UI."
    ),
)
async def list_available_tables(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    conn = await get_connection(db, connection_id)
    if conn.connector_type != ConnectorType.SQLSERVER:
        raise AppValidationError("available-tables is only supported for SQL Server connections.")
    tables = await schema_service.get_available_tables_for_sqlserver(db, connection_id)
    return [AvailableTableEntry(**t) for t in tables]


@router.get(
    "/connections/{connection_id}/tables",
    response_model=list[TableResponse],
)
async def list_tables(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    tables = await schema_service.get_tables(db, connection_id)
    return [
        TableResponse(
            id=t.id,
            schema_name=t.schema_name,
            table_name=t.table_name,
            table_type=t.table_type,
            comment=t.comment,
            row_count_estimate=t.row_count_estimate,
            column_count=len(t.columns),
            created_at=t.created_at,
        )
        for t in tables
    ]


@router.get(
    "/tables/{table_id}",
    response_model=TableDetailResponse,
)
async def get_table_detail(
    table_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    table = await schema_service.get_table_detail(db, table_id)

    columns = [
        ColumnResponse(
            id=c.id,
            column_name=c.column_name,
            data_type=c.data_type,
            is_nullable=c.is_nullable,
            is_primary_key=c.is_primary_key,
            default_value=c.default_value,
            comment=c.comment,
            ordinal_position=c.ordinal_position,
        )
        for c in sorted(table.columns, key=lambda c: c.ordinal_position)
    ]

    outgoing = [
        RelationshipResponse(
            constraint_name=r.constraint_name,
            source_table=table.table_name,
            source_column=r.source_column,
            target_table=r.target_table.table_name if r.target_table else "?",
            target_column=r.target_column,
        )
        for r in table.outgoing_relationships
    ]

    incoming = [
        RelationshipResponse(
            constraint_name=r.constraint_name,
            source_table=r.source_table.table_name if r.source_table else "?",
            source_column=r.source_column,
            target_table=table.table_name,
            target_column=r.target_column,
        )
        for r in table.incoming_relationships
    ]

    return TableDetailResponse(
        id=table.id,
        schema_name=table.schema_name,
        table_name=table.table_name,
        table_type=table.table_type,
        comment=table.comment,
        row_count_estimate=table.row_count_estimate,
        columns=columns,
        outgoing_relationships=outgoing,
        incoming_relationships=incoming,
    )


# ---------------------------------------------------------------------------
# Manual relationship endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/connections/{connection_id}/relationships",
    response_model=list[RelationshipResponse],
    summary="List manually declared relationships for a connection",
)
async def list_manual_relationships(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    """Return all is_manual=True relationships for the connection."""
    result = await db.execute(
        select(CachedRelationship)
        .where(
            CachedRelationship.connection_id == connection_id,
            CachedRelationship.is_manual.is_(True),
        )
        .order_by(CachedRelationship.created_at)
    )
    rels = result.scalars().all()

    out = []
    for r in rels:
        src = await db.get(CachedTable, r.source_table_id)
        tgt = await db.get(CachedTable, r.target_table_id)
        out.append(
            RelationshipResponse(
                id=r.id,
                constraint_name=r.constraint_name,
                source_table=src.table_name if src else "?",
                source_column=r.source_column,
                target_table=tgt.table_name if tgt else "?",
                target_column=r.target_column,
                is_manual=True,
                relationship_type=r.relationship_type,
            )
        )
    return out


@router.post(
    "/connections/{connection_id}/relationships",
    response_model=RelationshipResponse,
    status_code=201,
    summary="Declare a manual relationship between two cached tables",
)
async def create_manual_relationship(
    connection_id: uuid.UUID,
    payload: RelationshipCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Create a manually declared FK-like relationship.

    The relationship is stored with is_manual=True and will NOT be deleted
    when the schema is re-introspected.
    """
    # Resolve source table
    src_result = await db.execute(
        select(CachedTable).where(
            CachedTable.connection_id == connection_id,
            CachedTable.table_name == payload.source_table,
        )
    )
    src_table = src_result.scalar_one_or_none()
    if not src_table:
        raise HTTPException(
            status_code=404,
            detail=f"Source table '{payload.source_table}' not found in schema cache.",
        )

    # Resolve target table
    tgt_result = await db.execute(
        select(CachedTable).where(
            CachedTable.connection_id == connection_id,
            CachedTable.table_name == payload.target_table,
        )
    )
    tgt_table = tgt_result.scalar_one_or_none()
    if not tgt_table:
        raise HTTPException(
            status_code=404,
            detail=f"Target table '{payload.target_table}' not found in schema cache.",
        )

    rel = CachedRelationship(
        connection_id=connection_id,
        constraint_name=payload.constraint_name,
        is_manual=True,
        relationship_type=payload.relationship_type,
        source_table_id=src_table.id,
        source_column=payload.source_column,
        target_table_id=tgt_table.id,
        target_column=payload.target_column,
    )
    db.add(rel)
    await db.commit()
    await db.refresh(rel)

    return RelationshipResponse(
        id=rel.id,
        constraint_name=rel.constraint_name,
        source_table=src_table.table_name,
        source_column=rel.source_column,
        target_table=tgt_table.table_name,
        target_column=rel.target_column,
        is_manual=True,
        relationship_type=rel.relationship_type,
    )


@router.delete(
    "/connections/{connection_id}/relationships/{relationship_id}",
    status_code=204,
    summary="Delete a manually declared relationship",
)
async def delete_manual_relationship(
    connection_id: uuid.UUID,
    relationship_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    rel = await db.get(CachedRelationship, relationship_id)
    if not rel or rel.connection_id != connection_id:
        raise HTTPException(status_code=404, detail="Relationship not found.")
    await db.delete(rel)
    await db.commit()
