"""E2E tests for glossary, metrics, and sample queries (semantic layer)."""


import httpx

# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------


class TestGlossary:
    def test_list_glossary_terms(self, admin_client: httpx.Client, connection_id: str) -> None:
        resp = admin_client.get(f"/api/v1/glossary?connection_id={connection_id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_and_delete_glossary_term(
        self, admin_client: httpx.Client, connection_id: str
    ) -> None:
        create_resp = admin_client.post(
            "/api/v1/glossary",
            json={
                "connection_id": connection_id,
                "term": "E2E Test Term",
                "definition": "Created by E2E test suite — safe to delete",
            },
        )
        assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
        term_id = create_resp.json()["id"]

        try:
            get_resp = admin_client.get(f"/api/v1/glossary/{term_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["term"] == "E2E Test Term"
        finally:
            del_resp = admin_client.delete(f"/api/v1/glossary/{term_id}")
            assert del_resp.status_code in (200, 204)

    def test_glossary_requires_auth(self, base_url: str, connection_id: str) -> None:
        with httpx.Client(base_url=base_url, timeout=10) as client:
            resp = client.get(f"/api/v1/glossary?connection_id={connection_id}")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_list_metrics(self, admin_client: httpx.Client, connection_id: str) -> None:
        resp = admin_client.get(f"/api/v1/metrics?connection_id={connection_id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_and_delete_metric(self, admin_client: httpx.Client, connection_id: str) -> None:
        create_resp = admin_client.post(
            "/api/v1/metrics",
            json={
                "connection_id": connection_id,
                "name": "E2E Test Metric",
                "description": "E2E metric — safe to delete",
                "sql_expression": "COUNT(*)",
            },
        )
        assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
        metric_id = create_resp.json()["id"]

        try:
            get_resp = admin_client.get(f"/api/v1/metrics/{metric_id}")
            assert get_resp.status_code == 200
        finally:
            del_resp = admin_client.delete(f"/api/v1/metrics/{metric_id}")
            assert del_resp.status_code in (200, 204)


# ---------------------------------------------------------------------------
# Sample Queries
# ---------------------------------------------------------------------------


class TestSampleQueries:
    def test_list_sample_queries(self, admin_client: httpx.Client, connection_id: str) -> None:
        resp = admin_client.get(f"/api/v1/sample-queries?connection_id={connection_id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_and_delete_sample_query(
        self, admin_client: httpx.Client, connection_id: str
    ) -> None:
        create_resp = admin_client.post(
            "/api/v1/sample-queries",
            json={
                "connection_id": connection_id,
                "natural_language": "Show E2E test sample",
                "sql": "SELECT 1",
                "description": "E2E test — safe to delete",
            },
        )
        assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
        sq_id = create_resp.json()["id"]

        try:
            get_resp = admin_client.get(f"/api/v1/sample-queries/{sq_id}")
            assert get_resp.status_code == 200
        finally:
            del_resp = admin_client.delete(f"/api/v1/sample-queries/{sq_id}")
            assert del_resp.status_code in (200, 204)
