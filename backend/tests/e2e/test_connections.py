"""E2E tests for database connection management."""

import httpx


def test_list_connections_as_admin(admin_client: httpx.Client) -> None:
    resp = admin_client.get("/api/v1/connections")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_connections_schema(admin_client: httpx.Client) -> None:
    """Each connection object must have the expected fields."""
    resp = admin_client.get("/api/v1/connections")
    assert resp.status_code == 200
    connections = resp.json()
    if connections:
        conn = connections[0]
        expected_fields = {"id", "name", "connector_type", "is_active", "has_connection_string"}
        assert expected_fields.issubset(conn.keys()), f"Missing fields in: {conn.keys()}"


def test_create_connection_requires_admin(user_client: httpx.Client) -> None:
    """Regular users must not be able to create connections."""
    resp = user_client.post(
        "/api/v1/connections",
        json={
            "name": "Should Fail",
            "connector_type": "postgresql",
            "connection_string": "postgresql://fake:fake@localhost/fake",
        },
    )
    assert resp.status_code in (403, 401)


def test_create_and_delete_connection(admin_client: httpx.Client) -> None:
    """Admin can create a connection and then delete it."""
    create_resp = admin_client.post(
        "/api/v1/connections",
        json={
            "name": "E2E Test Connection",
            "connector_type": "postgresql",
            "connection_string": "postgresql+asyncpg://e2e:e2e@localhost:5432/e2e_test",
            "default_schema": "public",
        },
    )
    assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
    created = create_resp.json()
    conn_id = created["id"]

    try:
        # Verify it appears in the list
        list_resp = admin_client.get("/api/v1/connections")
        ids = [c["id"] for c in list_resp.json()]
        assert conn_id in ids
    finally:
        # Cleanup — delete even if assertions above fail
        del_resp = admin_client.delete(f"/api/v1/connections/{conn_id}")
        assert del_resp.status_code in (200, 204), f"Delete failed: {del_resp.text}"


def test_get_nonexistent_connection(admin_client: httpx.Client) -> None:
    import uuid

    fake_id = str(uuid.uuid4())
    resp = admin_client.get(f"/api/v1/connections/{fake_id}")
    assert resp.status_code == 404


def test_test_connection_endpoint(admin_client: httpx.Client, connection_id: str) -> None:
    """Test that the connection test endpoint responds correctly."""
    resp = admin_client.post(f"/api/v1/connections/{connection_id}/test")
    assert resp.status_code in (200, 400), f"Unexpected: {resp.text}"
    body = resp.json()
    assert "success" in body or "detail" in body
