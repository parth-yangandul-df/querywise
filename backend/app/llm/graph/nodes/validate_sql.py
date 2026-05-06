"""validate_sql node — static SQL validation against the linked schema.

Validates generated_sql against the schema_tables map produced by
build_context_node. Sets validation_issues to an empty list when the SQL is
valid, or a list of issue strings when it is not.

Routing:
  valid   → execute_sql
  invalid → handle_error  (triggers the correction + retry cycle)
"""

import logging
from typing import Any

from app.llm.agents.sql_validator import SQLValidatorAgent, ValidationStatus
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)


async def validate_sql(state: GraphState) -> dict[str, Any]:
    """Validate generated_sql against the schema."""
    generated_sql = state.get("generated_sql") or ""
    schema_tables: dict = state.get("schema_tables") or {}

    validator = SQLValidatorAgent()
    validation = await validator.validate(generated_sql, schema_tables)

    if validation.status == ValidationStatus.VALID:
        logger.info("validate_sql: valid sql=%r", generated_sql[:80])
        return {"validation_issues": []}

    logger.info("validate_sql: invalid issues=%r sql=%r", validation.issues, generated_sql[:80])
    return {"validation_issues": list(validation.issues)}


def route_after_validate(state: GraphState) -> str:
    """Route to execute_sql when valid, or to handle_error when issues exist."""
    if not state.get("validation_issues"):
        return "execute_sql"
    return "handle_error"
