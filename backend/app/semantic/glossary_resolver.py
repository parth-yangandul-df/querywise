"""Resolves business glossary terms and metrics from a NL question."""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dictionary import DictionaryEntry
from app.db.models.glossary import GlossaryTerm
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.models.metric import MetricDefinition
from app.db.models.sample_query import SampleQuery
from app.db.models.schema_cache import CachedColumn
from app.semantic.relevance_scorer import extract_keywords

logger = logging.getLogger(__name__)


async def _retry_db(
    coro_fn,
    db: AsyncSession,
    *args,
    retries: int = 3,
    base_delay: float = 0.25,
    name: str = "db operation",
) -> list:
    """Execute a DB coroutine with exponential-backoff retry on transient errors.

    Args:
        coro_fn: async function(db, *args) that returns a list
        *args: positional args passed through to coro_fn
        retries: max retry attempts (total attempts = retries + 1)
        base_delay: seconds to wait before first retry, doubles each subsequent attempt
        name: human-readable label for log messages

    Returns:
        The result of coro_fn, or an empty list if all retries fail.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await coro_fn(db, *args)
        except asyncio.CancelledError:
            raise
        except DBAPIError as exc:
            last_exc = exc
            if attempt < retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "%s attempt %d/%d failed (DBAPIError, %s), retrying in %.1fs.",
                    name,
                    attempt + 1,
                    retries + 1,
                    exc.__class__.__name__,
                    delay,
                    exc_info=False,
                )
                await asyncio.sleep(delay)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "%s attempt %d/%d failed, retrying in %.1fs.",
                    name,
                    attempt + 1,
                    retries + 1,
                    delay,
                    exc_info=False,
                )
                await asyncio.sleep(delay)
            else:
                break

    logger.warning(
        "%s failed after %d attempts — returning empty list. (%s: %s)",
        name,
        retries + 1,
        last_exc.__class__.__name__ if last_exc else "unknown",
        str(last_exc) if last_exc else "",
    )
    return []

# ---------------------------------------------------------------------------
# In-memory TTL caches for rarely-changing semantic metadata
# Keyed by connection_id (UUID); value is (timestamp, data).
# ---------------------------------------------------------------------------
_GLOSSARY_TTL = 300.0  # 5 minutes
_METRICS_TTL = 300.0

_glossary_cache: dict[uuid.UUID, tuple[float, list[GlossaryTerm]]] = {}
_metrics_cache: dict[uuid.UUID, tuple[float, list[MetricDefinition]]] = {}


def invalidate_glossary_cache(connection_id: uuid.UUID) -> None:
    """Call from API endpoints after glossary create/update/delete."""
    _glossary_cache.pop(connection_id, None)


def invalidate_metrics_cache(connection_id: uuid.UUID) -> None:
    """Call from API endpoints after metric create/update/delete."""
    _metrics_cache.pop(connection_id, None)


async def _get_all_glossary_terms(
    db: AsyncSession,
    connection_id: uuid.UUID,
) -> list[GlossaryTerm]:
    """Return all glossary terms for a connection, using the in-memory TTL cache."""
    now = time.monotonic()
    entry = _glossary_cache.get(connection_id)
    if entry and (now - entry[0]) < _GLOSSARY_TTL:
        return entry[1]

    result = await db.execute(
        select(GlossaryTerm).where(GlossaryTerm.connection_id == connection_id)
    )
    terms = list(result.scalars().all())
    _glossary_cache[connection_id] = (now, terms)
    return terms


async def _get_all_metrics(
    db: AsyncSession,
    connection_id: uuid.UUID,
) -> list[MetricDefinition]:
    """Return all metric definitions for a connection, using the in-memory TTL cache."""
    now = time.monotonic()
    entry = _metrics_cache.get(connection_id)
    if entry and (now - entry[0]) < _METRICS_TTL:
        return entry[1]

    result = await db.execute(
        select(MetricDefinition).where(MetricDefinition.connection_id == connection_id)
    )
    metrics = list(result.scalars().all())
    _metrics_cache[connection_id] = (now, metrics)
    return metrics


@dataclass
class ResolvedGlossary:
    term: str
    definition: str
    sql_expression: str
    related_tables: list[str]


@dataclass
class ResolvedMetric:
    metric_name: str
    display_name: str
    sql_expression: str
    related_tables: list[str]
    dimensions: list[str]


@dataclass
class ResolvedDictionary:
    table_name: str
    column_name: str
    mappings: dict[str, str]  # raw_value -> display_value


@dataclass
class ResolvedKnowledge:
    title: str
    source_url: str | None
    content: str


@dataclass
class ResolvedSampleQuery:
    natural_language: str
    sql_query: str


async def resolve_glossary(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question: str,
    question_embedding: list[float] | None = None,
) -> list[ResolvedGlossary]:
    """Find glossary terms relevant to the question.

    Uses keyword matching + optional embedding similarity.
    Fetches all terms via TTL cache to avoid per-request DB round-trips.
    """
    keywords = extract_keywords(question)
    results: list[ResolvedGlossary] = []
    seen_terms: set[str] = set()

    all_terms = await _get_all_glossary_terms(db, connection_id)

    # Keyword matching against term names
    for term in all_terms:
        term_lower = term.term.lower()
        for kw in keywords:
            if kw in term_lower or term_lower in kw:
                if term.term not in seen_terms:
                    results.append(
                        ResolvedGlossary(
                            term=term.term,
                            definition=term.definition,
                            sql_expression=term.sql_expression,
                            related_tables=term.related_tables or [],
                        )
                    )
                    seen_terms.add(term.term)
                break

    # Also check question text directly for term matches
    question_lower = question.lower()
    for term in all_terms:
        if term.term.lower() in question_lower and term.term not in seen_terms:
            results.append(
                ResolvedGlossary(
                    term=term.term,
                    definition=term.definition,
                    sql_expression=term.sql_expression,
                    related_tables=term.related_tables or [],
                )
            )
            seen_terms.add(term.term)

    # Embedding similarity (top 3)
    if question_embedding:
        emb_result = await _retry_db(
            _glossary_embedding_search, db, connection_id, question_embedding,
            name="Glossary vector search",
        )
        for term in emb_result:
            if term.term not in seen_terms:
                results.append(
                    ResolvedGlossary(
                        term=term.term,
                        definition=term.definition,
                        sql_expression=term.sql_expression,
                        related_tables=term.related_tables or [],
                    )
                )
                seen_terms.add(term.term)

    return results


async def _glossary_embedding_search(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question_embedding: list[float],
) -> list[GlossaryTerm]:
    stmt = (
        select(GlossaryTerm)
        .where(
            GlossaryTerm.connection_id == connection_id,
            GlossaryTerm.term_embedding.isnot(None),
        )
        .order_by(GlossaryTerm.term_embedding.cosine_distance(question_embedding))
        .limit(3)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def resolve_metrics(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question: str,
    question_embedding: list[float] | None = None,
) -> list[ResolvedMetric]:
    """Find metric definitions relevant to the question.

    Fetches all metrics via TTL cache to avoid per-request DB round-trips.
    """
    results: list[ResolvedMetric] = []
    seen: set[str] = set()

    question_lower = question.lower()
    all_metrics = await _get_all_metrics(db, connection_id)

    for metric in all_metrics:
        if (
            metric.display_name.lower() in question_lower
            or metric.metric_name.lower() in question_lower
        ):
            if metric.metric_name not in seen:
                results.append(
                    ResolvedMetric(
                        metric_name=metric.metric_name,
                        display_name=metric.display_name,
                        sql_expression=metric.sql_expression,
                        related_tables=metric.related_tables or [],
                        dimensions=metric.dimensions or [],
                    )
                )
                seen.add(metric.metric_name)

    # Embedding similarity
    if question_embedding:
        emb_result = await _retry_db(
            _metrics_embedding_search, db, connection_id, question_embedding,
            name="Metrics vector search",
        )
        for metric in emb_result:
            if metric.metric_name not in seen:
                results.append(
                    ResolvedMetric(
                        metric_name=metric.metric_name,
                        display_name=metric.display_name,
                        sql_expression=metric.sql_expression,
                        related_tables=metric.related_tables or [],
                        dimensions=metric.dimensions or [],
                    )
                )
                seen.add(metric.metric_name)

    return results


async def _metrics_embedding_search(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question_embedding: list[float],
) -> list[MetricDefinition]:
    stmt = (
        select(MetricDefinition)
        .where(
            MetricDefinition.connection_id == connection_id,
            MetricDefinition.metric_embedding.isnot(None),
        )
        .order_by(MetricDefinition.metric_embedding.cosine_distance(question_embedding))
        .limit(3)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def resolve_dictionary(
    db: AsyncSession,
    column_ids: list[uuid.UUID],
) -> list[ResolvedDictionary]:
    """Get data dictionary entries for the given columns."""
    if not column_ids:
        return []

    result = await db.execute(
        select(DictionaryEntry, CachedColumn)
        .join(CachedColumn, DictionaryEntry.column_id == CachedColumn.id)
        .where(DictionaryEntry.column_id.in_(column_ids))
        .order_by(DictionaryEntry.sort_order)
    )

    # Group by column
    grouped: dict[uuid.UUID, ResolvedDictionary] = {}
    for entry, column in result.all():
        if column.id not in grouped:
            grouped[column.id] = ResolvedDictionary(
                table_name="",  # Will be filled
                column_name=column.column_name,
                mappings={},
            )
        grouped[column.id].mappings[entry.raw_value] = entry.display_value

    return list(grouped.values())


async def find_similar_queries(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question_embedding: list[float] | None,
    limit: int = 3,
) -> list[ResolvedSampleQuery]:
    """Find the most similar validated sample queries."""
    if question_embedding is None:
        return []

    rows = await _retry_db(
        _sample_query_search, db, connection_id, question_embedding, limit,
        name="Sample query vector search",
    )
    return [
        ResolvedSampleQuery(natural_language=sq.natural_language, sql_query=sq.sql_query)
        for sq in rows
    ]


async def _sample_query_search(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question_embedding: list[float],
    limit: int,
) -> list[SampleQuery]:
    stmt = (
        select(SampleQuery)
        .where(
            SampleQuery.connection_id == connection_id,
            SampleQuery.is_validated.is_(True),
            SampleQuery.question_embedding.isnot(None),
        )
        .order_by(SampleQuery.question_embedding.cosine_distance(question_embedding))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def resolve_knowledge(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question: str,
    question_embedding: list[float] | None,
    limit: int = 3,
) -> list[ResolvedKnowledge]:
    """Find the most relevant knowledge chunks.

    Uses vector similarity with a cosine-distance threshold when embeddings are
    available; falls back to keyword ILIKE search otherwise.

    Only chunks with cosine_distance < 0.45 (similarity > 0.55) are returned to
    avoid injecting irrelevant content into the prompt.  At most 2 chunks per
    document are included to prevent a single verbose document from dominating
    the context window.
    """
    if question_embedding is not None:
        rows = await _retry_db(
            _knowledge_embedding_search, db, connection_id, question_embedding, limit,
            name="Knowledge vector search",
        )
        if rows:
            doc_counts: dict[uuid.UUID, int] = {}
            deduped: list[ResolvedKnowledge] = []
            for chunk, doc in rows:
                count = doc_counts.get(doc.id, 0)
                if count < 2:
                    deduped.append(
                        ResolvedKnowledge(
                            title=doc.title,
                            source_url=doc.source_url,
                            content=chunk.content,
                        )
                    )
                    doc_counts[doc.id] = count + 1
            if deduped:
                return deduped

    # Keyword fallback
    return await _knowledge_keyword_search(db, connection_id, question, limit)


async def _knowledge_embedding_search(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question_embedding: list[float],
    limit: int,
) -> list[tuple[KnowledgeChunk, KnowledgeDocument]]:
    stmt = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(
            KnowledgeDocument,
            KnowledgeChunk.document_id == KnowledgeDocument.id,
        )
        .where(
            KnowledgeDocument.connection_id == connection_id,
            KnowledgeChunk.chunk_embedding.isnot(None),
            KnowledgeChunk.chunk_embedding.cosine_distance(question_embedding) < 0.45,
        )
        .order_by(KnowledgeChunk.chunk_embedding.cosine_distance(question_embedding))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.all())


async def _knowledge_keyword_search(
    db: AsyncSession,
    connection_id: uuid.UUID,
    question: str,
    limit: int,
) -> list[ResolvedKnowledge]:
    keywords = [kw for kw in extract_keywords(question) if len(kw) > 2][:8]
    if not keywords:
        return []

    keyword_predicates = [KnowledgeChunk.content.ilike(f"%{kw}%") for kw in keywords]
    stmt = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(
            KnowledgeDocument,
            KnowledgeChunk.document_id == KnowledgeDocument.id,
        )
        .where(
            KnowledgeDocument.connection_id == connection_id,
            or_(*keyword_predicates),
        )
        .order_by(KnowledgeChunk.chunk_index.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        ResolvedKnowledge(
            title=doc.title,
            source_url=doc.source_url,
            content=chunk.content,
        )
        for chunk, doc in result.all()
    ]
