"""Confidence Scoring — calculate confidence for LLM extraction quality.

This module implements the confidence scoring system from the PRD:
- valid_json: +0.3
- valid_fields: +0.3
- matches_schema: +0.4

Decision thresholds:
- >= 0.7: accept (use LLM extraction directly)
- >= 0.4: partial fallback (use some filters, heuristic for others)
- < 0.4: full fallback (trigger fallback ladder)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.llm.graph.nodes.field_registry import lookup_field

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceResult:
    """Result of confidence scoring."""

    score: float
    breakdown: dict[str, float]
    decision: str  # "accept" | "partial_fallback" | "full_fallback"
    reasons: list[str]


def calculate_confidence(
    extracted: dict[str, Any],
    domain: str,
) -> ConfidenceResult:
    """Calculate confidence score for LLM extraction output.

    Args:
        extracted: The extracted dict from LLM (filters, sort, limit, follow_up_type)
        domain: The domain to validate fields against

    Returns:
        ConfidenceResult with score, breakdown, decision, and reasons
    """
    breakdown: dict[str, float] = {}
    reasons: list[str] = []

    # 1. Check JSON validity (+0.3)
    valid_json = _check_json_validity(extracted)
    if valid_json:
        breakdown["valid_json"] = 0.3
    else:
        breakdown["valid_json"] = 0.0
        reasons.append("Invalid JSON structure")

    # 2. Check field validity against FieldRegistry (+0.3)
    field_validity_score, field_reasons = _check_field_validity(extracted, domain)
    breakdown["valid_fields"] = field_validity_score
    reasons.extend(field_reasons)

    # 2b. Check filter value complexity (+0.1 penalty for complex values)
    # Complex values like "missing", "incomplete" require LLM fallback
    complexity_score, complexity_reasons = _check_value_complexity(extracted, domain)
    breakdown["value_complexity"] = -complexity_score  # negative penalty
    reasons.extend(complexity_reasons)

    # 3. Check schema match (+0.4)
    schema_score, schema_reasons = _check_schema_match(extracted)
    breakdown["matches_schema"] = schema_score
    reasons.extend(schema_reasons)

    # Calculate total
    total_score = sum(breakdown.values())

    # Determine decision
    if total_score >= 0.7:
        decision = "accept"
    elif total_score >= 0.4:
        decision = "partial_fallback"
    else:
        decision = "full_fallback"

    logger.info(
        "Confidence score: %.2f (decision=%s) breakdown=%s", total_score, decision, breakdown
    )

    return ConfidenceResult(
        score=total_score,
        breakdown=breakdown,
        decision=decision,
        reasons=reasons if reasons else ["All checks passed"],
    )


def _check_json_validity(extracted: dict[str, Any]) -> bool:
    """Check if extracted has valid JSON structure."""
    if not isinstance(extracted, dict):
        return False

    # Must have at least filters key
    if "filters" not in extracted:
        return False

    # filters must be a list
    if not isinstance(extracted.get("filters"), list):
        return False

    # sort must be a list (or missing)
    sort_val = extracted.get("sort")
    if sort_val is not None and not isinstance(sort_val, list):
        return False

    # limit must be int or missing
    limit_val = extracted.get("limit")
    if limit_val is not None and not isinstance(limit_val, int):
        return False

    # follow_up_type must be valid string or missing
    follow_up = extracted.get("follow_up_type")
    if follow_up is not None and follow_up not in ("refine", "replace", "new"):
        return False

    return True


def _check_field_validity(
    extracted: dict[str, Any],
    domain: str,
) -> tuple[float, list[str]]:
    """Check if all extracted fields exist in FieldRegistry for the domain.

    Returns:
        Tuple of (score, reasons)
    """
    filters = extracted.get("filters", [])

    if not filters:
        # No filters to validate - partial score for empty but valid
        return 0.15, ["No filters to validate"]

    valid_count = 0
    total_count = len(filters)
    reasons: list[str] = []

    for f in filters:
        field_name = f.get("field", "")
        if not field_name:
            continue

        field_config = lookup_field(field_name, domain)
        if field_config:
            valid_count += 1
        else:
            reasons.append(f"Unknown field '{field_name}' for domain '{domain}'")

    if valid_count == total_count:
        reasons.append("All fields valid")
        return 0.3, reasons

    # Partial validity
    score = (valid_count / total_count) * 0.3
    return score, reasons


def _check_value_complexity(
    extracted: dict[str, Any],
    domain: str,
) -> tuple[float, list[str]]:
    """Check if filter values are simple or complex (require LLM fallback).

    Complex values like "missing", "incomplete", "null", "empty" require
    SQL generation for NULL checks - can't be handled by template SQL.

    Returns:
        Tuple of (penalty_score, reasons) — higher penalty means more complex
    """
    # Keywords that indicate complex semantic meaning requiring LLM
    COMPLEX_KEYWORDS: frozenset[str] = frozenset(
        {
            "missing",
            "incomplete",
            "null",
            "empty",
            "blank",
            "undefined",
            "none",
            "unset",
            "absent",
            "without",
            "lacking",
            "no description",
            "no name",
        }
    )

    filters = extracted.get("filters", [])
    penalty = 0.0
    reasons: list[str] = []

    for f in filters:
        for value in f.get("values", []):
            value_str = str(value).lower()
            if any(kw in value_str for kw in COMPLEX_KEYWORDS):
                penalty += 0.15  # 0.15 penalty per complex filter
                reasons.append(f"Complex value '{value}' requires LLM fallback")

    return penalty, reasons


def _check_schema_match(extracted: dict[str, Any]) -> tuple[float, list[str]]:
    """Check if extracted matches expected schema structure.

    Returns:
        Tuple of (score, reasons)
    """
    reasons: list[str] = []
    score = 0.0

    # Check filters structure
    filters = extracted.get("filters", [])
    if filters:
        valid_filter_count = 0
        for f in filters:
            # Each filter must have field and operator
            if "field" in f and "operator" in f:
                valid_filter_count += 1

        if valid_filter_count == len(filters):
            score += 0.15
            reasons.append("All filters have required keys")
        else:
            score += (valid_filter_count / len(filters)) * 0.15
            reasons.append(f"{valid_filter_count}/{len(filters)} filters complete")
    else:
        # Empty filters is valid
        score += 0.15
        reasons.append("No filters (empty is valid)")

    # Check sort structure
    sort = extracted.get("sort", [])
    if sort:
        valid_sort_count = 0
        for s in sort:
            if "field" in s:
                valid_sort_count += 1

        if valid_sort_count == len(sort):
            score += 0.1
            reasons.append("Sort structure valid")
        else:
            score += (valid_sort_count / len(sort)) * 0.1
    else:
        # No sort is valid
        score += 0.1
        reasons.append("No sort (empty is valid)")

    # Check limit
    limit = extracted.get("limit")
    if limit is not None and isinstance(limit, int) and 1 <= limit <= 1000:
        score += 0.05
        reasons.append("Limit valid")
    elif limit is None:
        # Default is valid
        score += 0.05
        reasons.append("Limit uses default")

    # Check follow_up_type
    follow_up = extracted.get("follow_up_type")
    if follow_up in ("refine", "replace", "new"):
        score += 0.1
        reasons.append("follow_up_type valid")
    elif follow_up is None:
        score += 0.1
        reasons.append("follow_up_type defaults to new")

    return score, reasons


def route_by_confidence(
    confidence_result: ConfidenceResult,
) -> str:
    """Route to appropriate processing path based on confidence decision.

    Args:
        confidence_result: The result from calculate_confidence

    Returns:
        Routing decision: "accept" | "partial_fallback" | "full_fallback"
    """
    return confidence_result.decision


def get_filters_for_processing(
    extracted: dict[str, Any],
    confidence_result: ConfidenceResult,
) -> list[dict[str, Any]]:
    """Get filters to use based on confidence level.

    Args:
        extracted: Raw extracted dict
        confidence_result: Confidence result

    Returns:
        List of filters to use (may be empty for full_fallback)
    """
    if confidence_result.decision == "accept":
        return extracted.get("filters", [])

    elif confidence_result.decision == "partial_fallback":
        # Use only high-confidence filters (valid fields)
        filters = extracted.get("filters", [])
        # Keep all filters but they may be processed with extra validation
        return filters

    else:  # full_fallback
        # Don't use any LLM-extracted filters - trigger fallback ladder
        return []


# =============================================================================
# LangGraph Node Wrapper
# =============================================================================


async def confidence_scoring_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node for confidence scoring.

    Calculates confidence score for LLM extraction and routes accordingly.

    Args:
        state: Current GraphState

    Returns:
        Dict with confidence score and decision
    """
    # Get extracted data from prior nodes
    extracted = {
        "filters": state.get("filters", []),
        "sort": state.get("sort", []),
        "limit": state.get("limit", 50),
        "follow_up_type": state.get("follow_up_type", "new"),
    }

    domain = state.get("domain", "resource")

    # Calculate confidence
    confidence_result = calculate_confidence(extracted, domain)

    # Merge with existing confidence_breakdown
    breakdown = state.get("confidence_breakdown", {})
    breakdown.update(
        {
            "valid_json": confidence_result.breakdown.get("valid_json", 0.0),
            "valid_fields": confidence_result.breakdown.get("valid_fields", 0.0),
            "matches_schema": confidence_result.breakdown.get("matches_schema", 0.0),
            "confidence_score": confidence_result.score,
            "decision": confidence_result.decision,
        }
    )

    logger.info(
        "Confidence scoring node: score=%.2f, decision=%s",
        confidence_result.score,
        confidence_result.decision,
    )

    return {
        "confidence": confidence_result.score,
        "confidence_breakdown": breakdown,
    }


def route_after_confidence(state: dict[str, Any]) -> str:
    """LangGraph conditional edge: route based on confidence score.

    Args:
        state: Current GraphState

    Returns:
        "update_query_plan" if confidence >= 0.7, else "llm_fallback"
    """
    confidence = state.get("confidence", 0.0)

    if confidence >= 0.7:
        return "update_query_plan"
    return "llm_fallback"
