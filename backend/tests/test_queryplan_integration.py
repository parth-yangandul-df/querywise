"""Integration tests for BaseDomainAgent.execute() with QueryPlan compiler feature flag.

Tests the 5 regression flow scenarios specified in 07-03-PLAN.md:
1. Feature flag OFF → existing _try_refinement() path runs unchanged
2. Feature flag ON, query_plan present → compile_query() path runs
3. Feature flag ON, query_plan None → falls back to _run_intent() (no crash)
4. compile_query() result executed against connector with correct params
5. 5 regression flows under USE_QUERY_PLAN_COMPILER=true
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.base_connector import QueryResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_result(row_count: int = 2) -> QueryResult:
    """Build a minimal QueryResult for testing."""
    return QueryResult(
        columns=["Name", "EMPID"],
        column_types=["nvarchar", "int"],
        rows=[["Alice", 1], ["Bob", 2]][:row_count],
        row_count=row_count,
        execution_time_ms=5.0,
        truncated=False,
    )


def _base_state(**overrides) -> dict[str, Any]:
    """Minimal valid GraphState for domain agent tests."""
    defaults: dict[str, Any] = {
        "question": "show active resources",
        "connection_id": "conn-001",
        "connector_type": "mssql",
        "connection_string": "mssql://server/db",
        "timeout_seconds": 30,
        "max_rows": 1000,
        "db": MagicMock(),
        "session_id": None,
        "conversation_history": [],
        "last_turn_context": None,
        "user_id": None,
        "user_role": "admin",
        "resource_id": None,
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
        "filters": [],
        "query_plan": None,
    }
    defaults.update(overrides)
    return defaults


def _make_mock_connector(result: QueryResult | None = None) -> MagicMock:
    """Build a mock connector whose execute_query returns a fixed result."""
    connector = MagicMock()
    connector.execute_query = AsyncMock(return_value=result or _mock_result())
    return connector


# ---------------------------------------------------------------------------
# Test 1: Feature flag OFF → _try_refinement() path is used (existing path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_off_uses_existing_refinement_path(monkeypatch):
    """When USE_QUERY_PLAN_COMPILER=false, existing _is_refine_mode path runs."""
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "false")

    # Re-import config so the env var takes effect
    import app.config

    importlib.reload(app.config)
    import app.llm.graph.domains.base_domain as bd_module

    importlib.reload(bd_module)

    from app.llm.graph.domains.resource import ResourceAgent

    agent = ResourceAgent()
    mock_connector = _make_mock_connector()

    with patch(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        return_value=mock_connector,
    ):
        # Normal (non-refine) state → should call _run_intent via the existing else path
        state = _base_state(intent="active_resources", params={})
        result = await agent.execute(state)

    assert result["sql"] is not None
    assert result["llm_provider"] == "domain_tool"
    assert result["error"] is None
    # Connector was called (via _run_intent)
    mock_connector.execute_query.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2: Feature flag ON, query_plan present → compile_query() path runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_with_query_plan_uses_compiler(monkeypatch):
    """When flag=ON and query_plan is in state, compile_query() path executes."""
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)
    import app.llm.graph.domains.base_domain as bd_module

    importlib.reload(bd_module)

    from app.llm.graph.domains.resource import ResourceAgent

    agent = ResourceAgent()
    mock_connector = _make_mock_connector()

    query_plan = {
        "domain": "resource",
        "intent": "active_resources",
        "filters": [],
        "base_intent_sql": "",
        "schema_version": 1,
    }

    with patch(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        return_value=mock_connector,
    ):
        state = _base_state(query_plan=query_plan)
        result = await agent.execute(state)

    assert result["sql"] is not None
    assert result["error"] is None
    assert result["llm_provider"] == "domain_tool"
    # Should have used compile_query — SQL should come from BASE_QUERIES
    from app.llm.graph.nodes.sql_compiler import BASE_QUERIES

    expected_base = (
        BASE_QUERIES["active_resources"].replace("{select_extras}", "").replace("{join_extras}", "")
    )
    assert result["sql"] == expected_base


# ---------------------------------------------------------------------------
# Test 3: Feature flag ON, query_plan None → falls back to _run_intent() (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_no_query_plan_falls_back_to_run_intent(monkeypatch):
    """Flag=ON but query_plan=None (LLM fallback turn) → _run_intent() runs."""
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)
    import app.llm.graph.domains.base_domain as bd_module

    importlib.reload(bd_module)

    from app.llm.graph.domains.resource import ResourceAgent

    agent = ResourceAgent()
    mock_connector = _make_mock_connector()

    with patch(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        return_value=mock_connector,
    ):
        # query_plan=None → should fall back to _run_intent
        state = _base_state(query_plan=None)
        result = await agent.execute(state)

    assert result["sql"] is not None
    assert result["error"] is None
    # Connector called once via _run_intent
    mock_connector.execute_query.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: compile_query() result executed against connector with correct params
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flag_on_passes_compiled_sql_and_params_to_connector(monkeypatch):
    """compile_query() result (sql, params) is passed correctly to connector."""
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)
    import app.llm.graph.domains.base_domain as bd_module

    importlib.reload(bd_module)

    from app.llm.graph.domains.resource import ResourceAgent

    agent = ResourceAgent()
    mock_connector = _make_mock_connector()

    # Plan with one filter
    query_plan = {
        "domain": "resource",
        "intent": "active_resources",
        "filters": [{"field": "resource_name", "op": "eq", "values": ["Alice"]}],
        "base_intent_sql": "",
        "schema_version": 1,
    }

    with patch(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        return_value=mock_connector,
    ):
        state = _base_state(query_plan=query_plan)
        result = await agent.execute(state)

    # Verify connector was called
    mock_connector.execute_query.assert_called_once()
    call_kwargs = mock_connector.execute_query.call_args

    # SQL should have WHERE Name LIKE ?
    actual_sql = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("sql", "")
    # params should contain the %Alice% value
    actual_params = call_kwargs[1].get("params") or (
        call_kwargs[0][1] if len(call_kwargs[0]) > 1 else ()
    )

    assert result["sql"] is not None
    assert "Alice" in str(actual_params) or "%Alice%" in str(actual_params)


# ---------------------------------------------------------------------------
# Test 5a: Resource chain regression flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resource_chain_produces_clean_sql(monkeypatch):
    """test_resource_chain: active resources + Python skill + named John.

    Verifies: single compiled SQL with WHERE conditions (not nested subqueries).
    """
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)
    import app.llm.graph.domains.base_domain as bd_module

    importlib.reload(bd_module)

    from app.llm.graph.nodes.sql_compiler import compile_query
    from app.llm.graph.query_plan import FilterClause, QueryPlan

    # Simulate accumulated plan after 3 turns
    plan = QueryPlan(
        domain="resource",
        intent="active_resources",
        filters=[
            FilterClause(field="skill", op="in", values=["Python"]),
            FilterClause(field="resource_name", op="eq", values=["John"]),
        ],
        base_intent_sql="",
        schema_version=1,
    )
    sql, params = compile_query(plan)

    # Single-level SQL — NO nested subquery
    assert "SELECT prev.* FROM" not in sql, "Should not use subquery wrapping"
    assert "WHERE" in sql
    # Both filters should be applied
    assert len(params) >= 2


# ---------------------------------------------------------------------------
# Test 5b: Project filter chain regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_filter_chain(monkeypatch):
    """test_project_filter_chain: active projects + client Acme + budget > 100000.

    Verifies: single compiled SQL with WHERE clauses.
    """
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)

    from app.llm.graph.nodes.sql_compiler import compile_query
    from app.llm.graph.query_plan import FilterClause, QueryPlan

    plan = QueryPlan(
        domain="project",
        intent="active_projects",
        filters=[
            FilterClause(field="client_name", op="eq", values=["Acme"]),
            FilterClause(field="min_budget", op="gt", values=["100000"]),
        ],
        base_intent_sql="",
        schema_version=1,
    )
    sql, params = compile_query(plan)

    assert "SELECT prev.* FROM" not in sql, "Should not use subquery wrapping"
    assert len(params) >= 2


# ---------------------------------------------------------------------------
# Test 5c: Timesheet date chain regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timesheet_date_chain(monkeypatch):
    """test_timesheet_date_chain: approved timesheets + date range + hours >= 8.

    Verifies: single compiled SQL with BETWEEN + >=.
    """
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)

    from app.llm.graph.nodes.sql_compiler import compile_query
    from app.llm.graph.query_plan import FilterClause, QueryPlan

    plan = QueryPlan(
        domain="timesheet",
        intent="approved_timesheets",
        filters=[
            FilterClause(field="start_date", op="between", values=["2024-01-01", "2024-06-30"]),
            FilterClause(field="min_hours", op="gt", values=["8"]),
        ],
        base_intent_sql="",
        schema_version=1,
    )
    sql, params = compile_query(plan)

    assert "BETWEEN" in sql
    assert ">=" in sql
    assert "SELECT prev.* FROM" not in sql, "Should not use subquery wrapping"
    assert "2024-01-01" in params
    assert "2024-06-30" in params


# ---------------------------------------------------------------------------
# Test 5d: Topic switch recovery — fresh QueryPlan on domain switch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topic_switch_recovery(monkeypatch):
    """test_topic_switch_recovery: domain switch discards old query_plan.

    When domain changes from resource to project, the state's query_plan
    should contain only the new plan (not carry old filters).
    """
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)
    import app.llm.graph.domains.base_domain as bd_module

    importlib.reload(bd_module)

    from app.llm.graph.domains.project import ProjectAgent
    from app.llm.graph.nodes.sql_compiler import BASE_QUERIES

    agent = ProjectAgent()
    mock_connector = _make_mock_connector()

    # New plan for project domain (fresh, no old resource filters)
    new_plan = {
        "domain": "project",
        "intent": "active_projects",
        "filters": [],
        "base_intent_sql": "",
        "schema_version": 1,
    }

    with patch(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        return_value=mock_connector,
    ):
        state = _base_state(
            domain="project",
            intent="active_projects",
            query_plan=new_plan,
        )
        result = await agent.execute(state)

    assert result["error"] is None
    # Should use active_projects template
    expected_base = (
        BASE_QUERIES["active_projects"].replace("{select_extras}", "").replace("{join_extras}", "")
    )
    assert result["sql"] == expected_base


# ---------------------------------------------------------------------------
# Test 5e: LLM fallback → domain tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_fallback_to_domain(monkeypatch):
    """test_llm_fallback_to_domain: query_plan=None on LLM turn, fresh plan on domain turn.

    When query_plan is None (LLM fallback turn), falls back to _run_intent().
    When query_plan is present (domain turn), uses compile_query().
    """
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)
    import app.llm.graph.domains.base_domain as bd_module

    importlib.reload(bd_module)

    from app.llm.graph.domains.resource import ResourceAgent

    agent = ResourceAgent()
    mock_connector = _make_mock_connector()

    with patch(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        return_value=mock_connector,
    ):
        # LLM fallback turn: query_plan=None
        state_llm = _base_state(query_plan=None)
        result_llm = await agent.execute(state_llm)

    assert result_llm["error"] is None
    assert result_llm["sql"] is not None
    # Connector was called via _run_intent fallback
    assert mock_connector.execute_query.called

    # Domain turn: fresh plan
    mock_connector.execute_query.reset_mock()

    with patch(
        "app.llm.graph.domains.base_domain.get_or_create_connector",
        return_value=mock_connector,
    ):
        domain_plan = {
            "domain": "resource",
            "intent": "active_resources",
            "filters": [],
            "base_intent_sql": "",
            "schema_version": 1,
        }
        state_domain = _base_state(query_plan=domain_plan)
        result_domain = await agent.execute(state_domain)

    assert result_domain["error"] is None
    assert result_domain["sql"] is not None
    assert mock_connector.execute_query.called


# ---------------------------------------------------------------------------
# Test 7: Value_map normalization pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_value_map_normalization_pipeline(monkeypatch):
    """Full pipeline with value_map: 'backend' in question → 'Backend Developer' in SQL.

    Mocks cached value_map so plan_updater normalizes designation filter value.
    Verifies: compiled SQL param contains 'Backend Developer' not 'backend'.
    """
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)

    from app.llm.graph.nodes.plan_updater import update_query_plan
    from app.llm.graph.nodes.sql_compiler import compile_query
    from app.llm.graph.query_plan import FilterClause, QueryPlan

    # Mock the cached value_map to normalize designation
    value_map = {"designation": {"backend": "Backend Developer"}}

    with patch(
        "app.llm.graph.nodes.plan_updater.get_cached_value_map",
        return_value=value_map,
    ):
        state = {
            "domain": "resource",
            "intent": "active_resources",
            "query_plan": None,
            "filters": [
                FilterClause(field="designation", op="eq", values=["backend"]),
            ],
            "params": {},
        }
        plan_result = await update_query_plan(state)

    plan_dict = plan_result["query_plan"]
    assert plan_dict is not None

    # Reconstruct QueryPlan from dict and compile to SQL
    plan = QueryPlan.from_untrusted_dict(plan_dict)
    sql, params = compile_query(plan)

    # SQL should contain 'Backend Developer' — the normalized value
    assert "Backend Developer" in str(params), (
        f"Expected 'Backend Developer' in params, got: {params}"
    )
    # Should NOT contain the raw user value
    assert "%backend%" not in str(params).lower()


# ---------------------------------------------------------------------------
# Test 8: Metric injection pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metric_injection_pipeline(monkeypatch):
    """Full pipeline with metric injection: MetricFragment → SUM(Hours) with GROUP BY.

    Builds a QueryPlan and compiles with a MetricFragment for total hours.
    Verifies: compiled SQL contains SUM(Hours), GROUP BY.
    """
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)

    from app.llm.graph.nodes.sql_compiler import MetricFragment, compile_query
    from app.llm.graph.query_plan import QueryPlan

    plan = QueryPlan(
        domain="timesheet",
        intent="approved_timesheets",
        filters=[],
        base_intent_sql="",
        schema_version=1,
    )

    metric = MetricFragment(
        select_expr="SUM(ts.Hours) AS total_hours",
        join_clause="",
        requires_group_by=True,
    )

    sql, params = compile_query(plan, metrics=[metric])

    # Metric should be injected into the SELECT
    assert "SUM(ts.Hours) AS total_hours" in sql, f"Expected SUM(ts.Hours) in SQL: {sql[:200]}"
    # GROUP BY should be appended
    assert "GROUP BY" in sql, f"Expected GROUP BY in SQL: {sql[:300]}"


# ---------------------------------------------------------------------------
# Test 9: Full semantic pipeline — value_map + metrics + filter simulation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_semantic_pipeline(monkeypatch):
    """Full pipeline combining value_map normalization and metric injection.

    Simulates filters that would come from filter_extractor (now deprecated).
    Tests active code: plan_updater and sql_compiler.

    Verifies: value_map normalization and metric injection work together.
    """
    monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")

    import app.config

    importlib.reload(app.config)

    from app.llm.graph.nodes.plan_updater import update_query_plan
    from app.llm.graph.nodes.sql_compiler import MetricFragment, compile_query
    from app.llm.graph.query_plan import FilterClause, QueryPlan

    # Create filters directly (simulating what filter_extractor would have produced)
    # Include a skill filter and a designation filter to test value_map normalization
    filters = [
        FilterClause(field="skill", op="eq", values=["Python"]),
        FilterClause(field="designation", op="eq", values=["backend"]),
    ]

    # Step 1: Plan updater normalizes via value_map
    value_map = {
        "designation": {"backend": "Backend Developer"},
        "status": {"active": "Active"},
    }

    with patch(
        "app.llm.graph.nodes.plan_updater.get_cached_value_map",
        return_value=value_map,
    ):
        plan_state = {
            "domain": "resource",
            "intent": "active_resources",
            "query_plan": None,
            "filters": filters,
            "params": {},
        }
        plan_result = await update_query_plan(plan_state)

    plan_dict = plan_result["query_plan"]
    assert plan_dict is not None

    # Check designation was normalized
    desig_filters = [f for f in plan_dict["filters"] if f["field"] == "designation"]
    assert len(desig_filters) == 1
    assert desig_filters[0]["values"] == ["Backend Developer"]

    # Check skill filter is still present
    skill_filters = [f for f in plan_dict["filters"] if f["field"] == "skill"]
    assert len(skill_filters) == 1
    assert skill_filters[0]["values"] == ["Python"]

    # Step 2: Compile SQL with MetricFragment
    plan = QueryPlan.from_untrusted_dict(plan_dict)
    metric = MetricFragment(
        select_expr="SUM(Hours) AS total_hours",
        join_clause="",
        requires_group_by=True,
    )

    sql, params = compile_query(plan, metrics=[metric])

    # Verify effects:
    # 1. Skill filter → WHERE clause
    assert "WHERE" in sql
    # 2. Designation normalized to Backend Developer
    assert "Backend Developer" in str(params)
    # 3. Metric injection → SUM and GROUP BY
    assert "SUM(Hours) AS total_hours" in sql
    assert "GROUP BY" in sql
