# QueryWise Tech Stack

## Runtime
| Layer | Technology |
|-------|------------|
| Backend | Python 3.12+ |
| API Framework | FastAPI |
| Graph Orchestration | LangGraph |
| Database ORM | SQLAlchemy (async) |
| DB Driver | asyncpg (PostgreSQL), aioodbc (SQL Server) |
| Vector Store | pgvector |

## Frontends
| App | Technology | Port |
|-----|-----------|------|
| Main UI | React 19 + TypeScript + Mantine UI | 5173 |
| Chat UI | Angular 21 | 4200 |

## LLM + Embeddings (OpenRouter Only)
| Use | Model | Config |
|------|-------|--------|
| SQL Generation | deepseek/deepseek-v3.2 | `DEFAULT_LLM_MODEL` |
| Intent Classification | openai/gpt-4.1-nano | `RESOLVER_MODEL` |
| Result Interpretation | meta-llama/llama-3.1-8b-instruct | `INTERPRETER_MODEL` |
| Embeddings | text-embedding-3-small | `EMBEDDING_MODEL` |

## Database Connections
| Database | Port | Used For |
|----------|------|---------|
| App DB (PostgreSQL + pgvector) | 5434 | Metadata, embeddings, query history |
| Target DB | Variable | User's database to query |

## Key Files
| File | Purpose |
|------|--------|
| `backend/app/llm/graph/graph.py` | LangGraph state machine |
| `backend/app/llm/graph/nodes/similarity_check.py` | Exact-duplicate shortcut |
| `backend/app/semantic/schema_linker.py` | Find relevant tables/cols |
| `backend/app/semantic/glossary_resolver.py` | Business term resolution |
| `backend/app/connectors/` | DB plugin system (PostgreSQL, SQL Server) |
| `docker-compose.yml` | Full stack orchestration |

## Quick Config (OpenRouter Only)
```bash
# Required in .env
DEFAULT_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
EMBEDDING_PROVIDER=openrouter
EMBEDDING_DIMENSION=1536
```

## Run Commands
```bash
# Full stack (Docker)
docker compose up

# Backend only
cd backend && uvicorn app.main:app --reload

# Frontend
cd frontend && npm run dev

# Angular Chat
cd angular-test && npm run start
```