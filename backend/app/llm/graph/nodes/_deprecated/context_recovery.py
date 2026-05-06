"""Context Recovery — Level 3 fallback that infers filters from question tokens.

This module implements Level 3 of the fallback ladder: inferring filters from
question tokens when LLM extraction fails.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

#: Known skill patterns for heuristic extraction
KNOWN_SKILLS = {
    "python",
    "java",
    "javascript",
    "js",
    "typescript",
    "ts",
    "c#",
    "c++",
    "csharp",
    "cpp",
    "go",
    "golang",
    "rust",
    "ruby",
    "php",
    "swift",
    "kotlin",
    "scala",
    "perl",
    "r",
    "react",
    "angular",
    "vue",
    "svelte",
    "nextjs",
    "nuxt",
    "node",
    "nodejs",
    "express",
    "django",
    "flask",
    "fastapi",
    "spring",
    "rails",
    "laravel",
    "aspnet",
    ".net",
    "sql",
    "mysql",
    "postgresql",
    "postgres",
    "mongodb",
    "redis",
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "k8s",
    "graphql",
    "rest",
    "grpc",
    "machine learning",
    "ml",
    "ai",
    "data science",
    "devops",
    "ci/cd",
    "jenkins",
    "gitlab",
    "github actions",
}

#: Known status patterns
KNOWN_STATUS = {
    "active",
    "inactive",
    "pending",
    "approved",
    "rejected",
    "benched",
    "allocated",
    "assigned",
    "completed",
    "ongoing",
    "closed",
    "cancelled",
    "on hold",
}

#: Known date patterns
KNOWN_DATE_PATTERNS = {
    r"this month": "current_month",
    r"last month": "previous_month",
    r"next month": "next_month",
    r"this week": "current_week",
    r"last week": "previous_week",
    r"today": "today",
    r"yesterday": "yesterday",
    r"q[1-4]\s*\d{4}": "quarter_year",
    r"\d{4}-\d{2}-\d{2}": "specific_date",
    r"last\s+\d+\s+days": "last_n_days",
    r"last\s+\d+\s+months": "last_n_months",
}

#: Known numeric thresholds
KNOWN_THRESHOLDS = {
    r"more than (\d+)": "gt",
    r"over (\d+)": "gt",
    r"above (\d+)": "gt",
    r"at least (\d+)": "gte",
    r"minimum (\d+)": "gte",
    r"less than (\d+)": "lt",
    r"under (\d+)": "lt",
    r"below (\d+)": "lt",
    r"maximum (\d+)": "lte",
    r"(\d+)\+": "gte",
}


def recover_from_context(
    question: str,
    last_filters: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Infer filters from question tokens.

    Args:
        question: The user's question
        last_filters: Filters from prior turns (for context)

    Returns:
        List of inferred filters
    """
    if not question:
        return []

    question_lower = question.lower()
    inferred_filters: list[dict[str, Any]] = []

    # Extract skill filters
    skill_filters = _extract_skills(question_lower)
    inferred_filters.extend(skill_filters)

    # Extract status filters
    status_filters = _extract_status(question_lower)
    inferred_filters.extend(status_filters)

    # Extract date filters
    date_filters = _extract_dates(question_lower)
    inferred_filters.extend(date_filters)

    # Extract numeric thresholds
    threshold_filters = _extract_thresholds(question_lower)
    inferred_filters.extend(threshold_filters)

    logger.info("Context recovery: inferred %d filters from question", len(inferred_filters))

    return inferred_filters


def _extract_skills(question: str) -> list[dict[str, Any]]:
    """Extract skill filters from question."""
    filters = []

    for skill in KNOWN_SKILLS:
        if skill in question:
            filters.append(
                {
                    "field": "skill",
                    "operator": "contains",
                    "value": skill,
                    "_source": "context_recovery",
                }
            )
            break  # Only add one skill filter

    return filters


def _extract_status(question: str) -> list[dict[str, Any]]:
    """Extract status filters from question."""
    filters = []

    for status in KNOWN_STATUS:
        if status in question:
            filters.append(
                {
                    "field": "status",
                    "operator": "eq",
                    "value": status,
                    "_source": "context_recovery",
                }
            )
            break  # Only add one status filter

    return filters


def _extract_dates(question: str) -> list[dict[str, Any]]:
    """Extract date filters from question."""
    filters = []

    for pattern, date_type in KNOWN_DATE_PATTERNS.items():
        if re.search(pattern, question):
            # Extract date values if present
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", question)
            if date_match:
                filters.append(
                    {
                        "field": "start_date",
                        "operator": "eq",
                        "value": date_match.group(1),
                        "_source": "context_recovery",
                    }
                )
            else:
                # Just mark that date filtering is needed
                filters.append(
                    {
                        "field": "start_date",
                        "operator": "eq",
                        "value": date_type,
                        "_source": "context_recovery",
                    }
                )
            break

    return filters


def _extract_thresholds(question: str) -> list[dict[str, Any]]:
    """Extract numeric threshold filters from question."""
    filters = []

    # Map threshold patterns to fields
    threshold_fields = {
        "more than": "min_allocation",
        "over": "min_allocation",
        "above": "min_allocation",
        "at least": "min_hours",
        "minimum": "min_hours",
        "less than": "min_budget",
        "under": "min_budget",
        "below": "min_budget",
        "maximum": "min_duration",
    }

    for pattern, field in threshold_fields.items():
        if pattern in question:
            # Extract the number
            match = re.search(rf"{pattern}\s+(\d+)", question)
            if match:
                value = match.group(1)
                operator = (
                    "gte"
                    if "at least" in pattern or "minimum" in pattern or "+" in question
                    else "gt"
                )

                filters.append(
                    {
                        "field": field,
                        "operator": operator,
                        "value": value,
                        "_source": "context_recovery",
                    }
                )
                break

    return filters


def get_context_keywords() -> dict[str, set]:
    """Get all known context keywords (for debugging/analysis)."""
    return {
        "skills": KNOWN_SKILLS,
        "status": KNOWN_STATUS,
        "date_patterns": set(KNOWN_DATE_PATTERNS.keys()),
        "thresholds": set(KNOWN_THRESHOLDS.keys()),
    }


def add_known_pattern(category: str, pattern: str) -> None:
    """Add a new known pattern to the recovery system.

    Args:
        category: One of "skills", "status", "date_patterns", "thresholds"
        pattern: The pattern to add
    """
    global KNOWN_SKILLS, KNOWN_STATUS, KNOWN_DATE_PATTERNS, KNOWN_THRESHOLDS

    if category == "skills":
        KNOWN_SKILLS.add(pattern.lower())
    elif category == "status":
        KNOWN_STATUS.add(pattern.lower())
    elif category == "date_patterns":
        KNOWN_DATE_PATTERNS[pattern] = pattern
    elif category == "thresholds":
        KNOWN_THRESHOLDS[pattern] = pattern
