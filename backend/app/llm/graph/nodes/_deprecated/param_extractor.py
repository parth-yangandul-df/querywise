# DEPRECATED: superseded by filter_extractor.py (Phase 7, Plan 02).
# Kept at original path for backward compatibility with existing tests and the
# flag=OFF refinement path. Archived copy also at _deprecated/param_extractor.py.
# Delete after USE_QUERY_PLAN_COMPILER=true is confirmed in production.
"""extract_params node — regex/keyword parameter extraction. No LLM calls."""

from __future__ import annotations

import re
from typing import Any

from app.llm.graph.state import GraphState

# Skill extraction — two separate patterns to avoid IGNORECASE contaminating group 2.
# Group 1 (keyword-triggered): "with skill X", "with skills X", "skilled in X",
#   "who knows X", "expertise in X", "work on X", "using X", "proficient in X",
#   "experience with/in X" — case-insensitive, captures the word after the trigger.
_SKILL_KW_RE = re.compile(
    r"\b(?:with skills?\s+(?:in\s+)?|skilled in|who knows?|expertise in|work(?:ing)? on|using|proficient in|experience (?:with|in))\s*([A-Za-z0-9#+.\-]+)",
    re.IGNORECASE,
)
# Group 2 (tech-word before role noun): "Python developers", "Java engineers" —
#   NOT case-insensitive so generic adjectives like "active" don't match.
_SKILL_TECH_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9#+.\-]*)\s+(?:developers?|engineers?)\b",
)

# ISO date: YYYY-MM-DD
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Resource name: proper noun (Title Case word) after "for", "by", "assigned to", "of"
_NAME_RE = re.compile(
    r"\b(?:for|by|assigned to|of)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)

# Project name: everything after "on project", "for project", "project named/called", "about project"
# Captures until end-of-string or a question mark; handles hyphens, spaces, mixed case
_PROJECT_NAME_RE = re.compile(
    r"\b(?:on project|for project|project named?|project called|about project)\s+"
    r"([A-Za-z0-9][A-Za-z0-9\-\s]+?)(?:\s*[?]?\s*$)",
    re.IGNORECASE,
)

# Client name: "for client X", "by client X", "client named/called X"
_CLIENT_NAME_RE = re.compile(
    r"\b(?:for client|by client|client named?|client called)\s+"
    r"([A-Za-z0-9][A-Za-z0-9\-\s]+?)(?:\s*[?]?\s*$)",
    re.IGNORECASE,
)


async def extract_params(state: GraphState) -> dict[str, Any]:
    """Extract structured parameters from the question using regex only.

    Context-aware behavior:
    - Inherits params from last_turn_context (carry-forward from prior turn)
    - Newly extracted params overlay inherited ones (new wins on conflict)
    - Internal refine keys (_refine_mode, _prior_sql, _prior_columns) are stripped
      from inherited params so they don't cascade across multiple hops
    - Sets _refine_mode=True + _prior_sql + _prior_columns when the current intent
      matches the prior turn's intent and there is a prior SQL to refine against
    """
    question = state["question"]
    last_turn_context = state.get("last_turn_context") or {}

    # Start with inherited params from prior turn (carry-forward)
    params: dict[str, Any] = dict(last_turn_context.get("params") or {})
    # Remove internal refine-mode keys from inherited params so they don't carry
    # across multiple hops
    params.pop("_refine_mode", None)
    params.pop("_prior_sql", None)
    params.pop("_prior_columns", None)

    # Skill — keyword-trigger pattern first, then tech-word-before-role pattern
    skill_match = _SKILL_KW_RE.search(question) or _SKILL_TECH_RE.search(question)
    if skill_match:
        params["skill"] = skill_match.group(1)

    # Dates (first = start, second = end if present)
    dates = _DATE_RE.findall(question)
    if dates:
        params["start_date"] = dates[0]
    if len(dates) >= 2:
        params["end_date"] = dates[1]

    # Project name (must run before generic resource name to avoid conflicts)
    project_match = _PROJECT_NAME_RE.search(question)
    if project_match:
        params["project_name"] = project_match.group(1).strip()

    # Client name
    client_match = _CLIENT_NAME_RE.search(question)
    if client_match:
        params["client_name"] = client_match.group(1).strip()

    # Resource name (generic fallback — only set if no project/client match claimed it)
    name_match = _NAME_RE.search(question)
    if name_match:
        params["resource_name"] = name_match.group(1)

    # Set refine mode if this is a same-intent follow-up with prior SQL available
    prior_sql = last_turn_context.get("sql", "")
    prior_intent = last_turn_context.get("intent")
    current_intent = state.get("intent")
    if prior_sql and prior_intent and current_intent and prior_intent == current_intent:
        params["_refine_mode"] = True
        params["_prior_sql"] = prior_sql
        params["_prior_columns"] = last_turn_context.get("columns", [])

    # Fallback skill extraction for refinement follow-ups.
    # Fires only when _refine_mode is active and the existing regexes above
    # didn't capture a skill (they require explicit trigger phrases like
    # "who knows X" or "with skill X"). Bare phrasing such as
    # "which of these know Python" would otherwise leave skill unset and
    # cause ResourceAgent._run_refinement() to fall back to the full query.
    if params.get("_refine_mode") and not params.get("skill"):
        _refine_stop: frozenset[str] = frozenset(
            {
                "which",
                "one",
                "of",
                "these",
                "those",
                "them",
                "who",
                "the",
                "a",
                "an",
                "know",
                "knows",
                "can",
                "are",
                "is",
                "and",
                "or",
                "have",
                "do",
                "does",
                "show",
                "me",
                "list",
                "among",
                "filter",
                "only",
                "same",
                "ones",
                "from",
                "skill",
                "skills",
                "with",
                "by",
                "in",
                "for",
            }
        )
        candidates = [
            w
            for w in re.findall(r"[A-Za-z][A-Za-z0-9#+.\-]*", question)
            if w.lower() not in _refine_stop and len(w) >= 2
        ]
        if candidates:
            params["skill"] = candidates[0]

    return {"params": params}
