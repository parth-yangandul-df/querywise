"""execute_sql node — runs SQL against the target database connector.

Uses the connector_type and connection_string already stored in state by
query_service (avoids a MissingGreenlet error from re-accessing the expired
ORM connection object after awaits inside an asyncio.create_task context).

SQL source priority:
  1. state["sql"]            — set by similarity_check on the shortcut path
  2. state["generated_sql"]  — set by compose_sql / handle_error on normal path
"""

import logging
from typing import Any

from app.connectors.connector_registry import get_or_create_connector
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)


async def execute_sql(state: GraphState) -> dict[str, Any]:
    """Execute the current SQL against the target database."""
    # Shortcut path: similarity_check already set state["sql"]
    # Normal path: use the latest generated (and validated) SQL
    sql_to_run = state.get("sql") or state.get("generated_sql") or ""
    generated_sql = state.get("generated_sql") or sql_to_run

    if state.get("event_queue"):
        await state["event_queue"].put(
            {"type": "stage", "stage": "running_query", "label": "Running query...", "progress": 75}
        )

    connector = await get_or_create_connector(
        state["connection_id"],
        state["connector_type"],
        state["connection_string"],
    )

    logger.info("execute_sql: running sql=%r", sql_to_run[:80])

    try:
        result = await connector.execute_query(
            sql_to_run,
            timeout_seconds=state.get("timeout_seconds", 30),
            max_rows=state.get("max_rows", 1000),
        )
    except Exception as e:
        logger.warning("execute_sql: query failed error=%s", e)
        return {
            "sql": sql_to_run,
            "generated_sql": generated_sql,
            "result": None,
            "error": str(e),
        }

    return {
        "sql": sql_to_run,
        "generated_sql": generated_sql,
        "result": result,
        "error": None,
    }


def route_after_execute(state: GraphState) -> str:
    """Route to handle_error if execution failed, otherwise interpret result."""
    if state.get("error"):
        return "handle_error"
    return "interpret_result"
