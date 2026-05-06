"""Deterministic Override Layer — ensures deterministic rules always win over LLM output.

This module implements the PRD requirement: "Deterministic layer ALWAYS wins over LLM output."

Rules:
1. Intent mismatch: current_intent != last_intent → follow_up_type = "new"
2. Override applies for all cases where deterministic logic contradicts LLM
3. All overrides are logged for observability
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OverrideResult:
    """Result of applying deterministic overrides."""

    final_follow_up_type: str  # "refine" | "replace" | "new"
    overrides_applied: list[str]  # List of override reasons
    was_overridden: bool  # True if any override was applied


def apply_overrides(
    extracted: dict[str, Any],
    state: dict[str, Any],
) -> OverrideResult:
    """Apply deterministic override rules to LLM extraction output.

    Args:
        extracted: The extracted dict from LLM (filters, sort, limit, follow_up_type)
        state: GraphState dict containing last_intent, current intent, etc.

    Returns:
        OverrideResult with final follow_up_type and override details
    """
    overrides_applied: list[str] = []
    llm_follow_up_type = extracted.get("follow_up_type", "new")
    current_follow_up_type = llm_follow_up_type

    # Get current and last intent from state
    current_intent = state.get("intent") or state.get("domain", "")
    last_intent = state.get("last_intent")

    # Rule 1: Intent mismatch → force follow_up_type = "new"
    # This is the most critical override - if user switches topic, ignore prior context
    if last_intent and current_intent != last_intent:
        if current_follow_up_type != "new":
            logger.info(
                "Override: Intent mismatch detected (current=%s, last=%s), "
                "forcing follow_up_type=new (was=%s)",
                current_intent,
                last_intent,
                current_follow_up_type,
            )
            overrides_applied.append(f"intent_mismatch: {last_intent} -> {current_intent}")
            current_follow_up_type = "new"

    # Additional override rules can be added here:
    # - Domain switch → "new"
    # - Confidence below threshold → "new"
    # - Invalid filters detected → "new"

    was_overridden = len(overrides_applied) > 0

    if was_overridden:
        logger.info(
            "Deterministic override applied: %s, final follow_up_type=%s",
            overrides_applied,
            current_follow_up_type,
        )

    return OverrideResult(
        final_follow_up_type=current_follow_up_type,
        overrides_applied=overrides_applied,
        was_overridden=was_overridden,
    )


def should_force_new_query(
    current_intent: str | None,
    last_intent: str | None,
    confidence: float | None = None,
) -> bool:
    """Helper to determine if a new query should be forced.

    Args:
        current_intent: The current intent from classification
        last_intent: The last intent from prior turn
        confidence: Optional confidence score

    Returns:
        True if a new query should be forced
    """
    # Intent mismatch
    if last_intent and current_intent and current_intent != last_intent:
        return True

    # Low confidence (optional additional rule)
    if confidence is not None and confidence < 0.3:
        return True

    return False


def merge_override_with_extracted(
    extracted: dict[str, Any],
    override_result: OverrideResult,
) -> dict[str, Any]:
    """Merge override result with extracted data.

    Args:
        extracted: Original LLM extraction
        override_result: Result from apply_overrides

    Returns:
        Updated extracted dict with final follow_up_type
    """
    result = extracted.copy()
    result["follow_up_type"] = override_result.final_follow_up_type

    if override_result.was_overridden:
        result["_overrides_applied"] = override_result.overrides_applied
        result["_override_warnings"] = [
            f"follow_up_type was overridden from {extracted.get('follow_up_type', 'new')}"
        ]

    return result


# =============================================================================
# LangGraph Node Wrapper
# =============================================================================


async def deterministic_override_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node for deterministic override layer.

    Applies deterministic rules that always win over LLM output.

    Args:
        state: Current GraphState

    Returns:
        Dict with final follow_up_type and confidence_breakdown
    """
    # Get extracted data from prior nodes
    extracted = {
        "filters": state.get("filters", []),
        "sort": state.get("sort", []),
        "limit": state.get("limit", 50),
        "follow_up_type": state.get("follow_up_type", "new"),
    }

    # Get last intent from last_turn_context
    last_turn = state.get("last_turn_context")
    if last_turn:
        state["last_intent"] = last_turn.get("intent")

    # Apply deterministic overrides
    override_result = apply_overrides(extracted, state)

    logger.info(
        "Deterministic override node: was_overridden=%s, final_follow_up_type=%s",
        override_result.was_overridden,
        override_result.final_follow_up_type,
    )

    return {
        "follow_up_type": override_result.final_follow_up_type,
        "confidence_breakdown": {
            "deterministic_override": 0.4 if not override_result.was_overridden else 0.0,
            "overrides_applied": override_result.overrides_applied,
        },
    }
