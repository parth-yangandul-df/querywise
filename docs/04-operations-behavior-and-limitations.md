# Operations, Behavior & Limitations

## Overview

This document covers how to run, configure, and operate QueryWise — including environment variables, known behavioral constraints, edge cases, error handling patterns, and system limitations derived from the codebase.

---

## Running the Stack

### Docker (preferred)

```bash
docker compose up
```

| Service | URL |
|---|---|
| Frontend (admin) | http://localhost:5173 |
| Angular Chat | http://localhost:4200 |
| Backend API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |

The IFRS 9 sample database is auto-configured on first startup (see Auto-Setup below).

### Backend Only

```bash
# from backend/
pip install -e ".[llm,dev,bigquery,databricks]"
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend Only

```bash
# from frontend/
npm install
npm run dev

# from angular-test/
npm install
npm run start
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://querywise:querywise_dev@localhost:5432/querywise` | App metadata DB (pgvector) |
| `ENCRYPTION_KEY` | `dev-encryption-key-change-in-production` | Fernet key for encrypting connection strings. SHA-256 derived. **Change in production.** |
| `DEFAULT_LLM_PROVIDER` | `anthropic` | LLM provider: `anthropic`, `openai`, `ollama`, `openrouter`, `groq` |
| `DEFAULT_LLM_MODEL` | `claude-sonnet-4-20250514` | Default model for SQL generation and all LLM agent calls |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model (used when provider is `openai`, `anthropic`, `openrouter`, `groq`) |
| `EMBEDDING_DIMENSION` | `1536` | Vector dimension. Must match the embedding model: OpenAI=1536, Ollama nomic-embed-text=768 |
| `CORS_ORIGINS` | `["http://localhost:5173", "http://localhost:5175", "http://localhost:4200"]` | Allowed CORS origins |
| `AUTO_SETUP_SAMPLE_DB` | `true` | Auto-create + seed IFRS 9 sample DB on startup |
| `SAMPLE_DB_CONNECTION_STRING` | `postgresql://sample:sample_dev@sample-db:5432/sampledb` | Sample DB used by auto-setup |
| `ANTHROPIC_API_KEY` | — | Required if `DEFAULT_LLM_PROVIDER=anthropic` |
| `OPENAI_API_KEY` | — | Required if `DEFAULT_LLM_PROVIDER=openai`, or when any non-Ollama provider needs embeddings |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama server URL. Use `http://ollama:11434` for Docker-in-Docker Ollama. |
| `OLLAMA_MODEL` | `llama3.1:8b` | Ollama model for completions |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | Ollama model for embeddings (only when using Ollama for embeddings) |
| `TOOL_CONFIDENCE_THRESHOLD` | `0.65` | Cosine similarity cutoff for intent classification. Below this → LLM fallback path. |

---

## Auto-Setup Behavior

Controlled by `AUTO_SETUP_SAMPLE_DB` (default `true`). Logic in `backend/app/services/setup_service.py`, called from `main.py` lifespan.

**What it does:**
1. Creates a `database_connections` record for the IFRS 9 sample DB (connection string from `SAMPLE_DB_CONNECTION_STRING`).
2. Introspects the sample DB schema (6 tables: `counterparties`, `facilities`, `exposures`, `ecl_provisions`, `collateral`, `staging_history`).
3. Seeds metadata:
   - 10 glossary terms
   - 8 metric definitions
   - 43 dictionary entries across 12 columns
   - 1 knowledge document
4. Launches background embedding generation (non-blocking).

**Idempotency:** Auto-setup checks whether the sample connection already exists before creating it. Safe to restart the stack without duplicating data.

**To disable:** Set `AUTO_SETUP_SAMPLE_DB=false` in `.env`, then seed manually:
```bash
python backend/scripts/seed_ifrs9_metadata.py
```

---

## Embedding Dimension Management

On every startup, `ensure_embedding_dimensions()` (`setup_service.py`) runs before anything else:

1. Reads the current `EMBEDDING_DIMENSION` env var.
2. Checks the actual `atttypmod` of all `VECTOR(n)` columns in `app-db`.
3. If there's a mismatch (e.g., switching from OpenAI 1536 to Ollama 768):
   - Runs `ALTER COLUMN` to resize all vector columns.
   - Nulls all existing embedding values so they regenerate.
4. Background embedding generation re-embeds everything after startup.

**Implication:** Switching embedding providers causes all embeddings to be invalidated and regenerated. During regeneration, the system degrades to keyword-only search (see Graceful Degradation below).

---

## Ollama Deployment

### Option A: Native Ollama (macOS — recommended, GPU via Metal)

```bash
brew install ollama
ollama serve
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

Set `.env`:
```
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1:8b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768
```

Then: `docker compose up`

### Option B: Ollama in Docker (CPU-only)

```
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
EMBEDDING_DIMENSION=768
```

```bash
docker compose --profile ollama-docker up
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

Option A is ~5–10x faster on macOS because Docker on Mac runs inside a Linux VM with no GPU passthrough.

---

## Background Embedding Jobs

Embedding generation is always non-blocking. Triggers:

| Trigger | Behavior |
|---|---|
| Startup (after auto-setup) | `launch_background_embeddings()` runs all un-embedded entities |
| Schema introspection | Background task launched after introspection completes |
| Glossary/Metric/SampleQuery create or update | Embeds inline during the request |
| Knowledge document import | Embeds all chunks inline during the import request |

**Progress API:** `GET /api/v1/embeddings/status` — returns `{total, completed, in_progress, percent}`. In-memory only (resets on restart). Frontend polls every 2 seconds and shows a progress banner that auto-hides when complete.

---

## Conversation History

- History is passed as `list[dict]` with `role` (`user` or `assistant`) and `content` fields.
- **Maximum 6 turns** enforced at the Pydantic schema level on `QueryRequest`.
- History is injected into `QueryComposerAgent.compose()` to enable follow-up questions.
- History is **not** used in the intent classification or parameter extraction steps — only in the LLM fallback path for SQL generation.
- History is stored in `query_executions` (one row per turn) and retrieved via `GET /sessions/{id}/messages`.

---

## SQL Safety Enforcement

All SQL passes through `check_sql_safety()` (`backend/app/utils/sql_sanitizer.py`) before any connector executes it. This applies to both the LLM-generated SQL and raw SQL from `POST /query/execute-sql`.

Blocked patterns:
- DDL: `CREATE`, `DROP`, `ALTER`, `TRUNCATE`
- DML: `INSERT`, `UPDATE`, `DELETE`, `MERGE`
- Admin: `GRANT`, `REVOKE`, `EXEC`, `EXECUTE`, `CALL`
- Multiple statements via `;`
- Dangerous functions: `pg_sleep`, `xp_cmdshell`, `OPENROWSET`, `BULK INSERT`
- BigQuery-specific: `EXPORT DATA`, `LOAD DATA`
- Databricks-specific: `COPY INTO`, `OPTIMIZE`, `VACUUM`

All connectors also enforce read-only transactions at the connection level.

---

## Error Handling Patterns

### API Error Shape

All errors return:
```json
{"error": "human-readable message"}
```

Defined in `backend/app/core/exceptions.py` and registered in `backend/app/core/exception_handlers.py`.

### LLM Error Retry

`ErrorHandlerAgent` retries failed SQL up to **3 times** in the LLM fallback path. After 3 failures, the error is surfaced to the caller in the `error` field of `QueryResponse`.

### History Write Failure

Errors in `write_history` (e.g., DB unavailable) are **swallowed** — logged but not surfaced to the caller. The query response is returned even if history persistence failed.

### Interpretation Failure

Errors in `interpret_result` (e.g., LLM timeout) are **swallowed** — logged, and `answer` is returned as `null`. Rows and SQL are still returned.

### Vector Search Failure

If the embedding model is unavailable during semantic context building (`schema_linker.py`):
- The DB session is rolled back.
- The system falls back to **keyword-only** table matching.
- No error is raised to the caller.
- Logged at WARNING level.

---

## Graceful Degradation

| Failure Mode | Behavior |
|---|---|
| Embedding model unavailable | Keyword-only context matching; vector search disabled until model is available |
| All domain agents return 0 rows | Falls through to LLM fallback path automatically |
| LLM generates invalid SQL | `ErrorHandlerAgent` retries up to 3 times with the error message as context |
| History write fails | Swallowed; query still returns successfully |
| Interpretation fails | `answer` is null; rows and SQL still returned |
| Auto-setup fails | Logged; backend still starts; manual seeding required |

---

## Known Behavioral Constraints

### Intent System

- **`client_revenue` intent is partially broken**: the intent exists in `intent_catalog.py` and will be matched by the classifier, but the handler in `client.py` is commented out. Queries matching this intent route to `llm_fallback` instead of a domain agent.
- **Intent embeddings must be pre-computed**: the intent classifier embeds intent descriptions at graph compile time (or on first call). If the embedding provider is unavailable at startup, intent classification will fail for all queries until the provider is restored.
- **Threshold is global**: `TOOL_CONFIDENCE_THRESHOLD` applies to all 24 intents uniformly. There is no per-intent threshold tuning.

### SQL Template Path

- **Parameter injection uses Python string formatting** (f-strings / `.format()`), not parameterized DB queries. SQL injection through domain agents is not mitigated by the sanitizer for the template path — only by the `check_sql_safety()` blocklist.
- **Domain agents assume specific table/column names** hardcoded in templates (PRMS schema). They are not adapted for the IFRS 9 sample DB or other schemas.

### Semantic Layer

- **4 hardcoded relationship rules** in `relationship_inference.py` are PRMS-specific (Client→Status, Project→Status, Project→Client, Resource self-join). They are injected for all connections, including non-PRMS ones, which may produce incorrect JOIN suggestions.
- **FK-neighbour expansion** adds up to 5 extra tables. For highly connected schemas this may bloat the context window.
- **Table selection is capped**: the number of tables sent to the LLM is bounded to avoid exceeding model context limits, but the exact cap is configurable via schema linker parameters.

### Conversation History

- **Max 6 turns** is enforced at the API schema level. Clients sending more than 6 history items will receive a validation error.
- **History is only used in the LLM path** — domain agent (template) path queries do not use conversation history for SQL generation.

### Connection String Encryption

- The `ENCRYPTION_KEY` default (`dev-encryption-key-change-in-production`) is insecure. In production, this must be replaced with a strong random key. Changing the key after connections are stored **will break all stored connection strings** (they cannot be decrypted with the new key).

### Embedding Dimension Switching

- Switching embedding providers (e.g., OpenAI → Ollama) triggers a full vector column resize and nulls all embeddings. During background re-embedding, the system operates in degraded (keyword-only) mode. Re-embedding time depends on the number of entities and the speed of the new provider.

### Database Pool

- SQLAlchemy async pool: `pool_size=10`, `max_overflow=20`. Under sustained high concurrency (>30 simultaneous queries), pool exhaustion is possible.

### SQL Server

- Only the `dbo` schema is introspected.
- Tables matching `ts_*`, `*backup*`, `*bakup*` are auto-excluded from introspection.
- `LIMIT` clauses in generated SQL are automatically rewritten to `TOP N` by the connector. If the LLM generates non-standard SQL Server syntax, the rewrite may not cover all cases.

### BigQuery

- Introspection uses `INFORMATION_SCHEMA`. Very large BigQuery projects with thousands of tables may cause slow introspection.

### Databricks

- Supports Unity Catalog (`INFORMATION_SCHEMA`) and Hive metastore (`SHOW`/`DESCRIBE` fallback). Unity Catalog is preferred if available.

---

## Migrations

Managed by Alembic.

```bash
# from backend/
alembic upgrade head    # Apply all migrations
alembic revision --autogenerate -m "description"  # Generate new migration
```

Migration `002_configurable_embedding_dim` handles initial configurable vector column creation. Runtime dimension changes are handled by `ensure_embedding_dimensions()` at startup (not via Alembic).

---

## Development Commands

### Backend (`backend/`)

```bash
pytest                   # Run tests (asyncio_mode=auto, test paths at tests/)
ruff check .             # Lint (rules: E, F, I, N, UP, B; 100-char line length)
ruff format .            # Format
mypy .                   # Type check (strict)
```

### Frontend (`frontend/` and `angular-test/`)

```bash
npm run build            # Production build (tsc + vite)
npm run lint             # ESLint (strict, no explicit any)
```
