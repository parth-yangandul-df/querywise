"""Tests for sql_compiler.py — deterministic SQL compiler for QueryPlan.

Tests the 12 behaviors specified in 07-03-PLAN.md.
"""

from __future__ import annotations

import pytest
from app.llm.graph.nodes.sql_compiler import (
    BASE_QUERIES,
    build_filter_clause,
    build_in_clause,
    compile_query,
)
from app.llm.graph.query_plan import FilterClause, QueryPlan

from app.llm.graph.nodes.field_registry import FIELD_REGISTRY


def _make_plan(
    domain: str = "resource",
    intent: str = "active_resources",
    filters: list | None = None,
) -> QueryPlan:
    """Helper: build a minimal QueryPlan."""
    return QueryPlan(
        domain=domain,
        intent=intent,
        filters=filters or [],
        base_intent_sql="",
        schema_version=1,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: compile_query() with empty filters → returns base_intent_sql unchanged
# ─────────────────────────────────────────────────────────────────────────────


def test_compile_query_empty_filters_returns_base_sql():
    """Empty filters → base SQL returned with no WHERE clause appended (tokens replaced)."""
    plan = _make_plan(intent="active_resources")
    sql, params = compile_query(plan)
    assert params == ()
    # Base SQL for active_resources should contain key clauses
    assert "IsActive" in sql or "Resource" in sql
    # Tokens must be replaced (empty string by default)
    assert "{select_extras}" not in sql
    assert "{join_extras}" not in sql
    # Should equal the base query with empty tokens replaced
    expected = (
        BASE_QUERIES["active_resources"].replace("{select_extras}", "").replace("{join_extras}", "")
    )
    assert sql == expected


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: compile_query() with single eq filter → adds WHERE field=?
# ─────────────────────────────────────────────────────────────────────────────


def test_compile_query_single_eq_filter():
    """Single eq filter on resource_name → adds WHERE name LIKE ?."""
    plan = _make_plan(
        intent="active_resources",
        filters=[FilterClause(field="resource_name", op="eq", values=["John"])],
    )
    sql, params = compile_query(plan)
    assert len(params) >= 1
    assert "WHERE" in sql or "where" in sql.lower()
    # resource_name is text type → should use LIKE with % wrapping
    assert "%John%" in params or any("John" in str(p) for p in params)


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: compile_query() with multi-value in filter → adds WHERE field IN (?,?,?)
# ─────────────────────────────────────────────────────────────────────────────


def test_compile_query_multi_value_in_filter():
    """IN filter with multiple values → WHERE IN (?,?,?) or multiple LIKE clauses."""
    plan = _make_plan(
        intent="resource_by_skill",
        filters=[FilterClause(field="skill", op="in", values=["Python", "Java", "Go"])],
    )
    sql, params = compile_query(plan)
    # Should have 3 parameter placeholders for the IN clause
    assert len(params) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: compile_query() with date between filter → adds WHERE field BETWEEN ? AND ?
# ─────────────────────────────────────────────────────────────────────────────


def test_compile_query_date_between_filter():
    """Between filter on date field → WHERE WorkDate BETWEEN ? AND ?."""
    plan = _make_plan(
        domain="timesheet",
        intent="approved_timesheets",
        filters=[
            FilterClause(
                field="start_date",
                op="between",
                values=["2024-01-01", "2024-06-30"],
            )
        ],
    )
    sql, params = compile_query(plan)
    assert "BETWEEN" in sql
    assert len(params) == 2
    assert "2024-01-01" in params
    assert "2024-06-30" in params


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: compile_query() with numeric gt filter → adds WHERE field >= ?
# ─────────────────────────────────────────────────────────────────────────────


def test_compile_query_numeric_gt_filter():
    """GT filter on min_hours → WHERE Hours >= ?."""
    plan = _make_plan(
        domain="timesheet",
        intent="approved_timesheets",
        filters=[FilterClause(field="min_hours", op="gt", values=["8"])],
    )
    sql, params = compile_query(plan)
    assert ">=" in sql or ">" in sql
    assert "8" in params or 8 in params


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: build_in_clause([]) → returns "1=0" with empty params
# ─────────────────────────────────────────────────────────────────────────────


def test_build_in_clause_empty_values():
    """Empty values list → always-false clause."""
    clause, params = build_in_clause("Name", [])
    assert clause == "1=0"
    assert params == ()


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: build_in_clause(["x"]) → returns "field=?" with single param
# ─────────────────────────────────────────────────────────────────────────────


def test_build_in_clause_single_value():
    """Single value → collapses to equality."""
    clause, params = build_in_clause("Name", ["Alice"])
    assert clause == "Name=?"
    assert params == ("Alice",)


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: build_in_clause([>2000 values]) → raises ValueError
# ─────────────────────────────────────────────────────────────────────────────


def test_build_in_clause_exceeds_limit():
    """More than 2000 values → ValueError."""
    with pytest.raises(ValueError, match="2000"):
        build_in_clause("Name", [str(i) for i in range(2001)])


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: compile_query(plan.domain="user_self", resource_id=None) → raises ValueError
# ─────────────────────────────────────────────────────────────────────────────


def test_compile_query_user_self_requires_resource_id():
    """RBAC guard: user_self domain without resource_id → ValueError."""
    plan = _make_plan(domain="user_self", intent="my_projects")
    with pytest.raises(ValueError, match="resource_id"):
        compile_query(plan, resource_id=None)


def test_compile_query_user_self_with_resource_id_ok():
    """RBAC guard: user_self domain WITH resource_id → no error."""
    plan = _make_plan(domain="user_self", intent="my_projects")
    sql, params = compile_query(plan, resource_id=42)
    assert "?" in sql  # parameterized
    assert 42 in params


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: compile_query() with {select_extras}/{join_extras} tokens replaced
# ─────────────────────────────────────────────────────────────────────────────


def test_compile_query_token_replacement():
    """{select_extras} and {join_extras} tokens are replaced in output SQL."""
    plan = _make_plan(intent="active_resources")
    sql, _params = compile_query(
        plan,
        select_extras=", COUNT(*) AS total",
        join_extras=" LEFT JOIN Metrics m ON m.Id = r.Id",
    )
    assert "{select_extras}" not in sql
    assert "{join_extras}" not in sql
    assert "COUNT(*)" in sql
    assert "LEFT JOIN Metrics" in sql


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: BASE_QUERIES contains all 24 active intent SQL templates
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_INTENTS = {
    # Resource (6)
    "active_resources",
    "benched_resources",
    "resource_by_skill",
    "resource_availability",
    "resource_project_assignments",
    "resource_skills_list",
    # Client (3)
    "active_clients",
    "client_projects",
    "client_status",
    # Project (6)
    "active_projects",
    "project_by_client",
    "project_budget",
    "project_resources",
    "project_timeline",
    "overdue_projects",
    # Timesheet (4)
    "approved_timesheets",
    "timesheet_by_period",
    "unapproved_timesheets",
    "timesheet_by_project",
    # User Self (5)
    "my_projects",
    "my_allocation",
    "my_timesheets",
    "my_skills",
    "my_utilization",
}


def test_base_queries_contains_all_24_intents():
    """BASE_QUERIES must have all 24 active PRMS intent SQL templates."""
    assert EXPECTED_INTENTS == set(BASE_QUERIES.keys()), (
        f"Missing: {EXPECTED_INTENTS - set(BASE_QUERIES.keys())}\n"
        f"Extra: {set(BASE_QUERIES.keys()) - EXPECTED_INTENTS}"
    )


def test_base_queries_contain_token_placeholders():
    """All BASE_QUERIES templates must have {select_extras} and {join_extras} tokens."""
    for intent, sql in BASE_QUERIES.items():
        assert "{select_extras}" in sql, f"Missing {{select_extras}} in {intent}"
        assert "{join_extras}" in sql, f"Missing {{join_extras}} in {intent}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: Deferred intents excluded with #baadme comment
# ─────────────────────────────────────────────────────────────────────────────

DEFERRED_INTENTS = {
    "resource_utilization",
    "resource_billing_rate",
    "resource_timesheet_summary",
}


def test_deferred_intents_excluded():
    """Deferred intents must NOT be in BASE_QUERIES (they're commented out #baadme)."""
    for intent in DEFERRED_INTENTS:
        assert intent not in BASE_QUERIES, (
            f"Deferred intent '{intent}' should not be in BASE_QUERIES"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Test: build_filter_clause for all supported ops
# ─────────────────────────────────────────────────────────────────────────────


def test_build_filter_clause_eq_text():
    """eq on text field → LIKE with % wrapping."""
    fc = FIELD_REGISTRY["resource_name"]
    clause, params = build_filter_clause(
        FilterClause(field="resource_name", op="eq", values=["Alice"]), fc
    )
    assert "LIKE" in clause
    assert "%Alice%" in params


def test_build_filter_clause_eq_numeric():
    """eq on numeric field → = ? with raw value."""
    fc = FIELD_REGISTRY["min_hours"]
    clause, params = build_filter_clause(FilterClause(field="min_hours", op="eq", values=["8"]), fc)
    assert "=" in clause
    assert "8" in params


def test_build_filter_clause_between_date():
    """between on date field → BETWEEN ? AND ?."""
    fc = FIELD_REGISTRY["start_date"]
    clause, params = build_filter_clause(
        FilterClause(field="start_date", op="between", values=["2024-01-01", "2024-12-31"]), fc
    )
    assert "BETWEEN" in clause
    assert len(params) == 2


def test_build_filter_clause_gt_numeric():
    """gt on numeric → >= ?."""
    fc = FIELD_REGISTRY["min_budget"]
    clause, params = build_filter_clause(
        FilterClause(field="min_budget", op="gt", values=["100000"]), fc
    )
    assert ">=" in clause
    assert "100000" in params


def test_build_filter_clause_lt_numeric():
    """lt on numeric → < ?."""
    fc = FIELD_REGISTRY["min_budget"]
    clause, params = build_filter_clause(
        FilterClause(field="min_budget", op="lt", values=["50000"]), fc
    )
    assert "<" in clause
    assert "50000" in params


def test_build_filter_clause_in_text():
    """in on text field → IN (?,?,?) for multi-value."""
    fc = FIELD_REGISTRY["resource_name"]
    clause, params = build_filter_clause(
        FilterClause(field="resource_name", op="in", values=["Alice", "Bob"]), fc
    )
    assert len(params) == 2


def test_build_filter_clause_boolean():
    """boolean field → = ? with 1/0."""
    fc = FIELD_REGISTRY["billable"]
    clause, params = build_filter_clause(
        FilterClause(field="billable", op="eq", values=["true"]), fc
    )
    assert "=" in clause
    # Should coerce to 1/0
    assert 1 in params or "1" in params
