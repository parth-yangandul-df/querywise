import time
from collections.abc import AsyncIterator

import anthropic
import httpx

from app.core.exceptions import raise_if_provider_rate_limited
from app.llm.base_provider import (
    BaseLLMProvider,
    LLMConfig,
    LLMMessage,
    LLMProviderType,
    LLMResponse,
)
from app.llm.retry import llm_retry
from app.llm.tracing import trace_llm_call

logger = __import__("logging").getLogger(__name__)


class AnthropicProvider(BaseLLMProvider):
    provider_type = LLMProviderType.ANTHROPIC

    def __init__(self, api_key: str | None = None):
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    @llm_retry()
    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> LLMResponse:
        system_msg = None
        user_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                user_messages.append({"role": m.role, "content": m.content})

        start = time.monotonic()
        kwargs: dict = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "messages": user_messages,
        }
        if system_msg:
            kwargs["system"] = system_msg
        if config.stop_sequences:
            kwargs["stop_sequences"] = config.stop_sequences

        try:
            with trace_llm_call(
                provider="anthropic",
                model=config.model,
                operation="complete",
                metadata={
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                    "messages_count": len(messages),
                },
            ):
                response = await self._client.messages.create(**kwargs)
        except Exception as err:
            raise_if_provider_rate_limited(err, "Anthropic")
            logger.error("Anthropic API error: %s", err, exc_info=True)
            raise
        elapsed_ms = (time.monotonic() - start) * 1000

        return LLMResponse(
            content=response.content[0].text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            finish_reason=response.stop_reason or "stop",
            latency_ms=elapsed_ms,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> AsyncIterator[str]:
        system_msg = None
        user_messages = []
        for m in messages:
            if m.role == "system":
                system_msg = m.content
            else:
                user_messages.append({"role": m.role, "content": m.content})

        kwargs: dict = {
            "model": config.model,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
            "messages": user_messages,
        }
        if system_msg:
            kwargs["system"] = system_msg

        try:
            with trace_llm_call(
                provider="anthropic",
                model=config.model,
                operation="stream",
                metadata={
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                },
            ):
                async with self._client.messages.stream(**kwargs) as stream:
                    async for text in stream.text_stream:
                        yield text
        except Exception as err:
            raise_if_provider_rate_limited(err, "Anthropic")
            logger.error("Anthropic stream error: %s", exc_info=True)
            raise

    async def generate_embedding(self, text: str) -> list[float]:
        raise NotImplementedError(
            "Anthropic does not provide an embedding API. Use OpenAI or a local embedding model."
        )

    def list_models(self) -> list[str]:
        return [
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250414",
        ]