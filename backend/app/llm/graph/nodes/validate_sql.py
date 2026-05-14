"""validate_sql node — static SQL validation against the linked schema.

Validates generated_sql against the schema_tables map produced by
build_context_node. Sets validation_issues to an empty list when the SQL is
valid, or a list of issue strings when it is not.

Routing:
  valid          → execute_sql
  schema_mismatch → rebuild_context (fetch missing tables, then re-validate)
  invalid        → handle_error  (triggers the correction + retry cycle)
"""

import logging
import re
from typing import Any

from app.llm.agents.sql_validator import SQLValidatorAgent, ValidationStatus
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)


def _extract_missing_tables(issues: list[str]) -> list[str]:
    """Extract table names from schema mismatch issues like "Table 'X' not found"."""
    tables = []
    for issue in issues:
        match = re.search(r"Table '([^']+)' not found", issue)
        if match:
            tables.append(match.group(1))
    return tables


async def validate_sql(state: GraphState) -> dict[str, Any]:
    """Validate generated_sql against the schema."""
    generated_sql = state.get("generated_sql") or ""
    schema_tables: dict = state.get("schema_tables") or {}

    validator = SQLValidatorAgent()
    validation = await validator.validate(generated_sql, schema_tables)

    if validation.status == ValidationStatus.VALID:
        logger.info("validate_sql: valid sql=%r", generated_sql[:80])
        return {
            "validation_issues": [],
            "needs_context_rebuild": False,  # Clear stale rebuild flag
            "force_include_tables": [],  # Clear stale forced tables
        }

    # FIX #2: Detect schema mismatch and extract missing tables for context rebuild
    missing_tables = _extract_missing_tables(validation.issues)
    if validation.status == ValidationStatus.SCHEMA_MISMATCH and missing_tables:
        logger.info(
            "validate_sql: schema mismatch, missing tables=%r - will rebuild context",
            missing_tables,
        )
        return {
            "validation_issues": list(validation.issues),
            "needs_context_rebuild": True,
            "force_include_tables": missing_tables,
        }

    logger.info("validate_sql: invalid issues=%r sql=%r", validation.issues, generated_sql[:80])
    return {"validation_issues": list(validation.issues)}


def route_after_validate(state: GraphState) -> str:
    """Route to execute_sql, rebuild_context, or handle_error based on validation result."""
    if not state.get("validation_issues"):
        return "execute_sql"
    # FIX #2: Schema mismatch with missing tables → rebuild context with those tables
    if state.get("needs_context_rebuild") and state.get("force_include_tables"):
        logger.info(
            "route_after_validate: schema mismatch, missing tables=%r - routing to rebuild_context",
            state.get("force_include_tables"),
        )
        return "rebuild_context"
    return "handle_error"
