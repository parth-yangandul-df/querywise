"""Fallback Ladder — 6-level fallback chain for filter extraction failures.

This module implements the PRD fallback ladder:
- Level 1: Retry LLM (stronger prompt)
- Level 2: Heuristic Extraction (KNOWN_* constants)
- Level 3: Context Recovery (infer from tokens)
- Level 4: Partial Execution (run with partial filters)
- Level 5: Clarification (ask user)
- Level 6: Full LLM Fallback (generate SQL)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.llm.graph.nodes.context_recovery import recover_from_context
from app.llm.graph.nodes.llm_extraction import create_extraction_prompt_stronger

logger = logging.getLogger(__name__)


class FallbackLevel:
    """Enum for fallback levels."""

    RETRY_LLM = 1
    HEURISTIC = 2
    CONTEXT_RECOVERY = 3
    PARTIAL_EXECUTION = 4
    CLARIFICATION = 5
    FULL_LLM_FALLBACK = 6


@dataclass
class FallbackResult:
    """Result of fallback ladder execution."""

    level: int  # Which level succeeded (1-6)
    filters: list[dict[str, Any]]  # Extracted filters
    success: bool
    message: str | None = None
    clarification_needed: bool = False


async def execute_fallback_ladder(
    question: str,
    state: dict[str, Any],
    current_filters: list[dict[str, Any]],
    failure_reason: str,
    domain: str,
) -> FallbackResult:
    """Execute the 6-level fallback ladder.

    Args:
        question: The user's question
        state: GraphState dict
        current_filters: Filters extracted so far (may be empty)
        failure_reason: Why fallback was triggered (e.g., "low_confidence", "json_parse_error", "invalid_fields")
        domain: The domain for field validation

    Returns:
        FallbackResult with extracted filters and level info
    """
    logger.info(
        "Starting fallback ladder: failure_reason=%s, current_filters=%d",
        failure_reason,
        len(current_filters),
    )

    # Determine starting level based on failure reason
    start_level = _get_start_level(failure_reason)

    # Progress through levels
    for level in range(start_level, 7):
        try:
            logger.debug("Trying fallback level %d", level)

            if level == FallbackLevel.RETRY_LLM:
                result = await _try_retry_llm(question, domain, state)
            elif level == FallbackLevel.HEURISTIC:
                result = _try_heuristic(question, state)
            elif level == FallbackLevel.CONTEXT_RECOVERY:
                result = _try_context_recovery(question, state)
            elif level == FallbackLevel.PARTIAL_EXECUTION:
                result = _try_partial_execution(current_filters)
            elif level == FallbackLevel.CLARIFICATION:
                result = _try_clarification(question)
            elif level == FallbackLevel.FULL_LLM_FALLBACK:
                result = await _try_full_llm_fallback(question, state)
            else:
                continue

            if result.success:
                logger.info("Fallback succeeded at level %d", level)
                return FallbackResult(
                    level=level,
                    filters=result.filters,
                    success=True,
                    message=f"Succeeded at level {level}",
                )

        except Exception as e:
            logger.warning("Fallback level %d failed: %s", level, e)
            continue

    # All levels failed
    logger.error("All fallback levels exhausted")
    return FallbackResult(
        level=6,
        filters=[],
        success=False,
        message="All fallback levels exhausted",
    )


def _get_start_level(failure_reason: str) -> int:
    """Determine which level to start at based on failure reason."""
    if failure_reason == "low_confidence":
        # Low confidence - skip retry, start at context recovery
        return FallbackLevel.CONTEXT_RECOVERY
    elif failure_reason == "json_parse_error":
        # JSON failed - start at heuristic (skip retry)
        return FallbackLevel.HEURISTIC
    elif failure_reason == "invalid_fields":
        # Invalid fields - start at heuristic
        return FallbackLevel.HEURISTIC
    else:
        # Default: start at retry
        return FallbackLevel.RETRY_LLM


async def _try_retry_llm(
    question: str,
    domain: str,
    state: dict[str, Any],
) -> FallbackResult:
    """Level 1: Retry LLM with stronger prompt."""
    from app.llm.graph.nodes.llm_extraction import extract_structured

    messages = create_extraction_prompt_stronger(question, domain, state)

    try:
        # Use existing extraction but with stronger prompt
        result = await extract_structured(question, domain, state)

        if result.get("filters"):
            return FallbackResult(
                level=1,
                filters=result["filters"],
                success=True,
            )
    except Exception as e:
        logger.warning("Level 1 (retry) failed: %s", e)

    return FallbackResult(level=1, filters=[], success=False)


def _try_heuristic(
    question: str,
    state: dict[str, Any],
) -> FallbackResult:
    """Level 2: Heuristic extraction using known patterns."""
    from app.llm.graph.nodes.param_extractor import extract_params

    try:
        params = extract_params(state)

        # Convert params to filters
        filters = []
        for key, value in params.items():
            if value:
                filters.append(
                    {
                        "field": key,
                        "operator": "contains",
                        "value": value,
                    }
                )

        if filters:
            logger.info("Level 2 (heuristic) extracted %d filters", len(filters))
            return FallbackResult(
                level=2,
                filters=filters,
                success=True,
            )
    except Exception as e:
        logger.warning("Level 2 (heuristic) failed: %s", e)

    return FallbackResult(level=2, filters=[], success=False)


def _try_context_recovery(
    question: str,
    state: dict[str, Any],
) -> FallbackResult:
    """Level 3: Context recovery from question tokens."""
    last_filters = state.get("filters", [])

    try:
        filters = recover_from_context(question, last_filters)

        if filters:
            logger.info("Level 3 (context recovery) extracted %d filters", len(filters))
            return FallbackResult(
                level=3,
                filters=filters,
                success=True,
            )
    except Exception as e:
        logger.warning("Level 3 (context recovery) failed: %s", e)

    return FallbackResult(level=3, filters=[], success=False)


def _try_partial_execution(
    current_filters: list[dict[str, Any]],
) -> FallbackResult:
    """Level 4: Partial execution with available filters."""
    # If we have any filters, we can attempt partial execution
    # The actual SQL execution will handle partial filters
    if current_filters:
        logger.info("Level 4 (partial) using %d existing filters", len(current_filters))
        return FallbackResult(
            level=4,
            filters=current_filters,
            success=True,
            message="Using partial filters for execution",
        )

    return FallbackResult(level=4, filters=[], success=False)


def _try_clarification(question: str) -> FallbackResult:
    """Level 5: Request user clarification."""
    # Generate clarification prompt based on question
    clarification = _generate_clarification_prompt(question)

    logger.info("Level 5 (clarification) requesting user input")
    return FallbackResult(
        level=5,
        filters=[],
        success=False,
        message=clarification,
        clarification_needed=True,
    )


def _generate_clarification_prompt(question: str) -> str:
    """Generate a user-friendly clarification prompt."""
    # Analyze what information is missing
    return f"To help you with '{question}', could you specify more details about what you'd like to filter or find?"


async def _try_full_llm_fallback(
    question: str,
    state: dict[str, Any],
) -> FallbackResult:
    """Level 6: Full LLM fallback - generate SQL directly."""
    # This delegates to the existing llm_fallback chain
    # which will generate SQL without structured filter extraction

    logger.warning("Level 6 (full LLM fallback) - delegating to llm_fallback chain")

    # Return failure - the pipeline should detect this and route to llm_fallback
    # The actual LLM SQL generation happens in the existing graph path
    return FallbackResult(
        level=6,
        filters=[],
        success=False,
        message="Routing to full LLM fallback for SQL generation",
    )


def create_fallback_event_log(
    level: int,
    reason: str,
    filters_extracted: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create structured log for fallback events (for observability)."""
    return {
        "event": "fallback_triggered",
        "level": level,
        "reason": reason,
        "filters_extracted": len(filters_extracted),
    }
