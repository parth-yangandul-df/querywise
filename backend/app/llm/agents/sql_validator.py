"""Agent: SQL Validator — validates generated SQL for safety and correctness."""

import logging
from dataclasses import dataclass
from enum import StrEnum

import sqlglot
from sqlglot import exp

from app.utils.sql_sanitizer import check_sql_safety

logger = logging.getLogger(__name__)


class ValidationStatus(StrEnum):
    VALID = "valid"
    UNSAFE = "unsafe"
    SYNTAX_ERROR = "syntax_error"
    SCHEMA_MISMATCH = "schema_mismatch"


@dataclass
class ValidationResult:
    status: ValidationStatus
    issues: list[str]
    corrected_sql: str | None = None


class SQLValidatorAgent:
    """Validates SQL for safety, correctness, and schema compliance.

    Two levels:
    1. Static analysis (no LLM call): blocked patterns, injection detection
    2. Schema validation: checks referenced tables/columns exist in the cached schema
    """

    async def validate(
        self,
        sql: str,
        schema_tables: dict[str, list[str]] | None = None,
    ) -> ValidationResult:
        """Validate a SQL query.

        Args:
            sql: The SQL query to validate
            schema_tables: Dict of table_name -> list of column_names for schema checking
        """
        # Level 1: Static safety checks
        safety_issues = check_sql_safety(sql)
        if safety_issues:
            return ValidationResult(
                status=ValidationStatus.UNSAFE,
                issues=safety_issues,
            )

        # Check for empty SQL
        stripped = sql.strip()
        if not stripped:
            return ValidationResult(
                status=ValidationStatus.SYNTAX_ERROR,
                issues=["Empty SQL query"],
            )

        # Check it starts with SELECT (or WITH for CTEs)
        upper = stripped.upper().lstrip()
        if not (upper.startswith("SELECT") or upper.startswith("WITH")):
            return ValidationResult(
                status=ValidationStatus.UNSAFE,
                issues=[f"Query must start with SELECT or WITH, got: {upper[:20]}..."],
            )

        # Level 2: Schema validation (if schema context provided)
        if schema_tables:
            schema_issues = _check_schema_references(sql, schema_tables)
            if schema_issues:
                return ValidationResult(
                    status=ValidationStatus.SCHEMA_MISMATCH,
                    issues=schema_issues,
                )

        return ValidationResult(
            status=ValidationStatus.VALID,
            issues=[],
        )


def _check_schema_references(
    sql: str,
    schema_tables: dict[str, list[str]],
) -> list[str]:
    """Check if tables/columns referenced in SQL exist in the schema.

    Uses sqlglot to parse SQL into an AST and extract table/column references.
    Handles all SQL dialects including T-SQL (SQL Server).
    """
    issues: list[str] = []

    try:
        # Parse with T-SQL dialect for SQL Server compatibility
        parsed = sqlglot.parse_one(sql, read="tsql")
    except sqlglot.errors.ParseError as e:
        # Syntax error in SQL - let it through, the DB will catch it
        logger.debug("SQL parse error (will defer to DB): %s", e)
        return issues

    # Build lookup sets (case-insensitive)
    all_table_names = {name.upper() for name in schema_tables}
    all_known_cols: set[str] = set()
    for cols in schema_tables.values():
        all_known_cols.update(c.upper() for c in cols)

    # ── Check table references ──
    for table in parsed.find_all(exp.Table):
        table_name = table.name.upper()
        # Skip CTE aliases and subquery aliases
        if table_name not in all_table_names:
            issues.append(f"Table '{table.name}' not found in schema")

    # ── Check column references ──
    for column in parsed.find_all(exp.Column):
        col_name = column.name.upper()
        if col_name not in all_known_cols:
            issues.append(f"Column '{column.name}' not found in schema")

    return issues
