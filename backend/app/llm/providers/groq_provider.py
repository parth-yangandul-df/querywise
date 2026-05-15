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


class GroqProvider(BaseLLMProvider):
    provider_type = LLMProviderType.GROQ

    def __init__(self, api_key: str | None = None):
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY not configured — set GROQ_API_KEY in environment "
                "or use a different provider"
            )
        self._client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=30.0,
        )

    @llm_retry()
    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> LLMResponse:
        if not self._client.api_key:
            raise ValueError("GROQ_API_KEY not configured")
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
            raise_if_provider_rate_limited(err, "Groq")
            logger.error("Groq API error: %s", err, exc_info=True)
            raise
        elapsed_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            finish_reason=choice.finish_reason or "stop",
            latency_ms=elapsed_ms,
        )

    @llm_retry()
    async def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict],
        config: LLMConfig,
    ) -> dict:
        """Call Groq with tool definitions and return the tool call arguments as a parsed dict.

        Uses OpenAI-compatible function calling. Returns the first tool call's
        parsed arguments dict, or raises ValueError if no tool call was returned.
        """
        import json as _json

        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        start = time.monotonic()
        try:
            response = await self._client.chat.completions.create(
                model=config.model,
                messages=oai_messages,
                tools=tools,
                tool_choice="required",
                temperature=config.temperature,
                max_completion_tokens=config.max_tokens,
                top_p=config.top_p,
            )
        except Exception as err:
            raise_if_provider_rate_limited(err, "Groq")
            logger.error("Groq tool call error: %s", err, exc_info=True)
            raise
        elapsed_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]
        tool_calls = choice.message.tool_calls

        if not tool_calls:
            raise ValueError(
                f"Groq returned no tool calls (finish_reason={choice.finish_reason!r}). "
                "Model may not support tool calling or the prompt needs adjustment."
            )

        raw_args = tool_calls[0].function.arguments
        try:
            parsed = _json.loads(raw_args)
        except _json.JSONDecodeError as e:
            raise ValueError(f"Groq tool call returned invalid JSON: {e}. Raw: {raw_args!r}") from e

        return {
            "arguments": parsed,
            "tool_name": tool_calls[0].function.name,
            "latency_ms": elapsed_ms,
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }

    @llm_retry()
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
            raise_if_provider_rate_limited(err, "Groq")
            logger.error("Groq stream error: %s", exc_info=True)
            raise

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def generate_embedding(self, text: str) -> list[float]:
        raise NotImplementedError("Groq does not support embeddings API")

    def list_models(self) -> list[str]:
        return [
            "moonshotai/kimi-k2-instruct",
        ]
