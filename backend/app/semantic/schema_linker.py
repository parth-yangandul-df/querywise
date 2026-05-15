"""Maps NL terms to relevant tables and columns using hybrid search."""

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.schema_cache import CachedColumn, CachedRelationship, CachedTable
from app.semantic.relevance_scorer import (
    ANCHOR_TABLE_SIGNALS,
    LOW_SIGNAL_TABLES,
    ScoredItem,
    column_keyword_score,
    extract_keywords,
    keyword_match_score,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory column cache — keyed by table UUID, TTL 30 minutes.
# Eliminates repeated per-table column SELECTs across requests.
# ---------------------------------------------------------------------------
_COLUMN_CACHE_TTL = 1800.0  # 30 minutes
_column_cache: dict[uuid.UUID, tuple[float, list[CachedColumn]]] = {}


async def get_columns_for_tables(
    db: AsyncSession,
    table_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[CachedColumn]]:
    """Return columns for each table_id, using an in-memory TTL cache.

    Checks the cache first; batch-fetches only uncached table IDs from the DB,
    then updates the cache.  This eliminates the N+1 column-loading pattern
    across schema_linker, context_builder, and _expand_fk_neighbours.

    Args:
        db: Async SQLAlchemy session.
        table_ids: List of table UUIDs to load columns for.

    Returns:
        Mapping of table_id → sorted list of CachedColumn objects.
    """
    if not table_ids:
        return {}

    now = time.monotonic()
    result: dict[uuid.UUID, list[CachedColumn]] = {}
    uncached: list[uuid.UUID] = []

    for tid in table_ids:
        entry = _column_cache.get(tid)
        if entry and (now - entry[0]) < _COLUMN_CACHE_TTL:
            result[tid] = entry[1]
        else:
            uncached.append(tid)

    if uncached:
        col_result = await db.execute(
            select(CachedColumn)
            .where(CachedColumn.table_id.in_(uncached))
            .order_by(CachedColumn.ordinal_position)
        )
        cols_by_table: dict[uuid.UUID, list[CachedColumn]] = {}
        for col in col_result.scalars().all():
            cols_by_table.setdefault(col.table_id, []).append(col)

        for tid in uncached:
            cols = cols_by_table.get(tid, [])
            _column_cache[tid] = (now, cols)
            result[tid] = cols

    return result


def invalidate_column_cache(table_id: uuid.UUID) -> None:
    """Evict a single table from the column cache (e.g. after schema re-introspection)."""
    _column_cache.pop(table_id, None)


def clear_column_cache() -> None:
    """Clear the entire column cache (call after a full schema re-introspection)."""
    _column_cache.clear()


@dataclass
class LinkedTable:
    table: CachedTable
    columns: list[CachedColumn]
    score: float
    match_reason: str  # "embedding" | "keyword" | "column_keyword" | "anchor" | "relationship"


async def find_relevant_tables(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question_embedding: list[float] | None,
    question: str,
    max_tables: int | None = None,
) -> list[LinkedTable]:
    """Find the most relevant tables for a question using hybrid search.

    Combines:
    1. Vector similarity search on table description embeddings (when available)
    2. Keyword matching on table names
    3. Column-name keyword matching (catches e.g. 'status' → StatusId column)
    4. Anchor table forcing for high-signal domain keywords
    5. FK relationship expansion
    """
    if max_tables is None:
        max_tables = settings.max_context_tables

    keywords = extract_keywords(question)
    question_lower = question.lower()

    logger.info(
        "schema_linker: question=%r keywords=%s connection=%s",
        question,
        keywords,
        connection_id,
    )

    # Stages 1-4: vector search runs first (it may rollback the session on failure);
    # Keyword searches must be sequential — AsyncSession is NOT safe for concurrent use.
    anchor_table_names = _detect_anchor_tables(question_lower, keywords)

    if question_embedding is not None:
        embedding_results = await _vector_search_tables(
            db, connection_id, question_embedding, limit=15
        )
    else:
        embedding_results = []

    keyword_results = await _keyword_search_tables(db, connection_id, keywords)
    column_hit_results = await _column_keyword_search_tables(db, connection_id, keywords)
    anchor_results = await _get_tables_by_names(db, connection_id, anchor_table_names)

    if anchor_results:
        logger.info(
            "schema_linker: forcing anchor tables %s",
            [t.table_name for t in anchor_results],
        )

    # Merge all candidates and score
    scored: dict[str, ScoredItem] = {}
    reason_map: dict[str, str] = {}

    for table, similarity in embedding_results:
        key = str(table.id)
        if key not in scored:
            scored[key] = ScoredItem(id=key, name=table.table_name)
            reason_map[key] = "embedding"
        scored[key].embedding_score = similarity

    for table in keyword_results:
        key = str(table.id)
        if key not in scored:
            scored[key] = ScoredItem(id=key, name=table.table_name)
        score = keyword_match_score(table.table_name, keywords)
        if score > scored[key].keyword_score:
            scored[key].keyword_score = score
            if reason_map.get(key) != "embedding":
                reason_map[key] = "keyword"

    for table, col_score in column_hit_results:
        key = str(table.id)
        if key not in scored:
            scored[key] = ScoredItem(id=key, name=table.table_name)
            reason_map[key] = "column_keyword"
        # Cap column_keyword score for known low-signal (history/audit/notification) tables
        # so they don't displace relevant tables when they happen to share generic column names.
        effective_score = col_score
        if table.table_name.lower() in LOW_SIGNAL_TABLES:
            effective_score = min(col_score, 0.1)
        # Store column score as keyword_score if it's the best we have
        if effective_score > scored[key].keyword_score:
            scored[key].keyword_score = effective_score
            if reason_map.get(key) not in ("embedding", "keyword"):
                reason_map[key] = "column_keyword"

    for table in anchor_results:
        key = str(table.id)
        if key not in scored:
            scored[key] = ScoredItem(id=key, name=table.table_name)
            reason_map[key] = "anchor"
        # Guarantee anchor tables always make the cut
        scored[key].keyword_score = max(scored[key].keyword_score, 1.0)
        reason_map[key] = "anchor"

    # Stage 5: Relationship expansion — boost tables connected via FK to high-scoring tables
    top_table_ids = [
        uuid.UUID(s.id)
        for s in sorted(scored.values(), key=lambda s: s.final_score, reverse=True)[:5]
    ]
    related_tables = await _get_related_tables(db, connection_id, top_table_ids)
    for table in related_tables:
        key = str(table.id)
        if key not in scored:
            scored[key] = ScoredItem(id=key, name=table.table_name)
            reason_map[key] = "relationship"
        scored[key].relationship_score = 1.0

    # Identify anchor table IDs before truncation
    anchor_ids = {
        str(t.id) for t in anchor_results
    } if anchor_results else set()

    # Sort by final score, take top N (anchors are guaranteed to exceed threshold)
    sorted_items = sorted(scored.values(), key=lambda s: s.final_score, reverse=True)

    # Ensure all anchor tables survive truncation
    if anchor_ids:
        top_ids = {s.id for s in sorted_items[:max_tables]}
        missing_anchors = anchor_ids - top_ids
        if missing_anchors:
            logger.info(
                "schema_linker: preserving %d forced anchor tables: %s",
                len(missing_anchors),
                [scored[k].name for k in missing_anchors if k in scored],
            )
            # Take more items to include all anchors
            extra_needed = len(missing_anchors)
            sorted_items = sorted_items[: max_tables + extra_needed]

    top_items = sorted_items[:max_tables]

    logger.info(
        "schema_linker: selected tables %s",
        [(s.name, f"{s.final_score:.3f}", reason_map.get(s.id, "?")) for s in top_items],
    )

    # Batch-load table metadata and columns (replaces N individual db.get() calls)
    top_table_ids_for_load = [uuid.UUID(item.id) for item in top_items]

    tables_result = await db.execute(
        select(CachedTable).where(CachedTable.id.in_(top_table_ids_for_load))
    )
    tables_by_id = {t.id: t for t in tables_result.scalars().all()}

    # Batch-load all columns via cache
    columns_by_table = await get_columns_for_tables(db, top_table_ids_for_load)

    results: list[LinkedTable] = []
    for item in top_items:
        table_id = uuid.UUID(item.id)
        table = tables_by_id.get(table_id)
        if not table:
            continue
        results.append(
            LinkedTable(
                table=table,
                columns=columns_by_table.get(table_id, []),
                score=item.final_score,
                match_reason=reason_map.get(item.id, "embedding"),
            )
        )

    return results


def _detect_anchor_tables(question_lower: str, keywords: list[str]) -> list[str]:
    """Return canonical table names that must be included based on strong domain signals."""
    forced: set[str] = set()
    for signal, table_name in ANCHOR_TABLE_SIGNALS.items():
        # Multi-word signals (e.g. "direct report") matched against full question
        if " " in signal:
            if signal in question_lower:
                forced.add(table_name)
        else:
            # Single-word signals matched against extracted keywords
            if signal in keywords or any(signal in kw or kw in signal for kw in keywords):
                forced.add(table_name)
    return list(forced)


async def _vector_search_tables(
    db: AsyncSession,
    connection_id: uuid.UUID,
    embedding: list[float],
    limit: int = 15,
) -> list[tuple[CachedTable, float]]:
    """Find tables by embedding similarity."""
    # Use cosine distance (1 - similarity), so lower = more similar
    stmt = (
        select(
            CachedTable,
            (1 - CachedTable.description_embedding.cosine_distance(embedding)).label("similarity"),
        )
        .where(
            CachedTable.connection_id == connection_id,
            CachedTable.description_embedding.isnot(None),
        )
        .order_by(CachedTable.description_embedding.cosine_distance(embedding))
        .limit(limit)
    )
    try:
        result = await db.execute(stmt)
    except Exception:
        logger.warning(
            "Vector search failed (possible dimension mismatch). "
            "Check EMBEDDING_DIMENSION matches your model. Falling back to keyword search.",
            exc_info=True,
        )
        await db.rollback()
        return []
    return [(row[0], row[1]) for row in result.all()]


async def _keyword_search_tables(
    db: AsyncSession,
    connection_id: uuid.UUID,
    keywords: list[str],
) -> list[CachedTable]:
    """Find tables whose names match any keyword."""
    if not keywords:
        return []

    # Build ILIKE conditions for each keyword
    conditions = []
    for kw in keywords:
        conditions.append(CachedTable.table_name.ilike(f"%{kw}%"))

    from sqlalchemy import or_

    stmt = select(CachedTable).where(CachedTable.connection_id == connection_id, or_(*conditions))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _column_keyword_search_tables(
    db: AsyncSession,
    connection_id: uuid.UUID,
    keywords: list[str],
) -> list[tuple[CachedTable, float]]:
    """Find tables whose *column names* match the question keywords.

    Returns (table, column_keyword_score) pairs sorted by score descending.
    This catches cases like 'show all clients with their status' where the
    word 'status' hits columns StatusId / StatusName even when the table
    name 'Client' would not rank high for 'status'.
    """
    if not keywords:
        return []

    from sqlalchemy import or_

    # Build ILIKE conditions on column names
    col_conditions = []
    for kw in keywords:
        col_conditions.append(CachedColumn.column_name.ilike(f"%{kw}%"))

    col_result = await db.execute(
        select(CachedColumn)
        .join(CachedTable, CachedColumn.table_id == CachedTable.id)
        .where(
            CachedTable.connection_id == connection_id,
            or_(*col_conditions),
        )
    )
    matching_cols = list(col_result.scalars().all())

    # Group by table_id and compute score
    table_col_names: dict[uuid.UUID, list[str]] = {}
    for col in matching_cols:
        table_col_names.setdefault(col.table_id, []).append(col.column_name)

    # Score tables and collect IDs that pass the threshold
    scored_ids: dict[uuid.UUID, float] = {}
    for table_id, col_names in table_col_names.items():
        score = column_keyword_score(col_names, keywords)
        if score > 0:
            scored_ids[table_id] = score

    if not scored_ids:
        return []

    # Batch-load all matching tables in one query (replaces N individual db.get() calls)
    tables_result = await db.execute(
        select(CachedTable).where(CachedTable.id.in_(list(scored_ids.keys())))
    )
    tables_by_id = {t.id: t for t in tables_result.scalars().all()}

    results: list[tuple[CachedTable, float]] = [
        (tables_by_id[tid], score) for tid, score in scored_ids.items() if tid in tables_by_id
    ]
    results.sort(key=lambda x: x[1], reverse=True)
    return results


async def _get_tables_by_names(
    db: AsyncSession,
    connection_id: uuid.UUID,
    table_names: list[str],
) -> list[CachedTable]:
    """Fetch tables by exact name (case-insensitive) for anchor forcing."""
    if not table_names:
        return []

    from sqlalchemy import or_

    conditions = [CachedTable.table_name.ilike(name) for name in table_names]
    result = await db.execute(
        select(CachedTable).where(
            CachedTable.connection_id == connection_id,
            or_(*conditions),
        )
    )
    return list(result.scalars().all())


async def _get_related_tables(
    db: AsyncSession,
    connection_id: uuid.UUID,
    table_ids: list[uuid.UUID],
) -> list[CachedTable]:
    """Find tables connected via FK to the given tables."""
    if not table_ids:
        return []

    from sqlalchemy import or_

    # Find relationships where source or target is in our table set
    rel_result = await db.execute(
        select(CachedRelationship).where(
            CachedRelationship.connection_id == connection_id,
            or_(
                CachedRelationship.source_table_id.in_(table_ids),
                CachedRelationship.target_table_id.in_(table_ids),
            ),
        )
    )
    relationships = rel_result.scalars().all()

    # Collect IDs of related tables not already in our set
    related_ids = set()
    for rel in relationships:
        if rel.source_table_id not in table_ids:
            related_ids.add(rel.source_table_id)
        if rel.target_table_id not in table_ids:
            related_ids.add(rel.target_table_id)

    if not related_ids:
        return []

    result = await db.execute(select(CachedTable).where(CachedTable.id.in_(related_ids)))
    return list(result.scalars().all())
