"""E2E tests for health and readiness endpoints."""

import httpx


def test_health_check(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readiness_check(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.get("/ready")
    data = resp.json()
    assert resp.status_code in (200, 503), f"Unexpected status: {resp.status_code}"
    assert "status" in data
    assert "checks" in data
    if resp.status_code == 200:
        assert data["status"] == "ready"
        assert data["checks"]["database"] == "ok"


def test_embedding_status(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.get("/api/v1/embeddings/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "tasks" in body
    assert isinstance(body["tasks"], list)
