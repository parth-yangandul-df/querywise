"""interpret_result node — formats query results as markdown tables."""

import logging
from typing import Any

from app.core.metrics import timed_node
from app.llm.agents.result_interpreter import format_single_value_result
from app.llm.graph.state import GraphState
from app.llm.stream_stages import INTERPRETING, emit

logger = logging.getLogger(__name__)


@timed_node("interpret_result")
async def interpret_result(state: GraphState) -> dict[str, Any]:
    """Format query results as a markdown table. No LLM — zero latency."""
    result = state.get("result")
    if not result:
        return {
            "answer": None,
            "highlights": [],
            "suggested_followups": [],
        }

    if not result.rows:
        if state.get("event_queue"):
            await state.get("event_queue").put(emit(INTERPRETING))
        return {
            "answer": "No matching rows found.",
            "highlights": [],
            "suggested_followups": [
                "Show SQL",
                "Broader search terms",
                "Remove last filter",
            ],
        }

    # Single value: return plain text immediately (no LLM)
    single_value = format_single_value_result(result.rows)
    if single_value is not None:
        return {
            "answer": single_value,
            "highlights": [],
            "suggested_followups": [],
        }

    # Skip LLM interpretation ENTIRELY for all result sets.
    # Format results as a markdown table directly — eliminates 5-6s of LLM latency
    # and avoids the quality/consistency issues of model-generated summaries.
    if state.get("event_queue"):
        await state.get("event_queue").put(emit(INTERPRETING))
    formatted = _format_result_as_table(result.columns, result.rows, result.row_count)
    return {
        "answer": formatted,
        "highlights": [],
        "suggested_followups": _generate_followups_for_small_result(result.columns, result.rows),
    }


def _format_result_as_table(
    columns: list[str], rows: list[list], row_count: int, max_display: int = 50
) -> str:
    """Format query results as a markdown table for direct display.

    Capped at *max_display* rows with a count suffix so large result sets
    don't produce wall-of-text answers.
    """
    if not rows:
        return "No results found."

    lines = []

    # Header row
    header = " | ".join(columns)
    lines.append(header)
    lines.append("-" * len(header))

    # Data rows (capped)
    display_rows = rows[:max_display]
    for row in display_rows:
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))

    if row_count > max_display:
        lines.append(f"\n… and {row_count - max_display} more rows")

    return "\n".join(lines)


def _generate_followups_for_small_result(columns: list[str], rows: list[list]) -> list[str]:
    """Generate contextual follow-up suggestions based on the result schema."""
    followups = ["Show SQL"]

    col_lower = [c.lower() for c in columns]

    # If result has a name column, suggest filtering by name
    name_cols = [c for c in col_lower if "name" in c]
    if name_cols:
        followups.append(f"Filter by {name_cols[0].replace('_', ' ')}")

    # If result has date columns, suggest date range filter
    date_cols = [c for c in col_lower if any(d in c for d in ["date", "time", "year", "month"])]
    if date_cols:
        followups.append("Filter by date range")

    # If result has status/active columns, suggest status filter
    status_cols = [c for c in col_lower if any(s in c for s in ["status", "active", "state"])]
    if status_cols:
        followups.append("Filter by status")

    # If multiple rows, suggest sorting
    if len(rows) > 1:
        followups.append(f"Sort by {columns[0]}")

    return followups[:3]
