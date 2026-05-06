# Components, Agents & Tooling

## Overview

This document catalogs every major component in QueryWise: the LangGraph graph nodes, domain agents, LLM agents, semantic layer components, connectors, LLM providers, and frontend structure.

---

## LangGraph Pipeline Components

### Graph Assembly

**File:** `backend/app/llm/graph/graph.py`

Builds a `StateGraph` over `QueryState`. All nodes are registered with `add_node()` and edges (including conditional edges) are added before `compile()` is called. The compiled graph is a singleton reused across requests.

### State Schema

**File:** `backend/app/llm/graph/state.py` — `GraphState` (TypedDict)

| Field | Type | Description |
|---|---|---|
| `question` | `str` | The user's natural-language question |
| `connection_id` | `str` | Target database connection ID (UUID as str) |
| `session_id` | `str \| None` | Chat session ID (UUID as str) |
| `conversation_history` | `list[dict]` | Conversation history (role/content pairs, max 6 turns) |
| `user_id` | `str \| None` | Authenticated user's ID (UUID as str); None if unauthenticated |
| `user_role` | `str \| None` | "admin" \| "manager" \| "user"; None if unauthenticated |
| `resource_id` | `int \| None` | Only set for "user" role; None for admin/manager/unauthenticated |
| `domain` | `str \| None` | "resource" \| "client" \| "project" \| "timesheet" \| "user_self" |
| `intent` | `str \| None` | Matched intent name |
| `confidence` | `float` | Cosine similarity score |
| `params` | `dict` | Extracted parameters (skill, dates, names) |
| `filters` | `list` | FilterClause objects extracted by filter_extractor node |
| `query_plan` | `dict \| None` | QueryPlan serialized as dict |
| `sql` | `str \| None` | Generated or templated SQL |
| `result` | `QueryResult \| None` | Query execution result |
| `generated_sql` | `str \| None` | LLM path only; None for domain tool path |
| `answer` | `str \| None` | Final natural-language answer |
| `highlights` | `list[str]` | Result highlights |
| `suggested_followups` | `list[str]` | Suggested follow-up questions |
| `error` | `str \| None` | Error message if pipeline failed |
| `execution_time_ms` | `float \| None` | Query wall-clock time in milliseconds |

---

## Graph Nodes

### `classify_intent`

**File:** `backend/app/llm/graph/nodes/intent_classifier.py`

- Embeds the question using the configured embedding provider.
- Computes cosine similarity against pre-embedded descriptions of all 24 intents from `intent_catalog.py`.
- Writes `domain`, `intent`, `confidence`, and `fallback_intent` (second-best match) to state.
- Threshold: `TOOL_CONFIDENCE_THRESHOLD` env var (default `0.65`).

### `extract_filters`

**File:** `backend/app/llm/graph/nodes/filter_extractor.py`

- Calls the LLM with the question and matched intent to extract structured filter clauses.
- Uses regex post-processing to parse dates, numeric ranges, and text patterns.
- Writes `filters` (list of FilterClause objects) to state.

### `update_query_plan`

**File:** `backend/app/llm/graph/nodes/plan_updater.py`

- Builds a `QueryPlan` object from domain, intent, and extracted filters.
- Resolves schema references needed for SQL compilation.
- Writes `query_plan` (serialized dict) to state.

### `run_domain_tool`

Inline in `graph.py`. Resolves the intent name to an agent via `DomainAgentRegistry.get(intent)` and calls `agent.run(intent, params, session, connection)`. Writes `sql` and `rows` to state.

### `run_fallback_intent`

**File:** `backend/app/llm/graph/nodes/fallback_intent.py`

- Triggered when `run_domain_tool` returned 0 rows and state has a `fallback_intent`.
- Re-runs the domain tool with the next-best intent.
- If still 0 rows, the pipeline routes to `llm_fallback`.

### `llm_fallback`

**File:** `backend/app/llm/graph/nodes/llm_fallback.py`

- Calls `build_context()` from the semantic layer.
- Runs `QueryComposerAgent` → `SQLValidatorAgent` → connector execution.
- Calls `ErrorHandlerAgent` on failure; retries up to 3 times.
- Writes `sql`, `rows`, and `error` to state.

### `interpret_result`

**File:** `backend/app/llm/graph/nodes/result_interpreter.py`

- Calls `ResultInterpreterAgent.interpret(question, sql, rows)`.
- Writes `answer` to state.
- On failure, logs error and leaves `answer` as `None` (swallowed).

### `write_history`

**File:** `backend/app/llm/graph/nodes/history_writer.py`

- Persists a `QueryExecution` row to `app-db`.
- On the first turn of a session, auto-generates and sets the session title (via LLM or truncated question).
- On failure, logs error and continues (swallowed).

---

## Intent Catalog

**File:** `backend/app/llm/graph/intent_catalog.py`

24 intents across 5 domains. Each intent has a `name`, `description` (used for embedding), and `param_schema`.

| Domain | Intents (6) |
|---|---|
| `resource` | active resources, benched resources, resource by skill, resource availability, resource project assignments, resource skills list |

| Domain | Intents (3) |
|---|---|
| `client` | active clients, client projects, client status |

| Domain | Intents (6) |
|---|---|
| `project` | active projects, project by client, project budget, project resources, project timeline, overdue projects |

| Domain | Intents (4) |
|---|---|
| `timesheet` | approved timesheets, timesheet by period, unapproved timesheets, timesheet by project |

| Domain | Intents (5) |
|---|---|
| `user_self` | my projects, my allocation, my timesheets, my skills, my utilization |

---

## Domain Agents

All extend `BaseDomainAgent` (`backend/app/llm/graph/domains/base_domain.py`).

### `BaseDomainAgent`

- `run(intent, params, session, connection)` → `(sql: str, rows: list[dict])`
- Dispatches to the intent-specific handler method via a dict lookup.
- All SQL templates are defined as class-level constants or inline strings.
- Parameter substitution is done with Python f-strings or `str.format()` (not parameterized queries).

### `ResourceAgent`

**File:** `backend/app/llm/graph/domains/resource.py`

Handles 9 resource intents. Example SQL template queries `resources`, `allocations`, `projects`, `departments` tables.

### `ClientAgent`

**File:** `backend/app/llm/graph/domains/client.py`

Handles 4 active intents (client_revenue handler commented out). Queries `clients`, `projects`, `contacts` tables.

### `ProjectAgent`

**File:** `backend/app/llm/graph/domains/project.py`

Handles 6 project intents. Queries `projects`, `milestones`, `risks`, `budgets`, `allocations` tables.

### `TimesheetAgent`

**File:** `backend/app/llm/graph/domains/timesheet.py`

Handles 4 timesheet intents. Queries `timesheets`, `resources`, `projects` tables.

### `DomainAgentRegistry`

**File:** `backend/app/llm/graph/domains/registry.py`

Maps intent name prefixes to agent class instances. E.g., any intent starting with `resource_` routes to `ResourceAgent`.

---

## LLM Agents

### `QueryComposerAgent`

**File:** `backend/app/llm/agents/query_composer.py`

- Takes: assembled context string, question, conversation history.
- Calls the LLM with the composer system prompt (`llm/prompts/composer_prompts.py`).
- Returns: raw SQL string.
- Injects up to 6 turns of conversation history into the prompt.

### `SQLValidatorAgent`

**File:** `backend/app/llm/agents/sql_validator.py`

- Takes: SQL string, schema context.
- Calls the LLM to review the SQL for correctness and safety.
- Returns: validated SQL (may be unchanged or corrected).

### `ErrorHandlerAgent`

**File:** `backend/app/llm/agents/error_handler.py`

- Takes: failed SQL, error message, schema context.
- Calls the LLM to produce a corrected SQL.
- Called by `llm_fallback` node on execution failure; up to 3 retries.

### `ResultInterpreterAgent`

**File:** `backend/app/llm/agents/result_interpreter.py`

- Takes: question, SQL, result rows.
- Calls the LLM with the interpreter system prompt (`llm/prompts/interpreter_prompts.py`).
- Returns: natural-language answer string.

---

## Semantic Layer Components

### `context_builder.py`

**File:** `backend/app/semantic/context_builder.py`

Orchestrates the 11-step context assembly (see Document 01 for step-by-step breakdown). Entry point: `build_context(question, connection_id, session)`.

### `schema_linker.py`

**File:** `backend/app/semantic/schema_linker.py`

Finds relevant tables for a question using a hybrid strategy:
- **Embedding similarity**: cosine distance against `cached_tables.embedding` vectors.
- **Keyword match**: table name tokens against question tokens.
- **Column keyword match**: column name tokens against question tokens.
- **Anchor tables**: always-included tables (configurable).
- **FK expansion**: adds FK-neighbour tables up to a configured depth.

On vector search failure (e.g., embedding model unavailable), catches the exception, rolls back the session, and falls back to keyword-only matching.

### `glossary_resolver.py`

**File:** `backend/app/semantic/glossary_resolver.py`

Finds glossary terms relevant to the question (embedding + keyword). Returns term definitions to inject into the prompt. Also returns table names referenced in glossary term definitions so `context_builder` can inject them if not already found.

### `prompt_assembler.py`

**File:** `backend/app/semantic/prompt_assembler.py`

Takes all resolved context (tables, columns, relationships, glossary, metrics, knowledge chunks, sample queries) and assembles the final prompt string passed to `QueryComposerAgent`.

### `relationship_inference.py`

**File:** `backend/app/semantic/relationship_inference.py`

Applies 4 hardcoded PRMS-specific join rules for schemas with sparse FK declarations:
- `Client → ClientStatus`
- `Project → ProjectStatus`
- `Project → Client`
- `Resource` self-join (manager relationship)

Returns additional JOIN clauses to append to the prompt context.

---

## Connectors

**Base:** `backend/app/connectors/base_connector.py` — `BaseConnector` (ABC)

Required methods: `connect()`, `disconnect()`, `execute(sql)`, `introspect()`, `test_connection()`.

**Registry:** `backend/app/connectors/connector_registry.py`

Maps connector type strings to classes. PostgreSQL is always registered. Others are registered lazily on import if their driver package is installed.

| Connector | Type Key | Driver | File |
|---|---|---|---|
| PostgreSQL | `postgresql` | `asyncpg` | `connectors/postgresql/` |
| BigQuery | `bigquery` | `google-cloud-bigquery` | `connectors/bigquery/` |
| Databricks | `databricks` | `databricks-sql-connector` | `connectors/databricks/` |
| SQL Server | `sqlserver` | `aioodbc` (ODBC 18/17) | `connectors/sqlserver/connector.py` |

**SQL Server specifics** (`connectors/sqlserver/connector.py`):
- Injects `TOP N` instead of `LIMIT` in generated SQL.
- Restricts schema to `dbo` only.
- Auto-excludes tables matching `ts_*`, `*backup*`, `*bakup*` patterns during introspection.

**BigQuery specifics:**
- Service account JSON stored encrypted in the `connection_string` field.

**Databricks specifics:**
- JSON config (`server_hostname`, `http_path`, `access_token`, `catalog`) stored encrypted.
- Supports Unity Catalog (`INFORMATION_SCHEMA`) and Hive metastore (`SHOW`/`DESCRIBE` fallback).

---

## LLM Providers

**Base:** `backend/app/llm/base_provider.py` — `BaseLLMProvider` (ABC)

Required methods: `complete(messages)`, `embed(text)`.

**Registry:** `backend/app/llm/provider_registry.py`

**Router:** `backend/app/llm/router.py` — `get_llm_provider()`, `get_embedding_provider()`

| Provider | Key | Completions | Embeddings |
|---|---|---|---|
| Anthropic | `anthropic` | Anthropic API | Falls back to OpenAI |
| OpenAI | `openai` | OpenAI API | OpenAI API |
| Ollama | `ollama` | Ollama REST | Ollama REST |
| OpenRouter | `openrouter` | OpenRouter API | Falls back to OpenAI |
| Groq | `groq` | Groq API | Falls back to OpenAI |

**Ollama embedding endpoint detection:** Tries `/api/embed` (Ollama 0.4+) first, falls back to `/api/embeddings` (legacy) automatically.

**JSON repair:** `repair_json()` in `backend/app/llm/utils.py` strips markdown fences, converts Python booleans (`True`/`False`) to JSON booleans, removes trailing commas. Used after every LLM response that expects JSON.

---

## Services

| Service | File | Responsibility |
|---|---|---|
| `QueryService` | `services/query_service.py` | Session/history loading, delegates to LangGraph pipeline, formats response |
| `ConnectionService` | `services/connection_service.py` | CRUD for `database_connections`, connection string encryption/decryption, test connection |
| `SchemaService` | `services/schema_service.py` | Schema introspection (calls connector `introspect()`), writes to `cached_tables`/`cached_columns`/`cached_relationships` |
| `EmbeddingService` | `services/embedding_service.py` | Generates and stores embeddings for all embeddable entities |
| `SetupService` | `services/setup_service.py` | Auto-setup logic: seeds IFRS 9 sample DB metadata, launches background embedding |
| `EmbeddingProgress` | `services/embedding_progress.py` | In-memory tracker for background embedding job progress |
| `KnowledgeService` | `services/knowledge_service.py` | Import text/HTML, section-aware chunking (450 words, 80 overlap), vector + keyword search |

---

## Frontend Applications

### Admin Frontend (`frontend/`)

**Tech:** React 19, TypeScript, Vite, Mantine UI, React Query, React Router

**Pages:**
- `Query` — ad-hoc SQL query runner
- `Connections` — manage database connections
- `Glossary` — glossary term CRUD
- `Metrics` — metric definition CRUD
- `Dictionary` — column value dictionary CRUD
- `Knowledge` — knowledge document import/management
- `History` — query execution history

**Key directories:**
- `frontend/src/api/` — Axios API clients (one per resource)
- `frontend/src/hooks/` — React Query hooks
- `frontend/src/components/layout/` — AppShell with sidebar navigation
- `frontend/src/types/` — TypeScript interfaces matching backend schemas

### Angular Chat (`angular-test/`)

**Tech:** Angular 21, TypeScript

End-user chat interface. Communicates with the backend `POST /api/v1/query/stream` endpoint. Maintains session state and renders conversation history.

---

## Utilities

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
