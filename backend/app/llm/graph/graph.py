"""LangGraph StateGraph assembly — fully agentic multi-turn pipeline.

Graph topology:
  load_history          Fetches last 6 turns + last SQL/result preview from DB.
       |
  resolve_turn          LLM call (fast/cheap model): classifies intent + rewrites
       |                question into a fully standalone form for context building.
       |                Skipped on first turn (no history → straight to query path).
       |
       ├─ action=query ──────────────────────────────────────────────────────────┐
       │  User wants fresh or modified data from the database.                   │
       │                                                              build_context
       │                              Schema linking + semantic retrieval: finds  │
       │                              relevant tables/cols, glossary, metrics,    │
       │                              knowledge chunks via vector + keyword       │
       │                              search. Applies RBAC scope constraints.     │
       │                                                          similarity_check │
       │                              Cosine similarity vs validated sample        │
       │                              queries. If similarity ≥ threshold (0.92),  │
       │                              skip LLM entirely — use stored SQL directly. │
       │                         ┌──────────────────────┴──────────────────────┐  │
       │                  shortcut hit                                    no match │
       │              (stored validated SQL)                                   compose_sql
       │                         │                              QueryComposerAgent: LLM call
       │                         │                              to generate SQL from the      │
       │                         │                              resolved question + context.  │
       │                         │                         ┌──────────────┴────────────────┐ │
       │                         │                  scope violation /              validate_sql
        │                         │                  no SQL produced         SQLValidatorAgent: static
        │                         │                  (→ write_history        check vs schema tables.
        │                         │                   as clarification)      │
        │                         │                              ┌───────────┴──────────┐
        │                         │                           valid            invalid (issues found)
        │                         │                              │                  handle_error
        │                         │                              │         ErrorHandlerAgent: LLM call
        │                         │                              │         to correct SQL. Routes back
        │                         │                              │         to validate_sql (max 3 retries).
        │                         │                              │         On exhaustion → write_history
        │                         │                              │         as clarification.
       │                         └─────────────────────────→ execute_sql
       │                                                     Runs final SQL against the target
       │                                                     database via the registered connector.
       │                                                          │
       │                                                   interpret_result
       │                                                     ResultInterpreterAgent: LLM call to
       │                                                     produce a human-readable answer,
       │                                                     highlights, and follow-up suggestions.
       │                                                          │
       ├─ action=show_sql ───────→ answer_from_state              │
       │  User asks "show me the SQL". Returns last_generated_sql │
       │  from loaded state — no DB execution needed.             │
       │                             │                            │
       ├─ action=explain_result ─────┤                            │
       │  User asks "why is X here?". LLM call grounded in the    │
       │  stored result preview — no DB execution needed.         │
       │                             │                            │
       └─ action=clarification ──→ write_history ←────────────────┘
          Question is ambiguous or                Persists QueryExecution record to the
          LLM confidence < 0.75.                  app DB (turn_type, SQL, result preview,
          Sets clarification_message              LLM provider/model, retry count, etc.).
          + clarification_options.                       │
          No SQL generated.                            END
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from app.config import settings
from app.llm.graph.nodes.answer_from_state import answer_from_state
from app.llm.graph.nodes.build_context_node import build_context_node
from app.llm.graph.nodes.compose_sql import compose_sql, route_after_compose
from app.llm.graph.nodes.execute_sql import execute_sql, route_after_execute
from app.llm.graph.nodes.handle_error import handle_error, route_after_handle_error
from app.llm.graph.nodes.history_writer import write_history
from app.llm.graph.nodes.load_history import load_history
from app.llm.graph.nodes.resolve_turn import resolve_turn, route_after_resolve
from app.llm.graph.nodes.result_interpreter import interpret_result
from app.llm.graph.nodes.similarity_check import route_after_similarity, similarity_check
from app.llm.graph.nodes.validate_sql import route_after_validate, validate_sql
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)

_compiled_graph: Any = None
_langsmith_checkpointer: Any = None


def _setup_langsmith_tracing() -> None:
    """Initialize LangSmith tracing on startup."""
    global _langsmith_checkpointer

    if not settings.langsmith_tracing_enabled or not settings.langsmith_api_key:
        return

    try:
        from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore[import-not-found]

        _langsmith_checkpointer = PostgresSaver.from_conn_string(
            settings.database_url.replace("+asyncpg", ""),
        )
        _langsmith_checkpointer.setup()
        logger.info("LangSmith tracing enabled for project: %s", settings.langsmith_project)
    except Exception:
        logger.warning("Failed to setup LangSmith tracing: %s", exc_info=True)


def _build_graph(checkpointer: Any | None = None) -> Any:
    """Build the LangGraph with optional checkpointer."""
    logger = logging.getLogger(__name__)
    logger.info("graph: building LangGraph pipeline")
    graph = StateGraph(GraphState)

    # ── Nodes ────────────────────────────────────────────────────────────
    graph.add_node("load_history", load_history)
    graph.add_node("resolve_turn", resolve_turn)
    graph.add_node("build_context", build_context_node)
    graph.add_node("similarity_check", similarity_check)
    graph.add_node("compose_sql", compose_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("handle_error", handle_error)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("answer_from_state", answer_from_state)
    graph.add_node("interpret_result", interpret_result)
    graph.add_node("write_history", write_history)

    # ── Entry ─────────────────────────────────────────────────────────────
    graph.set_entry_point("load_history")
    graph.add_edge("load_history", "resolve_turn")

    # ── resolve_turn → branch on action ──────────────────────────────────
    graph.add_conditional_edges(
        "resolve_turn",
        route_after_resolve,
        {
            "build_context": "build_context",  # query path
            "answer_from_state": "answer_from_state",
            "write_history": "write_history",  # clarification path
        },
    )

    # ── Query path ────────────────────────────────────────────────────────
    graph.add_edge("build_context", "similarity_check")

    graph.add_conditional_edges(
        "similarity_check",
        route_after_similarity,
        {
            "execute_sql": "execute_sql",  # shortcut: stored SQL, skip LLM
            "compose_sql": "compose_sql",  # normal: proceed to LLM composer
        },
    )

    graph.add_conditional_edges(
        "compose_sql",
        route_after_compose,
        {
            "validate_sql": "validate_sql",
            "write_history": "write_history",  # scope violation / no SQL produced
        },
    )

    graph.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {
            "execute_sql": "execute_sql",
            "handle_error": "handle_error",
        },
    )

    # Retry cycle: handle_error → validate_sql/execute_sql → handle_error → ... → write_history
    graph.add_conditional_edges(
        "handle_error",
        route_after_handle_error,
        {
            "validate_sql": "validate_sql",
            "execute_sql": "execute_sql",
            "write_history": "write_history",
        },
    )

    # Execute SQL: route to handle_error on failure, else interpret result
    graph.add_conditional_edges(
        "execute_sql",
        route_after_execute,
        {
            "handle_error": "handle_error",  # execution failed — retry
            "interpret_result": "interpret_result",  # success
        },
    )
    graph.add_edge("interpret_result", "write_history")

    # ── Non-query paths ───────────────────────────────────────────────────
    graph.add_edge("answer_from_state", "write_history")
    graph.add_edge("write_history", END)

    return graph.compile(checkpointer=checkpointer)


def get_compiled_graph():
    """Return the compiled graph singleton. Thread-safe after first call."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph(checkpointer=_langsmith_checkpointer)
    return _compiled_graph
