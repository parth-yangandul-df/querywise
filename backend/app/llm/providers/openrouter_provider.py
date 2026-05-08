"""OpenRouter LLM provider — OpenAI-compatible API with 300+ models.

OpenRouter exposes the OpenAI chat-completions interface, so we subclass
OpenAIProvider and only change:
  • base_url → https://openrouter.ai/api/v1
  • two required headers: HTTP-Referer and X-Title
  • provider_type → LLMProviderType.OPENROUTER
  • list_models() → OpenRouter model catalogue

Embeddings: OpenRouter proxies OpenAI-compatible embedding endpoints.
When EMBEDDING_PROVIDER=openrouter, embeddings go through OpenRouter
using the configured EMBEDDING_MODEL (e.g. openai/text-embedding-3-small).

Usage (.env):
    DEFAULT_LLM_PROVIDER=openrouter
    OPENROUTER_API_KEY=sk-or-...
    OPENROUTER_MODEL=deepseek/deepseek-v3.2
    EMBEDDING_PROVIDER=openrouter
    EMBEDDING_MODEL=openai/text-embedding-3-small
    EMBEDDING_DIMENSION=1536
"""

from collections.abc import AsyncIterator

import openai

from app.config import settings
from app.llm.base_provider import (
    LLMConfig,
    LLMMessage,
    LLMProviderType,
    LLMResponse,
)
from app.llm.providers.openai_provider import OpenAIProvider
from app.llm.tracing import trace_llm_call

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(OpenAIProvider):
    """Thin wrapper around OpenAIProvider pointed at OpenRouter."""

    provider_type = LLMProviderType.OPENROUTER

    def __init__(self, api_key: str | None = None) -> None:
        resolved_key = api_key or settings.openrouter_api_key

        # OpenRouter requires two extra headers per their docs
        default_headers = {
            "HTTP-Referer": "https://github.com/querywise/querywise",
            "X-Title": "QueryWise",
        }

        self._client = openai.AsyncOpenAI(
            api_key=resolved_key,
            base_url=_OPENROUTER_BASE_URL,
            default_headers=default_headers,
            timeout=60.0,
        )

    # complete() and stream() are inherited from OpenAIProvider unchanged.
    # OpenRouter returns the same response shape as OpenAI.

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> AsyncIterator[str]:
        with trace_llm_call(
            provider="openrouter",
            model=config.model,
            operation="stream",
            metadata={
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
            },
        ) as run:
            async for token in super().stream(messages, config):
                yield token
            if run is not None:
                run.end(outputs={"status": "stream_complete"})

    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> LLMResponse:
        with trace_llm_call(
            provider="openrouter",
            model=config.model,
            operation="complete",
            metadata={
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "messages_count": len(messages),
            },
        ) as run:
            response = await super().complete(messages, config)
            if run is not None:
                run.end(outputs={"content": response.content[:500], "model": response.model})
            return response

    def list_models(self) -> list[str]:
        return [
            "openai/gpt-3.5-turbo",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "anthropic/claude-3-haiku",
            "anthropic/claude-3-sonnet",
            "meta-llama/llama-3.1-8b-instruct",
            "mistralai/mistral-7b-instruct",
        ]
