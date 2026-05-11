"""show_schema node — answers schema introspection questions directly from cache.

Handles:
  - "What tables do you have access to?"
  - "Show me the tables"
  - "List columns in the Employee table"

Bypasses SQL generation entirely. Queries the CachedTable / CachedColumn models
and returns a human-readable answer.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.core.metrics import timed_node
from app.db.models.schema_cache import CachedTable
from app.db.session import AsyncSession
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)


@timed_node("show_schema")
async def show_schema(state: GraphState) -> dict[str, Any]:
    """Answer a schema introspection question from the cached schema."""
    question = state["question"].lower()
    connection_id = uuid.UUID(state["connection_id"])
    db_factory = state["db"]

    if state.get("event_queue"):
        await state["event_queue"].put(
            {
                "type": "stage",
                "stage": "answering",
                "label": "Looking up schema...",
                "progress": 50,
            }
        )

    async with db_factory() as db:
        tables = await _get_cached_tables(db, connection_id)

        if not tables:
            return {
                "answer": (
                    "I don't have any schema information cached for this connection. "
                    "Please ask an admin to run schema introspection first."
                ),
                "highlights": [],
                "suggested_followups": [
                    "What queries can I run?",
                    "How do I get started?",
                ],
            }

        # Detect if the user is asking about columns in a specific table
        specific_table = _extract_table_name(question, tables)
        if specific_table and ("column" in question or "fields" in question):
            return _format_columns_answer(specific_table, tables)

        # Default: list all tables
        return _format_tables_answer(tables)


async def _get_cached_tables(db: AsyncSession, connection_id: uuid.UUID) -> list[CachedTable]:
    """Load cached tables with their columns for a connection."""
    result = await db.execute(
        select(CachedTable)
        .where(CachedTable.connection_id == connection_id)
        .order_by(CachedTable.schema_name, CachedTable.table_name)
    )
    return list(result.scalars().all())


def _extract_table_name(question: str, tables: list[CachedTable]) -> CachedTable | None:
    """Try to find which table the user is asking about."""
    for t in tables:
        name = t.table_name.lower()
        if name in question:
            return t
    return None


def _format_tables_answer(tables: list[CachedTable]) -> dict[str, Any]:
    """Format a list of tables as a human-readable answer."""
    if len(tables) == 0:
        return {
            "answer": "No tables are currently cached for this connection.",
            "highlights": [],
            "suggested_followups": [],
        }

    lines = [f"I have access to **{len(tables)}** tables:"]
    for t in tables:
        col_count = len(t.columns) if t.columns else 0
        lines.append(f"- **{t.table_name}** ({col_count} columns)")

    answer = "\n".join(lines)

    return {
        "answer": answer,
        "highlights": [t.table_name for t in tables[:10]],
        "suggested_followups": [
            f"What columns are in {tables[0].table_name}?",
            f"Show me data from {tables[0].table_name}",
        ],
    }


def _format_columns_answer(table: CachedTable, tables: list[CachedTable]) -> dict[str, Any]:
    """Format a table's columns as a human-readable answer."""
    columns = table.columns or []
    if not columns:
        return {
            "answer": f"I don't have column information for **{table.table_name}**.",
            "highlights": [],
            "suggested_followups": [],
        }

    lines = [f"**{table.table_name}** has {len(columns)} columns:"]
    for col in columns:
        pk_marker = " (PK)" if col.is_primary_key else ""
        lines.append(f"- **{col.column_name}** — {col.data_type}{pk_marker}")

    return {
        "answer": "\n".join(lines),
        "highlights": [col.column_name for col in columns[:10]],
        "suggested_followups": [
            f"Show me data from {table.table_name}",
            f"What tables are related to {table.table_name}?",
        ],
    }
