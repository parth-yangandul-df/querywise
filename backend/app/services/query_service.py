"""Query Service — orchestrates the full NL → SQL → results pipeline."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base_connector import QueryResult
from app.connectors.connector_registry import get_or_create_connector
from app.core.exceptions import AppError, SQLSafetyError
from app.db.models.chat_session import ChatSession
from app.db.models.query_history import QueryExecution
from app.db.models.user import User
from app.llm.agents.query_composer import QueryComposerAgent
from app.llm.agents.result_interpreter import ResultInterpreterAgent, format_single_value_result
from app.llm.graph.graph import get_compiled_graph
from app.llm.graph.state import GraphState
from app.llm.router import route_for_role
from app.semantic.context_builder import build_context
from app.services.connection_service import get_connection, get_decrypted_connection_string
from app.utils.sql_sanitizer import check_sql_safety

logger = logging.getLogger(__name__)


async def execute_nl_query(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question: str,
    session_id: uuid.UUID | None = None,
    current_user: User | None = None,
    clear_context: bool = False,
    event_queue=None,
) -> dict:
    """Full pipeline: NL question → LangGraph → results.

    The backend owns conversation history — loaded from QueryExecution by
    the load_history graph node. The frontend only provides session_id.
    """
    conn = await get_connection(db, connection_id)
    connection_string = get_decrypted_connection_string(conn)

    initial_state: GraphState = {
        "question": question,
        "connection_id": str(connection_id),
        "connector_type": conn.connector_type,
        "connection_string": connection_string,
        "timeout_seconds": conn.max_query_timeout_seconds,
        "max_rows": conn.max_rows,
        "db": db,
        "session_id": str(session_id) if session_id and not clear_context else None,
        # Auth / RBAC
        "user_id": str(current_user.id) if current_user else None,
        "user_role": current_user.role if current_user else None,
        "resource_id": current_user.resource_id if current_user else None,
        "employee_id": current_user.employee_id if current_user else None,
        # History — loaded by load_history node
        "loaded_history": [],
        "last_generated_sql": None,
        "last_result_columns": None,
        "last_result_preview_rows": None,
        # Turn resolution defaults
        "action": None,
        "resolved_question": None,
        "clarification_reason": None,
        "clarification_message": None,
        "clarification_options": [],
        # Execution defaults
        "sql": None,
        "result": None,
        "generated_sql": None,
        "retry_count": 0,
        "explanation": None,
        "llm_provider": None,
        "llm_model": None,
        # Interpretation defaults
        "answer": None,
        "highlights": [],
        "suggested_followups": [],
        # History write defaults
        "execution_id": None,
        "execution_time_ms": None,
        # Error propagation
        "error": None,
        # Streaming — injected by SSE endpoint, None on blocking path
        "event_queue": event_queue,
    }

    final_state = await get_compiled_graph().ainvoke(initial_state)

    # Auto-set session title from first question
    if session_id and not clear_context:
        session = await db.get(ChatSession, session_id)
        if session and session.title == "New Chat":
            session.title = question[:100].strip()
            session.updated_at = datetime.now(UTC)
            await db.flush()
        elif session:
            session.updated_at = datetime.now(UTC)
            await db.flush()

    action = final_state.get("action") or "query"

    # Clarification turns don't have SQL/result — raise as AppError only for failed query turns
    if action == "clarification":
        return {
            "id": final_state.get("execution_id"),
            "question": question,
            "turn_type": "clarification",
            "clarification_message": final_state.get("clarification_message"),
            "clarification_options": final_state.get("clarification_options", []),
            "generated_sql": None,
            "final_sql": None,
            "explanation": None,
            "columns": [],
            "column_types": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": None,
            "truncated": False,
            "summary": final_state.get("answer"),
            "highlights": [],
            "suggested_followups": [],
            "llm_provider": final_state.get("llm_provider"),
            "llm_model": final_state.get("llm_model"),
            "retry_count": final_state.get("retry_count", 0),
        }

    if final_state.get("error") and final_state.get("result") is None:
        raise AppError(final_state["error"], status_code=422)

    result: QueryResult = final_state["result"]

    return {
        "id": final_state.get("execution_id"),
        "question": question,
        "turn_type": action,
        "clarification_message": None,
        "clarification_options": [],
        "generated_sql": final_state.get("generated_sql"),
        "final_sql": final_state.get("sql"),
        "explanation": final_state.get("explanation"),
        "columns": result.columns if result else [],
        "column_types": result.column_types if result else [],
        "rows": _serialize_rows(result.rows) if result else [],
        "row_count": result.row_count if result else 0,
        "execution_time_ms": result.execution_time_ms if result else None,
        "truncated": result.truncated if result else False,
        "summary": final_state.get("answer"),
        "highlights": final_state.get("highlights", []),
        "suggested_followups": final_state.get("suggested_followups", []),
        "llm_provider": final_state.get("llm_provider"),
        "llm_model": final_state.get("llm_model"),
        "retry_count": final_state.get("retry_count", 0),
    }


async def generate_sql_only(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question: str,
) -> dict:
    """Generate SQL without executing it."""
    conn = await get_connection(db, connection_id)
    context = await build_context(db, connection_id, question, dialect=conn.connector_type)
    provider, llm_config = route_for_role(question)
    composer = QueryComposerAgent(provider, llm_config)
    output = await composer.compose(question, context.prompt_context)

    return {
        "generated_sql": output.generated_sql,
        "explanation": output.explanation,
        "confidence": output.confidence,
        "tables_used": output.tables_used,
        "assumptions": output.assumptions,
    }


async def execute_raw_sql(
    db: AsyncSession,
    connection_id: uuid.UUID,
    sql: str,
    original_question: str | None = None,
) -> dict:
    """Execute user-provided SQL directly (no LLM generation).

    Steps:
    1. Safety check (block DDL/DML)
    2. Execute query via connector
    3. Save to history

    No LLM retry on error — the user can fix the SQL manually.
    """
    # Step 1: Safety check
    safety_issues = check_sql_safety(sql)
    if safety_issues:
        raise SQLSafetyError("; ".join(safety_issues))

    conn = await get_connection(db, connection_id)
    connection_string = get_decrypted_connection_string(conn)

    # Step 2: Execute query
    connector = await get_or_create_connector(
        str(connection_id), conn.connector_type, connection_string
    )

    try:
        result = await connector.execute_query(
            sql,
            timeout_seconds=conn.max_query_timeout_seconds,
            max_rows=conn.max_rows,
        )
    except Exception:
        # Log internally - never expose to client
        logger.error("Query execution failed: %s", exc_info=True)
        execution = QueryExecution(
            connection_id=connection_id,
            natural_language=original_question or "(manual SQL)",
            generated_sql=None,
            final_sql=sql,
            execution_status="error",
            error_message="Query execution failed",
            retry_count=0,
        )
        db.add(execution)
        await db.flush()
        raise AppError("Query execution failed. Please try again.")

    # Step 3: Interpret results (LLM summary + follow-ups)
    summary = None
    highlights = []
    followups = []
    llm_provider_name = "manual"
    llm_model_name = "manual"

    question_text = original_question or "(manual SQL)"

    if result.rows:
        single_value = format_single_value_result(result.rows)
        if single_value is not None:
            summary = single_value
        else:
            try:
                provider, llm_config = route_for_role(question_text, role="interpreter")
                interpreter = ResultInterpreterAgent(provider, llm_config)
                interpretation = await interpreter.interpret(
                    question=question_text,
                    sql=sql,
                    columns=result.columns,
                    rows=result.rows,
                    row_count=result.row_count,
                )
                summary = interpretation.summary
                highlights = interpretation.highlights
                llm_provider_name = provider.provider_type.value
                llm_model_name = llm_config.model
            except Exception:
                pass  # Interpretation is best-effort; don't fail the query

    # Step 4: Save to history
    execution = QueryExecution(
        connection_id=connection_id,
        natural_language=question_text,
        generated_sql=None,
        final_sql=sql,
        execution_status="success",
        row_count=result.row_count,
        execution_time_ms=result.execution_time_ms,
        retry_count=0,
        result_summary=summary,
        llm_provider=llm_provider_name,
        llm_model=llm_model_name,
    )
    db.add(execution)
    await db.flush()

    return {
        "id": execution.id,
        "question": question_text,
        "generated_sql": sql,
        "final_sql": sql,
        "explanation": "User-provided SQL executed directly.",
        "columns": result.columns,
        "column_types": result.column_types,
        "rows": _serialize_rows(result.rows),
        "row_count": result.row_count,
        "execution_time_ms": result.execution_time_ms,
        "truncated": result.truncated,
        "summary": summary,
        "highlights": highlights,
        "suggested_followups": [],
        "llm_provider": llm_provider_name,
        "llm_model": llm_model_name,
        "retry_count": 0,
    }


def _serialize_rows(rows: list[list]) -> list[list]:
    """Ensure all row values are JSON-serializable."""
    serialized = []
    for row in rows:
        serialized_row = []
        for val in row:
            if hasattr(val, "isoformat"):
                serialized_row.append(val.isoformat())
            elif isinstance(val, bytes):
                serialized_row.append(val.hex())
            else:
                serialized_row.append(val)
        serialized.append(serialized_row)
    return serialized
