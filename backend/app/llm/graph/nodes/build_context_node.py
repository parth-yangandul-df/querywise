"""build_context_node — schema linking, semantic retrieval, and prompt assembly.

Runs build_context() to resolve relevant tables, glossary terms, metrics,
knowledge chunks, and sample queries via vector + keyword search. Applies
RBAC scope constraint blocks when resource_id / employee_id is set.

Stores in state:
  prompt_context       — scope-injected text to pass to the SQL composer
  schema_tables        — {TABLE_NAME: [COL, ...]} used by the SQL validator
  question_embedding   — reused by similarity_check to skip the LLM composer
"""

import logging
import uuid
from typing import Any

from app.core.metrics import timed_node
from app.llm.graph.state import GraphState
from app.llm.stream_stages import BUILDING_CONTEXT, emit
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


@timed_node("build_context")
async def build_context_node(state: GraphState) -> dict[str, Any]:
    """Run schema linking and context assembly for the current question."""
    resolved_question = state.get("resolved_question") or state["question"]
    connection_id = uuid.UUID(state["connection_id"])
    db_factory = state["db"]
    resource_id = state.get("resource_id")
    employee_id = state.get("employee_id")

    if state.get("event_queue"):
        await state["event_queue"].put(emit(BUILDING_CONTEXT))

    # connector_type is already in state — no extra DB round-trip needed
    async with db_factory() as db:
        context = await build_context(
            db, connection_id, resolved_question, dialect=state["connector_type"]
        )

        if context.sample_queries:
            for sq in context.sample_queries:
                logger.debug(
                    "build_context_node: sample_query q=%r sql=%r",
                    sq.natural_language,
                    sq.sql_query[:100],
                )
            logger.info(
                "build_context_node: sample_queries count=%d",
                len(context.sample_queries),
            )

        # Inject scope constraints only for 'user' role.
        # admin has no constraints at all; manager has resource_id/employee_id set
        # for identification purposes but is NOT subject to personal-data scope limits.
        prompt_context = context.prompt_context
        user_role = state.get("user_role")
        if user_role == "user":
            if resource_id is not None:
                prompt_context = (
                    _SCOPE_CONSTRAINT_TEMPLATE.format(resource_id=resource_id) + prompt_context
                )
            if employee_id is not None:
                prompt_context = (
                    _EMPLOYEE_ID_SCOPE_TEMPLATE.format(employee_id=employee_id) + prompt_context
                )

        schema_tables = {
            lt.table.table_name.upper(): [c.column_name.upper() for c in lt.columns]
            for lt in context.tables
        }

        logger.info(
            "build_context_node: resolved=%r tables=%d embedding=%s",
            resolved_question[:80],
            len(context.tables),
            context.question_embedding is not None,
        )

        return {
            "prompt_context": prompt_context,
            "schema_tables": schema_tables,
            "question_embedding": context.question_embedding,
        }
