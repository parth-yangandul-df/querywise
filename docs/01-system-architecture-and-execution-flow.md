# System Architecture and Execution Flow

## Overview

QueryWise currently uses a graph-based, multi-turn backend. The live request path is driven by `backend/app/llm/graph/graph.py`, not the older intent-template flow described in earlier drafts.

## Runtime topology

```text
React admin UI :5173
Angular chat UI :4200
        |
        v
FastAPI backend :8000
        |
        +-- QueryWise metadata DB (PostgreSQL + pgvector)
        +-- Target PostgreSQL / SQL Server databases
        +-- LLM providers: Anthropic, OpenAI, Ollama, OpenRouter, Groq
```

## Request entry points

Main query endpoints:

- `POST /api/v1/query`
- `POST /api/v1/query/stream`
- `POST /api/v1/query/sql-only`
- `POST /api/v1/query/execute-sql`

`execute_nl_query()` in `backend/app/services/query_service.py` builds the initial `GraphState`, injects auth scope, history defaults, and optional SSE event streaming, then invokes the compiled graph.

## Live graph topology

```text
load_history
  -> resolve_turn
     -> build_context            when action=query
     -> handle_follow_up         when action=follow_up_query_refinement
     -> answer_from_state        when action=show_sql or explain_result
     -> write_history            when action=clarification

build_context
  -> similarity_check
     -> execute_sql             when sample-query shortcut is valid
     -> compose_sql             otherwise

compose_sql
  -> validate_sql
  -> write_history              when composer returns clarification-style failure

validate_sql
  -> execute_sql
  -> handle_error

handle_error
  -> validate_sql
  -> execute_sql
  -> write_history              after retry exhaustion

execute_sql
  -> interpret_result
  -> handle_error               on execution failure

interpret_result
  -> write_history

answer_from_state
  -> write_history
```

## Turn resolution

`resolve_turn` decides between:

- `query`
- `follow_up_query_refinement`
- `show_sql`
- `explain_result`
- `clarification`

When `USE_FOLLOW_UP_PATH=true`, follow-up turns can take one of three refinement modes:

- `reuse_answer`
- `rewrite_sql`
- `needs_full_compose`

The graph uses persisted `last_query_context` from history to drive that decision.

## Semantic query path

The standard query path is:

1. `load_history` loads recent turns and cached context from `query_executions`
2. `resolve_turn` rewrites the user message into a standalone or follow-up-aware request
3. `build_context_node` calls `semantic/context_builder.py`
4. `similarity_check` optionally reuses validated sample-query SQL when similarity is high and no scope constraints are active
5. `compose_sql` asks the composer LLM for SQL
6. `validate_sql` statically validates schema and safety
7. `execute_sql` runs against the selected connector
8. `interpret_result` creates summary text and follow-up suggestions
9. `write_history` persists the execution record and compact turn context

## Follow-up refinement path

The follow-up path is deliberately smaller than a full recomposition:

- `reuse_answer` returns the cached prior answer without hitting the database again
- `rewrite_sql` routes directly into validation and execution using the refined question
- `needs_full_compose` falls back to the standard semantic query path

This is controlled by `resolve_turn` and persisted through `turn_context` in `query_executions`.

## Semantic context assembly

`build_context()` currently assembles context in this order:

1. Embed the question
2. Find relevant tables with hybrid semantic and keyword search
3. Resolve glossary terms
4. Inject glossary-linked tables
5. Resolve metrics
6. Retrieve knowledge chunks
7. Retrieve similar sample queries
8. Apply inferred relationships
9. Expand foreign-key neighbours, now keyword-scored against the question
10. Load dictionary entries and declared relationships
11. Assemble the final prompt block

RBAC scope constraints are prepended here when `resource_id` or `employee_id` is set.

## Result handling

`query_service.execute_nl_query()` returns a raw dict. Important fields are:

- `turn_type`
- `result_status`
- `generated_sql`
- `final_sql`
- `columns`
- `column_types`
- `rows`
- `summary`
- `suggested_followups`

Empty results are first-class: the interpreter returns `No matching rows found.` and the service marks the response as `result_status = "empty"`.

## Streaming flow

`POST /api/v1/query/stream` emits SSE events of these shapes:

- `stage`
- `token`
- `result`
- `error`

The Angular chat UI uses these events to drive progress indicators and then renders the final query result.
