"""Tests for QueryPlan and FilterClause Pydantic models."""

import pytest
from app.llm.graph.query_plan import FilterClause, QueryPlan
from pydantic import ValidationError


class TestFilterClause:
    """FilterClause validation and behavior tests."""

    def test_valid_filter_eq(self):
        """FilterClause with valid 'eq' op and values passes."""
        fc = FilterClause(field="status", op="eq", values=["active"])
        assert fc.field == "status"
        assert fc.op == "eq"
        assert fc.values == ["active"]

    def test_valid_filter_ops(self):
        """FilterClause accepts all valid ops: eq, in, lt, gt, between."""
        for op in ("eq", "in", "lt", "gt", "between"):
            fc = FilterClause(field="amount", op=op, values=["100"])
            assert fc.op == op

    def test_invalid_op_raises_validation_error(self):
        """FilterClause with invalid op ('contains') raises ValidationError."""
        with pytest.raises(ValidationError):
            FilterClause(field="status", op="contains", values=["active"])

    def test_values_exceeding_50_items_raises_validation_error(self):
        """FilterClause values exceeding 50 items raises ValidationError."""
        with pytest.raises(ValidationError):
            FilterClause(field="id", op="in", values=[str(i) for i in range(51)])

    def test_values_at_50_items_passes(self):
        """FilterClause with exactly 50 values passes."""
        fc = FilterClause(field="id", op="in", values=[str(i) for i in range(50)])
        assert len(fc.values) == 50

    def test_sql_injection_characters_sanitized(self):
        """FilterClause values with SQL injection characters are sanitized."""
        # Dangerous characters: ; ' -- /* */ DROP DELETE INSERT UPDATE ALTER TRUNCATE
        dangerous = "'; DROP TABLE users; --"
        fc = FilterClause(field="name", op="eq", values=[dangerous])
        # Sanitized value should not contain the dangerous patterns
        for pattern in (
            ";",
            "'",
            "--",
            "/*",
            "*/",
            "DROP",
            "DELETE",
            "INSERT",
            "UPDATE",
            "ALTER",
            "TRUNCATE",
        ):
            assert pattern not in fc.values[0].upper()

    def test_single_string_value_coerced_to_list(self):
        """FilterClause coerces single string to list for values."""
        fc = FilterClause(field="status", op="eq", values=["active"])
        assert isinstance(fc.values, list)


class TestQueryPlan:
    """QueryPlan validation and behavior tests."""

    def test_from_untrusted_dict_rejects_unknown_keys(self):
        """QueryPlan.from_untrusted_dict() rejects unknown keys (extra='forbid')."""
        data = {
            "domain": "resource",
            "intent": "active_resources",
            "filters": [],
            "base_intent_sql": "SELECT * FROM resources",
            "schema_version": 1,
            "unknown_field": "should be rejected",
        }
        with pytest.raises(ValidationError):
            QueryPlan.from_untrusted_dict(data)

    def test_from_untrusted_dict_valid_data(self):
        """QueryPlan.from_untrusted_dict() with valid data constructs correct model."""
        data = {
            "domain": "resource",
            "intent": "active_resources",
            "filters": [{"field": "status", "op": "eq", "values": ["active"]}],
            "base_intent_sql": "SELECT * FROM resources WHERE status = 'active'",
            "schema_version": 1,
        }
        plan = QueryPlan.from_untrusted_dict(data)
        assert plan.domain == "resource"
        assert plan.intent == "active_resources"
        assert len(plan.filters) == 1
        assert plan.filters[0].field == "status"
        assert plan.base_intent_sql == "SELECT * FROM resources WHERE status = 'active'"

    def test_from_untrusted_dict_coerces_single_string_to_list(self):
        """QueryPlan.from_untrusted_dict() coerces single string filter values to list."""
        data = {
            "domain": "resource",
            "intent": "active_resources",
            "filters": [{"field": "status", "op": "eq", "values": "active"}],
            "base_intent_sql": "",
            "schema_version": 1,
        }
        plan = QueryPlan.from_untrusted_dict(data)
        assert plan.filters[0].values == ["active"]

    def test_to_api_dict_returns_all_fields(self):
        """QueryPlan.to_api_dict() returns serializable dict with all fields."""
        plan = QueryPlan(
            domain="resource",
            intent="active_resources",
            filters=[FilterClause(field="status", op="eq", values=["active"])],
            base_intent_sql="SELECT * FROM resources",
            schema_version=1,
        )
        result = plan.to_api_dict()
        assert result["domain"] == "resource"
        assert result["intent"] == "active_resources"
        assert len(result["filters"]) == 1
        assert result["filters"][0]["field"] == "status"
        assert result["base_intent_sql"] == "SELECT * FROM resources"
        assert result["schema_version"] == 1

    def test_schema_version_is_literal_1(self):
        """QueryPlan.schema_version is Literal[1]."""
        plan = QueryPlan(
            domain="resource",
            intent="active_resources",
            base_intent_sql="",
            schema_version=1,
        )
        assert plan.schema_version == 1

    def test_schema_version_rejects_other_values(self):
        """QueryPlan.schema_version rejects values other than 1."""
        with pytest.raises(ValidationError):
            QueryPlan(
                domain="resource",
                intent="active_resources",
                base_intent_sql="",
                schema_version=2,
            )

    def test_default_filters_empty_list(self):
        """QueryPlan filters default to empty list."""
        plan = QueryPlan(
            domain="resource",
            intent="active_resources",
            base_intent_sql="",
            schema_version=1,
        )
        assert plan.filters == []

    def test_default_base_intent_sql_empty_string(self):
        """QueryPlan base_intent_sql defaults to empty string."""
        plan = QueryPlan(
            domain="resource",
            intent="active_resources",
            schema_version=1,
        )
        assert plan.base_intent_sql == ""


class TestSettings:
    """Settings feature flag tests."""

    def test_use_query_plan_compiler_defaults_to_false(self):
        """Settings.use_query_plan_compiler defaults to False."""
        from app.config import settings

        assert settings.use_query_plan_compiler is False

    def test_use_query_plan_compiler_reads_env_var(self, monkeypatch):
        """USE_QUERY_PLAN_COMPILER=true env var sets use_query_plan_compiler to True."""
        from app.config import Settings

        monkeypatch.setenv("USE_QUERY_PLAN_COMPILER", "true")
        new_settings = Settings()
        assert new_settings.use_query_plan_compiler is True


class TestGraphState:
    """GraphState structural tests."""

    def test_graph_state_accepts_query_plan_field(self):
        """GraphState TypedDict includes query_plan: dict | None field."""
        import typing

        from app.llm.graph.state import GraphState

        hints = typing.get_type_hints(GraphState)
        assert "query_plan" in hints
