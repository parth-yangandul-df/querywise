"""Resolves business glossary terms and metrics from a NL question."""

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dictionary import DictionaryEntry
from app.db.models.glossary import GlossaryTerm
from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.db.models.metric import MetricDefinition
from app.db.models.sample_query import SampleQuery
from app.db.models.schema_cache import CachedColumn
from app.semantic.relevance_scorer import extract_keywords

logger = logging.getLogger(__name__)

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
        try:
            stmt = (
                select(GlossaryTerm)
                .where(
                    GlossaryTerm.connection_id == connection_id,
                    GlossaryTerm.term_embedding.isnot(None),
                )
                .order_by(GlossaryTerm.term_embedding.cosine_distance(question_embedding))
                .limit(3)
            )
            emb_result = await db.execute(stmt)
            for term in emb_result.scalars().all():
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
        except Exception:
            logger.warning(
                "Glossary vector search failed, using keyword results only.", exc_info=True
            )

    return results


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
        try:
            stmt = (
                select(MetricDefinition)
                .where(
                    MetricDefinition.connection_id == connection_id,
                    MetricDefinition.metric_embedding.isnot(None),
                )
                .order_by(MetricDefinition.metric_embedding.cosine_distance(question_embedding))
                .limit(3)
            )
            emb_result = await db.execute(stmt)
            for metric in emb_result.scalars().all():
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
        except Exception:
            logger.warning(
                "Metrics vector search failed, using keyword results only.", exc_info=True
            )

    return results


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

    try:
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
        return [
            ResolvedSampleQuery(
                natural_language=sq.natural_language,
                sql_query=sq.sql_query,
            )
            for sq in result.scalars().all()
        ]
    except Exception:
        logger.warning("Sample query vector search failed.", exc_info=True)
        return []


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
        try:
            stmt = (
                select(KnowledgeChunk, KnowledgeDocument)
                .join(
                    KnowledgeDocument,
                    KnowledgeChunk.document_id == KnowledgeDocument.id,
                )
                .where(
                    KnowledgeDocument.connection_id == connection_id,
                    KnowledgeChunk.chunk_embedding.isnot(None),
                    # Only include chunks that are actually similar to the question
                    KnowledgeChunk.chunk_embedding.cosine_distance(question_embedding) < 0.45,
                )
                .order_by(KnowledgeChunk.chunk_embedding.cosine_distance(question_embedding))
                .limit(limit)
            )
            result = await db.execute(stmt)
            rows = result.all()
            if rows:
                # Deduplicate: max 2 chunks per document
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
                return deduped
        except Exception:
            logger.warning(
                "Knowledge vector search failed, using keyword fallback.",
                exc_info=True,
            )

    # Keyword fallback
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
