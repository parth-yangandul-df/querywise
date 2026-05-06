"""LLM Structured Extraction — single-call JSON extraction for hybrid mode.

This module replaces unstructured LLM SQL generation with structured JSON extraction.
A single LLM call extracts filters, sort, limit, and follow_up_type in strict JSON format.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.llm.base_provider import LLMConfig, LLMMessage
from app.llm.graph.nodes.field_registry import FIELD_REGISTRY_BY_DOMAIN, lookup_field
from app.llm.utils import repair_json

logger = logging.getLogger(__name__)

#: Remap well-known LLM field hallucinations to canonical field names
_FIELD_ALIAS_REMAP: dict[str, str] = {
    "reports_to": "resource_name",
    "manager": "resource_name",
    "reporting_to": "resource_name",
    "project_manager": "resource_name",
}

#: System prompt enforcing strict JSON output with no explanation
SYSTEM_PROMPT = """You are a structured query extractor. Given a user question about a database, extract the query parameters in JSON format.

OUTPUT STRICT JSON ONLY - no explanation, no markdown, no text before or after.

Required output format:
{
  "filters": [{"field": "field_name", "operator": "eq|contains|in", "value": "value"}],
  "sort": [{"field": "field_name", "order": "asc|desc"}],
  "limit": 50,
  "follow_up_type": "refine|replace|new"
}

Rules:
- Use "eq" for exact match, "contains" for LIKE search, "in" for multiple values
- "follow_up_type": "refine" = adding new filters, "replace" = changing existing filters, "new" = new query
- Only use field names that exist in the available fields for the domain
- If no filters can be extracted, return {"filters": [], "sort": [], "limit": 50, "follow_up_type": "new"}
"""

#: Available fields by domain - populated at module load
AVAILABLE_FIELDS_BY_DOMAIN: dict[str, list[str]] = {
    domain: list(fields.keys()) for domain, fields in FIELD_REGISTRY_BY_DOMAIN.items()
}


def _get_user_prompt_template(domain: str) -> str:
    """Generate user prompt with domain context and available fields."""
    available_fields = AVAILABLE_FIELDS_BY_DOMAIN.get(domain, [])
    fields_str = (
        ", ".join(available_fields) if available_fields else "skill, resource_name, designation"
    )

    return """Question: {question}

Domain: {domain}
Available fields for this domain: {fields}

Extract query parameters as JSON."""


async def extract_structured(
    question: str,
    domain: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured query parameters from a natural language question.

    Args:
        question: The user's natural language question
        domain: The intent domain (resource, client, project, timesheet, user_self)
        context: Optional context from prior turns (last_filters, last_intent)

    Returns:
        Dict with keys: filters, sort, limit, follow_up_type
    """
    # Get provider and config from router
    from app.llm.router import route

    provider, config = route(question)

    # Override config for extraction - use more tokens for JSON
    extraction_config = LLMConfig(
        model=config.model,
        temperature=0.0,
        max_tokens=1024,
        top_p=1.0,
    )

    # Build context string if provided
    context_str = ""
    if context:
        if context.get("last_filters"):
            context_str += f"\nPrevious filters: {json.dumps(context['last_filters'])}"
        if context.get("last_intent"):
            context_str += f"\nPrevious intent: {context['last_intent']}"

    # Format user prompt
    available_fields = AVAILABLE_FIELDS_BY_DOMAIN.get(domain, ["skill", "resource_name"])
    user_prompt = f"""Question: {question}

Domain: {domain}
Available fields for this domain: {", ".join(available_fields)}
{context_str}

IMPORTANT MAPPING RULES:
- "missing", "incomplete", "empty", "null", "blank" descriptions → use field "description" with value "missing"
- "has description", "with description", "complete descriptions" → use field "description" with value "has_value"
- Status values should be capitalized: "active" → "Active", "inactive" → "Inactive"
- "client_name" field is for filtering by specific client names, not for "missing" queries

Extract query parameters as JSON."""

    messages = [
        LLMMessage(role="system", content=SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_prompt),
    ]

    try:
        response = await provider.complete(messages, extraction_config)
        content = response.content.strip()

        # Handle repair_json for Ollama/local models
        if hasattr(provider, "provider_type") and str(provider.provider_type) == "ollama":
            content = repair_json(content)

        # Parse JSON
        extracted = json.loads(content)

        # Validate and normalize fields
        extracted = _validate_and_normalize_fields(extracted, domain)

        logger.info(
            "LLM extraction succeeded for domain=%s, filters=%d",
            domain,
            len(extracted.get("filters", [])),
        )

        return extracted

    except json.JSONDecodeError as e:
        logger.warning("LLM extraction JSON parse failed: %s, content: %s", e, content[:200])
        return _fallback_extraction(question, domain, context)
    except Exception as e:
        logger.warning("LLM extraction failed: %s", e)
        return _fallback_extraction(question, domain, context)


def _validate_and_normalize_fields(
    extracted: dict[str, Any],
    domain: str,
) -> dict[str, Any]:
    """Validate extracted fields against FieldRegistry and normalize.

    Args:
        extracted: Raw extracted dict from LLM
        domain: The domain to validate against

    Returns:
        Cleaned dict with invalid fields removed
    """
    valid_filters = []

    for f in extracted.get("filters", []):
        field_name = f.get("field", "")

        # Remap well-known LLM field hallucinations to canonical field names
        field_name = _FIELD_ALIAS_REMAP.get(field_name, field_name)

        # Check if field exists in registry for this domain
        field_config = lookup_field(field_name, domain)

        if field_config is None:
            logger.warning("Dropping unknown field '%s' for domain '%s'", field_name, domain)
            continue

        # Normalize operator
        op = f.get("operator", "eq")
        if op not in ("eq", "contains", "in"):
            op = "eq"

        # Normalize value
        value = f.get("value", "")

        valid_filters.append(
            {
                "field": field_name,
                "operator": op,
                "value": value,
            }
        )

    # Normalize sort
    valid_sort = []
    for s in extracted.get("sort", []):
        if "field" in s:
            valid_sort.append(
                {
                    "field": s["field"],
                    "order": s.get("order", "asc") if s.get("order") in ("asc", "desc") else "asc",
                }
            )

    # Normalize limit
    limit = extracted.get("limit", 50)
    if not isinstance(limit, int) or limit < 1:
        limit = 50
    limit = min(limit, 1000)  # Cap at 1000

    # Normalize follow_up_type
    follow_up_type = extracted.get("follow_up_type", "new")
    if follow_up_type not in ("refine", "replace", "new"):
        follow_up_type = "new"

    return {
        "filters": valid_filters,
        "sort": valid_sort,
        "limit": limit,
        "follow_up_type": follow_up_type,
    }


def _fallback_extraction(
    question: str,
    domain: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fallback extraction using heuristic patterns when LLM fails.

    This implements Level 2 of the fallback ladder.
    """
    from app.llm.graph.nodes.param_extractor import extract_params

    # Use existing param_extractor as fallback
    try:
        # Create minimal state for param_extractor
        state = {"question": question, "domain": domain}
        params = extract_params(state)

        # Convert params to filters
        filters = []
        for key, value in params.items():
            if value:
                # Map param key to field name
                field_config = lookup_field(key, domain)
                if field_config:
                    filters.append(
                        {
                            "field": key,
                            "operator": "contains" if field_config.sql_type == "text" else "eq",
                            "value": value,
                        }
                    )

        logger.info("Fallback extraction succeeded, filters=%d", len(filters))

        return {
            "filters": filters,
            "sort": [],
            "limit": 50,
            "follow_up_type": "new" if not context else "refine",
        }
    except Exception as e:
        logger.warning("Fallback extraction also failed: %s", e)

        # Complete failure - return empty
        return {
            "filters": [],
            "sort": [],
            "limit": 50,
            "follow_up_type": "new",
        }


def create_extraction_prompt_stronger(
    question: str,
    domain: str,
    context: dict[str, Any] | None = None,
) -> list[LLMMessage]:
    """Create a stronger prompt for retry attempts (Level 1 fallback).

    This adds more explicit instructions and examples.
    """
    available_fields = AVAILABLE_FIELDS_BY_DOMAIN.get(domain, [])

    stronger_system = """You are a precise query parameter extractor. 

CRITICAL: You must output ONLY valid JSON. No explanations, no markdown, no text before or after.

Example valid output:
{"filters": [{"field": "skill", "operator": "contains", "value": "python"}], "sort": [], "limit": 50, "follow_up_type": "new"}

If you cannot extract any filters, output:
{"filters": [], "sort": [], "limit": 50, "follow_up_type": "new"}"""

    stronger_user = f"""Extract filters from this question about {domain} domain.

Available fields: {", ".join(available_fields)}

Question: {question}

Output ONLY JSON."""

    return [
        LLMMessage(role="system", content=stronger_system),
        LLMMessage(role="user", content=stronger_user),
    ]


# =============================================================================
# LangGraph Node Wrapper
# =============================================================================


async def llm_extraction_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph node for LLM structured extraction.

    Called after followup_detection to extract filters using LLM.

    Args:
        state: Current GraphState

    Returns:
        Dict with extracted filters, sort, limit, follow_up_type
    """
    question = state.get("question", "")
    domain = state.get("domain", "resource")

    # Build context from last_turn_context
    context = None
    last_turn = state.get("last_turn_context")
    if last_turn:
        context = {
            "last_filters": last_turn.get("filters", []),
            "last_intent": last_turn.get("intent"),
        }

    # Extract structured parameters
    extracted = await extract_structured(question, domain, context)

    # Transform filters to match FilterClause schema
    filters = extracted.get("filters", [])
    transformed_filters = []

    for f in filters:
        # Convert from LLM format to FilterClause format
        # LLM: {"field": "skill", "operator": "contains", "value": "python"}
        # FilterClause: {"field": "skill", "op": "eq", "values": ["python"]}
        op = f.get("operator", "eq")
        # Map "contains" to "eq" for now since FilterClause doesn't support contains
        if op == "contains":
            op = "eq"

        transformed_filters.append(
            {
                "field": f.get("field"),
                "op": op,  # Use "op" not "operator"
                "values": [f.get("value")] if f.get("value") else [],  # Wrap in list
            }
        )

    # ── Log LLM extracted filters ────────────────────────────────────────
    filter_summary = (
        ", ".join(f"{f.get('field')}:{f.get('op')}:{f.get('values')}" for f in transformed_filters)
        if transformed_filters
        else "none"
    )
    logger.info(
        "llm_extraction: domain=%s intent=%s filters=[%s]",
        domain,
        state.get("intent", "unknown"),
        filter_summary,
    )

    logger.info(
        "LLM extraction node completed: domain=%s, filters=%d, follow_up=%s",
        domain,
        len(transformed_filters),
        extracted.get("follow_up_type", "new"),
    )

    return {
        "filters": transformed_filters,
        "sort": extracted.get("sort", []),
        "limit": extracted.get("limit", 50),
        "follow_up_type": extracted.get("follow_up_type", "new"),
    }
