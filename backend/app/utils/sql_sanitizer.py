"""SQL Safety — Defense-in-Depth Architecture

This module provides REGEX-BASED validation only. It is NOT the primary security boundary.
The actual query execution layer enforces defense-in-depth as follows:

1. **Primary defense**: All generated SQL runs inside read-only transactions at the
   database connector level (see app/connectors/). Even if a malicious query passes
   this sanitizer, it cannot mutate data.

2. **Secondary defense**: This regex-based blocklist catches known dangerous patterns
   (DDL, DML, admin commands, injection patterns) to reject obviously malicious queries
   BEFORE they reach the database connection.

3. **Tertiary defense**: Schema introspection and parameterized queries are used wherever
   possible, reducing the attack surface for identifier injection.

IMPORTANT: This sanitizer must NOT be the sole line of defense. The read-only transaction
enforcement in connectors is the real security guarantee. If you add a pattern here,
also ensure the connector-level read-only enforcement is intact.

See: app/connectors/base_connector.py and app/connectors/postgresql/connector.py
"""

import re

# Valid SQL identifier pattern — letters, digits, underscores; must start with a letter or underscore
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_identifier(name: str) -> str:
    """Validate a SQL identifier (table name, column name, schema name).

    Prevents SQL injection in dynamic identifier contexts where parameterized
    queries cannot be used (e.g., column names in SELECT lists).

    Args:
        name: The identifier to validate.

    Returns:
        The validated identifier string (unchanged).

    Raises:
        ValueError: If the identifier contains disallowed characters or is empty.
    """
    if not name:
        raise ValueError("Identifier must not be empty")
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid SQL identifier: {name!r}. "
            "Identifiers must start with a letter or underscore and contain only "
            "letters, digits, and underscores."
        )
    return name


# Patterns that indicate dangerous SQL operations
_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # DDL
    (re.compile(r"\bDROP\b", re.IGNORECASE), "DROP statements are not allowed"),
    (re.compile(r"\bALTER\b", re.IGNORECASE), "ALTER statements are not allowed"),
    (re.compile(r"\bCREATE\b", re.IGNORECASE), "CREATE statements are not allowed"),
    (re.compile(r"\bTRUNCATE\b", re.IGNORECASE), "TRUNCATE statements are not allowed"),
    # DML
    (re.compile(r"\bINSERT\b", re.IGNORECASE), "INSERT statements are not allowed"),
    (re.compile(r"\bUPDATE\b\s", re.IGNORECASE), "UPDATE statements are not allowed"),
    (re.compile(r"\bDELETE\b\s+FROM\b", re.IGNORECASE), "DELETE statements are not allowed"),
    (re.compile(r"\bMERGE\b", re.IGNORECASE), "MERGE statements are not allowed"),
    # UNION-based attacks
    (re.compile(r"\bUNION\b", re.IGNORECASE), "UNION statements are not allowed"),
    # INTO clause — prevents SELECT INTO OUTFILE / INTO DUMPFILE
    (
        re.compile(r"\bINTO\s+(OUTFILE|DUMPFILE)\b", re.IGNORECASE),
        "INTO OUTFILE/DUMPFILE is not allowed",
    ),
    # System catalog access — PostgreSQL
    (
        re.compile(
            r"\b(information_schema|pg_catalog|pg_shadow|pg_roles|pg_database|pg_stat_activity)\b",
            re.IGNORECASE,
        ),
        "System catalog access is not allowed",
    ),
    # System catalog access — SQL Server
    (
        re.compile(r"\b(sys\.tables|sys\.columns|sys\.objects|sys\.databases)\b", re.IGNORECASE),
        "System catalog access is not allowed",
    ),
    # Admin / dangerous
    (re.compile(r"\bGRANT\b", re.IGNORECASE), "GRANT statements are not allowed"),
    (re.compile(r"\bREVOKE\b", re.IGNORECASE), "REVOKE statements are not allowed"),
    (re.compile(r"\bCOPY\b", re.IGNORECASE), "COPY statements are not allowed"),
    (re.compile(r"\bEXECUTE\b", re.IGNORECASE), "EXECUTE statements are not allowed"),
    # T-SQL (MS SQL Server) dangerous patterns
    (re.compile(r"\bEXEC\b", re.IGNORECASE), "EXEC statements are not allowed"),
    (re.compile(r"\bXP_CMDSHELL\b", re.IGNORECASE), "xp_cmdshell is not allowed"),
    (re.compile(r"\bOPENROWSET\b", re.IGNORECASE), "OPENROWSET is not allowed"),
    (re.compile(r"\bOPENQUERY\b", re.IGNORECASE), "OPENQUERY is not allowed"),
    (re.compile(r"\bOPENDATASOURCE\b", re.IGNORECASE), "OPENDATASOURCE is not allowed"),
    (re.compile(r"\bsp_executesql\b", re.IGNORECASE), "sp_executesql is not allowed"),
    (re.compile(r"\bBULK\s+INSERT\b", re.IGNORECASE), "BULK INSERT is not allowed"),
    # Postgres-specific dangerous functions
    (re.compile(r"\bpg_sleep\b", re.IGNORECASE), "pg_sleep is not allowed"),
    (re.compile(r"\bpg_terminate_backend\b", re.IGNORECASE), "pg_terminate_backend is not allowed"),
    (re.compile(r"\bpg_cancel_backend\b", re.IGNORECASE), "pg_cancel_backend is not allowed"),
    (re.compile(r"\bdblink\b", re.IGNORECASE), "dblink is not allowed"),
    # BigQuery-specific
    (re.compile(r"\bEXPORT\s+DATA\b", re.IGNORECASE), "EXPORT DATA is not allowed"),
    (re.compile(r"\bLOAD\s+DATA\b", re.IGNORECASE), "LOAD DATA is not allowed"),
    # Databricks-specific
    (re.compile(r"\bCOPY\s+INTO\b", re.IGNORECASE), "COPY INTO is not allowed"),
    (re.compile(r"\bOPTIMIZE\b", re.IGNORECASE), "OPTIMIZE is not allowed"),
    (re.compile(r"\bVACUUM\b", re.IGNORECASE), "VACUUM is not allowed"),
    # Stacked queries (semicolon followed by another statement)
    (
        re.compile(r";\s*\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b", re.IGNORECASE),
        "Multiple statements (stacked queries) are not allowed",
    ),
]


def check_sql_safety(sql: str) -> list[str]:
    """Check SQL for dangerous patterns. Returns list of issues found, empty if safe."""
    issues: list[str] = []
    # Strip comments before checking
    cleaned = _strip_sql_comments(sql)
    for pattern, message in _BLOCKED_PATTERNS:
        if pattern.search(cleaned):
            issues.append(message)
    return issues


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL comments to prevent bypass via comment injection."""
    # Remove single-line comments
    sql = re.sub(r"--[^\n]*", "", sql)
    # Remove multi-line comments
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql
