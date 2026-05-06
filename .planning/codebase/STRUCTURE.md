# QueryWise Code Structure

## Directory Layout

```
querywise/
├── backend/
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── endpoints/      # FastAPI route handlers
│   │   │   └── schemas/      # Pydantic request/response models
│   │   ├── config.py        # Environment configuration
│   │   ├── core/          # Logging, exceptions, security
│   │   ├── connectors/    # Database connector plugins (PostgreSQL, SQL Server)
│   │   ├── db/
│   │   │   ├── models/     # SQLAlchemy ORM models
│   │   │   └── session.py # Async engine + session factory
│   │   ├── llm/
│   │   │   ├── agents/    # LLM agents (composer, validator, interpreter, error handler)
│   │   │   ├── graph/    # LangGraph stateful pipeline
│   │   │   ├── providers/ # LLM provider implementations
│   │   │   ├── prompts/  # System/user prompt templates
│   │   │   └── router.py # Complexity-based model routing
│   │   ├── semantic/       # Core IP: context builder, schema linker, glossary resolver
│   │   └── services/      # Business logic (query, connection, embedding)
│   └── main.py           # FastAPI app factory
├── frontend/              # Mantine UI (port 5173)
└── chatbot-frontend/     # React + Tailwind (port 5174)
```

## Module Purposes

### `backend/app/api/v1/endpoints/`
| File | Purpose |
|------|--------|
| `query.py` | Main query endpoints — execute NL, stream, execute raw SQL |
| `connections.py` | CRUD for database connections |
| `glossary.py` | CRUD for business term glossary |
| `metrics.py` | CRUD for business metrics |
| `dictionary.py` | CRUD for column descriptions |
| `knowledge.py` | Import/search imported documentation |
| `sessions.py` | Chat session management |
| `query_history.py` | Query execution history |
| `auth.py` | JWT authentication |
| `users.py` | User management (admin) |
| `schemas.py` | Schema introspection endpoints |

### `backend/app/semantic/`
| File | Purpose |
|------|--------|
| `context_builder.py` | Orchestrates hybrid context selection |
| `schema_linker.py` | Links tables to user question via embeddings |
| `glossary_resolver.py` | Resolves business terms from metadata |
| `relationship_inference.py` | Infers FKs for sparse schemas |
| `prompt_assembler.py` | Formats context into LLM prompt |
| `relevance_scorer.py` | Scores retrieved contexts |

### `backend/app/llm/graph/`
| File | Purpose |
|------|--------|
| `graph.py` | LangGraph StateGraph assembly |
| `state.py` | GraphState TypedDict definition |
| `nodes/` | Graph node implementations |

### `backend/app/llm/agents/`
| File | Purpose |
|------|--------|
| `query_composer.py` | Generates SQL from NL + context |
| `sql_validator.py` | Static validation vs schema |
| `error_handler.py` | LLM-based SQL correction |
| `result_interpreter.py` | Produces natural language answer |

### `backend/app/connectors/`
| File | Purpose |
|------|--------|
| `base_connector.py` | Abstract interface |
| `connector_registry.py` | Factory for connector instances |
| `postgresql/connector.py` | asyncpg implementation |
| `sqlserver/connector.py` | aioodbc implementation |

### `backend/app/services/`
| File | Purpose |
|------|--------|
| `query_service.py` | Orchestrates NL → SQL → results pipeline |
| `connection_service.py` | Connection CRUD + introspection |
| `embedding_service.py` | Text embedding generation |
| `schema_service.py` | Schema cache management |
| `knowledge_service.py` | Knowledge import + search |
| `setup_service.py` | Startup initialization |

### `backend/app/db/models/`
| File | Purpose |
|------|--------|
| `connection.py` | Database connections (encrypted creds) |
| `schema_cache.py` | Introspected schema (tables, columns, FKs) |
| `glossary.py` | Business term definitions |
| `metric.py` | Business metric definitions |
| `dictionary.py` | Column descriptions |
| `sample_query.py` | Example queries with embeddings |
| `knowledge.py` | Imported documentation |
| `query_history.py` | Execution history |
| `chat_session.py` | Multi-turn conversation sessions |
| `user.py` | User accounts + RBAC |

### `frontend/src/` (Mantine UI)
| Path | Purpose |
|------|--------|
| `pages/QueryPage.tsx` | Main query interface |
| `pages/ConnectionsPage.tsx` | Connection management |
| `pages/GlossaryPage.tsx` | Glossary CRUD |
| `pages/MetricsPage.tsx` | Metrics CRUD |
| `pages/DictionaryPage.tsx` | Column descriptions |
| `pages/KnowledgePage.tsx` | Knowledge import |
| `pages/HistoryPage.tsx` | Query history |
| `pages/LoginPage.tsx` | Authentication |
| `api/` | API client (Axios) |
| `components/` | Reusable UI components |

### `chatbot-frontend/src/` (React + Tailwind)
| Path | Purpose |
|------|--------|
| `pages/StandaloneChatPage.tsx` | Main chat interface |
| `pages/ChatQueryPage.tsx` | Query execution with streaming |
| `pages/ConnectionsPage.tsx` | Connection selection |
| `pages/HistoryPage.tsx` | Past conversations |
| `api/queryApi.ts` | Query API client |
| `api/connectionApi.ts` | Connection API client |

## Key Files

| File | Purpose |
|------|--------|
| `backend/app/main.py` | FastAPI app factory + middleware + lifespan |
| `backend/app/config.py` | Settings via pydantic-settings |
| `backend/app/api/v1/router.py` | API route aggregation |
| `backend/app/llm/graph/graph.py` | LangGraph pipeline definition |
| `backend/app/services/query_service.py` | Query orchestration |
| `backend/app/semantic/context_builder.py` | Hybrid context selection |
| `backend/app/connectors/postgresql/connector.py` | PostgreSQL executor |
| `backend/app/connectors/sqlserver/connector.py` | SQL Server executor |