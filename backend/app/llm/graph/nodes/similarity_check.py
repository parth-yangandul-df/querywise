"""similarity_check node — semantic shortcut for near-identical validated queries.

If the incoming question matches a validated sample query with cosine similarity
above SIMILARITY_SHORTCUT_THRESHOLD, the LLM composer is bypassed entirely and
execution routes directly to execute_sql with the stored, pre-validated SQL.

Skipped automatically when:
  - question_embedding is unavailable (embedding service is down / not configured)
  - Scope constraints are active (resource_id / employee_id set) — stored SQL
    lacks the per-user WHERE filter needed for scoped access
  - No validated sample queries exist for this connection

Configure via env:
SIMILARITY_SHORTCUT_THRESHOLD   float 0.0–1.0, default 0.85
"""

import logging
import os
import uuid
from typing import Any

from sqlalchemy import select

from app.db.models.sample_query import SampleQuery
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_SHORTCUT_THRESHOLD", "0.85"))


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

    # Cannot compute similarity without an embedding
    if not question_embedding:
        logger.info("similarity_check: skipped — no embedding")
        return {"similarity_shortcut": False}

    # Never shortcut when user-scoped queries are required —
    # the stored SQL has no ResourceId / EmployeeId WHERE clause.
    if state.get("resource_id") is not None or state.get("employee_id") is not None:
        logger.info("similarity_check: skipped — scope constraints active")
        return {"similarity_shortcut": False}

    connection_id = uuid.UUID(state["connection_id"])
    db = state["db"]

    try:
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
    except Exception:
        logger.warning("similarity_check: vector search failed", exc_info=True)
        return {"similarity_shortcut": False}

    if row is None:
        logger.info("similarity_check: NO validated sample queries found in DB")
        return {"similarity_shortcut": False}

    sample_query, distance = row
    similarity = 1.0 - float(distance)
    logger.info(
        "similarity_check: best match similarity=%.4f q=%r matched_sql=%r",
        similarity,
        sample_query.natural_language[:60],
        sample_query.sql_query[:60],
    )

    if similarity >= _SIMILARITY_THRESHOLD:
        logger.info(
            "similarity_check: shortcut matched q=%r similarity=%.4f sql=%r",
            state["question"][:60],
            similarity,
            sample_query.sql_query[:60],
        )
        return {
            "similarity_shortcut": True,
            "sql": sample_query.sql_query,
            "generated_sql": sample_query.sql_query,
        }

    logger.info(
        "similarity_check: no match (best=%.4f threshold=%.4f)",
        similarity,
        _SIMILARITY_THRESHOLD,
    )
    return {"similarity_shortcut": False}


def route_after_similarity(state: GraphState) -> str:
    """Route to execute_sql on shortcut hit, else proceed to compose_sql."""
    if state.get("similarity_shortcut"):
        logger.info("route_after_similarity: SHORTCUT HIT -> execute_sql")
        return "execute_sql"
    logger.info("route_after_similarity: no shortcut -> compose_sql")
    return "compose_sql"
