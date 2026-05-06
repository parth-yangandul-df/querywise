# System Architecture & Execution Flow

## Overview

QueryWise is a natural-language-to-SQL system with a semantic metadata layer. Users ask questions in plain English; the system classifies the intent, builds database context from a semantic layer, generates SQL (via templates or an LLM), executes it against the target database, and returns a human-readable answer.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Docker Compose                       │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   frontend   │  │  angular-    │  │     backend      │  │
│  │  :5173       │  │  test        │  │     :8000        │  │
│  │  (admin UI)  │  │  :4200       │  │   (FastAPI)      │  │
│  └──────────────┘  └──────────────┘  └────────┬─────────┘  │
│                                               │             │
│                         ┌─────────────────────┘             │
│                         ▼                                   │
│              ┌──────────────────────┐                       │
│              │       app-db         │                       │
│              │  PostgreSQL 16       │                       │
│              │  + pgvector          │                       │
│              │  (querywise)         │                       │
│              └──────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘

External:
  Target DBs   → PostgreSQL, BigQuery, Databricks, SQL Server
  LLM APIs     → Anthropic, OpenAI, Ollama, OpenRouter, Groq
```

**Service ports:**

| Service | Port | Purpose |
|---|---|---|
| `backend` | 8000 | FastAPI REST API |
| `frontend` | 5173 | Admin/management UI (connections, glossary, metrics, etc.) |
| `angular-test` | 4200 | End-user chat interface |
| `app-db` | 5432 (internal) | QueryWise metadata DB (pgvector) |

---

## Startup Sequence

Defined in `backend/app/main.py` lifespan hook:

1. **`ensure_embedding_dimensions()`** — reads vector column dimensions from `app-db`; if they don't match `EMBEDDING_DIMENSION`, resizes all vector columns and nulls stale embeddings so they regenerate. Handles LLM provider switches (e.g., OpenAI 1536 → Ollama 768).
2. **`auto_setup_sample_db()`** — if `AUTO_SETUP_SAMPLE_DB=true`: creates the IFRS 9 sample DB connection, introspects the schema, seeds glossary terms (10), metrics (8), dictionary entries (43 across 12 columns), and one knowledge document. Then launches background embedding generation (non-blocking). Idempotent — safe on restart.
3. **FastAPI app starts** on port 8000.

---

## Request Execution Flow

### Entry Point

`POST /api/v1/query` → `backend/app/api/v1/endpoints/query.py` → `QueryService.process_query()`

`QueryService` (`backend/app/services/query_service.py`) manages the session/history lookup and delegates to the **LangGraph pipeline**.

---

### LangGraph Pipeline

Defined in `backend/app/llm/graph/graph.py`. The pipeline is a `StateGraph` over `GraphState` (`backend/app/llm/graph/state.py`).

#### Full Graph Topology

```
START
  │
  ▼
classify_intent
  │
  ├─ confidence >= 0.65 ──► extract_filters ──► update_query_plan ──► run_domain_tool
  │                                                  │
  │                                          rows > 0 ──► interpret_result
  │                                                  │
  │                                   0 rows + fallback_intent ──► run_fallback_intent
  │                                                                        │
  │                                                               rows > 0 ──► interpret_result
  │                                                                        │
  │                                                               0 rows ──► llm_fallback
  │
  └─ confidence < 0.65 ──► llm_fallback
                                │
                                ▼
                          interpret_result
                                │
                                ▼
                          write_history
                                │
                                ▼
                              END
```

#### Graph Nodes

| Node | File | Responsibility |
|---|---|---|
| `classify_intent` | `nodes/intent_classifier.py` | Embeds question, cosine-similarity against 24 intent descriptions, picks best match |
| `extract_filters` | `nodes/filter_extractor.py` | Extracts structured filter clauses from question using LLM + regex patterns |
| `update_query_plan` | `nodes/plan_updater.py` | Builds QueryPlan from domain, intent, filters; resolves schema references |
| `run_domain_tool` | `nodes/` (inline in graph) | Looks up agent from `DomainAgentRegistry`, calls `agent.run(intent, params)` |
| `run_fallback_intent` | `nodes/fallback_intent.py` | Re-runs domain tool with next-best intent when primary returned 0 rows |
| `llm_fallback` | `nodes/llm_fallback.py` | Full LLM path: build semantic context → compose SQL → validate → execute → retry on error |
| `interpret_result` | `nodes/result_interpreter.py` | Calls `ResultInterpreterAgent` to turn raw rows into a natural-language answer |
| `write_history` | `nodes/history_writer.py` | Persists `QueryExecution` record to `app-db`; sets session title on first turn |

---

### Intent Classification Path (SQL Template Path)

1. **`classify_intent`**: The question is embedded using the configured embedding provider. Cosine similarity is computed against pre-embedded descriptions of all 24 intents across 5 domains in `intent_catalog.py`. If best-match similarity ≥ `TOOL_CONFIDENCE_THRESHOLD` (default `0.65`), the intent name and score are written to state.

2. **`extract_filters`**: Extracts structured filter clauses (date ranges, text matches, numeric comparisons) from the question using an LLM prompt and regex post-processing. Writes `filters` list to state.

3. **`update_query_plan`**: Builds a `QueryPlan` object from the domain, intent, and extracted filters. Resolves any schema references needed for SQL compilation. Writes `query_plan` to state.

4. **`run_domain_tool`**: The `DomainAgentRegistry` maps the intent name to its owning agent class. The agent's `run(intent, params, db_session, connection)` method is called. All domain agents extend `BaseDomainAgent` and use hardcoded SQL templates with parameter substitution. Result rows are written to state.

5. **`run_fallback_intent`** (conditional): If `run_domain_tool` returned 0 rows and the state has a `fallback_intent`, the next-best intent is tried. If that also returns 0 rows, the pipeline falls through to `llm_fallback`.

---

### LLM Fallback Path

Triggered when intent confidence < 0.65 or all domain tool attempts return 0 rows.

1. **`build_context()`** (`semantic/context_builder.py`): 11-step semantic context assembly (see Semantic Layer section below).
2. **`QueryComposerAgent.compose()`** (`llm/agents/query_composer.py`): Calls the LLM with the assembled context + conversation history to generate a SQL query.
3. **`SQLValidatorAgent.validate()`** (`llm/agents/sql_validator.py`): Validates the generated SQL for correctness and safety.
4. **Connector execution**: The validated SQL is executed against the target database via the registered connector.
5. **`ErrorHandlerAgent`** (`llm/agents/error_handler.py`): If execution fails, the error + original SQL are sent back to the LLM for a corrected query. Retried up to **3 times**.

---

### Semantic Context Builder (11 Steps)

`backend/app/semantic/context_builder.py` → `build_context(question, connection_id, session)`

| Step | Action |
|---|---|
| 1 | Embed the question |
| 2 | Find relevant tables (hybrid: embedding similarity + keyword + column keyword + anchor table + FK expansion) |
| 3 | Resolve glossary terms referenced in the question |
| 4 | Inject any tables referenced by resolved glossary terms that weren't already found |
| 5 | Resolve metric definitions matching the question |
| 6 | Resolve knowledge chunks (RAG: vector + keyword search) |
| 7 | Find similar sample queries from `sample_queries` table |
| 8 | Apply inferred relationship rules (4 hardcoded PRMS join rules) |
| 9 | FK-neighbour expansion (adds up to 5 extra tables reachable via foreign keys) |
| 10 | Fetch dictionary entries and declared relationships for selected tables |
| 11 | Assemble final prompt string via `prompt_assembler.py` |

---

## Connector Execution Layer

All target-DB access goes through connectors (`backend/app/connectors/`). Every connector extends `BaseConnector` (ABC) and is registered in `connector_registry.py`.

- **PostgreSQL**: Always registered. Uses `asyncpg`.
- **BigQuery**: Lazy-registered if `google-cloud-bigquery` is installed.
- **Databricks**: Lazy-registered if `databricks-sql-connector` is installed.
- **SQL Server**: Lazy-registered if `aioodbc` is installed.

All connectors enforce **read-only** transactions. SQL is also pre-checked by `check_sql_safety()` in `backend/app/utils/sql_sanitizer.py` before any connector receives it.

---

## Background Embedding Generation

Embeddings are generated asynchronously to avoid blocking API responses:

- **On startup**: after auto-setup seeds data, `launch_background_embeddings()` fires a background asyncio task.
- **On schema introspect**: background task launched after schema introspection completes.
- **On CRUD**: glossary term, metric, sample query, and knowledge document create/update embed inline.

Progress is tracked in-memory by `embedding_progress.py`, exposed at `GET /api/v1/embeddings/status`. The frontend polls this every 2 seconds and shows a progress banner that auto-hides on completion.

---

## Data Flow Summary

```
User question
    │
    ▼
POST /api/v1/query
    │
    ▼
QueryService.process_query()
    │  (load session, load history, resolve connection)
    ▼
LangGraph pipeline (graph.py)
    │
    ├─ [Template path] classify → extract → domain agent SQL → rows
    │
    └─ [LLM path] semantic context → LLM compose → validate → execute → retry
    │
    ▼
ResultInterpreterAgent  →  natural-language answer
    │
    ▼
write_history  →  QueryExecution persisted to app-db
    │
    ▼
Response: { answer, sql, rows, execution_time, ... }
```
