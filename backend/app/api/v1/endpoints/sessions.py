import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.schemas.session import SessionCreate, SessionMessageResponse, SessionResponse
from app.core.exceptions import NotFoundError
from app.db.models.chat_session import ChatSession
from app.db.models.query_history import QueryExecution
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = ChatSession(
        connection_id=body.connection_id,
        title=body.title or "New Chat",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return SessionResponse(
        id=session.id,
        connection_id=session.connection_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=0,
    )


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    connection_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Subquery: count executions per session
    count_subq = (
        select(
            QueryExecution.session_id,
            func.count(QueryExecution.id).label("message_count"),
        )
        .where(QueryExecution.session_id.is_not(None))
        .group_by(QueryExecution.session_id)
        .subquery()
    )

    stmt = (
        select(ChatSession, func.coalesce(count_subq.c.message_count, 0).label("message_count"))
        .outerjoin(count_subq, ChatSession.id == count_subq.c.session_id)
        .order_by(ChatSession.updated_at.desc())
    )
    if connection_id:
        stmt = stmt.where(ChatSession.connection_id == connection_id)

    result = await db.execute(stmt)
    rows = result.all()

    return [
        SessionResponse(
            id=s.id,
            connection_id=s.connection_id,
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=count,
        )
        for s, count in rows
    ]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise NotFoundError("ChatSession", str(session_id))

    count_result = await db.execute(
        select(func.count(QueryExecution.id)).where(QueryExecution.session_id == session_id)
    )
    count = count_result.scalar() or 0

    return SessionResponse(
        id=session.id,
        connection_id=session.connection_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=count,
    )


@router.get("/{session_id}/messages", response_model=list[SessionMessageResponse])
async def list_session_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise NotFoundError("ChatSession", str(session_id))

    stmt = (
        select(QueryExecution)
        .where(QueryExecution.session_id == session_id)
        .order_by(QueryExecution.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.patch("/{session_id}/title")
async def update_session_title(
    session_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise NotFoundError("ChatSession", str(session_id))
    title = str(body.get("title", "")).strip()
    if title:
        session.title = title[:100]
        session.updated_at = datetime.now(UTC)
        await db.flush()
    return {"title": session.title}


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise NotFoundError("ChatSession", str(session_id))
    await db.delete(session)
    await db.flush()
