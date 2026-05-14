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
import re
from typing import Any

from app.config import settings
from app.core.metrics import timed_node
from app.llm.base_provider import LLMMessage
from app.llm.graph.state import GraphState
from app.llm.stream_stages import UNDERSTANDING, emit
from app.llm.utils import repair_json

logger = logging.getLogger(__name__)


# Patterns that indicate the user wants to see schema / table listings.
# These should bypass SQL generation and return the schema cache directly.
_SCHEMA_INTROSPECTION_PATTERNS = [
    r"\bwhat tables\b",
    r"\bshow tables\b",
    r"\blist tables\b",
    r"\bwhich tables\b",
    r"\bwhat tables do you (have|know|see|access)\b",
    r"\bshow me (the |all )?tables\b",
    r"\bshow all (the )?tables\b",
    r"\bshow.*available tables\b",
    r"\btables (in|on|available|present)\b",
    r"\bwhat.*in (the |this )?database\b",
    r"\bshow.*schema\b",
    r"\bdatabase schema\b",
    r"\bwhat columns\b",
    r"\bshow columns\b",
    r"\blist columns\b",
    r"\btell me about (the |this )?schema\b",
    r"\bwhat can i query\b",
    r"\bwhat data (is|do you have)\b",
]

_STOP_WORDS = frozenset({
    "who", "what", "which", "how", "list", "show", "get",
    "the", "a", "in", "for", "and", "or", "all",
})


def _is_schema_introspection(question: str) -> bool:
    """Detect if the user is asking about schema/tables rather than data."""
    q_lower = question.lower()
    return any(re.search(p, q_lower) for p in _SCHEMA_INTROSPECTION_PATTERNS)


def _is_topic_switch(current_question: str, last_resolved: str) -> bool:
    """Detect if the current question is about a completely different topic.

    Heuristic: if the previous query was about a specific named entity (person,
    project, client) and the current question is about a different entity type,
    this is a topic switch — not a follow-up.
    """
    last_lower = last_resolved.lower()
    curr_lower = current_question.lower()

    # Previous query contained a specific person name (First + Last, capitalized).
    # e.g. "Who does Vivek Kumar report to?"
    name_match = re.search(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b", last_resolved)
    if name_match:
        person_name = name_match.group(1).lower()
        if person_name not in curr_lower:
            # Current question is NOT about the same person.
            # If it asks about a different entity type → topic switch.
            entity_indicators = [
                "business",
                "department",
                "project",
                "unit",
                "team",
                "office",
                "location",
                "company",
                "client",
                "account",
                "division",
                "group",
            ]
            if any(ind in curr_lower for ind in entity_indicators):
                return True

    # Previous was a specific lookup ("who does X report to") and current is
    # a broad count/group query about something else entirely.
    if "report to" in last_lower or "manager" in last_lower:
        if "how many" in curr_lower or "count" in curr_lower:
            if not re.search(r"\breport|manager|boss|supervisor", curr_lower):
                return True

    return False


_SYSTEM_PROMPT = """\
You are a query resolver for a database chatbot. Analyze the user's current message \
in the context of recent conversation and decide what action to take.

Return ONLY a valid JSON object — no explanation, no markdown.

Actions:
- "query": New or modified database query. Provide standalone resolved_question.
- "follow_up_query_refinement": Follow-up/refinement of previous query \
  (e.g., "from these...", "show only names", "add filter"). Builds on prior context. \
  Return follow_up_mode: reuse_answer | rewrite_sql | needs_full_compose.
- "explain_result": User wants explanation of previous result.
- "clarification": Message too ambiguous to resolve confidently.

JSON schema:
{
  "action": "query" | "follow_up_query_refinement" | "explain_result" | "clarification",
  "confidence": <float 0.0-1.0>,
  "resolved_question": "<standalone question string, only for query or follow_up>",
  "follow_up_mode": "reuse_answer" | "rewrite_sql" | "needs_full_compose" or null,
  "follow_up_reason": "<short reason>" or null,
  "clarification_reason": "<reason or null>",
  "clarification_message": "<user-facing question or null>",
  "clarification_options": ["option 1", "option 2"] or []
}

CRITICAL FOLLOW-UP RULES:
- If the user's message references the previous results using pronouns (these, those, them), 
  relative phrases (from the list, from above, from the result), or qualifiers combined 
  with previous context (e.g., "who know SQL" after benched resources, "add filter" 
  after previous list), classify as "follow_up_query_refinement" NOT "query".
- For follow_up, the resolved_question should COMBINE the previous query 
  context with the new qualifier. Example: "from these who know SQL" after 
  "benched resources" → "benched resources who know SQL".
- DO NOT convert to a standalone question unless it's clearly a new topic.

Rules:
- For "query": resolved_question must be fully self-contained ONLY if 
  it's a clearly different topic from the previous query.
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


@timed_node("resolve_turn")
async def resolve_turn(state: GraphState) -> dict[str, Any]:
    """Resolve the current turn against conversation history."""
    history = state.get("loaded_history") or []
    last_query_context = state.get("last_query_context")

    # Fast-path: schema introspection works even on first turn.
    # Must run BEFORE the empty-history short-circuit.
    if _is_schema_introspection(state["question"]):
        logger.info("resolve_turn: schema introspection detected — routing to show_schema")
        return {
            "action": "show_schema",
            "resolved_question": state["question"],
            "clarification_reason": None,
            "clarification_message": None,
            "clarification_options": [],
        }

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
        await state.get("event_queue").put(emit(UNDERSTANDING))

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
        from app.llm.router import route_for_role

        provider, config = route_for_role(state["question"], role="resolver")
        response = await provider.complete(messages, config)

        # Track token usage and cost in MLflow
        from app.core.mlflow_tracing import set_mlflow_llm_cost

        set_mlflow_llm_cost(
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            provider=provider.provider_type.value,
        )

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
    if action == "follow_up_query_refinement" and not settings.use_follow_up_path:
        action = "query"
        logger.info("resolve_turn: follow_up_path disabled by feature flag, converted to query")

    # Force clarification if confidence is below threshold (and not already clarification)
    if action != "clarification" and confidence < settings.resolve_turn_confidence_threshold:
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

    # Heuristic override: detect follow-ups the LLM missed.
    # If there's a previous successful query and the current message contains
    # follow-up signals ("these", "those", "how many of them", etc.), force
    # follow-up mode.  Runs AFTER confidence check because follow-ups with
    # clear pronoun references are structurally obvious — we don't need the
    # LLM's confidence in the classification.
    lqc = state.get("last_query_context")
    if lqc and action != "follow_up_query_refinement":
        last_resolved = lqc.get("resolved_question", "")
        if _is_topic_switch(state["question"], last_resolved):
            logger.info(
                "resolve_turn: topic switch detected (question=%r last=%r) "
                "— forcing query instead of follow-up",
                state["question"][:50],
                last_resolved[:50],
            )
        else:
            q_lower = state["question"].lower()
            last_q_lower = last_resolved.lower() if last_resolved else ""

            follow_up_signals = [
                r"\bthese\b",
                r"\bthose\b",
                r"\bthem\b",
                r"\bthey\b",
                r"\bhow many\b",
                r"\bcount (of|the)\b",
                r"\bfrom (the |those |these )?(above|result|list|table)\b",
                r"\bfrom (them|these|those)\b",
                r"\bshow only\b",
                r"\badd filter\b",
                r"\bfilter by\b",
                r"\bsort by\b",
                r"\border by\b",
                r"\bgive me (the |a )?(count|number|total)\b",
                r"\bwho (know|have|has)\b",
                r"\bwith (the )?(skill|experience)\b",
                r"\bfrom (the )?benched\b",
                r"\bfrom (the )?(list|result)\b",
            ]

            matched_any = any(re.search(p, q_lower) for p in follow_up_signals)

            if not matched_any and last_q_lower:
                combined_patterns = [
                    rf"\b{re.escape(word)}\b.*\b(sql|skill|bench|resource)\b"
                    for word in last_q_lower.split()
                    if len(word) > 3 and word not in _STOP_WORDS
                ]
                matched_any = any(
                    re.search(p, q_lower) for p in combined_patterns
                ) if combined_patterns else False

            if matched_any:
                action = "follow_up_query_refinement"
                parsed["follow_up_mode"] = "rewrite_sql"
                parsed["follow_up_reason"] = "heuristic_follow_up_detected"
                logger.info(
                    "resolve_turn: heuristic override -> follow_up_query_refinement "
                    "(question=%r last_sql_present=%s)",
                    state["question"][:50],
                    bool(lqc.get("sql")),
                )

    result: dict[str, Any] = {
        "action": action,
        "resolved_question": parsed.get("resolved_question") or state["question"],
        "clarification_reason": parsed.get("clarification_reason"),
        "clarification_message": parsed.get("clarification_message"),
        "clarification_options": parsed.get("clarification_options") or [],
    }

    # Topic switch: clear all prior context so the new query starts completely fresh.
    # This prevents stale schema_tables, last_query_context, or result previews
    # from leaking into a completely different topic's pipeline.
    last_resolved = lqc.get("resolved_question", "") if lqc else ""
    if action == "query" and lqc and _is_topic_switch(state["question"], last_resolved):
        result["last_query_context"] = None
        result["last_generated_sql"] = None
        result["last_result_columns"] = None
        result["last_result_preview_rows"] = None
        logger.info("resolve_turn: cleared prior context for topic switch")

    # Add follow-up mode if applicable
    if action == "follow_up_query_refinement":
        result["follow_up_mode"] = parsed.get("follow_up_mode")
        result["follow_up_reason"] = parsed.get("follow_up_reason")

        # FIX #4: If needs_full_compose, clear stale context to ensure fresh build
        # This prevents hallucinations from similarity-hit shortcuts with no schema
        if parsed.get("follow_up_mode") == "needs_full_compose":
            result["last_query_context"] = None
            result["last_generated_sql"] = None
            result["last_result_columns"] = None
            result["last_result_preview_rows"] = None
            logger.info("resolve_turn: cleared stale context for needs_full_compose follow-up")

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
    if action == "show_schema":
        return "show_schema"
    if action == "explain_result":
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
