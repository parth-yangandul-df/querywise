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
from app.core.metrics import timed_node
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)


def _format_result_as_table(
    columns: list[str], rows: list[list], row_count: int, max_display: int = 50
) -> str:
    """Format query results as a clean, readable markdown table.

    - Truncates cell values to keep width manageable
    - Caps displayed rows
    - Uses proper markdown table syntax
    """
    if not rows:
        return "No results found."

    # Truncate long values so the table doesn't become a wall of text
    MAX_CELL_LEN = 28
    MAX_COLS = 12  # Show at most 12 columns; very wide tables are unreadable

    display_cols = columns[:MAX_COLS]
    col_indices = list(range(len(display_cols)))
    truncated = len(columns) > MAX_COLS

    def _fmt(val: Any) -> str:
        s = "NULL" if val is None else str(val)
        return s if len(s) <= MAX_CELL_LEN else s[:MAX_CELL_LEN - 1] + "…"

    # Build rows of formatted strings
    formatted_rows = []
    for row in rows[:max_display]:
        formatted_rows.append([_fmt(row[i]) for i in col_indices])

    # Compute per-column widths for alignment
    widths = [len(c) for c in display_cols]
    for row in formatted_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    # Render markdown table
    def _pad(cell: str, w: int) -> str:
        return cell + " " * (w - len(cell))

    header = "| " + " | ".join(_pad(display_cols[i], widths[i]) for i in col_indices) + " |"
    sep = "|" + "|".join("-" * (widths[i] + 2) for i in col_indices) + "|"

    lines = [f"**{row_count} rows**" + (" — showing first " + str(min(max_display, row_count)) if row_count > max_display else ""), ""]
    lines.append(header)
    lines.append(sep)
    for row in formatted_rows:
        lines.append("| " + " | ".join(_pad(row[i], widths[i]) for i in col_indices) + " |")

    if row_count > max_display:
        lines.append(f"\n… and {row_count - max_display} more rows")

    if truncated:
        lines.append(f'\n_(Showing {MAX_COLS} of {len(columns)} columns — ask "show all columns" to see the full table)_')

    return "\n".join(lines)


def _format_single_value(rows: list[list]) -> str | None:
    """Return plain text for a single-cell result, or None if not single-value."""
    if len(rows) == 1 and len(rows[0]) == 1:
        return str(rows[0][0])
    return None


@timed_node("execute_sql")
async def execute_sql(state: GraphState) -> dict[str, Any]:
    """Execute SQL and format the answer directly — no separate interpret node."""
    sql_to_run = state.get("sql") or state.get("generated_sql") or ""
    generated_sql = state.get("generated_sql") or sql_to_run

    if state.get("event_queue"):
        await state.get("event_queue").put(
            {"type": "stage", "stage": "running_query", "label": "Running query...", "progress": 75}
        )

    connector = await get_or_create_connector(
        state["connection_id"],
        state["connector_type"],
        state["connection_string"],
    )

    logger.info("execute_sql: running sql=%r", sql_to_run[:200])

    try:
        result = await connector.execute_query(
            sql_to_run,
            timeout_seconds=state.get("timeout_seconds", 30),
            max_rows=state.get("max_rows", 1000),
        )
    except Exception as e:
        logger.warning("execute_sql: query failed error=%s sql=%r", e, sql_to_run[:200])
        return {
            "sql": sql_to_run,
            "generated_sql": generated_sql,
            "result": None,
            "error": str(e),
            "answer": None,
        }

    # Format minimal answer — frontend already renders the real data table
    # from result.rows / result.columns.  The answer field is just chat text.
    if not result.rows:
        answer = "No matching rows found."
    else:
        single = _format_single_value(result.rows)
        answer = single if single is not None else f"{result.row_count} row(s) returned"

    return {
        "sql": sql_to_run,
        "generated_sql": generated_sql,
        "result": result,
        "error": None,
        "answer": answer,
    }


def route_after_execute(state: GraphState) -> str:
    """Route to handle_error if execution failed, else write_history directly."""
    if state.get("error"):
        return "handle_error"
    return "write_history"
