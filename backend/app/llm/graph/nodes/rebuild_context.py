"""rebuild_context node — rebuilds semantic context with forced table inclusion.

Triggered when validation detects schema mismatches (missing tables).
Fetches missing tables and adds them to context, then re-routes to validation.
"""

import logging
import uuid
from typing import Any

from app.core.metrics import timed_node
from app.llm.graph.state import GraphState
from app.semantic.context_builder import build_context
from app.semantic.context_builder import _fetch_tables_by_names as fetch_tables_by_names
from app.semantic.prompt_assembler import assemble_prompt

logger = logging.getLogger(__name__)


@timed_node("rebuild_context")
async def rebuild_context(state: GraphState) -> dict[str, Any]:
    """Rebuild semantic context including tables that caused schema mismatch.

    This node is triggered when validate_sql detects missing tables in the generated SQL.
    It fetches the missing tables and adds them to the existing context, then
    returns to validate_sql for re-validation.
    """
    resolved_question = state.get("resolved_question") or state["question"]
    force_tables = state.get("force_include_tables", [])
    connection_id = uuid.UUID(state["connection_id"])
    db_factory = state["db"]

    logger.info(
        "rebuild_context: adding missing tables=%r question=%r",
        force_tables,
        resolved_question[:60],
    )

    try:
        async with db_factory() as db:
            # Step 1: Build base context (same as build_context_node)
            context = await build_context(
                db, connection_id, resolved_question, dialect=state["connector_type"]
            )

            # Step 2: Fetch the missing tables that caused validation failure
            missing_tables = await fetch_tables_by_names(db, connection_id, force_tables)

            # Step 3: Add missing tables to context (avoid duplicates)
            existing_table_names = {lt.table.table_name.upper() for lt in context.tables}
            added_count = 0
            for lt in missing_tables:
                if lt.table.table_name.upper() not in existing_table_names:
                    context.tables.append(lt)
                    existing_table_names.add(lt.table.table_name.upper())
                    added_count += 1

            # Step 4: Rebuild schema_tables dict with all tables
            schema_tables = {
                lt.table.table_name.upper(): [c.column_name.upper() for c in lt.columns]
                for lt in context.tables
            }

            logger.info(
                "rebuild_context: success - total tables=%d, added=%d",
                len(context.tables),
                added_count,
            )

            return {
                "prompt_context": context.prompt_context,  # Original prompt still valid
                "schema_tables": schema_tables,  # Updated with missing tables
                "needs_context_rebuild": False,  # Clear the flag
                "force_include_tables": [],  # Clear to prevent stale rebuild routing
                "validation_issues": [],  # Clear so validate_sql re-evaluates from scratch
            }

    except Exception as e:
        logger.warning("rebuild_context: failed - %s", e, exc_info=True)
        # On failure, fall back to error handling
        return {
            "error": f"Failed to rebuild context with missing tables: {e}",
            "needs_context_rebuild": False,
        }


def route_after_rebuild(state: GraphState) -> str:
    """Route back to validate_sql after context rebuild, or to handle_error on failure."""
    if state.get("error"):
        return "handle_error"
    # Re-validate with new context (missing tables now included)
    return "validate_sql"
