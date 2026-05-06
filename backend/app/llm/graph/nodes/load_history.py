"""load_history node — loads recent conversation turns from QueryExecution records.

Runs at graph entry. Produces a compact history bundle for resolve_turn:
- loaded_history: last 6 turns as [{role, content}], summaries truncated to 400 chars
- last_generated_sql: SQL from the most recent successful query turn only
- last_result_columns: columns from the most recent successful query turn
- last_result_preview_rows: result preview (max 20 rows) from last successful query turn

First-turn requests (empty session or no prior executions) return empty state —
resolve_turn is then skipped and the graph goes straight to the query path.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import desc, select

from app.db.models.query_history import QueryExecution
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)

_MAX_TURNS = 6
_SUMMARY_TRUNCATE = 400  # chars per assistant turn


async def load_history(state: GraphState) -> dict[str, Any]:
    """Load recent session turns from the database into GraphState."""
    session_id_str = state.get("session_id")
    if not session_id_str:
        return _empty_history()

    event_queue = state.get("event_queue")
    if event_queue is not None:
        await event_queue.put(
            {
                "type": "stage",
                "stage": "understanding",
                "label": "Understanding your question...",
                "progress": 10,
            }
        )

    db = state["db"]
    try:
        session_id = uuid.UUID(session_id_str)
    except ValueError:
        return _empty_history()

    try:
        result = await db.execute(
            select(QueryExecution)
            .where(QueryExecution.session_id == session_id)
            .order_by(desc(QueryExecution.created_at))
            .limit(_MAX_TURNS)
        )
        rows: list[QueryExecution] = list(reversed(result.scalars().all()))
    except Exception:
        logger.warning("load_history: failed to load session history", exc_info=True)
        return _empty_history()

    if not rows:
        return _empty_history()

    # Build compacted [{role, content}] message list
    history: list[dict] = []
    for row in rows:
        # User turn — always the natural language question
        history.append({"role": "user", "content": row.natural_language})
        # Assistant turn — result_summary for query/explain, or clarification message
        assistant_content = _assistant_content(row)
        if assistant_content:
            history.append({"role": "assistant", "content": assistant_content})

    # Trim to last _MAX_TURNS messages (user+assistant pairs = _MAX_TURNS each)
    # Keep at most 3 user + 3 assistant = 6 messages
    history = history[-_MAX_TURNS:]

    # Extract last SQL + result preview from the most recent successful query turn
    last_sql: str | None = None
    last_columns: list[str] | None = None
    last_preview: list[list] | None = None
    for row in reversed(rows):
        if row.turn_type == "query" and row.execution_status == "success":
            last_sql = row.generated_sql or row.final_sql
            last_columns = row.result_columns
            last_preview = row.result_preview_rows
            break

    return {
        "loaded_history": history,
        "last_generated_sql": last_sql,
        "last_result_columns": last_columns,
        "last_result_preview_rows": last_preview,
    }


def _assistant_content(row: QueryExecution) -> str | None:
    """Extract the assistant-facing content from a turn record."""
    if row.turn_type == "clarification":
        # Use result_summary which stores the clarification message
        content = row.result_summary
    elif row.turn_type == "show_sql":
        content = f"[SQL shown]\n{row.final_sql or row.generated_sql or ''}"
    elif row.turn_type == "explain_result":
        content = row.result_summary
    else:
        content = row.result_summary

    if not content:
        return None
    # Truncate to keep token cost bounded
    return content[:_SUMMARY_TRUNCATE]


def _empty_history() -> dict[str, Any]:
    return {
        "loaded_history": [],
        "last_generated_sql": None,
        "last_result_columns": None,
        "last_result_preview_rows": None,
    }
