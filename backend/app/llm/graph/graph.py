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
       │                                                     Formats the answer as a markdown
       │                                                     table directly (no LLM interpret step).
       │                                                          │
       ├─ action=explain_result ───→ answer_from_state            │
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

from app.llm.graph.nodes.answer_from_state import answer_from_state
from app.llm.graph.nodes.build_context_node import build_context_node
from app.llm.graph.nodes.compose_sql import compose_sql, route_after_compose
from app.llm.graph.nodes.execute_sql import execute_sql, route_after_execute
from app.llm.graph.nodes.handle_error import handle_error, route_after_handle_error
from app.llm.graph.nodes.handle_follow_up import handle_follow_up, route_after_follow_up
from app.llm.graph.nodes.history_writer import write_history
from app.llm.graph.nodes.load_history import load_history
from app.llm.graph.nodes.resolve_turn import resolve_turn, route_after_resolve
from app.llm.graph.nodes.show_schema import show_schema
from app.llm.graph.nodes.similarity_check import route_after_similarity, similarity_check
from app.llm.graph.nodes.validate_sql import route_after_validate, validate_sql
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)

_compiled_graph: Any = None


def _build_graph(checkpointer: Any | None = None) -> Any:
    """Build the LangGraph with optional checkpointer."""
    logger = logging.getLogger(__name__)
    logger.info("graph: building LangGraph pipeline")
    graph = StateGraph(GraphState)

    # ── Nodes ────────────────────────────────────────────────────────────
    graph.add_node("load_history", load_history)
    graph.add_node("resolve_turn", resolve_turn)
    graph.add_node("handle_follow_up", handle_follow_up)
    graph.add_node("build_context", build_context_node)
    graph.add_node("similarity_check", similarity_check)
    graph.add_node("compose_sql", compose_sql)
    graph.add_node("validate_sql", validate_sql)
    graph.add_node("handle_error", handle_error)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("answer_from_state", answer_from_state)
    graph.add_node("show_schema", show_schema)
    graph.add_node("write_history", write_history)

    # ── Entry ─────────────────────────────────────────────────────────────
    graph.set_entry_point("load_history")
    graph.add_edge("load_history", "resolve_turn")

    # ── resolve_turn → branch on action ──────────────────────────────────
    graph.add_conditional_edges(
        "resolve_turn",
        route_after_resolve,
        {
            "build_context": "build_context",  # query path + follow_up needs_full_compose
            "handle_follow_up": "handle_follow_up",  # follow_up reuse/rewrite path
            "answer_from_state": "answer_from_state",
            "write_history": "write_history",  # clarification path
        },
    )

    # ── Follow-up path ───────────────────────────────────────────────────
    graph.add_conditional_edges(
        "handle_follow_up",
        route_after_follow_up,
        {
            "execute_sql": "execute_sql",  # follow_up_rewrite_sql path — skip validation
            "build_context": "build_context",  # validation failed — escalate to full compose
            "write_history": "write_history",  # reuse_answer or clarification
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

    # Execute SQL: route to handle_error on failure, else write_history directly
    graph.add_conditional_edges(
        "execute_sql",
        route_after_execute,
        {
            "handle_error": "handle_error",  # execution failed — retry
            "write_history": "write_history",  # success — answer already formatted
        },
    )

    # ── Non-query paths ───────────────────────────────────────────────────
    graph.add_edge("answer_from_state", "write_history")
    graph.add_edge("show_schema", "write_history")
    graph.add_edge("write_history", END)

    return graph.compile(checkpointer=checkpointer)


def get_compiled_graph():
    """Return the compiled graph singleton. Thread-safe after first call."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_graph()
    return _compiled_graph
