# Data and Interface Contracts

## Purpose

This document captures the current persistence model and the HTTP contracts that are active in the live backend.

## Core persistence entities

All app-owned data lives in the metadata database configured by `DATABASE_URL`.

### DatabaseConnection

Model: `backend/app/db/models/connection.py`

Important fields:

- `id`
- `name`
- `connector_type`
- `connection_string_encrypted`
- `default_schema`
- `read_only`
- `max_query_timeout_seconds`
- `max_rows`
- `allowed_table_names`
- `last_introspected_at`

This is the root entity for schema cache, semantic metadata, and sessions.

### Schema cache

Main models in `backend/app/db/models/schema_cache.py`:

- `CachedTable`
- `CachedColumn`
- `CachedRelationship`
- `DictionaryEntry`

These power table selection, column dictionaries, and relationship awareness in the semantic layer.

### Semantic metadata

Main models:

- `GlossaryTerm`
- `MetricDefinition`
- `SampleQuery`
- `KnowledgeDocument`
- `KnowledgeChunk`

These objects are connection-scoped and may have embeddings generated or regenerated in the background.

### Session and history

Main models:

- `ChatSession`
- `QueryExecution`

`QueryExecution` is the key audit record. Important fields include:

- `natural_language`
- `generated_sql`
- `final_sql`
- `execution_status`
- `error_message`
- `row_count`
- `execution_time_ms`
- `llm_provider`
- `llm_model`
- `retry_count`
- `result_summary`
- `turn_type`
- `clarification_reason`
- `result_columns`
- `result_preview_rows`
- `turn_context`

`turn_context` now stores compact follow-up data such as the resolved question, answer, SQL, preview rows, and `result_status`.

## API surface

Base prefix: `/api/v1`

Active router groups:

- `/auth`
- `/query`
- `/connections`
- `/schemas`
- `/glossary`
- `/connections/{connection_id}/metrics`
- `/columns/{column_id}/dictionary`
- `/connections/{connection_id}/sample-queries`
- `/query-history`
- `/knowledge`
- `/sessions`
- `/users`
- `/admin`
- `/health`, `/ready`, `/embeddings/status`

## Query API

### Request

Schema: `backend/app/api/v1/schemas/query.py::QueryRequest`

```json
{
  "connection_id": "uuid",
  "question": "Show open invoices",
  "session_id": "uuid or null",
  "clear_context": false
}
```

Notes:

- conversation history is backend-owned and loaded from persisted session history
- `clear_context=true` forces the backend to ignore prior session context for this request

### Response from `POST /api/v1/query`

The endpoint returns the raw dict produced by `execute_nl_query()`. In practice that includes:

```json
{
  "id": "uuid or null",
  "question": "Show open invoices",
  "turn_type": "query",
  "result_status": "success",
  "clarification_message": null,
  "clarification_options": [],
  "generated_sql": "SELECT ...",
  "final_sql": "SELECT ...",
  "explanation": null,
  "columns": ["invoice_id", "amount"],
  "column_types": ["uuid", "numeric"],
  "rows": [["...", 1200.5]],
  "row_count": 1,
  "execution_time_ms": 83.4,
  "truncated": false,
  "summary": "1 open invoice found.",
  "highlights": [],
  "suggested_followups": ["Show SQL"],
  "llm_provider": "openrouter",
  "llm_model": "deepseek/deepseek-v3.2",
  "retry_count": 0
}
```

Clarification turns return the same general shape but with:

- `turn_type = "clarification"`
- no SQL or rows
- `clarification_message`
- `clarification_options`

### Stream events from `POST /api/v1/query/stream`

SSE event payloads currently use these shapes:

```json
{"type": "stage", "stage": "understanding", "label": "Understanding your question...", "progress": 20}
```

```json
{"type": "result", "data": {"turn_type": "query"}}
```

```json
{"type": "error", "message": "Something went wrong. Please try again.", "code": 500}
```

## Sessions API

Primary session endpoints:

- `POST /api/v1/sessions`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `GET /api/v1/sessions/{session_id}/messages`
- `DELETE /api/v1/sessions/{session_id}`

The Angular chat UI creates a session up front and then reuses that session ID for every streamed query.

## Health and readiness

Operational endpoints:

- `GET /api/v1/health` returns `{ "status": "ok" }`
- `GET /api/v1/ready` checks database connectivity and returns `ready` or `not_ready`
- `GET /api/v1/embeddings/status` reports background embedding task status per connection

## Frontend-facing query shape

The Angular chat client expects a subset of the query response under `QueryResult`:

- `generated_sql`
- `final_sql`
- `columns`
- `column_types`
- `rows`
- `row_count`
- `execution_time_ms`
- `truncated`
- `summary`
- `highlights`
- `suggested_followups`
- `clarification_message`
- `clarification_options`
- `turn_type`
- `retry_count`

That client renders the rows as a client-side searchable, sortable, paginated table.

```json
{
  "name": "string",
  "db_type": "postgresql | bigquery | databricks | sqlserver",
  "connection_string": "string (plaintext — encrypted at rest)"
}
```

**Note:** Connection strings are encrypted with Fernet before storage. The key is derived from `ENCRYPTION_KEY` env var using SHA-256.

---

### Schema

| Method | Path | Description |
|---|---|---|
| `POST` | `/schemas/{connection_id}/introspect` | Trigger schema introspection |
| `GET` | `/schemas/{connection_id}/tables` | List cached tables |
| `GET` | `/schemas/{connection_id}/tables/{table_id}/columns` | List columns for a table |

---

### Glossary

| Method | Path | Description |
|---|---|---|
| `GET` | `/glossary` | List all terms (optionally filter by `connection_id`) |
| `POST` | `/glossary` | Create a term |
| `PUT` | `/glossary/{id}` | Update a term |
| `DELETE` | `/glossary/{id}` | Delete a term |

#### Glossary Term Object

```json
{
  "id": "UUID",
  "connection_id": "UUID",
  "term": "string",
  "definition": "string",
  "related_tables": ["table1", "table2"]
}
```

---

### Metrics

| Method | Path | Description |
|---|---|---|
| `GET` | `/metrics` | List all metrics |
| `POST` | `/metrics` | Create a metric |
| `PUT` | `/metrics/{id}` | Update a metric |
| `DELETE` | `/metrics/{id}` | Delete a metric |

#### Metric Object

```json
{
  "id": "UUID",
  "connection_id": "UUID",
  "metric_name": "string",
  "description": "string",
  "sql_expression": "string"
}
```

---

### Dictionary

| Method | Path | Description |
|---|---|---|
| `GET` | `/dictionary` | List entries (filter by `connection_id`, `table`, `column`) |
| `POST` | `/dictionary` | Create an entry |
| `PUT` | `/dictionary/{id}` | Update an entry |
| `DELETE` | `/dictionary/{id}` | Delete an entry |

---

### Knowledge

| Method | Path | Description |
|---|---|---|
| `GET` | `/knowledge` | List knowledge documents |
| `POST` | `/knowledge` | Import a document (text, HTML, or URL) |
| `DELETE` | `/knowledge/{id}` | Delete a document and its chunks |

#### Knowledge Import Request

```json
{
  "connection_id": "UUID",
  "title": "string",
  "content": "string | null",
  "source_url": "string | null"
}
```

If `source_url` is provided and `content` is null, the backend fetches the URL server-side via `httpx`.

---

### Query History

| Method | Path | Description |
|---|---|---|
| `GET` | `/query-history` | List query execution records (filter by `connection_id`, `session_id`) |
| `GET` | `/query-history/{id}` | Get a single execution record |

---

### Embeddings

| Method | Path | Description |
|---|---|---|
| `GET` | `/embeddings/status` | Get background embedding job progress |

#### Embedding Status Response

```json
{
  "total": 100,
  "completed": 72,
  "in_progress": true,
  "percent": 72.0
}
```

---

### Sample Queries

| Method | Path | Description |
|---|---|---|
| `GET` | `/sample-queries` | List sample queries |
| `POST` | `/sample-queries` | Create a sample query |
| `PUT` | `/sample-queries/{id}` | Update a sample query |
| `DELETE` | `/sample-queries/{id}` | Delete a sample query |

---

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check — returns `{"status": "ok"}` |

---

## Error Shape

All API errors normalize to:

```json
{
  "error": "human-readable error message"
}
```

HTTP status codes follow standard conventions (400 for validation, 404 for not found, 500 for server errors). Defined in `backend/app/core/exceptions.py` and `backend/app/core/exception_handlers.py`.

---

## Frontend TypeScript Types

**Location:** `frontend/src/types/`

TypeScript interfaces mirror the backend Pydantic schemas. Key interfaces:

| Interface | Mirrors |
|---|---|
| `QueryRequest` | `QueryRequest` |
| `QueryResponse` | `QueryResponse` |
| `Session` | `ChatSession` |
| `Message` | `QueryExecution` (message view) |
| `Connection` | `DatabaseConnection` |
| `GlossaryTerm` | `GlossaryTerm` |
| `MetricDefinition` | `MetricDefinition` |
| `DictionaryEntry` | `DictionaryEntry` |
| `KnowledgeDocument` | `KnowledgeDocument` |
| `SampleQuery` | `SampleQuery` |

All API calls go through Axios clients in `frontend/src/api/` (one file per resource). Data fetching uses React Query hooks in `frontend/src/hooks/`.
