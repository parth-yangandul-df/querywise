"""SQL Server connector for QueryWise — Azure SQL via ODBC Driver 18.

Connection string format (enter in the UI):
    DRIVER={ODBC Driver 18 for SQL Server};Server={server}.database.windows.net;
    Database={db};UID={user};PWD={password};Encrypt=yes;TrustServerCertificate=no;

    For Azure SQL (recommended):
        TrustServerCertificate=no  — validates the Azure CA-signed cert (correct for Azure SQL)
        TrustServerCertificate=yes — skips cert validation (use only for on-prem/self-signed certs)

Falls back to ODBC Driver 17 automatically if Driver 18 is not installed.

**Security note:** SQL Server connections should use a read-only database role.
All queries are executed within a transaction that is always rolled back, ensuring
no DML statements can persist even if they bypass the SQL blocklist.
"""

import asyncio
import time
from typing import Any

import aioodbc

from app.connectors.base_connector import (
    BaseConnector,
    ColumnInfo,
    ConnectorType,
    ForeignKeyInfo,
    QueryResult,
    TableInfo,
)
from app.core.exceptions import ConnectionError, QueryTimeoutError, SQLSafetyError
from app.utils.sql_sanitizer import check_sql_safety

# ODBC drivers to try in preference order
_ODBC_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
]


def _resolve_driver(connection_string: str) -> str:
    """If the connection string has no DRIVER= clause, inject the best available one."""
    if "DRIVER=" in connection_string.upper():
        return connection_string

    # Probe which driver is available
    try:
        import pyodbc  # type: ignore[import-untyped]

        installed = [d for d in pyodbc.drivers() if "SQL Server" in d]
        for preferred in _ODBC_DRIVERS:
            if preferred in installed:
                return f"DRIVER={{{preferred}}};{connection_string}"
        # Last resort — use whatever is there
        if installed:
            return f"DRIVER={{{installed[0]}}};{connection_string}"
    except Exception:
        pass

    # Fallback to 18 and let the OS error surface clearly
    return f"DRIVER={{ODBC Driver 18 for SQL Server}};{connection_string}"


class SQLServerConnector(BaseConnector):
    """Async SQL Server / Azure SQL connector.

    Uses aioodbc (async wrapper around pyodbc) so all DB I/O is non-blocking.
    Uses aioodbc.create_pool() (minsize=1, maxsize=5) so concurrent requests
    each acquire their own connection from the pool, avoiding the
    "Connection is busy" error from simultaneous cursors on a single connection.
    """

    connector_type = ConnectorType.SQLSERVER

    def __init__(self) -> None:
        self._pool: Any | None = None
        self._connection_string: str = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, connection_string: str, **kwargs: Any) -> None:
        resolved = _resolve_driver(connection_string)
        try:
            self._pool = await aioodbc.create_pool(
                dsn=resolved, minsize=1, maxsize=5, autocommit=True
            )
            self._connection_string = resolved
        except Exception:
            raise ConnectionError(
                "Unable to connect to the database. Please verify your connection string and try again."
            )

    async def disconnect(self) -> None:
        if self._pool:
            try:
                await self._pool.close()
            except Exception:
                pass
            self._pool = None

    async def test_connection(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                cursor = await conn.cursor()
                await cursor.execute("SELECT 1")
                await cursor.close()
            return True
        except Exception:
            # Pool may have stale connections — try to reconnect once
            try:
                await self.connect(self._connection_string)
                async with self._pool.acquire() as conn:  # type: ignore[union-attr]
                    cursor = await conn.cursor()
                    await cursor.execute("SELECT 1")
                    await cursor.close()
                return True
            except Exception:
                return False

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    async def introspect_schemas(self) -> list[str]:
        """Return user-accessible schemas, excluding system ones."""
        if self._pool is None:
            raise ConnectionError("Database connection lost. Please try again.")
        sql = """
            SELECT SCHEMA_NAME
            FROM INFORMATION_SCHEMA.SCHEMATA
            WHERE SCHEMA_NAME NOT IN (
                'information_schema', 'sys', 'guest',
                'db_owner', 'db_accessadmin', 'db_securityadmin',
                'db_ddladmin', 'db_backupoperator', 'db_datareader',
                'db_datawriter', 'db_denydatareader', 'db_denydatawriter'
            )
            ORDER BY SCHEMA_NAME
        """
        async with self._pool.acquire() as conn:
            cursor = await conn.cursor()
            try:
                await cursor.execute(sql)
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
            finally:
                await cursor.close()

    async def introspect_tables(self, schema: str = "dbo") -> list[TableInfo]:
        """Introspect all tables and views in a schema with columns."""
        if self._pool is None:
            raise ConnectionError("Database connection lost. Please try again.")
        async with self._pool.acquire() as conn:
            cursor = await conn.cursor()
            try:
                # --- Tables and views ---
                await cursor.execute(
                    """
                    SELECT TABLE_NAME, TABLE_TYPE
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = ?
                      AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                    ORDER BY TABLE_NAME
                    """,
                    schema,
                )
                table_rows = await cursor.fetchall()

                # --- All columns for the schema in one query (efficient) ---
                await cursor.execute(
                    """
                    SELECT
                        c.TABLE_NAME,
                        c.COLUMN_NAME,
                        c.DATA_TYPE,
                        c.IS_NULLABLE,
                        c.COLUMN_DEFAULT,
                        c.ORDINAL_POSITION,
                        CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS IS_PK
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    LEFT JOIN (
                        SELECT ku.TABLE_NAME, ku.COLUMN_NAME
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                            ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                            AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA
                        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                          AND tc.TABLE_SCHEMA = ?
                    ) pk ON pk.TABLE_NAME = c.TABLE_NAME
                         AND pk.COLUMN_NAME = c.COLUMN_NAME
                    WHERE c.TABLE_SCHEMA = ?
                    ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
                    """,
                    schema,
                    schema,
                )
                col_rows = await cursor.fetchall()

                await cursor.execute(
                    """
                    SELECT
                        fk.CONSTRAINT_NAME,
                        fk.TABLE_NAME,
                        fk.COLUMN_NAME,
                        fk.REFERENCED_TABLE_SCHEMA,
                        fk.REFERENCED_TABLE_NAME,
                        fk.REFERENCED_COLUMN_NAME
                    FROM (
                        SELECT
                            tc.CONSTRAINT_NAME,
                            kcu.TABLE_SCHEMA,
                            kcu.TABLE_NAME,
                            kcu.COLUMN_NAME,
                            ccu.TABLE_SCHEMA AS REFERENCED_TABLE_SCHEMA,
                            ccu.TABLE_NAME AS REFERENCED_TABLE_NAME,
                            ccu.COLUMN_NAME AS REFERENCED_COLUMN_NAME
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                            ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                            AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                        JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
                            ON rc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
                        JOIN INFORMATION_SCHEMA.CONSTRAINT_COLUMN_USAGE ccu
                            ON ccu.CONSTRAINT_NAME = rc.UNIQUE_CONSTRAINT_NAME
                            AND ccu.TABLE_SCHEMA = rc.UNIQUE_CONSTRAINT_SCHEMA
                        WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
                            AND kcu.TABLE_SCHEMA = ?
                    ) fk
                    ORDER BY fk.TABLE_NAME, fk.CONSTRAINT_NAME, fk.COLUMN_NAME
                    """,
                    schema,
                )
                fk_rows = await cursor.fetchall()

            finally:
                await cursor.close()

        # Group columns by table
        columns_by_table: dict[str, list[ColumnInfo]] = {}
        for cr in col_rows:
            tname = cr[0]
            if tname not in columns_by_table:
                columns_by_table[tname] = []
            columns_by_table[tname].append(
                ColumnInfo(
                    name=cr[1],
                    data_type=cr[2],
                    is_nullable=(cr[3] == "YES"),
                    is_primary_key=bool(cr[6]),
                    default_value=cr[4],
                    comment=None,  # SQL Server column descriptions need extended properties
                    ordinal_position=cr[5],
                )
            )

        foreign_keys_by_table: dict[str, list[ForeignKeyInfo]] = {}
        for fk in fk_rows:
            table_name = fk[1]
            if table_name not in foreign_keys_by_table:
                foreign_keys_by_table[table_name] = []
            foreign_keys_by_table[table_name].append(
                ForeignKeyInfo(
                    constraint_name=fk[0],
                    column_name=fk[2],
                    referred_schema=fk[3],
                    referred_table=fk[4],
                    referred_column=fk[5],
                )
            )

        tables: list[TableInfo] = []
        for trow in table_rows:
            table_name = trow[0]
            table_type = "table" if trow[1] == "BASE TABLE" else "view"
            tables.append(
                TableInfo(
                    schema_name=schema,
                    table_name=table_name,
                    table_type=table_type,
                    comment=None,
                    columns=columns_by_table.get(table_name, []),
                    foreign_keys=foreign_keys_by_table.get(table_name, []),
                    row_count_estimate=None,
                )
            )

        return tables

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def execute_query(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        timeout_seconds: int = 30,
        max_rows: int = 1000,
    ) -> QueryResult:
        # Safety check (shared blocklist)
        issues = check_sql_safety(sql)
        if issues:
            raise SQLSafetyError()

        if self._pool is None:
            raise ConnectionError("Database connection lost. Please try again.")

        # T-SQL uses TOP instead of LIMIT
        wrapped_sql = _inject_top(sql, max_rows + 1)

        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._run_query_readonly(wrapped_sql, params),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            raise QueryTimeoutError(timeout_seconds)

        elapsed_ms = (time.monotonic() - start) * 1000

        rows, col_names, col_types = result
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]

        return QueryResult(
            columns=col_names,
            column_types=col_types,
            rows=[list(r) for r in rows],
            row_count=len(rows),
            execution_time_ms=elapsed_ms,
            truncated=truncated,
        )

    async def _run_query_readonly(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> tuple[list[Any], list[str], list[str]]:
        """Execute a query inside a transaction that always rolls back.

        This ensures no writes can ever persist, even if the SQL contains
        DML statements that bypass the blocklist.
        """
        if self._pool is None:
            raise ConnectionError("Database connection lost. Please try again.")
        async with self._pool.acquire() as conn:
            # Begin a transaction, execute, then always rollback
            await conn.execute("BEGIN TRANSACTION")
            try:
                cursor = await conn.cursor()
                try:
                    if params:
                        await cursor.execute(sql, params)
                    else:
                        await cursor.execute(sql)
                    rows = await cursor.fetchall()
                    if not rows:
                        return [], [], []
                    col_names = [desc[0] for desc in cursor.description]
                    col_types = [_mssql_type_name(desc[1]) for desc in cursor.description]
                    return rows, col_names, col_types
                finally:
                    await cursor.close()
            finally:
                # Always rollback — never commit, ensuring read-only safety
                try:
                    await conn.execute("ROLLBACK TRANSACTION")
                except Exception:
                    pass

    async def _run_query(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> tuple[list[Any], list[str], list[str]]:
        if self._pool is None:
            raise ConnectionError("Database connection lost. Please try again.")
        async with self._pool.acquire() as conn:
            cursor = await conn.cursor()
            try:
                if params:
                    await cursor.execute(sql, params)
                else:
                    await cursor.execute(sql)
                rows = await cursor.fetchall()
                if not rows:
                    return [], [], []
                col_names = [desc[0] for desc in cursor.description]
                col_types = [_mssql_type_name(desc[1]) for desc in cursor.description]
                return rows, col_names, col_types
            finally:
                await cursor.close()

    # ------------------------------------------------------------------
    # Sample values
    # ------------------------------------------------------------------

    async def get_sample_values(
        self, schema: str, table: str, column: str, limit: int = 20
    ) -> list[Any]:
        if self._pool is None:
            raise ConnectionError("Database connection lost. Please try again.")
        sql = (
            f"SELECT DISTINCT TOP {limit} [{column}] "
            f"FROM [{schema}].[{table}] "
            f"WHERE [{column}] IS NOT NULL "
            f"ORDER BY [{column}]"
        )
        async with self._pool.acquire() as conn:
            cursor = await conn.cursor()
            try:
                await cursor.execute(sql)
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
            finally:
                await cursor.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _inject_top(sql: str, n: int) -> str:
    """Wrap a SELECT statement with TOP N if no TOP/LIMIT is present.

    Handles:
        SELECT ...      → SELECT TOP N ...
        SELECT TOP ...  → unchanged
    Also strips trailing semicolons (T-SQL doesn't need them and some
    drivers reject them in subqueries).
    """
    stripped = sql.strip().rstrip(";").strip()

    upper = stripped.upper()
    if "TOP " in upper or "LIMIT " in upper:
        return stripped

    # Find position after SELECT (accounting for SELECT DISTINCT)
    if upper.startswith("SELECT DISTINCT"):
        insert_at = upper.index("DISTINCT") + len("DISTINCT")
    elif upper.startswith("SELECT"):
        insert_at = stripped.index("SELECT") + len("SELECT")
    else:
        # Not a SELECT — wrap in subquery
        return f"SELECT TOP {n} * FROM ({stripped}) AS _q"

    return f"{stripped[:insert_at]} TOP {n}{stripped[insert_at:]}"


def _mssql_type_name(type_code: Any) -> str:
    """Map pyodbc type objects to readable type name strings."""
    if type_code is None:
        return "unknown"
    name = getattr(type_code, "__name__", None) or str(type_code)
    _map = {
        "str": "nvarchar",
        "int": "int",
        "float": "float",
        "bool": "bit",
        "bytes": "varbinary",
        "Decimal": "decimal",
        "datetime": "datetime",
        "date": "date",
        "time": "time",
    }
    return _map.get(name, name)
