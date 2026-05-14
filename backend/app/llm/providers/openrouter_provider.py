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
from app.llm.retry import llm_retry

logger = __import__("logging").getLogger(__name__)

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

    # stream() is inherited from OpenAIProvider unchanged.
    # complete() is overridden to extract usage.cost from OpenRouter's response.

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> AsyncIterator[str]:
        async for token in super().stream(messages, config):
            yield token

    @llm_retry()
    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> LLMResponse:
        import time

        from app.core.exceptions import raise_if_provider_rate_limited

        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        start = time.monotonic()
        try:
            raw_response = await self._client.chat.completions.create(
                model=config.model,
                messages=oai_messages,
                temperature=config.temperature,
                max_completion_tokens=config.max_tokens,
                top_p=config.top_p,
                stop=config.stop_sequences or None,
            )
        except Exception as err:
            raise_if_provider_rate_limited(err, "OpenRouter")
            logger.error("OpenRouter API error: %s", err, exc_info=True)
            raise
        elapsed_ms = (time.monotonic() - start) * 1000

        choice = raw_response.choices[0]

        # OpenRouter returns actual cost in usage.cost (a pydantic extra field).
        # The OpenAI SDK preserves unknown fields via extra="allow", accessible
        # through __pydantic_extra__. This is the authoritative per-request cost
        # from OpenRouter — more accurate than litellm's pricing catalog which
        # may not cover models like deepseek-v3.2 or qwen.
        cost_usd: float | None = None
        if raw_response.usage:
            extras = getattr(raw_response.usage, "__pydantic_extra__", None)
            if extras and "cost" in extras:
                cost_usd = float(extras["cost"])

        return LLMResponse(
            content=choice.message.content or "",
            model=raw_response.model,
            input_tokens=raw_response.usage.prompt_tokens if raw_response.usage else 0,
            output_tokens=raw_response.usage.completion_tokens if raw_response.usage else 0,
            finish_reason=choice.finish_reason or "stop",
            latency_ms=elapsed_ms,
            cost_usd=cost_usd,
        )

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
