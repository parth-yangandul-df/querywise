"""interpret_result node — wraps ResultInterpreterAgent, with optional token streaming."""

import json
import logging
from typing import Any

from app.llm.agents.result_interpreter import (
    InterpretationOutput,
    ResultInterpreterAgent,
    format_single_value_result,
)
from app.llm.base_provider import LLMMessage
from app.llm.graph.state import GraphState
from app.llm.router import route_for_role
from app.llm.utils import repair_json

logger = logging.getLogger(__name__)


async def interpret_result(state: GraphState) -> dict[str, Any]:
    """Interpret query results. Streams tokens if event_queue is present."""
    result = state.get("result")
    if not result or not result.rows:
        return {
            "answer": None,
            "highlights": [],
            "suggested_followups": [],
        }

    single_value = format_single_value_result(result.rows)
    if single_value is not None:
        return {
            "answer": single_value,
            "highlights": [],
            "suggested_followups": [],
        }

    question = state.get("resolved_question") or state["question"]
    sql: str = state.get("sql") or ""
    provider, llm_config = route_for_role(question, role="interpreter")

    if state.get("event_queue"):
        await state["event_queue"].put(
            {
                "type": "stage",
                "stage": "interpreting",
                "label": "Interpreting results...",
                "progress": 80,
            }
        )

    try:
        if state.get("event_queue"):
            interpretation = await _stream_interpret(
                state, provider, llm_config, question, sql, result
            )
        else:
            interpreter = ResultInterpreterAgent(provider, llm_config)
            interpretation = await interpreter.interpret(
                question=question,
                sql=sql,
                columns=result.columns,
                rows=result.rows,
                row_count=result.row_count,
            )
    except Exception:
        logger.warning("interpret_result: LLM interpretation failed", exc_info=True)
        return {
            "answer": None,
            "highlights": [],
            "suggested_followups": [],
        }

    return {
        "answer": interpretation.summary,
        "highlights": interpretation.highlights,
        "suggested_followups": interpretation.suggested_followups,
    }


async def _stream_interpret(
    state, provider, llm_config, question, sql, result
) -> InterpretationOutput:
    """Stream interpreter tokens into event_queue and return structured interpretation."""
    from app.llm.agents.result_interpreter import _format_results_preview
    from app.llm.prompts.interpreter_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

    results_preview = _format_results_preview(result.columns, result.rows, max_rows=20)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        question=question,
        sql=sql,
        row_count=result.row_count,
        columns=", ".join(result.columns),
        results_preview=results_preview,
    )
    messages = [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_prompt),
    ]

    full_text = ""
    async for token in provider.stream(messages, llm_config):
        full_text += token
        await state["event_queue"].put({"type": "token", "content": token})

    # Extract summary from the streamed JSON if the model returned JSON
    try:
        parsed = json.loads(repair_json(full_text))
        return InterpretationOutput(
            summary=parsed.get("summary", full_text),
            highlights=parsed.get("highlights", []),
            suggested_followups=parsed.get("suggested_followups", []),
        )
    except Exception:
        return InterpretationOutput(
            summary=full_text,
            highlights=[],
            suggested_followups=[],
        )
