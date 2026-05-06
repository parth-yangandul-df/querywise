"""
E2E integration test fixtures.

These tests run against a live QueryWise backend at BASE_URL (default: http://localhost:8000).
They require:
  - A running backend (docker compose up or uvicorn)
  - Environment variables (or .env) with valid test credentials:
      E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD — admin user credentials
      E2E_USER_EMAIL, E2E_USER_PASSWORD   — regular user credentials
      E2E_CONNECTION_ID                   — UUID of a configured database connection

Set these in a .env.e2e file or as environment variables before running:
    pytest tests/e2e -v
"""

import os
from pathlib import Path

import httpx
import pytest

# Load .env.e2e if present — simple manual parsing to avoid requiring python-dotenv
_env_file = Path(__file__).resolve().parents[3] / ".env.e2e"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@querywise.local")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "admin123")
USER_EMAIL = os.getenv("E2E_USER_EMAIL", "user@querywise.local")
USER_PASSWORD = os.getenv("E2E_USER_PASSWORD", "user123")
CONNECTION_ID = os.getenv("E2E_CONNECTION_ID", "")


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def connection_id() -> str:
    """Return the configured connection UUID, or skip if not set."""
    if not CONNECTION_ID:
        pytest.skip("E2E_CONNECTION_ID not set — skipping query tests")
    return CONNECTION_ID


@pytest.fixture(scope="session")
def admin_token(base_url: str) -> str:
    """Log in as admin and return the JWT access token."""
    with httpx.Client(base_url=base_url, timeout=15) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert resp.status_code == 200, f"Admin login failed: {resp.text}"
        return resp.json()["access_token"]


@pytest.fixture(scope="session")
def user_token(base_url: str) -> str:
    """Log in as a regular user and return the JWT access token."""
    with httpx.Client(base_url=base_url, timeout=15) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert resp.status_code == 200, f"User login failed: {resp.text}"
        return resp.json()["access_token"]


@pytest.fixture(scope="session")
def admin_client(base_url: str, admin_token: str) -> httpx.Client:
    client = httpx.Client(
        base_url=base_url,
        headers=_auth_headers(admin_token),
        timeout=60,
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def user_client(base_url: str, user_token: str) -> httpx.Client:
    client = httpx.Client(
        base_url=base_url,
        headers=_auth_headers(user_token),
        timeout=60,
    )
    yield client
    client.close()
