# Table Context Pruning

> Reduces irrelevant lookup/dimension tables in the LLM context prompt by enriching table embeddings and tightening column-keyword scoring.

## Problem

The LLM context prompt was flooded with irrelevant lookup/dimension tables (TechCategory, CompanyType, TechFunction, BusinessUnit) even for simple questions like "show me projects and their resources". This caused:

- ~8-table context cap consumed by garbage tables
- Useful tables (Project, Resource, ProjectResource) pruned by the cap
- SQL validation errors when the LLM hallucinated missing tables

## Root Cause

Two compounding issues:

### 1. Table embeddings had zero discriminative power
`embed_table()` generated text as just `"dbo.Project"`. With no table descriptions in the DB, every table embedding was practically indistinguishable to the vector search — only table name signal, no column-context signal.

### 2. Column-keyword scores outranked table-name scores
`column_keyword_score()` returned **0.8** when a keyword like "project" matched a generic FK column (`ProjectId`) on any lookup table. This beat the actual `Project` table's `keyword_match_score` of **0.5** (substring match). A lookup table like `CompanyType` (with `ProjectId` FK column) scored higher than `Project` itself:

| Table | Score source | Score | Weight 30% | Final contribution |
|---|---|---|---|---|
| `CompanyType` | column "ProjectId" matches "project" | 0.8 | 0.3 | 0.24 |
| `Project` | table name substring "project" | 0.5 | 0.3 | 0.15 |

With weak embedding scores (due to problem 1), the keyword score dominated, and garbage tables consistently won the top-8 cap.

## Changes

### Change 1: `backend/app/services/embedding_service.py`

**`embed_table()` signature** — accepts optional `columns` parameter:

```python
async def embed_table(table: CachedTable, columns: list[CachedColumn] | None = None) -> list[float]:
```

**Embedding text** — includes all column names, types, and PK flag:

```
# Before
dbo.Project

# After
dbo.Project: [ProjectId(int PK), ProjectName(varchar), ClientId(int), StartDate(datetime), EndDate(datetime), ... , IsActive(bit)]
```

Columns include ALL columns (audit columns included) — no filtering.

**`generate_embeddings_for_connection()`** — loop reordered so ALL columns are loaded before table embedding:

```
Before:  embed_table(table) → load only unembedded columns → embed columns
After:   load all columns → embed_table(table, all_columns) → embed only unembedded columns
```

Same single-pass generation. Same background trigger (fires after introspection). No re-runs. New format takes effect automatically on next introspection (which deletes and recreates all CachedTable rows).

### Change 2: `backend/app/semantic/relevance_scorer.py`

**`column_keyword_score()`** — reduced return values:

| Match type | Before | After |
|---|---|---|
| Exact column name match | 0.8 | **0.5** |
| Column component match | 0.5 | **0.5** |
| Substring match | 0.4 | **0.25** |

Column-only matches can no longer outrank direct table-name matches (`keyword_match_score` returns 1.0 for exact match, 0.5 for substring). A table hit only via a generic FK column gets 0.5 × 30% weight = 0.15 final, while the actual table gets 1.0 × 30% = 0.30 from keyword alone — plus a strong embedding score from the enriched text.

## Files Modified

| File | Lines changed | Description |
|---|---|---|
| `app/services/embedding_service.py:122-133` | Full rewrite of `embed_table()` | Accept columns parameter, build `[col(type), ...]` text |
| `app/services/embedding_service.py:245-272` | Reordered loop body | Load all columns before calling embed_table |
| `app/semantic/relevance_scorer.py:207-233` | Reduced return values | 0.8→0.5, 0.4→0.25 in column_keyword_score |

## Rollback Instructions

To revert to original state, apply the inverse diffs or restore from git:

```bash
git checkout HEAD~1 -- backend/app/services/embedding_service.py
git checkout HEAD~1 -- backend/app/semantic/relevance_scorer.py
```

Or restore specific hunks:

### Revert Change 1 — `embedding_service.py`

1. Restore `embed_table()` to original:
   ```python
   async def embed_table(table: CachedTable) -> list[float]:
       """Generate an embedding for a table's description."""
       text = f"{table.schema_name}.{table.table_name}"
       if table.comment:
           text += f": {table.comment}"
       return await embed_text(text)
   ```

2. Restore `generate_embeddings_for_connection()` table loop to original — load only unembedded columns, call `embed_table(table)` without columns argument, then embed unembedded columns.

### Revert Change 2 — `relevance_scorer.py`

1. Restore `column_keyword_score()` return values to original:
   - Exact match: `return 0.8`
   - Component match: `best = max(best, 0.8)`  
   - Substring match: `best = max(best, 0.4)`

## Verification

After next introspection, test:
- "show me projects and their resources" → context should contain only: Project, Resource, ProjectResource (± FK neighbours that have explicit keyword match)
- "list all clients" → context should contain: Client, not TechCategory or BusinessUnit
- "what skills are available" → context should contain: PA_Skills, PA_ResourceSkills, not CompanyType

### Monitoring

Watch logs for schema_linker selected tables output — it logs selected tables with scores:
```
schema_linker: selected tables [('Project', 0.723, 'embedding'), ('Resource', 0.701, 'embedding'), ...]
```

Compare before/after — embedding scores should be significantly higher and better differentiated.
