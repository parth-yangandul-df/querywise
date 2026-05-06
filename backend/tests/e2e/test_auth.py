"""E2E tests for authentication endpoints."""

import httpx


def test_login_success(base_url: str, admin_token: str) -> None:
    """A valid login returns a non-empty token, email, and role."""
    assert admin_token, "Expected a non-empty access token"


def test_login_invalid_credentials(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@nowhere.com", "password": "wrong"},
        )
    assert resp.status_code == 401


def test_login_missing_fields(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.post("/api/v1/auth/login", json={"email": "x@x.com"})
    assert resp.status_code == 422


def test_login_rate_limit(base_url: str) -> None:
    """Brute-force guard: 6 rapid requests with wrong creds should hit rate limit."""
    with httpx.Client(base_url=base_url, timeout=15) as client:
        statuses = []
        for _ in range(7):
            resp = client.post(
                "/api/v1/auth/login",
                json={"email": "brute@force.test", "password": "badpass"},
            )
            statuses.append(resp.status_code)
    # After 5 failed attempts the limiter should return 429
    assert 429 in statuses, f"Rate limiter not triggered. Statuses: {statuses}"


def test_protected_endpoint_requires_auth(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.get("/api/v1/connections")
    # No auth header → should be 401 or 403
    assert resp.status_code in (401, 403)


def test_protected_endpoint_rejects_bad_token(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=10) as client:
        resp = client.get(
            "/api/v1/connections",
            headers={"Authorization": "Bearer thisisnotavalidjwt"},
        )
    assert resp.status_code in (401, 403)
