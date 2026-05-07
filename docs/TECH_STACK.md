# QueryWise Tech Stack

## Backend

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| API | FastAPI |
| Orchestration | LangGraph |
| ORM | SQLAlchemy async |
| Metadata DB | PostgreSQL 16 + pgvector |
| PostgreSQL driver | asyncpg |
| SQL Server driver | aioodbc |

## Frontends

| Surface | Technology | Port |
|---|---|---|
| Admin UI | React 19, TypeScript, Vite, Mantine | 5173 |
| Chat UI | Angular 21 | 4200 |

## LLM and embedding support

Supported provider families:

- Anthropic
- OpenAI
- Ollama
- OpenRouter
- Groq

Important model settings:

- `DEFAULT_LLM_MODEL`
- `OPENROUTER_MODEL`
- `RESOLVER_MODEL`
- `INTERPRETER_MODEL`
- `EMBEDDING_MODEL`

## Data and retrieval

| Concern | Technology |
|---|---|
| Semantic table search | pgvector + keyword scoring |
| Knowledge retrieval | chunked text + embeddings |
| Query history | PostgreSQL JSONB-backed audit records |
| Streaming responses | Server-sent events |

## Key code locations

| Path | Purpose |
|---|---|
| `backend/app/llm/graph/graph.py` | Live LangGraph assembly |
| `backend/app/services/query_service.py` | Query orchestration entry point |
| `backend/app/semantic/context_builder.py` | Semantic prompt context assembly |
| `backend/app/connectors/` | Database connector implementations |
| `frontend/src/` | React admin UI |
| `angular-test/src/` | Angular chat UI |

## Default local commands

```bash
docker compose up

cd backend
uvicorn app.main:app --reload

cd frontend
npm run dev

cd angular-test
npm run start
```