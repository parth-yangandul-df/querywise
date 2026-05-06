"""resolve_turn node — resolves the current message against conversation history.

Makes a single fast LLM call to determine:
  - action: "query" | "clarification" | "show_sql" | "explain_result"
  - resolved_question: standalone rewritten question (for query action only)
  - clarification data: reason, message, options (for clarification action)

Skipped entirely when loaded_history is empty (first turn → straight to query path).

Uses a fast cheap model tier — the resolver output is one small JSON object.
The confidence threshold is configurable via RESOLVE_TURN_CONFIDENCE_THRESHOLD env var.
"""

import json
import logging
import os
from typing import Any

from app.llm.base_provider import LLMConfig, LLMMessage
from app.llm.graph.state import GraphState
from app.llm.utils import repair_json

logger = logging.getLogger(__name__)

# Configurable threshold — below this, ask for clarification
_CONFIDENCE_THRESHOLD = float(os.getenv("RESOLVE_TURN_CONFIDENCE_THRESHOLD", "0.75"))

# Fast model for resolution — override via env.
# Defaults to None, which means fall back to the configured default model for the active provider.
_RESOLVER_MODEL: str | None = os.getenv("RESOLVER_MODEL") or None

_SYSTEM_PROMPT = """\
You are a query resolver for a database chatbot. Your job is to analyze the user's \
current message in the context of recent conversation and decide what action to take.

You must return ONLY a valid JSON object — no explanation, no markdown.

Actions:
- "query": The user wants to run a new or modified database query. Provide a \
  standalone resolved_question that fully expresses the query without needing any prior context.
- "show_sql": The user wants to see the SQL from the previous query (e.g. "show me the SQL", \
  "what was the query", "show in SQL"). No new query needed.
- "explain_result": The user wants an explanation of the previous result (e.g. "why is X here?", \
  "explain this", "why only N results?").
- "clarification": The message is too ambiguous to resolve confidently.

JSON schema:
{
  "action": "query" | "clarification" | "show_sql" | "explain_result",
  "confidence": <float 0.0-1.0>,
  "resolved_question": "<standalone question string, only for action=query, else null>",
  "clarification_reason": "<reason string or null>",
  "clarification_message": "<user-facing question string or null>",
  "clarification_options": ["option 1", "option 2"] or []
}

Rules:
- For "query": resolved_question MUST be fully self-contained — include all context from \
  prior turns needed to run this query fresh with no history.
- For "show_sql": set resolved_question to null. Only use this when the user clearly wants \
  to see the SQL code, not run a new query.
- For "explain_result": set resolved_question to null. Use when the user asks about the \
  meaning, correctness, or content of the previous result.
- For "clarification": provide a helpful clarification_message and 2-3 clarification_options.
- If confidence < 0.75, use "clarification" unless the intent is crystal clear.
"""

_USER_PROMPT_TEMPLATE = """\
Recent conversation:
{history}

Last SQL executed (if any):
{last_sql}

Current message: "{question}"

Resolve this message and return the JSON object."""


async def resolve_turn(state: GraphState) -> dict[str, Any]:
    """Resolve the current turn against conversation history."""
    history = state.get("loaded_history") or []

    # Skip resolve on first turn — no ambiguity possible
    if not history:
        return {
            "action": "query",
            "resolved_question": state["question"],
            "clarification_reason": None,
            "clarification_message": None,
            "clarification_options": [],
        }

    if state.get("event_queue"):
        await state["event_queue"].put(
            {
                "type": "stage",
                "stage": "understanding",
                "label": "Understanding your question...",
                "progress": 20,
            }
        )

    history_text = _format_history(history)
    last_sql = state.get("last_generated_sql") or "None"

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        history=history_text,
        last_sql=last_sql,
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
        return _default_query(state["question"])

    action = parsed.get("action", "query")
    confidence = float(parsed.get("confidence", 0.0))

    # Force clarification if confidence is below threshold (and not already clarification)
    if action != "clarification" and confidence < _CONFIDENCE_THRESHOLD:
        logger.info(
            "resolve_turn: low confidence %.2f for action=%s — asking clarification",
            confidence,
            action,
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

    return {
        "action": action,
        "resolved_question": parsed.get("resolved_question") or state["question"],
        "clarification_reason": parsed.get("clarification_reason"),
        "clarification_message": parsed.get("clarification_message"),
        "clarification_options": parsed.get("clarification_options") or [],
    }


def route_after_resolve(state: GraphState) -> str:
    """Conditional edge: route based on resolved action."""
    action = state.get("action", "query")
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
