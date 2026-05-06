# QueryWise

A full-stack application that translates natural language questions into SQL queries. It uses a **semantic metadata layer** — business glossary, metrics definitions, data dictionary, and schema context — to give LLMs the context they need to generate accurate SQL against your databases.



```
┌─────────────────────────────────────────────┐
│        FRONTEND (React + TypeScript)        │
│  Query Interface │ Semantic Layer Mgmt UI   │
│  Mantine UI (port 5173)                     │
│  Angular Chat (port 4200)                    │
└────────────────────┬────────────────────────┘
                       │ REST API
┌────────────────────▼────────────────────────┐
│           BACKEND (FastAPI)                 │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  LANGGRAPH ORCHESTRATION            │    │
│  │  QueryPlan → Intent → Semantic →    │    │
│  │  SQL Compiler → Interpreter         │    │
│  └──────────────┬──────────────────────┘    │
│                 │                            │
│  ┌──────────────▼──────────────────────┐    │
│  │  SEMANTIC LAYER                     │    │
│  │  Context Builder → Prompt Assembler │    │
│  │  (embedding search + keyword match) │    │
│  └──────────────┬──────────────────────┘    │
│                 │                            │
│  ┌──────────────▼──────────────────────┐    │
│  │  CONNECTOR LAYER (plugin system)    │    │
│  │  BaseConnector → PostgreSQL,        │    │
│  │  SQL Server                        │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

## Features

- **Natural language to SQL** — ask questions in plain English, get SQL + results + explanations
- **Semantic metadata layer** — business glossary, metric definitions, data dictionary, knowledge base, sample queries
- **Knowledge import** — import documentation (Confluence, wikis, HTML pages) to inject relevant business context into SQL generation
- **Hybrid context selection** — embedding similarity + keyword matching + foreign key graph traversal
- **Multi-provider LLM** — Anthropic Claude, OpenAI, Ollama, OpenRouter, Groq (provider-agnostic design)
- **LangGraph orchestration** — stateful graph with query plan, intent classification, semantic resolution, and SQL compilation
- **4 specialized LLM agents** — Query Composer, SQL Validator, Result Interpreter, Error Handler
- **Intelligent routing** — routes simple/moderate/complex queries to appropriate models
- **Plugin connector system** — PostgreSQL and SQL Server built-in, extensible to other databases
- **Security by default** — read-only query execution, SQL blocklist, encrypted connection strings
- **Query history** — full execution log with favorites, retry counts, token usage
- **Schema introspection** — auto-discovers tables, columns, types, relationships from target databases

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- An LLM API key (Anthropic and/or OpenAI) **or** Ollama for fully local operation

> 📖 **For detailed step-by-step instructions**, see the [Onboarding Guide](docs/onboarding-guide.md).

### Run with Docker

```bash
# Clone the repo
git clone <repo-url> querywise
cd querywise

# Create your .env (see .env.example)
cp .env.example .env
# Edit .env to add your API keys (or configure Ollama — see below)

# Start everything
docker compose up
```

| Service | URL |
|---------|-----|
| Frontend (Mantine) | http://localhost:5173 |
| Angular Chat | http://localhost:4200 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| App Database (pgvector) | localhost:5434 |
| Sample Database | localhost:5433 |

### Connecting to a Host Database from Docker

If QueryWise is running in Docker but your target PostgreSQL is running on the host machine, use:

`postgresql://<user>:<password>@host.docker.internal:<port>/<database>`

Example:

`postgresql://qadmin:your-password@host.docker.internal:5434/Adventureworks_aw`

On Linux, if `host.docker.internal` is not resolvable in your containers, add this to the `backend` service in `docker-compose.yml`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### Connecting to SQL Server

1. Select **SQL Server** as the connector type in the Add Connection form
2. Enter an ODBC-style connection string, for example:

```text
SERVER=localhost,1433;DATABASE=master;UID=sa;PWD=your-password;Encrypt=yes;TrustServerCertificate=yes;
```

3. Set the **Default schema** to `dbo` unless your tables live elsewhere
4. Click Create, then Test and Introspect

Local development requirements:

- Install the backend SQL Server extra: `pip install -e ".[llm,dev,sqlserver]"`
- Install a Windows ODBC driver: **ODBC Driver 18 for SQL Server** or **ODBC Driver 17 for SQL Server**

The backend auto-injects the best available SQL Server ODBC driver if the connection string omits `DRIVER=...`.

### First Steps

1. Open http://localhost:5173 (or Angular Chat at http://localhost:4200)
2. Add a database connection and run schema introspection
3. Ask a natural language query against your connected database

### Using Ollama (Fully Local — No API Keys)

QueryWise can run entirely on local hardware using Ollama. No cloud API keys needed.

```bash
# Configure .env for Ollama
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768

# --- Or configure for Anthropic (Claude) ---
# DEFAULT_LLM_PROVIDER=anthropic
# DEFAULT_LLM_MODEL=claude-sonnet-4-20250514
# ANTHROPIC_API_KEY=your-anthropic-api-key
# OPENAI_API_KEY=your-openai-api-key          # Required for embeddings
# EMBEDDING_DIMENSION=1536

# --- Or configure for OpenAI ---
# DEFAULT_LLM_PROVIDER=openai
# DEFAULT_LLM_MODEL=gpt-4o
# OPENAI_API_KEY=your-openai-api-key
# EMBEDDING_DIMENSION=1536

# Start the stack (includes Ollama service)
docker compose up

# Provide ollama models on host or pull the required models in docker (CPU) (first time only)
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

**Switching providers:** When you change `EMBEDDING_DIMENSION` (e.g., 768 → 1536), migration `002_configurable_embedding_dim` automatically resizes vector columns and **clears all existing embeddings** — they are not portable across providers (different dimensions and incompatible vector spaces). Embeddings regenerate automatically on first use with the new provider. Your metadata (glossary, metrics, dictionary) is preserved; only the embedding vectors are reset.

> **GPU support:** Uncomment the `deploy.resources` section in `docker-compose.yml` under the `ollama` service to enable NVIDIA GPU acceleration.

---

## Development Setup (without Docker)

### Backend

```bash
cd backend

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[llm,dev]"

# If you want to connect to SQL Server locally
pip install -e ".[llm,dev,sqlserver]"

# Start PostgreSQL with pgvector (must be running on localhost:5432)
# Run migrations
alembic upgrade head

# Start the dev server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server (proxies /api to localhost:8000)
npm run dev
```

### Angular Chat (Alternative UI)

```bash
cd angular-test

# Install dependencies
npm install

# Start dev server on port 4200
npm run start
```

### Database Setup

The application requires:

1. **App database** (PostgreSQL with pgvector extension) — stores metadata, glossary, embeddings, query history
2. **Target database** — the database you want to query with natural language

For development, `docker compose up app-db` starts the app database without the full stack.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://querywise:querywise_dev@localhost:5432/querywise` | App metadata database connection |
| `ENVIRONMENT` | `development` | Environment name |
| `DEBUG` | `false` | Enable debug mode |
| `ENCRYPTION_KEY` | `dev-encryption-key-change-in-production` | Fernet key for encrypting stored connection strings |
| `CORS_ORIGINS` | `["http://localhost:5173", "http://localhost:5175", "http://localhost:4200"]` | Allowed CORS origins (JSON list) |
| `DEFAULT_LLM_PROVIDER` | `openrouter` | Default LLM provider (`anthropic`, `openai`, `ollama`, `openrouter`, `groq`) |
| `DEFAULT_LLM_MODEL` | `deepseek/deepseek-v3.2` | Default model for SQL generation |
| `EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Model for generating embeddings (used with OpenAI provider or `EMBEDDING_PROVIDER=openrouter`) |
| `EMBEDDING_DIMENSION` | `1536` | Embedding vector dimension |
| `DEFAULT_QUERY_TIMEOUT_SECONDS` | `30` | Max query execution time |
| `DEFAULT_MAX_ROWS` | `1000` | Max rows returned per query |
| `MAX_RETRY_ATTEMPTS` | `3` | Max SQL correction retries |
| `MAX_QUERIES_PER_MINUTE` | `30` | Rate limit |
| `MAX_CONTEXT_TABLES` | `8` | Max tables included in LLM context |
| `MAX_SAMPLE_QUERIES` | `3` | Max sample queries included in context |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.1:8b` | Ollama model for completions |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Ollama model for embeddings (only when using Ollama for embeddings) |
| `OPENROUTER_API_KEY` | — | OpenRouter API key (required if using OpenRouter) |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v3.2` | OpenRouter model for Composer (SQL generation + error correction) |
| `RESOLVER_MODEL` | `openai/gpt-4.1-nano` | OpenRouter model for Resolver (intent classification + question rewrite) |
| `INTERPRETER_MODEL` | `meta-llama/llama-3.1-8b-instruct` | OpenRouter model for Interpreter (result → natural language summary) |
| `GROQ_API_KEY` | — | Groq API key (required if using Groq) |
| `GROQ_MODEL` | `meta-llama/llama-3.1-70b-versatile` | Groq model |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required if using Anthropic) |
| `OPENAI_API_KEY` | — | OpenAI API key (required if using OpenAI) |
| `VITE_API_URL` | `http://localhost:8000` | Frontend: backend API URL |

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

---

## Groq Support

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

---

## Project Structure

```
querywise/
├── backend/                     # Python FastAPI backend
│   ├── app/
│   │   ├── api/v1/             # API endpoints and schemas
│   │   │   ├── endpoints/      # FastAPI route handlers
│   │   │   └── schemas/       # Pydantic request/response models
│   │   ├── core/              # Exceptions, logging, security
│   │   ├── connectors/        # Database connector plugin system
│   │   │   ├── postgresql/     # PostgreSQL connector
│   │   │   └── sqlserver/     # SQL Server connector
│   │   ├── db/                # Database configuration
│   │   │   ├── models/        # SQLAlchemy ORM models
│   │   │   └── session.py     # Async engine + session factory
│   │   ├── llm/               # LLM integration
│   │   │   ├── agents/        # LLM agents (composer, validator, interpreter, error handler)
│   │   │   ├── providers/     # LLM provider implementations
│   │   │   ├── prompts/       # System/user prompt templates
│   │   │   ├── graph/        # LangGraph stateful graph
│   │   │   └── router.py    # Complexity estimation + model routing
│   │   ├── semantic/         # Core semantic layer
│   │   │   ├── context_builder.py
│   │   │   ├── schema_linker.py
│   │   │   ├── glossary_resolver.py
│   │   │   └── knowledge_resolver.py
│   │   ├── services/         # Business logic services
│   │   └── utils/            # Utility functions
│   ├── scripts/               # Backend utility scripts
│   └── tests/                # Backend tests
│
├── frontend/                   # React + Mantine UI (port 5173)
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   └── utils/
│   └── package.json
│
├── angular-test/               # Angular 21 chat application
│   └── src/
│
├── docker-compose.yml        # Docker composition file
├── .env.example             # Environment variable template
├── README.md               # This file
└── CLAUDE.md               # Developer documentation
```

---

## License

MIT License

Copyright (c) 2024 QueryWise

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.