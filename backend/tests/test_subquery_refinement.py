"""Tests for subquery refinement mode — base helpers and ResourceAgent._run_refinement().

Covers:
  - _strip_order_by() with ORDER BY present, absent, mid-query (should not strip mid-query ORDER BY)
  - _is_refine_mode() edge cases
  - ResourceAgent._run_refinement() unified skill filter (benched_resources pattern with prev.EMPID join)
  - ResourceAgent._run_refinement() active_resources pattern (prev.[EMPID] join)
  - ResourceAgent._run_refinement() with no skill param → falls back to _run_intent
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.llm.graph.domains.base_domain import _is_refine_mode, _strip_order_by
from app.llm.graph.domains.resource import ResourceAgent

from app.connectors.base_connector import QueryResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BENCHED_SQL_WITH_ORDER_BY = (
    "SELECT DISTINCT r.employeeid, r.ResourceName, r.EmailId, t.TechCategoryName "
    "FROM Resource r "
    "JOIN ProjectResource pr ON r.ResourceId = pr.ResourceId "
    "JOIN Project p ON pr.ProjectId = p.ProjectId "
    "JOIN TechCatagory t ON t.TechCategoryId = r.TechCategoryId "
    "WHERE p.ProjectId = 119 "
    "ORDER BY r.ResourceName"
)

ACTIVE_SQL_WITH_ORDER_BY = (
    "SELECT r.EmployeeId as [EMPID], r.ResourceName as [Name], r.EmailId, dr.designationname as [Designation] "
    "FROM Resource r "
    "JOIN Designation dr ON r.designationid = dr.designationid "
    "WHERE r.IsActive = 1 and r.statusid = 8 order by r.resourcename asc"
)

BENCHED_COLUMNS = ["EMPID", "ResourceName", "EmailId", "TechCategoryName"]
ACTIVE_COLUMNS = ["EMPID", "Name", "EmailId", "Designation"]


def _make_state(intent: str, params: dict, timeout: int = 30, max_rows: int = 100) -> dict:
    """Build a minimal GraphState dict for domain agent tests."""
    return {
        "intent": intent,
        "params": params,
        "timeout_seconds": timeout,
        "max_rows": max_rows,
        "connection_id": "test-conn",
        "connector_type": "sqlserver",
        "connection_string": "mssql://...",
        # other GraphState keys not needed for domain agent tests
        "query": "",
        "domain": "resource",
        "confidence": 0.95,
        "user_role": "admin",
        "last_turn_context": None,
        "sql": None,
        "result": None,
        "generated_sql": None,
        "explanation": None,
        "llm_provider": None,
        "llm_model": None,
        "error": None,
    }


def _make_query_result(columns: list[str] | None = None) -> QueryResult:
    return QueryResult(
        columns=columns or ["col"],
        column_types=["nvarchar"] * (len(columns) if columns else 1),
        rows=[],
        row_count=0,
        execution_time_ms=5.0,
        truncated=False,
    )


# ---------------------------------------------------------------------------
# _strip_order_by tests
# ---------------------------------------------------------------------------


class TestStripOrderBy:
    def test_strips_trailing_order_by(self):
        sql = "SELECT * FROM t ORDER BY name"
        assert _strip_order_by(sql) == "SELECT * FROM t"

    def test_strips_trailing_order_by_case_insensitive(self):
        sql = "SELECT * FROM t order by name asc"
        assert _strip_order_by(sql) == "SELECT * FROM t"

    def test_strips_multiline_order_by(self):
        sql = "SELECT * FROM t\nORDER BY name, id DESC"
        result = _strip_order_by(sql)
        assert "ORDER BY" not in result.upper()
        assert "SELECT * FROM t" in result

    def test_no_order_by_unchanged(self):
        sql = "SELECT * FROM t WHERE x = 1"
        assert _strip_order_by(sql) == sql

    def test_strips_benched_resources_sql(self):
        result = _strip_order_by(BENCHED_SQL_WITH_ORDER_BY)
        assert "ORDER BY" not in result.upper()
        assert "employeeid" in result
        assert "TechCategoryName" in result

    def test_strips_active_resources_sql(self):
        result = _strip_order_by(ACTIVE_SQL_WITH_ORDER_BY)
        assert "ORDER BY" not in result.upper()
        assert "EMPID" in result

    def test_strips_from_first_order_by_to_end(self):
        # The regex uses re.DOTALL so .+ matches everything including newlines.
        # It strips from the first occurrence of \s+ORDER\s+BY to end of string.
        # This is correct for the actual use case: stripping ORDER BY from
        # simple resource queries before wrapping as a subquery.
        sql = "SELECT * FROM t ORDER BY name, id DESC"
        result = _strip_order_by(sql)
        assert result == "SELECT * FROM t"
        assert "ORDER BY" not in result.upper()


# ---------------------------------------------------------------------------
# _is_refine_mode tests
# ---------------------------------------------------------------------------


class TestIsRefineMode:
    def test_true_when_both_flags_set(self):
        params = {"_refine_mode": True, "_prior_sql": "SELECT * FROM t"}
        assert _is_refine_mode(params) is True

    def test_false_when_empty_prior_sql(self):
        params = {"_refine_mode": True, "_prior_sql": ""}
        assert _is_refine_mode(params) is False

    def test_false_when_refine_mode_missing(self):
        params = {"_prior_sql": "SELECT * FROM t"}
        assert _is_refine_mode(params) is False

    def test_false_when_empty_dict(self):
        assert _is_refine_mode({}) is False

    def test_false_when_refine_mode_false(self):
        params = {"_refine_mode": False, "_prior_sql": "SELECT * FROM t"}
        assert _is_refine_mode(params) is False

    def test_false_when_prior_sql_none(self):
        params = {"_refine_mode": True, "_prior_sql": None}
        assert _is_refine_mode(params) is False


# ---------------------------------------------------------------------------
# ResourceAgent._run_refinement — unified skill filter (both patterns)
# ---------------------------------------------------------------------------


class TestResourceAgentRefinementBenched:
    @pytest.mark.asyncio
    async def test_benched_refinement_sql_contains_as_prev(self):
        """Benched resources refinement wraps prior SQL as AS prev subquery."""
        agent = ResourceAgent()
        mock_connector = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=_make_query_result(BENCHED_COLUMNS))

        params = {
            "_refine_mode": True,
            "_prior_sql": BENCHED_SQL_WITH_ORDER_BY,
            "_prior_columns": BENCHED_COLUMNS,
            "skill": "Python",
        }
        state = _make_state("benched_resources", params)

        sql, result = await agent._run_refinement(
            prior_sql=BENCHED_SQL_WITH_ORDER_BY,
            params=params,
            connector=mock_connector,
            state=state,
        )

        assert "AS prev" in sql
        assert "PA_Skills" in sql
        assert "ORDER BY" not in sql.upper()

    @pytest.mark.asyncio
    async def test_benched_refinement_sql_joins_on_empid(self):
        """Unified pattern joins on r2.EmployeeId = prev.EMPID (uppercase alias)."""
        agent = ResourceAgent()
        mock_connector = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=_make_query_result(BENCHED_COLUMNS))

        params = {
            "_refine_mode": True,
            "_prior_sql": BENCHED_SQL_WITH_ORDER_BY,
            "_prior_columns": BENCHED_COLUMNS,
            "skill": "Python",
        }
        state = _make_state("benched_resources", params)

        sql, _ = await agent._run_refinement(
            BENCHED_SQL_WITH_ORDER_BY, params, mock_connector, state
        )

        # Both benched and active use unified prev.EMPID reference
        assert "prev.EMPID" in sql
        assert "prev.employeeid" not in sql

    @pytest.mark.asyncio
    async def test_benched_refinement_passes_skill_param(self):
        """Unified skill filter searches s.Name, r2.PrimarySkill, r2.SecondarySkill."""
        agent = ResourceAgent()
        mock_connector = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=_make_query_result(BENCHED_COLUMNS))

        params = {
            "_refine_mode": True,
            "_prior_sql": BENCHED_SQL_WITH_ORDER_BY,
            "_prior_columns": BENCHED_COLUMNS,
            "skill": "Python",
        }
        state = _make_state("benched_resources", params)

        await agent._run_refinement(BENCHED_SQL_WITH_ORDER_BY, params, mock_connector, state)

        call_kwargs = mock_connector.execute_query.call_args
        passed_params = (
            call_kwargs.kwargs.get("params") or call_kwargs.args[1]
            if len(call_kwargs.args) > 1
            else None
        )
        # Params kwarg is used
        assert mock_connector.execute_query.called
        _, kw = mock_connector.execute_query.call_args
        # Unified skill filter searches s.Name, r2.PrimarySkill, r2.SecondarySkill
        assert kw["params"] == ("%Python%", "%Python%", "%Python%")


# ---------------------------------------------------------------------------
# ResourceAgent._run_refinement — active_resources pattern
# ---------------------------------------------------------------------------


class TestResourceAgentRefinementActive:
    @pytest.mark.asyncio
    async def test_active_refinement_sql_contains_empid_join(self):
        """Active resources refinement joins on prev.EMPID (unified alias)."""
        agent = ResourceAgent()
        mock_connector = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=_make_query_result(ACTIVE_COLUMNS))

        params = {
            "_refine_mode": True,
            "_prior_sql": ACTIVE_SQL_WITH_ORDER_BY,
            "_prior_columns": ACTIVE_COLUMNS,
            "skill": "Java",
        }
        state = _make_state("active_resources", params)

        sql, _ = await agent._run_refinement(
            ACTIVE_SQL_WITH_ORDER_BY, params, mock_connector, state
        )

        assert "AS prev" in sql
        assert "prev.EMPID" in sql
        assert "PA_Skills" in sql
        assert "ORDER BY" not in sql.upper()

    @pytest.mark.asyncio
    async def test_active_refinement_passes_three_skill_params(self):
        """Active pattern passes skill 3× (s.Name, r2.PrimarySkill, r2.SecondarySkill)."""
        agent = ResourceAgent()
        mock_connector = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=_make_query_result(ACTIVE_COLUMNS))

        params = {
            "_refine_mode": True,
            "_prior_sql": ACTIVE_SQL_WITH_ORDER_BY,
            "_prior_columns": ACTIVE_COLUMNS,
            "skill": "Java",
        }
        state = _make_state("active_resources", params)

        await agent._run_refinement(ACTIVE_SQL_WITH_ORDER_BY, params, mock_connector, state)

        _, kw = mock_connector.execute_query.call_args
        assert kw["params"] == ("%Java%", "%Java%", "%Java%")


# ---------------------------------------------------------------------------
# ResourceAgent._run_refinement — no skill param → fallback to _run_intent
# ---------------------------------------------------------------------------


class TestResourceAgentRefinementNoSkill:
    @pytest.mark.asyncio
    async def test_no_skill_falls_back_to_run_intent(self):
        """When skill param is missing, _run_refinement calls _run_intent instead."""
        agent = ResourceAgent()
        mock_connector = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=_make_query_result(BENCHED_COLUMNS))

        params = {
            "_refine_mode": True,
            "_prior_sql": BENCHED_SQL_WITH_ORDER_BY,
            "_prior_columns": BENCHED_COLUMNS,
            # NO skill param
        }
        state = _make_state("benched_resources", params)

        # Patch _run_intent to verify it gets called
        with patch.object(
            agent, "_run_intent", new=AsyncMock(return_value=("SELECT 1", _make_query_result()))
        ) as mock_run_intent:
            sql, _ = await agent._run_refinement(
                BENCHED_SQL_WITH_ORDER_BY, params, mock_connector, state
            )
            mock_run_intent.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_skill_falls_back_to_run_intent(self):
        """Empty skill string also falls back to _run_intent."""
        agent = ResourceAgent()
        mock_connector = AsyncMock()
        mock_connector.execute_query = AsyncMock(return_value=_make_query_result(ACTIVE_COLUMNS))

        params = {
            "_refine_mode": True,
            "_prior_sql": ACTIVE_SQL_WITH_ORDER_BY,
            "_prior_columns": ACTIVE_COLUMNS,
            "skill": "",  # empty string — falsy
        }
        state = _make_state("active_resources", params)

        with patch.object(
            agent, "_run_intent", new=AsyncMock(return_value=("SELECT 1", _make_query_result()))
        ) as mock_run_intent:
            await agent._run_refinement(ACTIVE_SQL_WITH_ORDER_BY, params, mock_connector, state)
            mock_run_intent.assert_called_once()
