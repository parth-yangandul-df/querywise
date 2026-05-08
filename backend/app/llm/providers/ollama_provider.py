"""Ollama LLM provider — local models via Ollama REST API."""

import json
import time
from collections.abc import AsyncIterator

import httpx

from app.config import settings
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


class OllamaProvider(BaseLLMProvider):
    provider_type = LLMProviderType.OLLAMA

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        """Ensure the base URL ends with /api.

        Both local Ollama (http://localhost:11434) and Ollama Cloud
        (https://ollama.com/api) expose the same API under /api. Normalizing
        here lets all path references use /chat, /embed, /embeddings without
        an /api prefix, which works correctly for both hosts.
        """
        url = url.rstrip("/")
        if not url.endswith("/api"):
            url = f"{url}/api"
        return url

    def __init__(self, api_key: str | None = None):
        # LLM completions: use cloud URL if configured, else fall back to local URL
        llm_base_url = self._normalize_base_url(
            settings.ollama_llm_base_url or settings.ollama_base_url
        )

        # Embedding: always use the local base URL, never send auth
        embedding_base_url = self._normalize_base_url(settings.ollama_base_url)

        # API key applies to LLM calls only (cloud auth)
        resolved_key = api_key or settings.ollama_api_key or None

        llm_headers = {}
        if resolved_key:
            llm_headers["Authorization"] = f"Bearer {resolved_key}"

        # Separate clients: LLM client (possibly cloud + auth), embedding client (local, no auth)
        self._client = httpx.AsyncClient(
            base_url=llm_base_url,
            timeout=60.0,
            headers=llm_headers,
        )
        self._embed_client = httpx.AsyncClient(
            base_url=embedding_base_url,
            timeout=60.0,
        )

    @llm_retry()
    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> LLMResponse:
        ollama_messages = [{"role": m.role, "content": m.content} for m in messages]

        payload: dict = {
            "model": config.model,
            "messages": ollama_messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": config.temperature,
                "top_p": config.top_p,
                "num_predict": config.max_tokens,
            },
        }

        if config.stop_sequences:
            payload["options"]["stop"] = config.stop_sequences

        start = time.monotonic()
        try:
            with trace_llm_call(
                provider="ollama",
                model=config.model,
                operation="complete",
                metadata={
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                    "messages_count": len(messages),
                },
            ) as run:
                resp = await self._client.post("/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                if run is not None:
                    run.end(outputs={"content": data.get("message", {}).get("content", "")[:500], "model": data.get("model", config.model)})
        except httpx.ConnectError as err:
            raise ConnectionError(
                f"Cannot connect to Ollama at {settings.ollama_llm_base_url or settings.ollama_base_url}. "
                "Is Ollama running? Start it with: ollama serve"
            ) from err
        except httpx.HTTPStatusError as err:
            raise_if_provider_rate_limited(err, "Ollama")
            raise
        elapsed_ms = (time.monotonic() - start) * 1000

        data = resp.json()
        message_content = data.get("message", {}).get("content", "")

        return LLMResponse(
            content=message_content,
            model=data.get("model", config.model),
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            finish_reason=data.get("done_reason", "stop"),
            latency_ms=elapsed_ms,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        config: LLMConfig,
    ) -> AsyncIterator[str]:
        ollama_messages = [{"role": m.role, "content": m.content} for m in messages]

        payload: dict = {
            "model": config.model,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "temperature": config.temperature,
                "top_p": config.top_p,
                "num_predict": config.max_tokens,
            },
        }

        try:
            with trace_llm_call(
                provider="ollama",
                model=config.model,
                operation="stream",
                metadata={
                    "temperature": config.temperature,
                    "max_tokens": config.max_tokens,
                },
            ) as run:
                async with self._client.stream("POST", "/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if chunk.get("done", False):
                            break
                    if run is not None:
                        run.end(outputs={"status": "stream_complete"})
        except httpx.ConnectError as err:
            raise ConnectionError(
                f"Cannot connect to Ollama at {settings.ollama_llm_base_url or settings.ollama_base_url}. "
                "Is Ollama running? Start it with: ollama serve"
            ) from err
        except httpx.HTTPStatusError as err:
            raise_if_provider_rate_limited(err, "Ollama")
            raise

    @llm_retry()
    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embeddings using Ollama's embedding endpoint.

        Tries the new /api/embed endpoint first (Ollama 0.4+), then falls
        back to the legacy /api/embeddings endpoint for older versions.
        """
        model = settings.ollama_embedding_model

        with trace_llm_call(
            provider="ollama",
            model=model,
            operation="embed",
            metadata={"text_length": len(text)},
        ) as run:
            try:
                result = await self._embed_new_api(text, model)
                if run is not None:
                    run.end(outputs={"embedding_dim": len(result), "model": model})
                return result
            except httpx.HTTPStatusError as err:
                raise_if_provider_rate_limited(err, "Ollama")
                if err.response.status_code == 404:
                    result = await self._embed_legacy_api(text, model)
                    if run is not None:
                        run.end(outputs={"embedding_dim": len(result), "model": model})
                    return result
                raise
            except httpx.ConnectError as err:
                raise ConnectionError(
                    f"Cannot connect to Ollama at {settings.ollama_base_url}. "
                    "Is Ollama running? Start it with: ollama serve"
                ) from err

    async def _embed_new_api(self, text: str, model: str) -> list[float]:
        """Ollama 0.4+ /api/embed endpoint."""
        resp = await self._embed_client.post("/embed", json={"model": model, "input": text})
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings", [])
        if not embeddings:
            raise ValueError(
                f"No embeddings returned from Ollama model '{model}'. "
                f"Make sure the model is pulled: ollama pull {model}"
            )
        return embeddings[0]

    async def _embed_legacy_api(self, text: str, model: str) -> list[float]:
        """Legacy /api/embeddings endpoint for older Ollama versions."""
        try:
            resp = await self._embed_client.post(
                "/embeddings", json={"model": model, "prompt": text}
            )
            resp.raise_for_status()
        except httpx.ConnectError as err:
            raise ConnectionError(
                f"Cannot connect to Ollama at {settings.ollama_base_url}. "
                "Is Ollama running? Start it with: ollama serve"
            ) from err
        except httpx.HTTPStatusError as err:
            raise_if_provider_rate_limited(err, "Ollama")
            raise
        data = resp.json()
        embedding = data.get("embedding", [])
        if not embedding:
            raise ValueError(
                f"No embeddings returned from Ollama model '{model}'. "
                f"Make sure the model is pulled: ollama pull {model}"
            )
        return embedding

    def list_models(self) -> list[str]:
        """Return commonly used Ollama models. Use /api/tags for dynamic listing."""
        return [
            "llama3.1:8b",
            "llama3.1:70b",
            "mistral:7b",
            "codellama:13b",
            "qwen2.5:7b",
        ]
