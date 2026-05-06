"""answer_from_state node — handles show_sql and explain_result without DB execution.

show_sql: returns the last generated SQL directly from loaded state.
explain_result: makes one LLM call grounded in the stored result preview to explain
                why specific rows appeared, what patterns exist, etc.
"""

import logging
from typing import Any

from app.llm.base_provider import LLMMessage
from app.llm.graph.state import GraphState
from app.llm.router import route_for_role

logger = logging.getLogger(__name__)

_EXPLAIN_SYSTEM_PROMPT = """\
You are a data analyst assistant. The user is asking a question about the results \
of a previous database query. Use the provided SQL, column names, and result preview \
to give a clear, grounded explanation.

Be specific — reference actual values from the results. Do not speculate beyond what \
the data shows. Keep your answer concise (under 200 words).

Respond with plain text, not JSON."""


async def answer_from_state(state: GraphState) -> dict[str, Any]:
    """Return an answer from loaded state without executing any SQL."""
    action = state.get("action")

    if action == "show_sql":
        return await _handle_show_sql(state)
    if action == "explain_result":
        return await _handle_explain_result(state)

    # Fallback — should not reach here
    return {
        "answer": None,
        "highlights": [],
        "suggested_followups": [],
        "error": f"Unknown action: {action}",
    }


async def _handle_show_sql(state: GraphState) -> dict[str, Any]:
    sql = state.get("last_generated_sql")
    if not sql:
        return {
            "answer": None,
            "highlights": [],
            "suggested_followups": [],
            "clarification_reason": "missing_previous_sql",
            "clarification_message": "I don't have a previous SQL query to show. Try running a query first.",
            "clarification_options": [],
            "action": "clarification",
        }

    if state.get("event_queue"):
        await state["event_queue"].put(
            {
                "type": "stage",
                "stage": "understanding",
                "label": "Retrieving previous SQL...",
                "progress": 90,
            }
        )

    return {
        "answer": f"```sql\n{sql}\n```",
        "generated_sql": sql,
        "sql": sql,
        "highlights": [],
        "suggested_followups": [],
    }


async def _handle_explain_result(state: GraphState) -> dict[str, Any]:
    columns = state.get("last_result_columns")
    preview_rows = state.get("last_result_preview_rows")
    last_sql = state.get("last_generated_sql")

    if not columns or not preview_rows:
        return {
            "answer": None,
            "highlights": [],
            "suggested_followups": [],
            "clarification_reason": "missing_previous_result",
            "clarification_message": "I don't have a previous result to explain. Try running a query first.",
            "clarification_options": [],
            "action": "clarification",
        }

    if state.get("event_queue"):
        await state["event_queue"].put(
            {
                "type": "stage",
                "stage": "interpreting",
                "label": "Interpreting results...",
                "progress": 80,
            }
        )

    # Format a compact preview table
    preview_text = _format_preview(columns, preview_rows)
    user_prompt = (
        f"Question: {state['question']}\n\n"
        f"SQL that produced this result:\n{last_sql or 'unknown'}\n\n"
        f"Columns: {', '.join(columns)}\n\n"
        f"Result preview ({len(preview_rows)} rows shown):\n{preview_text}"
    )

    messages = [
        LLMMessage(role="system", content=_EXPLAIN_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_prompt),
    ]

    provider, llm_config = route_for_role(state["question"], role="interpreter")
    try:
        if state.get("event_queue"):
            explanation = ""
            async for token in provider.stream(messages, llm_config):
                explanation += token
                await state["event_queue"].put({"type": "token", "content": token})
        else:
            response = await provider.complete(messages, llm_config)
            explanation = response.content
    except Exception:
        logger.warning("answer_from_state: explain_result LLM call failed", exc_info=True)
        explanation = "I was unable to explain the result at this time."

    return {
        "answer": explanation,
        "highlights": [],
        "suggested_followups": [],
    }


def _format_preview(columns: list[str], rows: list[list]) -> str:
    header = " | ".join(columns)
    separator = "-" * len(header)
    lines = [header, separator]
    for row in rows[:20]:
        lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
    return "\n".join(lines)
