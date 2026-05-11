import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.schemas.query import QueryHistoryResponse
from app.core.exceptions import NotFoundError
from app.db.models.query_history import QueryExecution
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/query-history", tags=["query_history"])


@router.get("", response_model=list[QueryHistoryResponse])
async def list_query_history(
    connection_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(QueryExecution).order_by(QueryExecution.created_at.desc())
    if connection_id:
        stmt = stmt.where(QueryExecution.connection_id == connection_id)
    # Scope to own executions only (all roles — RBAC refinements deferred)
    stmt = stmt.where(QueryExecution.user_id == current_user.id)
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{execution_id}", response_model=QueryHistoryResponse)
async def get_query_execution(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    execution = await db.get(QueryExecution, execution_id)
    if not execution or execution.user_id != current_user.id:
        raise NotFoundError("QueryExecution", str(execution_id))
    return execution


@router.patch("/{execution_id}/favorite")
async def toggle_favorite(
    execution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    execution = await db.get(QueryExecution, execution_id)
    if not execution or execution.user_id != current_user.id:
        raise NotFoundError("QueryExecution", str(execution_id))
    execution.is_favorite = not execution.is_favorite
    await db.flush()
    return {"is_favorite": execution.is_favorite}
