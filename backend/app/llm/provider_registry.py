from app.core.exceptions import ValidationError as AppValidationError
from app.llm.base_provider import BaseLLMProvider, LLMProviderType

_PROVIDER_CLASSES: dict[LLMProviderType, type[BaseLLMProvider]] = {}
_instances: dict[str, BaseLLMProvider] = {}


def _register_defaults() -> None:
    """Lazily register built-in providers."""
    if _PROVIDER_CLASSES:
        return
    from app.llm.providers.anthropic_provider import AnthropicProvider
    from app.llm.providers.groq_provider import GroqProvider
    from app.llm.providers.ollama_provider import OllamaProvider
    from app.llm.providers.openai_provider import OpenAIProvider
    from app.llm.providers.openrouter_provider import OpenRouterProvider

    _PROVIDER_CLASSES[LLMProviderType.ANTHROPIC] = AnthropicProvider
    _PROVIDER_CLASSES[LLMProviderType.OPENAI] = OpenAIProvider
    _PROVIDER_CLASSES[LLMProviderType.OLLAMA] = OllamaProvider
    _PROVIDER_CLASSES[LLMProviderType.OPENROUTER] = OpenRouterProvider
    _PROVIDER_CLASSES[LLMProviderType.GROQ] = GroqProvider


def register_provider(provider_type: LLMProviderType, cls: type[BaseLLMProvider]) -> None:
    _PROVIDER_CLASSES[provider_type] = cls


def get_provider(provider_type: str, api_key: str | None = None) -> BaseLLMProvider:
    """Get or create a provider instance."""
    _register_defaults()

    # For Ollama, inject the configured API key if the caller didn't supply one
    if provider_type == "ollama" and api_key is None:
        from app.config import settings as _settings

        if _settings.ollama_api_key:
            api_key = _settings.ollama_api_key

    # For Groq, inject the configured API key if the caller didn't supply one
    if provider_type == "groq" and api_key is None:
        from app.config import settings as _settings

        if _settings.groq_api_key:
            api_key = _settings.groq_api_key

    cache_key = f"{provider_type}:{api_key or 'default'}"
    if cache_key in _instances:
        return _instances[cache_key]

    try:
        pt = LLMProviderType(provider_type)
    except ValueError as exc:
        raise AppValidationError(
            f"Unknown LLM provider: '{provider_type}'. "
            f"Available: {[t.value for t in LLMProviderType]}"
        ) from exc

    cls = _PROVIDER_CLASSES.get(pt)
    if cls is None:
        raise AppValidationError(f"Provider '{provider_type}' is not registered.")

    instance = cls(api_key=api_key) if api_key else cls()
    _instances[cache_key] = instance
    return instance


def get_embedding_provider(api_key: str | None = None) -> BaseLLMProvider:
    """Get a provider that supports embeddings.

    Resolution order:
    1. If EMBEDDING_PROVIDER is explicitly set, use that.
    2. Otherwise derive from DEFAULT_LLM_PROVIDER:
       - "ollama"      → Ollama (local or cloud via OLLAMA_API_KEY)
       - "openai"      → OpenAI text-embedding-3-small
       - "anthropic"   → fall back to OpenAI (Anthropic has no embeddings API)
    """
    from app.config import settings

    # Explicit override takes priority
    provider_type = settings.embedding_provider or settings.default_llm_provider

    # Providers without an embeddings endpoint fall back to OpenAI
    if provider_type in ("anthropic", "groq"):
        provider_type = "openai"

    return get_provider(provider_type, api_key=api_key)
