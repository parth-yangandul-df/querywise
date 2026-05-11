"""similarity_check node - semantic shortcut for near-identical validated queries.

If the incoming question matches a validated sample query with cosine similarity
above SIMILARITY_SHORTCUT_THRESHOLD, the LLM composer is bypassed entirely and
execution routes directly to execute_sql with the stored, pre-validated SQL.

Skipped automatically when:
  - question_embedding is unavailable
  - Scope constraints are active (resource_id / employee_id set)
  - No validated sample queries exist for this connection
  - The stored SQL is unfiltered but the question asks for a specific named entity
  - The stored SQL filters on a different entity than the question asks about

Configure via env:
SIMILARITY_SHORTCUT_THRESHOLD   float 0.0-1.0, default 0.85
"""

import logging
import re
import uuid
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.core.metrics import timed_node
from app.db.models.sample_query import SampleQuery
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = settings.similarity_shortcut_threshold

# Patterns that signal a specific named entity is being requested
_ENTITY_PREPOSITIONS = re.compile(
    r"\b(for|of|named|called|by|at|under|within|belonging to)\s+(.+)",
    re.IGNORECASE,
)

# String literals in SQL WHERE clauses
_SQL_STRING_LITERALS = re.compile(r"'([^']+)'")


def _sql_has_string_filter(sql: str) -> bool:
    """True if the SQL has any hardcoded string literal (i.e. is a filtered/scoped query)."""
    return bool(_SQL_STRING_LITERALS.search(sql))


def _extract_entity_from_question(question: str) -> str | None:
    """Extract the named entity the user is filtering by, if any.

    Uses resolved_question (LLM-normalized, properly cased) for reliable detection.
    Returns the entity string or None if no specific entity is requested.
    """
    m = _ENTITY_PREPOSITIONS.search(question)
    if not m:
        return None
    entity = m.group(2).strip().rstrip("?.!")
    # Strip trailing clauses like "with...", "based on...", "where..."
    entity = re.split(r"\s+(with|based|where|who|that|and|or)\b", entity, flags=re.IGNORECASE)[0]
    return entity.strip() if entity.strip() else None


@timed_node("similarity_check")
async def similarity_check(state: GraphState) -> dict[str, Any]:
    """Check if the question closely matches a validated sample query.

    On a match, sets sql + generated_sql to the stored SQL and marks
    similarity_shortcut=True so route_after_similarity can skip compose_sql.
    """
    question = state.get("question", "")[:60]
    question_embedding = state.get("question_embedding")

    logger.info(
        "similarity_check: ====== ENTRY ====== q=%r embedding=%s",
        question,
        question_embedding is not None,
    )

    if not question_embedding:
        logger.info("similarity_check: skipped - no embedding")
        return {"similarity_shortcut": False}

    if state.get("resource_id") is not None or state.get("employee_id") is not None:
        logger.info("similarity_check: skipped - scope constraints active")
        return {"similarity_shortcut": False}

    connection_id = uuid.UUID(state["connection_id"])
    db_factory = state["db"]

    try:
        async with db_factory() as db:
            distance_col = SampleQuery.question_embedding.cosine_distance(question_embedding).label(
                "distance"
            )
            stmt = (
                select(SampleQuery, distance_col)
                .where(
                    SampleQuery.connection_id == connection_id,
                    SampleQuery.is_validated.is_(True),
                    SampleQuery.question_embedding.isnot(None),
                )
                .order_by(distance_col)
                .limit(1)
            )
            result = await db.execute(stmt)
            row = result.first()

            if row is None:
                logger.info("similarity_check: NO validated sample queries found in DB")
                return {"similarity_shortcut": False}

            sample_query, distance = row
            similarity = 1.0 - float(distance)
            logger.info(
                "similarity_check: best match similarity=%.4f q=%r matched_sql=%r",
                similarity,
                sample_query.natural_language[:60],
                sample_query.sql_query[:200],
            )

            if similarity >= _SIMILARITY_THRESHOLD:
                sql = sample_query.sql_query

                # Use resolved_question (LLM-normalized, properly cased) for entity detection.
                # The raw question is often all-lowercase so title-case heuristics fail.
                resolved = state.get("resolved_question") or state.get("question", "")
                entity = _extract_entity_from_question(resolved)
                sql_has_filter = _sql_has_string_filter(sql)

                if entity:
                    if not sql_has_filter:
                        # Generic unfiltered SQL cannot answer a specific-entity question
                        logger.info(
                            "similarity_check: entity guard - question asks for %r but stored SQL is unfiltered; falling through to compose_sql",
                            entity,
                        )
                        return {"similarity_shortcut": False}
                    if entity.lower() not in sql.lower():
                        # SQL filters on a different entity
                        logger.info(
                            "similarity_check: entity guard - question asks for %r but stored SQL filters on different entity; falling through to compose_sql",
                            entity,
                        )
                        return {"similarity_shortcut": False}

                logger.info(
                    "similarity_check: shortcut matched q=%r similarity=%.4f sql=%r",
                    state["question"][:60],
                    similarity,
                    sql[:200],
                )
                return {
                    "similarity_shortcut": True,
                    "sql": sql,
                    "generated_sql": sql,
                }

            logger.info(
                "similarity_check: no match (best=%.4f threshold=%.4f)",
                similarity,
                _SIMILARITY_THRESHOLD,
            )
            return {"similarity_shortcut": False}
    except Exception:
        logger.warning("similarity_check: vector search failed", exc_info=True)
        return {"similarity_shortcut": False}


def route_after_similarity(state: GraphState) -> str:
    """Route to execute_sql on shortcut hit, else proceed to compose_sql."""
    if state.get("similarity_shortcut"):
        logger.info("route_after_similarity: SHORTCUT HIT -> execute_sql")
        return "execute_sql"
    logger.info("route_after_similarity: no shortcut -> compose_sql")
    return "compose_sql"
