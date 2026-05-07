"""handle_follow_up node — processes follow_up_query_refinement actions.

Routes based on follow_up_mode:
- reuse_answer: returns cached prior answer directly
- rewrite_sql: rewrites prior SQL with modifications
- needs_full_compose: escalates to full build_context path (handled by route_after_resolve)
"""

import logging
from typing import Any

from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)


async def handle_follow_up(state: GraphState) -> dict[str, Any]:
    """Handle follow-up query refinement."""
    follow_up_mode = state.get("follow_up_mode")
    last_query_context = state.get("last_query_context") or {}
    last_answer = last_query_context.get("answer")

    logger.info(
        "handle_follow_up: mode=%s base_resolved_question=%s base_sql=%s",
        follow_up_mode,
        last_query_context.get("resolved_question", "None")[:50],
        last_query_context.get("sql", "None")[:50],
    )

    if follow_up_mode == "reuse_answer":
        if not last_answer:
            logger.warning("handle_follow_up: reuse_answer but no cached answer, escalating")
            return {
                "action": "clarification",
                "clarification_reason": "missing_prior_answer",
                "clarification_message": "No prior answer to reuse. Could you rephrase?",
                "clarification_options": ["Rephrase question", "Ask a new query"],
            }

        if state.get("event_queue"):
            await state.get("event_queue").put(
                {
                    "type": "stage",
                    "stage": "answering",
                    "label": "Answering from previous result...",
                    "progress": 90,
                }
            )

        return {
            "answer": last_answer,
            "generated_sql": last_query_context.get("sql"),
            "sql": last_query_context.get("sql"),
            "highlights": [],
            "suggested_followups": [],
        }

    if follow_up_mode == "rewrite_sql":
        return {
            "action": "follow_up_rewrite_sql",
            "resolved_question": state.get("resolved_question"),
            "clarification_reason": None,
            "clarification_message": None,
            "clarification_options": [],
        }

    # fallback: escalate to full compose
    logger.warning("handle_follow_up: unknown mode=%s, escalating to build_context", follow_up_mode)
    return {
        "action": "query",
        "resolved_question": state.get("resolved_question"),
        "clarification_reason": None,
        "clarification_message": None,
        "clarification_options": [],
    }


def route_after_follow_up(state: GraphState) -> str:
    """Route after follow-up handling."""
    action = state.get("action")

    if action == "clarification":
        return "write_history"

    if action == "follow_up_rewrite_sql":
        # Route to a minimal rewrite path - for now go through validate -> execute
        return "validate_sql"

    # reuse_answer - go straight to write_history
    return "write_history"