"""compose_sql node — SQL generation via QueryComposerAgent.

Receives the scope-injected prompt_context assembled by build_context_node
and calls the LLM composer to produce SQL for the resolved question.

Short-circuits to write_history (with action=clarification) if:
  - The LLM signals a scope violation (returns SCOPE_VIOLATION sentinel)
  - The LLM returns no SQL at all
"""

import logging
from typing import Any

from app.llm.agents.query_composer import QueryComposerAgent
from app.llm.graph.state import GraphState
from app.llm.router import route

logger = logging.getLogger(__name__)

_SCOPE_VIOLATION_MSG = (
    "This query is not permitted. As a standard user you can only access your own data. "
    "Try asking about your own projects, timesheets, allocation, or skills."
)


async def compose_sql(state: GraphState) -> dict[str, Any]:
    """Generate SQL from the resolved question using the LLM composer."""
    resolved_question = state.get("resolved_question") or state["question"]
    prompt_context = state.get("prompt_context") or ""
    resource_id = state.get("resource_id")
    employee_id = state.get("employee_id")

    if state.get("event_queue"):
        await state["event_queue"].put(
            {
                "type": "stage",
                "stage": "generating_sql",
                "label": "Generating SQL...",
                "progress": 55,
            }
        )

    provider, llm_config = route(resolved_question)
    composer = QueryComposerAgent(provider, llm_config)
    composer_output = await composer.compose(
        resolved_question,
        prompt_context,
        conversation_history=state.get("loaded_history") or [],
    )
    generated_sql = composer_output.generated_sql

    # LLM signalled it cannot scope the query for this user
    if (
        (resource_id is not None or employee_id is not None)
        and generated_sql
        and "SCOPE_VIOLATION" in generated_sql.upper()
    ):
        return {
            "action": "clarification",
            "clarification_reason": "scope_violation",
            "clarification_message": _SCOPE_VIOLATION_MSG,
            "clarification_options": [],
            "error": _SCOPE_VIOLATION_MSG,
            "llm_provider": provider.provider_type.value,
            "llm_model": llm_config.model,
            "generated_sql": None,
        }

    if not generated_sql:
        return {
            "action": "clarification",
            "clarification_reason": "no_sql_generated",
            "clarification_message": (
                "I wasn't able to generate a SQL query for your question. Could you rephrase it?"
            ),
            "clarification_options": ["Rephrase my question", "Try a simpler version"],
            "error": "LLM did not produce SQL",
            "llm_provider": provider.provider_type.value,
            "llm_model": llm_config.model,
        }

    logger.info(
        "compose_sql: generated sql=%r provider=%s model=%s",
        generated_sql[:80],
        provider.provider_type.value,
        llm_config.model,
    )

    return {
        "generated_sql": generated_sql,
        "explanation": composer_output.explanation,
        "llm_provider": provider.provider_type.value,
        "llm_model": llm_config.model,
        "previous_attempts": [generated_sql],
        "retry_count": 0,
    }


def route_after_compose(state: GraphState) -> str:
    """Route to validate_sql, or short-circuit to write_history on scope/no-SQL."""
    if state.get("action") == "clarification":
        return "write_history"
    return "validate_sql"
