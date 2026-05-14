"""compose_sql node — SQL generation via QueryComposerAgent.

Receives the scope-injected prompt_context assembled by build_context_node
and calls the LLM composer to produce SQL for the resolved question.

Short-circuits to write_history (with action=clarification) if:
  - The LLM signals a scope violation (returns SCOPE_VIOLATION sentinel)
  - The LLM returns no SQL at all AND compose_retry_count >= _MAX_COMPOSE_RETRIES
"""

import logging
import re
import time
from typing import Any

from app.core.metrics import record_llm_call, timed_node
from app.llm.agents.query_composer import QueryComposerAgent
from app.llm.graph.state import GraphState
from app.llm.router import QueryComplexity, route
from app.llm.stream_stages import GENERATING_SQL, emit

logger = logging.getLogger(__name__)

_MAX_COMPOSE_RETRIES = 2  # up to 3 total attempts (0, 1, 2)

_SCOPE_VIOLATION_MSG = (
    "This query is not permitted. As a standard user you can only access your own data. "
    "Try asking about your own projects, timesheets, allocation, or skills."
)


# Patterns that indicate the user is asking for unscoped / all data
_UNSCOPED_QUERY_PATTERNS = [
    r"\blist all\b",
    r"\bshow all\b",
    r"\ball \w+\b",
    r"\bevery \w+\b",
    r"\ball (?:clients|projects|resources|employees|users)\b",
    r"\b(?:clients|projects|resources|employees|users) (?:list|overview|summary)\b",
]


def _is_unscoped_question(question: str) -> bool:
    """Detect if the user is asking for ALL data rather than their own scoped data."""
    q_lower = question.lower()
    return any(re.search(p, q_lower) for p in _UNSCOPED_QUERY_PATTERNS)


@timed_node("compose_sql")
async def compose_sql(state: GraphState) -> dict[str, Any]:
    """Generate SQL from the resolved question using the LLM composer."""
    resolved_question = state.get("resolved_question") or state["question"]
    prompt_context = state.get("prompt_context") or ""
    resource_id = state.get("resource_id")
    employee_id = state.get("employee_id")

    hint_sql = state.get("similarity_hint_sql")
    if hint_sql:
        hint_block = (
            f"\n\nNOTE: A similar validated query exists:\n{hint_sql}\n"
            "Use this as a reference but adjust the filters to match the question exactly."
        )
        prompt_context = prompt_context + hint_block
        logger.info("compose_sql: injected similarity hint SQL (%d chars)", len(hint_sql))

    # Hard RBAC gate: 'user' role asking for ALL data → immediate rejection.
    # admin and manager bypass scope constraints entirely.
    user_role = state.get("user_role")
    if (
        user_role == "user"
        and (resource_id is not None or employee_id is not None)
        and _is_unscoped_question(resolved_question)
    ):
        logger.warning(
            "compose_sql: unscoped question for scoped user — "
            "resource_id=%s employee_id=%s question=%r",
            resource_id,
            employee_id,
            resolved_question[:60],
        )
        return {
            "action": "clarification",
            "clarification_reason": "scope_violation",
            "clarification_message": _SCOPE_VIOLATION_MSG,
            "clarification_options": [],
            "error": _SCOPE_VIOLATION_MSG,
            "generated_sql": None,
        }

    if state.get("event_queue"):
        await state["event_queue"].put(emit(GENERATING_SQL))

    # If schema context has many tables, the query is NOT simple —
    # force MODERATE complexity so we use the strong model (e.g., deepseek-v3.2)
    # instead of the fast cheap model (gpt-4.1-nano) which hallucinates with
    # large schema contexts.
    schema_tables = state.get("schema_tables") or {}
    complexity_override = None
    if len(schema_tables) > 6:
        complexity_override = QueryComplexity.MODERATE
        logger.info(
            "compose_sql: %d tables in schema context — forcing MODERATE complexity",
            len(schema_tables),
        )

    provider, llm_config = route(resolved_question, complexity_override=complexity_override)
    composer = QueryComposerAgent(provider, llm_config)
    llm_start = time.monotonic()
    composer_output = await composer.compose(
        resolved_question,
        prompt_context,
        conversation_history=state.get("loaded_history") or [],
    )
    record_llm_call(
        "compose_sql",
        provider.provider_type.value,
        llm_config.model,
        time.monotonic() - llm_start,
    )
    generated_sql = composer_output.generated_sql

    # LLM signalled it cannot scope the query for this user
    if (
        user_role == "user"
        and (resource_id is not None or employee_id is not None)
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
        compose_retry_count = state.get("compose_retry_count", 0)
        logger.warning(
            "compose_sql: LLM returned empty SQL — provider=%s model=%s "
            "explanation=%r confidence=%.2f tables_used=%s assumptions=%s "
            "compose_retry_count=%d",
            provider.provider_type.value,
            llm_config.model,
            composer_output.explanation[:200] if composer_output.explanation else None,
            composer_output.confidence,
            composer_output.tables_used,
            composer_output.assumptions,
            compose_retry_count,
        )
        if compose_retry_count < _MAX_COMPOSE_RETRIES:
            # Retry: increment counter and loop back to compose_sql
            return {
                "compose_retry_count": compose_retry_count + 1,
                "action": "no_sql_retry",
                "llm_provider": provider.provider_type.value,
                "llm_model": llm_config.model,
            }
        # Exhausted retries — give up and ask user to rephrase
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
        generated_sql[:200],
        provider.provider_type.value,
        llm_config.model,
    )
    logger.debug("compose_sql: generated_sql full=%r", generated_sql)

    return {
        "generated_sql": generated_sql,
        "explanation": composer_output.explanation,
        "llm_provider": provider.provider_type.value,
        "llm_model": llm_config.model,
        "previous_attempts": [generated_sql],
        "retry_count": 0,
    }


def route_after_compose(state: GraphState) -> str:
    """Route to validate_sql, compose_sql (retry), or write_history on scope/no-SQL."""
    action = state.get("action")
    if action == "no_sql_retry":
        return "compose_sql"
    if action == "clarification":
        return "write_history"
    return "validate_sql"
