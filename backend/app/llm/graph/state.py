"""GraphState — the single shared state dict threaded through the LangGraph pipeline."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from app.connectors.base_connector import QueryResult


class GraphState(TypedDict):
    # ── Inputs ───────────────────────────────────────────────────────────
    question: str
    connection_id: str  # UUID as str
    connector_type: str
    connection_string: str
    timeout_seconds: int
    max_rows: int
    db: AsyncSession  # SQLAlchemy async session (not serialized)
    session_id: str | None  # UUID as str — chat thread identifier

    # ── Auth / RBAC ──────────────────────────────────────────────────────
    user_id: str | None
    user_role: str | None
    resource_id: int | None
    employee_id: str | None

    # ── History (loaded by load_history node) ────────────────────────────
    loaded_history: list[dict]  # [{role, content}, ...] compacted last 6 turns
    last_generated_sql: str | None  # SQL from the most recent successful query turn
    last_result_columns: list[str] | None
    last_result_preview_rows: list[list] | None  # max 20 rows from last successful query

    # ── Turn resolution (set by resolve_turn node) ───────────────────────
    action: str | None  # "query" | "clarification" | "show_sql" | "explain_result"
    resolved_question: str | None  # standalone rewritten question for build_context
    clarification_reason: str | None
    clarification_message: str | None
    clarification_options: list[str]

    # ── Context building (set by build_context_node) ─────────────────────
    prompt_context: str | None  # scope-injected prompt string for the composer
    schema_tables: dict | None  # {TABLE_NAME: [COL, ...]} for the SQL validator
    question_embedding: list[float] | None  # question vector, used by similarity_check

    # ── Similarity shortcut (set by similarity_check node) ────────────────
    similarity_shortcut: bool  # True if a validated sample query matched

    # ── SQL generation pipeline (compose → validate → handle_error cycle) ─
    generated_sql: str | None
    validation_issues: list[str]  # empty = valid; non-empty = re-route to handle_error
    previous_attempts: list[str]  # all SQL strings tried in this turn
    retry_count: int

    # ── Execution (set by execute_sql node) ───────────────────────────────
    sql: str | None
    result: QueryResult | None
    explanation: str | None
    llm_provider: str | None
    llm_model: str | None

    # ── Interpretation (set by interpret_result) ─────────────────────────
    answer: str | None
    highlights: list[str]
    suggested_followups: list[str]

    # ── History write (set by write_history) ─────────────────────────────
    execution_id: Any
    execution_time_ms: float | None

    # ── Error propagation ────────────────────────────────────────────────
    error: str | None

    # ── Streaming (optional — None on non-streaming path) ────────────────
    event_queue: asyncio.Queue | None  # push {"type": "stage"|"token", ...} events here
