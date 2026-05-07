# QueryWise

QueryWise is a full-stack text-to-SQL system with a semantic metadata layer. It accepts natural-language questions, builds database-aware business context, generates or reuses SQL through a LangGraph pipeline, executes against a connected database, and returns a human-readable answer.

## What is in the repo

- FastAPI backend with async SQLAlchemy, LangGraph orchestration, and connector plugins
- React admin UI on port `5173` for connections and semantic metadata management
- Angular chat UI on port `4200` for the end-user conversational experience
- PostgreSQL metadata store with pgvector for embeddings, query history, and semantic assets

## Current execution flow

The live graph is centered on a multi-turn query pipeline:

```text
load_history
  -> resolve_turn
     -> handle_follow_up        when follow-up refinement is enabled
     -> build_context           for fresh or escalated queries
     -> answer_from_state       for show_sql / explain_result
     -> write_history           for clarification turns

build_context
  -> similarity_check
  -> compose_sql               when no validated sample-query shortcut exists
  -> validate_sql
  -> execute_sql
  -> interpret_result
  -> write_history
```

Two recent behaviors matter for operators and QA:

- Follow-up refinement is feature-flagged with `USE_FOLLOW_UP_PATH`
- Empty query results are now explicit and return `result_status = "empty"` with `No matching rows found.`

## Quick start

For the full walkthrough, use [docs/onboarding-guide.md](docs/onboarding-guide.md).

### Docker path

```bash
cp .env.example .env
docker compose up
```

Services:

| Service | URL |
|---|---|
| React admin UI | http://localhost:5173 |
| Angular chat UI | http://localhost:4200 |
| Backend API | http://localhost:8000 |
| OpenAPI docs | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |
| Ready | http://localhost:8000/api/v1/ready |

### Local development path

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[llm,dev,sqlserver]"
alembic upgrade head
uvicorn app.main:app --reload
```

React admin UI:

```bash
cd frontend
npm install
npm run dev
```

Angular chat UI:

```bash
cd angular-test
npm install
npm run start
```

## Key features

- Hybrid semantic retrieval: embeddings, keyword matching, glossary, metrics, knowledge chunks, and sample queries
- Query history persisted per session with result previews and turn context for follow-ups
- Role-aware scope constraints for end users with `resource_id` or `employee_id`
- Streaming query progress over SSE from `/api/v1/query/stream`
- Angular result tables with search, sort, pagination, and CSV export
- SQL safety enforcement before execution plus retry-correction on failed LLM-generated SQL

## Core configuration

Important environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://querywise:querywise_dev@localhost:5432/querywise` | Metadata database |
| `DEFAULT_LLM_PROVIDER` | `anthropic` | Primary provider |
| `DEFAULT_LLM_MODEL` | `claude-sonnet-4-20250514` | Default generation model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSION` | `1536` | Vector dimension |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v3.2` | Composer model when using OpenRouter |
| `RESOLVER_MODEL` | `openai/gpt-4.1-nano` | Turn resolver model |
| `INTERPRETER_MODEL` | `meta-llama/llama-3.1-8b-instruct` | Result interpreter model |
| `USE_FOLLOW_UP_PATH` | `false` | Enables compact follow-up refinement |
| `AUTO_SETUP_SAMPLE_DB` | `false` | Seeds the sample environment on startup |

When switching embedding providers, keep `EMBEDDING_DIMENSION` aligned with the model. Startup logic resizes vector columns and invalidates stale embeddings when dimensions change.

## Documentation map

- [docs/00_INDEX.md](docs/00_INDEX.md): curated documentation index
- [docs/01-system-architecture-and-execution-flow.md](docs/01-system-architecture-and-execution-flow.md): live graph and request flow
- [docs/03-data-and-interface-contracts.md](docs/03-data-and-interface-contracts.md): core models and API contracts
- [docs/04-operations-behavior-and-limitations.md](docs/04-operations-behavior-and-limitations.md): runtime behavior, feature flags, and limits
- [docs/QA_TESTING.md](docs/QA_TESTING.md): manual QA scenarios for current behavior

## Status of older docs

The codebase recently moved away from older intent-template documentation. The curated docs under `docs/` are now the canonical source. Redundant or accidental markdown files have been removed or superseded.