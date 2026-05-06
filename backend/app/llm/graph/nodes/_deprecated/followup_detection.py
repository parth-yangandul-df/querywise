"""Follow-up detection node for hybrid query mode.

Determines whether a user query is:
- "refine": Adding more filters to the same intent (semantic similarity > 0.7)
- "replace": Replacing filters on the same fields
- "new": Completely new query (intent mismatch or low similarity)
"""

from typing import Any


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First embedding vector
        b: Second embedding vector

    Returns:
        Cosine similarity score between -1 and 1
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    magnitude_a = sum(x * x for x in a) ** 0.5
    magnitude_b = sum(y * y for y in b) ** 0.5

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def detect_followup_type(
    current_embedding: list[float] | None,
    last_embedding: list[float] | None,
    current_intent: str | None,
    last_intent: str | None,
    current_filters: list[dict] | None = None,
    last_filters: list[dict] | None = None,
) -> tuple[str, float | None]:
    """Detect the type of follow-up query.

    Args:
        current_embedding: Embedding of current user question
        last_embedding: Embedding of previous user question
        current_intent: Intent classification of current question
        last_intent: Intent classification of previous question
        current_filters: Filters extracted from current question
        last_filters: Filters from previous question

    Returns:
        Tuple of (follow_up_type, semantic_similarity)
        - follow_up_type: "refine" | "replace" | "new"
        - semantic_similarity: Cosine similarity score (None if embeddings unavailable)
    """
    # Rule 1: Intent mismatch = new query (topic switch)
    if current_intent and last_intent and current_intent != last_intent:
        return ("new", None)

    # Cannot determine without embeddings
    if not current_embedding or not last_embedding:
        return ("new", None)

    # Rule 2: Compute semantic similarity
    similarity = cosine_similarity(current_embedding, last_embedding)

    # Rule 3: High similarity (> 0.7) = refine
    if similarity > 0.7:
        return ("refine", similarity)

    # Rule 4: Check for same-field filter replacement
    if current_filters and last_filters:
        current_fields = {f.get("field") for f in current_filters if f.get("field")}
        last_fields = {f.get("field") for f in last_filters if f.get("field")}

        # If same field exists in both, it's a replace (not refine)
        if current_fields & last_fields:
            return ("replace", similarity)

    # Default: new query (low similarity, no intent match)
    return ("new", similarity)


async def followup_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node for follow-up detection.

    Called after classify_intent to determine query type.

    Args:
        state: Current GraphState

    Returns:
        Dict with follow_up_type and semantic_similarity
    """
    current_embedding = state.get("current_query_embedding")
    last_embedding = state.get("last_query_embedding")
    current_intent = state.get("intent")
    last_intent = (
        state.get("last_turn_context", {}).get("intent") if state.get("last_turn_context") else None
    )
    current_filters = state.get("filters", [])
    last_filters = (
        state.get("last_turn_context", {}).get("filters")
        if state.get("last_turn_context")
        else None
    )

    follow_up_type, similarity = detect_followup_type(
        current_embedding=current_embedding,
        last_embedding=last_embedding,
        current_intent=current_intent,
        last_intent=last_intent,
        current_filters=current_filters,
        last_filters=last_filters,
    )

    return {
        "follow_up_type": follow_up_type,
        "semantic_similarity": similarity,
    }
