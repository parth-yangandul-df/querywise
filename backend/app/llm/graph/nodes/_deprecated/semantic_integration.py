"""Semantic Integration — bridges semantic layer with hybrid pipeline.

This module provides:
- get_field_hints: Returns available fields from glossary for a domain
- normalize_filter_value: Normalizes user filter values using the value map
- Integration helpers for the hybrid query pipeline
"""

from typing import Any

# Lazy import to avoid circular dependencies
_semantic_resolver = None


def _get_semantic_resolver():
    """Lazy load semantic resolver module."""
    global _semantic_resolver
    if _semantic_resolver is None:
        from app.llm.graph.nodes import semantic_resolver

        _semantic_resolver = semantic_resolver
    return _semantic_resolver


def get_field_hints(domain: str) -> list[str]:
    """Get available field names from glossary for a domain.

    Args:
        domain: The domain (resource, client, project, timesheet, user_self)

    Returns:
        List of available field names from glossary terms
    """
    # This is a synchronous wrapper - returns cached hints
    # In practice, glossary hints are loaded at startup and cached
    sr = _get_semantic_resolver()

    # Return field names based on domain
    # These are the canonical fields from FieldRegistry
    domain_fields = {
        "resource": [
            "EMPID",
            "ResourceName",
            "designation",
            "PA_Skills.Name",
            "status",
            "email",
            "phone",
        ],
        "client": [
            "ClientCode",
            "ClientName",
            "Industry",
            "status",
        ],
        "project": [
            "ProjectCode",
            "ProjectName",
            "ProjectType",
            "status",
            "StartDate",
            "EndDate",
        ],
        "timesheet": [
            "ResourceName",
            "ProjectName",
            "WeekStartDate",
            "Hours",
            "IsApproved",
            "IsRejected",
        ],
        "user_self": [
            "ResourceName",
            "email",
            "designation",
            "status",
        ],
    }

    return domain_fields.get(domain, [])


def normalize_filter_value(
    user_value: str,
    field: str,
    value_map: dict[str, dict[str, str]] | None = None,
) -> str:
    """Normalize a user-provided filter value using the value map.

    Args:
        user_value: The user-provided value (e.g., "backend")
        field: The field name (e.g., "designation")
        value_map: Optional pre-loaded value map. If None, uses cached map.

    Returns:
        Normalized DB value (e.g., "Backend Developer")
    """
    sr = _get_semantic_resolver()

    # Use provided value_map or get cached one
    if value_map is None:
        try:
            value_map = sr.get_cached_value_map()
        except Exception:
            # Graceful degradation - return original value
            return user_value

    # Use semantic_resolver's normalize_value function
    try:
        return sr.normalize_value(user_value, field, value_map)
    except Exception:
        # Graceful degradation - return original value
        return user_value


def normalize_values_batch(
    filters: list[dict[str, Any]],
    value_map: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Normalize a batch of filter dicts.

    Args:
        filters: List of filter dictionaries
        value_map: Optional pre-loaded value map

    Returns:
        List of filters with normalized values
    """
    if not filters:
        return filters

    sr = _get_semantic_resolver()

    if value_map is None:
        try:
            value_map = sr.get_cached_value_map()
        except Exception:
            return filters

    try:
        return sr.normalize_values_batch(filters, value_map)
    except Exception:
        return filters


async def get_glossary_for_domain(
    db: Any,
    connection_id: str,
    domain: str,
) -> list[dict[str, Any]]:
    """Get full glossary entries for a domain (async version).

    Args:
        db: Database session
        connection_id: Connection identifier
        domain: Domain name

    Returns:
        List of glossary term dictionaries
    """
    sr = _get_semantic_resolver()

    try:
        return await sr.resolve_glossary_hints(db, connection_id, domain)
    except Exception:
        return []


def validate_field_mapping(
    user_field: str,
    domain: str,
    value_map: dict[str, dict[str, str]] | None = None,
) -> str | None:
    """Validate if a user-provided field name maps to a canonical field.

    Args:
        user_field: User-provided field name (e.g., "skill", "tech")
        domain: Domain context
        value_map: Optional value map

    Returns:
        Canonical field name if valid, None otherwise
    """
    # Common user term -> canonical field mappings
    field_mappings = {
        "skill": "PA_Skills.Name",
        "skills": "PA_Skills.Name",
        "tech": "PA_Skills.Name",
        "technology": "PA_Skills.Name",
        "technology skills": "PA_Skills.Name",
        "empid": "EMPID",
        "employee id": "EMPID",
        "name": "ResourceName",
        "resource name": "ResourceName",
        "designation": "designation",
        "role": "designation",
        "job title": "designation",
        "status": "status",
        "client": "ClientName",
        "project": "ProjectName",
        "week": "WeekStartDate",
        "hours": "Hours",
    }

    normalized = user_field.lower().strip()
    return field_mappings.get(normalized)
