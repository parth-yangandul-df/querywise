# QueryWise Architecture

## System Overview

QueryWise is a text-to-SQL application with a semantic metadata layer. Users ask natural language questions, an LLM generates SQL using business context (schema, glossary, metrics, knowledge), executes against their database, and returns human-readable answers.

## High-Level Data Flow

```
User Question → FastAPI → LangGraph Pipeline → LLM (generate SQL) → Connector (execute) → LLM (interpret results) → User
                                      ↑
                              Semantic Context Builder
                                      ↑
                     Schema + Glossary + Metrics + Knowledge
```

## Key Components

### 1. API Layer (`backend/app/api/v1/endpoints/`)
- **query.py**: Main endpoints — `POST /query`, `POST /query/stream`, `POST /query/execute-sql`, `POST /query/sql-only`
- Returns SQL + results + LLM interpretation
- Supports server-sent events (SSE) streaming

### 2. Query Service (`backend/app/services/query_service.py`)
- Orchestrates full NL → SQL → results pipeline
- Uses LangGraph for stateful multi-turn conversations

### 3. LangGraph Pipeline (`backend/app/llm/graph/graph.py`)
- **Nodes**: load_history → resolve_turn → build_context → similarity_check → compose_sql → validate_sql → execute_sql → interpret_result → write_history
- Decision points: intent classification (query/show_sql/explain_result/clarification), similarity shortcut, validation + retry

### 4. Semantic Layer (`backend/app/semantic/`)
- **context_builder.py**: Hybrids vector + keyword search to find relevant tables/columns
- **schema_linker.py**: Links tables to user question via embeddings
- **glossary_resolver.py**: Resolves business terms from glossary/metrics/dictionary
- **relationship_inference.py**: Infers FKs for schemas without enforced relationships

### 5. LLM Agents (`backend/app/llm/agents/`)
- **query_composer.py**: Generates SQL from NL + context
- **sql_validator.py**: Static validation vs schema
- **error_handler.py**: LLM-based SQL correction (max 3 retries)
- **result_interpreter.py**: Produces human-readable answer + highlights + follow-ups

### 6. Connectors (`backend/app/connectors/`)
- **base_connector.py**: Abstract interface — `execute_query()`, `introspect_schemas()`, `get_sample_values()`
- **postgresql/**: asyncpg implementation
- **sqlserver/**: aioodbc implementation

### 7. Database Models (`backend/app/db/models/`)
- **schema_cache.py**: CachedTable, CachedColumn, CachedRelationship (post-introspection)
- **glossary.py**, **metric.py**, **dictionary.py**: Semantic metadata
- **sample_query.py**: Example queries with embeddings
- **knowledge.py**: Imported documentation chunks
- **query_history.py**: Execution history

### 8. Frontends
- **frontend/src/** (port 5173): Mantine UI — full admin dashboard
- **chatbot-frontend/src/** (port 5174): React + Tailwind + shadcn/ui — chat interface

## Architecture Patterns

- **Async everywhere**: All DB operations, HTTP calls, LLM calls are async
- **Stateful graph**: LangGraph maintains conversation state across turns
- **Graceful degradation**: Falls back to keyword-only if embedding unavailable
- **Read-only enforcement**: Connectors block DDL/DML + admin commands
- **Background embeddings**: Non-blocking generation on startup/CRUD

## Data Flow Details

1. User submits question → `/api/v1/query` endpoint
2. `query_service.execute_nl_query()` builds initial GraphState
3. LangGraph processes through nodes:
   - **load_history**: Fetches prior turns from DB
   - **resolve_turn**: LLM classifies intent (query/show_sql/explain_result/clarification)
   - **build_context**: Hybrid retrieval (embedding + keyword + FK expansion)
   - **similarity_check**: If similar sample query exists (≥0.92 similarity), skip LLM
   - **compose_sql**: LLM generates SQL from context
   - **validate_sql**: Static check vs schema tables
   - **handle_error**: LLM corrects issues (up to 3 retries)
   - **execute_sql**: Runs against target DB via connector
   - **interpret_result**: LLM produces natural language answer
   - **write_history**: Persists to app DB
4. Response returned with SQL, results, summary, highlights, follow-ups