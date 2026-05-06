"""Observability — structured logging for the hybrid query system.

This module implements observability logging as required by PRD:
- log_query_context: Full query context logging
- log_fallback_event: Fallback ladder event logging
All logging uses structured JSON format.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

#: Extra logging for query context
query_logger = logging.getLogger("query_context")
#: Extra logging for fallback events
fallback_logger = logging.getLogger("fallback_events")


def log_query_context(
    query: str,
    intent: str | None,
    filters: list[dict[str, Any]],
    follow_up_type: str,
    confidence: float | None,
    final_sql: str | None,
    fallback_used: str | None,
    session_id: str | None = None,
    execution_id: str | None = None,
    domain: str | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    """Log complete query context for observability.

    Args:
        query: Original user question
        intent: Classified intent
        filters: Extracted filters
        follow_up_type: refine | replace | new
        confidence: Confidence score
        final_sql: Executed SQL (if any)
        fallback_used: Which fallback level was used (if any)
        session_id: Session identifier
        execution_id: Execution identifier
        domain: Domain (resource, client, etc.)
        success: Whether query succeeded
        error_message: Error message if failed
    """
    log_data = {
        "event": "query_context",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "session_id": session_id,
        "execution_id": execution_id,
        "query": query,
        "domain": domain,
        "intent": intent,
        "filters": filters,
        "follow_up_type": follow_up_type,
        "confidence": confidence,
        "final_sql": final_sql,
        "fallback_used": fallback_used,
        "success": success,
        "error_message": error_message,
    }

    # Use INFO for normal, WARN for fallback, ERROR for failures
    if not success:
        query_logger.error("Query failed: %s", log_data)
    elif fallback_used:
        query_logger.warning("Query with fallback: %s", log_data)
    else:
        query_logger.info("Query context: %s", log_data)


def log_fallback_event(
    level: int,
    reason: str,
    extracted_filters: list[dict[str, Any]],
    success: bool,
    session_id: str | None = None,
    execution_id: str | None = None,
    question: str | None = None,
) -> None:
    """Log fallback ladder event.

    Args:
        level: Fallback level (1-6)
        reason: Why fallback was triggered
        extracted_filters: Filters extracted at this level
        success: Whether this level succeeded
        session_id: Session identifier
        execution_id: Execution identifier
        question: Original question
    """
    log_data = {
        "event": "fallback_event",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "session_id": session_id,
        "execution_id": execution_id,
        "question": question,
        "level": level,
        "reason": reason,
        "extracted_filters_count": len(extracted_filters),
        "extracted_filters": extracted_filters,
        "success": success,
    }

    if success:
        fallback_logger.info("Fallback succeeded at level %d: %s", level, log_data)
    else:
        fallback_logger.warning("Fallback failed at level %d: %s", level, log_data)


def log_node_execution(
    node_name: str,
    execution_id: str | None = None,
    session_id: str | None = None,
    duration_ms: float | None = None,
    success: bool = True,
    error: str | None = None,
    **kwargs: Any,
) -> None:
    """Log individual node execution.

    Args:
        node_name: Name of the node
        execution_id: Execution identifier
        session_id: Session identifier
        duration_ms: Execution duration in milliseconds
        success: Whether execution succeeded
        error: Error message if failed
        **kwargs: Additional node-specific data
    """
    log_data = {
        "event": "node_execution",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "execution_id": execution_id,
        "session_id": session_id,
        "node_name": node_name,
        "duration_ms": duration_ms,
        "success": success,
        "error": error,
        **kwargs,
    }

    if success:
        logger.debug("Node %s completed: %s", node_name, log_data)
    else:
        logger.warning("Node %s failed: %s", node_name, log_data)


def create_query_log_context(
    session_id: str | None = None,
) -> dict[str, str]:
    """Create initial log context for a query.

    Args:
        session_id: Optional session ID

    Returns:
        Dict with session_id and execution_id
    """
    return {
        "session_id": session_id or str(uuid.uuid4()),
        "execution_id": str(uuid.uuid4()),
    }


def log_confidence_calculation(
    confidence: float,
    breakdown: dict[str, float],
    decision: str,
    execution_id: str | None = None,
) -> None:
    """Log confidence calculation details.

    Args:
        confidence: Final confidence score
        breakdown: Confidence breakdown by component
        decision: Decision (accept, partial_fallback, full_fallback)
        execution_id: Execution identifier
    """
    log_data = {
        "event": "confidence_calculation",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "execution_id": execution_id,
        "confidence": confidence,
        "breakdown": breakdown,
        "decision": decision,
    }

    logger.info("Confidence calculation: %s", log_data)


def log_override_applied(
    override_type: str,
    original_value: str,
    final_value: str,
    execution_id: str | None = None,
) -> None:
    """Log when deterministic override is applied.

    Args:
        override_type: Type of override (e.g., "intent_mismatch")
        original_value: Original value before override
        final_value: Final value after override
        execution_id: Execution identifier
    """
    log_data = {
        "event": "override_applied",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "execution_id": execution_id,
        "override_type": override_type,
        "original_value": original_value,
        "final_value": final_value,
    }

    logger.info("Override applied: %s", log_data)
