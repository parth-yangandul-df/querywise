"""The Context Builder — orchestrates hybrid context selection.

This is the core intelligence of the product. It selects the minimal
relevant context for the LLM prompt, combining:
1. Embedding similarity search
2. Keyword matching
3. FK relationship expansion
4. Glossary/metric/dictionary resolution
5. Inferred relationship rules (for schemas with sparse enforced FKs)
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from app.core.mlflow_tracing import mlflow_span
from app.db.models.schema_cache import CachedRelationship, CachedTable
from app.semantic.glossary_resolver import (
    ResolvedDictionary,
    ResolvedGlossary,
    ResolvedKnowledge,
    ResolvedMetric,
    ResolvedSampleQuery,
    find_similar_queries,
    resolve_dictionary,
    resolve_glossary,
    resolve_knowledge,
    resolve_metrics,
)
from app.semantic.prompt_assembler import assemble_prompt
from app.semantic.relationship_inference import (
    InferredRelationship,
    get_inferred_relationships,
    get_referenced_tables,
)
from app.semantic.relevance_scorer import extract_keywords, keyword_match_score
from app.semantic.schema_linker import LinkedTable, find_relevant_tables, get_columns_for_tables
from app.services.embedding_service import embed_text

# In-memory embedding cache: question text → (embedding, timestamp)
# TTL = 5 minutes.  Saves recomputing embeddings for identical questions
# (common on retry / follow-up / cache refresh).
_EMBEDDING_CACHE: dict[str, tuple[list[float], float]] = {}
_EMBEDDING_CACHE_TTL_SECONDS = 300

# In-memory context cache: (connection_id, question, dialect) → (BuiltContext, timestamp)
# TTL = 5 minutes. Saves rebuilding context for identical repeated questions.
_CONTEXT_CACHE: dict[str, tuple[Any, float]] = {}
_CONTEXT_CACHE_TTL_SECONDS = 300
_CONTEXT_CACHE_MAX_SIZE = 128

# Per-key locks prevent redundant concurrent context/embedding builds.
# Without locks, N concurrent requests for the same question would all
# miss the cache and fan out to N parallel LLM+DB calls before any of
# them can populate the cache.
_CONTEXT_LOCKS: dict[str, asyncio.Lock] = {}
_EMBEDDING_LOCKS: dict[str, asyncio.Lock] = {}

logger = logging.getLogger(__name__)


@dataclass
class BuiltContext:
    """The assembled context ready for the LLM."""

    prompt_context: str  # Formatted text to include in the LLM prompt
    tables: list[LinkedTable]
    glossary: list[ResolvedGlossary]
    metrics: list[ResolvedMetric]
    knowledge: list[ResolvedKnowledge]
    dictionaries: list[ResolvedDictionary]
    sample_queries: list[ResolvedSampleQuery]
    question_embedding: list[float] | None
    inferred_relationships: list[InferredRelationship]


@mlflow_span("build_context", span_type="RETRIEVER", capture_output=False)
async def build_context(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question: str,
    dialect: str = "postgresql",
) -> BuiltContext:
    """Build the full context for an NL question.

    Steps:
    1. Embed the question
    2. Find relevant tables (hybrid: embedding + keyword + column keyword + anchor + FK expansion)
    3. Resolve glossary terms
    4. Inject tables referenced by glossary terms but not yet in context
    5. Resolve metrics
    6. Get knowledge chunks
    7. Find similar sample queries
    8. Apply inferred relationship rules — force-include missing lookup tables
    9. FK-neighbour expansion
    10. Get dictionary entries + declared relationships between selected tables
    11. Assemble everything into a structured prompt
    """
    # Check context cache first — identical (connection, question, dialect) skip
    # all schema linking and context assembly (~2s saved on repeat questions).
    context_cache_key = f"{connection_id}:{question.lower().strip()}:{dialect}"
    now = time.time()
    cached_context = _CONTEXT_CACHE.get(context_cache_key)
    if cached_context:
        context, ts = cached_context
        if now - ts < _CONTEXT_CACHE_TTL_SECONDS:
            logger.debug("Context cache hit for question: %r", question[:50])
            return context

    # Acquire a per-key lock so concurrent requests for the same question don't
    # each fan out to N parallel LLM+DB builds (thundering-herd). The actual
    # build runs inside the lock; a re-check at the top short-circuits if another
    # coroutine already populated the cache while we waited.
    if context_cache_key not in _CONTEXT_LOCKS:
        _CONTEXT_LOCKS[context_cache_key] = asyncio.Lock()

    return await _build_context_locked(
        context_cache_key, connection_id, question, dialect, db
    )


async def _build_context_locked(
    context_cache_key: str,
    connection_id: uuid.UUID,
    question: str,
    dialect: str,
    db: "AsyncSession",
) -> "BuiltContext":
    """Build context under a per-key lock to prevent concurrent duplicate builds."""
    async with _CONTEXT_LOCKS[context_cache_key]:
        # Re-check after acquiring lock — another coroutine may have built it already
        now = time.time()
        cached_context = _CONTEXT_CACHE.get(context_cache_key)
        if cached_context:
            context, ts = cached_context
            if now - ts < _CONTEXT_CACHE_TTL_SECONDS:
                logger.debug("Context cache hit (post-lock) for question: %r", question[:50])
                return context

        return await _do_build_context(context_cache_key, connection_id, question, dialect, db)


async def _do_build_context(
    context_cache_key: str,
    connection_id: uuid.UUID,
    question: str,
    dialect: str,
    db: "AsyncSession",
) -> "BuiltContext":
    """Execute the full context build pipeline — called while holding the cache lock."""
    # Step 1: Embed the question (gracefully degrade to keyword-only if unavailable)
    # Check in-memory cache first — identical questions reuse the embedding.
    question_embedding: list[float] | None = None
    cache_key = question.lower().strip()
    now = time.time()
    cached = _EMBEDDING_CACHE.get(cache_key)
    if cached:
        embedding, ts = cached
        if now - ts < _EMBEDDING_CACHE_TTL_SECONDS:
            question_embedding = embedding
            logger.debug("Embedding cache hit for question: %r", question[:50])

    # If not cached, generate with aggressive 3s timeout.
    # Keyword fallback is nearly as good as vector search for table-name matching.
    if question_embedding is None:
        if cache_key not in _EMBEDDING_LOCKS:
            _EMBEDDING_LOCKS[cache_key] = asyncio.Lock()
        async with _EMBEDDING_LOCKS[cache_key]:
            # Re-check after acquiring lock
            now = time.time()
            cached = _EMBEDDING_CACHE.get(cache_key)
            if cached:
                embedding, ts = cached
                if now - ts < _EMBEDDING_CACHE_TTL_SECONDS:
                    question_embedding = embedding
            if question_embedding is None:
                try:
                    question_embedding = await asyncio.wait_for(
                        asyncio.shield(embed_text(question)), timeout=3.0
                    )
                    _EMBEDDING_CACHE[cache_key] = (question_embedding, now)
                except TimeoutError:
                    logger.warning(
                        "Embedding generation timed out after 3s — using keyword-only context. "
                        "Consider switching to a faster embedding provider "
                        "(e.g. Ollama nomic-embed-text)."
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "Embedding generation failed — falling back to keyword-only context. "
                        "Ensure the embedding model is pulled (e.g. ollama pull nomic-embed-text).",
                        exc_info=True,
                    )

    # Step 2-7: Run independent DB queries in parallel using separate sessions.
    # SQLAlchemy AsyncSession is NOT thread-safe / concurrency-safe — each query
    # gets its own session to avoid session-state corruption.
    from app.db.session import async_session_factory

    async def _with_new_session(coro, *args):
        async with async_session_factory() as new_db:
            return await coro(new_db, *args)

    (
        tables,
        glossary,
        metrics,
        knowledge,
        sample_queries,
    ) = await asyncio.gather(
        _with_new_session(find_relevant_tables, connection_id, question_embedding, question),
        _with_new_session(resolve_glossary, connection_id, question, question_embedding),
        _with_new_session(resolve_metrics, connection_id, question, question_embedding),
        _with_new_session(resolve_knowledge, connection_id, question, question_embedding),
        _with_new_session(find_similar_queries, connection_id, question_embedding),
    )

    # Step 4: Inject tables referenced by matched glossary terms but not yet in context.
    table_names_in_context = {lt.table.table_name for lt in tables}
    glossary_tables_needed: list[str] = []
    for g in glossary:
        for ref_table in g.related_tables:
            if ref_table not in table_names_in_context:
                glossary_tables_needed.append(ref_table)

    # Steps 8-9 (inference fetch + FK expansion): launch in parallel once
    # glossary tables are known. Both depend only on the initial table set.
    extra_tables_from_glossary: list[LinkedTable] = []
    if glossary_tables_needed:
        logger.info(
            "context_builder: glossary references missing tables %s — fetching",
            glossary_tables_needed,
        )
        extra_tables_from_glossary = await _with_new_session(
            _fetch_tables_by_names, connection_id, glossary_tables_needed
        )
        for lt in extra_tables_from_glossary:
            tables.append(lt)
            table_names_in_context.add(lt.table.table_name)

    inferred_relationships = get_inferred_relationships(
        list(table_names_in_context), question=question
    )
    missing_from_inference = get_referenced_tables(list(table_names_in_context), question=question)

    # Fetch inference-referenced tables and run FK expansion in parallel
    inference_extra: list[LinkedTable] = []
    if missing_from_inference:
        logger.info(
            "context_builder: inferred rules reference missing tables %s — fetching",
            missing_from_inference,
        )
        inference_extra = await _with_new_session(
            _fetch_tables_by_names, connection_id, missing_from_inference
        )
        for lt in inference_extra:
            tables.append(lt)
            table_names_in_context.add(lt.table.table_name)
        inferred_relationships = get_inferred_relationships(
            list(table_names_in_context), question=question
        )

    tables, table_ids, column_ids = await _finalize_tables_and_columns(
        db, connection_id, tables, table_names_in_context, question
    )

    # Inject tables referenced in sample queries but missed by FK expansion /
    # keyword scoring.  FK expansion skips neighbours with keyword score <= 0.0
    # (e.g. 'Project' scores 0.0 against "benched resources"), but the LLM sees
    # the sample SQL and hallucinates those tables.  Force-include them here.
    if sample_queries:
        sample_missing_set: set[str] = set()
        for sq in sample_queries:
            if not sq.sql_query:
                continue
            try:
                parsed = sqlglot.parse_one(sq.sql_query, read="tsql")
                for table in parsed.find_all(exp.Table):
                    name = table.name
                    if name.lower() not in table_names_in_context:
                        sample_missing_set.add(name)
            except Exception:
                pass
        if sample_missing_set:
            sample_missing = list(sample_missing_set)
            logger.info(
                "context_builder: sample queries reference missing tables %s — injecting",
                sample_missing,
            )
            extra = await _with_new_session(
                _fetch_tables_by_names, connection_id, sample_missing
            )
            for lt in extra:
                tables.append(lt)
                table_names_in_context.add(lt.table.table_name)
            # Recompute IDs so dictionary/relationship resolution covers them
            table_ids = [lt.table.id for lt in tables]
            column_ids = [col.id for lt in tables for col in lt.columns]

    logger.info(
        "context_builder: using %d tables in context",
        len(tables),
    )

    # Step 10: Get dictionary entries + relationships between the final table set.
    # Must be sequential — AsyncSession is NOT safe for concurrent use.
    dictionaries = await resolve_dictionary(db, column_ids)
    relationships = await _get_relationships_between(db, table_ids)

    # Step 11: Assemble prompt
    prompt_context = assemble_prompt(
        tables=tables,
        glossary=glossary,
        metrics=metrics,
        knowledge=knowledge,
        dictionaries=dictionaries,
        sample_queries=sample_queries,
        relationships=relationships,
        inferred_relationships=inferred_relationships,
        dialect=dialect,
    )

    # Enforce LRU eviction before storing new entry
    if len(_CONTEXT_CACHE) >= _CONTEXT_CACHE_MAX_SIZE:
        oldest_key = min(_CONTEXT_CACHE, key=lambda k: _CONTEXT_CACHE[k][1])
        _CONTEXT_CACHE.pop(oldest_key)

    built = BuiltContext(
        prompt_context=prompt_context,
        tables=tables,
        glossary=glossary,
        metrics=metrics,
        knowledge=knowledge,
        dictionaries=dictionaries,
        sample_queries=sample_queries,
        question_embedding=question_embedding,
        inferred_relationships=inferred_relationships,
    )
    _CONTEXT_CACHE[context_cache_key] = (built, now)
    return built


async def _fetch_tables_by_names(
    db: AsyncSession,
    connection_id: uuid.UUID,
    table_names: list[str],
) -> list[LinkedTable]:
    """Fetch CachedTable + columns for a list of table names and return as LinkedTable.

    Used to inject glossary-referenced or inference-referenced tables into context.
    Table name matching is case-insensitive.
    """
    if not table_names:
        return []

    conditions = [CachedTable.table_name.ilike(name) for name in table_names]
    result = await db.execute(
        select(CachedTable).where(
            CachedTable.connection_id == connection_id,
            or_(*conditions),
        )
    )
    cached_tables = result.scalars().all()

    table_ids = [tbl.id for tbl in cached_tables]
    columns_by_table = await get_columns_for_tables(db, table_ids)

    return [
        LinkedTable(
            table=tbl,
            columns=columns_by_table.get(tbl.id, []),
            score=0.05,
            match_reason="injected",
        )
        for tbl in cached_tables
    ]


async def _get_relationships_between(
    db: AsyncSession,
    table_ids: list[uuid.UUID],
) -> list[dict]:
    """Get all FK relationships between the given tables."""
    if len(table_ids) < 2:
        return []

    result = await db.execute(
        select(CachedRelationship).where(
            CachedRelationship.source_table_id.in_(table_ids),
            CachedRelationship.target_table_id.in_(table_ids),
        )
    )

    relationships = []
    # Batch-load all table names in a single query (fixes N+1: was 2 db.get() per rel)
    all_ids: set[uuid.UUID] = set()
    rel_rows: list[tuple[uuid.UUID, str, uuid.UUID, str]] = []
    for rel in result.scalars().all():
        all_ids.add(rel.source_table_id)
        all_ids.add(rel.target_table_id)
        rel_rows.append(
            (rel.source_table_id, rel.source_column, rel.target_table_id, rel.target_column)
        )

    if not rel_rows:
        return []

    tables_result = await db.execute(select(CachedTable).where(CachedTable.id.in_(list(all_ids))))
    tables_by_id = {t.id: t for t in tables_result.scalars().all()}

    for source_id, source_col, target_id, target_col in rel_rows:
        source = tables_by_id.get(source_id)
        target = tables_by_id.get(target_id)
        if source and target:
            relationships.append(
                {
                    "source_table": source.table_name,
                    "source_column": source_col,
                    "target_table": target.table_name,
                    "target_column": target_col,
                }
            )

    return relationships


async def _finalize_tables_and_columns(
    db: AsyncSession,
    connection_id: uuid.UUID,
    tables: list[LinkedTable],
    table_names_in_context: set[str],
    question: str,
) -> tuple[list[LinkedTable], list[uuid.UUID], list[uuid.UUID]]:
    """Run FK-neighbour expansion + collect final table/column IDs.

    Step 9 (FK expansion) runs in parallel with Step 4/8 table additions.
    """
    # FK-neighbour expansion: pull in lookup/dimension tables via FK
    tables = await _expand_fk_neighbours(db, connection_id, tables, question=question, max_extra=5)

    # Re-scan for any tables added via FK expansion that also need glossary injection
    for lt in tables:
        if lt.table.table_name not in table_names_in_context:
            table_names_in_context.add(lt.table.table_name)

    # Final IDs for dictionary + relationship resolution
    table_ids = [lt.table.id for lt in tables]
    column_ids = [col.id for lt in tables for col in lt.columns]

    return tables, table_ids, column_ids


async def _expand_fk_neighbours(
    db: AsyncSession,
    connection_id: uuid.UUID,
    tables: list[LinkedTable],
    question: str = "",
    max_extra: int = 5,
) -> list[LinkedTable]:
    """Expand context by pulling in FK-neighbour tables not yet selected.

    For every table already in `tables`, find ALL FK relationships where it is
    either the source or the target.  Score each neighbour by keyword relevance
    against the user's question, sort descending, take top-N.

    Only neighbours with score > 0.0 are added — tables with no keyword overlap
    with the question are excluded to prevent context bloat.  This ensures
    lookup/dimension tables (e.g. BusinessUnit, Designation) are present so the
    LLM can read exact column names — but only when actually relevant.

    Args:
        db: Async SQLAlchemy session.
        connection_id: The connection whose schema is being queried.
        tables: The tables already selected by find_relevant_tables.
        question: The user's original question (used for keyword scoring).
        max_extra: Cap on how many extra tables to add (prevents context explosion).

    Returns:
        Augmented list of LinkedTable (original tables + scored FK neighbours).
    """
    if not tables:
        return tables

    keywords = extract_keywords(question)
    selected_ids = {lt.table.id for lt in tables}

    rel_result = await db.execute(
        select(CachedRelationship).where(
            CachedRelationship.connection_id == connection_id,
            or_(
                CachedRelationship.source_table_id.in_(selected_ids),
                CachedRelationship.target_table_id.in_(selected_ids),
            ),
        )
    )
    relationships = rel_result.scalars().all()

    neighbour_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for rel in relationships:
        for candidate_id in (rel.source_table_id, rel.target_table_id):
            if candidate_id not in selected_ids and candidate_id not in seen:
                seen.add(candidate_id)
                neighbour_ids.append(candidate_id)

    if not neighbour_ids:
        return tables

    # Batch-load all neighbour tables in a single query (replaces N db.get() calls)
    neighbours_result = await db.execute(
        select(CachedTable).where(CachedTable.id.in_(neighbour_ids))
    )
    neighbour_tables_by_id = {t.id: t for t in neighbours_result.scalars().all()}

    # Score each neighbour by keyword relevance; skip score=0 tables (irrelevant)
    scored_neighbours: list[tuple[uuid.UUID, float]] = []
    for table_id in neighbour_ids:
        cached_table = neighbour_tables_by_id.get(table_id)
        if not cached_table:
            continue
        score = keyword_match_score(cached_table.table_name, keywords)
        logger.debug(
            "FK-neighbour scoring: table=%s score=%.2f",
            cached_table.table_name,
            score,
        )
        scored_neighbours.append((table_id, score))

    scored_neighbours.sort(key=lambda x: x[1], reverse=True)
    # Only add neighbours with a positive keyword relevance score
    top_neighbours = [x for x in scored_neighbours if x[1] > 0.0][:max_extra]

    if not top_neighbours:
        return tables

    # Batch-load columns for all top neighbours via shared cache
    top_neighbour_ids = [t_id for t_id, _ in top_neighbours]
    columns_by_table = await get_columns_for_tables(db, top_neighbour_ids)

    extra: list[LinkedTable] = []
    for table_id, score in top_neighbours:
        cached_table = neighbour_tables_by_id.get(table_id)
        if not cached_table:
            continue
        extra.append(
            LinkedTable(
                table=cached_table,
                columns=columns_by_table.get(table_id, []),
                score=score,
                match_reason="fk_neighbour",
            )
        )
        logger.debug("FK-neighbour expansion: added table %s", cached_table.table_name)

    if extra:
        logger.info(
            "FK-neighbour expansion added %d table(s): %s",
            len(extra),
            [lt.table.table_name for lt in extra],
        )

    return tables + extra



