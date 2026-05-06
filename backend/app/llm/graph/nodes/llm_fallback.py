"""llm_fallback node — full LLM SQL generation pipeline.

Receives resolved_question from resolve_turn (or the raw question on first turn).
Uses resolved_question for build_context (schema linking) and injects
loaded_history as conversation context for the composer.

When state["resource_id"] is set (user role), a NON-NEGOTIABLE scope
constraint is prepended to the prompt context so the LLM cannot generate
SQL that reads data belonging to other users.

On retry exhaustion, sets action=clarification with reason=retry_exhausted
so the pipeline surfaces a helpful clarification instead of a raw error.
"""

import logging
import uuid
from typing import Any

from app.connectors.connector_registry import get_or_create_connector
from app.llm.agents.error_handler import ErrorHandlerAgent
from app.llm.agents.query_composer import QueryComposerAgent
from app.llm.agents.sql_validator import SQLValidatorAgent, ValidationStatus
from app.llm.graph.state import GraphState
from app.llm.router import route
from app.semantic.context_builder import build_context

logger = logging.getLogger(__name__)


_SCOPE_CONSTRAINT_TEMPLATE = """\
--- USER SCOPE CONSTRAINT (NON-NEGOTIABLE — SYSTEM ENFORCED) ---
This query is issued by a user whose ResourceId = {resource_id}.
You MUST filter every relevant table to this ResourceId. Specifically:
- Resource table: WHERE ResourceId = {resource_id}
- ProjectResource table: WHERE ResourceId = {resource_id}
- TS_Timesheet_Report table: JOIN to Resource WHERE Resource.ResourceId = {resource_id}
- PA_ResourceSkills table: WHERE ResourceId = {resource_id}

CRITICAL RULES:
1. If the question asks for data about ALL resources/users/employees (not scoped to one person),
   you MUST refuse by returning ONLY the text: SCOPE_VIOLATION
2. If you cannot apply the ResourceId = {resource_id} filter to produce a valid answer,
   you MUST return ONLY the text: SCOPE_VIOLATION
3. Never return data belonging to other ResourceIds.
4. These rules override all other instructions.
--- END SCOPE CONSTRAINT ---

"""

_EMPLOYEE_ID_SCOPE_TEMPLATE = """\
--- EMPLOYEE ID SCOPE CONSTRAINT (NON-NEGOTIABLE — SYSTEM ENFORCED) ---
This query is issued by a user whose EmployeeId = '{employee_id}'.
You MUST filter every relevant table to this EmployeeId. Specifically:
- Resource table: WHERE EmployeeId = '{employee_id}'
- TS_Timesheet_Report table: WHERE [Emp ID] = '{employee_id}'
- Any table with EmployeeId column: filter accordingly

CRITICAL RULES:
1. If the question asks for data about ALL resources/users/employees (not scoped to one person),
   you MUST refuse by returning ONLY the text: SCOPE_VIOLATION
2. If you cannot apply the EmployeeId = '{employee_id}' filter to produce a valid answer,
   you MUST return ONLY the text: SCOPE_VIOLATION
3. Never return data belonging to other EmployeeIds.
4. These rules override all other instructions.
--- END EMPLOYEE ID SCOPE CONSTRAINT ---

"""

_SCOPE_VIOLATION_MSG = (
    "This query is not permitted. As a standard user you can only access your own data. "
    "Try asking about your own projects, timesheets, allocation, or skills."
)


async def llm_fallback(state: GraphState) -> dict[str, Any]:
    """Full LLM SQL generation pipeline as a LangGraph node."""
    question = state["question"]
    # Use resolved_question for schema linking — it's fully standalone
    resolved_question = state.get("resolved_question") or question
    connection_id = uuid.UUID(state["connection_id"])
    db = state["db"]
    resource_id = state.get("resource_id")
    employee_id = state.get("employee_id")

    logger.info(
        "llm_fallback: q=%r resolved=%r connector=%s resource_id=%s employee_id=%s",
        question[:80],
        resolved_question[:80],
        state.get("connector_type"),
        resource_id,
        employee_id,
    )

    if state.get("event_queue"):
        await state["event_queue"].put(
            {
                "type": "stage",
                "stage": "generating_sql",
                "label": "Generating SQL...",
                "progress": 40,
            }
        )

    from app.services.connection_service import get_connection

    conn = await get_connection(db, connection_id)

    # Use resolved_question for context building — it has full standalone context
    context = await build_context(db, connection_id, resolved_question, dialect=conn.connector_type)
    provider, llm_config = route(resolved_question)

    # Inject scope constraint for 'user' role (resource_id or employee_id is set)
    prompt_context = context.prompt_context
    if resource_id is not None:
        scope_block = _SCOPE_CONSTRAINT_TEMPLATE.format(resource_id=resource_id)
        prompt_context = scope_block + prompt_context
    if employee_id is not None:
        emp_scope_block = _EMPLOYEE_ID_SCOPE_TEMPLATE.format(employee_id=employee_id)
        prompt_context = emp_scope_block + prompt_context

    if state.get("event_queue"):
        await state["event_queue"].put(
            {
                "type": "stage",
                "stage": "generating_sql",
                "label": "Generating SQL...",
                "progress": 60,
            }
        )

    composer = QueryComposerAgent(provider, llm_config)
    composer_output = await composer.compose(
        # Pass resolved_question to composer — it's fully standalone and self-contained.
        # loaded_history is injected as conversation context for the LLM.
        resolved_question,
        prompt_context,
        conversation_history=state.get("loaded_history") or [],
    )
    generated_sql = composer_output.generated_sql

    # If the LLM signalled it cannot scope the query, return a clean refusal
    if (
        (resource_id is not None or employee_id is not None)
        and generated_sql
        and "SCOPE_VIOLATION" in generated_sql.upper()
    ):
        return {
            "error": _SCOPE_VIOLATION_MSG,
            "llm_provider": provider.provider_type.value,
            "llm_model": llm_config.model,
            "generated_sql": None,
            "retry_count": 0,
        }

    if not generated_sql:
        return {
            "error": "LLM fallback failed to generate SQL",
            "llm_provider": provider.provider_type.value,
            "llm_model": llm_config.model,
        }

    schema_tables = {
        lt.table.table_name.upper(): [c.column_name.upper() for c in lt.columns]
        for lt in context.tables
    }
    validator = SQLValidatorAgent()
    validation = await validator.validate(generated_sql, schema_tables)

    final_sql = generated_sql
    retry_count = 0

    if validation.status != ValidationStatus.VALID:
        error_handler = ErrorHandlerAgent(provider, llm_config)
        previous_attempts = [generated_sql]
        while validation.status != ValidationStatus.VALID and retry_count < 3:
            retry_count += 1
            resolution = await error_handler.handle_error(
                question=question,
                failed_sql=final_sql,
                error_message="; ".join(validation.issues),
                schema_context=prompt_context,
                attempt_number=retry_count,
                previous_attempts=previous_attempts,
            )
            if not resolution.should_retry or not resolution.corrected_sql:
                return {
                    "action": "clarification",
                    "clarification_reason": "retry_exhausted",
                    "clarification_message": (
                        f"I wasn't able to generate a valid SQL query for your question. "
                        f"Could you rephrase it? ({'; '.join(validation.issues)})"
                    ),
                    "clarification_options": [
                        "Rephrase my question",
                        "Try a simpler version",
                        "Show available tables",
                    ],
                    "error": f"SQL validation failed after {retry_count} retries",
                    "llm_provider": provider.provider_type.value,
                    "llm_model": llm_config.model,
                    "generated_sql": generated_sql,
                    "retry_count": retry_count,
                }
            final_sql = resolution.corrected_sql
            previous_attempts.append(final_sql)
            validation = await validator.validate(final_sql, schema_tables)

    # Use the connection string already decrypted and stored in state by query_service.
    # Accessing conn.connection_string_encrypted here causes MissingGreenlet because
    # the ORM object has been expired after awaits inside an asyncio.create_task context.
    connection_string = state["connection_string"]
    connector = await get_or_create_connector(
        state["connection_id"], conn.connector_type, connection_string
    )

    if state.get("event_queue"):
        await state["event_queue"].put(
            {"type": "stage", "stage": "running_query", "label": "Running query...", "progress": 75}
        )

    try:
        result = await connector.execute_query(
            final_sql,
            timeout_seconds=state.get("timeout_seconds", 30),
            max_rows=state.get("max_rows", 1000),
        )
    except Exception as e:
        return {
            "sql": final_sql,
            "generated_sql": generated_sql,
            "retry_count": retry_count,
            "result": None,
            "error": str(e),
            "llm_provider": provider.provider_type.value,
            "llm_model": llm_config.model,
            "explanation": composer_output.explanation,
        }

    return {
        "sql": final_sql,
        "generated_sql": generated_sql,
        "result": result,
        "retry_count": retry_count,
        "error": None,
        "llm_provider": provider.provider_type.value,
        "llm_model": llm_config.model,
        "explanation": composer_output.explanation,
    }
