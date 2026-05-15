# Operations, Behavior, and Limitations

## Running the stack

Preferred full-stack command:

```bash
docker compose up
```

Core URLs:

| Service | URL |
|---|---|
| React admin UI | http://localhost:5173 |
| Angular chat UI | http://localhost:4200 |
| Backend API | http://localhost:8000 |
| OpenAPI | http://localhost:8000/docs |
| Health | http://localhost:8000/api/v1/health |
| Ready | http://localhost:8000/api/v1/ready |

## Important settings

Selected runtime settings from `backend/app/config.py`:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://querywise:querywise_dev@localhost:5432/querywise` | Metadata database |
| `DEFAULT_LLM_PROVIDER` | `anthropic` | Active provider family |
| `DEFAULT_LLM_MODEL` | `claude-sonnet-4-20250514` | Default generation model |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `EMBEDDING_DIMENSION` | `1536` | Vector size for semantic retrieval |
| `MAX_QUERY_TIMEOUT_SECONDS` behavior | connection-specific | Default query timeout is stored per connection |
| `MAX_RETRY_ATTEMPTS` | `3` | Correction retries for failed SQL |
| `MAX_CONTEXT_TABLES` | `8` | Upper bound on table context |
| `MAX_SAMPLE_QUERIES` | `3` | Sample-query few-shot cap |
| `AUTO_SETUP_SAMPLE_DB` | `false` | Optional startup seeding |
| `USE_FOLLOW_UP_PATH` | `false` | Enables compact follow-up refinement path |

## Startup behavior

At application startup the backend can:

1. validate or resize embedding dimensions for vector columns
2. optionally auto-seed the sample environment when `AUTO_SETUP_SAMPLE_DB=true`
3. expose health, readiness, embedding progress, and metrics endpoints

Embedding dimension changes are handled at runtime. When the configured vector size changes, stale embeddings are nulled and regenerated later.

## Health and observability

Available endpoints:

- `GET /api/v1/health`
- `GET /api/v1/ready`
- `GET /api/v1/embeddings/status`
- `GET /metrics`

`/metrics` is open in development and guarded in non-development environments.

## Background embeddings

Embeddings can be generated:

- on startup
- after schema introspection
- during glossary, metric, sample-query, and knowledge mutations

The progress endpoint returns task state per connection, including total items, completed items, and errors.

## Query behavior and safeguards

### SQL safety

All SQL flows through `app/utils/sql_sanitizer.py` before execution. The system blocks dangerous DDL, DML, admin commands, multi-statement payloads, and known unsafe function patterns.

### Retry behavior

If generated SQL fails validation or execution, `handle_error` can retry through the correction path up to the configured retry limit.

### Follow-up behavior

When follow-up refinement is enabled:

- prior turn context is read from persisted history
- the system may reuse a prior answer directly
- the system may refine SQL instead of rebuilding the whole semantic context
- the system may still fall back to full composition if the follow-up is too ambiguous

### Empty results

Zero-row results are not treated as silent failures. The interpreter returns `No matching rows found.` and the service marks the result as `empty`.

## Degraded modes

| Failure | Current behavior |
|---|---|
| Embedding search unavailable | fall back to keyword-oriented retrieval where supported |
| History write failure | query response still returns; persistence failure is logged |
| Interpreter failure | rows and SQL can still return even if summary generation fails |
| Sample-query shortcut unavailable | graph falls through to normal composition |
| Follow-up cache missing | query may clarify or fall back to full compose |

## Current operational constraints

- Similarity shortcuts are skipped when RBAC scope constraints are active
- SQL Server support depends on an installed ODBC driver and connector extras
- Follow-up refinement is disabled unless the feature flag is enabled
- Query history is the source of conversational state; clients do not send raw history lists
- Changing `ENCRYPTION_KEY` after storing connections will invalidate existing encrypted connection strings

## Useful commands

Backend:

```bash
cd backend
alembic upgrade head
pytest
ruff check .
ruff format .
mypy .
```

Frontends:

```bash
cd frontend
npm run dev
npm run build

cd angular-test
npm run start
npm run build
```
