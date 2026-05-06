"""E2E tests for query history."""

import httpx


def test_query_history_recorded(user_client: httpx.Client, connection_id: str) -> None:
    """After executing a query, it must appear in query history."""
    question = "Show all active projects for history test"

    # Execute query
    resp = user_client.post(
        "/api/v1/query",
        json={"connection_id": connection_id, "question": question},
    )
    assert resp.status_code == 200
    query_id = resp.json()["id"]

    # Check history
    history_resp = user_client.get(f"/api/v1/query-history?connection_id={connection_id}&limit=10")
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert isinstance(history, list)

    ids = [h["id"] for h in history]
    assert str(query_id) in ids, f"Query {query_id} not found in history: {ids}"


def test_query_history_schema(user_client: httpx.Client, connection_id: str) -> None:
    """History entries must have expected fields."""
    history_resp = user_client.get(f"/api/v1/query-history?connection_id={connection_id}&limit=5")
    assert history_resp.status_code == 200
    history = history_resp.json()
    if history:
        entry = history[0]
        expected_fields = {
            "id",
            "connection_id",
            "natural_language",
            "generated_sql",
            "execution_status",
        }
        assert expected_fields.issubset(entry.keys()), f"Missing: {expected_fields - entry.keys()}"


def test_query_history_requires_auth(base_url: str, connection_id: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.get(f"/api/v1/query-history?connection_id={connection_id}")
    assert resp.status_code in (401, 403)
