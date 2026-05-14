import asyncio
import json
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.schemas.query import ExecuteSQLRequest, QueryRequest, SQLOnlyResponse
from app.core.exceptions import AppError
from app.core.limiter import limiter
from app.db.models.user import User
from app.db.session import get_db
from app.llm.stream_stages import UNDERSTANDING, emit
from app.services import query_service

router = APIRouter(prefix="/query", tags=["query"])
logger = logging.getLogger(__name__)

_STREAM_STAGE_TIMELINE_S = (0.0, 1.5, 3.0, 4.5)


def _json_default(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _encode_stream_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=_json_default)}\n\n"


@router.post("")
@limiter.limit("30/minute")
async def execute_query(
    request: Request,
    body: QueryRequest,
    current_user: User = Depends(get_current_user),
):
    """Submit a natural language question and get SQL + results + interpretation."""
    result = await query_service.execute_nl_query(
        body.connection_id,
        body.question,
        session_id=body.session_id,
        current_user=current_user,
        clear_context=body.clear_context,
        skip_cache=body.skip_cache,
    )
    return result


@router.post("/stream")
@limiter.limit("30/minute")
async def stream_query(
    request: Request,
    body: QueryRequest,
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

        # Emit UNDERSTANDING immediately so the UI shows a stage label
        # before the graph has even started running (eliminates blank delay).
        yield _encode_stream_event(emit(UNDERSTANDING))

        query_task = asyncio.create_task(
            query_service.execute_nl_query(
                body.connection_id,
                body.question,
                session_id=body.session_id,
                current_user=current_user,
                clear_context=body.clear_context,
                event_queue=event_queue,
                skip_cache=body.skip_cache,
            )
        )

        try:
            while not query_task.done() or not event_queue.empty():
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                    yield _encode_stream_event(event)
                except TimeoutError:
                    continue

            result = await query_task
            yield _encode_stream_event({"type": "result", "data": result})

        except asyncio.CancelledError:
            query_task.cancel()
            logger.debug("Query stream cancelled by client")
            return
        except AppError as exc:
            logger.warning(
                "Query error: %s (code=%s, category=%s)",
                exc.message,
                exc.status_code,
                exc.category,
            )
            yield _encode_stream_event(exc.to_stream_event())
        except Exception:
            logger.error("Query stream error", exc_info=True)
            yield _encode_stream_event(
                {
                    "type": "error",
                    "error": "Something went wrong. Please try again.",
                    "code": 500,
                    "category": "pipeline.unknown",
                    "retryable": False,
                    "retry_after_seconds": None,
                }
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
