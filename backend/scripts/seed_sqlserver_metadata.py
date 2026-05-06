#!/usr/bin/env python3
"""
Seed semantic metadata for your Azure SQL Server connection into QueryWise.

This script populates the four layers of the semantic layer:
  1. Glossary  — business terms → definitions + SQL expressions
  2. Metrics   — named KPIs with SQL expressions and dimensions
  3. Dictionary — raw column values → human-readable labels
  4. Knowledge  — free-text business context documents

Usage:
    # From the repo root, while docker compose is running:
    docker compose exec backend python scripts/seed_sqlserver_metadata.py

    # Or locally (needs httpx):
    pip install httpx
    python backend/scripts/seed_sqlserver_metadata.py

    # Target a different backend URL:
    python backend/scripts/seed_sqlserver_metadata.py --base-url http://localhost:8000

    # Target a specific connection by name (default: picks the first sqlserver connection):
    python backend/scripts/seed_sqlserver_metadata.py --connection-name "My Azure DB"

HOW TO FILL THIS IN:
    1. Run introspection in the UI (Connections → introspect icon) so your
       tables and columns are cached.
    2. Edit GLOSSARY_TERMS, METRICS, DICTIONARY_ENTRIES, and KNOWLEDGE_DOCS
       below to match your schema.
    3. Run this script — it is idempotent-safe (will report errors on duplicate
       unique constraint violations but won't crash).

DICTIONARY ENTRIES NOTE:
    Dictionary entries are keyed by (table_name, column_name). The table_name
    must match exactly what was introspected (case-sensitive). Run:
        GET /api/v1/connections/{id}/tables
    to see the exact table names that were cached.
"""

from __future__ import annotations

import argparse
import sys

import httpx

API_PREFIX = "/api/v1"


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
        "term": "Resource",
        "definition": "An individual employee or workforce member who performs tasks and logs work in the system.",
        "sql_expression": "Resource.ResourceId",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.ResourceId"],
        "examples": ["SELECT * FROM Resource WHERE IsActive = 1"],
    },
    {
        "term": "Active Resource",
        "definition": "A resource who is currently active and part of the organization.",
        "sql_expression": "CASE WHEN Resource.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.IsActive"],
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
        "term": "Date of Joining",
        "definition": "The date on which the resource joined the organization.",
        "sql_expression": "Resource.DateOfJoin",
        "related_tables": ["Resource"],
        "related_columns": ["Resource.DateOfJoin"],
    },
    {
        "term": "Client",
        "definition": "An external organization or customer for whom services are delivered.",
        "sql_expression": "Client.ClientId",
        "related_tables": ["Client"],
        "related_columns": ["Client.ClientId"],
        "examples": ["SELECT * FROM Client WHERE IsActive = 1"],
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
        "term": "Client Start Date",
        "definition": "The actual start date of engagement with the client.",
        "sql_expression": "Client.ActualStartDate",
        "related_tables": ["Client"],
        "related_columns": ["Client.ActualStartDate"],
    },
    {
        "term": "Client End Date",
        "definition": "The actual end date of engagement with the client.",
        "sql_expression": "Client.ActualEndDate",
        "related_tables": ["Client"],
        "related_columns": ["Client.ActualEndDate"],
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
        "term": "City",
        "definition": "Geographical city associated with clients or resources.",
        "sql_expression": "cities.cityID",
        "related_tables": ["cities"],
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
        "term": "Company Type",
        "definition": "Classification of a client organization based on its business nature or structure.",
        "sql_expression": "CompanyType.CompanyTypeId",
        "related_tables": ["CompanyType"],
        "related_columns": ["CompanyType.CompanyTypeId"],
    },
    {
        "term": "Active Company Type",
        "definition": "A company type that is currently valid and in use.",
        "sql_expression": "CASE WHEN CompanyType.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["CompanyType"],
        "related_columns": ["CompanyType.IsActive"],
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
        "term": "Project",
        "definition": "A client engagement or initiative under which work is planned, executed, and tracked.",
        "sql_expression": "Project.ProjectId",
        "related_tables": ["Project"],
        "related_columns": ["Project.ProjectId"],
        "examples": ["SELECT * FROM Project WHERE IsActive = 1"],
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
        "sql_expression": "CASE WHEN ProjectResource.Shadow = 1 THEN 1 ELSE 0 END",
        "related_tables": ["ProjectResource"],
        "related_columns": ["ProjectResource.Shadow"],
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
        "sql_expression": "CASE WHEN ProjectResource.Bench = 1 THEN 1 ELSE 0 END",
        "related_tables": ["ProjectResource"],
        "related_columns": ["ProjectResource.Bench"],
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
        "term": "Resource Status",
        "definition": "Availability status of a resource such as Active or Inactive.",
        "sql_expression": "Status.StatusName",
        "related_tables": ["Status"],
        "related_columns": ["Status.StatusName", "Status.ReferenceId"],
    },
    {
        "term": "Email Queue Status",
        "definition": "Processing status of email queue items such as Pending, Success, or Error.",
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
        "term": "Active Technology Category",
        "definition": "A technology category that is currently active and available for use.",
        "sql_expression": "CASE WHEN TechCatagory.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["TechCatagory"],
        "related_columns": ["TechCatagory.IsActive"],
    },
    {
        "term": "Technology Category Function Mapping",
        "definition": "Mapping of a technology category to one or more functions using FunctionIds.",
        "sql_expression": "TechCatagory.FunctionIds",
        "related_tables": ["TechCatagory"],
        "related_columns": ["TechCatagory.FunctionIds"],
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
        "term": "Active Technology Function",
        "definition": "A technology function that is currently active and usable.",
        "sql_expression": "CASE WHEN TechFunction.IsActive = 1 THEN 1 ELSE 0 END",
        "related_tables": ["TechFunction"],
        "related_columns": ["TechFunction.IsActive"],
    },
    {
        "term": "Function Organization Mapping",
        "definition": "Mapping of technology function to one or more organizations.",
        "sql_expression": "TechFunction.OrganizationIds",
        "related_tables": ["TechFunction"],
        "related_columns": ["TechFunction.OrganizationIds"],
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
    },
    {
        "term": "Employee",
        "definition": "An employee refers to a resource in the system.",
        "sql_expression": "Resource.ResourceId",
        "related_tables": ["Resource"],
    },
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
        "sql_expression": "COUNT(Resource.ResourceId)",
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
        "sql_expression": "SUM(CASE WHEN ProjectResource.Bench = 1 THEN 1 ELSE 0 END)",
        "aggregation_type": "sum",
        "related_tables": ["ProjectResource"],
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
    ("Client", "LeaveClauseConfirmed"): [
        {
            "raw_value": "0",
            "display_value": "Not Confirmed",
            "description": "Leave clause not confirmed",
            "sort_order": 1,
        },
        {
            "raw_value": "1",
            "display_value": "Confirmed",
            "description": "Leave clause confirmed",
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
This system represents a Project Resource Management System (PRMS) designed to manage clients, projects, resources, and their work tracking (EOD/timesheet entries).

CORE ENTITIES:

1. CLIENT
The Client table represents external business clients. Each client is uniquely identified by ClientId.
Clients are associated with Business Units, Organizations, and Functional domains.
Clients include billing configurations such as MonthlyBillingRate, WeeklyBillingRate, and HourlyBillingRate.

A client is considered valid for reporting only when IsActive = 1.

There are two interpretations of client status:
- System Status: Controlled by Client.IsActive (1 = Active, 0 = Inactive)
- Business Status: Derived from Status table via StatusId (e.g., Active, Inactive, Closed)

2. PROJECT
The Project table represents engagements executed for clients.
Each project is linked to:
- Client (ClientId)
- Business Unit (BusinessUnitId)
- Function (FunctionId)

Projects include planned and actual timelines:
- StartDate / EndDate (planned)
- ActualStartDate / ActualEndDate (execution)

Project status is derived from Status table using ProjectStatusId.

3. RESOURCE
The Resource table represents employees or workforce members.
Each resource has:
- EmployeeId (business identifier)
- ResourceName
- Designation, Role, and Reporting hierarchy

A resource is considered active when IsActive = 1.

Resources are associated with:
- Business Units
- Skills (Primaryskill, Secondaryskill)
- Functional roles (FunctionId, DesignatedRoleId)

4. PROJECT RESOURCE (ALLOCATION LAYER)
The ProjectResource table maps resources to projects.

It defines:
- Allocation percentage (PercentageAllocation)
- Billing status (Billable / Non-billable)
- Engagement duration (StartDate, EndDate)
- Billing rates (Rate, HourlyBillingRate)

Special flags:
- Bench = 1 → resource not allocated to active work
- Shadow = 1 → non-primary assignment
- Billable = 1 → revenue-generating allocation

This table is the foundation for utilization and billing calculations.

5. TIMESHEET / EOD (TS_EODDetails)
The TS_EODDetails table captures daily work logs.

Each entry includes:
- Resource (ResourceId, ResourceName)
- Project and task details
- Hours worked (Hrs)
- Completion tracking (Completion, CompletionPercent)

Approval workflow:
- IsApproved = 1 → approved entry
- IsRejected = 1 → rejected entry
- IsDeleted = 1 → logically deleted entry

Only valid work entries should satisfy:
IsApproved = 1 AND IsDeleted = 0 AND IsRejected = 0

These rules must be consistently applied in all reporting metrics.

6. STATUS SYSTEM
The Status table is a shared lookup table used across:
- Client
- Project
- Resource
- Other modules

ReferenceId differentiates status domains:
- 1 → Client Status
- 2 → Project Status
- 3 → Resource Status
- 4 → Email Queue Status

Important:
The same StatusName (e.g., "Active") can exist in multiple domains.
Therefore, status interpretation must always consider ReferenceId.

7. ORGANIZATIONAL STRUCTURE

- BusinessUnit → logical grouping of operations
- Organization → higher-level grouping
- TechFunction → functional domain (e.g., engineering, analytics)

Entities like Client, Project, and Resource are linked to these structures.

8. LOCATION DATA

Geographic information is stored using:
- countries (countryID)
- cities (cityID)

These are reference tables used for address mapping.

9. CLASSIFICATION TABLES

Several tables act as lookup/reference systems:
- CategoryTable / CategoryType
- CompanyType
- Domain
- Designation / DesignatedRole
- TechCategory / TechFunction

These define classification hierarchies used across the system.

10. BILLING MODEL

Billing is defined at multiple levels:
- Client level (default rates)
- Project level (override rates)
- ProjectResource level (final billing rate)

Hierarchy:
ProjectResource > Project > Client

Billing calculations must respect this override order.

11. DATA VALIDITY RULES (CRITICAL)

The following filters are considered standard across reporting:

- Active records:
  IsActive = 1

- Valid EOD entries:
  IsApproved = 1 AND IsDeleted = 0 AND IsRejected = 0

- Active allocations:
  ProjectResource.IsActive = 1

These conditions must always be applied when computing metrics.

12. RELATIONSHIP SUMMARY

- Client → Project (1 to many)
- Project → ProjectResource (1 to many)
- Resource → ProjectResource (1 to many)
- Resource → TS_EODDetails (1 to many)
- Client → BusinessUnit / Organization / Function (many to one)

13. REPORTING PRINCIPLES

- Always filter inactive records unless explicitly required
- Avoid mixing system status (IsActive) with business status (StatusId)
- Prefer ProjectResource for allocation and billing analysis
- Prefer TS_EODDetails for work tracking and effort metrics

14. SEMANTIC LAYER USAGE

This knowledge document is used to:
- provide business context to the LLM
- ensure correct interpretation of metrics and glossary terms
- enforce consistent filtering and relationships

All metrics and glossary definitions must align with these rules.

STRICT SCHEMA ENFORCEMENT:

Only use tables and columns that exist in the database schema.

Do NOT generate or assume:
- Table names not present in the schema
- Columns not present in the schema

Examples of INVALID behavior:
- Using table 'EMP' if it does not exist
- Using column 'EmployeeName' if it does not exist

If the required data is not available in known tables, return no result instead of guessing.

QUERY SIMPLICITY RULE:

Always generate the simplest possible query that answers the question.

Avoid:
- unnecessary joins
- subqueries
- extra tables

Only include tables that are strictly required.

NO GUESSING RULE:

If a user query references an entity that cannot be mapped to a known table or column, do not infer or guess.

Instead:
- Use closest matching known table
OR
- Return that data is not available

Never invent schema elements.
        """.strip(),
    },
    {
        "title": "PRMS Join Rules and Status Lookup Guide",
        "content": """
CONFIRMED JOIN RULES FOR THE PRMS SQL SERVER SCHEMA

These rules are not enforced as database foreign keys but are confirmed correct
by the project team. Always use these join paths when generating SQL queries.

1. CLIENT STATUS LOOKUP
   Join path: Client.StatusId -> Status.StatusId WHERE Status.ReferenceId = 1
   SQL:
       JOIN [Status] ON [Client].[StatusId] = [Status].[StatusId]
                     AND [Status].[ReferenceId] = 1
   Notes:
   - Client.StatusId references Status.StatusId, NOT Status.ReferenceId
   - The ReferenceId = 1 filter restricts to client-domain status values
   - Do NOT join using Client.ClientId = Status.ReferenceId (wrong column)

2. PROJECT STATUS LOOKUP
   Join path: Project.ProjectStatusId -> Status.StatusId WHERE Status.ReferenceId = 2
   SQL:
       JOIN [Status] ON [Project].[ProjectStatusId] = [Status].[StatusId]
                     AND [Status].[ReferenceId] = 2
   Notes:
   - Projects use ProjectStatusId (not StatusId) to reference their status
   - The ReferenceId = 2 filter restricts to project-domain status values

3. PROJECT → CLIENT JOIN
   Join path: Project.ClientId -> Client.ClientId
   SQL:
       JOIN [Client] ON [Project].[ClientId] = [Client].[ClientId]
   Notes:
   - This is a standard parent-child join
   - Use Client.ClientName for the human-readable client name

4. RESOURCE SELF-JOIN (REPORTING HIERARCHY)
   Join path: Resource.ReportingTo -> Resource.ResourceId  (self-join)
   SQL:
       JOIN [Resource] AS [Manager]
            ON [Resource].[ReportingTo] = [Manager].[ResourceId]
   Notes:
   - ReportingTo stores the ResourceId of the direct manager
   - Use a table alias (e.g. Manager) for the manager side of the join
   - IsReportingPerson = 1 identifies resources who are managers
   - To list employees under a specific manager, filter: Manager.ResourceName = '<name>'

STATUS TABLE DOMAIN REFERENCE IDS

The Status table is shared across multiple modules. Always filter by ReferenceId:
  - ReferenceId = 1  → Client Status values (e.g. Active, Inactive, Closed)
  - ReferenceId = 2  → Project Status values
  - ReferenceId = 3  → Resource Status values
  - ReferenceId = 4  → Email Queue Status values

Never read a status without also filtering ReferenceId, or you will mix statuses
from different modules.

ENTITY STATUS vs ISACTIVE FLAG

Two concepts exist for status:
  a) IsActive (bit column on each entity table) — system-level active flag
  b) Status.StatusName via StatusId — business-level lifecycle status label

IsActive is a boolean flag. Status.StatusName is the descriptive label.
For "show active clients", use Client.IsActive = 1.
For "show client status", join to Status using the join rule above.
Do NOT confuse these two.

CLIENT NAME COLUMN

Always use Client.ClientName for the client name in queries.
Do NOT use Project_Details_PRMS.DFINT_ClientName — it is a denormalized copy.
For entity-level client questions, always query the Client table directly.

RESOURCE NAME COLUMN

Always use Resource.ResourceName for the employee or resource name.
For manager names in a self-join, use Manager.ResourceName (with alias).
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
        "sql_query": "SELECT COUNT(*) FROM Resource WHERE IsActive = 1",
        "description": "Total active workforce",
        "tags": ["resource"],
        "is_validated": True,
    },
    {
        "natural_language": "How many clients exist in the system?",
        "sql_query": "SELECT COUNT(*) FROM Client",
        "description": "Total clients",
        "tags": ["client"],
        "is_validated": True,
    },
    {
        "natural_language": "How many projects are currently active?",
        "sql_query": "SELECT COUNT(*) FROM Project WHERE IsActive = 1",
        "description": "Active projects count",
        "tags": ["project"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total number of timesheet entries?",
        "sql_query": "SELECT COUNT(*) FROM TS_EODDetails WHERE IsDeleted = 0",
        "description": "Total timesheet logs",
        "tags": ["timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total number of hours logged in the system?",
        "sql_query": "SELECT SUM(Hrs) FROM TS_EODDetails WHERE IsDeleted = 0",
        "description": "Total effort logged",
        "tags": ["timesheet"],
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
        "sql_query": "SELECT c.ClientName, COUNT(p.ProjectId) as Count FROM Client c JOIN Project p ON c.ClientId = p.ClientId GROUP BY c.ClientName",
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
        "sql_query": "SELECT COUNT(*) FROM ProjectResource WHERE Bench = 1 AND IsActive = 1",
        "description": "Unallocated resources",
        "tags": ["resource", "bench"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average allocation percentage per project?",
        "sql_query": "SELECT p.ProjectName, AVG(pr.PercentageAllocation) FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId GROUP BY p.ProjectName",
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
        "natural_language": "Which projects have no timesheet entries?",
        "sql_query": "SELECT p.ProjectName FROM Project p LEFT JOIN TS_EODDetails e ON p.ProjectName = e.Project WHERE e.ID IS NULL",
        "description": "Inactive projects",
        "tags": ["project"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have not logged any hours?",
        "sql_query": "SELECT r.ResourceName FROM Resource r LEFT JOIN TS_EODDetails e ON r.ResourceId = e.ResourceId WHERE e.ID IS NULL",
        "description": "Inactive resources",
        "tags": ["resource"],
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
        "sql_query": "SELECT r.ResourceName, SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 100.0 / SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY r.ResourceName",
        "description": "Resource utilization",
        "tags": ["resource", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients generate the highest revenue based on billable hours?",
        "sql_query": "SELECT e.ClientName, SUM(e.Hrs * c.HourlyBillingRate) as [Total Revenue] FROM TS_EODDetails e JOIN Client c ON e.ClientName = c.ClientName JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY e.ClientName ORDER BY 2 DESC",
        "description": "Revenue per client",
        "tags": ["client", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have more non-billable hours than billable hours?",
        "sql_query": "SELECT e.Project FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.Project HAVING SUM(CASE WHEN a.Billablestatus = 0 THEN e.Hrs ELSE 0 END) > SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END)",
        "description": "Loss-making projects",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are over-utilized beyond 160 hours per month?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE MONTH(e.ReportDate) = MONTH(GETDATE()) GROUP BY r.ResourceName HAVING SUM(e.Hrs) > 176",
        "description": "Over-utilized resources",
        "tags": ["resource", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are under-utilized below 80 hours per month?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE MONTH(e.ReportDate) = MONTH(GETDATE()) GROUP BY r.ResourceName HAVING SUM(e.Hrs) < 80",
        "description": "Under-utilized resources",
        "tags": ["resource", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the highest non-billable percentage?",
        "sql_query": "SELECT e.ClientName, SUM(CASE WHEN a.Billablestatus = 0 THEN e.Hrs ELSE 0 END) * 100.0 / SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.ClientName ORDER BY 2 DESC",
        "description": "Client inefficiency",
        "tags": ["client", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are contributing to the most number of clients?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT e.ClientName) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName ORDER BY 2 DESC",
        "description": "Client spread",
        "tags": ["resource", "client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have high effort but very few resources?",
        "sql_query": "SELECT e.Project, SUM(e.Hrs), COUNT(DISTINCT e.ResourceId) FROM TS_EODDetails e GROUP BY e.Project HAVING SUM(e.Hrs) > 100 AND COUNT(DISTINCT e.ResourceId) < 2",
        "description": "Dependency risk",
        "tags": ["project", "risk"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources generate the highest revenue contribution?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs * c.HourlyBillingRate) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN Client c ON e.ClientName = c.ClientName JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY r.ResourceName ORDER BY 2 DESC",
        "description": "Top revenue contributors",
        "tags": ["resource", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total effort logged per client per month?",
        "sql_query": "SELECT      e.ClientName,      DATENAME(month, e.ReportDate) as MonthName,      YEAR(e.ReportDate) as Year,      SUM(e.Hrs) as [Total Hours]  FROM TS_EODDetails e   GROUP BY      e.ClientName,      YEAR(e.ReportDate),      DATENAME(month, e.ReportDate), -- Added the exact expression here     MONTH(e.ReportDate)            -- Kept for correct chronological sorting ORDER BY      YEAR(e.ReportDate),      MONTH(e.ReportDate);",
        "description": "Monthly client effort trend",
        "tags": ["client", "timesheet"],
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
        "natural_language": "Which clients have the highest number of active projects?",
        "sql_query": "SELECT c.ClientName, COUNT(p.ProjectId) FROM Client c JOIN Project p ON c.ClientId = p.ClientId WHERE p.IsActive = 1 GROUP BY c.ClientName ORDER BY 2 DESC",
        "description": "Client engagement breadth",
        "tags": ["client", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have logged effort across multiple business units?",
        "sql_query": "SELECT r.ResourceName FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName HAVING COUNT(DISTINCT r.BusinessUnitId) > 1",
        "description": "Cross-BU work",
        "tags": ["resource", "business_unit"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total effort per designation?",
        "sql_query": "SELECT d.DesignationName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN Designation d ON r.DesignationId = d.DesignationId GROUP BY d.DesignationName",
        "description": "Effort by role",
        "tags": ["resource", "designation"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have not logged any hours in the current month?",
        "sql_query": "SELECT r.ResourceName FROM Resource r LEFT JOIN TS_EODDetails e ON r.ResourceId = e.ResourceId AND MONTH(e.ReportDate) = MONTH(GETDATE()) WHERE e.ID IS NULL",
        "description": "Inactive this month",
        "tags": ["resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have the highest billable to non-billable ratio?",
        "sql_query": "SELECT e.Project, SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 1.0 / NULLIF(SUM(CASE WHEN a.Billablestatus = 0 THEN e.Hrs ELSE 0 END),0) FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.Project ORDER BY 2 DESC",
        "description": "Project efficiency",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have logged hours continuously for more than 10 days?",
        "sql_query": "SELECT r.ResourceName FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName HAVING COUNT(DISTINCT e.ReportDate) > 10",
        "description": "Continuous work streak",
        "tags": ["resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total number of distinct activities logged?",
        "sql_query": "SELECT COUNT(DISTINCT Activity_Id) FROM TS_EODDetails",
        "description": "Activity diversity",
        "tags": ["activity"],
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
        "natural_language": "Which resources have worked with the highest number of stakeholders' clients?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT cs.ClientId) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN Client c ON e.ClientName = c.ClientName JOIN ClientStakeholder cs ON c.ClientId = cs.ClientId GROUP BY r.ResourceName ORDER BY 2 DESC",
        "description": "Stakeholder exposure",
        "tags": ["resource", "client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have declining effort compared to previous month?",
        "sql_query": "SELECT Project FROM (SELECT Project, MONTH(ReportDate) m, SUM(Hrs) hrs FROM TS_EODDetails GROUP BY Project, MONTH(ReportDate)) t GROUP BY Project HAVING MAX(CASE WHEN m = MONTH(GETDATE()) THEN hrs END) < MAX(CASE WHEN m = MONTH(GETDATE())-1 THEN hrs END)",
        "description": "Declining engagement",
        "tags": ["project", "trend"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have highest variance in daily effort?",
        "sql_query": "SELECT r.ResourceName, VAR(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName ORDER BY 2 DESC",
        "description": "Effort inconsistency",
        "tags": ["resource", "pattern"],
        "is_validated": True,
    },
    {
        "natural_language": "Which business units contribute most to revenue?",
        "sql_query": "SELECT bu.BusinessUnitName, SUM(e.Hrs * c.HourlyBillingRate) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId JOIN Client c ON e.ClientName = c.ClientName JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY bu.BusinessUnitName ORDER BY 2 DESC",
        "description": "Revenue by BU",
        "tags": ["business_unit", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are assigned to projects but have zero allocation percentage?",
        "sql_query": "SELECT DISTINCT r.ResourceName FROM ProjectResource pr JOIN Resource r ON pr.ResourceId = r.ResourceId WHERE pr.PercentageAllocation = 0",
        "description": "Invalid allocation",
        "tags": ["resource", "allocation"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the highest effort per stakeholder?",
        "sql_query": "SELECT c.ClientName, SUM(e.Hrs) * 1.0 / COUNT(cs.StakeholderId) FROM Client c JOIN TS_EODDetails e ON c.ClientName = e.ClientName JOIN ClientStakeholder cs ON c.ClientId = cs.ClientId GROUP BY c.ClientName",
        "description": "Stakeholder load",
        "tags": ["client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have highest number of distinct activity types?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT e.Activity_Id) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName ORDER BY 2 DESC",
        "description": "Skill diversity proxy",
        "tags": ["resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have effort logged but zero completion percentage?",
        "sql_query": "SELECT e.Project FROM TS_EODDetails e GROUP BY e.Project HAVING SUM(e.Hrs) > 0 AND AVG(CAST(e.CompletionPercent AS FLOAT)) = 0",
        "description": "Execution gap",
        "tags": ["project"],
        "is_validated": True,
    },
    {
        "natural_language": "How many active resources are currently in the organization?",
        "sql_query": "SELECT COUNT(*) FROM Resource WHERE IsActive = 1;",
        "description": "Gives total active employees/resources.",
        "tags": ["resource", "headcount", "active"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the distribution of resources across business units?",
        "sql_query": "SELECT bu.BusinessUnitName, COUNT(r.ResourceId) FROM Resource r LEFT JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId GROUP BY bu.BusinessUnitName;",
        "description": "Shows workforce allocation across business units.",
        "tags": ["resource", "business_unit"],
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
        "sql_query": "SELECT r.ResourceName FROM ProjectResource pr JOIN Resource r ON pr.ResourceId = r.ResourceId WHERE pr.Bench = 1;",
        "description": "Identifies unallocated or idle resources.",
        "tags": ["resource", "bench"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average tenure of employees?",
        "sql_query": "SELECT AVG(TenureInYears) FROM Resource;",
        "description": "Measures employee retention.",
        "tags": ["resource", "tenure"],
        "is_validated": True,
    },
    {
        "natural_language": "List all active clients.",
        "sql_query": "SELECT ClientName FROM Client WHERE IsActive = 1;",
        "description": "Fetches all currently active clients.",
        "tags": ["client"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total agreement value of all clients?",
        "sql_query": "SELECT SUM(AgreementValue) FROM Client;",
        "description": "Total revenue from agreements.",
        "tags": ["client", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the highest monthly billing rate?",
        "sql_query": "SELECT TOP 5 ClientName, MonthlyBillingRate FROM Client ORDER BY MonthlyBillingRate DESC;",
        "description": "Top revenue-generating clients.",
        "tags": ["client", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "List all projects along with their client names.",
        "sql_query": "SELECT p.ProjectName, c.ClientName FROM Project p JOIN Client c ON p.ClientId = c.ClientId;",
        "description": "Maps projects to clients.",
        "tags": ["project", "client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have exceeded their planned end date?",
        "sql_query": "SELECT ProjectName FROM Project WHERE ActualEndDate > EndDate;",
        "description": "Identifies delayed projects.",
        "tags": ["project", "delay"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average project duration?",
        "sql_query": "SELECT AVG(DATEDIFF(DAY, StartDate, EndDate)) FROM Project;",
        "description": "Measures project lifecycle.",
        "tags": ["project", "duration"],
        "is_validated": True,
    },
    {
        "natural_language": "Which project has the highest number of resources allocated?",
        "sql_query": "SELECT TOP 1 ProjectName, NumberOfResorces FROM Project ORDER BY NumberOfResorces DESC;",
        "description": "Identifies largest project by team size.",
        "tags": ["project", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "List all resources working on a specific project.",
        "sql_query": "SELECT r.ResourceName FROM ProjectResource pr JOIN Resource r ON pr.ResourceId = r.ResourceId WHERE pr.ProjectId = @ProjectId;",
        "description": "Project team composition.",
        "tags": ["project", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total billing generated from all project resources?",
        "sql_query": "SELECT SUM(Rate) FROM ProjectResource;",
        "description": "Revenue from resource billing.",
        "tags": ["billing", "finance"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have the highest allocation percentage?",
        "sql_query": "SELECT TOP 5 r.ResourceName, pr.PercentageAllocation FROM ProjectResource pr JOIN Resource r ON pr.ResourceId = r.ResourceId ORDER BY pr.PercentageAllocation DESC;",
        "description": "Identifies overloaded resources.",
        "tags": ["resource", "allocation"],
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
        "natural_language": "List all stakeholders for a given client.",
        "sql_query": "SELECT StakeholderName FROM ClientStakeholder WHERE ClientId = @ClientId;",
        "description": "Client communication mapping.",
        "tags": ["client", "stakeholder"],
        "is_validated": True,
    },
    {
        "natural_language": "Which business units generate the most revenue?",
        "sql_query": "SELECT BusinessUnitId, SUM(AgreementValue) FROM Client GROUP BY BusinessUnitId ORDER BY SUM(AgreementValue) DESC;",
        "description": "Revenue by business unit.",
        "tags": ["business_unit", "revenue"],
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
        "natural_language": "Which projects are currently ongoing?",
        "sql_query": "SELECT ProjectName FROM Project WHERE GETDATE() BETWEEN StartDate AND EndDate;",
        "description": "Active timeline-based projects.",
        "tags": ["project"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the distribution of resources by designation?",
        "sql_query": "SELECT d.DesignationName, COUNT(r.ResourceId) FROM Resource r JOIN Designation d ON r.DesignationId = d.DesignationId GROUP BY d.DesignationName;",
        "description": "Hierarchy distribution.",
        "tags": ["resource", "designation"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients belong to which domain?",
        "sql_query": "SELECT c.ClientName, d.DomainName FROM Client c JOIN Domain d ON c.DomainId = d.DomainId;",
        "description": "Client domain mapping.",
        "tags": ["client", "domain"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the count of projects per client?",
        "sql_query": "SELECT c.ClientName, COUNT(p.ProjectId) FROM Project p JOIN Client c ON p.ClientId = c.ClientId GROUP BY c.ClientName;",
        "description": "Client engagement level.",
        "tags": ["client", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources report to a specific manager?",
        "sql_query": "SELECT ResourceName FROM Resource WHERE ReportingTo = @ManagerId;",
        "description": "Reporting hierarchy.",
        "tags": ["resource", "hierarchy"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average billing rate per project?",
        "sql_query": "SELECT ProjectId, AVG(Rate) FROM ProjectResource GROUP BY ProjectId;",
        "description": "Project profitability metric.",
        "tags": ["billing", "project"],
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
        "natural_language": "How many inactive resources are there?",
        "sql_query": "SELECT COUNT(*) FROM Resource WHERE IsActive = 0;",
        "description": "Inactive workforce count.",
        "tags": ["resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total revenue generated per client along with number of projects and allocated resources?",
        "sql_query": "SELECT c.ClientName, SUM(pr.Rate) AS TotalRevenue, COUNT(DISTINCT p.ProjectId) AS ProjectCount, COUNT(DISTINCT pr.ResourceId) AS ResourceCount FROM Client c JOIN Project p ON c.ClientId = p.ClientId JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId GROUP BY c.ClientName;",
        "description": "Holistic client-level revenue and engagement view.",
        "tags": ["client", "revenue", "project", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which business units have the highest billable utilization?",
        "sql_query": "SELECT bu.BusinessUnitName, SUM(CASE WHEN pr.Billable = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS Utilization FROM ProjectResource pr JOIN BusinessUnit bu ON pr.BusinessUnitId = bu.BusinessUnitId GROUP BY bu.BusinessUnitName;",
        "description": "Measures billable efficiency by business unit.",
        "tags": ["business_unit", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "List all projects with their project manager, lead, and client details.",
        "sql_query": "SELECT p.ProjectName, pm.ResourceName AS ProjectManager, pl.ResourceName AS ProjectLead, c.ClientName FROM Project p LEFT JOIN Resource pm ON p.ProjectManagerId = pm.ResourceId LEFT JOIN Resource pl ON p.ProjectLeadId = pl.ResourceId LEFT JOIN Client c ON p.ClientId = c.ClientId;",
        "description": "Project ownership mapping.",
        "tags": ["project", "resource", "client"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average experience of resources working on each project?",
        "sql_query": "SELECT p.ProjectName, AVG(r.TotalYears) AS AvgExperience FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId JOIN Resource r ON pr.ResourceId = r.ResourceId GROUP BY p.ProjectName;",
        "description": "Project team maturity analysis.",
        "tags": ["project", "resource", "experience"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have projects across multiple business units?",
        "sql_query": "SELECT c.ClientName, COUNT(DISTINCT p.BusinessUnitId) AS BUCount FROM Client c JOIN Project p ON c.ClientId = p.ClientId GROUP BY c.ClientName HAVING COUNT(DISTINCT p.BusinessUnitId) > 1;",
        "description": "Cross-BU client spread.",
        "tags": ["client", "business_unit"],
        "is_validated": True,
    },
    {
        "natural_language": "List resources along with their skills and associated projects.",
        "sql_query": "SELECT r.ResourceName, s.Name AS SkillName, p.ProjectName FROM Resource r JOIN PA_ResourceSkills rs ON r.ResourceId = rs.ResourceId JOIN PA_Skills s ON rs.SkillId = s.SkillId LEFT JOIN ProjectResource pr ON r.ResourceId = pr.ResourceId LEFT JOIN Project p ON pr.ProjectId = p.ProjectId;",
        "description": "Skill-to-project mapping.",
        "tags": ["resource", "skills", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have the highest average billing rate per resource?",
        "sql_query": "SELECT p.ProjectName, AVG(pr.Rate) AS AvgRate FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId GROUP BY p.ProjectName ORDER BY AvgRate DESC;",
        "description": "High-value projects.",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the skill distribution across business units?",
        "sql_query": "SELECT bu.BusinessUnitName, s.Name, COUNT(*) FROM Resource r JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId JOIN PA_ResourceSkills rs ON r.ResourceId = rs.ResourceId JOIN PA_Skills s ON rs.SkillId = s.SkillId GROUP BY bu.BusinessUnitName, s.Name;",
        "description": "Skill concentration by BU.",
        "tags": ["skills", "business_unit"],
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
        "sql_query": "SELECT c.ClientName, p.ProjectName, SUM(pr.Rate) FROM Project p JOIN Client c ON p.ClientId = c.ClientId JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId GROUP BY c.ClientName, p.ProjectName;",
        "description": "Granular billing view.",
        "tags": ["billing", "client", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "Which domains generate the highest agreement value?",
        "sql_query": "SELECT d.DomainName, SUM(c.AgreementValue) FROM Client c JOIN Domain d ON c.DomainId = d.DomainId GROUP BY d.DomainName ORDER BY SUM(c.AgreementValue) DESC;",
        "description": "Domain-wise revenue.",
        "tags": ["domain", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "List all stakeholders mapped to projects through clients.",
        "sql_query": "SELECT p.ProjectName, cs.StakeholderName FROM Project p JOIN ClientStakeholder cs ON p.ClientId = cs.ClientId;",
        "description": "Stakeholder visibility per project.",
        "tags": ["project", "stakeholder"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have the lowest average resource experience?",
        "sql_query": "SELECT p.ProjectName, AVG(r.TotalYears) AS AvgExp FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId JOIN Resource r ON pr.ResourceId = r.ResourceId GROUP BY p.ProjectName ORDER BY AvgExp ASC;",
        "description": "Risky (low-experience) projects.",
        "tags": ["project", "risk"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the billing contribution by each resource within a project?",
        "sql_query": "SELECT p.ProjectName, r.ResourceName, pr.Rate FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId JOIN Resource r ON pr.ResourceId = r.ResourceId;",
        "description": "Resource-level billing contribution.",
        "tags": ["billing", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which business units have the most active projects?",
        "sql_query": "SELECT bu.BusinessUnitName, COUNT(p.ProjectId) FROM Project p JOIN BusinessUnit bu ON p.BusinessUnitId = bu.BusinessUnitId WHERE p.IsActive = 1 GROUP BY bu.BusinessUnitName;",
        "description": "BU activity comparison.",
        "tags": ["business_unit", "project"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are assigned to clients across multiple domains?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT c.DomainId) FROM Resource r JOIN ProjectResource pr ON r.ResourceId = pr.ResourceId JOIN Project p ON pr.ProjectId = p.ProjectId JOIN Client c ON p.ClientId = c.ClientId GROUP BY r.ResourceName HAVING COUNT(DISTINCT c.DomainId) > 1;",
        "description": "Cross-domain exposure.",
        "tags": ["resource", "domain"],
        "is_validated": True,
    },
    {
        "natural_language": "List all combinations of business units and domains (even if no mapping exists).",
        "sql_query": "SELECT bu.BusinessUnitName, d.DomainName FROM BusinessUnit bu CROSS JOIN Domain d;",
        "description": "Full matrix for strategic planning.",
        "tags": ["cross_join", "business_unit", "domain"],
        "is_validated": True,
    },
    {
        "natural_language": "List all combinations of skills and business units.",
        "sql_query": "SELECT s.Name, bu.BusinessUnitName FROM PA_Skills s CROSS JOIN BusinessUnit bu;",
        "description": "Skill coverage planning grid.",
        "tags": ["cross_join", "skills"],
        "is_validated": True,
    },
    {
        "natural_language": "Which combinations of project types and business units have no projects?",
        "sql_query": "SELECT pt.ProjectTypeName, bu.BusinessUnitName FROM ProjectType pt CROSS JOIN BusinessUnit bu LEFT JOIN Project p ON p.ProjectTypeId = pt.ProjectTypeId AND p.BusinessUnitId = bu.BusinessUnitId WHERE p.ProjectId IS NULL;",
        "description": "Gap analysis.",
        "tags": ["cross_join", "gap_analysis"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have no associated projects?",
        "sql_query": "SELECT c.ClientName FROM Client c LEFT JOIN Project p ON c.ClientId = p.ClientId WHERE p.ProjectId IS NULL;",
        "description": "Inactive clients.",
        "tags": ["client"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have skills but are not assigned to any project?",
        "sql_query": "SELECT r.ResourceName FROM Resource r JOIN PA_ResourceSkills rs ON r.ResourceId = rs.ResourceId LEFT JOIN ProjectResource pr ON r.ResourceId = pr.ResourceId WHERE pr.ProjectId IS NULL;",
        "description": "Underutilized skilled resources.",
        "tags": ["resource", "skills", "utilization"],
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
        "sql_query": "SELECT pm.ResourceName AS Manager, r.ResourceName AS Resource FROM Project p JOIN Resource pm ON p.ProjectManagerId = pm.ResourceId JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId JOIN Resource r ON pr.ResourceId = r.ResourceId;",
        "description": "Manager-team mapping.",
        "tags": ["resource", "hierarchy"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the distribution of resources across clients?",
        "sql_query": "SELECT c.ClientName, COUNT(DISTINCT pr.ResourceId) FROM Client c JOIN Project p ON c.ClientId = p.ClientId JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId GROUP BY c.ClientName;",
        "description": "Client staffing levels.",
        "tags": ["client", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have both billable and non-billable resources?",
        "sql_query": "SELECT p.ProjectName FROM Project p JOIN ProjectResource pr ON p.ProjectId = pr.ProjectId GROUP BY p.ProjectName HAVING SUM(CASE WHEN pr.Billable = 1 THEN 1 ELSE 0 END) > 0 AND SUM(CASE WHEN pr.Billable = 0 THEN 1 ELSE 0 END) > 0;",
        "description": "Mixed billing projects.",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average experience per skill?",
        "sql_query": "SELECT s.Name, AVG(rs.Experience) FROM PA_ResourceSkills rs JOIN PA_Skills s ON rs.SkillId = s.SkillId GROUP BY s.Name;",
        "description": "Skill maturity analysis.",
        "tags": ["skills", "experience"],
        "is_validated": True,
    },
    {
        "natural_language": "Which business units have the most diverse skill sets?",
        "sql_query": "SELECT bu.BusinessUnitName, COUNT(DISTINCT rs.SkillId) FROM Resource r JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId JOIN PA_ResourceSkills rs ON r.ResourceId = rs.ResourceId GROUP BY bu.BusinessUnitName ORDER BY COUNT(DISTINCT rs.SkillId) DESC;",
        "description": "Skill diversity by BU.",
        "tags": ["business_unit", "skills"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have stakeholders but no active projects?",
        "sql_query": "SELECT DISTINCT c.ClientName FROM Client c JOIN ClientStakeholder cs ON c.ClientId = cs.ClientId LEFT JOIN Project p ON c.ClientId = p.ClientId AND p.IsActive = 1 WHERE p.ProjectId IS NULL;",
        "description": "Dormant but engaged clients.",
        "tags": ["client", "stakeholder"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the allocation load per resource across all projects?",
        "sql_query": "SELECT r.ResourceName, SUM(pr.PercentageAllocation) FROM Resource r JOIN ProjectResource pr ON r.ResourceId = pr.ResourceId GROUP BY r.ResourceName;",
        "description": "Resource workload analysis.",
        "tags": ["resource", "allocation"],
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
        "sql_query": "SELECT c.ClientName, SUM(e.Hrs * c.HourlyBillingRate) AS EstimatedRevenue FROM TS_EODDetails e JOIN Client c ON e.ClientName = c.ClientName GROUP BY c.ClientName;",
        "description": "Revenue estimation using timesheets.",
        "tags": ["billing", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "Which business units have the highest average resource tenure?",
        "sql_query": "SELECT bu.BusinessUnitName, AVG(r.TenureInYears) FROM Resource r JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId GROUP BY bu.BusinessUnitName;",
        "description": "Experience maturity by BU.",
        "tags": ["resource", "business_unit"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients belong to which domains and company types?",
        "sql_query": "SELECT c.ClientName, d.DomainName, ct.CompanyTypeName FROM Client c LEFT JOIN Domain d ON c.DomainId = d.DomainId LEFT JOIN CompanyType ct ON c.CompanyTypeId = ct.CompanyTypeId;",
        "description": "Client segmentation view.",
        "tags": ["client", "domain"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the distribution of clients across countries and cities?",
        "sql_query": "SELECT co.countryName, ci.cityName, COUNT(c.ClientId) FROM Client c LEFT JOIN countries co ON c.CountryId = co.countryID LEFT JOIN cities ci ON c.CityId = ci.cityID GROUP BY co.countryName, ci.cityName;",
        "description": "Geographic distribution of clients.",
        "tags": ["client", "geo"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are mapped to which clients via timesheet entries?",
        "sql_query": "SELECT DISTINCT r.ResourceName, e.ClientName FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE e.IsDeleted = 0;",
        "description": "Resource-client interaction mapping.",
        "tags": ["resource", "client"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average completion percentage of tasks per project?",
        "sql_query": "SELECT e.Project, AVG(CAST(e.CompletionPercent AS FLOAT)) FROM TS_EODDetails e WHERE e.IsDeleted = 0 GROUP BY e.Project;",
        "description": "Project progress tracking.",
        "tags": ["project", "progress"],
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
        "natural_language": "Which clients have the highest agreement value per domain?",
        "sql_query": "SELECT d.DomainName, c.ClientName, c.AgreementValue FROM Client c JOIN Domain d ON c.DomainId = d.DomainId ORDER BY c.AgreementValue DESC;",
        "description": "High-value clients per domain.",
        "tags": ["client", "revenue"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average client satisfaction score per project?",
        "sql_query": "SELECT cr.ProjectId, AVG(cs.ClientSatisfactionScore) FROM ClientReview cr JOIN ClientSatisfaction cs ON cs.ClientSatisfactionId = cr.ClientId GROUP BY cr.ProjectId;",
        "description": "Project satisfaction trends.",
        "tags": ["client", "review"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have unapproved timesheet entries?",
        "sql_query": "SELECT DISTINCT r.ResourceName FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE e.IsApproved = 0;",
        "description": "Pending approvals.",
        "tags": ["resource", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the workload distribution by business unit using timesheet hours?",
        "sql_query": "SELECT bu.BusinessUnitName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId GROUP BY bu.BusinessUnitName;",
        "description": "Effort distribution across BUs.",
        "tags": ["business_unit", "effort"],
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
        "natural_language": "Which resources have skills that are not approved?",
        "sql_query": "SELECT r.ResourceName, s.Name FROM PA_ResourceSkills rs JOIN Resource r ON rs.ResourceId = r.ResourceId JOIN PA_Skills s ON rs.SkillId = s.SkillId WHERE rs.IsApproved = 0;",
        "description": "Skill validation gaps.",
        "tags": ["skills", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average experience per subskill?",
        "sql_query": "SELECT ss.Name, AVG(rs.SubSkillExperience) FROM PA_ResourceSkills rs JOIN PA_SubSkills ss ON rs.SubSkillId = ss.SubSkillId GROUP BY ss.Name;",
        "description": "Subskill depth analysis.",
        "tags": ["skills"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients use which payment methods and cycles?",
        "sql_query": "SELECT c.ClientName, pm.PaymentMethodName, pc.PaymentCycleName FROM Client c LEFT JOIN PaymentMethod pm ON c.PaymentMethodId = pm.PaymentMethodId LEFT JOIN PaymentCycle pc ON c.PaymentCycleId = pc.PaymentCycleId;",
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
        "natural_language": "What is the average effort logged per activity category?",
        "sql_query": "SELECT o.Dropdown_Description, AVG(e.Hrs) FROM TS_EODDetails e JOIN TS_SG_OEM_Master o ON e.OEM_Id = o.Dropdown_Identifier GROUP BY o.Dropdown_Description;",
        "description": "Category-level effort trends.",
        "tags": ["timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients have the longest business relationship duration?",
        "sql_query": "SELECT ClientName, DATEDIFF(YEAR, ActualStartDate, GETDATE()) AS Years FROM Client ORDER BY Years DESC;",
        "description": "Client longevity.",
        "tags": ["client"],
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
        "natural_language": "Which clients have stakeholders but no recent timesheet activity?",
        "sql_query": "SELECT DISTINCT c.ClientName FROM Client c JOIN ClientStakeholder cs ON c.ClientId = cs.ClientId LEFT JOIN TS_EODDetails e ON c.ClientName = e.ClientName AND e.ReportDate >= DATEADD(MONTH, -1, GETDATE()) WHERE e.ID IS NULL;",
        "description": "Inactive but engaged clients.",
        "tags": ["client"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the effort split between billable and non-billable activities?",
        "sql_query": "SELECT a.Billablestatus, SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY a.Billablestatus;",
        "description": "Billing efficiency.",
        "tags": ["billing"],
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
        "natural_language": "Which organizations have the most active resources?",
        "sql_query": "SELECT o.OrganizationName, COUNT(r.ResourceId) FROM Resource r JOIN Organization o ON r.OrganizationId = o.OrganizationId WHERE r.IsActive = 1 GROUP BY o.OrganizationName;",
        "description": "Org-level workforce.",
        "tags": ["organization"],
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
        "natural_language": "Which Jira tickets consume the most effort hours?",
        "sql_query": "SELECT j.SFID, SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_Jira_Master j ON e.Jira_Identifier = j.Jira_Identifier GROUP BY j.SFID ORDER BY SUM(e.Hrs) DESC;",
        "description": "Jira effort tracking.",
        "tags": ["jira", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average effort per project per month?",
        "sql_query": "SELECT e.Project, MONTH(e.ReportDate), AVG(e.Hrs) FROM TS_EODDetails e GROUP BY e.Project, MONTH(e.ReportDate);",
        "description": "Monthly effort trends.",
        "tags": ["project", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the total billable vs non-billable effort logged per resource?",
        "sql_query": "SELECT r.ResourceName, a.Billablestatus, SUM(e.Hrs) AS TotalHours FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY r.ResourceName, a.Billablestatus;",
        "description": "Resource-level billability breakdown.",
        "tags": ["timesheet", "billing", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have less than 50% billable utilization?",
        "sql_query": "SELECT r.ResourceName, SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 1.0 / SUM(e.Hrs) AS BillableRatio FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY r.ResourceName HAVING SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 1.0 / SUM(e.Hrs) < 0.5;",
        "description": "Identifies underperforming utilization.",
        "tags": ["utilization", "billing"],
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
        "natural_language": "Which projects have the highest non-billable effort?",
        "sql_query": "SELECT e.Project, SUM(e.Hrs) AS NonBillableHours FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 0 GROUP BY e.Project ORDER BY NonBillableHours DESC;",
        "description": "Non-billable leakage.",
        "tags": ["project", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the average daily hours logged per resource?",
        "sql_query": "SELECT r.ResourceName, AVG(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName;",
        "description": "Daily effort consistency.",
        "tags": ["timesheet", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are over-utilized (more than 9 hours per day on average)?",
        "sql_query": "SELECT r.ResourceName, AVG(e.Hrs) AS AvgHours FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName HAVING AVG(e.Hrs) > 9;",
        "description": "Overloaded resources.",
        "tags": ["utilization", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the utilization percentage per business unit based on timesheet hours?",
        "sql_query": "SELECT bu.BusinessUnitName, SUM(e.Hrs) / (COUNT(DISTINCT r.ResourceId) * 8.0 * 22) * 100 AS UtilizationPercent FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId GROUP BY bu.BusinessUnitName;",
        "description": "BU-level capacity utilization.",
        "tags": ["business_unit", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources have not logged any hours in the last 7 days?",
        "sql_query": "SELECT r.ResourceName FROM Resource r LEFT JOIN TS_EODDetails e ON r.ResourceId = e.ResourceId AND e.ReportDate >= DATEADD(DAY, -7, GETDATE()) WHERE e.ID IS NULL;",
        "description": "Inactive resources.",
        "tags": ["timesheet", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the project-wise effort split by activity type?",
        "sql_query": "SELECT e.Project, a.ActivityName, SUM(e.Hrs) FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.Project, a.ActivityName;",
        "description": "Effort categorization per project.",
        "tags": ["project", "activity"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources are working across multiple projects in the same week?",
        "sql_query": "SELECT r.ResourceName, COUNT(DISTINCT e.Project) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE e.ReportDate >= DATEADD(DAY, -7, GETDATE()) GROUP BY r.ResourceName HAVING COUNT(DISTINCT e.Project) > 1;",
        "description": "Multi-project allocation.",
        "tags": ["resource", "project"],
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
        "natural_language": "Which resources have the highest billable hours?",
        "sql_query": "SELECT r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE a.Billablestatus = 1 GROUP BY r.ResourceName ORDER BY SUM(e.Hrs) DESC;",
        "description": "Top billable contributors.",
        "tags": ["resource", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the ratio of billable to non-billable hours per client?",
        "sql_query": "SELECT e.ClientName, SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 1.0 / SUM(CASE WHEN a.Billablestatus = 0 THEN e.Hrs ELSE 0 END) AS Ratio FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY e.ClientName;",
        "description": "Client efficiency ratio.",
        "tags": ["client", "billing"],
        "is_validated": True,
    },
    {
        "natural_language": "Which projects have resources exceeding 100% allocation (more than 8 hours per day)?",
        "sql_query": "SELECT e.Project, r.ResourceName, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY e.Project, r.ResourceName HAVING SUM(e.Hrs) > 8;",
        "description": "Over-allocation detection.",
        "tags": ["project", "resource"],
        "is_validated": True,
    },
    {
        "natural_language": "What is the weekly utilization trend per project?",
        "sql_query": "SELECT e.Project, DATEPART(WEEK, e.ReportDate), SUM(e.Hrs) FROM TS_EODDetails e GROUP BY e.Project, DATEPART(WEEK, e.ReportDate);",
        "description": "Weekly effort trend.",
        "tags": ["project", "timesheet"],
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
        "natural_language": "What is the utilization trend of each resource over time?",
        "sql_query": "SELECT r.ResourceName, e.ReportDate, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName, e.ReportDate;",
        "description": "Daily utilization tracking.",
        "tags": ["resource", "timesheet"],
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
        "sql_query": "SELECT r.ResourceName, AVG(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName HAVING AVG(e.Hrs) < 4;",
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
        "natural_language": "Which managers have the highest team utilization?",
        "sql_query": "SELECT r.ReportingTo, SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ReportingTo ORDER BY SUM(e.Hrs) DESC;",
        "description": "Manager efficiency.",
        "tags": ["hierarchy", "utilization"],
        "is_validated": True,
    },
    {
        "natural_language": "Which resources log time on weekends?",
        "sql_query": "SELECT DISTINCT r.ResourceName FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE DATENAME(WEEKDAY, e.ReportDate) IN ('Saturday', 'Sunday');",
        "description": "Weekend workload.",
        "tags": ["timesheet", "resource"],
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
        "natural_language": "What is the monthly billable utilization trend per business unit?",
        "sql_query": "SELECT bu.BusinessUnitName, MONTH(e.ReportDate), SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) * 100.0 / SUM(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId JOIN BusinessUnit bu ON r.BusinessUnitId = bu.BusinessUnitId JOIN TS_Activity a ON e.Activity_Id = a.Id GROUP BY bu.BusinessUnitName, MONTH(e.ReportDate);",
        "description": "BU billing trends.",
        "tags": ["business_unit", "billing"],
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
        "natural_language": "What is the variance in daily logged hours per resource?",
        "sql_query": "SELECT r.ResourceName, VAR(e.Hrs) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY r.ResourceName;",
        "description": "Consistency of work patterns.",
        "tags": ["resource", "timesheet"],
        "is_validated": True,
    },
    {
        "natural_language": "Which clients are experiencing revenue leakage due to high non-billable effort?",
        "sql_query": "SELECT e.ClientName, SUM(CASE WHEN a.Billablestatus = 0 THEN e.Hrs ELSE 0 END) * c.HourlyBillingRate AS LeakageValue FROM TS_EODDetails e JOIN TS_Activity a ON e.Activity_Id = a.Id JOIN Client c ON e.ClientName = c.ClientName GROUP BY e.ClientName, c.HourlyBillingRate ORDER BY LeakageValue DESC;",
        "description": "Quantifies lost revenue due to non-billable work.",
        "tags": ["revenue", "leakage"],
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
        "natural_language": "Which resources are logging effort outside their primary skill areas?",
        "sql_query": "SELECT r.ResourceName, e.Project FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId LEFT JOIN PA_ResourceSkills rs ON r.ResourceId = rs.ResourceId WHERE rs.SkillId IS NULL;",
        "description": "Skill mismatch detection.",
        "tags": ["resource", "skills"],
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
        "natural_language": "Which resources have not logged billable hours despite being active?",
        "sql_query": "SELECT r.ResourceName FROM Resource r LEFT JOIN TS_EODDetails e ON r.ResourceId = e.ResourceId LEFT JOIN TS_Activity a ON e.Activity_Id = a.Id WHERE r.IsActive = 1 GROUP BY r.ResourceName HAVING SUM(CASE WHEN a.Billablestatus = 1 THEN e.Hrs ELSE 0 END) = 0;",
        "description": "Idle or misaligned resources.",
        "tags": ["resource", "billing"],
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
        "natural_language": "Which projects are dependent on resources with low experience?",
        "sql_query": "SELECT e.Project, AVG(r.TotalYears) FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId GROUP BY e.Project HAVING AVG(r.TotalYears) < 2;",
        "description": "Delivery risk due to inexperience.",
        "tags": ["project", "risk"],
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
        "natural_language": "Which resources are consistently logging hours on non-working days?",
        "sql_query": "SELECT r.ResourceName FROM TS_EODDetails e JOIN Resource r ON e.ResourceId = r.ResourceId WHERE DATENAME(WEEKDAY, e.ReportDate) IN ('Saturday','Sunday') GROUP BY r.ResourceName HAVING COUNT(*) > 10;",
        "description": "Sustained overtime pattern.",
        "tags": ["resource", "workload"],
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
    {
        "source_table": "Resource",
        "source_column": "CountryId",
        "target_table": "countries",
        "target_column": "countryID",
        "constraint_name": "FK_Resource_Country",
        "relationship_type": "hierarchical",
    },
    {
        "source_table": "Resource",
        "source_column": "StateId",
        "target_table": "states",
        "target_column": "stateID",
        "constraint_name": "FK_Resource_State",
        "relationship_type": "hierarchical",
    },
    {
        "source_table": "Resource",
        "source_column": "CityId",
        "target_table": "cities",
        "target_column": "cityID",
        "constraint_name": "FK_Resource_City",
        "relationship_type": "hierarchical",
    },
    # ── Geography hierarchy ───────────────────────────────────────────────────
    {
        "source_table": "states",
        "source_column": "countryID",
        "target_table": "countries",
        "target_column": "countryID",
        "constraint_name": "FK_State_Country",
        "relationship_type": "hierarchical",
    },
    {
        "source_table": "cities",
        "source_column": "stateID",
        "target_table": "states",
        "target_column": "stateID",
        "constraint_name": "FK_City_State",
        "relationship_type": "hierarchical",
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
        "source_column": "ProjectSubTypeId",
        "target_table": "ProjectSubType",
        "target_column": "ProjectSubTypeId",
        "constraint_name": "FK_Project_SubType",
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
        "source_column": "ReviewCycleId",
        "target_table": "ReviewCycle",
        "target_column": "ReviewId",
        "constraint_name": "FK_Project_Review",
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
    {
        "source_table": "Client",
        "source_column": "CountryId",
        "target_table": "countries",
        "target_column": "countryID",
        "constraint_name": "FK_Client_Country",
        "relationship_type": "hierarchical",
    },
    {
        "source_table": "Client",
        "source_column": "CityId",
        "target_table": "cities",
        "target_column": "cityID",
        "constraint_name": "FK_Client_City",
        "relationship_type": "hierarchical",
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
        "source_column": "Jira_Identifier",
        "target_table": "TS_Jira_Master",
        "target_column": "Jira_Identifier",
        "constraint_name": "FK_EOD_Jira",
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
# Seeding functions — no need to edit below this line
# =============================================================================


def find_connection(client: httpx.Client, connection_name: str | None) -> dict:
    """Find the target connection — by name if specified, else first sqlserver."""
    resp = client.get(f"{API_PREFIX}/connections")
    resp.raise_for_status()
    connections = resp.json()

    if not connections:
        print("ERROR: No connections found. Create and introspect a connection first.")
        sys.exit(1)

    if connection_name:
        match = next((c for c in connections if c["name"] == connection_name), None)
        if not match:
            names = [c["name"] for c in connections]
            print(f"ERROR: Connection '{connection_name}' not found. Available: {names}")
            sys.exit(1)
        return match

    # Default: prefer first sqlserver connection, fallback to first of any type
    sqlserver = next((c for c in connections if c["connector_type"] == "sqlserver"), None)
    target = sqlserver or connections[0]
    print(f"  Using connection: {target['name']} ({target['id']}, {target['connector_type']})")
    return target


def purge_glossary(client: httpx.Client, connection_id: str) -> None:
    """Delete every glossary term for this connection."""
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/glossary")
    if resp.status_code != 200:
        print(f"  ! Could not fetch glossary (HTTP {resp.status_code}) — skipping purge")
        return
    items = resp.json()
    if not items:
        print("  Glossary: nothing to purge")
        return
    deleted = fail = 0
    for item in items:
        del_resp = client.delete(f"{API_PREFIX}/connections/{connection_id}/glossary/{item['id']}")
        if del_resp.status_code in (200, 204):
            deleted += 1
        else:
            print(f"  ! {item['term']} — delete failed HTTP {del_resp.status_code}")
            fail += 1
    print(f"  Glossary: {deleted} deleted, {fail} failed")


def purge_metrics(client: httpx.Client, connection_id: str) -> None:
    """Delete every metric for this connection."""
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/metrics")
    if resp.status_code != 200:
        print(f"  ! Could not fetch metrics (HTTP {resp.status_code}) — skipping purge")
        return
    items = resp.json()
    if not items:
        print("  Metrics: nothing to purge")
        return
    deleted = fail = 0
    for item in items:
        del_resp = client.delete(f"{API_PREFIX}/connections/{connection_id}/metrics/{item['id']}")
        if del_resp.status_code in (200, 204):
            deleted += 1
        else:
            print(f"  ! {item['metric_name']} — delete failed HTTP {del_resp.status_code}")
            fail += 1
    print(f"  Metrics: {deleted} deleted, {fail} failed")


def purge_dictionary(client: httpx.Client, connection_id: str) -> None:
    """Delete every dictionary entry for every column in this connection."""
    tables_resp = client.get(f"{API_PREFIX}/connections/{connection_id}/tables")
    if tables_resp.status_code != 200:
        print(f"  ! Could not fetch tables (HTTP {tables_resp.status_code}) — skipping purge")
        return
    tables = tables_resp.json()
    deleted = fail = 0
    for table_summary in tables:
        detail_resp = client.get(f"{API_PREFIX}/tables/{table_summary['id']}")
        if detail_resp.status_code != 200:
            continue
        detail = detail_resp.json()
        for col in detail["columns"]:
            col_id = col["id"]
            entries_resp = client.get(f"{API_PREFIX}/columns/{col_id}/dictionary")
            if entries_resp.status_code != 200:
                continue
            for entry in entries_resp.json():
                del_resp = client.delete(f"{API_PREFIX}/columns/{col_id}/dictionary/{entry['id']}")
                if del_resp.status_code in (200, 204):
                    deleted += 1
                else:
                    fail += 1
    print(f"  Dictionary: {deleted} deleted, {fail} failed")


def purge_knowledge(client: httpx.Client, connection_id: str) -> None:
    """Delete every knowledge document for this connection."""
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/knowledge")
    if resp.status_code != 200:
        print(f"  ! Could not fetch knowledge (HTTP {resp.status_code}) — skipping purge")
        return
    items = resp.json()
    if not items:
        print("  Knowledge: nothing to purge")
        return
    deleted = fail = 0
    for item in items:
        del_resp = client.delete(f"{API_PREFIX}/connections/{connection_id}/knowledge/{item['id']}")
        if del_resp.status_code in (200, 204):
            deleted += 1
        else:
            print(f"  ! {item['title']} — delete failed HTTP {del_resp.status_code}")
            fail += 1
    print(f"  Knowledge: {deleted} deleted, {fail} failed")


def purge_sample_queries(client: httpx.Client, connection_id: str) -> None:
    """Delete every sample query for this connection."""
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/sample-queries")
    if resp.status_code != 200:
        print(f"  ! Could not fetch sample queries (HTTP {resp.status_code}) — skipping purge")
        return
    items = resp.json()
    if not items:
        print("  Sample Queries: nothing to purge")
        return
    deleted = fail = 0
    for item in items:
        del_resp = client.delete(
            f"{API_PREFIX}/connections/{connection_id}/sample-queries/{item['id']}"
        )
        if del_resp.status_code in (200, 204):
            deleted += 1
        else:
            print(
                f"  ! {item['natural_language'][:60]} — delete failed HTTP {del_resp.status_code}"
            )
            fail += 1
    print(f"  Sample Queries: {deleted} deleted, {fail} failed")


def purge_relationships(client: httpx.Client, connection_id: str) -> None:
    """Delete every manually declared relationship for this connection."""
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/relationships")
    if resp.status_code != 200:
        print(f"  ! Could not fetch relationships (HTTP {resp.status_code}) — skipping purge")
        return
    items = resp.json()
    if not items:
        print("  Relationships: nothing to purge")
        return
    deleted = fail = 0
    for item in items:
        del_resp = client.delete(
            f"{API_PREFIX}/connections/{connection_id}/relationships/{item['id']}"
        )
        if del_resp.status_code in (200, 204):
            deleted += 1
        else:
            print(
                f"  ! {item['source_table']}.{item['source_column']} — delete failed HTTP {del_resp.status_code}"
            )
            fail += 1
    print(f"  Relationships: {deleted} deleted, {fail} failed")


def seed_glossary(client: httpx.Client, connection_id: str, overwrite: bool = False) -> None:
    if not GLOSSARY_TERMS:
        print("\n--- Glossary: nothing to seed (GLOSSARY_TERMS is empty) ---")
        return

    print(f"\n--- Seeding {len(GLOSSARY_TERMS)} Glossary Terms (overwrite={overwrite}) ---")

    # Fetch existing terms: term -> id
    existing: dict[str, str] = {}
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/glossary")
    if resp.status_code == 200:
        for item in resp.json():
            existing[item["term"]] = item["id"]

    ok = skip = overwritten = fail = 0
    for term_data in GLOSSARY_TERMS:
        term = term_data["term"]
        if term in existing:
            if overwrite:
                del_resp = client.delete(
                    f"{API_PREFIX}/connections/{connection_id}/glossary/{existing[term]}"
                )
                if del_resp.status_code not in (200, 204):
                    print(
                        f"  ! {term} — delete failed HTTP {del_resp.status_code}: {del_resp.text[:80]}"
                    )
                    fail += 1
                    continue
            else:
                print(f"  = {term} (skipped — already exists)")
                skip += 1
                continue

        post_resp = client.post(
            f"{API_PREFIX}/connections/{connection_id}/glossary", json=term_data
        )
        if post_resp.status_code == 201:
            if overwrite and term in existing:
                print(f"  ~ {term} (overwritten)")
                overwritten += 1
            else:
                print(f"  + {term}")
                ok += 1
        else:
            print(f"  ! {term} — HTTP {post_resp.status_code}: {post_resp.text[:120]}")
            fail += 1

    print(f"  Glossary: {ok} created, {overwritten} overwritten, {skip} skipped, {fail} failed")


def seed_metrics(client: httpx.Client, connection_id: str, overwrite: bool = False) -> None:
    if not METRICS:
        print("\n--- Metrics: nothing to seed (METRICS is empty) ---")
        return

    print(f"\n--- Seeding {len(METRICS)} Metrics (overwrite={overwrite}) ---")

    # Fetch existing metrics: metric_name -> id
    existing: dict[str, str] = {}
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/metrics")
    if resp.status_code == 200:
        for item in resp.json():
            existing[item["metric_name"]] = item["id"]

    ok = skip = overwritten = fail = 0
    for metric_data in METRICS:
        name = metric_data["metric_name"]
        display = metric_data["display_name"]
        if name in existing:
            if overwrite:
                del_resp = client.delete(
                    f"{API_PREFIX}/connections/{connection_id}/metrics/{existing[name]}"
                )
                if del_resp.status_code not in (200, 204):
                    print(
                        f"  ! {display} — delete failed HTTP {del_resp.status_code}: {del_resp.text[:80]}"
                    )
                    fail += 1
                    continue
            else:
                print(f"  = {display} (skipped — already exists)")
                skip += 1
                continue

        post_resp = client.post(
            f"{API_PREFIX}/connections/{connection_id}/metrics", json=metric_data
        )
        if post_resp.status_code == 201:
            if overwrite and name in existing:
                print(f"  ~ {display} (overwritten)")
                overwritten += 1
            else:
                print(f"  + {display}")
                ok += 1
        else:
            print(f"  ! {display} — HTTP {post_resp.status_code}: {post_resp.text[:120]}")
            fail += 1

    print(f"  Metrics: {ok} created, {overwritten} overwritten, {skip} skipped, {fail} failed")


def seed_dictionary(client: httpx.Client, connection_id: str, overwrite: bool = False) -> None:
    if not DICTIONARY_ENTRIES:
        print("\n--- Dictionary: nothing to seed (DICTIONARY_ENTRIES is empty) ---")
        return

    print(
        f"\n--- Seeding Dictionary Entries for {len(DICTIONARY_ENTRIES)} columns (overwrite={overwrite}) ---"
    )

    # Build (table_name, column_name) → column_id map from the cached schema
    tables_resp = client.get(f"{API_PREFIX}/connections/{connection_id}/tables")
    tables_resp.raise_for_status()
    tables = tables_resp.json()

    column_map: dict[tuple[str, str], str] = {}
    print(f"  Scanning {len(tables)} tables for column IDs...")
    for table_summary in tables:
        detail_resp = client.get(f"{API_PREFIX}/tables/{table_summary['id']}")
        detail_resp.raise_for_status()
        detail = detail_resp.json()
        for col in detail["columns"]:
            column_map[(detail["table_name"], col["column_name"])] = col["id"]

    ok = skip = overwritten = fail = col_skip = 0
    for (table_name, column_name), entries in DICTIONARY_ENTRIES.items():
        col_id = column_map.get((table_name, column_name))
        if not col_id:
            print(f"  ! {table_name}.{column_name} — not found in schema cache (introspect first?)")
            col_skip += 1
            continue

        # Fetch existing entries for this column: raw_value -> entry_id
        existing: dict[str, str] = {}
        get_resp = client.get(f"{API_PREFIX}/columns/{col_id}/dictionary")
        if get_resp.status_code == 200:
            for item in get_resp.json():
                existing[item["raw_value"]] = item["id"]

        print(f"  {table_name}.{column_name} ({len(entries)} entries):")
        for entry_data in entries:
            raw = entry_data["raw_value"]
            if raw in existing:
                if overwrite:
                    del_resp = client.delete(
                        f"{API_PREFIX}/columns/{col_id}/dictionary/{existing[raw]}"
                    )
                    if del_resp.status_code not in (200, 204):
                        print(
                            f"    ! {raw!r} — delete failed HTTP {del_resp.status_code}: {del_resp.text[:80]}"
                        )
                        fail += 1
                        continue
                else:
                    print(f"    = {raw!r} (skipped — already exists)")
                    skip += 1
                    continue

            post_resp = client.post(f"{API_PREFIX}/columns/{col_id}/dictionary", json=entry_data)
            if post_resp.status_code == 201:
                if overwrite and raw in existing:
                    print(f"    ~ {raw!r} → {entry_data['display_value']} (overwritten)")
                    overwritten += 1
                else:
                    print(f"    + {raw!r} → {entry_data['display_value']}")
                    ok += 1
            else:
                print(f"    ! {raw!r} — HTTP {post_resp.status_code}: {post_resp.text[:100]}")
                fail += 1

    print(
        f"  Dictionary: {ok} created, {overwritten} overwritten, {skip} skipped, {fail} failed, {col_skip} columns not found"
    )


def seed_knowledge(client: httpx.Client, connection_id: str, overwrite: bool = False) -> None:
    if not KNOWLEDGE_DOCS:
        print("\n--- Knowledge: nothing to seed (KNOWLEDGE_DOCS is empty) ---")
        return

    print(f"\n--- Seeding {len(KNOWLEDGE_DOCS)} Knowledge Documents (overwrite={overwrite}) ---")

    # Fetch existing documents: title -> id
    existing: dict[str, str] = {}
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/knowledge")
    if resp.status_code == 200:
        for item in resp.json():
            existing[item["title"]] = item["id"]

    ok = skip = overwritten = fail = 0
    for doc in KNOWLEDGE_DOCS:
        title = doc["title"]
        if title in existing:
            if overwrite:
                del_resp = client.delete(
                    f"{API_PREFIX}/connections/{connection_id}/knowledge/{existing[title]}"
                )
                if del_resp.status_code not in (200, 204):
                    print(
                        f"  ! {title} — delete failed HTTP {del_resp.status_code}: {del_resp.text[:80]}"
                    )
                    fail += 1
                    continue
            else:
                print(f"  = {title} (skipped — already exists)")
                skip += 1
                continue

        payload = {"title": title, "content": doc["content"], "source_url": None}
        post_resp = client.post(f"{API_PREFIX}/connections/{connection_id}/knowledge", json=payload)
        if post_resp.status_code == 201:
            result = post_resp.json()
            if overwrite and title in existing:
                print(f"  ~ {title} ({result.get('chunk_count', '?')} chunks, overwritten)")
                overwritten += 1
            else:
                print(f"  + {title} ({result.get('chunk_count', '?')} chunks)")
                ok += 1
        else:
            print(f"  ! {title} — HTTP {post_resp.status_code}: {post_resp.text[:120]}")
            fail += 1

    print(f"  Knowledge: {ok} created, {overwritten} overwritten, {skip} skipped, {fail} failed")


def seed_sample_queries(client: httpx.Client, connection_id: str, overwrite: bool = False) -> None:
    if not SAMPLE_QUERIES:
        print("\n--- Sample Queries: nothing to seed (SAMPLE_QUERIES is empty) ---")
        return

    print(f"\n--- Seeding {len(SAMPLE_QUERIES)} Sample Queries (overwrite={overwrite}) ---")

    # Fetch existing queries: natural_language -> id
    existing: dict[str, str] = {}
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/sample-queries")
    if resp.status_code == 200:
        for item in resp.json():
            existing[item["natural_language"]] = item["id"]

    ok = skip = overwritten = fail = 0
    for sq in SAMPLE_QUERIES:
        label = sq["natural_language"]
        if label in existing:
            if overwrite:
                del_resp = client.delete(
                    f"{API_PREFIX}/connections/{connection_id}/sample-queries/{existing[label]}"
                )
                if del_resp.status_code not in (200, 204):
                    print(
                        f"  ! {label[:70]} — delete failed HTTP {del_resp.status_code}: {del_resp.text[:80]}"
                    )
                    fail += 1
                    continue
            else:
                print(f"  = {label[:70]} (skipped — already exists)")
                skip += 1
                continue

        post_resp = client.post(f"{API_PREFIX}/connections/{connection_id}/sample-queries", json=sq)
        if post_resp.status_code == 201:
            if overwrite and label in existing:
                print(f"  ~ {label[:70]} (overwritten)")
                overwritten += 1
            else:
                print(f"  + {label[:70]}")
                ok += 1
        else:
            print(f"  ! {label[:70]} — HTTP {post_resp.status_code}: {post_resp.text[:120]}")
            fail += 1

    print(
        f"  Sample Queries: {ok} created, {overwritten} overwritten, {skip} skipped, {fail} failed"
    )


def seed_relationships(client: httpx.Client, connection_id: str, overwrite: bool = False) -> None:
    if not RELATIONSHIPS:
        print("\n--- Relationships: nothing to seed (RELATIONSHIPS is empty) ---")
        return

    print(f"\n--- Seeding {len(RELATIONSHIPS)} Manual Relationships (overwrite={overwrite}) ---")

    tables_resp = client.get(f"{API_PREFIX}/connections/{connection_id}/tables")
    cached_tables: set[str] = set()
    if tables_resp.status_code == 200:
        for table in tables_resp.json():
            cached_tables.add(table["table_name"])
    else:
        print(
            f"  ! Could not fetch cached tables (HTTP {tables_resp.status_code}) — "
            "relationship validation will rely on API errors"
        )

    # Fetch existing manual relationships: constraint_name -> id
    existing: dict[str, str] = {}
    resp = client.get(f"{API_PREFIX}/connections/{connection_id}/relationships")
    if resp.status_code == 200:
        for item in resp.json():
            if item.get("constraint_name"):
                existing[item["constraint_name"]] = item["id"]

    ok = skip = overwritten = fail = unavailable = 0
    for rel in RELATIONSHIPS:
        key = rel.get("constraint_name") or f"{rel['source_table']}.{rel['source_column']}"

        missing_tables: list[str] = []
        if cached_tables:
            if rel["source_table"] not in cached_tables:
                missing_tables.append(rel["source_table"])
            if rel["target_table"] not in cached_tables:
                missing_tables.append(rel["target_table"])
        if missing_tables:
            missing_display = ", ".join(dict.fromkeys(missing_tables))
            print(f"  - {key} (skipped — table not present in schema cache: {missing_display})")
            unavailable += 1
            continue

        if key in existing:
            if overwrite:
                del_resp = client.delete(
                    f"{API_PREFIX}/connections/{connection_id}/relationships/{existing[key]}"
                )
                if del_resp.status_code not in (200, 204):
                    print(
                        f"  ! {key} — delete failed HTTP {del_resp.status_code}: {del_resp.text[:80]}"
                    )
                    fail += 1
                    continue
            else:
                print(f"  = {key} (skipped — already exists)")
                skip += 1
                continue

        post_resp = client.post(f"{API_PREFIX}/connections/{connection_id}/relationships", json=rel)
        if post_resp.status_code == 201:
            if overwrite and key in existing:
                print(f"  ~ {key} (overwritten)")
                overwritten += 1
            else:
                print(
                    f"  + {rel['source_table']}.{rel['source_column']} → {rel['target_table']}.{rel['target_column']}"
                )
                ok += 1
        else:
            print(f"  ! {key} — HTTP {post_resp.status_code}: {post_resp.text[:120]}")
            fail += 1

    print(
        f"  Relationships: {ok} created, {overwritten} overwritten, {skip} skipped, "
        f"{unavailable} unavailable, {fail} failed"
    )


def print_schema_summary(client: httpx.Client, connection_id: str) -> None:
    """Print all table/column names to help fill in DICTIONARY_ENTRIES."""
    print("\n--- Schema Summary (use this to fill in DICTIONARY_ENTRIES) ---")
    tables_resp = client.get(f"{API_PREFIX}/connections/{connection_id}/tables")
    tables_resp.raise_for_status()
    tables = tables_resp.json()

    for table_summary in tables:
        detail_resp = client.get(f"{API_PREFIX}/tables/{table_summary['id']}")
        detail_resp.raise_for_status()
        detail = detail_resp.json()
        cols = [c["column_name"] for c in detail["columns"]]
        print(f"  {detail['table_name']}: {', '.join(cols)}")


def login(base_url: str, email: str, password: str) -> str:
    """Authenticate against the QueryWise backend and return an access token."""
    try:
        resp = httpx.post(
            f"{base_url}{API_PREFIX}/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
    except httpx.ConnectError as e:
        print(f"ERROR: Cannot reach backend at {base_url}: {e}")
        sys.exit(1)

    if resp.status_code == 401:
        print(f"ERROR: Login failed — invalid credentials for '{email}'.")
        print("  Use --email and --password to supply valid admin credentials.")
        sys.exit(1)

    if resp.status_code != 200:
        print(f"ERROR: Login returned HTTP {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)

    token = resp.json().get("access_token")
    if not token:
        print("ERROR: Login response did not contain an access_token.")
        sys.exit(1)

    return token


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed semantic metadata for an Azure SQL Server connection into QueryWise"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="QueryWise backend URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--connection-name",
        default=None,
        help="Name of the connection to seed (default: first sqlserver connection)",
    )
    parser.add_argument(
        "--email",
        default="admin@querywise.dev",
        help="Admin user email for authentication (default: admin@querywise.dev)",
    )
    parser.add_argument(
        "--password",
        default="admin123",
        help="Admin user password for authentication (default: admin123)",
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Only print the schema summary — useful for discovering column names before filling in the seed data",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete existing entries (matched by key) before re-seeding. By default existing entries are skipped.",
    )
    parser.add_argument(
        "--purge",
        action="store_true",
        help=(
            "Delete ALL existing entries for this connection across all resources, "
            "then seed from scratch. Use this to fully reset the semantic layer."
        ),
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"QueryWise SQL Server Metadata Seeder → {base_url}")
    if args.purge:
        print("  Mode: PURGE — ALL existing entries will be deleted, then re-seeded from scratch")
    elif args.overwrite:
        print(
            "  Mode: OVERWRITE — existing entries (matched by key) will be deleted and re-created"
        )
    else:
        print(
            "  Mode: SKIP — existing entries will not be modified (use --overwrite or --purge to reset)"
        )

    # Authenticate and obtain a JWT before making any API calls
    print(f"  Authenticating as {args.email}...")
    token = login(base_url, args.email, args.password)
    print("  Authenticated.")

    auth_headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=base_url, timeout=60, headers=auth_headers) as client:
        # Verify backend is reachable
        try:
            client.get(f"{API_PREFIX}/health").raise_for_status()
        except (httpx.ConnectError, httpx.HTTPStatusError) as e:
            print(f"ERROR: Cannot reach backend at {base_url}: {e}")
            sys.exit(1)

        conn = find_connection(client, args.connection_name)
        connection_id = conn["id"]

        if args.schema_only:
            print_schema_summary(client, connection_id)
            return

        if args.purge:
            print("\n--- Purging all existing entries ---")
            purge_glossary(client, connection_id)
            purge_metrics(client, connection_id)
            purge_dictionary(client, connection_id)
            purge_knowledge(client, connection_id)
            purge_sample_queries(client, connection_id)
            purge_relationships(client, connection_id)
            print("--- Purge complete — seeding fresh ---")

        seed_glossary(client, connection_id, overwrite=args.overwrite)
        seed_metrics(client, connection_id, overwrite=args.overwrite)
        seed_dictionary(client, connection_id, overwrite=args.overwrite)
        seed_knowledge(client, connection_id, overwrite=args.overwrite)
        seed_sample_queries(client, connection_id, overwrite=args.overwrite)
        seed_relationships(client, connection_id, overwrite=args.overwrite)

    print("\n✓ Done. Verify in the UI:")
    print("  Glossary        → http://localhost:5173/glossary")
    print("  Metrics         → http://localhost:5173/metrics")
    print("  Dictionary      → Connections → click a table → Dictionary tab")
    print("  Knowledge       → http://localhost:5173/knowledge")
    print("  Sample Queries  → http://localhost:5173/sample-queries")
    print(f"  Relationships   → GET {args.base_url}/api/v1/connections/<id>/relationships")
    print("\nEmbeddings will generate in the background — check the progress")
    print(f"banner in the UI or: GET {args.base_url}/api/v1/embeddings/status")
    print("\nNOTE: Manual relationships survive re-introspection. Sample query")
    print("  embeddings are generated automatically after seeding.")


if __name__ == "__main__":
    main()
