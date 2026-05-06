"""Compute Embedding Node — generates embedding for the current user question.

This node is used in Hybrid Mode (Phase 8) to compute current_query_embedding
for follow-up detection and semantic similarity comparison with the previous query.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.embedding_service import embed_text

logger = logging.getLogger(__name__)


async def compute_embedding_node(state: dict[str, Any]) -> dict[str, Any]:
    """Compute embedding for the current question.

    Args:
        state: Current GraphState containing the question

    Returns:
        Dict with current_query_embedding
    """
    question = state.get("question", "")

    if not question:
        logger.warning("No question provided for embedding")
        return {"current_query_embedding": None}

    try:
        embedding = await embed_text(question)
        logger.debug("Computed embedding for question: %s", question[:50])
        return {"current_query_embedding": embedding}
    except Exception as e:
        logger.warning("Failed to compute embedding: %s", e)
        return {"current_query_embedding": None}
