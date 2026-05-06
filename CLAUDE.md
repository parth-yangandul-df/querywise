# CLAUDE.md

## Project Overview

QueryWise — a text-to-SQL application with a semantic metadata layer. Users ask natural language questions, an LLM generates SQL using business context, executes against their database, and returns human-readable answers.

## What is QueryWise?

QueryWise is designed to:
1. Accept natural language queries from users
2. Use business context (glossary, metrics, sample queries) to understand intent
3. Generate accurate SQL using the semantic layer
4. Execute against target databases (PostgreSQL, SQL Server)
5. Return human-readable answers

### Key Capabilities
- Natural language → SQL conversion
- Semantic metadata layer (glossary, metrics, dictionaries, knowledge base)
- Multi-turn conversation context
- Multi-database support (PostgreSQL, SQL Server)
- Provider-agnostic LLM (Anthropic, OpenAI, Ollama, OpenRouter, Groq)

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy (async), asyncpg, pgvector, Alembic, LangGraph
- **Frontend:** React 19, TypeScript, Vite, Mantine UI, React Query, React Router (port 5173)
- **Chat UI:** Angular 21 (port 4200)
- **Databases:** PostgreSQL 16 with pgvector (app metadata), target DBs via PostgreSQL/SQL Server connectors
- **LLM:** Provider-agnostic — Anthropic, OpenAI, Ollama, OpenRouter, Groq

## How to Run

```bash
# Full stack with Docker
docker compose up

# Frontend:      http://localhost:5173
# Chat UI:       http://localhost:4200
# Backend:       http://localhost:8000
# API docs:      http://localhost:8000/docs
```

## Backend Commands

Run from `backend/`:

```bash
pip install -e ".[llm,dev,sqlserver]"  # Install all deps
alembic upgrade head                  # Run migrations
uvicorn app.main:app --reload       # Dev server on :8000
pytest                             # Run tests
ruff check .                       # Lint
ruff format .                      # Format
mypy .                             # Type check
```

## Frontend Commands

Run from `frontend/`:

```bash
npm install                           # Install deps
npm run dev                          # Dev server on :5173
npm run build                        # Production build (tsc + vite)
npm run lint                         # ESLint
```

Run from `angular-test/`:

```bash
npm install                           # Install deps
npm run start                         # Dev server on :4200
npm run build                         # Production build
```

## Code Style

- **Python:** Ruff, 100 char line length, Python 3.12 target, rules: E, F, I, N, UP, B
- **TypeScript:** ESLint, strict mode, no explicit `any`
- **Async everywhere:** All DB operations, HTTP calls, and LLM calls are async
- **Pytest:** asyncio_mode="auto", test paths at `tests/`

## Key Directories

```
backend/
├── scripts/             # Backend scripts
backend/app/
├── api/v1/endpoints/    # FastAPI route handlers (all under /api/v1)
├── api/v1/schemas/      # Pydantic request/response models
├── core/                # Exceptions, logging, security
├── connectors/          # Database connector plugin system (PostgreSQL, SQL Server)
├── db/models/           # SQLAlchemy ORM models (UUID PKs, timestamps)
├── db/session.py        # Async engine + session factory
├── llm/
│   ├── agents/          # LLM agents (composer, validator, interpreter, error handler)
│   ├── providers/       # LLM provider implementations (anthropic, openai, ollama, openrouter, groq)
│   ├── prompts/         # System/user prompt templates
│   ├── utils.py         # Shared LLM utilities (JSON repair for local models)
│   ├── graph/           # LangGraph stateful graph (query plan, intent classification, semantic resolver)
│   └── router.py        # Complexity estimation + model routing
├── semantic/            # Core IP: context builder, schema linker, glossary resolver, knowledge resolver
├── services/            # Business logic (query pipeline, connection mgmt, embeddings, knowledge import)
└── utils/               # SQL sanitizer

frontend/src/            # Mantine UI (port 5173)
angular-test/src/       # Angular 21 chat UI (port 4200)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://querywise:querywise_dev@localhost:5432/querywise` | App metadata DB |
| `ENCRYPTION_KEY` | `dev-encryption-key-change-in-production` | Fernet key for connection strings |
| `DEFAULT_LLM_PROVIDER` | `anthropic` | LLM provider (`anthropic`, `openai`, `ollama`, `openrouter`, `groq`) |
| `DEFAULT_LLM_MODEL` | `claude-sonnet-4-20250514` | Default model for SQL generation. **Ignored when `DEFAULT_LLM_PROVIDER=openrouter`** — use `OPENROUTER_MODEL`, `RESOLVER_MODEL`, `INTERPRETER_MODEL` instead. |
| `EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Embedding model (used with OpenAI, OpenRouter, or when `EMBEDDING_PROVIDER=openai`) |
| `CORS_ORIGINS` | `["http://localhost:5173", "http://localhost:5175", "http://localhost:4200"]` | Allowed CORS origins |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.1:8b` | Ollama model for completions |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Ollama model for embeddings (only when using Ollama for embeddings) |
| `OPENROUTER_API_KEY` | — | Required if using OpenRouter |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v3.2` | OpenRouter model for Composer (SQL generation + error correction) |
| `RESOLVER_MODEL` | `openai/gpt-4.1-nano` | OpenRouter model for Resolver (intent classification + question rewrite) |
| `INTERPRETER_MODEL` | `meta-llama/llama-3.1-8b-instruct` | OpenRouter model for Interpreter (result → natural language summary) |
| `GROQ_API_KEY` | — | Required if using Groq |
| `EMBEDDING_DIMENSION` | `1536` | Vector dimension (1536 for OpenAI/OpenRouter, 768 for Ollama nomic-embed-text) |
| `EMBEDDING_PROVIDER` | — | Explicit embedding provider override (e.g., `openrouter` to route embeddings through OpenRouter) |
| `ANTHROPIC_API_KEY` | — | Required if using Anthropic |
| `OPENAI_API_KEY` | — | Required if using OpenAI directly. **Not needed** when `EMBEDDING_PROVIDER=openrouter` (embeddings routed through OpenRouter). |

### Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_GROQ_EXTRACTOR` | `false` | Enable Groq unified intent + filter extractor |
| `USE_QUERY_PLAN_COMPILER` | `false` | QueryPlan compiler feature flag |
| `USE_HYBRID_MODE` | `false` | Hybrid Mode (context-aware query system) |

### Cloud Ollama (Optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_LLM_BASE_URL` | — | Cloud Ollama URL for LLM completions |
| `OLLAMA_API_KEY` | — | API key for cloud Ollama |
| `EMBEDDING_PROVIDER` | — | Explicit embedding provider override (e.g., `openrouter` to route embeddings through OpenRouter) |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | — | JWT authentication secret key |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_EXPIRY_SECONDS` | `3600` | JWT token expiry in seconds |

### Development

| Variable | Default | Description |
|----------|---------|-------------|
| `MORPH_API_KEY` | — | Morph API key for development tools |

## Ollama (Local LLM)

When using Ollama, all completions and embeddings go through Ollama — no OpenAI/Anthropic fallback. Two deployment modes:

### Option A: Native Ollama on macOS (recommended — GPU-accelerated via Metal)

```bash
# 1. Install and start Ollama on your Mac
brew install ollama
ollama serve

# 2. Pull required models
ollama pull llama3.1:8b
ollama pull nomic-embed-text

# 3. Set .env
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768

# 4. Start stack (Ollama is NOT in Docker — backend reaches it via host.docker.internal)
docker compose up
```

### Option B: Ollama in Docker (CPU-only, fully self-contained)

```bash
# .env
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768

# Start stack with Ollama Docker profile
docker compose --profile ollama-docker up

# Pull required models inside the container
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

> **Why Option A is faster on macOS:** Docker on Mac runs inside a Linux VM with no GPU passthrough. Native Ollama uses Apple Metal for GPU-accelerated inference. Expect ~5-10x faster responses.

### Embedding dimension

`nomic-embed-text` produces **768**-dimension vectors. Set `EMBEDDING_DIMENSION=768` in `.env`. Migration `002_configurable_embedding_dim` handles initial column creation. On subsequent provider switches, `ensure_embedding_dimensions()` (in `setup_service.py`, called from `main.py` lifespan) detects dimension mismatches at startup, resizes all vector columns, and nulls stale embeddings so they regenerate in the background.

### Embedding generation

Embeddings are generated in **background asyncio tasks** (non-blocking):
- **On startup:** after schema introspection, `launch_background_embeddings()` fires a background task
- **On introspect:** background task launched after schema introspection
- **On CRUD:** each create/update of glossary term, metric, sample query, or knowledge document embeds inline
- **Progress tracking:** in-memory tracker (`embedding_progress.py`), exposed at `GET /api/v1/embeddings/status`, displayed as a frontend progress banner (auto-polls every 2s, auto-hides when complete)

### Graceful degradation

If the embedding model is unavailable (not pulled, or Ollama is down), the query pipeline falls back to keyword-only context matching instead of crashing. Vector search failures in `schema_linker.py` trigger a session rollback and keyword fallback. Embedding-based search resumes automatically once the model is available.

### Key implementation details

- `OllamaProvider` (`app/llm/providers/ollama_provider.py`) uses `httpx` to call Ollama REST API
- Completions use `format: "json"` to force JSON output mode
- `repair_json()` in `app/llm/utils.py` handles common local model JSON issues (markdown fences, Python booleans, trailing commas)
- Embeddings: tries `/api/embed` (Ollama 0.4+), falls back to `/api/embeddings` (legacy) automatically
- `get_embedding_provider()` follows the configured provider — Ollama embeds locally, Anthropic falls back to OpenAI

## Groq

QueryWise supports Groq for high-performance LLM completions with two modes:

### Standard Mode
When `USE_GROQ_EXTRACTOR=false` (default), Groq operates as a standard LLM provider with the current recommended model:
- `DEFAULT_LLM_MODEL="meta-llama/llama-3.1-70b-versatile"`

### Groq Extractor Mode
When `USE_GROQ_EXTRACTOR=true`, Groq's unified intent and filter extractor replaces the embedding classifier + regex filter_extractor. This mode provides:
- Faster intent classification
- Native filter extraction without regex
- Improved accuracy for complex queries

### Configuration
```bash
# Enable Groq with extractor
DEFAULT_LLM_PROVIDER=groq
USE_GROQ_EXTRACTOR=true
GROQ_API_KEY=your-groq-api-key
```

## Architecture Conventions

- **Connectors:** Extend `BaseConnector` ABC in `app/connectors/`, register in `connector_registry.py`. Built-in: PostgreSQL (`asyncpg`), SQL Server (`aioodbc`, lazy-loaded). PostgreSQL uses connection pooling, SQL Server uses ODBC driver.
- **LLM Providers:** Extend `BaseLLMProvider` ABC in `app/llm/providers/`, register via `provider_registry`. Built-in: Anthropic, OpenAI, Ollama, OpenRouter, Groq
- **API routes:** All under `/api/v1`, defined in `app/api/v1/endpoints/`, aggregated in `app/api/v1/router.py`
- **ORM models:** UUID primary keys, `created_at`/`updated_at` timestamps, pgvector `VECTOR(settings.embedding_dimension)` for embeddings
- **Services:** Business logic in `app/services/`, never in endpoints directly
- **Knowledge:** Import text/HTML content, auto-detect HTML, section-aware chunking (450 words, 80 overlap), vector + keyword search for relevant chunks injected into LLM prompt. URL fetching server-side via `httpx`. Service in `app/services/knowledge_service.py`
- **SQL safety:** Read-only transactions enforced at connector level, static SQL blocklist in `app/utils/sql_sanitizer.py` (blocks DDL, DML, admin commands, injection patterns)
