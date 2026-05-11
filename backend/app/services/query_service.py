"""Query Service — orchestrates the full NL → SQL → results pipeline."""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.base_connector import QueryResult
from app.connectors.connector_registry import get_or_create_connector
from app.core.exceptions import AppError, SQLSafetyError
from app.core.metrics import CACHE_HITS, COALESCE_HITS, PIPELINE_DURATION
from app.core.mlflow_tracing import trace_query_pipeline
from app.core.query_cache import (
    get_cached_sql,
    publish_coalesce_result,
    set_cached_sql,
    try_coalesce_leader,
    wait_for_coalesce_result,
)
from app.db.models.chat_session import ChatSession
from app.db.models.query_history import QueryExecution
from app.db.models.user import User
from app.db.session import async_session_factory
from app.llm.agents.query_composer import QueryComposerAgent
from app.llm.agents.result_interpreter import format_single_value_result
from app.llm.graph.graph import get_compiled_graph
from app.llm.graph.state import GraphState
from app.llm.router import route_for_role
from app.semantic.context_builder import build_context
from app.services.connection_service import get_connection, get_decrypted_connection_string
from app.utils.sql_sanitizer import check_sql_safety

logger = logging.getLogger(__name__)


async def _execute_cached_pipeline(
    connection_id: uuid.UUID,
    connection_string: str,
    connector_type: str,
    sql: str,
    question: str,
    session_id: uuid.UUID | None,
    current_user: User | None,
    timeout_seconds: int,
    max_rows: int,
    event_queue=None,
) -> dict:
    """Execute a cached SQL query, interpret results, write history, and return."""
    connector = await get_or_create_connector(str(connection_id), connector_type, connection_string)

    if event_queue:
        await event_queue.put(
            {
                "type": "stage",
                "stage": "running_query",
                "label": "Running query...",
                "progress": 75,
            }
        )

    result = await connector.execute_query(sql, timeout_seconds=timeout_seconds, max_rows=max_rows)

    # Format result — same minimal approach as the graph path.
    # Single-value results show the value; multi-row shows row count.
    # No LLM interpreter — the frontend already renders the data table.
    summary = None
    highlights = []
    suggested_followups = []
    llm_provider_name = "cache"
    llm_model_name = "cache"

    if result.rows:
        single_value = format_single_value_result(result.rows)
        if single_value is not None:
            summary = single_value
        else:
            summary = f"{result.row_count} row(s) returned"

    # Write history in a standalone session
    try:
        async with async_session_factory() as db:
            execution = QueryExecution(
                connection_id=connection_id,
                session_id=session_id,
                user_id=current_user.id if current_user else None,
                natural_language=question,
                generated_sql=None,
                final_sql=sql,
                execution_status="success",
                row_count=result.row_count,
                execution_time_ms=result.execution_time_ms,
                retry_count=0,
                result_summary=summary,
                llm_provider=llm_provider_name,
                llm_model=llm_model_name,
                turn_type="query",
                result_columns=result.columns,
                result_preview_rows=_serialize_rows(result.rows[:20]),
            )
            db.add(execution)
            await db.commit()
            execution_id = execution.id
    except Exception:
        logger.warning("Cached query history write failed — non-critical", exc_info=True)
        execution_id = None

    return {
        "id": execution_id,
        "question": question,
        "turn_type": "query",
        "result_status": "success" if result.rows else "empty",
        "clarification_message": None,
        "clarification_options": [],
        "generated_sql": sql,
        "final_sql": sql,
        "explanation": None,
        "columns": result.columns,
        "column_types": result.column_types,
        "rows": _serialize_rows(result.rows),
        "row_count": result.row_count,
        "execution_time_ms": result.execution_time_ms,
        "truncated": result.truncated,
        "summary": summary,
        "highlights": highlights,
        "suggested_followups": suggested_followups,
        "llm_provider": llm_provider_name,
        "llm_model": llm_model_name,
        "retry_count": 0,
    }


async def execute_nl_query(
    connection_id: uuid.UUID,
    question: str,
    session_id: uuid.UUID | None = None,
    current_user: User | None = None,
    clear_context: bool = False,
    event_queue=None,
    skip_cache: bool = False,
) -> dict:
    """Full pipeline: NL question → LangGraph → results.

    The backend owns conversation history — loaded from QueryExecution by
    the load_history graph node. The frontend only provides session_id.

    This function manages its own DB session to avoid concurrency conflicts
    with FastAPI's dependency-injected sessions in streaming endpoints.
    """
    async with async_session_factory() as db:
        conn = await get_connection(db, connection_id)
    connection_string = get_decrypted_connection_string(conn)
    user_role = current_user.role if current_user else None
    resource_id = current_user.resource_id if current_user else None
    employee_id = current_user.employee_id if current_user else None

    # ── Request Coalescing ────────────────────────────────────────────────
    is_leader, coalesce_result_key = await try_coalesce_leader(
        str(connection_id), question, user_role, resource_id, employee_id
    )

    if not is_leader:
        # Another request is already computing this exact query — wait for it
        coalesced = await wait_for_coalesce_result(coalesce_result_key)
        if coalesced is not None:
            logger.info("Query coalesced — returning leader result")
            COALESCE_HITS.inc()
            return coalesced
        logger.warning("Coalesce wait timed out — falling through to normal pipeline")

    # ── SQL Cache Check ───────────────────────────────────────────────────
    cached = None
    if not skip_cache:
        cached = await get_cached_sql(
            str(connection_id), question, user_role, resource_id, employee_id
        )

    if cached:
        logger.info("SQL cache hit — bypassing LLM pipeline")
        CACHE_HITS.labels(type="sql").inc()
        try:
            result = await _execute_cached_pipeline(
                connection_id=connection_id,
                connection_string=connection_string,
                connector_type=conn.connector_type,
                sql=cached["sql"],
                question=question,
                session_id=session_id,
                current_user=current_user,
                timeout_seconds=conn.max_query_timeout_seconds,
                max_rows=conn.max_rows,
                event_queue=event_queue,
            )
            if is_leader and coalesce_result_key:
                await publish_coalesce_result(coalesce_result_key, result)
            return result
        except Exception:
            # Cached SQL failed — likely schema drift or bad cached SQL.
            # Invalidate cache and fall through to fresh LLM generation.
            logger.warning(
                "Cached SQL execution failed — invalidating cache and regenerating. q=%r sql=%r",
                question,
                cached["sql"][:200],
                exc_info=True,
            )
            from app.core.query_cache import delete_cached_sql

            await delete_cached_sql(
                str(connection_id), question, user_role, resource_id, employee_id
            )
            # Fall through to LangGraph pipeline below

    # ── LangGraph Pipeline ────────────────────────────────────────────────
    initial_state: GraphState = {
        "question": question,
        "connection_id": str(connection_id),
        "connector_type": conn.connector_type,
        "connection_string": connection_string,
        "timeout_seconds": conn.max_query_timeout_seconds,
        "max_rows": conn.max_rows,
        "db": async_session_factory,
        "session_id": str(session_id) if session_id and not clear_context else None,
        # Auth / RBAC
        "user_id": str(current_user.id) if current_user else None,
        "user_role": user_role,
        "resource_id": resource_id,
        "employee_id": employee_id,
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

    pipeline_start = time.monotonic()
    try:
        async with trace_query_pipeline(
            question=question,
            connection_id=str(connection_id),
            session_id=str(session_id) if session_id else None,
            user_id=str(current_user.id) if current_user else None,
        ):
            final_state = await asyncio.wait_for(
                get_compiled_graph().ainvoke(initial_state),
                timeout=settings.pipeline_timeout_seconds,
            )
        PIPELINE_DURATION.labels(outcome="success").observe(time.monotonic() - pipeline_start)
    except TimeoutError as err:
        PIPELINE_DURATION.labels(outcome="timeout").observe(time.monotonic() - pipeline_start)
        logger.error("Pipeline timed out after %ds", settings.pipeline_timeout_seconds)
        raise AppError(
            f"Query processing timed out after {settings.pipeline_timeout_seconds}s. "
            "Please try a simpler question or contact support.",
            status_code=504,
        ) from err

    # ── Structured observability log ──────────────────────────────────────
    pipeline_duration = time.monotonic() - pipeline_start
    result_for_cache: QueryResult | None = final_state.get("result")
    logger.info(
        "Pipeline complete",
        extra={
            "metrics": {
                "pipeline_duration_sec": round(pipeline_duration, 3),
                "question": question,
                "action": final_state.get("action") or "query",
                "model": final_state.get("llm_model"),
                "provider": final_state.get("llm_provider"),
                "retry_count": final_state.get("retry_count", 0),
                "row_count": result_for_cache.row_count if result_for_cache else 0,
                "cached": bool(cached) if "cached" in locals() else False,
                "coalesced": not is_leader,
            }
        },
    )

    # ── Post-graph: Cache + Coalesce Publish ──────────────────────────────
    action = final_state.get("action") or "query"
    retry_count = final_state.get("retry_count", 0)

    # Only cache if:
    # 1. It's a query action (not clarification)
    # 2. SQL was generated
    # 3. No pipeline error
    # 4. No retries were needed (LLM got it right first time)
    # 5. Result has rows (empty results often indicate wrong SQL)
    # This prevents caching wrong/uncertain SQL that would keep returning bad results.
    should_cache = (
        action == "query"
        and final_state.get("sql")
        and not final_state.get("error")
        and retry_count == 0
        and result_for_cache is not None
        and result_for_cache.row_count > 0
    )

    if should_cache:
        await set_cached_sql(
            str(connection_id),
            question,
            sql=final_state["sql"],
            explanation=final_state.get("explanation"),
            llm_provider=final_state.get("llm_provider"),
            llm_model=final_state.get("llm_model"),
            user_role=user_role,
            resource_id=resource_id,
            employee_id=employee_id,
        )
        logger.info(
            "SQL cached: q=%r rows=%d sql=%r",
            question,
            result_for_cache.row_count,
            final_state["sql"][:100],
        )
    else:
        logger.info(
            "SQL NOT cached: q=%r action=%s error=%s retry=%d has_rows=%s",
            question,
            action,
            bool(final_state.get("error")),
            retry_count,
            result_for_cache.row_count > 0 if result_for_cache else False,
        )

    # Auto-set session title from first question
    if session_id and not clear_context:
        async with async_session_factory() as title_db:
            session = await title_db.get(ChatSession, session_id)
            if session and session.title == "New Chat":
                session.title = question[:100].strip()
                session.updated_at = datetime.now(UTC)
                await title_db.commit()
            elif session:
                session.updated_at = datetime.now(UTC)
                await title_db.commit()

    # ── Format Response ───────────────────────────────────────────────────
    if action == "clarification":
        result_payload = {
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
        if is_leader and coalesce_result_key:
            await publish_coalesce_result(coalesce_result_key, result_payload)
        return result_payload

    if final_state.get("error") and final_state.get("result") is None:
        if is_leader and coalesce_result_key:
            await publish_coalesce_result(coalesce_result_key, {"error": final_state["error"]})
        raise AppError(final_state["error"], status_code=422)

    result: QueryResult = final_state["result"]

    result_status = "success"
    if result and not result.rows:
        result_status = "empty"
    elif final_state.get("error"):
        result_status = "error"

    result_payload = {
        "id": final_state.get("execution_id"),
        "question": question,
        "turn_type": action,
        "result_status": result_status,
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
    if is_leader and coalesce_result_key:
        await publish_coalesce_result(coalesce_result_key, result_payload)
    return result_payload


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
    except Exception as err:
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
        raise AppError("Query execution failed. Please try again.") from err

    # Step 3: Format results — minimal, no LLM interpreter
    summary = None
    highlights = []
    llm_provider_name = "manual"
    llm_model_name = "manual"
    question_text = original_question or "(manual SQL)"

    if result.rows:
        single_value = format_single_value_result(result.rows)
        if single_value is not None:
            summary = single_value
        else:
            summary = f"{result.row_count} row(s) returned"

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
    import decimal

    serialized = []
    for row in rows:
        serialized_row = []
        for val in row:
            if hasattr(val, "isoformat"):
                serialized_row.append(val.isoformat())
            elif isinstance(val, bytes):
                serialized_row.append(val.hex())
            elif isinstance(val, decimal.Decimal):
                serialized_row.append(float(val))
            else:
                serialized_row.append(val)
        serialized.append(serialized_row)
    return serialized
