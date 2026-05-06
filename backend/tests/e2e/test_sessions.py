"""E2E tests for chat session management."""

import uuid

import httpx


def test_create_session(user_client: httpx.Client, connection_id: str) -> None:
    resp = user_client.post(
        "/api/v1/sessions",
        json={"connection_id": connection_id, "title": "E2E Test Session"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["title"] == "E2E Test Session"
    assert data["message_count"] == 0


def test_create_session_default_title(user_client: httpx.Client, connection_id: str) -> None:
    resp = user_client.post(
        "/api/v1/sessions",
        json={"connection_id": connection_id},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "New Chat"


def test_list_sessions(user_client: httpx.Client, connection_id: str) -> None:
    # Create one so we know there's at least one
    user_client.post(
        "/api/v1/sessions",
        json={"connection_id": connection_id, "title": "List Test"},
    )
    resp = user_client.get("/api/v1/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_sessions_filtered_by_connection(
    user_client: httpx.Client, connection_id: str
) -> None:
    resp = user_client.get(f"/api/v1/sessions?connection_id={connection_id}")
    assert resp.status_code == 200
    sessions = resp.json()
    # All returned sessions should belong to the requested connection
    for s in sessions:
        assert s["connection_id"] == connection_id


def test_session_message_count_increments(user_client: httpx.Client, connection_id: str) -> None:
    """Executing a query tied to a session should increment message_count."""
    # Create session
    create_resp = user_client.post(
        "/api/v1/sessions",
        json={"connection_id": connection_id, "title": "Count Test"},
    )
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    # Execute a query under that session
    query_resp = user_client.post(
        "/api/v1/query",
        json={
            "connection_id": connection_id,
            "question": "Show active clients",
            "session_id": session_id,
        },
    )
    assert query_resp.status_code == 200

    # Retrieve session messages and check count > 0
    msg_resp = user_client.get(f"/api/v1/sessions/{session_id}/messages")
    assert msg_resp.status_code == 200
    messages = msg_resp.json()
    assert len(messages) >= 1


def test_get_nonexistent_session(user_client: httpx.Client) -> None:
    resp = user_client.get(f"/api/v1/sessions/{uuid.uuid4()}/messages")
    assert resp.status_code == 404


def test_session_requires_auth(base_url: str, connection_id: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.get("/api/v1/sessions")
    assert resp.status_code in (401, 403)
