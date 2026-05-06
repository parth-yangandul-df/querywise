"""Conflict Resolution — handles field-level conflict when merging filters across turns.

This module implements the PRD requirement:
- Same field → REPLACE (remove existing, add new)
- Different field → ADD (append new)
- All fields validated against FieldRegistry
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.llm.graph.nodes.field_registry import lookup_field

logger = logging.getLogger(__name__)


@dataclass
class MergeResult:
    """Result of merging filters."""

    filters: list[dict[str, Any]]  # Merged filters
    conflicts_resolved: int  # Number of conflicts resolved
    additions: int  # Number of new filters added
    replacements: int  # Number of filters replaced


def resolve_conflicts(
    new_filters: list[dict[str, Any]],
    existing_filters: list[dict[str, Any]],
    domain: str,
) -> MergeResult:
    """Resolve conflicts between new and existing filters.

    Args:
        new_filters: Filters from current extraction
        existing_filters: Filters from prior turns
        domain: The domain for field validation

    Returns:
        MergeResult with merged filters and resolution details
    """
    if not existing_filters:
        # No existing filters - just validate and add new
        validated = _validate_filters(new_filters, domain)
        return MergeResult(
            filters=validated,
            conflicts_resolved=0,
            additions=len(validated),
            replacements=0,
        )

    if not new_filters:
        # No new filters - keep existing
        return MergeResult(
            filters=existing_filters,
            conflicts_resolved=0,
            additions=0,
            replacements=0,
        )

    # Build a map of existing fields for quick lookup
    existing_field_map: dict[str, dict[str, Any]] = {}
    for f in existing_filters:
        field_name = f.get("field", "").lower()
        existing_field_map[field_name] = f

    # Track which existing fields are kept (not replaced)
    replaced_fields: set[str] = set()

    # Start with new filters, will add non-conflicting existing
    merged_filters: list[dict[str, Any]] = []

    for new_filter in new_filters:
        new_field = new_filter.get("field", "").lower()
        new_field_key = new_field

        if new_field_key in existing_field_map:
            # CONFLICT: Same field → REPLACE
            # Replace existing with new
            merged_filters.append(new_filter)
            replaced_fields.add(new_field_key)
            logger.debug(
                "Conflict resolved: REPLACE field '%s' with new value '%s'",
                new_field,
                new_filter.get("value"),
            )
        else:
            # NO CONFLICT: New field → ADD
            merged_filters.append(new_filter)

    # Add existing filters that weren't replaced
    for existing_field, existing_filter in existing_field_map.items():
        if existing_field not in replaced_fields:
            merged_filters.append(existing_filter)

    # Validate all merged filters against FieldRegistry
    validated = _validate_filters(merged_filters, domain)

    # Count resolved conflicts
    conflicts_resolved = len(replaced_fields)
    additions = len(new_filters) - conflicts_resolved
    replacements = conflicts_resolved

    logger.info(
        "Conflict resolution: %d conflicts resolved, %d additions, %d replacements, "
        "total filters=%d",
        conflicts_resolved,
        additions,
        replacements,
        len(validated),
    )

    return MergeResult(
        filters=validated,
        conflicts_resolved=conflicts_resolved,
        additions=additions,
        replacements=replacements,
    )


def _validate_filters(
    filters: list[dict[str, Any]],
    domain: str,
) -> list[dict[str, Any]]:
    """Validate filters against FieldRegistry.

    Args:
        filters: List of filter dicts
        domain: Domain for validation

    Returns:
        List of valid filters (invalid fields removed)
    """
    valid_filters = []

    for f in filters:
        field_name = f.get("field", "")
        if not field_name:
            continue

        # Normalize to lowercase for lookup
        field_name_lower = field_name.lower()

        # Check if field exists in registry for this domain
        field_config = lookup_field(field_name_lower, domain)
        if field_config is None:
            logger.warning("Dropping invalid field '%s' for domain '%s'", field_name, domain)
            continue

        valid_filters.append(f)

    return valid_filters


def normalize_filter_value(
    value: str,
    sql_type: str,
) -> str:
    """Normalize filter value based on SQL type.

    Args:
        value: Raw filter value
        sql_type: SQL type from FieldConfig

    Returns:
        Normalized value
    """
    if sql_type == "text":
        # Trim whitespace for text fields
        return value.strip()
    elif sql_type in ("date", "numeric", "boolean"):
        # No normalization needed for structured types
        return value
    else:
        return value.strip()


def detect_field_overlap(
    filters_a: list[dict[str, Any]],
    filters_b: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Detect overlapping fields between two filter lists.

    Args:
        filters_a: First list of filters
        filters_b: Second list of filters

    Returns:
        List of (field, field) tuples for overlapping fields
    """
    fields_a = {f.get("field", "").lower() for f in filters_a if f.get("field")}
    fields_b = {f.get("field", "").lower() for f in filters_b if f.get("field")}

    overlaps = []
    for field_a in fields_a:
        if field_a in fields_b:
            overlaps.append((field_a, field_a))

    return overlaps
