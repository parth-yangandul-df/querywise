import asyncio
import json
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.schemas.query import ExecuteSQLRequest, QueryRequest, SQLOnlyResponse
from app.core.exceptions import AppError
from app.db.models.user import User
from app.db.session import get_db
from app.services import query_service

router = APIRouter(prefix="/query", tags=["query"])
logger = logging.getLogger(__name__)

_STREAM_STAGES = [
    {"stage": "understanding", "label": "Understanding your question...", "progress": 20},
    {"stage": "generating_sql", "label": "Generating SQL...", "progress": 50},
    {"stage": "running_query", "label": "Running query...", "progress": 75},
    {"stage": "interpreting", "label": "Interpreting results...", "progress": 95},
]
# Fallback timeline used only when no real stage events are emitted (e.g. errors before first node)
_STREAM_STAGE_TIMELINE_S = (0.0, 1.5, 3.0, 4.5)
_STREAM_POLL_INTERVAL_S = 0.05


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _encode_stream_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=_json_default)}\n\n"


@router.post("")
async def execute_query(
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit a natural language question and get SQL + results + interpretation."""
    result = await query_service.execute_nl_query(
        db,
        body.connection_id,
        body.question,
        session_id=body.session_id,
        current_user=current_user,
        clear_context=body.clear_context,
    )
    return result


@router.post("/stream")
async def stream_query(
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream real pipeline progress events followed by the final result.

    Each SSE event is one of:
      {"type": "stage", "stage": "...", "label": "...", "progress": N}
      {"type": "token", "content": "..."}   — streaming interpreter tokens
      {"type": "result", "data": {...}}      — final result object
      {"type": "error", "message": "..."}   — error
    """

    async def event_generator():
        event_queue: asyncio.Queue = asyncio.Queue()

        query_task = asyncio.create_task(
            query_service.execute_nl_query(
                db,
                body.connection_id,
                body.question,
                session_id=body.session_id,
                current_user=current_user,
                clear_context=body.clear_context,
                event_queue=event_queue,
            )
        )

        try:
            while not query_task.done():
                try:
                    event = event_queue.get_nowait()
                    yield _encode_stream_event(event)
                except asyncio.QueueEmpty:
                    await asyncio.sleep(_STREAM_POLL_INTERVAL_S)

            # Drain any remaining events pushed before task completed
            while not event_queue.empty():
                event = event_queue.get_nowait()
                yield _encode_stream_event(event)

            result = query_task.result()
            yield _encode_stream_event({"type": "result", "data": result})

        except asyncio.CancelledError:
            query_task.cancel()
            raise
        except AppError as exc:
            logger.warning("Query error: %s (code=%s)", exc.message, exc.status_code)
            yield _encode_stream_event(exc.to_stream_event())
        except Exception:
            logger.error("Query stream error: %s", exc_info=True)
            yield _encode_stream_event(
                {"type": "error", "message": "Something went wrong. Please try again.", "code": 500}
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/execute-sql")
async def execute_sql(
    body: ExecuteSQLRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute user-provided SQL directly (no LLM generation)."""
    result = await query_service.execute_raw_sql(
        db, body.connection_id, body.sql, body.original_question
    )
    return result


@router.post("/sql-only", response_model=SQLOnlyResponse)
async def generate_sql_only(
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate SQL without executing it."""
    result = await query_service.generate_sql_only(db, body.connection_id, body.question)
    return SQLOnlyResponse(**result)
