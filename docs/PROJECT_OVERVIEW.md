# QueryWise — Project Overview

## 1. What Is QueryWise?

**QueryWise** is a full-stack, enterprise-grade **text-to-SQL (NL2SQL)** application with a **semantic metadata layer**. Users type natural language questions like `Show me active resources from the last 30 days` or `How many of these are in SQL Server?`, and the system:

1. **Understands the question** (intent classification, context resolution)
2. **Finds relevant database context** (tables, columns, glossary, metrics, knowledge documents, sample queries)
3. **Generates or reuses SQL** (via LLM composition, sample-query similarity shortcuts, or follow-up rewriting)
4. **Validates and executes** the SQL against the connected target database (PostgreSQL or SQL Server)
5. **Returns a formatted result** (markdown table, row count, or single value) and writes the turn to query history

### Architecture Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy (async), asyncpg, pgvector, Alembic, LangGraph |
| **Frontend (Admin)** | React 19, TypeScript, Vite, Mantine UI — port `5173` |
| **Frontend (Chat)** | Angular 21 — port `4200` |
| **Metadata DB** | PostgreSQL 16 with pgvector (stores connections, schema cache, query history, glossary, metrics, embeddings) |
| **Target DBs** | PostgreSQL (`asyncpg`) or SQL Server (`aioodbc`) via connector plugins |
| **LLM Orchestration** | LangGraph stateful graph with model routing per role |
| **LLM Providers** | Anthropic, OpenAI, Ollama (local), OpenRouter, Groq |
| **Cache & Coalescing** | Redis (SQL result cache, request coalescing, embedding L2 cache, schema cache) |
| **Observability** | Prometheus metrics, structured JSONL logs, LangSmith tracing |

---

## 2. The LangGraph Pipeline — Every Node Explained

The core of QueryWise is a **compiled LangGraph StateGraph** (`app/llm/graph/graph.py`) that threads a single `GraphState` dictionary through 11 nodes. The graph is compiled once at startup and reused for every query.

### Graph Topology

```text
load_history
    |
resolve_turn  ──┬──> build_context ──> similarity_check ──┬──> execute_sql ──> write_history ──> END
                |                                         |
                |                                         └──> compose_sql ──> validate_sql ──┬──> execute_sql
                |                                                                              |
                |                                                                              └──> handle_error ──(retry loop max 3)──> validate_sql
                |
                ├──> handle_follow_up ──┬──> execute_sql ──> write_history ──> END
                |                       |
                |                       └──> write_history (reuse_answer / clarification)
                |
                ├──> answer_from_state ──> write_history ──> END
                |
                └──> write_history (clarification) ──> END
```

---

### Node 1: `load_history`

**File:** `app/llm/graph/nodes/load_history.py`

**What it does:**
- Loads the last **6 turns** of conversation history from `QueryExecution` records in the metadata DB
- Compacts history into `{role, content}` messages (last user message, assistant summary, etc.)
- Extracts the **last successful query context** (`last_query_context`): `resolved_question`, `sql`, `answer`, `columns`, `preview_rows`, `status`
- Populates `last_generated_sql`, `last_result_columns`, `last_result_preview_rows` in state

**Why it matters:**
This is the memory of the conversation. Without it, follow-up questions like `How many of these?` have no anchor. The bug we fixed: `result_summary` was empty in old DB records, so `loaded_history` had no assistant messages, causing the resolver LLM to miss follow-up intent.

---

### Node 2: `resolve_turn`

**File:** `app/llm/graph/nodes/resolve_turn.py`

**What it does:**
- **First turn optimization:** If `loaded_history` is empty, skips the LLM entirely and returns `action="query"` instantly
- **LLM call:** Otherwise, calls a **fast/cheap resolver model** (default: `openai/gpt-4.1-nano`) with a compact prompt containing recent history + last query context
- **Classifies intent** into one of:
  - `query` — fresh data request
  - `follow_up_query_refinement` — user is refining a previous query
  - `show_sql` — user wants to see the SQL
  - `explain_result` — user wants an explanation of prior results
  - `clarification` — the LLM is unsure (confidence < 0.75)
- **Rewrites the question** into a fully standalone form (e.g., `How many of these?` → `How many active resources from the last 30 days?`)
- **Heuristic override:** After the confidence check, if the question contains follow-up signals (`"these"`, `"how many"`, `"count of"`, `"filter by"`, etc.) AND there is a `last_query_context`, forces `action="follow_up_query_refinement"` with `follow_up_mode="rewrite_sql"`

**Key fix applied:** The heuristic override was originally placed **before** the confidence check. A low-confidence LLM response (e.g., `confidence=0.6`) would be downgraded to `clarification` even when the heuristic detected a clear follow-up. We moved the heuristic **after** the confidence check so clear follow-ups always win.

---

### Node 3: `route_after_resolve`

**File:** `app/llm/graph/nodes/resolve_turn.py` (routing function)

**Routes based on `action`:**

| Action | Route Target |
|--------|-------------|
| `query` | `build_context` |
| `follow_up_query_refinement` | `handle_follow_up` |
| `show_sql` | `answer_from_state` |
| `explain_result` | `answer_from_state` |
| `clarification` | `write_history` |

---

### Node 4: `handle_follow_up`

**File:** `app/llm/graph/nodes/handle_follow_up.py`

**What it does:**
Processes follow-up query refinements with three modes:

1. **`reuse_answer`** — The user is asking for the same data again (e.g., `Can you repeat that?`). Returns the cached `answer` directly without touching the database.
2. **`rewrite_sql`** — The user is refining the previous query (e.g., `How many of these?`, `Sort by date`, `Show only active ones`). Generates new SQL using:
   - A **minimal prompt** (~500 tokens vs 10,000+ for full composition)
   - The **fast resolver model** (`gpt-4.1-nano`, ~1-2s vs 40-45s for deepseek)
   - The original SQL + the follow-up question as input
   - The model is instructed to keep the same FROM/JOIN tables and only modify WHERE, ORDER BY, or aggregates
3. **`needs_full_compose`** — The follow-up is too complex for a minimal rewrite (e.g., `Now join it with the sales table`). Escalates back to `build_context` → full pipeline.

**Key fix applied:** The `_rewrite_sql` function previously existed but never actually generated SQL (empty output). We implemented the full minimal-prompt rewrite with JSON parsing. Additionally, `rewrite_sql` now routes **directly to `execute_sql`**, skipping `validate_sql`, because:
- The rewriter inherits structural validity from the original SQL
- The database is the ultimate validator — execution errors are caught and routed to `handle_error`
- `validate_sql` needs `schema_tables` from `build_context`, which was skipped in the follow-up path

---

### Node 5: `route_after_follow_up`

| Action | Route Target |
|--------|-------------|
| `follow_up_rewrite_sql` | `execute_sql` (skip validation) |
| `reuse_answer` | `write_history` |
| `clarification` | `write_history` |

---

### Node 6: `build_context`

**File:** `app/semantic/context_builder.py`

**What it does:**
This is the **heaviest node** in the pipeline. It builds the full prompt context for SQL generation by:

1. **Embedding the question** — generates a vector embedding (with in-memory L1 cache + Redis L2 cache, TTL 5 min)
2. **Schema linking** — finds relevant tables via:
   - **Vector search** (cosine similarity on table/column description embeddings)
   - **Keyword search** (ILIKE on table/column names)
   - **Anchor table forcing** — if the question contains a table name, that table is always included
3. **Semantic resolution** (parallel DB queries, each with its own `AsyncSession`):
   - `resolve_glossary` — business term definitions + related tables
   - `resolve_metrics` — pre-defined metric formulas
   - `resolve_knowledge` — relevant knowledge document chunks
   - `find_similar_queries` — validated sample queries via vector similarity
4. **Glossary table injection** — if a glossary term references a table not yet in context, fetch it
5. **Inference relationship expansion** — inferred FK-like relationships from heuristics
6. **FK neighbour expansion** — pull in dimension/lookup tables connected via foreign keys, scored by keyword relevance
7. **Dictionary resolution** — get human-readable descriptions for all columns in context
8. **Relationship resolution** — get actual FK relationships between all context tables
9. **Prompt assembly** — assemble everything into a single prompt string for the composer

**Performance characteristics:**
- 10-20 DB round trips for a 30-table schema
- Parallelized where safe via `asyncio.gather`
- Each parallel query gets its own `AsyncSession` (SQLAlchemy sessions are not concurrency-safe)

**Planned improvement:** Redis-backed schema cache (`app/services/schema_cache.py`) to reduce DB round trips from 10-20 to 1-2 for subsequent queries.

---

### Node 7: `similarity_check`

**File:** `app/llm/graph/nodes/similarity_check.py`

**What it does:**
- Compares the question embedding against stored `sample_queries` embeddings
- If cosine similarity ≥ **0.92**, the stored SQL is considered a match
- The stored SQL has already been **validated and executed successfully** in the past
- If shortcut hits: skip `compose_sql` entirely, route directly to `execute_sql`

**Why it matters:**
This is the **fastest path** in the entire pipeline — no LLM call at all. For common questions like `Show active resources`, the system can go from question to results in ~2-3 seconds (embedding cache + similarity hit + DB execution).

---

### Node 8: `route_after_similarity`

| Condition | Route Target |
|-----------|-------------|
| `similarity_shortcut == True` | `execute_sql` (skip LLM) |
| Otherwise | `compose_sql` |

---

### Node 9: `compose_sql`

**File:** `app/llm/graph/nodes/compose_sql.py`

**What it does:**
- Calls the **QueryComposerAgent** with the resolved question + full prompt context
- Model routed by complexity: simple queries → fast model (nano), complex queries → heavy model (deepseek/deepseek-v4-flash)
- The agent generates SQL + explanation + confidence score
- If the model emits `SCOPE_VIOLATION` or returns no SQL, routes to `write_history` as a clarification

**Performance characteristics:**
- Fast model (nano): ~2-5s
- Heavy model (deepseek): ~40-60s
- This is the **bottleneck** for first-turn complex queries

---

### Node 10: `route_after_compose`

| Condition | Route Target |
|-----------|-------------|
| SQL generated successfully | `validate_sql` |
| Scope violation / no SQL | `write_history` (clarification) |

---

### Node 11: `validate_sql`

**File:** `app/llm/graph/nodes/validate_sql.py`

**What it does:**
- **Static validation** against `schema_tables` (tables and columns from `build_context`):
  - Checks all referenced tables exist
  - Checks all referenced columns exist in those tables
  - Checks for ambiguous column names (same column name in multiple tables without table prefix)
- Does **NOT** execute the SQL — this is a semantic check, not a runtime check
- Returns `validation_issues` list; empty list = valid

**Limitation:**
Requires `schema_tables` from `build_context`. This is why follow-up rewrites skip validation — `build_context` was never called in the follow-up path, so `schema_tables` is empty.

---

### Node 12: `route_after_validate`

| Condition | Route Target |
|-----------|-------------|
| `validation_issues` empty | `execute_sql` |
| Issues found | `handle_error` |

---

### Node 13: `handle_error`

**File:** `app/llm/graph/nodes/handle_error.py`

**What it does:**
- Called when SQL validation fails OR SQL execution fails
- Calls the **ErrorHandlerAgent** (fast model) with:
  - The failed SQL
  - Validation issues or execution error message
  - Schema tables
  - Dialect
  - Attempt number
  - All previous attempts (dedup check)
- **Retry loop:** Routes back to `validate_sql` (validation errors) or `execute_sql` (execution errors)
- **Max 3 retries** (`_MAX_RETRIES = 3`)
- **Fast-fail dedup:** If the model returns the **identical SQL** as before, immediately exhausts retries instead of burning the budget
- On exhaustion: returns `clarification` with retry reason

---

### Node 14: `route_after_handle_error`

| Condition | Route Target |
|-----------|-------------|
| `action == "clarification"` | `write_history` |
| `_target_node == "execute_sql"` | `execute_sql` |
| `_target_node == "validate_sql"` | `validate_sql` |

---

### Node 15: `execute_sql`

**File:** `app/llm/graph/nodes/execute_sql.py`

**What it does:**
- Gets or creates the database connector (PostgreSQL or SQL Server) from the registry
- Runs the final SQL against the target database
- Applies `max_rows` limit and `timeout_seconds`
- Formats the result as a markdown table directly (no LLM interpretation step)
- On execution error: routes to `handle_error`

**Key change:** The `interpret_result` node was **removed** from the graph. Previously, after execution, an LLM interpreter would generate a natural language summary (`35 active resources found...`). This added 5-10s of latency. Now:
- Single-value results → show the value directly (`35`)
- Multi-row results → show row count (`42 row(s) returned`)
- The frontend already renders the data table; the backend doesn't need to narrate it

---

### Node 16: `route_after_execute`

| Condition | Route Target |
|-----------|-------------|
| Execution error | `handle_error` |
| Success | `write_history` |

---

### Node 17: `answer_from_state`

**File:** `app/llm/graph/nodes/answer_from_state.py`

**What it does:**
- For `show_sql`: returns `last_generated_sql` directly
- For `explain_result`: grounds the explanation in the stored result preview
- No DB execution needed
- If the required state is missing (e.g., `explain_result` with no prior result), downgrades to `clarification`

---

### Node 18: `write_history`

**File:** `app/llm/graph/nodes/history_writer.py`

**What it does:**
- Persists a `QueryExecution` record to the metadata DB
- Captures: `turn_type`, `natural_language`, `generated_sql`, `final_sql`, `execution_status`, `row_count`, `result_summary`, `result_columns`, `result_preview_rows`, `llm_provider`, `llm_model`, `retry_count`, `error_message`, `clarification_reason`
- This record becomes the **source of truth** for `load_history` on the next turn

---

## 3. API Endpoints

All routes are prefixed with `/api/v1`.

### Query Endpoints (`/api/v1/query`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/v1/query` | JWT | Submit a natural language question. Returns SQL + results + summary. |
| `POST` | `/api/v1/query/stream` | JWT | Same as above but streams SSE events: `stage`, `token`, `result`, `error`. |
| `POST` | `/api/v1/query/execute-sql` | JWT | Execute user-provided SQL directly (no LLM generation). |
| `POST` | `/api/v1/query/sql-only` | JWT | Generate SQL without executing it. |

### Connection Management (`/api/v1/connections`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/v1/connections` | JWT | List all database connections for the current user. |
| `POST` | `/api/v1/connections` | JWT | Create a new database connection. |
| `GET` | `/api/v1/connections/{id}` | JWT | Get a specific connection. |
| `PUT` | `/api/v1/connections/{id}` | JWT | Update a connection. |
| `DELETE` | `/api/v1/connections/{id}` | JWT | Delete a connection. |
| `POST` | `/api/v1/connections/{id}/introspect` | JWT | Trigger schema introspection and cache tables/columns/relationships. |
| `POST` | `/api/v1/connections/{id}/test` | JWT | Test the connection string. |

### Schema & Semantic Metadata (`/api/v1/schemas`, `/api/v1/glossary`, etc.)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/v1/schemas/{connection_id}/tables` | JWT | List cached tables for a connection. |
| `GET` | `/api/v1/schemas/{connection_id}/tables/{table_id}/columns` | JWT | List columns for a table. |
| `GET` | `/api/v1/schemas/{connection_id}/relationships` | JWT | List FK relationships. |
| `GET` | `/api/v1/glossary` | JWT | List glossary terms. |
| `POST` | `/api/v1/glossary` | JWT | Create a glossary term. |
| `GET` | `/api/v1/metrics` | JWT | List metric definitions. |
| `POST` | `/api/v1/metrics` | JWT | Create a metric. |
| `GET` | `/api/v1/dictionary` | JWT | List dictionary entries (column descriptions). |
| `POST` | `/api/v1/dictionary` | JWT | Create a dictionary entry. |
| `GET` | `/api/v1/sample-queries` | JWT | List validated sample queries. |
| `POST` | `/api/v1/sample-queries` | JWT | Create a sample query. |

### Knowledge Documents (`/api/v1/knowledge`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/v1/knowledge` | JWT | Upload/import a knowledge document (text or HTML). |
| `GET` | `/api/v1/knowledge` | JWT | List knowledge documents. |
| `GET` | `/api/v1/knowledge/{id}` | JWT | Get a specific document. |
| `DELETE` | `/api/v1/knowledge/{id}` | JWT | Delete a document. |

### Query History & Sessions (`/api/v1/query-history`, `/api/v1/sessions`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/v1/query-history` | JWT | List query execution history. |
| `GET` | `/api/v1/query-history/{id}` | JWT | Get a specific execution. |
| `GET` | `/api/v1/sessions` | JWT | List chat sessions. |
| `POST` | `/api/v1/sessions` | JWT | Create a new chat session. |
| `GET` | `/api/v1/sessions/{id}/messages` | JWT | Get messages for a session. |

### Admin & Health (`/api/v1/admin`, `/api/v1/health`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/v1/health` | None | Basic health check (FastAPI running). |
| `GET` | `/api/v1/ready` | None | Deep readiness: DB connectivity, Redis, LLM provider health. |
| `GET` | `/api/v1/admin/stats` | Admin | System statistics. |
| `GET` | `/api/v1/admin/users` | Admin | List all users. |

### Auth (`/api/v1/auth`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/v1/auth/register` | None | Register a new user. |
| `POST` | `/api/v1/auth/login` | None | Login and receive JWT. |
| `POST` | `/api/v1/auth/refresh` | JWT | Refresh access token. |
| `GET` | `/api/v1/auth/me` | JWT | Get current user profile. |

### Embeddings Status (`/api/v1/embeddings/status`)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/api/v1/embeddings/status` | JWT | Get background embedding generation progress. |

---

## 4. Issues We Are Facing — Detailed Analysis

### Issue 1: Pipeline Latency (Primary Concern)

**Problem:**
A full first-turn query takes **60-75 seconds**. A follow-up question was observed taking **63 seconds**.

**Root causes identified:**

| Bottleneck | Time | Explanation |
|------------|------|-------------|
| **DeepSeek composer model** | 40-60s | Heavy SQL generation via `deepseek/deepseek-v4-flash` through OpenRouter. This is the single longest step. |
| **`build_context` DB round trips** | 5-10s | 10-20 sequential+parallel DB queries to fetch schema, glossary, metrics, knowledge, sample queries, relationships. |
| **`interpret_result` LLM call** | 5-10s | Previously called after every execution to narrate results. Now removed. |
| **Cached pipeline interpreter** | 5-6s | Even cache-hit queries were calling `ResultInterpreterAgent`. Now removed. |
| **Pipeline timeout** | 120s | Too permissive — slow paths were not surfacing as errors. Reduced to 45s. |
| **Follow-up full pipeline** | 60s+ | Follow-ups were incorrectly routed through the entire `build_context` → `compose_sql` path instead of a fast rewrite. |

**Fixes applied:**
1. ✅ Removed `interpret_result` node from graph — results formatted directly
2. ✅ Removed LLM interpreter from cached and raw SQL paths
3. ✅ Implemented minimal-prompt `rewrite_sql` for follow-ups using fast model (~1-2s)
4. ✅ Follow-up rewrites skip `validate_sql` and route directly to `execute_sql`
5. ✅ Reduced pipeline timeout from 120s to 45s
6. 🔄 Redis schema cache module created, integration pending

**Expected latency after all fixes:**

| Scenario | Before | After |
|----------|--------|-------|
| First-turn simple query | ~15-20s | ~10-15s (nano composer) |
| First-turn complex query | ~60-75s | ~45-60s (deepseek compose) |
| Follow-up ("how many of these") | **63s** | **~8-12s** (nano rewriter) |
| Cached query | ~8-10s | **~2-3s** (no interpreter) |
| Similarity shortcut | ~5-8s | **~2-3s** (no LLM at all) |

---

### Issue 2: Intent Classification (Follow-Up Detection)

**Problem:**
The resolver LLM (fast model) was **missing follow-up intent** even when the user clearly used follow-up language (`"How many of these?"`). Logs showed `follow_up_node=false` despite `USE_FOLLOW_UP_PATH=true` in `.env`.

**Root causes:**
1. **Empty `loaded_history`** — old `QueryExecution` records had empty `result_summary`, so `load_history` produced no assistant messages. The resolver had no context that a previous query existed.
2. **Low confidence override** — the LLM returned `action="query"` with `confidence=0.6`. The heuristic override was placed **before** the confidence check, but the confidence check at the end would still downgrade it to `clarification`.

**Fixes applied:**
1. ✅ Added **regex heuristic override** with 12 follow-up signal patterns (`"these"`, `"how many"`, `"count of"`, `"filter by"`, `"sort by"`, etc.)
2. ✅ Moved heuristic **after** confidence check — a clear follow-up with pronoun references bypasses low confidence
3. ✅ The heuristic forces `follow_up_mode="rewrite_sql"` with a reason logged for observability

---

### Issue 3: Similarity Check — Sample Query Shortcuts

**Problem:**
The similarity check compares question embeddings against stored sample queries. It can **skip the entire LLM composition step** (saving 40-60s), but:
- The threshold is **0.92** — very high. Many semantically similar questions won't hit it.
- Sample queries must be **pre-validated and embedded** — if the admin hasn't seeded them, the shortcut never fires.
- There's no **fuzzy matching** on question text (exact embedding match only).

**Current behavior:**
- If similarity ≥ 0.92: route to `execute_sql` with stored SQL → **~2-3s total**
- If similarity < 0.92: route to `compose_sql` → **~45-60s total**

**Recommendation (not yet implemented):**
- Lower threshold to 0.85 for broader matching, with a quick SQL syntax validation before execution
- Add **keyword-based pre-filtering** before embedding comparison for common questions
- Auto-generate sample queries from successful query history

---

### Issue 4: Follow-Up Path (`USE_FOLLOW_UP_PATH`)

**Problem:**
Even with the feature flag enabled, follow-ups were burning through the **full pipeline** because:
1. The resolver LLM misclassified them as `query` (low confidence, missing history)
2. The `handle_follow_up` node existed but `_rewrite_sql` returned empty SQL
3. The routing sent empty SQL to `validate_sql` which had no `schema_tables`, causing silent failure

**How the follow-up path works now (after fixes):**

```
User: "Show me active resources"
  -> resolve_turn: action="query" -> build_context -> compose_sql -> execute_sql -> write_history
     (stores last_query_context with SQL, result, columns, preview)

User: "How many of these?"
  -> load_history: loads last_query_context
  -> resolve_turn: LLM returns action="query", confidence=0.6
     -> confidence check: would be clarification... BUT
     -> heuristic override: detects "how many" + last_query_context exists
     -> action="follow_up_query_refinement", follow_up_mode="rewrite_sql"
  -> route_after_resolve -> handle_follow_up
  -> _rewrite_sql:
     - Minimal prompt with original SQL + follow-up question
     - Calls fast model (gpt-4.1-nano) in ~1-2s
     - Returns rewritten SQL (e.g., SELECT COUNT(*) FROM ...)
  -> route_after_follow_up -> execute_sql
  -> Runs SQL against DB
  -> write_history
```

**Total follow-up time:** ~8-12s (vs 63s before)

---

### Issue 5: Build Context DB Round Trips

**Problem:**
`build_context` makes **10-20 DB round trips** per query:
1. Find relevant tables (vector + keyword)
2. Resolve glossary
3. Resolve metrics
4. Resolve knowledge
5. Find similar queries
6. Fetch glossary-referenced tables
7. Fetch inference-referenced tables
8. FK neighbour expansion
9. Resolve dictionary
10. Get relationships

Each step is a separate SQL query. For a 30-table schema, this is significant.

**Current mitigations:**
- `asyncio.gather` parallelizes independent queries (steps 2-5 run in parallel)
- Each parallel query gets its own `AsyncSession`
- In-memory embedding cache with 5-min TTL
- Redis L2 embedding cache with 24-hour TTL

**Planned fix:**
- **Redis schema cache** (`app/services/schema_cache.py` already built):
  - Cache the full schema (tables, columns, relationships, dictionary) for a connection_id
  - TTL: 5 minutes
  - Invalidated automatically after schema introspection
  - Reduces DB round trips from 10-20 to 1-2 for cached connections

---

### Issue 6: Model Routing & Cost

**Current routing strategy:**

| Role | Model | Cost | Speed | Use Case |
|------|-------|------|-------|----------|
| Resolver | `openai/gpt-4.1-nano` | Very low | ~1-2s | Intent classification, follow-up rewrite |
| Composer (simple) | `openai/gpt-4.1-nano` | Very low | ~2-5s | Simple SELECT queries |
| Composer (complex) | `deepseek/deepseek-v4-flash` | Low | ~40-60s | Complex joins, aggregations, CTEs |
| Interpreter | `meta-llama/llama-3.1-8b-instruct` | Very low | ~3-5s | **Removed from graph** |
| Error handler | `openai/gpt-4.1-nano` | Very low | ~1-2s | SQL correction retries |

**Problem:**
The complexity estimator (`app/llm/router.py`) may misclassify a complex query as simple, sending it to nano and producing bad SQL that needs retries.

**Recommendation (not yet implemented):**
- Add an **ensemble path**: for queries classified as "medium complexity", generate SQL with both nano and deepseek in parallel, then execute both and pick the one that returns valid results faster.
- This costs 2× LLM calls but improves accuracy for the ambiguous middle ground.

---

## 5. File Map for Key Components

| Component | File |
|-----------|------|
| Graph assembly | `backend/app/llm/graph/graph.py` |
| Graph state schema | `backend/app/llm/graph/state.py` |
| Resolve turn | `backend/app/llm/graph/nodes/resolve_turn.py` |
| Handle follow-up | `backend/app/llm/graph/nodes/handle_follow_up.py` |
| Build context | `backend/app/semantic/context_builder.py` |
| Compose SQL | `backend/app/llm/graph/nodes/compose_sql.py` |
| Validate SQL | `backend/app/llm/graph/nodes/validate_sql.py` |
| Handle error | `backend/app/llm/graph/nodes/handle_error.py` |
| Execute SQL | `backend/app/llm/graph/nodes/execute_sql.py` |
| Load history | `backend/app/llm/graph/nodes/load_history.py` |
| Write history | `backend/app/llm/graph/nodes/history_writer.py` |
| Answer from state | `backend/app/llm/graph/nodes/answer_from_state.py` |
| Query service (orchestrator) | `backend/app/services/query_service.py` |
| Schema cache (new) | `backend/app/services/schema_cache.py` |
| Config | `backend/app/config.py` |
| LLM router | `backend/app/llm/router.py` |
| API routes | `backend/app/api/v1/endpoints/query.py` |

---

*Last updated: May 9, 2026*
