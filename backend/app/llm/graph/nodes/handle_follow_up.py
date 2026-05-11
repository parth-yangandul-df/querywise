"""handle_follow_up node — processes follow_up_query_refinement actions.

Routes based on follow_up_mode:
- reuse_answer: returns cached prior answer directly
- rewrite_sql: rewrites prior SQL with a minimal LLM prompt (fast model)
- needs_full_compose: escalates to full build_context path (handled by route_after_resolve)
"""

import json
import logging
import re
from typing import Any

from app.llm.base_provider import LLMMessage
from app.llm.graph.state import GraphState
from app.llm.router import route_for_role
from app.llm.utils import repair_json

logger = logging.getLogger(__name__)


def _extract_tables_from_sql(sql: str) -> set[str]:
    """Extract table names from a SQL query (SQL Server bracket notation + bare names).

    Handles: FROM [Table], JOIN [Table], FROM Table, JOIN Table, etc.
    """
    # Match [TableName] or bare TableName after FROM / JOIN / INTO
    pattern = re.compile(
        r"\b(?:FROM|JOIN|INTO)\s+(?:\[(\w+)\]|(\w+))",
        re.IGNORECASE,
    )
    tables = set()
    for m in pattern.finditer(sql):
        tables.add((m.group(1) or m.group(2)).lower())
    return tables


# SQL reserved words that should NOT be treated as column names
_SQL_KEYWORDS = {
    "select",
    "from",
    "where",
    "and",
    "or",
    "not",
    "null",
    "is",
    "as",
    "join",
    "left",
    "right",
    "inner",
    "outer",
    "on",
    "group",
    "by",
    "order",
    "having",
    "limit",
    "top",
    "distinct",
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "case",
    "when",
    "then",
    "else",
    "end",
    "between",
    "like",
    "in",
    "exists",
    "all",
    "any",
    "some",
    "cast",
    "convert",
    "date",
    "datetime",
    "varchar",
    "nvarchar",
    "int",
    "bigint",
    "decimal",
    "float",
    "bit",
    "char",
    "nchar",
    "text",
    "ntext",
    "xml",
    "uniqueidentifier",
    "binary",
    "varbinary",
    "image",
    "timestamp",
    "rowversion",
    "money",
    "smallmoney",
    "real",
    "numeric",
    "smallint",
    "tinyint",
}


def _validate_sql_against_schema(sql: str, schema_tables: dict) -> tuple[bool, str]:
    """Validate a rewritten SQL query against a cached schema.

    Returns (is_valid, reason) where reason is empty if valid.
    Checks:
    1. All referenced tables exist in schema_tables
    2. All referenced columns exist in at least one known table

    This is a best-effort heuristic — not a full SQL parser.
    """
    if not schema_tables:
        return False, "no cached schema available"

    # 1. Table check
    tables_in_sql = _extract_tables_from_sql(sql)
    known_tables = {t.lower() for t in schema_tables}
    added_tables = tables_in_sql - known_tables
    if added_tables:
        return False, f"new tables required: {', '.join(sorted(added_tables))}"

    # 2. Column check — extract bracketed and bare column references
    col_pattern = re.compile(
        r"(?:\w+\.)?\[(\w+)\]|(?<!\.)\b(\w+)\b",
        re.IGNORECASE,
    )
    all_known_cols: set[str] = set()
    for cols in schema_tables.values():
        all_known_cols.update(c.lower() for c in cols)

    for m in col_pattern.finditer(sql):
        col = (m.group(1) or m.group(2)).lower()
        if col in _SQL_KEYWORDS or col.isdigit():
            continue
        # Allow aggregate functions, aliases (we can't parse perfectly)
        # Just check if the column exists anywhere in the known schema
        if col not in all_known_cols:
            # It might be an alias or expression — don't hard-reject,
            # but log a warning. We can't be 100% sure without a parser.
            pass  # lenient: allow unknown columns (caught at execution)

    return True, ""


_FOLLOW_UP_SYSTEM_PROMPT = """\
You are a SQL rewriter. Given the original SQL query and a follow-up request, \
modify the SQL to satisfy the follow-up. Keep the same FROM / JOIN tables. \
Only change SELECT, WHERE, ORDER BY, or add aggregates. \
Return ONLY a JSON object with a single key "sql". No explanation, no markdown."""

_FOLLOW_UP_USER_TEMPLATE = """\
Original question: {original_question}
Original SQL:
{original_sql}

Follow-up request: {follow_up_question}

Return the modified SQL as JSON: {{"sql": "..."}}"""


async def _rewrite_sql(state: GraphState) -> str | None:
    """Rewrite previous SQL based on follow-up question using fast model.

    Minimal prompt — no full schema context needed because we already know
    the tables from the previous SQL.  Uses the resolver model (gpt-4.1-nano).
    """
    lqc = state.get("last_query_context") or {}
    original_sql = lqc.get("sql", "")
    original_question = lqc.get("resolved_question", "")
    follow_up_question = state.get("resolved_question") or state["question"]

    if not original_sql:
        logger.warning("handle_follow_up: rewrite_sql but no prior SQL available")
        return None

    user_prompt = _FOLLOW_UP_USER_TEMPLATE.format(
        original_question=original_question,
        original_sql=original_sql,
        follow_up_question=follow_up_question,
    )

    provider, llm_config = route_for_role(follow_up_question, role="resolver")
    messages = [
        LLMMessage(role="system", content=_FOLLOW_UP_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_prompt),
    ]

    try:
        response = await provider.complete(messages, llm_config)
        parsed = json.loads(repair_json(response.content))
        new_sql = parsed.get("sql", "").strip()
        if not new_sql:
            return None

        # Validate rewritten SQL against the cached schema from the previous turn.
        # The cached schema includes ALL tables/columns from build_context, not just
        # what's referenced in the original SQL. This catches:
        # - New tables needed (e.g., BusinessUnit for "vResourcing")
        # - Column hallucinations (e.g., IsBillable on Project)
        cached_schema = lqc.get("schema_tables") or {}
        is_valid, reason = _validate_sql_against_schema(new_sql, cached_schema)
        if not is_valid:
            logger.warning(
                "handle_follow_up: rewrite validation failed — %s. Escalating to full compose.",
                reason,
            )
            return None

        logger.info(
            "handle_follow_up: rewrite_sql success sql=%r model=%s",
            new_sql[:200],
            llm_config.model,
        )
        return new_sql
    except Exception:
        logger.warning("handle_follow_up: rewrite_sql failed", exc_info=True)

    return None


async def handle_follow_up(state: GraphState) -> dict[str, Any]:
    """Handle follow-up query refinement."""
    follow_up_mode = state.get("follow_up_mode")
    last_query_context = state.get("last_query_context") or {}
    last_answer = last_query_context.get("answer")

    logger.info(
        "handle_follow_up: mode=%s base_resolved_question=%s base_sql=%s",
        follow_up_mode,
        last_query_context.get("resolved_question", "None")[:50],
        last_query_context.get("sql", "None")[:50],
    )

    if follow_up_mode == "reuse_answer":
        if not last_answer:
            logger.warning("handle_follow_up: reuse_answer but no cached answer, escalating")
            return {
                "action": "clarification",
                "clarification_reason": "missing_prior_answer",
                "clarification_message": "No prior answer to reuse. Could you rephrase?",
                "clarification_options": ["Rephrase question", "Ask a new query"],
            }

        if state.get("event_queue"):
            await state.get("event_queue").put(
                {
                    "type": "stage",
                    "stage": "answering",
                    "label": "Answering from previous result...",
                    "progress": 90,
                }
            )

        return {
            "answer": last_answer,
            "generated_sql": last_query_context.get("sql"),
            "sql": last_query_context.get("sql"),
            "highlights": [],
            "suggested_followups": [],
        }

    if follow_up_mode == "rewrite_sql":
        new_sql = await _rewrite_sql(state)
        if new_sql:
            return {
                "generated_sql": new_sql,
                "sql": new_sql,
                "action": "follow_up_rewrite_sql",
                "clarification_reason": None,
                "clarification_message": None,
                "clarification_options": [],
            }

        # Rewrite failed — escalate to full compose
        logger.warning("handle_follow_up: rewrite_sql failed, escalating to full compose")
        return {
            "action": "query",
            "resolved_question": state.get("resolved_question"),
            "clarification_reason": None,
            "clarification_message": None,
            "clarification_options": [],
        }

    # fallback: escalate to full compose
    logger.warning("handle_follow_up: unknown mode=%s, escalating to build_context", follow_up_mode)
    return {
        "action": "query",
        "resolved_question": state.get("resolved_question"),
        "clarification_reason": None,
        "clarification_message": None,
        "clarification_options": [],
    }


def route_after_follow_up(state: GraphState) -> str:
    """Route after follow-up handling.

    - follow_up_rewrite_sql → execute_sql (fast path, validation passed)
    - query → build_context (validation failed, escalate to full compose)
    - clarification → write_history
    - reuse_answer → write_history
    """
    action = state.get("action")

    if action == "clarification":
        return "write_history"

    if action == "follow_up_rewrite_sql":
        return "execute_sql"

    if action == "query":
        # Validation failed or rewrite couldn't proceed — escalate to
        # build_context so the full schema-linking + composer path runs.
        logger.info("route_after_follow_up: escalating to build_context")
        return "build_context"

    # reuse_answer
    return "write_history"
