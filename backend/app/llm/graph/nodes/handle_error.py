"""handle_error node — LLM-assisted SQL correction loop.

Calls ErrorHandlerAgent with the current invalid SQL and validation issues.
On a successful correction, updates generated_sql and routes back to
validate_sql (the retry cycle). After MAX_RETRIES attempts, or when the
agent signals it cannot fix the query, sets action=clarification and routes
to write_history.

MAX_RETRIES matches the original llm_fallback behaviour (3 attempts).
"""

import logging
import re
from typing import Any

import sqlglot
from sqlglot import exp

from app.llm.agents.error_handler import ErrorHandlerAgent
from app.llm.graph.state import GraphState
from app.llm.router import route_for_role

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3

_DISTINCT_TOP_ODBC_ERROR = "incorrect syntax near the keyword 'distinct'"


def _try_fix_distinct_top_error(sql: str, error: str) -> str | None:
    """Convert SELECT DISTINCT to GROUP BY to fix SQL Server ODBC Driver 18 errors.

    ODBC Driver 18 rejects 'SELECT DISTINCT TOP N col FROM t1 JOIN t2' even though
    it is valid T-SQL. The correct fix is to replace SELECT DISTINCT with a GROUP BY
    on all projected columns, which provides identical deduplication semantics.

    Returns the corrected SQL string, or None if the pattern doesn't match.
    """
    if _DISTINCT_TOP_ODBC_ERROR not in error.lower():
        return None

    sql_upper = sql.upper()
    if "DISTINCT" not in sql_upper:
        return None

    # Try sqlglot-based rewrite: strip DISTINCT and inject GROUP BY
    try:
        tree = sqlglot.parse_one(sql, read="tsql")
        select_node = tree.find(exp.Select)
        if select_node and select_node.args.get("distinct"):
            # Remove DISTINCT flag
            select_node.args["distinct"] = None

            # Collect all projected column expressions for GROUP BY
            # Skip aggregates (COUNT, SUM, etc.) — they must stay as-is
            group_by_cols: list[exp.Expression] = []
            for expr in select_node.expressions:
                # Unwrap aliases: use the alias target, not the full aliased expression
                col = expr.this if isinstance(expr, exp.Alias) else expr
                # Skip window functions and aggregates
                if not col.find(exp.AggFunc) and not col.find(exp.Window):
                    group_by_cols.append(col.copy())

            if group_by_cols and not tree.find(exp.Group):
                tree.set("group", exp.Group(expressions=group_by_cols))

            fixed = tree.sql(dialect="tsql")
            logger.info(
                "handle_error: converted SELECT DISTINCT → GROUP BY to fix ODBC error "
                "(%d GROUP BY columns)",
                len(group_by_cols),
            )
            return fixed
    except Exception as exc:  # noqa: BLE001
        logger.debug("handle_error: sqlglot DISTINCT fix failed (%s), falling back to regex", exc)

    # Regex fallback: strip DISTINCT (deduplication will be approximate)
    match = re.search(
        r"(SELECT\s+(?:TOP\s+\d+\s+)?)\s*DISTINCT\s+",
        sql,
        re.IGNORECASE,
    )
    if not match:
        return None

    prefix = match.group(1)
    after_distinct = sql[match.end():]
    fixed = f"{prefix}{after_distinct.lstrip()}"
    logger.info(
        "handle_error: regex-stripped DISTINCT from SQL (GROUP BY not injected — fallback path)",
    )
    return fixed


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

    # Fast path: try to auto-fix SQL Server ODBC DISTINCT/TOP error without LLM.
    if execution_error:
        fixed = _try_fix_distinct_top_error(generated_sql, execution_error)
        if fixed:
            logger.info(
                "handle_error: auto-corrected DISTINCT/TOP error on attempt %d — retrying",
                retry_count + 1,
            )
            return {
                "generated_sql": fixed,
                "sql": None,
                "retry_count": retry_count + 1,
                "previous_attempts": previous_attempts + [fixed],
                "llm_provider": provider.provider_type.value,
                "llm_model": llm_config.model,
                "_target_node": "execute_sql",
            }

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

    if not resolution.corrected_sql:
        return _exhausted(validation_issues, execution_error, retry_count, provider, llm_config)

    # Dedup fast-fail: if the model returned the same SQL, further retries will also fail.
    # Short-circuit immediately rather than burning remaining retry budget on identical output.
    if resolution.corrected_sql.strip() == generated_sql.strip():
        logger.warning(
            "handle_error: model returned identical SQL on attempt %d — fast-failing",
            retry_count + 1,
        )
        return _exhausted(validation_issues, execution_error, retry_count, provider, llm_config)

    # If the model says should_retry=False but gave us different SQL, still use it —
    # the corrected SQL may be valid even if the agent thinks the fix is uncertain.
    if not resolution.should_retry:
        logger.info(
            "handle_error: should_retry=False but corrected_sql is different — using it once",
        )

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
        "sql": None,
        "action": "query",  # CRITICAL: override stale action (e.g. "no_sql_retry", "clarification")
        "retry_count": new_retry_count,
        "previous_attempts": previous_attempts + [resolution.corrected_sql],
        "llm_provider": provider.provider_type.value,
        "llm_model": llm_config.model,
        "_target_node": target_node,
        "validation_issues": [],  # Clear stale issues — validate_sql will re-evaluate
        "needs_context_rebuild": False,  # Clear stale rebuild flag
        "force_include_tables": [],  # Clear stale forced tables
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
        "_target_node": None,
    }


def route_after_handle_error(state: GraphState) -> str:
    """Route to execute_sql (DB errors) or validate_sql (validation), else write_history."""
    if state.get("action") == "clarification":
        return "write_history"
    target = state.get("_target_node")
    if target in ("execute_sql", "validate_sql"):
        return target
    return "validate_sql"
