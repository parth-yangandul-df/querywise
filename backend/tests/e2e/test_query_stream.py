"""E2E tests for the streaming query endpoint (SSE)."""

import httpx


def test_stream_query_returns_sse_events(user_client: httpx.Client, connection_id: str) -> None:
    """The stream endpoint must return SSE-formatted data with progress stages."""
    lines = []
    with user_client.stream(
        "POST",
        "/api/v1/query/stream",
        json={"connection_id": connection_id, "question": "Show active projects"},
        timeout=60,
    ) as resp:
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type, (
            f"Expected SSE content-type, got: {content_type}"
        )
        for line in resp.iter_lines():
            lines.append(line)

    data_lines = [l for l in lines if l.startswith("data: ")]
    assert len(data_lines) >= 2, f"Expected multiple SSE events, got: {lines}"

    # Last data event should be the final result
    import json

    last_event = json.loads(data_lines[-1][len("data: ") :])
    assert "generated_sql" in last_event or "stage" in last_event


def test_stream_query_has_progress_stages(user_client: httpx.Client, connection_id: str) -> None:
    """Stream events should include at least one progress stage before the result."""
    import json

    events = []
    with user_client.stream(
        "POST",
        "/api/v1/query/stream",
        json={"connection_id": connection_id, "question": "List all active clients"},
        timeout=60,
    ) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[len("data: ") :]))
                except json.JSONDecodeError:
                    pass

    stage_events = [e for e in events if "stage" in e]
    result_events = [e for e in events if "generated_sql" in e]
    assert len(stage_events) >= 1, "No progress stage events emitted"
    assert len(result_events) == 1, "Expected exactly one result event"


def test_stream_query_requires_auth(base_url: str, connection_id: str) -> None:
    with httpx.Client(base_url=base_url, timeout=15) as client:
        resp = client.post(
            "/api/v1/query/stream",
            json={"connection_id": connection_id, "question": "Show active projects"},
        )
    assert resp.status_code in (401, 403)
