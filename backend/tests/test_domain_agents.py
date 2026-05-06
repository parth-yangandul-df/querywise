from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base_connector import QueryResult


def _mock_connector(rows=None):
    c = MagicMock()
    result = QueryResult(
        columns=["Name"],
        column_types=["nvarchar"],
        rows=rows or [["Alice"]],
        row_count=len(rows or [["Alice"]]),
        execution_time_ms=5.0,
        truncated=False,
    )
    c.execute_query = AsyncMock(return_value=result)
    return c


def _state(**overrides):
    base = {
        "question": "show active resources",
        "connection_id": "00000000-0000-0000-0000-000000000001",
        "connector_type": "sqlserver",
        "connection_string": "dsn=test",
        "timeout_seconds": 30,
        "max_rows": 100,
        "db": None,
        "domain": "resource",
        "intent": "active_resources",
        "confidence": 0.95,
        "params": {},
        "sql": None,
        "result": None,
        "generated_sql": None,
        "retry_count": 0,
        "explanation": None,
        "llm_provider": None,
        "llm_model": None,
        "answer": None,
        "highlights": [],
        "suggested_followups": [],
        "execution_id": None,
        "execution_time_ms": None,
        "error": None,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_resource_active(monkeypatch):
    from app.llm.graph.domains.resource import ResourceAgent

    mock_conn = _mock_connector()
    monkeypatch.setattr(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        AsyncMock(return_value=mock_conn),
    )
    agent = ResourceAgent()
    state = _state(intent="active_resources")
    updates = await agent.execute(state)
    assert updates["llm_provider"] == "domain_tool"
    assert updates["llm_model"] == "active_resources"
    assert updates["result"] is not None
    assert updates["error"] is None


@pytest.mark.asyncio
async def test_resource_by_skill_passes_param(monkeypatch):
    from app.llm.graph.domains.resource import ResourceAgent

    mock_conn = _mock_connector()
    monkeypatch.setattr(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        AsyncMock(return_value=mock_conn),
    )
    agent = ResourceAgent()
    state = _state(intent="resource_by_skill", params={"skill": "Python"})
    await agent.execute(state)
    call_kwargs = mock_conn.execute_query.call_args
    assert call_kwargs.kwargs.get("params") == ("%Python%", "%Python%", "%Python%", "%Python%")


@pytest.mark.asyncio
async def test_resource_unknown_intent_raises(monkeypatch):
    from app.llm.graph.domains.resource import ResourceAgent

    mock_conn = _mock_connector()
    monkeypatch.setattr(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        AsyncMock(return_value=mock_conn),
    )
    agent = ResourceAgent()
    state = _state(intent="nonexistent_intent")
    with pytest.raises(ValueError, match="unknown intent"):
        await agent.execute(state)


@pytest.mark.asyncio
async def test_client_active(monkeypatch):
    from app.llm.graph.domains.client import ClientAgent

    mock_conn = _mock_connector()
    monkeypatch.setattr(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        AsyncMock(return_value=mock_conn),
    )
    agent = ClientAgent()
    state = _state(domain="client", intent="active_clients")
    updates = await agent.execute(state)
    assert updates["llm_provider"] == "domain_tool"
    assert updates["result"] is not None


@pytest.mark.asyncio
async def test_project_active(monkeypatch):
    from app.llm.graph.domains.project import ProjectAgent

    mock_conn = _mock_connector()
    monkeypatch.setattr(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        AsyncMock(return_value=mock_conn),
    )
    agent = ProjectAgent()
    state = _state(domain="project", intent="active_projects")
    updates = await agent.execute(state)
    assert updates["llm_provider"] == "domain_tool"
    assert updates["result"] is not None


@pytest.mark.asyncio
async def test_timesheet_valid_filter(monkeypatch):
    """Approved timesheet query must include IsApproved=1 AND IsDeleted=0 AND IsRejected=0."""
    from app.llm.graph.domains.timesheet import TimesheetAgent

    mock_conn = _mock_connector()
    monkeypatch.setattr(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        AsyncMock(return_value=mock_conn),
    )
    agent = TimesheetAgent()
    state = _state(domain="timesheet", intent="approved_timesheets")
    await agent.execute(state)
    executed_sql = mock_conn.execute_query.call_args[0][0]
    assert "IsApproved = 1" in executed_sql
    assert "IsDeleted = 0" in executed_sql
    assert "IsRejected = 0" in executed_sql


@pytest.mark.asyncio
async def test_run_domain_tool_dispatches(monkeypatch):
    from app.llm.graph.domains.registry import run_domain_tool

    mock_conn = _mock_connector()
    monkeypatch.setattr(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        AsyncMock(return_value=mock_conn),
    )
    state = _state(domain="resource", intent="active_resources")
    updates = await run_domain_tool(state)
    assert updates["llm_provider"] == "domain_tool"


@pytest.mark.asyncio
async def test_run_domain_tool_unknown_domain(monkeypatch):
    from app.llm.graph.domains.registry import run_domain_tool

    state = _state(domain="nonexistent")
    with pytest.raises(ValueError, match="unknown domain"):
        await run_domain_tool(state)
