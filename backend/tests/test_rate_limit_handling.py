import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.exceptions import RateLimitError, raise_if_provider_rate_limited
from app.llm.base_provider import LLMConfig, LLMMessage
from app.llm.providers.openai_provider import OpenAIProvider


def test_raise_if_provider_rate_limited_from_status_code_attr() -> None:
    class DummyRateLimitError(Exception):
        def __init__(self) -> None:
            self.status_code = 429
            super().__init__("rate limited")

    with pytest.raises(RateLimitError) as exc_info:
        raise_if_provider_rate_limited(DummyRateLimitError(), "OpenAI")

    assert exc_info.value.status_code == 429
    assert "OpenAI rate limit exceeded" in exc_info.value.message


def test_raise_if_provider_rate_limited_from_response_status() -> None:
    request = httpx.Request("POST", "https://example.com/chat")
    response = httpx.Response(429, request=request)
    err = httpx.HTTPStatusError("Too Many Requests", request=request, response=response)

    with pytest.raises(RateLimitError) as exc_info:
        raise_if_provider_rate_limited(err, "Ollama")

    assert exc_info.value.status_code == 429
    assert "Ollama rate limit exceeded" in exc_info.value.message


def test_openai_provider_complete_maps_rate_limit_to_app_error() -> None:
    provider = OpenAIProvider(api_key="test-key")

    class DummyOpenAIRateLimit(Exception):
        def __init__(self) -> None:
            self.status_code = 429
            super().__init__("limited")

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=DummyOpenAIRateLimit()))
        )
    )

    async def run_test() -> None:
        with pytest.raises(RateLimitError) as exc_info:
            await provider.complete(
                [LLMMessage(role="user", content="hello")],
                LLMConfig(model="gpt-4o-mini"),
            )

        assert exc_info.value.status_code == 429
        assert "OpenAI rate limit exceeded" in exc_info.value.message

    asyncio.run(run_test())
