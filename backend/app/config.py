from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(WORKSPACE_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "QueryWise"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # App database (stores metadata, glossary, etc.)
    database_url: str = "postgresql+asyncpg://querywise:querywise_dev@localhost:5432/querywise"

    # Security
    encryption_key: str
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:4200",
        "http://localhost:4000",
    ]

    # JWT authentication
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_seconds: int = 3600

    # Query defaults
    default_query_timeout_seconds: int = 30
    default_max_rows: int = 1000
    max_retry_attempts: int = 3

    # LLM defaults
    default_llm_provider: str = "anthropic"
    default_llm_model: str = "claude-sonnet-4-20250514"
    embedding_model: str = "text-embedding-3-small"

    # Ollama settings (used when default_llm_provider = "ollama")
    ollama_base_url: str = "http://localhost:11434"
    # Cloud Ollama base URL for LLM completions — falls back to ollama_base_url if empty.
    # Use this to point LLM calls at a remote Ollama host (e.g. https://ollama.com)
    # while keeping ollama_base_url pointed at a local instance for embeddings.
    ollama_llm_base_url: str = ""
    ollama_model: str = "llama3.1:8b"
    ollama_embedding_model: str = "nomic-embed-text"
    # API key for cloud-hosted Ollama LLM calls (leave empty for local Ollama)
    ollama_api_key: str = ""

    # OpenRouter settings (used when default_llm_provider = "openrouter")
    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-v3.2"

    # Groq settings (used when default_llm_provider = "groq")
    groq_api_key: str = ""
    groq_model: str = (
        "meta-llama/llama-3.1-70b-versatile"  # Upgraded from kimi-k2 for better tool calling
    )

    # Interpreter model (used for result-to-natural-language conversion across all providers)
    interpreter_model: str = "meta-llama/llama-3.1-8b-instruct"

    # Embedding provider override (leave empty to auto-derive from default_llm_provider)
    # Set to "ollama" to use Ollama for embeddings while using a different provider for LLM.
    # Valid values: "", "openai", "ollama", "anthropic"
    embedding_provider: str = ""

    # Auto-setup sample DB (only enable in development/demo)
    auto_setup_sample_db: bool = False

    # Rate limiting
    max_queries_per_minute: int = 30

    # Context builder
    max_context_tables: int = 8
    max_sample_queries: int = 3
    embedding_dimension: int = 1536

    # Logging
    log_level: str = "INFO"
    log_file_enabled: bool = True
    log_rotation: str = "10 MB"
    log_retention: str = "10 days"

    # LangSmith observability
    langsmith_api_key: str = ""
    langsmith_project: str = "querywise"
    langsmith_tracing_enabled: bool = False


settings = Settings()
