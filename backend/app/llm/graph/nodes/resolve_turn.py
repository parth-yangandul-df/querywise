"""resolve_turn node — resolves the current message against conversation history.

Makes a single fast LLM call to determine:
  - action: 5 possible values (query, follow_up_query_refinement, show_sql, etc.)
  - resolved_question: standalone rewritten question
  - follow_up_mode: reuse_answer | rewrite_sql | needs_full_compose
  - clarification data for ambiguous cases

Skipped entirely when loaded_history is empty (first turn → straight to query path).

Uses a fast cheap model tier — the resolver output is one small JSON object.
The confidence threshold is configurable via RESOLVE_TURN_CONFIDENCE_THRESHOLD env var.
"""

import json
import logging
import os
from typing import Any

from app.config import settings
from app.llm.base_provider import LLMConfig, LLMMessage
from app.llm.graph.state import GraphState
from app.llm.utils import repair_json

logger = logging.getLogger(__name__)

# Configurable threshold — below this, ask for clarification
_CONFIDENCE_THRESHOLD = float(os.getenv("RESOLVE_TURN_CONFIDENCE_THRESHOLD", "0.75"))

# Fast model for resolution — override via env.
# Defaults to None, which means fall back to the configured default model for the active provider.
_RESOLVER_MODEL: str | None = os.getenv("RESOLVER_MODEL") or None

# Feature flag check
_USE_FOLLOW_UP_PATH = (
    os.getenv("USE_FOLLOW_UP_PATH", "").lower() == "true" or settings.use_follow_up_path
)

_SYSTEM_PROMPT = """\
You are a query resolver for a database chatbot. Analyze the user's current message \
in the context of recent conversation and decide what action to take.

Return ONLY a valid JSON object — no explanation, no markdown.

Actions:
- "query": New or modified database query. Provide standalone resolved_question.
- "follow_up_query_refinement": Follow-up/refinement of previous query \
  (e.g., "from these...", "show only names", "add filter"). Builds on prior context. \
  Return follow_up_mode: reuse_answer | rewrite_sql | needs_full_compose.
- "show_sql": User wants to see previous SQL. No new query needed.
- "explain_result": User wants explanation of previous result.
- "clarification": Message too ambiguous to resolve confidently.

JSON schema:
{
  "action": "query" | "follow_up_query_refinement" | "clarification" |
            "show_sql" | "explain_result",
  "confidence": <float 0.0-1.0>,
  "resolved_question": "<standalone question string, only for query or follow_up>",
  "follow_up_mode": "reuse_answer" | "rewrite_sql" | "needs_full_compose" or null,
  "follow_up_reason": "<short reason>" or null,
  "clarification_reason": "<reason or null>",
  "clarification_message": "<user-facing question or null>",
  "clarification_options": ["option 1", "option 2"] or []
}

Rules:
- For "query": resolved_question must be fully self-contained.
- For "follow_up": reuse_answer if cached answer works, rewrite_sql if SQL needs change, \
  needs_full_compose if context insufficient.
- For "show_sql" / "explain_result": set resolved_question to null.
- For "clarification": provide helpful message + 2-3 options.
- If confidence < 0.75, use "clarification" unless intent crystal clear.
- Do NOT use "follow_up_query_refinement" if feature flag disabled — fallback to "query".
"""

_USER_PROMPT_TEMPLATE = """\
Recent conversation:
{history}

Last successful query (if any):
- resolved_question: {last_resolved_question}
- SQL: {last_sql}
- Answer: {last_answer}
- Result status: {result_status}

Current message: "{question}"

Resolve this message and return the JSON object."""


async def resolve_turn(state: GraphState) -> dict[str, Any]:
    """Resolve the current turn against conversation history."""
    history = state.get("loaded_history") or []
    last_query_context = state.get("last_query_context")

    # Skip resolve on first turn — no ambiguity possible
    if not history:
        logger.info(
            "resolve_turn: history_count=0 action=query resolved_question=%s",
            state["question"][:50],
        )
        return {
            "action": "query",
            "resolved_question": state["question"],
            "clarification_reason": None,
            "clarification_message": None,
            "clarification_options": [],
        }

    if state.get("event_queue"):
        await state.get("event_queue").put(
            {
                "type": "stage",
                "stage": "understanding",
                "label": "Understanding your question...",
                "progress": 20,
            }
        )

    history_text = _format_history(history)
    last_sql = state.get("last_generated_sql") or "None"
    lqc = last_query_context
    last_resolved = lqc.get("resolved_question") if lqc else "None"
    last_ans = lqc.get("answer") if lqc else "None"
    result_st = lqc.get("result_status", "unknown") if lqc else "unknown"

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        history=history_text,
        last_resolved_question=last_resolved[:100] if last_resolved != "None" else "None",
        last_sql=last_sql[:200] if last_sql != "None" else "None",
        last_answer=last_ans[:200] if last_ans != "None" else "None",
        result_status=result_st,
        question=state["question"],
    )

    messages = [
        LLMMessage(role="system", content=_SYSTEM_PROMPT),
        LLMMessage(role="user", content=user_prompt),
    ]

    try:
        from app.llm.router import route

        provider, default_config = route(state["question"])
        resolver_model = _RESOLVER_MODEL or default_config.model
        config = LLMConfig(model=resolver_model, temperature=0.0, max_tokens=512)
        response = await provider.complete(messages, config)
        parsed = json.loads(repair_json(response.content))
    except Exception:
        logger.warning("resolve_turn: LLM call failed, defaulting to query", exc_info=True)
        result = _default_query(state["question"])
        logger.info(
            "resolve_turn: history_count=%d action=%s resolved_question=%s last_sql_present=%s",
            len(history),
            result["action"],
            result["resolved_question"][:50] if result["resolved_question"] else "None",
            last_sql != "None",
        )
        return result

    action = parsed.get("action", "query")
    confidence = float(parsed.get("confidence", 0.0))

    # Disable follow_up_path if feature flag is off
    if action == "follow_up_query_refinement" and not _USE_FOLLOW_UP_PATH:
        action = "query"
        logger.info("resolve_turn: follow_up_path disabled by feature flag, converted to query")

    # Force clarification if confidence is below threshold (and not already clarification)
    if action != "clarification" and confidence < _CONFIDENCE_THRESHOLD:
        logger.info(
            "resolve_turn: history_count=%d action=%s confidence=%.2f -> clarification",
            len(history),
            action,
            confidence,
        )
        return {
            "action": "clarification",
            "resolved_question": None,
            "clarification_reason": "low_confidence_rewrite",
            "clarification_message": parsed.get(
                "clarification_message",
                "I'm not sure what you mean. Could you clarify what you'd like to do?",
            ),
            "clarification_options": parsed.get("clarification_options", []),
        }

    result = {
        "action": action,
        "resolved_question": parsed.get("resolved_question") or state["question"],
        "clarification_reason": parsed.get("clarification_reason"),
        "clarification_message": parsed.get("clarification_message"),
        "clarification_options": parsed.get("clarification_options") or [],
    }

    # Add follow-up mode if applicable
    if action == "follow_up_query_refinement":
        result["follow_up_mode"] = parsed.get("follow_up_mode")
        result["follow_up_reason"] = parsed.get("follow_up_reason")

    logger.info(
        "resolve_turn: history_count=%d action=%s confidence=%.2f resolved_question=%s "
        "follow_up_mode=%s last_sql_present=%s",
        len(history),
        result["action"],
        confidence,
        result["resolved_question"][:50] if result["resolved_question"] else "None",
        result.get("follow_up_mode"),
        last_sql != "None",
    )

    return result


def route_after_resolve(state: GraphState) -> str:
    """Conditional edge: route based on resolved action."""
    action = state.get("action", "query")

    if action == "follow_up_query_refinement":
        follow_up_mode = state.get("follow_up_mode")
        logger.info(
            "route_after_resolve: follow_up_path mode=%s reason=%s",
            follow_up_mode,
            state.get("follow_up_reason"),
        )
        if follow_up_mode == "needs_full_compose":
            return "build_context"
        # reuse_answer and rewrite_sql both handled via follow_up_resolver (new node)
        # For now, we'll handle them here by routing to a simple handler
        return "handle_follow_up"

    if action == "query":
        return "build_context"
    if action in ("show_sql", "explain_result"):
        return "answer_from_state"
    return "write_history"  # clarification — skip execution entirely


def _format_history(history: list[dict]) -> str:
    lines = []
    for turn in history:
        role = turn.get("role", "user").capitalize()
        content = turn.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _default_query(question: str) -> dict[str, Any]:
    return {
        "action": "query",
        "resolved_question": question,
        "clarification_reason": None,
        "clarification_message": None,
        "clarification_options": [],
    }
