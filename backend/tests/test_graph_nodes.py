from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base_connector import QueryResult
from app.llm.graph.state import GraphState


def _base_state(**overrides) -> GraphState:
    state = {
        "question": "show active resources",
        "connection_id": "00000000-0000-0000-0000-000000000001",
        "connector_type": "sqlserver",
        "connection_string": "dsn=test",
        "timeout_seconds": 30,
        "max_rows": 100,
        "db": None,
        "session_id": None,
        "user_id": None,
        "user_role": None,
        "resource_id": None,
        "employee_id": None,
        "loaded_history": [],
        "last_generated_sql": None,
        "last_result_columns": None,
        "last_result_preview_rows": None,
        "action": "query",
        "resolved_question": "show active resources",
        "clarification_reason": None,
        "clarification_message": None,
        "clarification_options": [],
        "sql": "SELECT * FROM Resource WHERE IsActive = 1",
        "result": None,
        "generated_sql": None,
        "retry_count": 0,
        "answer": None,
        "highlights": [],
        "suggested_followups": [],
        "explanation": None,
        "llm_provider": "domain_tool",
        "llm_model": "active_resources",
        "execution_id": None,
        "execution_time_ms": None,
        "error": None,
        "event_queue": None,
    }
    state.update(overrides)
    return state


@pytest.mark.anyio
async def test_interpret_result_no_rows():
    from app.llm.graph.nodes.result_interpreter import interpret_result

    result = QueryResult(
        columns=[], column_types=[], rows=[], row_count=0, execution_time_ms=5.0, truncated=False
    )
    state = _base_state(result=result)
    updates = await interpret_result(state)
    assert updates["answer"] is None
    assert updates["highlights"] == []


@pytest.mark.anyio
async def test_interpret_result_with_rows():
    from app.llm.agents.result_interpreter import InterpretationOutput
    from app.llm.graph.nodes.result_interpreter import interpret_result

    result = QueryResult(
        columns=["Name", "Role"],
        column_types=["nvarchar", "nvarchar"],
        rows=[["Alice", "Engineer"]],
        row_count=1,
        execution_time_ms=10.0,
        truncated=False,
    )
    mock_interp = InterpretationOutput(
        summary="1 active resource found.",
        highlights=["Alice"],
        suggested_followups=["Only show engineers", "Group by role"],
    )
    state = _base_state(result=result)
    with patch(
        "app.llm.graph.nodes.result_interpreter.route", return_value=(MagicMock(), MagicMock())
    ):
        with patch("app.llm.graph.nodes.result_interpreter.ResultInterpreterAgent") as MockAgent:
            instance = AsyncMock()
            instance.interpret = AsyncMock(return_value=mock_interp)
            MockAgent.return_value = instance
            updates = await interpret_result(state)

    assert updates["answer"] == "1 active resource found."
    assert updates["highlights"] == ["Alice"]
    assert updates["suggested_followups"] == ["Only show engineers", "Group by role"]


@pytest.mark.anyio
async def test_write_history_success(mock_db):
    from app.llm.graph.nodes.history_writer import write_history

    result = QueryResult(
        columns=["Name"],
        column_types=["nvarchar"],
        rows=[["Alice"]],
        row_count=1,
        execution_time_ms=12.0,
        truncated=False,
    )
    state = _base_state(result=result, db=mock_db, answer="1 result found.")
    await write_history(state)
    assert mock_db.add.called
    assert mock_db.flush.called
    execution = mock_db.add.call_args[0][0]
    assert execution.turn_type == "query"
    assert execution.result_columns == ["Name"]
    assert execution.result_preview_rows == [["Alice"]]
    assert execution.result_summary == "1 result found."


@pytest.mark.anyio
async def test_write_history_error(mock_db):
    from app.llm.graph.nodes.history_writer import write_history

    state = _base_state(db=mock_db, result=None, error="Connection failed")
    await write_history(state)
    assert mock_db.add.called
    call_arg = mock_db.add.call_args[0][0]
    assert call_arg.execution_status == "error"
    assert call_arg.error_message == "Connection failed"


@pytest.mark.anyio
async def test_write_history_clarification_turn_is_persisted_as_success(mock_db):
    from app.llm.graph.nodes.history_writer import write_history

    state = _base_state(
        db=mock_db,
        action="clarification",
        clarification_reason="low_confidence_rewrite",
        clarification_message="Did you want the SQL or the result explanation?",
        error="ignored for clarification",
    )

    await write_history(state)

    execution = mock_db.add.call_args[0][0]
    assert execution.turn_type == "clarification"
    assert execution.execution_status == "success"
    assert execution.error_message is None
    assert execution.result_summary == "Did you want the SQL or the result explanation?"
    assert execution.clarification_reason == "low_confidence_rewrite"


@pytest.mark.anyio
async def test_load_history_returns_compacted_messages_and_last_successful_query(mock_db):
    from app.llm.graph.nodes.load_history import load_history

    rows = [
        SimpleNamespace(
            natural_language="Now show in SQL",
            result_summary="```sql\nSELECT * FROM resource\n```",
            turn_type="show_sql",
            execution_status="success",
            generated_sql=None,
            final_sql="SELECT * FROM resource",
            result_columns=None,
            result_preview_rows=None,
        ),
        SimpleNamespace(
            natural_language="Show active resources",
            result_summary="Returned 2 rows",
            turn_type="query",
            execution_status="success",
            generated_sql="SELECT * FROM resource",
            final_sql="SELECT * FROM resource",
            result_columns=["Name"],
            result_preview_rows=[["Alice"], ["Bob"]],
        ),
    ]
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = rows
    mock_db.execute.return_value = execute_result

    updates = await load_history(
        _base_state(db=mock_db, session_id="00000000-0000-0000-0000-000000000123")
    )

    assert updates["loaded_history"][0] == {"role": "user", "content": "Show active resources"}
    assert updates["loaded_history"][2] == {"role": "user", "content": "Now show in SQL"}
    assert updates["loaded_history"][1]["role"] == "assistant"
    assert updates["last_generated_sql"] == "SELECT * FROM resource"
    assert updates["last_result_columns"] == ["Name"]
    assert updates["last_result_preview_rows"] == [["Alice"], ["Bob"]]


@pytest.mark.anyio
async def test_resolve_turn_first_message_skips_llm_and_returns_query():
    from app.llm.graph.nodes.resolve_turn import resolve_turn

    updates = await resolve_turn(_base_state(question="Show active resources", loaded_history=[]))

    assert updates["action"] == "query"
    assert updates["resolved_question"] == "Show active resources"


@pytest.mark.anyio
async def test_resolve_turn_low_confidence_rewrite_becomes_clarification():
    from app.llm.graph.nodes.resolve_turn import resolve_turn

    mock_provider = MagicMock()
    mock_provider.complete = AsyncMock(
        return_value=SimpleNamespace(
            content=(
                '{"action":"show_sql","confidence":0.4,'
                '"resolved_question":null,'
                '"clarification_message":"Do you want the SQL or a new query?",'
                '"clarification_options":["Show previous SQL","Run a new query"]}'
            )
        )
    )

    with patch("app.llm.graph.nodes.resolve_turn.get_provider", return_value=mock_provider):
        updates = await resolve_turn(
            _base_state(
                loaded_history=[{"role": "user", "content": "Show active resources"}],
                last_generated_sql="SELECT * FROM resource",
            )
        )

    assert updates["action"] == "clarification"
    assert updates["clarification_reason"] == "low_confidence_rewrite"
    assert "Do you want the SQL" in updates["clarification_message"]


@pytest.mark.anyio
async def test_answer_from_state_show_sql_returns_previous_sql():
    from app.llm.graph.nodes.answer_from_state import answer_from_state

    updates = await answer_from_state(
        _base_state(action="show_sql", last_generated_sql="SELECT 1", sql=None)
    )

    assert updates["generated_sql"] == "SELECT 1"
    assert "SELECT 1" in updates["answer"]


@pytest.mark.anyio
async def test_answer_from_state_missing_previous_result_requests_clarification():
    from app.llm.graph.nodes.answer_from_state import answer_from_state

    updates = await answer_from_state(_base_state(action="explain_result"))

    assert updates["action"] == "clarification"
    assert updates["clarification_reason"] == "missing_previous_result"
