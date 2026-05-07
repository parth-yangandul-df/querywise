"""write_history node — saves QueryExecution record to the app database."""

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.db.models.query_history import QueryExecution
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 20


def _sanitize_value(value: Any) -> Any:
    """Convert non-serializable types to JSON-serializable formats."""
    if isinstance(value, Decimal):
        return float(value) if value % 1 else int(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _sanitize_rows(rows: list[list[Any]]) -> list[list[Any]]:
    """Sanitize row values for JSONB serialization."""
    return [[_sanitize_value(v) for v in row] for row in rows]


async def write_history(state: GraphState) -> dict[str, Any]:
    """Persist the query execution record to the app database.

    Failures are logged and swallowed — a history write error must never
    prevent the query response from reaching the caller.
    """
    db = state["db"]
    result = state.get("result")
    error = state.get("error")
    action = state.get("action") or "query"

    # Determine turn_type from action
    turn_type = (
        action if action in ("query", "clarification", "show_sql", "explain_result") else "query"
    )

    # For successful query turns, persist column names and a result preview
    result_columns: list | None = None
    result_preview_rows: list | None = None
    if turn_type == "query" and result and not error:
        result_columns = result.columns
        raw_rows = [list(row) for row in result.rows[:_MAX_PREVIEW_ROWS]]
        result_preview_rows = _sanitize_rows(raw_rows)

    # result_summary: clarification message for clarification turns, answer for others
    if turn_type == "clarification":
        summary = state.get("clarification_message")
    else:
        summary = state.get("answer")

    # Build turn_context for follow-up reuse
    turn_context: dict | None = None
    if turn_type == "query" and result and not error:
        result_status = "empty" if not result.rows else "success"
        turn_context = {
            "resolved_question": state.get("resolved_question") or state["question"],
            "answer": summary,
            "result_columns": result_columns,
            "result_preview_rows": result_preview_rows,
            "result_status": result_status,
        }

    try:
        execution = QueryExecution(
            connection_id=uuid.UUID(state["connection_id"]),
            session_id=uuid.UUID(state["session_id"]) if state.get("session_id") else None,
            user_id=uuid.UUID(state["user_id"]) if state.get("user_id") else None,
            natural_language=state["question"],
            generated_sql=state.get("generated_sql"),
            final_sql=state.get("sql"),
            execution_status="error" if error and turn_type == "query" else "success",
            error_message=error if turn_type == "query" else None,
            row_count=result.row_count if result else None,
            execution_time_ms=result.execution_time_ms if result else None,
            retry_count=state.get("retry_count", 0),
            result_summary=summary,
            llm_provider=state.get("llm_provider"),
            llm_model=state.get("llm_model"),
            turn_type=turn_type,
            clarification_reason=state.get("clarification_reason"),
            result_columns=result_columns,
            result_preview_rows=result_preview_rows,
            turn_context=turn_context,
        )
        db.add(execution)
        await db.flush()
    except Exception as e:
        logger.error(
            "write_history: failed - session=%s action=%s error=%s",
            state.get("session_id"),
            action,
            str(e),
            exc_info=True,
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return {
            "execution_id": None,
            "execution_time_ms": result.execution_time_ms if result else None,
            "history_write_failed": True,
        }

    return {
        "execution_id": execution.id,
        "execution_time_ms": result.execution_time_ms if result else None,
    }
