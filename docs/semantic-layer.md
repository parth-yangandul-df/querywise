# QueryWise Semantic Layer

## Purpose

The semantic layer gives the SQL composer structured business context instead of forcing the model to infer everything from raw table names.

## Semantic assets

QueryWise currently uses five semantic asset types:

- glossary terms
- metric definitions
- dictionary entries
- knowledge documents and chunks
- validated sample queries

All of them are scoped to a connection and stored in the metadata database.

## What the semantic layer contributes

At query time it provides:

- relevant tables and columns
- business vocabulary
- reusable metric formulas
- human-readable value mappings from dictionaries
- domain knowledge excerpts from imported documents
- validated SQL examples from similar sample queries

## Current context-building flow

`backend/app/semantic/context_builder.py` builds context in this order:

1. embed the question
2. find relevant tables through hybrid semantic and keyword scoring
3. resolve glossary terms
4. inject glossary-linked tables that were not already selected
5. resolve metric definitions
6. retrieve relevant knowledge chunks
7. retrieve similar sample queries
8. apply inferred relationships
9. expand foreign-key neighbours using question-aware keyword scoring
10. fetch dictionary entries and relationships for the selected tables
11. assemble a final prompt block

## Retrieval behavior

### Table selection

Table selection is hybrid. It combines:

- embedding similarity
- keyword matching on table and column names
- inferred relationships
- foreign-key neighbourhood expansion

The recent change here is that FK neighbour expansion is no longer blindly positional. Candidate neighbours are now scored against extracted question keywords before the top entries are added.

### Glossary and metrics

Glossary and metric resolution support business-language queries such as:

- internal terms that do not match raw schema names
- named KPIs that should map to stable SQL expressions
- organization-specific labels that the model would otherwise guess incorrectly

### Knowledge documents

Knowledge documents are chunked on import and searched semantically at query time. They are useful for policy explanations, business logic, and domain-specific caveats that are not encoded directly in schema objects.

### Sample queries

Validated sample queries do double duty:

- few-shot examples during composition
- direct similarity shortcut in `similarity_check` when a close enough validated SQL match exists

## RBAC interaction

The semantic layer is also where scope constraints are injected for limited users. If `resource_id` or `employee_id` is present in graph state, the prompt context is prefixed with a non-negotiable scope block.

That is why similarity shortcuts are skipped for scoped users: reusing stored SQL without reapplying scope would be unsafe.

## Failure behavior

When semantic vector search is unavailable, QueryWise does not stop entirely. It degrades toward keyword-driven retrieval where supported and continues the query path with reduced semantic quality instead of failing immediately.

Provider defaults:

- OpenAI `text-embedding-3-small` at 1536 dimensions
- Ollama `nomic-embed-text` at 768 dimensions for local operation

Dimension mismatches on provider switch are handled automatically at startup by invalidating stale embeddings and regenerating them later.
User question ────────────────► Context Builder ──► Assembled context
                                            │
                                            ▼
                                     SQL Composer (LLM)
                                            │
                                     SQL Validator
                                            │
                                    DB Execution
                                            │
                                   Interpreter (LLM)
                                            │
                                            ▼
                               SQL + results + plain-English summary
                                  + suggested follow-up questions
```

---

## 11. Key Design Decisions

**No business logic in application code.** All domain knowledge — formulas, filters, term definitions, value mappings — lives in the metadata store. Adding a new KPI or correcting a term definition requires no code changes, only a metadata update.

**Hybrid retrieval, not pure vector search.** Keyword matching handles exact term references reliably. Vector search handles paraphrases and synonyms. FK expansion ensures JOIN paths are never broken. All three signals combine into a single ranked score.

**Graceful degradation.** If the embedding model is unavailable, the system falls back to keyword-only retrieval. Queries continue to work; accuracy degrades rather than failing entirely.

**Idempotent setup.** The sample database auto-setup runs on every container start and skips any metadata that already exists. Restarting the stack is always safe.

**Audit trail.** Every query execution — question, generated SQL, final SQL, row count, execution time, LLM provider and model, retry count, and the plain-English summary — is persisted to `query_executions`. Nothing is ephemeral.
