"""E2E tests for the natural language query pipeline."""

import httpx

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_query(client: httpx.Client, connection_id: str, question: str, **kwargs) -> dict:
    payload = {"connection_id": connection_id, "question": question, **kwargs}
    resp = client.post("/api/v1/query", json=payload)
    assert resp.status_code == 200, f"Query failed [{resp.status_code}]: {resp.text}"
    return resp.json()


def _assert_query_response_shape(data: dict) -> None:
    """Assert the response has all required top-level fields."""
    required = {"id", "question", "columns", "column_types", "rows", "row_count"}
    missing = required - data.keys()
    assert not missing, f"Response missing fields: {missing}"
    assert isinstance(data["rows"], list)
    assert isinstance(data["columns"], list)
    assert data["row_count"] == len(data["rows"])
    # Clarification turns have no SQL
    if data.get("turn_type", "query") == "query":
        assert data.get("generated_sql"), "generated_sql should not be empty for query turns"


# ---------------------------------------------------------------------------
# Basic intent tests
# ---------------------------------------------------------------------------


class TestBasicIntents:
    def test_active_resources_query(self, user_client: httpx.Client, connection_id: str) -> None:
        data = _post_query(user_client, connection_id, "Show me all active resources")
        _assert_query_response_shape(data)
        sql = data["generated_sql"].upper()
        # Should filter on active status
        assert "ISACTIVE" in sql or "IS_ACTIVE" in sql or "ACTIVE" in sql

    def test_active_projects_query(self, user_client: httpx.Client, connection_id: str) -> None:
        data = _post_query(user_client, connection_id, "List all active projects")
        _assert_query_response_shape(data)

    def test_active_clients_query(self, user_client: httpx.Client, connection_id: str) -> None:
        data = _post_query(user_client, connection_id, "Show me all active clients")
        _assert_query_response_shape(data)

    def test_benched_resources_query(self, user_client: httpx.Client, connection_id: str) -> None:
        data = _post_query(user_client, connection_id, "Who is on the bench right now?")
        _assert_query_response_shape(data)

    def test_skill_filter_query(self, user_client: httpx.Client, connection_id: str) -> None:
        data = _post_query(user_client, connection_id, "List all Python developers")
        _assert_query_response_shape(data)
        # SQL should mention Python as a filter value
        assert "python" in data["generated_sql"].lower()

    def test_overdue_projects_query(self, user_client: httpx.Client, connection_id: str) -> None:
        data = _post_query(user_client, connection_id, "Which projects are overdue?")
        _assert_query_response_shape(data)
        sql = data["generated_sql"].upper()
        # Should have a date comparison
        assert any(kw in sql for kw in ["ENDDATE", "END_DATE", "GETDATE", "NOW()", "CURRENT_DATE"])

    def test_query_returns_suggested_followups(
        self, user_client: httpx.Client, connection_id: str
    ) -> None:
        data = _post_query(user_client, connection_id, "Show active clients")
        assert "suggested_followups" in data
        assert isinstance(data["suggested_followups"], list)

    def test_query_includes_turn_type(self, user_client: httpx.Client, connection_id: str) -> None:
        data = _post_query(user_client, connection_id, "Show me all active resources")
        assert "turn_type" in data
        assert data["turn_type"] in ("query", "show_sql", "explain_result", "clarification")


# ---------------------------------------------------------------------------
# Multi-turn context tests
# ---------------------------------------------------------------------------


class TestMultiTurnConversation:
    def test_refinement_adds_filter(self, user_client: httpx.Client, connection_id: str) -> None:
        """A follow-up query should narrow the results, not return the same thing."""
        first = _post_query(user_client, connection_id, "Show me all active projects")
        _assert_query_response_shape(first)
        first_ctx = first.get("turn_context")

        second = _post_query(
            user_client,
            connection_id,
            "Now filter to only those starting this year",
            conversation_history=[
                {"role": "user", "content": "Show me all active projects"},
                {"role": "assistant", "content": first["explanation"]},
            ],
            last_turn_context=first_ctx,
        )
        _assert_query_response_shape(second)
        # The refined SQL should differ from the original
        assert second["generated_sql"] != first["generated_sql"]

    def test_refinement_adds_filter(
        self, user_client: httpx.Client, connection_id: str, session_id: str
    ) -> None:
        """A follow-up query within a session should use loaded history for context."""
        first = _post_query(
            user_client, connection_id, "Show me all active projects", session_id=session_id
        )
        _assert_query_response_shape(first)

        second = _post_query(
            user_client,
            connection_id,
            "Now filter to only those starting this year",
            session_id=session_id,
        )
        _assert_query_response_shape(second)
        # The refined SQL should differ from the original
        assert second.get("generated_sql") != first.get("generated_sql")

    def test_explicit_clear_context_flag(
        self, user_client: httpx.Client, connection_id: str, session_id: str
    ) -> None:
        """clear_context=True must produce a fresh query ignoring prior turn."""
        _post_query(user_client, connection_id, "Show me benched resources", session_id=session_id)

        second = _post_query(
            user_client,
            connection_id,
            "Show me all active clients",
            session_id=session_id,
            clear_context=True,
        )
        _assert_query_response_shape(second)

    def test_invalid_connection_id(self, user_client: httpx.Client) -> None:
        import uuid

        resp = user_client.post(
            "/api/v1/query",
            json={"connection_id": str(uuid.uuid4()), "question": "Show active projects"},
        )
        # Should fail cleanly — not 500
        assert resp.status_code in (400, 404, 422)

    def test_malformed_connection_id(self, user_client: httpx.Client) -> None:
        resp = user_client.post(
            "/api/v1/query",
            json={"connection_id": "not-a-uuid", "question": "Show active projects"},
        )
        assert resp.status_code == 422

    def test_sql_injection_attempt(self, user_client: httpx.Client, connection_id: str) -> None:
        """SQL injection in natural language question must not cause unhandled errors."""
        resp = user_client.post(
            "/api/v1/query",
            json={
                "connection_id": connection_id,
                "question": "Show resources; DROP TABLE resources --",
            },
        )
        # Should either succeed with safe SQL or return an error — never 500
        assert resp.status_code != 500, "SQL injection caused a 500 error"
        if resp.status_code == 200:
            data = resp.json()
            sql = data["generated_sql"].upper()
            assert "DROP" not in sql, "Generated SQL contains DROP statement"
            assert "DELETE" not in sql, "Generated SQL contains DELETE statement"


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------


class TestQueryAuth:
    def test_query_requires_auth(self, base_url: str, connection_id: str) -> None:
        with httpx.Client(base_url=base_url, timeout=15) as client:
            resp = client.post(
                "/api/v1/query",
                json={"connection_id": connection_id, "question": "Show active projects"},
            )
        assert resp.status_code in (401, 403)
