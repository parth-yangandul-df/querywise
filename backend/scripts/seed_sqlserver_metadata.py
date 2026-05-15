#!/usr/bin/env python3
"""
Seed semantic metadata for your Azure SQL Server connection into QueryWise.

This script populates the four layers of the semantic layer:
  1. Glossary  — business terms → definitions + SQL expressions
  2. Metrics   — named KPIs with SQL expressions and dimensions
  3. Dictionary — raw column values → human-readable labels
  4. Knowledge  — free-text business context documents

This script connects DIRECTLY to the PostgreSQL app DB using DATABASE_URL
from .env — it does NOT use the REST API.

Required .env vars:
    DATABASE_URL          — PostgreSQL connection string (e.g. postgresql+psycopg://...)
    SEED_CONNECTION_NAME  — Name of the SQL Server connection in QueryWise

Usage:
    # From the repo root, while docker compose is running:
    docker compose exec backend python scripts/seed_sqlserver_metadata.py

    # Or locally:
    pip install -e ".[dev]"
    python backend/scripts/seed_sqlserver_metadata.py

    # Edit .env to set SEED_CONNECTION_NAME

HOW TO FILL THIS IN:
    1. Run introspection in the UI (Connections → introspect icon) so your
       tables and columns are cached.
    2. Edit GLOSSARY_TERMS, METRICS, DICTIONARY_ENTRIES, and KNOWLEDGE_DOCS
       below to match your schema.
    3. Run this script — it is idempotent-safe (INSERT ... ON CONFLICT DO UPDATE).

DICTIONARY ENTRIES NOTE:
    Dictionary entries are keyed by (table_name, column_name). The table_name
    must match exactly what was introspected (case-sensitive). Run introspection
    first so cached_columns is populated.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path
from uuid import UUID

import psycopg
from dotenv import dotenv_values, find_dotenv

# =============================================================================
# 1. GLOSSARY TERMS
#    Business terms that map natural language to SQL concepts.
#
#    Fields:
#      term            (required) Short business term label
#      definition      (required) Human-readable explanation
#      sql_expression  (required) SQL snippet that implements this term
#      related_tables  (optional) List of table names this term touches
#      related_columns (optional) List of "table.column" strings
#      examples        (optional) List of example SQL queries
# =============================================================================
GLOSSARY_TERMS: list[dict] = [
    {
        "term": "Active Resource",
        "definition": "A resource who is currently active and part of the organization.",
        "sql_expression": "CASE WHEN Resource.IsActive = 1 AND Resource.StatusId IN (SELECT StatusId FROM Status WHERE StatusName = 'Active')",
        "related_tables": ["Resource", "Status"],
        "related_columns": ["Resource.IsActive", "Resource.StatusId", "Status.StatusId", "Status.StatusName"],
    },
    {
        "term": "Employee ID",
        "definition": "Unique identifier assigned to each employee within the organization.",
        "sql_expression": "Resource.EmployeeId",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.EmployeeId"],
    },
    {
        "term": "Resource Tenure (Months)",
        "definition": "Total duration of employment for a resource measured in months.",
        "sql_expression": "Resource.TenureInMonths",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.TenureInMonths"],
    },
    {
        "term": "Resource Tenure (Years)",
        "definition": "Total duration of employment for a resource measured in years.",
        "sql_expression": "Resource.TenureInYears",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.TenureInYears"],
    },
    {
        "term": "Reporting Manager",
        "definition": "The manager to whom the resource reports within the organization hierarchy.",
        "sql_expression": "Resource.ReportingTo",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.ReportingTo"],
    },
    {
        "term": "Primary Skill",
        "definition": "Main technical or functional skill of the resource.",
        "sql_expression": "Resource.Primaryskill",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.Primaryskill"],
    },
    {
        "term": "Secondary Skill",
        "definition": "Additional supporting skill set of the resource.",
        "sql_expression": "Resource.Secondaryskill",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.Secondaryskill"],
    },
    {
        "term": "skills",
        "definition": (
            "Skill data is spread across four tables: "
            "PA_Skills (master skill catalogue), "
            "PA_SubSkills (subskills nested under each skill), "
            "PA_ResourceSkills (bridge table — which skills and subskills each resource holds), "
            "and Resource.Primaryskill / Resource.Secondaryskill columns for each resource's "
            "declared primary and secondary skill. "
            "Always join PA_Skills and PA_SubSkills via PA_ResourceSkills when asking about "
            "skills, subskills, primary skills, or secondary skills."
        ),
        "sql_expression": (
            "JOIN PA_ResourceSkills rs ON r.ResourceId = rs.ResourceId "
            "JOIN PA_Skills s ON rs.SkillId = s.SkillId "
            "LEFT JOIN PA_SubSkills ss ON rs.SubSkillId = ss.SubSkillId"
        ),
        "related_tables": ["PA_Skills", "PA_SubSkills", "PA_ResourceSkills", "Resource"],
        "related_columns": [
            "PA_ResourceSkills.ResourceId",
            "PA_ResourceSkills.SkillId",
            "PA_ResourceSkills.SubSkillId",
            "PA_Skills.SkillId",
            "PA_Skills.Name",
            "PA_SubSkills.SubSkillId",
            "PA_SubSkills.Name",
            "PA_SubSkills.SkillId",
            "Resource.Primaryskill",
            "Resource.Secondaryskill",
        ],
    },
    {
        "term": "Date of Joining",
        "definition": "The date on which the resource joined the organization.",
        "sql_expression": "Resource.DateOfJoin",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.DateOfJoin"],
    },
    {
        "term": "Active Client",
        "definition": "A client that is currently active and engaged in business operations.",
        "sql_expression": "CASE WHEN Client.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["Client"],
        "related_columns": ["Client.IsActive"],
    },
    {
        "term": "Client Billing Rate (Hourly)",
        "definition": "Hourly rate charged to the client for services rendered.",
        "sql_expression": "Client.HourlyBillingRate",
        "related_tables": ["Client"],
        "related_columns": ["Client.HourlyBillingRate"],
    },
    {
        "term": "Agreement Value",
        "definition": "Total monetary value agreed upon in the client contract.",
        "sql_expression": "Client.AgreementValue",
        "related_tables": ["Client"],
        "related_columns": ["Client.AgreementValue"],
    },
    {
        "term": "Agreement Duration",
        "definition": "Duration of the contractual agreement with the client.",
        "sql_expression": "Client.AgreementDuration",
        "related_tables": ["Client"],
        "related_columns": ["Client.AgreementDuration"],
    },
    {
        "term": "Business Unit",
        "definition": "An organizational division responsible for a specific business function or service line.",
        "sql_expression": "BusinessUnit.BusinessUnitId",
        "related_tables": ["BusinessUnit"],
        "related_columns": ["BusinessUnit.BusinessUnitId"],
    },
    {
        "term": "Active Business Unit",
        "definition": "A business unit that its currently operational and active.",
        "sql_expression": "CASE WHEN BusinessUnit.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["BusinessUnit"],
        "related_columns": ["BusinessUnit.IsActive"],
    },

    {
        "term": "Client Stakeholder",
        "definition": "An individual associated with a client organization who is involved in communication, decision-making, or project oversight.",
        "sql_expression": "ClientStakeholder.ClientStakeholderId",
        "related_tables": ["ClientStakeholder"],
        "related_columns": ["ClientStakeholder.ClientStakeholderId"],
    },
    {
        "term": "Active Client Stakeholder",
        "definition": "A stakeholder who is currently active and associated with a client.",
        "sql_expression": "CASE WHEN ClientStakeholder.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["ClientStakeholder"],
        "related_columns": ["ClientStakeholder.IsActive"],
    },
    {
        "term": "Client Stakeholder Contact",
        "definition": "Contact information (email and phone) of a stakeholder representing a client.",
        "sql_expression": "ClientStakeholder.EmailId",
        "related_tables": ["ClientStakeholder"],
        "related_columns": ["ClientStakeholder.EmailId", "ClientStakeholder.ContactNumber"],
    },
    {
        "term": "Designated Role",
        "definition": "A formally assigned role that defines responsibilities and function of a resource within the organization.",
        "sql_expression": "DesignatedRole.DesignatedRoleId",
        "related_tables": ["DesignatedRole"],
        "related_columns": ["DesignatedRole.DesignatedRoleId"],
    },
    {
        "term": "Active Designated Role",
        "definition": "A designated role that is currently active and assigned within the organization.",
        "sql_expression": "CASE WHEN DesignatedRole.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["DesignatedRole"],
        "related_columns": ["DesignatedRole.IsActive"],
    },
    {
        "term": "Designation",
        "definition": "Job title assigned to a resource indicating their position in the organizational hierarchy.",
        "sql_expression": "Designation.DesignationId",
        "related_tables": ["Designation"],
        "related_columns": ["Designation.DesignationId"],
    },
    {
        "term": "Timesheet Applicable Designation",
        "definition": "A designation for which timesheet (EOD logging) is mandatory.",
        "sql_expression": "CASE WHEN Designation.IsTimesheetApplies = 1 THEN 1 ELSE 0 END",
        "related_tables": ["Designation"],
        "related_columns": ["Designation.IsTimesheetApplies"],
    },
    {
        "term": "Active Designation",
        "definition": "A designation that is currently active in the system.",
        "sql_expression": "CASE WHEN Designation.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["Designation"],
        "related_columns": ["Designation.IsActive"],
    },
    {
        "term": "Active Project",
        "definition": "A project that is currently active and ongoing.",
        "sql_expression": "CASE WHEN Project.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["Project"],
        "related_columns": ["Project.IsActive"],
    },
    {
        "term": "Project Duration",
        "definition": "Planned duration of the project.",
        "sql_expression": "Project.Duration",
        "related_tables": ["Project"],
        "related_columns": ["Project.Duration"],
    },
    {
        "term": "Project Billing Rate (Hourly)",
        "definition": "Hourly billing rate defined for the project.",
        "sql_expression": "Project.HourlyBillingRate",
        "related_tables": ["Project"],
        "related_columns": ["Project.HourlyBillingRate"],
    },
    {
        "term": "Project Start Date",
        "definition": "Planned start date of the project.",
        "sql_expression": "Project.StartDate",
        "related_tables": ["Project"],
        "related_columns": ["Project.StartDate"],
    },
    {
        "term": "Project End Date",
        "definition": "Planned end date of the project.",
        "sql_expression": "Project.EndDate",
        "related_tables": ["Project"],
        "related_columns": ["Project.EndDate"],
    },
    {
        "term": "Actual Project Start Date",
        "definition": "Actual date when project execution began.",
        "sql_expression": "Project.ActualStartDate",
        "related_tables": ["Project"],
        "related_columns": ["Project.ActualStartDate"],
    },
    {
        "term": "Actual Project End Date",
        "definition": "Actual date when project execution completed.",
        "sql_expression": "Project.ActualEndDate",
        "related_tables": ["Project"],
        "related_columns": ["Project.ActualEndDate"],
    },
    {
        "term": "Project Resource Allocation",
        "definition": "Assignment of a resource to a project with defined allocation percentage and billing attributes.",
        "sql_expression": "ProjectResource.ProjectResourceId",
        "related_tables": ["ProjectResource"],
        "related_columns": ["ProjectResource.ProjectResourceId"],
    },
    {
        "term": "Billable Resource",
        "definition": "A resource whose work is billable to the client.",
        "sql_expression": "CASE WHEN ProjectResource.Billable = 1 THEN 1 ELSE 0 END",
        "related_tables": ["ProjectResource"],
        "related_columns": ["ProjectResource.Billable"],
    },
    {
        "term": "Shadow Resource",
        "definition": "A resource assigned for support or learning purposes and not directly billable.",
        "sql_expression": "CASE WHEN ProjectResource.Shadow = 1 AND ProjectResource.Billable = 0 AND Resource.IsReportingPerson = 0 THEN 1 ELSE 0 END",
        "related_tables": ["ProjectResource", "Resource"],
        "related_columns": ["ProjectResource.Shadow", "ProjectResource.Billable", "Resource.IsReportingPerson"],
    },
    {
        "term": "Resource Allocation Percentage",
        "definition": "Percentage of a resource's time allocated to a project.",
        "sql_expression": "ProjectResource.PercentageAllocation",
        "related_tables": ["ProjectResource"],
        "related_columns": ["ProjectResource.PercentageAllocation"],
    },
    {
        "term": "Bench Resource",
        "definition": "A resource not currently allocated to billable work.",
        "sql_expression": "CASE WHEN Project.ProjectName = 'DF-Bench' THEN 1 ELSE 0 END",
        "related_tables": ["Project"],
        "related_columns": ["Project.ProjectName"],
    },
    {
        "term": "Client Status",
        "definition": "Operational status of a client such as Active, Inactive, or Closed.",
        "sql_expression": "Status.StatusName",
        "related_tables": ["Status"],
        "related_columns": ["Status.StatusName", "Status.ReferenceId"],
        "examples": ["SELECT * FROM Status WHERE ReferenceId = 1"],
    },
    {
        "term": "Project Status",
        "definition": "Lifecycle status of a project such as Active, Inactive, On-hold, or Closed.",
        "sql_expression": "Status.StatusName",
        "related_tables": ["Status"],
        "related_columns": ["Status.StatusName", "Status.ReferenceId"],
        "examples": ["SELECT * FROM Status WHERE ReferenceId = 2"],
    },
    {
        "term": "Internal Project",
        "definition": "A project that is classified as internal within the organization.",
        "sql_expression": "CASE WHEN Client.ClientName = 'Internal Projects' THEN 1 ELSE 0 END",
        "related_tables": ["Client"],
        "related_columns": ["Client.ClientName"],
    },
    {
        "term": "Resource Status",
        "definition": "Availability status of a resource such as Active or Inactive.",
        "sql_expression": "Status.StatusName",
        "related_tables": ["Status"],
        "related_columns": ["Status.StatusName", "Status.ReferenceId"],
    },
    {
        "term": "Active Status",
        "definition": "A status value indicating an entity is currently active.",
        "sql_expression": "CASE WHEN Status.StatusName = 'Active' THEN 1 ELSE 0 END",
        "related_tables": ["Status"],
        "related_columns": ["Status.StatusName"],
    },
    {
        "term": "Technology Category",
        "definition": "A classification grouping technologies or skills into broader categories such as Frontend, Backend, Data Engineering, etc.",
        "sql_expression": "TechCatagory.TechCategoryId",
        "related_tables": ["TechCatagory"],
        "related_columns": ["TechCatagory.TechCategoryId"],
    },
    {
        "term": "Technology Category Name",
        "definition": "The name representing a specific technology category.",
        "sql_expression": "TechCatagory.TechCategoryName",
        "related_tables": ["TechCatagory"],
        "related_columns": ["TechCatagory.TechCategoryName"],
    },
    {
        "term": "Technology Function",
        "definition": "A functional grouping of technology roles such as Development, QA, DevOps, or Data.",
        "sql_expression": "TechFunction.FunctionId",
        "related_tables": ["TechFunction"],
        "related_columns": ["TechFunction.FunctionId"],
    },
    {
        "term": "Technology Function Name",
        "definition": "The name of the functional technology group.",
        "sql_expression": "TechFunction.FunctionName",
        "related_tables": ["TechFunction"],
        "related_columns": ["TechFunction.FunctionName"],
    },
    {
        "term": "Client Name",
        "definition": "The name of the client, stored in Client.ClientName. This should always be used when referring to a client.",
        "sql_expression": "Client.ClientName",
        "related_tables": ["Client"],
        "related_columns": ["Client.ClientName"],
    },
    {
        "term": "Business Unit Name",
        "definition": "The name of the business unit, stored in BusinessUnit.BusinessUnitName.",
        "sql_expression": "BusinessUnit.BusinessUnitName",
        "related_tables": ["BusinessUnit"],
        "related_columns": ["BusinessUnit.BusinessUnitName"],
    },
    {
        "term": "Resource Name",
        "definition": "The name of the employee or resource, stored in Resource.ResourceName.",
        "sql_expression": "Resource.ResourceName",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.ResourceName"],
    }
    # -------------------------------------------------------------------------
    # TODO: Replace these examples with terms from your domain.
    #
    # Example for a sales database:
    # {
    #     "term": "ARR",
    #     "definition": "Annual Recurring Revenue — annualised value of active subscriptions.",
    #     "sql_expression": "SUM(subscriptions.monthly_value) * 12",
    #     "related_tables": ["subscriptions"],
    #     "related_columns": ["subscriptions.monthly_value"],
    #     "examples": [
    #         "SELECT SUM(monthly_value) * 12 AS arr FROM subscriptions WHERE status = 'active'",
    #     ],
    # },
    # -------------------------------------------------------------------------
]


# =============================================================================
# 2. METRICS
#    Named, reusable KPI definitions. The LLM uses these to answer
#    "what is our X?" questions correctly without needing to figure out
#    the SQL from scratch.
#
#    Fields:
#      metric_name      (required) snake_case identifier
#      display_name     (required) Human-readable name shown in context
#      description      (optional) Longer explanation
#      sql_expression   (required) SQL fragment that computes the metric
#      aggregation_type (optional) "sum" | "avg" | "count" | "ratio" | "max" | "min"
#      related_tables   (optional) List of table names
#      dimensions       (optional) Columns typically used to GROUP BY this metric
#      filters          (optional) Dict of pre-applied WHERE conditions
# =============================================================================
METRICS: list[dict] = [
    {
        "metric_name": "total_resources",
        "display_name": "Total Resources",
        "description": "Total number of resources in the organization",
        "sql_expression": "COUNT(Resource.ResourceId)",
        "aggregation_type": "count",
        "related_tables": ["Resource"],
        "dimensions": ["BusinessUnitId", "DesignationId", "FunctionId"],
    },
    {
        "metric_name": "active_resources",
        "display_name": "Active Resources",
        "description": "Total number of currently active resources",
        "sql_expression": "SUM(CASE WHEN Resource.IsActive = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["Resource"],
        "dimensions": ["BusinessUnitId", "DesignationId"],
    },
    {
        "metric_name": "average_tenure_years",
        "display_name": "Average Tenure (Years)",
        "description": "Average tenure of resources in years",
        "sql_expression": "AVG(Resource.TenureInYears)",
        "aggregation_type": "avg",
        "related_tables": ["Resource"],
    },
    {
        "metric_name": "new_joiners",
        "display_name": "New Joiners",
        "description": "Number of resources who joined in a given period",
        "sql_expression": "COUNT(Resource.ResourceId) WHERE Resource.DateOfJoin >= DATEADD(MONTH, -3, GETDATE())",
        "aggregation_type": "count",
        "related_tables": ["Resource"],
        "dimensions": ["DateOfJoin"],
    },
    {
        "metric_name": "reporting_managers_count",
        "display_name": "Reporting Managers Count",
        "description": "Number of resources who are designated as reporting managers",
        "sql_expression": "SUM(CASE WHEN Resource.IsReportingPerson = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["Resource"],
    },
    {
        "metric_name": "total_clients",
        "display_name": "Total Clients",
        "description": "Total number of clients in the system",
        "sql_expression": "COUNT(Client.ClientId)",
        "aggregation_type": "count",
        "related_tables": ["Client"],
        "dimensions": ["BusinessUnitId", "DomainId"],
    },
    {
        "metric_name": "active_clients",
        "display_name": "Active Clients",
        "description": "Number of currently active clients",
        "sql_expression": "SUM(CASE WHEN Client.IsActive = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["Client"],
    },
    {
        "metric_name": "total_agreement_value",
        "display_name": "Total Agreement Value",
        "description": "Sum of all client agreement values",
        "sql_expression": "SUM(Client.AgreementValue)",
        "aggregation_type": "sum",
        "related_tables": ["Client"],
    },
    {
        "metric_name": "average_hourly_billing_rate",
        "display_name": "Average Hourly Billing Rate",
        "description": "Average hourly billing rate across clients",
        "sql_expression": "AVG(Client.HourlyBillingRate)",
        "aggregation_type": "avg",
        "related_tables": ["Client"],
    },
    {
        "metric_name": "total_business_units",
        "display_name": "Total Business Units",
        "description": "Total number of business units",
        "sql_expression": "COUNT(BusinessUnit.BusinessUnitId)",
        "aggregation_type": "count",
        "related_tables": ["BusinessUnit"],
    },
    {
        "metric_name": "active_business_units",
        "display_name": "Active Business Units",
        "description": "Number of active business units",
        "sql_expression": "SUM(CASE WHEN BusinessUnit.IsActive = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["BusinessUnit"],
    },
    {
        "metric_name": "total_client_stakeholders",
        "display_name": "Total Client Stakeholders",
        "description": "Total number of stakeholders across all clients",
        "sql_expression": "COUNT(ClientStakeholder.ClientStakeholderId)",
        "aggregation_type": "count",
        "related_tables": ["ClientStakeholder"],
        "dimensions": ["ClientId"],
    },
    {
        "metric_name": "active_client_stakeholders",
        "display_name": "Active Client Stakeholders",
        "description": "Number of active stakeholders",
        "sql_expression": "SUM(CASE WHEN ClientStakeholder.IsActive = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["ClientStakeholder"],
    },
    {
        "metric_name": "total_company_types",
        "display_name": "Total Company Types",
        "description": "Total number of company type classifications",
        "sql_expression": "COUNT(CompanyType.CompanyTypeId)",
        "aggregation_type": "count",
        "related_tables": ["CompanyType"],
    },
    {
        "metric_name": "total_designated_roles",
        "display_name": "Total Designated Roles",
        "description": "Total number of designated roles defined in the system",
        "sql_expression": "COUNT(DesignatedRole.DesignatedRoleId)",
        "aggregation_type": "count",
        "related_tables": ["DesignatedRole"],
    },
    {
        "metric_name": "total_designations",
        "display_name": "Total Designations",
        "description": "Total number of job designations",
        "sql_expression": "COUNT(Designation.DesignationId)",
        "aggregation_type": "count",
        "related_tables": ["Designation"],
    },
    {
        "metric_name": "timesheet_applicable_designations",
        "display_name": "Timesheet Applicable Designations",
        "description": "Number of designations where timesheet logging is required",
        "sql_expression": "SUM(CASE WHEN Designation.IsTimesheetApplies = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["Designation"],
    },
    {
        "metric_name": "total_projects",
        "display_name": "Total Projects",
        "description": "Total number of projects",
        "sql_expression": "COUNT(Project.ProjectId)",
        "aggregation_type": "count",
        "related_tables": ["Project"],
        "dimensions": ["ClientId", "BusinessUnitId"],
    },
    {
        "metric_name": "active_projects",
        "display_name": "Active Projects",
        "description": "Number of currently active projects",
        "sql_expression": "SUM(CASE WHEN Project.IsActive = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["Project"],
    },
    {
        "metric_name": "average_project_duration",
        "display_name": "Average Project Duration",
        "description": "Average duration of projects",
        "sql_expression": "AVG(CAST(Project.Duration AS FLOAT))",
        "aggregation_type": "avg",
        "related_tables": ["Project"],
    },
    {
        "metric_name": "average_project_billing_rate",
        "display_name": "Average Project Billing Rate",
        "description": "Average hourly billing rate across projects",
        "sql_expression": "AVG(Project.HourlyBillingRate)",
        "aggregation_type": "avg",
        "related_tables": ["Project"],
    },
    {
        "metric_name": "total_allocated_resources",
        "display_name": "Total Allocated Resources",
        "description": "Total number of resource allocations across projects",
        "sql_expression": "COUNT(ProjectResource.ProjectResourceId)",
        "aggregation_type": "count",
        "related_tables": ["ProjectResource"],
        "dimensions": ["ProjectId", "ClientId"],
    },
    {
        "metric_name": "billable_resources",
        "display_name": "Billable Resources",
        "description": "Number of resources assigned as billable",
        "sql_expression": "SUM(CASE WHEN ProjectResource.Billable = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["ProjectResource"],
    },
    {
        "metric_name": "average_allocation_percentage",
        "display_name": "Average Allocation Percentage",
        "description": "Average allocation percentage across resources",
        "sql_expression": "AVG(ProjectResource.PercentageAllocation)",
        "aggregation_type": "avg",
        "related_tables": ["ProjectResource"],
    },
    {
        "metric_name": "bench_resources",
        "display_name": "Bench Resources",
        "description": "Number of resources currently on bench",
        "sql_expression": "SUM(CASE WHEN Project.ProjectName = 'DF-Bench' THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["Project"],
    },
    {
        "metric_name": "active_status_count",
        "display_name": "Active Status Count",
        "description": "Number of active status entries across all categories",
        "sql_expression": "SUM(CASE WHEN Status.IsActive = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["Status"],
    },
    {
        "metric_name": "total_technology_categories",
        "display_name": "Total Technology Categories",
        "description": "Total number of defined technology categories",
        "sql_expression": "COUNT(TechCatagory.TechCategoryId)",
        "aggregation_type": "count",
        "related_tables": ["TechCatagory"],
    },
    {
        "metric_name": "active_technology_categories",
        "display_name": "Active Technology Categories",
        "description": "Number of active technology categories",
        "sql_expression": "SUM(CASE WHEN TechCatagory.IsActive = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["TechCatagory"],
    },
    {
        "metric_name": "total_technology_functions",
        "display_name": "Total Technology Functions",
        "description": "Total number of technology functions",
        "sql_expression": "COUNT(TechFunction.FunctionId)",
        "aggregation_type": "count",
        "related_tables": ["TechFunction"],
    },
    {
        "metric_name": "active_technology_functions",
        "display_name": "Active Technology Functions",
        "description": "Number of active technology functions",
        "sql_expression": "SUM(CASE WHEN TechFunction.IsActive = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["TechFunction"],
    },
    # -------------------------------------------------------------------------
    # TODO: Replace these examples with KPIs from your domain.
    #
    # Example for a sales database:
    # {
    #     "metric_name": "total_revenue",
    #     "display_name": "Total Revenue",
    #     "description": "Sum of all completed order amounts",
    #     "sql_expression": "SUM(orders.amount)",
    #     "aggregation_type": "sum",
    #     "related_tables": ["orders"],
    #     "dimensions": ["region", "product_category", "sales_rep"],
    # },
    # {
    #     "metric_name": "avg_order_value",
    #     "display_name": "Average Order Value",
    #     "description": "Mean value of completed orders",
    #     "sql_expression": "AVG(orders.amount)",
    #     "aggregation_type": "avg",
    #     "related_tables": ["orders"],
    #     "dimensions": ["region", "product_category"],
    # },
    # -------------------------------------------------------------------------
]


# =============================================================================
# 3. DICTIONARY ENTRIES
#    Value-level mappings: what does a coded DB value actually mean?
#    These are scoped to a specific (table_name, column_name) pair.
#
#    The table_name must match exactly the name introspected from your DB.
#    The column must already exist in the schema cache (introspect first).
#
#    Fields per entry:
#      raw_value     (required) The actual stored value, as a string (e.g. "1", "Y", "active")
#      display_value (required) Human-friendly label (e.g. "Active Customer")
#      description   (optional) Longer explanation of what this value means
#      sort_order    (optional) Integer; controls display order (default 0)
# =============================================================================
DICTIONARY_ENTRIES: dict[tuple[str, str], list[dict]] = {
    ("Resource", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Resource is not active",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Resource is active",
            "sort_order": 2,
        },
    ],
    ("Resource", "IsReportingPerson"): [
        {
            "raw_value": "0",
            "display_value": "Individual Contributor",
            "description": "Does not manage other resources",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Manager",
            "description": "Manages other resources",
            "sort_order": 2,
        },
    ],
    ("Client", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Client is not active",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Client is active",
            "sort_order": 2,
        },
    ],
    ("BusinessUnit", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Business unit is inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Business unit is active",
            "sort_order": 2,
        },
    ],
    ("ClientStakeholder", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Stakeholder is inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Stakeholder is active",
            "sort_order": 2,
        },
    ],
    ("CompanyType", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Company type is inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Company type is active",
            "sort_order": 2,
        },
    ],
    ("DesignatedRole", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Role is inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Role is active",
            "sort_order": 2,
        },
    ],
    ("Designation", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Designation is inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Designation is active",
            "sort_order": 2,
        },
    ],
    ("Designation", "IsTimesheetApplies"): [
        {
            "raw_value": "0",
            "display_value": "Not Required",
            "description": "Timesheet not required",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Required",
            "description": "Timesheet required",
            "sort_order": 2,
        },
    ],
    ("Project", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Project is inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Project is active",
            "sort_order": 2,
        },
    ],
    ("ProjectResource", "Billable"): [
        {
            "raw_value": "0",
            "display_value": "Non-Billable",
            "description": "Work is not billed to client",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Billable",
            "description": "Work is billed to client",
            "sort_order": 2,
        },
    ],
    ("ProjectResource", "Shadow"): [
        {
            "raw_value": "0",
            "display_value": "Primary Resource",
            "description": "Main assigned resource",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Shadow Resource",
            "description": "Support or backup resource",
            "sort_order": 2,
        },
    ],
    ("ProjectResource", "Bench"): [
        {
            "raw_value": "0",
            "display_value": "Allocated",
            "description": "Assigned to project",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Bench",
            "description": "Not assigned to billable work",
            "sort_order": 2,
        },
    ],
    ("ProjectResource", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Allocation inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Allocation active",
            "sort_order": 2,
        },
    ],
    ("Status", "StatusId"): [
        {
            "raw_value": "1",
            "display_value": "Client - Inactive",
            "description": "StatusId for Inactive status in the Client domain (ReferenceId=1)",
            "sort_order": 1,
        },
        {
            "raw_value": "2",
            "display_value": "Client - Active",
            "description": "StatusId for Active status in the Client domain (ReferenceId=1)",
            "sort_order": 2,
        },
        {
            "raw_value": "3",
            "display_value": "Project - Inactive",
            "description": "StatusId for Inactive status in the Project domain (ReferenceId=2)",
            "sort_order": 3,
        },
        {
            "raw_value": "4",
            "display_value": "Project - Active",
            "description": "StatusId for Active status in the Project domain (ReferenceId=2)",
            "sort_order": 4,
        },
        {
            "raw_value": "5",
            "display_value": "Project - On hold",
            "description": "StatusId for On hold status in the Project domain (ReferenceId=2)",
            "sort_order": 5,
        },
        {
            "raw_value": "6",
            "display_value": "Project - Others",
            "description": "StatusId for Others status in the Project domain (ReferenceId=2)",
            "sort_order": 6,
        },
        {
            "raw_value": "7",
            "display_value": "Resource - Inactive",
            "description": "StatusId for Inactive status in the Resource domain (ReferenceId=3)",
            "sort_order": 7,
        },
        {
            "raw_value": "8",
            "display_value": "Resource - Active",
            "description": "StatusId for Active status in the Resource domain (ReferenceId=3)",
            "sort_order": 8,
        },
        {
            "raw_value": "12",
            "display_value": "Client - Closed",
            "description": "StatusId for Closed status in the Client domain (ReferenceId=1)",
            "sort_order": 9,
        },
        {
            "raw_value": "13",
            "display_value": "Project - Closed",
            "description": "StatusId for Closed status in the Project domain (ReferenceId=2)",
            "sort_order": 10,
        },
    ],
    ("Status", "ReferenceId"): [
        {
            "raw_value": "1",
            "display_value": "Client Status",
            "description": "Status applicable to clients",
            "sort_order": 1,
        },
        {
            "raw_value": "2",
            "display_value": "Project Status",
            "description": "Status applicable to projects",
            "sort_order": 2,
        },
        {
            "raw_value": "3",
            "display_value": "Resource Status",
            "description": "Status applicable to resources",
            "sort_order": 3,
        },
        {
            "raw_value": "4",
            "display_value": "Email Queue Status",
            "description": "Status for email processing system",
            "sort_order": 4,
        },
    ],
    ("Status", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Status is not in use",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Status is currently usable",
            "sort_order": 2,
        },
    ],
    ("TechCatagory", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Technology category is inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Technology category is active",
            "sort_order": 2,
        },
    ],
    ("TechFunction", "IsActive"): [
        {
            "raw_value": "0",
            "display_value": "Inactive",
            "description": "Function is inactive",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Active",
            "description": "Function is active",
            "sort_order": 2,
        },
    ],
    # -------------------------------------------------------------------------
    # TODO: Replace with coded columns from your schema.
    #
    # Example:
    # ("Orders", "Status"): [
    #     {"raw_value": "0", "display_value": "Pending",   "description": "Order received, not yet processed", "sort_order": 1},
    #     {"raw_value": "1", "display_value": "Processing","description": "Order is being fulfilled",          "sort_order": 2},
    #     {"raw_value": "2", "display_value": "Shipped",   "description": "Dispatched to customer",           "sort_order": 3},
    #     {"raw_value": "3", "display_value": "Delivered", "description": "Confirmed delivered",              "sort_order": 4},
    #     {"raw_value": "4", "display_value": "Cancelled", "description": "Cancelled before fulfilment",      "sort_order": 5},
    # ],
    # ("Customers", "Tier"): [
    #     {"raw_value": "G", "display_value": "Gold",     "description": "Top-tier customer; >$10k LTV", "sort_order": 1},
    #     {"raw_value": "S", "display_value": "Silver",   "description": "Mid-tier customer",            "sort_order": 2},
    #     {"raw_value": "B", "display_value": "Bronze",   "description": "Standard customer",            "sort_order": 3},
    # ],
    # -------------------------------------------------------------------------
}


# =============================================================================
# 4. KNOWLEDGE DOCUMENTS
#    Free-text business context injected into the LLM prompt during queries.
#    Use these for: data model docs, business rules, calculation methodologies,
#    naming conventions, known data quality issues, etc.
#
#    Fields:
#      title   (required) Short descriptive title
#      content (required) The full text of the document (plain text or HTML)
#
#    Tips:
#      - Keep each document focused on one topic (the chunker splits at ~450 words)
#      - HTML is auto-detected and parsed to plain text
#      - You can also import documents via the UI Knowledge tab
# =============================================================================
KNOWLEDGE_DOCS: list[dict] = [
    {
        "title": "PRMS Data Model and Business Semantics Overview",
        "content": """
PRMS CRITICAL BUSINESS RULES

TIMESHEET VALIDITY (CRITICAL — apply to every TS_EODDetails query):
Always filter: IsApproved = 1 AND IsDeleted = 0 AND IsRejected = 0
Never count unapproved or deleted entries in any hours/effort metric.

ACTIVE ALLOCATIONS:
For current resource-project allocations always filter:
  ProjectResource.IsActive = 1 AND ProjectResource.AssignmentDate <= GETDATE()

BILLING RATE OVERRIDE (most specific level wins):
  ProjectResource.Rate > Project.HourlyBillingRate > Client.HourlyBillingRate
  Always use the most specific rate available when computing billing calculations.

PROJECT TIMELINE COLUMNS:
  Planned dates:  Project.StartDate / Project.EndDate
  Actual dates:   Project.ActualStartDate / Project.ActualEndDate
        """.strip(),
    },
    {
        "title": "PRMS Status Lookup Disambiguation",
        "content": """
PRMS STATUS DISAMBIGUATION

Two separate concepts control entity status — do NOT confuse them:

1. IsActive (bit column on entity tables): system-level on/off flag.
   IsActive = 1 means the record is active/enabled in the system.

2. Status.StatusName via StatusId or ProjectStatusId: business lifecycle label
   (e.g., Active, Inactive, On Hold, Closed).
   The Status table is shared across domains; always filter by ReferenceId.

Status ReferenceId values:
- ReferenceId = 1 → Client status domain (JOIN Status ON Client.StatusId = Status.StatusId AND Status.ReferenceId = 1)
- ReferenceId = 2 → Project status domain (JOIN Status ON Project.ProjectStatusId = Status.StatusId AND Status.ReferenceId = 2)
- ReferenceId = 3 → Resource status domain (Active resource: r.IsActive = 1 AND r.StatusId = 8, where StatusId 8 = "Resource - Active")

CRITICAL WARNINGS:
- Do NOT join using Client.ClientId = Status.ReferenceId — that is wrong.
  Correct join is: Client.StatusId = Status.StatusId
- Projects use ProjectStatusId (not StatusId) to reference their status.
        """.strip(),
    },
    # -------------------------------------------------------------------------
    # TODO: Add your own documents. Examples below.
    #
    # {
    #     "title": "Data Model Overview",
    #     "content": """
    # Our database contains three main areas:
    #
    # CUSTOMERS: The Customers table holds all registered users. The primary key is
    # CustomerId (integer). CustomerTier (G/S/B) indicates loyalty level.
    #
    # ORDERS: Each row is one order. Status is an integer code (0=Pending,
    # 1=Processing, 2=Shipped, 3=Delivered, 4=Cancelled). OrderDate is UTC.
    # Amount is in USD, stored as decimal(18,2).
    #
    # PRODUCTS: ProductId links to Orders.ProductId. Category and SubCategory
    # are free-text strings. IsActive = 1 means the product is currently sold.
    #     """.strip(),
    # },
    # {
    #     "title": "Revenue Recognition Rules",
    #     "content": """
    # Revenue is recognised when Status = 3 (Delivered). Cancelled orders (Status=4)
    # must never be included in revenue figures. Refunded orders are recorded as
    # negative-amount rows with Status = 3.
    #
    # For month-on-month comparisons, always filter on MONTH(OrderDate) and
    # YEAR(OrderDate) — do not use CreatedDate.
    #
    # Tax is not included in the Amount column. The TaxAmount column is separate.
    # Net Revenue = Amount. Gross Revenue = Amount + TaxAmount.
    #     """.strip(),
    # },
    # -------------------------------------------------------------------------
]


# =============================================================================
# SAMPLE QUERIES
# Curated natural-language ↔ SQL pairs used as few-shot examples in the prompt.
# All entries have is_validated=True so they are retrieved at query time.
# Tags let you filter/group them in the UI.
# =============================================================================

SAMPLE_QUERIES: list[dict] = [
    {
        "natural_language": "How many active resources are in the organization?",
        "sql_query": "SELECT COUNT(*) AS ActiveResourceCount FROM Resource WHERE IsActive = 1",
        "description": "Baseline active workforce count",
        "tags": ["resource", "active"],
        "is_validated": True,
    },
    {
        "natural_language": "How many projects are currently active?",
        "sql_query": """SELECT count(*) FROM Project p
        JOIN Client c ON p.ClientId = c.ClientId
        JOIN Status s ON s.StatusId = p.ProjectStatusId
        JOIN Resource r ON r.ResourceId = p.ProjectManagerId
		where (p.EndDate>getdate() or EndDate is null)
		and s.StatusName = 'Active'""",
        "description": "Active projects count",
        "tags": ["project"],
        "is_validated": True,
    },
    {
        "natural_language": "How many resources belong to each business unit?",
        "sql_query": "SELECT bu.BusinessUnitName, COUNT(r.ResourceId) as Count FROM Resource r JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId GROUP BY bu.BusinessUnitName",
        "description": "Resource distribution",
        "tags": ["resource", "business_unit"],
        "is_validated": True,
    },
    {
        "natural_language": "How many projects are mapped to each client?",
        "sql_query": "SELECT c.ClientName, COUNT(p.ProjectId) as Count FROM Client c JOIN Project p ON c.ClientId = p.ClientId where p.IsActive=1 and p.ProjectStatusId=4 GROUP BY c.ClientName",
        "description": "Projects per client",
        "tags": ["client", "project"],
        "is_validated": True,
    },

    {
        "natural_language": "What is the total hours logged per resource?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName",
        "description": "Effort per resource",
        "tags": ["resource", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total billable hours per resource?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY r.ResourceName",
        "description": "Billable contribution",
        "tags": ["resource", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total non-billable hours per resource?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 0 GROUP BY r.ResourceName",
        "description": "Non-billable effort",
        "tags": ["resource", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "How many resources are allocated to each project?",
        "sql_query": "SELECT p.ProjectName, COUNT(pr.ResourceId) FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId GROUP BY p.ProjectName",
        "description": "Team size per project",
        "tags": ["project", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are assigned to multiple projects?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT pr.ProjectId) as Count FROM ProjectResource pr JOIN Resource r ON pr.ResourceId = r.ResourceId GROUP BY r.ResourceName HAVING COUNT(DISTINCT pr.ProjectId) > 1",
        "description": "Multi-project resources",
        "tags": ["resource", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "How many resources are on bench?",
        "sql_query": """select 
    count(*)
    from ProjectResource pr
    join project p on p.ProjectId  = pr.ProjectId
    join resource r on r.ResourceId=pr.ResourceId
    join Resource pm on r.ReportingTo = pm.ResourceId
    where p.ProjectName = 'DF-Bench'
    and pr.percentageallocation>1
    AND pr.IsActive = 1
    AND pr.AssignmentDate <= GETDATE()
    AND r.IsActive = 1
    AND r.StatusId = 8""",
        "description": "Unallocated resources",
        "tags": ["resource", "bench"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average allocation percentage per project?",
        "sql_query": "SELECT p.ProjectName, AVG(pr.PercentageAllocation) as [Average Allocation in (%)] FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId GROUP BY p.ProjectName having AVG(pr.PercentageAllocation)>1",
        "description": "Allocation efficiency",
        "tags": ["project", "allocation"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total effort logged per project?",
        "sql_query": "SELECT e.Project, SUM(e.Hrs) FROM TS_EODDetails e GROUP BY e.Project",
        "description": "Project workload",
        "tags": ["project", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total billable hours per client?",
        "sql_query": "SELECT e.ClientName, SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY e.ClientName",
        "description": "Client billing",
        "tags": ["client", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the billable utilization percentage per resource?",
        "sql_query": """SELECT r.ResourceName,
       SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 100.0
           / NULLIF(SUM(e.Hrs), 0) AS BillableUtilizationPercent
        FROM TS_EODDetails e
        JOIN Resource r ON e.ResourceId = r.ResourceId
        JOIN TS_Activity a ON e.Activity_Id = a.Id
        WHERE e.IsDeleted = 0
        AND e.IsApproved = 1
        GROUP BY r.ResourceName
        ORDER BY BillableUtilizationPercent DESC""",
        "description": "Resource utilization",
        "tags": ["resource", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients generate the highest revenue based on billable hours?",
        "sql_query": """
                    SELECT e.ClientName, SUM(e.Hrs * c.HourlyBillingRate) AS TotalRevenue
                    FROM TS_EODDetails e
                    JOIN Client c ON e.ClientName = c.ClientName
                    JOIN TS_Activity a ON e.Activity_Id = a.Id
                    WHERE e.IsDeleted = 0
                    AND e.IsApproved = 1
                    AND a.Billablestatus = 1
                    GROUP BY e.ClientName
                    ORDER BY TotalRevenue DESC
                    """,
        "description": "Revenue per client",
        "tags": ["client", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources generate the highest revenue contribution?",
        "sql_query": "SELECT TOP 25 r.ResourceName, SUM(e.Hrs * c.HourlyBillingRate) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN Client c ON e.ClientName = c.ClientName JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY r.ResourceName ORDER BY 2 DESC",
        "description": "Top revenue contributors",
        "tags": ["resource", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have logged effort on weekends?",
        "sql_query": "SELECT DISTINCT r.ResourceName FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE DATENAME(WEEKDAY, e.ReportDate) IN ('Saturday','Sunday')",
        "description": "Weekend work tracking",
        "tags": ["resource", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average number of projects per resource?",
        "sql_query": "SELECT AVG(ProjectCount) FROM (SELECT ResourceId, COUNT(DISTINCT ProjectId) AS ProjectCount FROM ProjectResource GROUP BY ResourceId) t",
        "description": "Resource project load",
        "tags": ["resource", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total effort per designation?",
        "sql_query": "SELECT d.DesignationName, SUM(e.Hrs) as TotalEffort FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN Designation d ON r.DesignationId = d.DesignationId GROUP BY d.DesignationName Order By TotalEffort desc",
        "description": "Effort by role",
        "tags": ["resource", "designation"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have the highest billable to non-billable ratio?",
        "sql_query": """
                    SELECT 
                        e.Project,
                        (SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 1.0
                        / NULLIF(SUM(e.Hrs), 0))*100 AS billable_ratio
                        FROM TS_EODDetails e
                        JOIN TS_Activity a ON e.Activity_Id = a.Id
                        join Client c on c.clientname = e.ClientName
                        where c.IsActive=1 and c.StatusId=2
                        GROUP BY e.Project
                        ORDER BY billable_ratio DESC;
                        """,
        "description": "Project efficiency",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the highest average billable hours per project?",
        "sql_query": "SELECT e.ClientName, AVG(ProjectHours) FROM (SELECT ClientName, Project, SUM(Hrs) AS ProjectHours FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY ClientName, Project) t GROUP BY ClientName",
        "description": "Client project productivity",
        "tags": ["client", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have highest variance in daily effort?",
        "sql_query": "SELECT r.ResourceName, VAR(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId where r.isactive=1 and r.statusid=8 GROUP BY r.ResourceName HAVING VAR(e.hrs)>0 ORDER BY 2 DESC",
        "description": "Effort inconsistency",
        "tags": ["resource", "pattern"],
        "is_validated": True,
    },
    {
        "natural_language": "List all resources with more than 5 years of experience.",
        "sql_query": "SELECT ResourceName, TotalYears FROM Resource WHERE TotalYears > 5;",
        "description": "Helps identify senior resources.",
        "tags": ["resource", "experience"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are currently on bench?",
        "sql_query": """
                    select 
                        r.ResourceId, r.ResourceName,p.projectname, pr.PercentageAllocation, pm.ResourceName
                        from ProjectResource pr
                    join project p on p.ProjectId  = pr.ProjectId
                    join resource r on r.ResourceId=pr.ResourceId
                    join Resource pm on r.ReportingTo = pm.ResourceId
                    where p.ProjectName = 'DF-Bench'
                    and pr.percentageallocation>1
                    AND pr.IsActive = 1
                        AND pr.AssignmentDate <= GETDATE()
                        AND r.IsActive = 1
                        AND r.StatusId = 8
                        order by r.ResourceName                        
                    """,
        "description": "Identifies Benched, unallocated or idle resources.",
        "tags": ["resource", "bench"],
        "is_validated": True,
    },
    {
        "natural_language": "List all active clients.",
        "sql_query": "SELECT distinct c.ClientName, c.Description, c.CountryId FROM Client c JOIN Status st ON c.StatusId = st.StatusId WHERE c.IsActive = 1 and st.statusname='Active'",
        "description": "Fetches all currently active clients.",
        "tags": ["client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the highest monthly billing rate?",
        "sql_query": "SELECT TOP 5 ClientName, MonthlyBillingRate FROM Client where IsActive=1 and StatusId=2 ORDER BY MonthlyBillingRate DESC;",
        "description": "Top revenue-generating clients.",
        "tags": ["client", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "List all projects along with their client names.",
        "sql_query": "SELECT p.ProjectName, c.ClientName FROM Project p JOIN Client c ON p.ClientId = c.ClientId where c.IsActive=1 and c.statusid=2 and p.ProjectStatusId=4;",
        "description": "Maps projects to clients.",
        "tags": ["project", "client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which project has the highest number of resources allocated?",
        "sql_query": "SELECT TOP 10 ProjectName, NumberOfResorces FROM Project where ProjectStatusId=4 ORDER BY NumberOfResorces DESC;",
        "description": "Identifies largest project by team size.",
        "tags": ["project", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "List all resources working on a specific project.",
        "sql_query": "SELECT r.ResourceName FROM ProjectResource pr JOIN Resource r ON pr.ResourceId = r.ResourceId JOIN Project p on p.ProjectId=pr.ProjectId WHERE p.ProjectName like '%' + @ProjectName + '%'  and r.isactive=1 and r.statusid=8 AND GETDATE() BETWEEN pr.StartDate AND ISNULL(pr.EndDate, '9999-12-31');",
        "description": "Project team composition.",
        "tags": ["project", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "List all skills available in the system.",
        "sql_query": "SELECT Name FROM PA_Skills;",
        "description": "Skill inventory.",
        "tags": ["skills"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have a specific skill?",
        "sql_query": "SELECT r.ResourceName FROM PA_ResourceSkills rs JOIN Resource r ON rs.ResourceId = r.ResourceId WHERE rs.SkillId = @SkillId;",
        "description": "Skill-based resource lookup.",
        "tags": ["skills", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What are the most common skills among resources?",
        "sql_query": "SELECT SkillId, COUNT(*) as Count FROM PA_ResourceSkills GROUP BY SkillId ORDER BY Count DESC;",
        "description": "Popular skills in workforce.",
        "tags": ["skills", "analytics"],
        "is_validated": True,
    },
    {
        "natural_language": "How many resources joined in the last year?",
        "sql_query": "SELECT COUNT(*) FROM Resource WHERE DateOfJoin >= DATEADD(YEAR, -1, GETDATE());",
        "description": "Recent hiring trends.",
        "tags": ["resource", "hiring"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients belong to which domain?",
        "sql_query": "SELECT c.ClientName, d.DomainName FROM Client c JOIN Domain d ON c.DomainId = d.DomainId where c.isactive=1 and c.statusid=2;",
        "description": "Client domain mapping.",
        "tags": ["client", "domain"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources reporting to a specific manager?",
        "sql_query": """SELECT DISTINCT
                        r.[ResourceName],
                        r.[EmployeeId],
                        d.[DesignationName],
                        bu.[BusinessUnitName],
                        dr.[DesignatedRoleName],
                        tf.[FunctionName]
                    FROM [Resource] r
                    JOIN [Resource] m ON r.[ReportingTo] = m.[ResourceId]
                    LEFT JOIN [Designation] d ON r.[DesignationId] = d.[DesignationId]
                    LEFT JOIN [BusinessUnit] bu ON r.[BusinessUnitId] = bu.[BusinessUnitId]
                    LEFT JOIN [DesignatedRole] dr ON r.[DesignatedRoleId] = dr.[DesignatedRoleId]
                    LEFT JOIN [TechFunction] tf ON r.[FunctionId] = tf.[FunctionId]
                    WHERE m.[ResourceName] = 'ashutosh pandey'
                        AND r.[IsActive] = 1
                        AND r.[StatusId] = 8 
                    ORDER BY r.[ResourceName];
                    """,
        "description": "Reporting hierarchy.",
        "tags": ["resource", "hierarchy"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have multiple skills?",
        "sql_query": "SELECT ResourceId, COUNT(SkillId) as SkillCount FROM PA_ResourceSkills GROUP BY ResourceId HAVING COUNT(SkillId) > 1;",
        "description": "Multi-skilled employees.",
        "tags": ["skills", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total revenue generated per client along with number of projects and allocated resources?",
        "sql_query": "SELECT c.ClientName, SUM(pr.Rate) AS TotalRevenue, COUNT(DISTINCT p.ProjectId) AS ProjectCount, COUNT(DISTINCT pr.ResourceId) AS ResourceCount FROM Client c JOIN Project p ON c.ClientId = p.ClientId JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId where c.IsActive=1 and c.StatusId=2 and p.ProjectStatusId=4 and p.IsActive=1 GROUP BY c.ClientName;",
        "description": "Holistic client-level revenue and engagement view.",
        "tags": ["client", "revenue", "project", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "List resources along with their skills and associated projects.",
        "sql_query": "SELECT r.ResourceName, s.Name AS SkillName, p.ProjectName FROM Resource r JOIN PA_ResourceSkills rs ON r.ResourceId = rs.ResourceId JOIN PA_Skills s ON rs.SkillId = s.SkillId LEFT JOIN ProjectResource pr ON r.ResourceId = pr.ResourceId LEFT JOIN Project p ON pr.ProjectId = p.ProjectId where p.isactive=1 and r.isactive=1 and p.projectstatusid=4;",
        "description": "Skill-to-project mapping.",
        "tags": ["resource", "skills", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have the highest average billing rate per resource?",
        "sql_query": "SELECT p.ProjectName, AVG(pr.Rate) AS AvgRate FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId where p.isactive=1 and p.projectstatusid=4 GROUP BY p.ProjectName HAVING AVG(pr.Rate)>0 ORDER BY AvgRate DESC ;",
        "description": "High-value projects.",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are working on multiple projects simultaneously?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT pr.ProjectId) AS ProjectCount FROM Resource r JOIN ProjectResource pr ON r.ResourceId = pr.ResourceId GROUP BY r.ResourceName HAVING COUNT(DISTINCT pr.ProjectId) > 1;",
        "description": "Multi-project allocation.",
        "tags": ["resource", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total billing grouped by project and client?",
        "sql_query": "SELECT c.ClientName, p.ProjectName, SUM(pr.Rate) FROM Project p JOIN Client c ON p.ClientId = c.ClientId JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId where p.isactive=1 and c.isactive=1 GROUP BY c.ClientName, p.ProjectName having SUM(pr.Rate)>0",
        "description": "Granular billing view.",
        "tags": ["billing", "client", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "List all stakeholders mapped to projects through clients.",
        "sql_query": "SELECT DISTINCT p.ProjectName, cs.StakeholderName FROM Project p JOIN ClientStakeholder cs ON p.ClientId = cs.ClientId;",
        "description": "Stakeholder visibility per project.",
        "tags": ["project", "stakeholder"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average billing rate by domain?",
        "sql_query": "SELECT d.DomainName, AVG(pr.Rate) FROM ProjectResource pr JOIN Project p ON pr.ProjectId = p.ProjectId JOIN Client c ON p.ClientId = c.ClientId JOIN Domain d ON c.DomainId = d.DomainId GROUP BY d.DomainName;",
        "description": "Domain profitability.",
        "tags": ["billing", "domain"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are working under each project manager?",
        "sql_query": "SELECT DISTINCT pm.ResourceName AS Manager, r.ResourceName AS Resource FROM Project p JOIN Resource pm ON p.ProjectManagerId = pm.ResourceId JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId JOIN Resource r ON pr.ResourceId = r.ResourceId where r.IsActive=1 and r.StatusId=8 and pm.IsActive=1 and pm.StatusId=8 order by pm.ResourceName;",
        "description": "Manager-team mapping.",
        "tags": ["resource", "hierarchy"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the distribution of resources across clients?",
        "sql_query": "SELECT c.ClientName, COUNT(DISTINCT pr.ResourceId) as Count FROM Client c JOIN Project p ON c.ClientId = p.ClientId JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId where pr.IsActive=1 and c.IsActive=1 and c.StatusId=2 GROUP BY c.ClientName;",
        "description": "Client staffing levels. Resource count per client.",
        "tags": ["client", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total effort (hours) logged per client in the last month?",
        "sql_query": "SELECT e.ClientName, SUM(e.Hrs) AS TotalHours FROM TS_EODDetails e WHERE e.IsDeleted = 0 AND e.ReportDate >= DATEADD(MONTH, -1, GETDATE()) GROUP BY e.ClientName;",
        "description": "Client-level effort tracking from timesheets.",
        "tags": ["timesheet", "client", "effort"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have logged the highest hours in the last month?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs) AS TotalHours FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE e.IsDeleted = 0 GROUP BY r.ResourceName ORDER BY TotalHours DESC;",
        "description": "Identifies highly utilized resources.",
        "tags": ["resource", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total billing potential based on hourly rates and logged hours per client?",
        "sql_query": "SELECT c.ClientName, SUM(e.Hrs * c.HourlyBillingRate) AS EstimatedRevenue FROM TS_EODDetails e JOIN Client c ON e.ClientName = c.ClientName where c.IsActive=1 and c.StatusId=2 GROUP BY c.ClientName;",
        "description": "Revenue estimation using timesheets.",
        "tags": ["billing", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "Which activities consume the most effort hours?",
        "sql_query": "SELECT a.ActivityName, SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY a.ActivityName ORDER BY SUM(e.Hrs) DESC;",
        "description": "Activity-level effort breakdown.",
        "tags": ["activity", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the approval rate of timesheets per manager?",
        "sql_query": "SELECT e.ManagerEmail, SUM(CASE WHEN e.IsApproved = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS ApprovalRate FROM TS_EODDetails e GROUP BY e.ManagerEmail;",
        "description": "Manager efficiency in approvals.",
        "tags": ["timesheet", "approval"],
        "is_validated": True,
    },
    {
        "natural_language": "Which skills are most common among high-tenure resources?",
        "sql_query": "SELECT s.Name, COUNT(*) FROM Resource r JOIN PA_ResourceSkills rs ON r.ResourceId = rs.ResourceId JOIN PA_Skills s ON rs.SkillId = s.SkillId WHERE r.TotalYears > 5 GROUP BY s.Name ORDER BY COUNT(*) DESC;",
        "description": "Senior skill trends.",
        "tags": ["skills", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which subskills are linked to each primary skill?",
        "sql_query": "SELECT s.Name, ss.Name FROM PA_Skills s JOIN PA_SubSkills ss ON s.SkillId = ss.SkillId;",
        "description": "Skill hierarchy mapping.",
        "tags": ["skills"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients use which payment methods and cycles?",
        "sql_query": "SELECT c.ClientName, pm.PaymentMethodName, pc.PaymentCycleName FROM Client c LEFT JOIN PaymentMethod pm ON c.PaymentMethodId = pm.PaymentMethodId LEFT JOIN PaymentCycle pc ON c.PaymentCycleId = pc.PaymentCycleId where c.isactive=1 and c.statusid=2;",
        "description": "Payment configuration view.",
        "tags": ["client", "finance"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources joined recently and are already contributing to timesheets?",
        "sql_query": "SELECT DISTINCT r.ResourceName FROM Resource r JOIN TS_EODDetails e ON r.ResourceId = e.ResourceId WHERE r.DateOfJoin >= DATEADD(MONTH, -3, GETDATE());",
        "description": "New hire productivity.",
        "tags": ["resource", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average workload per resource by designation?",
        "sql_query": "SELECT d.DesignationName, AVG(e.Hrs) FROM Resource r JOIN Designation d ON r.DesignationId = d.DesignationId JOIN TS_EODDetails e ON r.ResourceId = e.ResourceId GROUP BY d.DesignationName;",
        "description": "Workload by role.",
        "tags": ["resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources report to managers and also act as reporting persons?",
        "sql_query": "SELECT r1.ResourceName, r2.ResourceName AS Manager FROM Resource r1 JOIN Resource r2 ON r1.ReportingTo = r2.ResourceId WHERE r1.IsReportingPerson = 1;",
        "description": "Dual-role resources.",
        "tags": ["hierarchy"],
        "is_validated": True,
    },
    {
        "natural_language": "Which holidays fall within major project timelines?",
        "sql_query": "SELECT h.HolidayName, h.HolidayDate, e.Project FROM DesignatedHolidays h JOIN TS_EODDetails e ON h.HolidayDate = e.ReportDate;",
        "description": "Holiday impact analysis.",
        "tags": ["holiday"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the billable utilization percentage per project?",
        "sql_query": "SELECT e.Project, SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 100.0 / SUM(e.Hrs) AS BillableUtilization FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.Project;",
        "description": "Project-level billability.",
        "tags": ["project", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average daily hours logged per resource?",
        "sql_query": "SELECT r.ResourceName, AVG(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId where r.isactive=1 and r.statusid=8 GROUP BY r.ResourceName;",
        "description": "Daily effort consistency.",
        "tags": ["timesheet", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total billable effort per client?",
        "sql_query": "SELECT e.ClientName, SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY e.ClientName;",
        "description": "Client billing contribution.",
        "tags": ["client", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources contribute the most non-billable hours?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 0 GROUP BY r.ResourceName ORDER BY SUM(e.Hrs) DESC;",
        "description": "Non-billable heavy contributors.",
        "tags": ["resource", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average billable utilization per designation?",
        "sql_query": "SELECT d.DesignationName, SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 100.0 / SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN Designation d ON r.DesignationId = d.DesignationId JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY d.DesignationName;",
        "description": "Role-based billability.",
        "tags": ["designation", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have no billable activity logged?",
        "sql_query": "SELECT e.Project FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.Project HAVING SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) = 0;",
        "description": "Zero-billing projects.",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are consistently under-utilized (less than 4 hours daily)?",
        "sql_query": "SELECT r.ResourceName, AVG(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId where r.IsActive=1 and r.StatusId=8 GROUP BY r.ResourceName HAVING AVG(e.Hrs) < 4;",
        "description": "Low utilization resources.",
        "tags": ["resource", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the distribution of hours across different OEM categories?",
        "sql_query": "SELECT o.Dropdown_Description, SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_SG_OEM_Master o ON e.OEM_Id = o.Dropdown_Identifier GROUP BY o.Dropdown_Description;",
        "description": "OEM-level effort analysis.",
        "tags": ["timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average completion percentage per resource?",
        "sql_query": "SELECT r.ResourceName, AVG(CAST(e.CompletionPercent AS FLOAT)) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName;",
        "description": "Execution efficiency.",
        "tags": ["resource", "performance"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have the highest average completion percentage?",
        "sql_query": "SELECT e.Project, AVG(CAST(e.CompletionPercent AS FLOAT)) FROM TS_EODDetails e GROUP BY e.Project ORDER BY 2 DESC;",
        "description": "Fast-moving projects.",
        "tags": ["project", "progress"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are contributing to the highest number of clients?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT e.ClientName) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName ORDER BY 2 DESC;",
        "description": "Client spread.",
        "tags": ["resource", "client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects are at risk due to low average daily effort from assigned resources?",
        "sql_query": "SELECT e.Project, AVG(e.Hrs) AS AvgDailyHours FROM TS_EODDetails e GROUP BY e.Project HAVING AVG(e.Hrs) < 4;",
        "description": "Low engagement risk indicator.",
        "tags": ["project", "risk"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are consistently logging hours but not contributing to billable work?",
        "sql_query": "SELECT r.ResourceName FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY r.ResourceName HAVING SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) = 0;",
        "description": "Identifies cost centers instead of revenue contributors.",
        "tags": ["resource", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have declining utilization trends over the last 3 months?",
        "sql_query": "SELECT e.ClientName, MONTH(e.ReportDate), SUM(e.Hrs) FROM TS_EODDetails e WHERE e.ReportDate >= DATEADD(MONTH, -3, GETDATE()) GROUP BY e.ClientName, MONTH(e.ReportDate) ORDER BY e.ClientName, MONTH(e.ReportDate);",
        "description": "Detects declining engagement.",
        "tags": ["client", "trend"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are over-utilized and simultaneously working on multiple clients?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT e.ClientName) AS ClientCount, SUM(e.Hrs) AS TotalHours FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName HAVING SUM(e.Hrs) > 180 AND COUNT(DISTINCT e.ClientName) > 1;",
        "description": "Burnout and context-switching risk.",
        "tags": ["resource", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects are generating effort but have zero associated billing rate?",
        "sql_query": "SELECT e.Project FROM TS_EODDetails e LEFT JOIN Client c ON e.ClientName = c.ClientName WHERE c.HourlyBillingRate IS NULL GROUP BY e.Project;",
        "description": "Unmonetized delivery effort.",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have high effort but low agreement value indicating poor margins?",
        "sql_query": "SELECT c.ClientName, SUM(e.Hrs) AS TotalEffort, c.AgreementValue FROM TS_EODDetails e JOIN Client c ON e.ClientName = c.ClientName GROUP BY c.ClientName, c.AgreementValue HAVING SUM(e.Hrs) > 500;",
        "description": "Margin pressure indicator.",
        "tags": ["client", "margin"],
        "is_validated": True,
    },
    {
        "natural_language": "Which managers have the highest number of unapproved timesheets?",
        "sql_query": "SELECT e.ManagerEmail, COUNT(*) FROM TS_EODDetails e WHERE e.IsApproved = 0 GROUP BY e.ManagerEmail ORDER BY COUNT(*) DESC;",
        "description": "Approval bottleneck.",
        "tags": ["timesheet", "governance"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the highest dependency on a single resource?",
        "sql_query": "SELECT e.ClientName, r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY e.ClientName, r.ResourceName HAVING SUM(e.Hrs) = (SELECT MAX(SUM(e2.Hrs)) FROM TS_EODDetails e2 WHERE e2.ClientName = e.ClientName GROUP BY e2.ResourceId);",
        "description": "Single point of failure.",
        "tags": ["client", "risk"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have high effort variance indicating unstable execution?",
        "sql_query": "SELECT e.Project, VAR(e.Hrs) FROM TS_EODDetails e GROUP BY e.Project ORDER BY VAR(e.Hrs) DESC;",
        "description": "Execution inconsistency.",
        "tags": ["project", "stability"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have a sudden spike in effort compared to previous periods?",
        "sql_query": "SELECT e.ClientName, MONTH(e.ReportDate), SUM(e.Hrs) FROM TS_EODDetails e GROUP BY e.ClientName, MONTH(e.ReportDate) ORDER BY e.ClientName, MONTH(e.ReportDate);",
        "description": "Spike detection.",
        "tags": ["client", "trend"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are contributing to the highest revenue based on billable hours?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs * c.HourlyBillingRate) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN Client c ON e.ClientName = c.ClientName JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY r.ResourceName ORDER BY 2 DESC;",
        "description": "Top revenue generators.",
        "tags": ["resource", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have multiple stakeholders but low engagement effort?",
        "sql_query": "SELECT c.ClientName, COUNT(cs.StakeholderId), SUM(e.Hrs) FROM Client c JOIN ClientStakeholder cs ON c.ClientId = cs.ClientId LEFT JOIN TS_EODDetails e ON c.ClientName = e.ClientName GROUP BY c.ClientName HAVING SUM(e.Hrs) < 50;",
        "description": "Low ROI engagements.",
        "tags": ["client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects are consuming effort without any recorded completion progress?",
        "sql_query": "SELECT e.Project FROM TS_EODDetails e GROUP BY e.Project HAVING AVG(CAST(e.CompletionPercent AS FLOAT)) = 0;",
        "description": "Execution inefficiency.",
        "tags": ["project", "progress"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have effort logged but no recent agreement updates?",
        "sql_query": "SELECT c.ClientName FROM Client c JOIN TS_EODDetails e ON c.ClientName = e.ClientName WHERE c.AgreementEndDate < GETDATE() GROUP BY c.ClientName;",
        "description": "Contract risk.",
        "tags": ["client", "contract"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have the most inconsistent daily effort patterns?",
        "sql_query": "SELECT r.ResourceName, VAR(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName ORDER BY VAR(e.Hrs) DESC;",
        "description": "Unpredictable contributors.",
        "tags": ["resource", "pattern"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have more non-billable effort than billable effort?",
        "sql_query": "SELECT e.Project FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.Project HAVING SUM(CASE WHEN a.Billablestatus = 0 THEN e.Hrs ELSE 0 END) > SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END);",
        "description": "Loss-making projects.",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have high effort concentration in a single activity type?",
        "sql_query": "SELECT e.ClientName, a.ActivityName, SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.ClientName, a.ActivityName;",
        "description": "Workload skew analysis.",
        "tags": ["client", "activity"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are under-utilized despite being assigned to active projects?",
        "sql_query": "SELECT r.ResourceName FROM Resource r JOIN TS_EODDetails e ON r.ResourceId = e.ResourceId GROUP BY r.ResourceName HAVING AVG(e.Hrs) < 3;",
        "description": "Underutilized workforce.",
        "tags": ["resource", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the highest effort-to-revenue imbalance?",
        "sql_query": "SELECT c.ClientName, SUM(e.Hrs)/c.AgreementValue FROM TS_EODDetails e JOIN Client c ON e.ClientName = c.ClientName GROUP BY c.ClientName, c.AgreementValue ORDER BY 2 DESC;",
        "description": "Profitability ratio.",
        "tags": ["client", "margin"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have high effort but low resource diversity?",
        "sql_query": "SELECT e.Project, COUNT(DISTINCT e.ResourceId), SUM(e.Hrs) FROM TS_EODDetails e GROUP BY e.Project HAVING COUNT(DISTINCT e.ResourceId) < 2 AND SUM(e.Hrs) > 100;",
        "description": "Resource dependency risk.",
        "tags": ["project", "risk"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are working on clients across different domains?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT c.DomainId) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN Client c ON e.ClientName = c.ClientName GROUP BY r.ResourceName HAVING COUNT(DISTINCT c.DomainId) > 1;",
        "description": "Cross-domain expertise.",
        "tags": ["resource", "domain"],
        "is_validated": True,
    },
    {
        "natural_language": "Which managers are overseeing the highest total effort?",
        "sql_query": "SELECT r.ReportingTo, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ReportingTo ORDER BY SUM(e.Hrs) DESC;",
        "description": "Managerial workload.",
        "tags": ["manager"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are working on, or assigned to Internal Projects?",
        "sql_query": """select r.Resourcename, p.ProjectName,pr.PercentageAllocation, pr.AssignmentDate, pr.Billable, pr.EndDate from ProjectResource pr
                join Client c on c.ClientId = pr.ClientId
                join Resource r on r.ResourceId = pr.ResourceId
                join Project p on p.ProjectId = pr.ProjectId
                where pr.IsActive = 1
                    AND pr.AssignmentDate <= GETDATE()
                    AND (pr.EndDate IS NULL OR pr.EndDate > GETDATE())
                    AND r.IsActive = 1
                    AND r.StatusId = 8
                    and r.IsReportingPerson=0
                    and pr.PercentageAllocation>1
                    and (pr.Billable=0 and pr.Shadow=1)
                    and c.ClientName = 'Internal Projects';""",
        "description": "Internal project assignments.",
        "tags": ["Internal", "project", "resource"],
        "is_validated": True,
    },

    {
        "natural_language": "Which projects show declining completion percentages despite high effort?",
        "sql_query": "SELECT e.Project, AVG(CAST(e.CompletionPercent AS FLOAT)), SUM(e.Hrs) FROM TS_EODDetails e GROUP BY e.Project HAVING SUM(e.Hrs) > 100;",
        "description": "Execution inefficiency.",
        "tags": ["project", "risk"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the highest number of unique resources working on them?",
        "sql_query": "SELECT e.ClientName, COUNT(DISTINCT e.ResourceId) FROM TS_EODDetails e GROUP BY e.ClientName ORDER BY 2 DESC;",
        "description": "Client complexity.",
        "tags": ["client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources contribute to the most number of projects but with low total effort?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT e.Project), SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName HAVING COUNT(DISTINCT e.Project) > 3 AND SUM(e.Hrs) < 50;",
        "description": "Context switching inefficiency.",
        "tags": ["resource", "efficiency"],
        "is_validated": True,
    },
]


# =============================================================================
# RELATIONSHIPS
# Explicitly declared FK-like joins that are NOT enforced in the database
# but must be known for correct SQL generation.  These are stored as
# is_manual=True CachedRelationship rows and survive schema re-introspection.
# =============================================================================

RELATIONSHIPS: list[dict] = [
    # ── Resource ─────────────────────────────────────────────────────────────
    {
        "source_table": "Resource",
        "source_column": "ReportingTo",
        "target_table": "Resource",
        "target_column": "ResourceId",
        "constraint_name": "FK_Resource_Reporting",
        "relationship_type": "hierarchical",
    },
    {
        "source_table": "Resource",
        "source_column": "BusinessUnitId",
        "target_table": "BusinessUnit",
        "target_column": "BusinessUnitId",
        "constraint_name": "FK_Resource_BusinessUnit",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Resource",
        "source_column": "DesignationId",
        "target_table": "Designation",
        "target_column": "DesignationId",
        "constraint_name": "FK_Resource_Designation",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Resource",
        "source_column": "OrganizationId",
        "target_table": "Organization",
        "target_column": "OrganizationId",
        "constraint_name": "FK_Resource_Organization",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Resource",
        "source_column": "FunctionId",
        "target_table": "TechFunction",
        "target_column": "FunctionId",
        "constraint_name": "FK_Resource_Function",
        "relationship_type": "explicit_fk",
    },
    # ── Project ───────────────────────────────────────────────────────────────
    {
        "source_table": "Project",
        "source_column": "ClientId",
        "target_table": "Client",
        "target_column": "ClientId",
        "constraint_name": "FK_Project_Client",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Project",
        "source_column": "ProjectManagerId",
        "target_table": "Resource",
        "target_column": "ResourceId",
        "constraint_name": "FK_Project_Manager",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Project",
        "source_column": "ProjectLeadId",
        "target_table": "Resource",
        "target_column": "ResourceId",
        "constraint_name": "FK_Project_Lead",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Project",
        "source_column": "ProjectTypeId",
        "target_table": "ProjectType",
        "target_column": "ProjectTypeId",
        "constraint_name": "FK_Project_Type",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Project",
        "source_column": "CategoryId",
        "target_table": "CategoryType",
        "target_column": "CategoryTypeId",
        "constraint_name": "FK_Project_Category",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Project",
        "source_column": "FunctionId",
        "target_table": "TechFunction",
        "target_column": "FunctionId",
        "constraint_name": "FK_Project_Function",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Project",
        "source_column": "OrganizationId",
        "target_table": "Organization",
        "target_column": "OrganizationId",
        "constraint_name": "FK_Project_Org",
        "relationship_type": "explicit_fk",
    },
    # ── ProjectResource (bridge) ──────────────────────────────────────────────
    {
        "source_table": "ProjectResource",
        "source_column": "ProjectId",
        "target_table": "Project",
        "target_column": "ProjectId",
        "constraint_name": "FK_ProjectResource_Project",
        "relationship_type": "bridge",
    },
    {
        "source_table": "ProjectResource",
        "source_column": "ResourceId",
        "target_table": "Resource",
        "target_column": "ResourceId",
        "constraint_name": "FK_ProjectResource_Resource",
        "relationship_type": "bridge",
    },
    # ── Client ────────────────────────────────────────────────────────────────
    {
        "source_table": "Client",
        "source_column": "BusinessUnitId",
        "target_table": "BusinessUnit",
        "target_column": "BusinessUnitId",
        "constraint_name": "FK_Client_BU",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Client",
        "source_column": "DomainId",
        "target_table": "Domain",
        "target_column": "DomainId",
        "constraint_name": "FK_Client_Domain",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Client",
        "source_column": "CompanyTypeId",
        "target_table": "CompanyType",
        "target_column": "CompanyTypeId",
        "constraint_name": "FK_Client_CompanyType",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Client",
        "source_column": "PaymentMethodId",
        "target_table": "PaymentMethod",
        "target_column": "PaymentMethodId",
        "constraint_name": "FK_Client_PaymentMethod",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "Client",
        "source_column": "PaymentCycleId",
        "target_table": "PaymentCycle",
        "target_column": "PaymentCycleId",
        "constraint_name": "FK_Client_PaymentCycle",
        "relationship_type": "explicit_fk",
    },
    # ── Client related ────────────────────────────────────────────────────────
    {
        "source_table": "ClientStakeholder",
        "source_column": "ClientId",
        "target_table": "Client",
        "target_column": "ClientId",
        "constraint_name": "FK_Stakeholder_Client",
        "relationship_type": "explicit_fk",
    },
    # ── Skills (bridge) ───────────────────────────────────────────────────────
    {
        "source_table": "PA_ResourceSkills",
        "source_column": "ResourceId",
        "target_table": "Resource",
        "target_column": "ResourceId",
        "constraint_name": "FK_RS_Resource",
        "relationship_type": "bridge",
    },
    {
        "source_table": "PA_ResourceSkills",
        "source_column": "SkillId",
        "target_table": "PA_Skills",
        "target_column": "SkillId",
        "constraint_name": "FK_RS_Skill",
        "relationship_type": "bridge",
    },
    {
        "source_table": "PA_ResourceSkills",
        "source_column": "SubSkillId",
        "target_table": "PA_SubSkills",
        "target_column": "SubSkillId",
        "constraint_name": "FK_RS_SubSkill",
        "relationship_type": "bridge",
    },
    {
        "source_table": "PA_SubSkills",
        "source_column": "SkillId",
        "target_table": "PA_Skills",
        "target_column": "SkillId",
        "constraint_name": "FK_SubSkill_Skill",
        "relationship_type": "hierarchical",
    },
    # ── Client reviews ────────────────────────────────────────────────────────
    {
        "source_table": "ClientReview",
        "source_column": "ClientId",
        "target_table": "Client",
        "target_column": "ClientId",
        "constraint_name": "FK_CR_Client",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "ClientReview",
        "source_column": "ProjectId",
        "target_table": "Project",
        "target_column": "ProjectId",
        "constraint_name": "FK_CR_Project",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "ClientReview",
        "source_column": "YearMasterId",
        "target_table": "YearMaster",
        "target_column": "YearMasterId",
        "constraint_name": "FK_CR_Year",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "ClientReview",
        "source_column": "DateMasterId",
        "target_table": "DateMaster",
        "target_column": "DateMasterId",
        "constraint_name": "FK_CR_Date",
        "relationship_type": "explicit_fk",
    },
    # ── Timesheets ────────────────────────────────────────────────────────────
    {
        "source_table": "TS_EODDetails",
        "source_column": "ResourceId",
        "target_table": "Resource",
        "target_column": "ResourceId",
        "constraint_name": "FK_EOD_Resource",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "TS_EODDetails",
        "source_column": "Activity_Id",
        "target_table": "TS_Activity",
        "target_column": "Id",
        "constraint_name": "FK_EOD_Activity",
        "relationship_type": "explicit_fk",
    },
    {
        "source_table": "TS_EODDetails",
        "source_column": "OEM_Id",
        "target_table": "TS_SG_OEM_Master",
        "target_column": "Dropdown_Identifier",
        "constraint_name": "FK_EOD_OEM",
        "relationship_type": "explicit_fk",
    },
    # ── Implicit joins (no FK, join on name columns — critical for chatbot) ───
    {
        "source_table": "TS_EODDetails",
        "source_column": "ClientName",
        "target_table": "Client",
        "target_column": "ClientName",
        "constraint_name": "IMPLICIT_EOD_Client",
        "relationship_type": "implicit_join",
    },
    {
        "source_table": "TS_EODDetails",
        "source_column": "Project",
        "target_table": "Project",
        "target_column": "ProjectName",
        "constraint_name": "IMPLICIT_EOD_Project",
        "relationship_type": "implicit_join",
    },
]


# =============================================================================
# Direct PostgreSQL seeding — no need to edit below this line
# =============================================================================


def _load_env() -> dict:
    env_path = find_dotenv(str(Path(__file__).resolve().parents[2] / ".env"))
    if env_path:
        return dotenv_values(env_path)
    return {}


def _get_connection_id(conn, connection_name: str) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM database_connections WHERE name = %s",
            (connection_name,),
        )
        row = cur.fetchone()
        if not row:
            cur.execute("SELECT name FROM database_connections")
            available = [r[0] for r in cur.fetchall()]
            print(f"ERROR: Connection '{connection_name}' not found.")
            print(f"  Available connections: {available}")
            sys.exit(1)
        return UUID(str(row[0]))


def _ensure_constraints(conn) -> None:
    """Create unique constraints and id defaults if they don't exist (upsert prerequisite)."""
    constraints = [
        (
            "glossary_terms",
            "glossary_terms_connection_id_term_unique",
            "UNIQUE (connection_id, term)",
        ),
        (
            "metric_definitions",
            "metric_definitions_connection_id_metric_name_unique",
            "UNIQUE (connection_id, metric_name)",
        ),
        (
            "sample_queries",
            "sample_queries_connection_id_nl_unique",
            "UNIQUE (connection_id, natural_language)",
        ),
        (
            "knowledge_documents",
            "knowledge_documents_connection_id_title_unique",
            "UNIQUE (connection_id, title)",
        ),
        (
            "dictionary_entries",
            "dictionary_entries_column_id_raw_value_unique",
            "UNIQUE (column_id, raw_value)",
        ),
    ]
    tables_with_uuid_id = [
        "glossary_terms",
        "metric_definitions",
        "sample_queries",
        "knowledge_documents",
        "dictionary_entries",
        "cached_relationships",
    ]
    print("  Ensuring schema prerequisites for upsert...")
    with conn.cursor() as cur:
        for tbl in tables_with_uuid_id:
            cur.execute(
                """
                SELECT column_default FROM information_schema.columns
                WHERE table_name = %s AND column_name = 'id' AND column_default IS NULL
                """,
                (tbl,),
            )
            if cur.fetchone():
                cur.execute(
                    f"ALTER TABLE {tbl} ALTER COLUMN id SET DEFAULT gen_random_uuid()"
                )
                print(f"    + Added id DEFAULT to: {tbl}")
            else:
                print(f"    = id DEFAULT exists: {tbl}")

        for _tbl, constraint_name, _def in constraints:
            cur.execute(
                "SELECT 1 FROM pg_constraint WHERE conname = %s",
                (constraint_name,),
            )
            if not cur.fetchone():
                cur.execute(f"ALTER TABLE {_tbl} ADD CONSTRAINT {constraint_name} {_def}")
                print(f"    + Added constraint: {constraint_name}")
            else:
                print(f"    = Constraint exists: {constraint_name}")


def _upsert_glossary(conn, connection_id: UUID) -> None:
    if not GLOSSARY_TERMS:
        print("\n--- Glossary: nothing to seed (GLOSSARY_TERMS is empty) ---")
        return

    print(f"\n--- Seeding {len(GLOSSARY_TERMS)} Glossary Terms ---")
    ok = fail = 0
    with conn.cursor() as cur:
        for term_data in GLOSSARY_TERMS:
            try:
                cur.execute(
                    """
                    INSERT INTO glossary_terms
                        (connection_id, term, definition, sql_expression,
                         related_tables, related_columns, examples)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (connection_id, term) DO UPDATE SET
                        definition   = EXCLUDED.definition,
                        sql_expression = EXCLUDED.sql_expression,
                        related_tables = EXCLUDED.related_tables,
                        related_columns = EXCLUDED.related_columns,
                        examples = EXCLUDED.examples,
                        updated_at = NOW()
                    """,
                    (
                        str(connection_id),
                        term_data["term"],
                        term_data["definition"],
                        term_data["sql_expression"],
                        term_data.get("related_tables"),
                        term_data.get("related_columns"),
                        json.dumps(term_data.get("examples", [])),
                    ),
                )
                ok += 1
            except Exception as e:
                print(f"  ! {term_data['term']} — {e}")
                fail += 1
    print(f"  Glossary: {ok} upserted, {fail} failed")


def _upsert_metrics(conn, connection_id: UUID) -> None:
    if not METRICS:
        print("\n--- Metrics: nothing to seed (METRICS is empty) ---")
        return

    print(f"\n--- Seeding {len(METRICS)} Metrics ---")
    ok = fail = 0
    with conn.cursor() as cur:
        for metric_data in METRICS:
            try:
                cur.execute(
                    """
                    INSERT INTO metric_definitions
                        (connection_id, metric_name, display_name, description,
                         sql_expression, aggregation_type, related_tables,
                         dimensions, filters)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (connection_id, metric_name) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        description  = EXCLUDED.description,
                        sql_expression = EXCLUDED.sql_expression,
                        aggregation_type = EXCLUDED.aggregation_type,
                        related_tables = EXCLUDED.related_tables,
                        dimensions = EXCLUDED.dimensions,
                        filters    = EXCLUDED.filters,
                        updated_at  = NOW()
                    """,
                    (
                        str(connection_id),
                        metric_data["metric_name"],
                        metric_data["display_name"],
                        metric_data.get("description"),
                        metric_data["sql_expression"],
                        metric_data.get("aggregation_type"),
                        metric_data.get("related_tables"),
                        metric_data.get("dimensions"),
                        json.dumps(metric_data.get("filters", {})),
                    ),
                )
                ok += 1
            except Exception as e:
                print(f"  ! {metric_data['metric_name']} — {e}")
                fail += 1
    print(f"  Metrics: {ok} upserted, {fail} failed")


def _upsert_sample_queries(conn, connection_id: UUID) -> None:
    if not SAMPLE_QUERIES:
        print("\n--- Sample Queries: nothing to seed (SAMPLE_QUERIES is empty) ---")
        return

    print(f"\n--- Seeding {len(SAMPLE_QUERIES)} Sample Queries ---")
    ok = fail = 0
    with conn.cursor() as cur:
        for sq in SAMPLE_QUERIES:
            try:
                cur.execute(
                    """
                    INSERT INTO sample_queries
                        (connection_id, natural_language, sql_query,
                         description, tags, is_validated)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (connection_id, natural_language) DO UPDATE SET
                        sql_query     = EXCLUDED.sql_query,
                        description   = EXCLUDED.description,
                        tags          = EXCLUDED.tags,
                        is_validated  = EXCLUDED.is_validated,
                        updated_at    = NOW()
                    """,
                    (
                        str(connection_id),
                        sq["natural_language"],
                        sq["sql_query"],
                        sq.get("description"),
                        sq.get("tags"),
                        sq.get("is_validated", True),
                    ),
                )
                ok += 1
            except Exception as e:
                print(f"  ! {sq['natural_language'][:60]} — {e}")
                fail += 1
    print(f"  Sample Queries: {ok} upserted, {fail} failed")


def _chunk_words(text: str, max_words: int = 450, overlap_words: int = 80) -> list[str]:
    """Split text into overlapping word-based chunks (matches knowledge_service logic)."""
    words = text.split()
    if not words:
        return []
    if len(words) <= max_words:
        return [" ".join(words)]
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(0, end - overlap_words)
    return chunks


def _get_embedding(conn, text: str) -> list[float] | None:
    """Generate embedding for a text string using the configured provider.

    Calls the backend's embedding service via a subprocess to reuse the
    existing provider logic.  Falls back to None on failure.
    """
    try:
        import httpx

        resp = httpx.post(
            "http://localhost:8000/api/v1/embeddings/generate",
            json={"text": text},
            timeout=30.0,
        )
        if resp.status_code == 200:
            return resp.json().get("embedding")
    except Exception:
        pass
    return None


def _upsert_knowledge(conn, connection_id: UUID) -> None:
    if not KNOWLEDGE_DOCS:
        print("\n--- Knowledge: nothing to seed (KNOWLEDGE_DOCS is empty) ---")
        return

    print(f"\n--- Seeding {len(KNOWLEDGE_DOCS)} Knowledge Documents ---")
    ok = fail = 0
    with conn.cursor() as cur:
        for doc in KNOWLEDGE_DOCS:
            try:
                # Delete existing chunks for this doc (on re-seed)
                cur.execute(
                    """
                    DELETE FROM knowledge_chunks
                    USING knowledge_documents kd
                    WHERE knowledge_chunks.document_id = kd.id
                      AND kd.connection_id = %s
                      AND kd.title = %s
                    """,
                    (str(connection_id), doc["title"]),
                )

                # Upsert the document
                cur.execute(
                    """
                    INSERT INTO knowledge_documents
                        (connection_id, title, source_url, content, chunk_count)
                    VALUES (%s, %s, %s, %s, 0)
                    ON CONFLICT (connection_id, title) DO UPDATE SET
                        source_url   = EXCLUDED.source_url,
                        content      = EXCLUDED.content,
                        updated_at   = NOW()
                    RETURNING id
                    """,
                    (
                        str(connection_id),
                        doc["title"],
                        doc.get("source_url"),
                        doc["content"],
                    ),
                )
                doc_id = cur.fetchone()[0]

                # Create chunks
                chunk_texts = _chunk_words(doc["content"])
                chunk_count = 0
                for idx, chunk_text in enumerate(chunk_texts):
                    chunk_id = uuid.uuid4()
                    cur.execute(
                        """
                        INSERT INTO knowledge_chunks
                            (id, document_id, chunk_index, content, content_hash)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            str(chunk_id),
                            str(doc_id),
                            idx,
                            chunk_text,
                            hashlib.md5(
                                f"{connection_id}:{doc.get('source_url', '')}:{chunk_text}".encode()
                            ).hexdigest(),
                        ),
                    )
                    chunk_count += 1

                # Update chunk_count on the document
                cur.execute(
                    """
                    UPDATE knowledge_documents SET chunk_count = %s WHERE id = %s
                    """,
                    (chunk_count, str(doc_id)),
                )

                print(f"  {doc['title']}: {chunk_count} chunks created")
                ok += 1
            except Exception as e:
                print(f"  ! {doc['title']} — {e}")
                fail += 1
    print(f"  Knowledge: {ok} upserted, {fail} failed")
    print("  Note: Run reembed script or trigger embed from UI to generate chunk embeddings.")


def _upsert_dictionary(conn, connection_id: UUID) -> None:
    if not DICTIONARY_ENTRIES:
        print("\n--- Dictionary: nothing to seed (DICTIONARY_ENTRIES is empty) ---")
        return

    print(f"\n--- Seeding Dictionary Entries for {len(DICTIONARY_ENTRIES)} columns ---")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cc.id, ct.table_name, cc.column_name
            FROM cached_columns cc
            JOIN cached_tables ct ON cc.table_id = ct.id
            WHERE ct.connection_id = %s
            """,
            (str(connection_id),),
        )
        rows = cur.fetchall()
        if not rows:
            print("  WARNING: No cached schema found. Run introspection first.")
            print("  Skipping dictionary entries.")
            return

        col_map: dict[tuple[str, str], str] = {
            (str(r[1]), str(r[2])): str(r[0]) for r in rows
        }
        print(f"  Found {len(col_map)} columns in schema cache.")

    ok = col_skip = fail = 0
    with conn.cursor() as cur:
        for (table_name, column_name), entries in DICTIONARY_ENTRIES.items():
            col_id = col_map.get((table_name, column_name))
            if not col_id:
                print(
                    f"  ! {table_name}.{column_name} — not found in schema cache "
                    "(run introspection first)"
                )
                col_skip += 1
                continue

            for entry_data in entries:
                try:
                    cur.execute(
                        """
                        INSERT INTO dictionary_entries
                            (column_id, raw_value, display_value, description, sort_order)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (column_id, raw_value) DO UPDATE SET
                            display_value = EXCLUDED.display_value,
                            description   = EXCLUDED.description,
                            sort_order    = EXCLUDED.sort_order
                        """,
                        (
                            col_id,
                            entry_data["raw_value"],
                            entry_data["display_value"],
                            entry_data.get("description"),
                            entry_data.get("sort_order", 0),
                        ),
                    )
                    ok += 1
                except Exception as e:
                    conn.execute("ROLLBACK")
                    print(f"  ! {table_name}.{column_name}[{entry_data['raw_value']}] — {e}")
                    fail += 1

    print(
        f"  Dictionary: {ok} upserted, {fail} failed, {col_skip} columns not found"
    )


def _upsert_relationships(conn, connection_id: UUID) -> None:
    if not RELATIONSHIPS:
        print("\n--- Relationships: nothing to seed (RELATIONSHIPS is empty) ---")
        return

    print(f"\n--- Seeding {len(RELATIONSHIPS)} Manual Relationships ---")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, table_name FROM cached_tables WHERE connection_id = %s
            """,
            (str(connection_id),),
        )
        rows = cur.fetchall()
        if not rows:
            print("  WARNING: No cached schema found. Run introspection first.")
            print("  Skipping relationships.")
            return

        table_map: dict[str, str] = {str(r[1]): str(r[0]) for r in rows}
        print(f"  Found {len(table_map)} tables in schema cache.")

    ok = unavailable = fail = 0
    with conn.cursor() as cur:
        for rel in RELATIONSHIPS:
            src_id = table_map.get(rel["source_table"])
            tgt_id = table_map.get(rel["target_table"])

            missing = [
                t for t in [rel["source_table"], rel["target_table"]]
                if t not in table_map
            ]
            if missing:
                key = rel.get("constraint_name") or f"{rel['source_table']}.{rel['source_column']}"
                print(f"  - {key} (skipped — table not in cache: {', '.join(missing)})")
                unavailable += 1
                continue

            try:
                cur.execute(
                    """
                    INSERT INTO cached_relationships
                        (connection_id, constraint_name, is_manual,
                         relationship_type, source_table_id, source_column,
                         target_table_id, target_column)
                    VALUES (%s, %s, true, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        str(connection_id),
                        rel.get("constraint_name"),
                        rel.get("relationship_type"),
                        src_id,
                        rel["source_column"],
                        tgt_id,
                        rel["target_column"],
                    ),
                )
                if cur.rowcount > 0:
                    ok += 1
                    print(
                        f"  + {rel['source_table']}.{rel['source_column']} "
                        f"-> {rel['target_table']}.{rel['target_column']}"
                    )
                else:
                    key = rel.get("constraint_name") or f"{rel['source_table']}.{rel['source_column']}"
                    print(f"  = {key} (already exists)")
            except Exception as e:
                conn.execute("ROLLBACK")
                print(f"  ! {rel.get('constraint_name', rel['source_table'])} — {e}")
                fail += 1

    print(
        f"  Relationships: {ok} created, {unavailable} unavailable (no schema), {fail} failed"
    )


def _purge_connection(conn, connection_id: UUID) -> None:
    """Delete ALL semantic metadata for a connection (chunks, docs, dicts, glossary, metrics, samples, relationships)."""
    cid = str(connection_id)
    print(f"\n--- Purging ALL metadata for connection {cid[:8]}... ---")
    with conn.cursor() as cur:
        # Order matters due to FK constraints
        cur.execute(
            "DELETE FROM knowledge_chunks USING knowledge_documents kd "
            "WHERE knowledge_chunks.document_id = kd.id AND kd.connection_id = %s",
            (cid,),
        )
        n_chunks = cur.rowcount
        cur.execute("DELETE FROM knowledge_documents WHERE connection_id = %s", (cid,))
        n_docs = cur.rowcount
        cur.execute("DELETE FROM dictionary_entries WHERE column_id IN (SELECT cc.id FROM cached_columns cc JOIN cached_tables ct ON cc.table_id = ct.id WHERE ct.connection_id = %s)", (cid,))
        n_dict = cur.rowcount
        cur.execute("DELETE FROM glossary_terms WHERE connection_id = %s", (cid,))
        n_glossary = cur.rowcount
        cur.execute("DELETE FROM metric_definitions WHERE connection_id = %s", (cid,))
        n_metrics = cur.rowcount
        cur.execute("DELETE FROM sample_queries WHERE connection_id = %s", (cid,))
        n_samples = cur.rowcount
        cur.execute("DELETE FROM cached_relationships WHERE connection_id = %s", (cid,))
        n_rels = cur.rowcount
    print(
        f"  Purged: {n_chunks} chunks, {n_docs} docs, {n_dict} dict entries, "
        f"{n_glossary} glossary, {n_metrics} metrics, {n_samples} samples, {n_rels} relationships"
    )


def main() -> None:
    env = _load_env()

    # Parse CLI flags
    import argparse

    parser = argparse.ArgumentParser(description="Seed QueryWise semantic metadata")
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete ALL semantic metadata for the connection before seeding",
    )
    args = parser.parse_args()

    database_url = env.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not found in .env")
        print("  Set DATABASE_URL in your .env file (postgresql:// or postgresql+asyncpg://)")
        sys.exit(1)

    connection_name = env.get("SEED_CONNECTION_NAME")
    if not connection_name:
        print("ERROR: SEED_CONNECTION_NAME not found in .env")
        print("  Set SEED_CONNECTION_NAME to the name of your SQL Server connection in QueryWise.")
        sys.exit(1)

    print("QueryWise SQL Server Metadata Seeder")
    database_url_sync = database_url.replace("postgresql+asyncpg://", "postgresql://")
    db_display = database_url_sync.split("@")[0] + "@..." if "@" in database_url_sync else database_url_sync
    print(f"  DATABASE_URL: {db_display}")
    print(f"  Connection:    {connection_name}")

    try:
        conn = psycopg.connect(database_url_sync)
        print("  Connected to PostgreSQL.")
    except Exception as e:
        print(f"ERROR: Cannot connect to PostgreSQL: {e}")
        sys.exit(1)

    connection_id = _get_connection_id(conn, connection_name)
    print(f"  Connection ID: {connection_id}")

    try:
        if args.purge:
            _purge_connection(conn, connection_id)
        _ensure_constraints(conn)
        _upsert_glossary(conn, connection_id)
        _upsert_metrics(conn, connection_id)
        _upsert_sample_queries(conn, connection_id)
        _upsert_knowledge(conn, connection_id)
        _upsert_dictionary(conn, connection_id)
        _upsert_relationships(conn, connection_id)
        conn.commit()
        print("\nDone. All data committed.")
        print("  Embeddings will generate in background - run reembed script or trigger from UI.")
    except Exception as e:
        conn.rollback()
        print(f"\nERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
