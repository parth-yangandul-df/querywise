"""Tests for schema_linker.py — SQL Server-oriented scenarios.

Strategy:
- Pure-Python helpers (_detect_anchor_tables, scoring functions, extract_keywords)
  are tested directly without any DB.
- The async find_relevant_tables function is tested via lightweight mocks so the
  test suite can run without a live PostgreSQL connection.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.semantic.relevance_scorer import (
    ANCHOR_TABLE_SIGNALS,
    column_keyword_score,
    extract_keywords,
    keyword_match_score,
)
from app.semantic.schema_linker import LinkedTable, _detect_anchor_tables

# ---------------------------------------------------------------------------
# Helpers: extract_keywords
# ---------------------------------------------------------------------------


class TestExtractKeywords:
    def test_filters_stop_words(self):
        kws = extract_keywords("show me all the clients")
        assert "the" not in kws
        assert "me" not in kws
        assert "all" not in kws
        assert "show" not in kws

    def test_keeps_domain_nouns(self):
        kws = extract_keywords("list all active clients by project")
        assert "clients" in kws or "client" in kws
        assert "project" in kws

    def test_lowercases_output(self):
        kws = extract_keywords("Show Active Clients")
        assert all(k == k.lower() for k in kws)

    def test_empty_question(self):
        assert extract_keywords("") == []

    def test_short_words_filtered(self):
        kws = extract_keywords("a b c go do")
        # single characters should be excluded (len > 1 required)
        assert "a" not in kws
        assert "b" not in kws

    def test_retains_multi_char_words(self):
        kws = extract_keywords("resource reporting manager")
        assert "resource" in kws
        assert "reporting" in kws
        assert "manager" in kws


# ---------------------------------------------------------------------------
# Helpers: keyword_match_score
# ---------------------------------------------------------------------------


class TestKeywordMatchScore:
    def test_exact_match_returns_1(self):
        assert keyword_match_score("client", ["client"]) == 1.0

    def test_substring_match_returns_05(self):
        # "clients" contains "client"
        score = keyword_match_score("clients", ["client"])
        assert score == 0.5

    def test_underscore_separated_part_returns_05(self):
        # "status" is both a substring of "project_status" AND a part after splitting by "_".
        # The substring check fires first in the implementation, so the result is 0.5.
        score = keyword_match_score("project_status", ["status"])
        assert score == 0.5

    def test_no_match_returns_0(self):
        assert keyword_match_score("resource", ["invoice"]) == 0.0

    def test_empty_keywords(self):
        assert keyword_match_score("client", []) == 0.0


# ---------------------------------------------------------------------------
# Helpers: column_keyword_score
# ---------------------------------------------------------------------------


class TestColumnKeywordScore:
    def test_camelcase_status_id_matches_status(self):
        """StatusId should match keyword 'status' via CamelCase splitting."""
        score = column_keyword_score(["StatusId", "ClientId"], ["status"])
        assert score == 0.8

    def test_exact_column_name_returns_08(self):
        score = column_keyword_score(["status"], ["status"])
        assert score == 0.8

    def test_partial_column_substring_returns_04(self):
        # "ProjectStatusId" — 'proj' is a substring but not a CamelCase part
        score = column_keyword_score(["ProjectStatusId"], ["proj"])
        assert score == 0.4

    def test_no_match_returns_0(self):
        score = column_keyword_score(["ClientId", "ClientName"], ["invoice"])
        assert score == 0.0

    def test_empty_columns_returns_0(self):
        assert column_keyword_score([], ["status"]) == 0.0

    def test_empty_keywords_returns_0(self):
        assert column_keyword_score(["StatusId"], []) == 0.0

    def test_client_id_matches_client(self):
        score = column_keyword_score(["ClientId"], ["client"])
        assert score == 0.8

    def test_resource_id_matches_resource(self):
        score = column_keyword_score(["ResourceId", "ReportingTo"], ["resource"])
        assert score == 0.8

    def test_reporting_to_matches_reporting(self):
        score = column_keyword_score(["ReportingTo"], ["reporting"])
        assert score == 0.8


# ---------------------------------------------------------------------------
# Helpers: ANCHOR_TABLE_SIGNALS & _detect_anchor_tables
# ---------------------------------------------------------------------------


class TestAnchorTableSignals:
    def test_client_keyword_maps_to_client_table(self):
        result = _detect_anchor_tables("list all clients", ["clients", "client"])
        assert "Client" in result

    def test_project_keyword_maps_to_project_table(self):
        result = _detect_anchor_tables("show me all projects", ["projects", "project"])
        assert "Project" in result

    def test_resource_keyword_maps_to_resource_table(self):
        result = _detect_anchor_tables(
            "active resources by department", ["active", "resources", "resource"]
        )
        assert "Resource" in result

    def test_manager_maps_to_resource_table(self):
        result = _detect_anchor_tables("who is the manager", ["manager"])
        assert "Resource" in result

    def test_employee_maps_to_resource_table(self):
        result = _detect_anchor_tables("list employees", ["employees", "employee"])
        assert "Resource" in result

    def test_status_maps_to_status_table(self):
        result = _detect_anchor_tables(
            "clients with active status", ["clients", "active", "status"]
        )
        assert "Status" in result

    def test_direct_report_multi_word_signal(self):
        """'direct report' is a multi-word signal matched against the full question."""
        result = _detect_anchor_tables(
            "who are the direct reports of this manager", ["direct", "reports", "manager"]
        )
        assert "Resource" in result

    def test_unrelated_question_returns_empty(self):
        result = _detect_anchor_tables("what is the weather today", ["weather", "today"])
        assert result == []

    def test_no_duplicate_tables_in_result(self):
        """'manager' and 'resource' both map to Resource — should appear once."""
        result = _detect_anchor_tables(
            "list all resources and their managers",
            ["resources", "resource", "managers", "manager"],
        )
        assert result.count("Resource") == 1

    def test_anchor_signals_dict_has_expected_keys(self):
        expected_keys = {
            "client",
            "project",
            "resource",
            "employee",
            "status",
            "manager",
            "reporting",
            "direct report",
        }
        assert expected_keys.issubset(set(ANCHOR_TABLE_SIGNALS.keys()))


# ---------------------------------------------------------------------------
# find_relevant_tables — async integration-level tests with mocked DB
# ---------------------------------------------------------------------------


def _make_table(name: str, conn_id: uuid.UUID) -> MagicMock:
    """Return a mock CachedTable with the minimum attributes schema_linker uses."""
    t = MagicMock()
    t.id = uuid.uuid4()
    t.table_name = name
    t.connection_id = conn_id
    t.description_embedding = None
    return t


def _make_column(table_id: uuid.UUID, name: str, ordinal: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        table_id=table_id,
        column_name=name,
        ordinal_position=ordinal,
    )


def _make_scalars_result(items: list) -> MagicMock:
    """Mock an execute() result whose .scalars().all() returns `items`."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = items
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock


class TestFindRelevantTablesAsync:
    """Async tests for find_relevant_tables with mocked SQLAlchemy session."""

    @pytest.fixture
    def conn_id(self) -> uuid.UUID:
        return uuid.uuid4()

    @pytest.fixture
    def client_table(self, conn_id):
        return _make_table("Client", conn_id)

    @pytest.fixture
    def status_table(self, conn_id):
        return _make_table("Status", conn_id)

    @pytest.fixture
    def project_table(self, conn_id):
        return _make_table("Project", conn_id)

    @pytest.fixture
    def resource_table(self, conn_id):
        return _make_table("Resource", conn_id)

    def _build_session(
        self,
        conn_id: uuid.UUID,
        tables_by_name: dict[str, MagicMock],
        keyword_hits: list[Any] | None = None,
        column_hits: list[Any] | None = None,
        columns_per_table: dict[uuid.UUID, list[Any]] | None = None,
    ) -> AsyncMock:
        """Build a mock AsyncSession that returns preset data for each query stage."""
        keyword_hits = keyword_hits or []
        column_hits = column_hits or []
        columns_per_table = columns_per_table or {}

        session = AsyncMock()

        # db.get(CachedTable, id) — return the table matching the UUID
        id_to_table = {t.id: t for t in tables_by_name.values()}

        async def fake_get(model_class: Any, pk: uuid.UUID) -> Any:
            return id_to_table.get(pk)

        session.get = fake_get

        # db.execute() calls when question_embedding=None (vector search is skipped):
        # call #1: keyword search on table names   (_keyword_search_tables)
        # call #2: column keyword search            (_column_keyword_search_tables JOIN)
        # call #3: relationship expansion           (_get_related_tables)
        # call #4+: column loading per selected table (one SELECT per table)
        call_count = 0

        async def fake_execute(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Keyword table name search
                return _make_scalars_result(keyword_hits)
            elif call_count == 2:
                # Column keyword search — return matching CachedColumn objects
                return _make_scalars_result(column_hits)
            elif call_count == 3:
                # Relationship expansion — empty (no FK records in tests)
                return _make_scalars_result([])
            else:
                # Column loading for a specific table (one call per selected table)
                return _make_scalars_result([])

        session.execute = fake_execute
        return session

    @pytest.mark.asyncio
    async def test_keyword_hit_on_client_returns_client_table(
        self, conn_id, client_table, status_table
    ):
        from app.semantic.schema_linker import find_relevant_tables

        columns_for_client = [
            _make_column(client_table.id, "ClientId"),
            _make_column(client_table.id, "StatusId"),
        ]
        session = self._build_session(
            conn_id,
            {"Client": client_table, "Status": status_table},
            keyword_hits=[client_table],
        )

        results = await find_relevant_tables(
            db=session,
            connection_id=conn_id,
            question_embedding=None,
            question="show all clients",
        )

        table_names = [r.table.table_name for r in results]
        assert "Client" in table_names

    @pytest.mark.asyncio
    async def test_anchor_forcing_injects_status_for_status_keyword(self, conn_id, status_table):
        """When 'status' appears in the question, Status table must be injected."""
        from app.semantic.schema_linker import find_relevant_tables

        # Status is NOT in keyword_hits — only anchor forcing should pull it in
        session = self._build_session(
            conn_id,
            {"Status": status_table},
            keyword_hits=[],
        )

        # Patch _get_tables_by_names to return Status table for anchor forcing
        with patch(
            "app.semantic.schema_linker._get_tables_by_names",
            new=AsyncMock(return_value=[status_table]),
        ):
            results = await find_relevant_tables(
                db=session,
                connection_id=conn_id,
                question_embedding=None,
                question="show clients with their status labels",
            )

        table_names = [r.table.table_name for r in results]
        assert "Status" in table_names

    @pytest.mark.asyncio
    async def test_column_keyword_hit_returns_table(self, conn_id, client_table):
        """A table whose column name matches a keyword should be selected."""
        from app.semantic.schema_linker import find_relevant_tables

        status_col = _make_column(client_table.id, "StatusId")
        session = self._build_session(
            conn_id,
            {"Client": client_table},
            keyword_hits=[],
            column_hits=[status_col],
        )

        results = await find_relevant_tables(
            db=session,
            connection_id=conn_id,
            question_embedding=None,
            question="show clients with status information",
        )

        table_names = [r.table.table_name for r in results]
        assert "Client" in table_names

    @pytest.mark.asyncio
    async def test_returns_linked_table_instances(self, conn_id, client_table):
        from app.semantic.schema_linker import find_relevant_tables

        session = self._build_session(
            conn_id,
            {"Client": client_table},
            keyword_hits=[client_table],
        )

        results = await find_relevant_tables(
            db=session,
            connection_id=conn_id,
            question_embedding=None,
            question="clients",
        )

        assert all(isinstance(r, LinkedTable) for r in results)

    @pytest.mark.asyncio
    async def test_max_tables_limits_output(
        self, conn_id, client_table, project_table, resource_table
    ):
        from app.semantic.schema_linker import find_relevant_tables

        session = self._build_session(
            conn_id,
            {"Client": client_table, "Project": project_table, "Resource": resource_table},
            keyword_hits=[client_table, project_table, resource_table],
        )

        results = await find_relevant_tables(
            db=session,
            connection_id=conn_id,
            question_embedding=None,
            question="clients projects resources",
            max_tables=2,
        )

        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_no_results_for_empty_question(self, conn_id):
        from app.semantic.schema_linker import find_relevant_tables

        session = self._build_session(conn_id, {})

        results = await find_relevant_tables(
            db=session,
            connection_id=conn_id,
            question_embedding=None,
            question="",
        )

        assert results == []
