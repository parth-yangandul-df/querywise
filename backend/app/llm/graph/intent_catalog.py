"""Runtime intent catalog used by startup embedding and registry validation.

The agentic query pipeline no longer routes through deterministic intent handlers,
but other startup paths still rely on a lightweight catalog of supported domains.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntentCatalogEntry:
    domain: str
    intent: str
    description: str
    examples: tuple[str, ...] = ()


INTENT_CATALOG: tuple[IntentCatalogEntry, ...] = (
    IntentCatalogEntry(
        domain="resource",
        intent="resource_lookup",
        description="Find resources by skills, designation, availability, or status.",
        examples=(
            "show active Python developers",
            "who knows React in Mumbai",
        ),
    ),
    IntentCatalogEntry(
        domain="project",
        intent="project_lookup",
        description="Find projects by client, status, staffing, allocation, or budget.",
        examples=(
            "show active projects for Google",
            "which projects need Python resources",
        ),
    ),
    IntentCatalogEntry(
        domain="client",
        intent="client_lookup",
        description="Find clients by status, geography, or associated work.",
        examples=(
            "list active clients",
            "show closed clients in India",
        ),
    ),
    IntentCatalogEntry(
        domain="timesheet",
        intent="timesheet_lookup",
        description="Inspect timesheet hours, work logs, and overdue effort.",
        examples=(
            "show timesheets over 40 hours",
            "who logged hours on Project Alpha",
        ),
    ),
    IntentCatalogEntry(
        domain="user_self",
        intent="self_lookup",
        description="Answer user-centric questions about their own assignments, skills, or hours.",
        examples=(
            "what projects am I on",
            "show my timesheet hours this week",
        ),
    ),
)


async def ensure_catalog_embedded() -> None:
    """Compatibility shim for previous startup embedding behavior.

    The old deterministic pipeline pre-embedded catalog entries. The current
    backend can start without that work, so this is intentionally a no-op.
    """

    return None
