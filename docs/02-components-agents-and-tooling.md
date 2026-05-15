# Components, Agents, and Tooling

## Purpose

This document is the ownership map for the current codebase. It focuses on the components that are active today, rather than older experimental or deprecated nodes.

## Backend ownership map

### API layer

`backend/app/api/v1/router.py` wires these endpoint groups:

- `auth`
- `health`
- `query`
- `connections`
- `schemas`
- `glossary`
- `metrics`
- `dictionary`
- `sample_queries`
- `query_history`
- `knowledge`
- `sessions`
- `users`
- `admin`

### Query orchestration

Primary files:

- `backend/app/services/query_service.py`
- `backend/app/llm/graph/graph.py`
- `backend/app/llm/graph/state.py`

Responsibilities:

- Build initial graph state from API input, session ID, and auth scope
- Invoke the compiled LangGraph singleton
- Normalize the final response payload returned to the API layer

### Active graph nodes

| Node | Responsibility |
|---|---|
| `load_history` | Loads recent messages plus last successful query context |
| `resolve_turn` | Decides between fresh query, follow-up refinement, show SQL, explain result, or clarification |
| `handle_follow_up` | Reuses cached answers or routes refined SQL through validation |
| `build_context` | Builds semantic prompt context and injects RBAC scope blocks |
| `similarity_check` | Reuses validated sample-query SQL when similarity is high |
| `compose_sql` | Calls the composer LLM to produce SQL |
| `validate_sql` | Verifies schema usage and SQL safety expectations |
| `handle_error` | Performs retry-correction after invalid or failed SQL |
| `execute_sql` | Executes SQL via the selected connector |
| `answer_from_state` | Answers show-SQL and explain-result turns from cached state |
| `interpret_result` | Produces summary, highlights, and follow-up suggestions |
| `write_history` | Persists query execution plus compact turn context |

### LLM-facing agents

Main agent classes live in `backend/app/llm/agents/`:

- `QueryComposerAgent`
- `SQLValidatorAgent`
- `ErrorHandlerAgent`
- `ResultInterpreterAgent`

The backend also uses provider routing through `backend/app/llm/router.py` and concrete provider implementations in `backend/app/llm/providers/`.

### Semantic layer

Main semantic modules:

- `context_builder.py`: orchestration of retrieval and prompt construction
- `schema_linker.py`: hybrid table discovery
- `glossary_resolver.py`: glossary and metric lookup
- `knowledge_resolver.py`: knowledge chunk retrieval
- `prompt_assembler.py`: final prompt generation
- `relevance_scorer.py`: keyword extraction and scoring helpers used in neighbour expansion

### Connector layer

Connectors are in `backend/app/connectors/`. They enforce read-only querying and are created through `connector_registry.py`.

The documented first-class connectors in active use are:

- PostgreSQL
- SQL Server

### Persistence layer

Important ORM models:

- `DatabaseConnection`
- `CachedTable`, `CachedColumn`, `CachedRelationship`
- `GlossaryTerm`
- `MetricDefinition`
- `SampleQuery`
- `KnowledgeDocument`, `KnowledgeChunk`
- `ChatSession`
- `QueryExecution`
- `User`

## Frontend ownership map

### React admin UI

`frontend/` is the configuration and metadata management interface.

Key responsibilities:

- user login
- connection management
- schema inspection flows
- semantic metadata CRUD for glossary, metrics, dictionary, sample queries, and knowledge

### Angular chat UI

`angular-test/` is the conversational client.

Key runtime pieces:

- `src/app/services/chat.service.ts`: session creation, SSE query streaming, and local persistence of recent questions
- `src/app/chat/chat.component.ts`: chat interaction state plus result-table state
- `src/app/chat/chat.component.html`: message rendering, clarification chips, SQL display, result table, and pagination
- `src/app/chat/chat.component.css`: presentation of the conversational UI and table controls

The current Angular result table supports:

- client-side search
- sortable headers
- pagination
- rows-per-page selection
- CSV export

## Tooling and observability

Backend development tools:

- `pytest`
- `ruff`
- `mypy`
- Alembic migrations

Operational helpers:

- `/api/v1/health`
- `/api/v1/ready`
- `/api/v1/embeddings/status`
- `/metrics`

The backend also supports optional LangSmith tracing through `settings.langsmith_tracing_enabled`.

### `sql_sanitizer.py`

**File:** `backend/app/utils/sql_sanitizer.py` — `check_sql_safety(sql)`

Blocks:
- DDL: `CREATE`, `DROP`, `ALTER`, `TRUNCATE`
- DML: `INSERT`, `UPDATE`, `DELETE`, `MERGE`
- Admin: `GRANT`, `REVOKE`, `EXEC`, `EXECUTE`, `CALL`
- Stacked queries (multiple statements via `;`)
- Dangerous functions: `pg_sleep`, `xp_cmdshell`, `OPENROWSET`, `BULK INSERT`
- BigQuery-specific: `EXPORT DATA`, `LOAD DATA`
- Databricks-specific: `COPY INTO`, `OPTIMIZE`, `VACUUM`

### `repair_json()` in `llm/utils.py`

**File:** `backend/app/llm/utils.py`

Handles common local model JSON issues: strips markdown code fences (` ```json ... ``` `), converts Python `True`/`False`/`None` to JSON equivalents, removes trailing commas before `}` and `]`.
