import time
from collections.abc import AsyncIterator

import openai

from app.core.exceptions import raise_if_provider_rate_limited
from app.llm.base_provider import (
    BaseLLMProvider,
    LLMConfig,
    LLMMessage,
    LLMProviderType,
    LLMResponse,
)
from app.llm.retry import llm_retry

logger = __import__("logging").getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    provider_type = LLMProviderType.OPENAI

    def __init__(self, api_key: str | None = None):
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=60.0)

    @llm_retry()
    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> LLMResponse:
        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        start = time.monotonic()
        try:
            response = await self._client.chat.completions.create(
                model=config.model,
                messages=oai_messages,
                temperature=config.temperature,
                max_completion_tokens=config.max_tokens,
                top_p=config.top_p,
                stop=config.stop_sequences or None,
            )
        except Exception as err:
            raise_if_provider_rate_limited(err, "OpenAI")
            logger.error("OpenAI API error: %s", err, exc_info=True)
            raise
        elapsed_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]

        # Log cache stats if available
        if response.usage and hasattr(response.usage, "prompt_tokens_details"):
            details = response.usage.prompt_tokens_details
            cached = details.cached_tokens if details else 0
            if cached:
                total = response.usage.prompt_tokens
                cache_hit_ratio = cached / total if total else 0
                logger.info(
                    "llm_cache_hit",
                    extra={
                        "model": response.model,
                        "cached_tokens": cached,
                        "total_prompt_tokens": total,
                        "cache_hit_ratio": cache_hit_ratio,
                    },
                )

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            finish_reason=choice.finish_reason or "stop",
            latency_ms=elapsed_ms,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> AsyncIterator[str]:
        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        try:
            stream = await self._client.chat.completions.create(
                model=config.model,
                messages=oai_messages,
                temperature=config.temperature,
                max_completion_tokens=config.max_tokens,
                stream=True,
            )
        except Exception as err:
            raise_if_provider_rate_limited(err, "OpenAI")
            logger.error("OpenAI stream error: %s", exc_info=True)
            raise

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    @llm_retry()
    async def generate_embedding(self, text: str) -> list[float]:
        from app.config import settings

        try:
            response = await self._client.embeddings.create(
                model=settings.embedding_model,
                input=text,
            )
        except Exception as err:
            raise_if_provider_rate_limited(err, "OpenAI")
            logger.error("OpenAI embedding error: %s", err, exc_info=True)
            raise
        return response.data[0].embedding

    def list_models(self) -> list[str]:
        return [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
        ]
