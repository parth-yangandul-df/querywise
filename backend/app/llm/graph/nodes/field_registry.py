"""FieldRegistry — filterable fields and status mappings used by the semantic layer.

This module remains a runtime dependency for semantic prompt assembly,
semantic value normalization, and startup validation even though the old
deterministic routing pipeline has been removed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class StartupIntegrityError(Exception):
    """Raised when the field registry is incomplete relative to live intents."""


@dataclass(frozen=True)
class FieldConfig:
    """Configuration for a single filterable field."""

    field_name: str
    column_name: str
    multi_value: bool
    sql_type: str
    domains: list[str]
    aliases: list[str] = field(default_factory=list)
    example_values: list[str] = field(default_factory=list)
    extraction_hints: list[str] = field(default_factory=list)
    isactive_column: str | None = None
    status_map: dict[str, dict[str, int]] = field(default_factory=dict)
    table_alias: str | None = None


DOMAIN_STATUS_IDS: dict[str, dict[str, int]] = {
    "client": {
        "Active": 2,
        "Inactive": 1,
        "Closed": 12,
    },
    "project": {
        "Active": 4,
        "Inactive": 3,
        "On hold": 5,
        "Others": 6,
        "Closed": 13,
    },
    "resource": {
        "Active": 8,
        "Inactive": 7,
    },
}


STATUS_ALIASES: dict[str, str] = {
    "close": "Closed",
    "closed": "Closed",
    "on-hold": "On hold",
    "onhold": "On hold",
    "on hold": "On hold",
    "active": "Active",
    "inactive": "Inactive",
    "others": "Others",
}


FIELD_REGISTRY: dict[str, FieldConfig] = {
    "skill": FieldConfig(
        field_name="skill",
        column_name="Name",
        multi_value=True,
        sql_type="text",
        domains=["resource"],
        aliases=["skill_filter"],
        example_values=["Python", "Java", "React", "SQL", "Angular", ".NET", "NodeJS"],
        extraction_hints=["knows", "experienced", "proficient", "skills", "technology", "tech"],
    ),
    "resource_name": FieldConfig(
        field_name="resource_name",
        column_name="ResourceName",
        multi_value=False,
        sql_type="text",
        domains=["resource", "project", "timesheet"],
        aliases=["employee_name", "person", "resource"],
        example_values=["John Doe", "Harshal Yeole", "Jane Smith"],
        extraction_hints=["of", "skills of", "show me", "assigned to", "for"],
        table_alias="r",
    ),
    "designation": FieldConfig(
        field_name="designation",
        column_name="Designation",
        multi_value=False,
        sql_type="text",
        domains=["resource"],
        example_values=["Software Engineer", "Senior Developer", "Tech Lead", "Manager"],
        extraction_hints=["working as", "role", "designation", "position"],
    ),
    "tech_category": FieldConfig(
        field_name="tech_category",
        column_name="TechCategoryName",
        multi_value=False,
        sql_type="text",
        domains=["resource", "project"],
        aliases=["category"],
        example_values=["Java", "Microsoft", "Open Source", "Data"],
        extraction_hints=["category", "tech category", "technology stack"],
    ),
    "role": FieldConfig(
        field_name="role",
        column_name="Role",
        multi_value=False,
        sql_type="text",
        domains=["resource", "project"],
        example_values=["Developer", "Tester", "Architect", "Lead"],
        extraction_hints=["role", "as", "working as"],
    ),
    "start_date": FieldConfig(
        field_name="start_date",
        column_name="StartDate",
        multi_value=False,
        sql_type="date",
        domains=["resource", "client", "project", "timesheet", "user_self"],
    ),
    "end_date": FieldConfig(
        field_name="end_date",
        column_name="EndDate",
        multi_value=False,
        sql_type="date",
        domains=["resource", "client", "project", "timesheet", "user_self"],
    ),
    "billable": FieldConfig(
        field_name="billable",
        column_name="Billable",
        multi_value=False,
        sql_type="boolean",
        domains=["resource", "project"],
    ),
    "min_allocation": FieldConfig(
        field_name="min_allocation",
        column_name="PercentageAllocation",
        multi_value=False,
        sql_type="numeric",
        domains=["resource", "project", "user_self"],
    ),
    "skill_name": FieldConfig(
        field_name="skill_name",
        column_name="Name",
        multi_value=False,
        sql_type="text",
        domains=["resource", "user_self"],
    ),
    "min_experience": FieldConfig(
        field_name="min_experience",
        column_name="SkillExperience",
        multi_value=False,
        sql_type="numeric",
        domains=["resource", "user_self"],
    ),
    "client_name": FieldConfig(
        field_name="client_name",
        column_name="ClientName",
        multi_value=False,
        sql_type="text",
        domains=["client", "project"],
        aliases=["account_name"],
        example_values=["Google", "Microsoft", "Amazon", "Apple"],
        extraction_hints=["for client", "projects for", "client"],
    ),
    "country_id": FieldConfig(
        field_name="country_id",
        column_name="CountryId",
        multi_value=False,
        sql_type="text",
        domains=["client"],
    ),
    "project_name": FieldConfig(
        field_name="project_name",
        column_name="ProjectName",
        multi_value=False,
        sql_type="text",
        domains=["client", "project", "user_self"],
        example_values=["Project Alpha", "Migration Project"],
        extraction_hints=["project", "named"],
    ),
    "status": FieldConfig(
        field_name="status",
        column_name="StatusId",
        multi_value=False,
        sql_type="numeric",
        domains=["client", "project", "resource"],
        example_values=["Active", "Inactive", "Closed", "On hold", "Others", "Completed"],
        extraction_hints=["status", "is", "state"],
        isactive_column="IsActive",
        status_map=DOMAIN_STATUS_IDS,
        table_alias="c",
    ),
    "min_budget": FieldConfig(
        field_name="min_budget",
        column_name="Budget",
        multi_value=False,
        sql_type="numeric",
        domains=["project"],
    ),
    "min_utilization": FieldConfig(
        field_name="min_utilization",
        column_name="BudgetUtilized",
        multi_value=False,
        sql_type="numeric",
        domains=["project"],
    ),
    "client_id": FieldConfig(
        field_name="client_id",
        column_name="ClientId",
        multi_value=False,
        sql_type="numeric",
        domains=["project"],
    ),
    "min_duration": FieldConfig(
        field_name="min_duration",
        column_name="DurationDays",
        multi_value=False,
        sql_type="numeric",
        domains=["project"],
    ),
    "days_overdue": FieldConfig(
        field_name="days_overdue",
        column_name="EndDate",
        multi_value=False,
        sql_type="numeric",
        domains=["project"],
    ),
    "min_hours": FieldConfig(
        field_name="min_hours",
        column_name="Hours",
        multi_value=False,
        sql_type="numeric",
        domains=["timesheet", "user_self"],
    ),
    "description": FieldConfig(
        field_name="description",
        column_name="Description",
        multi_value=False,
        sql_type="text",
        domains=["client", "timesheet"],
        example_values=["Client description", "Acme Corp partnership"],
        extraction_hints=["description", "about", "details"],
    ),
    "category": FieldConfig(
        field_name="category",
        column_name="Category",
        multi_value=False,
        sql_type="text",
        domains=["user_self"],
    ),
}


FIELD_REGISTRY_BY_DOMAIN: dict[str, dict[str, FieldConfig]] = {}
for field_config in FIELD_REGISTRY.values():
    for domain in field_config.domains:
        FIELD_REGISTRY_BY_DOMAIN.setdefault(domain, {})[field_config.field_name] = field_config


def lookup_field(field_name: str, domain: str) -> FieldConfig | None:
    """Look up a field config by canonical field name and domain."""
    return FIELD_REGISTRY_BY_DOMAIN.get(domain, {}).get(field_name)


def resolve_alias(param_key: str, domain: str) -> str | None:
    """Resolve a param key or alias to a canonical field name for the domain."""
    domain_fields = FIELD_REGISTRY_BY_DOMAIN.get(domain, {})
    if param_key in domain_fields:
        return param_key

    for field_config in domain_fields.values():
        if param_key in field_config.aliases:
            return field_config.field_name

    return None


def validate_registry_completeness() -> None:
    """Assert that every live intent domain has at least one registered field."""
    from app.llm.graph.intent_catalog import INTENT_CATALOG

    catalog_domains = {entry.domain for entry in INTENT_CATALOG}
    for domain in catalog_domains:
        fields = FIELD_REGISTRY_BY_DOMAIN.get(domain, {})
        if not fields:
            raise StartupIntegrityError(
                f"FieldRegistry is incomplete: domain '{domain}' has no registered fields "
                "but appears in INTENT_CATALOG."
            )
        logger.debug("FieldRegistry domain '%s' OK — %d fields registered", domain, len(fields))
