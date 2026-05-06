"""
E2E test for the full query pipeline happy path.

Tests the sequence: login → list connections → create session → run query → check history.
"""

import httpx


def test_full_query_pipeline(
    user_client: httpx.Client,
    admin_client: httpx.Client,
    connection_id: str,
) -> None:
    """
    Scenario: A user logs in, picks a connection, creates a session,
    asks a question, and sees the result in history.
    """
    # 1. Verify connection is reachable
    conn_resp = admin_client.get(f"/api/v1/connections/{connection_id}")
    assert conn_resp.status_code == 200
    conn = conn_resp.json()
    assert conn["is_active"] is True, "Target connection is not active"

    # 2. Create a chat session
    session_resp = user_client.post(
        "/api/v1/sessions",
        json={"connection_id": connection_id, "title": "E2E Pipeline Test"},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    # 3. Ask a question in that session
    query_resp = user_client.post(
        "/api/v1/query",
        json={
            "connection_id": connection_id,
            "question": "Show me all active projects",
            "session_id": session_id,
        },
    )
    assert query_resp.status_code == 200, f"Query failed: {query_resp.text}"
    result = query_resp.json()

    # 4. Validate full response shape
    assert result["question"] == "Show me all active projects"
    assert len(result["generated_sql"]) > 0
    assert isinstance(result["rows"], list)
    assert result["row_count"] == len(result["rows"])
    assert result["execution_time_ms"] >= 0

    # 5. Verify the result appears in session messages
    msg_resp = user_client.get(f"/api/v1/sessions/{session_id}/messages")
    assert msg_resp.status_code == 200
    messages = msg_resp.json()
    assert len(messages) >= 1

    # 6. Verify it appears in query history
    history_resp = user_client.get(f"/api/v1/query-history?connection_id={connection_id}&limit=5")
    assert history_resp.status_code == 200
    history_ids = [h["id"] for h in history_resp.json()]
    assert str(result["id"]) in history_ids


def test_multi_turn_pipeline(user_client: httpx.Client, connection_id: str) -> None:
    """
    Scenario: User asks a question, then refines it in the next turn.
    Both turns should produce valid SQL and the second should differ from the first.
    Backend loads history from session — no client-side context needed.
    """
    # Create a session for this multi-turn test
    session_resp = user_client.post("/api/v1/sessions", json={"title": "multi-turn test"})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    # Turn 1
    t1_resp = user_client.post(
        "/api/v1/query",
        json={
            "connection_id": connection_id,
            "question": "Show me all active clients",
            "session_id": session_id,
        },
    )
    assert t1_resp.status_code == 200
    t1 = t1_resp.json()

    # Turn 2 — refine using same session_id; backend loads history automatically
    t2_resp = user_client.post(
        "/api/v1/query",
        json={
            "connection_id": connection_id,
            "question": "Now only show the ones in Bangalore",
            "session_id": session_id,
        },
    )
    assert t2_resp.status_code == 200
    t2 = t2_resp.json()

    # SQL must have changed (refinement applied)
    assert t2.get("generated_sql") != t1.get("generated_sql"), (
        "Refinement produced identical SQL — context was not applied"
    )
