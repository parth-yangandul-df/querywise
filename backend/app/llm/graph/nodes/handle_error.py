"""handle_error node — LLM-assisted SQL correction loop.

Calls ErrorHandlerAgent with the current invalid SQL and validation issues.
On a successful correction, updates generated_sql and routes back to
validate_sql (the retry cycle). After MAX_RETRIES attempts, or when the
agent signals it cannot fix the query, sets action=clarification and routes
to write_history.

MAX_RETRIES matches the original llm_fallback behaviour (3 attempts).
"""

import logging
from typing import Any

from app.llm.agents.error_handler import ErrorHandlerAgent
from app.llm.graph.state import GraphState
from app.llm.router import route_for_role

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


async def handle_error(state: GraphState) -> dict[str, Any]:
    """Attempt to correct invalid SQL via the error handler LLM agent."""
    question = state["question"]
    generated_sql = state.get("generated_sql") or state.get("sql") or ""
    validation_issues = state.get("validation_issues") or []
    execution_error = state.get("error")
    schema_tables: dict = state.get("schema_tables") or {}
    dialect = state.get("connector_type", "sqlserver")
    retry_count = state.get("retry_count") or 0
    previous_attempts = list(state.get("previous_attempts") or [generated_sql])

    resolved_question = state.get("resolved_question") or question
    # Use the fast resolver model — error correction is a simple rewrite, not composition
    provider, llm_config = route_for_role(resolved_question, role="error_handler")

    if retry_count >= _MAX_RETRIES:
        return _exhausted(validation_issues, execution_error, retry_count, provider, llm_config)

    # Try to load cached schema from last_query_context if state has none.
    # The follow-up fast path skips build_context, but history may have
    # schema_tables cached from the previous turn.
    if not schema_tables:
        lqc = state.get("last_query_context") or {}
        cached_schema = lqc.get("schema_tables")
        if cached_schema:
            schema_tables = cached_schema
            logger.info(
                "handle_error: loaded cached schema from history (%d tables)",
                len(cached_schema),
            )

    # Guard: execution errors (e.g., "Invalid column name") require schema context to fix.
    # If we still have no schema after checking history, we cannot auto-fix.
    if execution_error and not schema_tables:
        logger.warning(
            "handle_error: execution error with no schema context — cannot auto-fix. "
            "Escalating to clarification. error=%s",
            execution_error[:100],
        )
        return _exhausted(
            validation_issues,
            execution_error,
            retry_count,
            provider,
            llm_config,
            no_schema_context=True,
        )

    error_handler = ErrorHandlerAgent(provider, llm_config)

    error_source = execution_error or "; ".join(validation_issues)
    resolution = await error_handler.handle_error(
        question=question,
        failed_sql=generated_sql,
        error_message=error_source,
        schema_tables=schema_tables,
        dialect=dialect,
        attempt_number=retry_count + 1,
        previous_attempts=previous_attempts,
    )

    if not resolution.should_retry or not resolution.corrected_sql:
        return _exhausted(validation_issues, execution_error, retry_count, provider, llm_config)

    # Dedup fast-fail: if the model returned the same SQL, further retries will also fail.
    # Short-circuit immediately rather than burning remaining retry budget on identical output.
    if resolution.corrected_sql.strip() == generated_sql.strip():
        logger.warning(
            "handle_error: model returned identical SQL on attempt %d — fast-failing",
            retry_count + 1,
        )
        return _exhausted(validation_issues, execution_error, retry_count, provider, llm_config)

    new_retry_count = retry_count + 1
    logger.info(
        "handle_error: retry %d/%d corrected_sql=%r",
        new_retry_count,
        _MAX_RETRIES,
        resolution.corrected_sql[:80],
    )

    target_node = "execute_sql" if execution_error else "validate_sql"
    return {
        "generated_sql": resolution.corrected_sql,
        "retry_count": new_retry_count,
        "previous_attempts": previous_attempts + [resolution.corrected_sql],
        "llm_provider": provider.provider_type.value,
        "llm_model": llm_config.model,
        "_target_node": target_node,
    }


def _exhausted(
    validation_issues: list[str],
    execution_error: str | None,
    retry_count: int,
    provider: Any,
    llm_config: Any,
    no_schema_context: bool = False,
) -> dict[str, Any]:
    # Log the raw technical error server-side only — never expose to users.
    raw_error = execution_error or "; ".join(validation_issues) or "unknown"
    logger.error(
        "handle_error exhausted: retry_count=%d no_schema_context=%s raw_error=%s",
        retry_count,
        no_schema_context,
        raw_error[:200],
    )

    if no_schema_context:
        message = (
            "I couldn't refine your follow-up because I don't have enough schema "
            "context from the previous query. Please rephrase your question as a "
            "standalone query, or try a simpler version."
        )
    else:
        message = (
            "I wasn't able to generate a valid SQL query for your question. "
            "Could you rephrase it or try a simpler version?"
        )

    return {
        "action": "clarification",
        "clarification_reason": "retry_exhausted",
        "clarification_message": message,
        "clarification_options": [
            "Rephrase my question",
            "Try a simpler version",
            "Show available tables",
        ],
        "error": f"SQL generation failed after {retry_count} retries",
        "llm_provider": provider.provider_type.value,
        "llm_model": llm_config.model,
    }


def route_after_handle_error(state: GraphState) -> str:
    """Route to execute_sql (DB errors) or validate_sql (validation), else write_history."""
    if state.get("action") == "clarification":
        return "write_history"
    target = state.get("_target_node")
    if target in ("execute_sql", "validate_sql"):
        return target
    return "validate_sql"
