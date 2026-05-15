# QueryWise QA Testing Guide

## Purpose

This is the current manual QA source for the live codebase. Use it instead of older intent-bank markdown files.

## Environment smoke check

Before deeper testing, verify:

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/ready
curl http://localhost:8000/api/v1/embeddings/status
```

Expected:

- health returns `ok`
- ready returns `ready`
- embeddings status returns task data or an empty task list

## Core QA scenarios

### 1. Connection lifecycle

Verify:

- create a PostgreSQL connection
- create a SQL Server connection when the local environment supports it
- test the connection
- introspect schema successfully
- delete the connection cleanly

### 2. Semantic metadata lifecycle

Verify CRUD for:

- glossary terms
- metrics
- sample queries
- knowledge documents
- dictionary entries

Also verify that embedding work is scheduled or refreshed after these changes.

### 3. Fresh query path

Ask a first-turn query and verify:

- `turn_type = query`
- SQL is present in `generated_sql` or `final_sql`
- rows render in the UI
- summary text is present for non-empty results
- query history records the execution

### 4. Empty result behavior

Ask a query that should return zero rows and verify:

- response completes without a hard error
- `result_status = empty` in the backend payload
- summary says `No matching rows found.`
- suggested follow-ups still render

### 5. Clarification path

Ask an ambiguous question and verify:

- `turn_type = clarification`
- `clarification_message` is shown
- clarification options render as chips in the Angular UI
- no SQL or row payload is returned

### 6. Show SQL and explain-result path

After a successful query:

1. ask `Show SQL`
2. ask `Explain this result`

Verify the backend answers from stored state without rerunning a fresh data query.

### 7. Follow-up refinement path

Enable `USE_FOLLOW_UP_PATH=true` and test:

1. run a query returning multiple rows
2. ask a refinement such as `only show the top 5`
3. ask a reuse-style prompt such as `summarize that again`

Verify that:

- refinement works against prior query context
- reuse-style prompts can answer without a fresh context rebuild when appropriate
- fallback to full compose still works when refinement is insufficient

### 8. Streaming UI behavior

In the Angular chat UI, verify:

- stage progress updates appear while the query is running
- the final result arrives as a single assistant message
- errors render as error bubbles rather than breaking the session

### 9. Result table behavior

In the Angular chat UI, verify for any multi-row result:

- search filters the visible rows
- header click cycles sort state
- pagination updates correctly
- rows-per-page selector works
- CSV export downloads a file

### 10. RBAC and scoped querying

For a scoped user account, verify:

- access is limited to permitted data slices
- similarity shortcut is skipped when scope constraints are active
- follow-up questions do not escape user scope

## Regression checklist

Use this short checklist on every release candidate:

- [ ] login and logout work
- [ ] connection create, test, introspect, delete work
- [ ] one successful query returns rows and summary
- [ ] one empty-result query returns `No matching rows found.`
- [ ] clarification chips render for an ambiguous query
- [ ] `Show SQL` works after a successful query
- [ ] streamed progress appears in the Angular chat UI
- [ ] result table search, sort, pagination, and CSV export work
- [ ] query history captures the run

## Canonicality

If a legacy markdown test bank conflicts with this guide, treat this file as correct and update or remove the older file.

---

## 12. Useful Commands

```bash
# Check service health
curl http://localhost:8000/api/v1/health

# View backend logs
docker compose logs -f backend

# Check PostgreSQL
docker compose logs app-db

# Restart services
docker compose restart

# View embedding status
curl http://localhost:8000/api/v1/embeddings/status
```