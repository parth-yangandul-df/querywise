"""filter_extractor node — regex-first filter extraction with FieldRegistry validation.

Extracts structured FilterClause objects from the user's question by:
1. Running regex patterns against the question text
2. Validating extracted values against FieldRegistry for the current domain
3. Creating typed FilterClause objects with sanitized values
4. Handling follow-up turns by inheriting refine-mode context
5. Dropping unknown fields safely with a WARNING log (never crash)
6. Deferring LLM extraction to Plan 04 (stub logged)
7. (Plan 04) Resolving glossary hints for field disambiguation
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.llm.graph.query_plan import FilterClause, _sanitize_value

from app.llm.graph.nodes.field_registry import STATUS_ALIASES, lookup_field, resolve_alias
from app.llm.graph.state import GraphState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import for semantic_resolver — avoids circular imports and allows
# test isolation via patch on the attribute at filter_extractor module level.
# ---------------------------------------------------------------------------
try:
    from app.llm.graph.nodes.semantic_resolver import resolve_glossary_hints
except ImportError:
    resolve_glossary_hints = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Regex patterns — reused/extended from param_extractor.py
# ---------------------------------------------------------------------------

# Skill extraction
_SKILL_KW_RE = re.compile(
    r"\b(?:with skills?\s+(?:in\s+)?|skilled in|who knows?|expertise in|work(?:ing)? on|using|proficient in|experience (?:with|in))\s*([A-Za-z0-9#+.\-]+)",
    re.IGNORECASE,
)
_SKILL_TECH_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9#+.\-]*)\s+(?:developers?|engineers?)\b",
)
# "<TechWord> skill[s]" pattern — "Python skill", "Java skills"
_SKILL_WORD_BEFORE_RE = re.compile(
    r"\b([A-Za-z0-9#+.\-]+)\s+skills?\b",
    re.IGNORECASE,
)
_SKILL_STOP_WORDS: frozenset[str] = frozenset(
    {
        "active",
        "inactive",
        "with",
        "the",
        "a",
        "an",
        "and",
        "or",
        "no",
        "any",
        "all",
        "some",
        "their",
        "new",
        "old",
        "good",
        "bad",
        "key",
        "top",
        "my",
        "his",
        "her",
        "our",
        "your",
        "other",
        "primary",
        "secondary",
        "additional",
        "required",
        "specific",
    }
)

# ISO date: YYYY-MM-DD
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Resource name: proper noun after "for", "by", "assigned to", "of"
_NAME_RE = re.compile(
    r"\b(?:for|by|assigned to|of)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
)

# Project name
_PROJECT_NAME_RE = re.compile(
    r"\b(?:on project|for project|project named?|project called|about project)\s+"
    r"([A-Za-z0-9][A-Za-z0-9\-\s]+?)(?:\s*[?]?\s*$)",
    re.IGNORECASE,
)

# Client name
_CLIENT_NAME_RE = re.compile(
    r"\b(?:for client|by client|client named?|client called)\s+"
    r"([A-Za-z0-9][A-Za-z0-9\-\s]+?)(?:\s*[?]?\s*$)",
    re.IGNORECASE,
)

# Designation / title: "senior developer", "junior analyst", etc.
_DESIGNATION_RE = re.compile(
    r"\b(?:designation|titled?|role of|position of)\s+([A-Za-z][A-Za-z\s]+?)(?:\s+(?:resource|employee|people|person)|\s*[?]?\s*$)",
    re.IGNORECASE,
)

# Status filter: "active", "inactive", "pending", "completed", etc.
_STATUS_RE = re.compile(
    r"\b(active|inactive|pending|completed|closed|open|approved|unapproved)\b",
    re.IGNORECASE,
)

# Billable filter: "billable resources", "non-billable"
_BILLABLE_RE = re.compile(
    r"\b(non-?billable|billable)\b",
    re.IGNORECASE,
)

# Numeric threshold patterns
# "more than N hours", "at least N hours", "greater than N"
_HOURS_GT_RE = re.compile(
    r"\b(?:more than|at least|greater than|over|above)\s+(\d+(?:\.\d+)?)\s*hours?\b",
    re.IGNORECASE,
)
# "less than N hours", "under N hours", "below N hours"
_HOURS_LT_RE = re.compile(
    r"\b(?:less than|fewer than|under|below)\s+(\d+(?:\.\d+)?)\s*hours?\b",
    re.IGNORECASE,
)
# "minimum allocation N%"
_ALLOCATION_RE = re.compile(
    r"\b(?:min(?:imum)?\s+allocation|allocation\s+(?:of\s+)?(?:at\s+least\s+)?)\s*(\d+(?:\.\d+)?)\s*%?",
    re.IGNORECASE,
)
# "minimum budget N"
_BUDGET_RE = re.compile(
    r"\b(?:min(?:imum)?\s+budget|budget\s+(?:of\s+)?(?:at\s+least\s+)?)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
# "min experience N years"
_EXPERIENCE_RE = re.compile(
    r"\b(?:min(?:imum)?\s+experience|experience\s+(?:of\s+)?(?:at\s+least\s+)?)\s*(\d+(?:\.\d+)?)\s*(?:years?)?",
    re.IGNORECASE,
)
# "overdue by N days", "N days overdue"
_DAYS_OVERDUE_RE = re.compile(
    r"\b(?:overdue\s+(?:by\s+)?|(?:at\s+least\s+)?)(\d+)\s*days?\s+overdue\b|\boverdue\s+(?:by\s+)?(\d+)\s*days?\b",
    re.IGNORECASE,
)

# Fallback skill extraction for refine mode (bare word candidates)
_REFINE_STOP: frozenset[str] = frozenset(
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


def _make_filter(field: str, op: str, values: list[str], domain: str) -> FilterClause | None:
    """Create a FilterClause if the field is registered for this domain.

    Logs a WARNING and returns None if the field is unknown for the domain.
    Values are sanitized via QueryPlan's _sanitize_value before creation.
    """
    canonical = resolve_alias(field, domain)
    if canonical is None:
        logger.warning(
            "filter_extractor: field '%s' not in registry for domain '%s' — dropping",
            field,
            domain,
        )
        return None
    fc_meta = lookup_field(canonical, domain)
    if fc_meta is None:
        logger.warning(
            "filter_extractor: canonical field '%s' not found in domain '%s' registry — dropping",
            canonical,
            domain,
        )
        return None
    sanitized = [_sanitize_value(v) for v in values if v and v.strip()]
    if not sanitized:
        return None
    return FilterClause(field=canonical, op=op, values=sanitized)


async def extract_filters(state: GraphState) -> dict[str, Any]:
    """Extract structured FilterClause objects from the question.

    Phase 2 behavior:
    - Regex-first extraction against all known patterns
    - Validates each match against FieldRegistry for the current domain
    - Drops unknown/invalid fields with WARNING log
    - Handles follow-up turns via refine-mode fallback skill extraction
    - (Plan 04) Resolves glossary hints for field disambiguation
    - Returns {"filters": list[FilterClause]} (FilterClause objects directly)
    """
    question = state["question"]
    domain: str = state.get("domain") or ""
    intent: str = state.get("intent") or ""
    last_turn_context: dict = state.get("last_turn_context") or {}

    # Detect same-intent follow-up (refine mode)
    prior_sql = last_turn_context.get("sql", "")
    prior_intent = last_turn_context.get("intent")
    is_refine_mode = bool(prior_sql and prior_intent and intent and prior_intent == intent)

    filters: list[FilterClause] = []

    if not domain:
        # No domain classified → LLM fallback path, return empty
        logger.debug("filter_extractor: no domain set, returning empty filters")
    return {"filters": filters}


def validate_groq_filters(domain: str, raw_filters: list[dict]) -> list[dict]:
    """Validate and normalize Groq-extracted filters against the FieldRegistry.

    Drops filters whose field name is not in the registry for the given domain.
    Resolves field aliases. Returns only valid, normalized filter dicts.
    """
    from app.llm.graph.nodes.field_registry import FIELD_REGISTRY_BY_DOMAIN, resolve_alias

    domain_fields = FIELD_REGISTRY_BY_DOMAIN.get(domain, {})
    valid = []
    for f in raw_filters:
        field = f.get("field", "")
        # Try alias resolution
        resolved = resolve_alias(domain, field)
        if resolved:
            field = resolved
        if field not in domain_fields:
            logger.warning(
                "validate_groq_filters: field '%s' not in registry for domain '%s' — dropping",
                field,
                domain,
            )
            continue
        valid.append({**f, "field": field})
    return valid

    # ── 0. Glossary hint resolution (Plan 04 wiring) ─────────────────────
    # Resolve available field hints from glossary terms to aid disambiguation.
    # Degrades gracefully — regex extraction proceeds regardless of outcome.
    glossary_hints: list[str] = []
    db = state.get("db")
    connection_id = state.get("connection_id")
    if db is not None and connection_id is not None and resolve_glossary_hints is not None:
        try:
            glossary_hints = await resolve_glossary_hints(db, connection_id, domain)
            if glossary_hints:
                logger.debug(
                    "filter_extractor: glossary hints for domain='%s': %s",
                    domain,
                    glossary_hints,
                )
        except Exception:
            logger.warning(
                "filter_extractor: glossary hint resolution failed — continuing with regex only",
                exc_info=True,
            )

    # ── 1. Skill extraction ──────────────────────────────────────────────
    skill_match = _SKILL_KW_RE.search(question) or _SKILL_TECH_RE.search(question)
    if not skill_match:
        # Try "<TechWord> skill[s]" form (e.g. "Python skill", "Java skills")
        word_before = _SKILL_WORD_BEFORE_RE.search(question)
        if word_before and word_before.group(1).lower() not in _SKILL_STOP_WORDS:
            skill_match = word_before
    if skill_match:
        fc = _make_filter("skill", "eq", [skill_match.group(1)], domain)
        if fc:
            filters.append(fc)

    # ── 2. Refine-mode fallback skill extraction ─────────────────────────
    # Fires only when refine mode is active and no skill matched above.
    # Covers bare phrasing like "which of these know Python".
    if is_refine_mode and not any(f.field == "skill" for f in filters):
        candidates = [
            w
            for w in re.findall(r"[A-Za-z][A-Za-z0-9#+.\-]*", question)
            if w.lower() not in _REFINE_STOP and len(w) >= 2
        ]
        if candidates:
            fc = _make_filter("skill", "eq", [candidates[0]], domain)
            if fc:
                filters.append(fc)

    # ── 3. Date extraction ───────────────────────────────────────────────
    dates = _DATE_RE.findall(question)
    if len(dates) == 1:
        fc = _make_filter("start_date", "eq", [dates[0]], domain)
        if fc:
            filters.append(fc)
    elif len(dates) >= 2:
        fc = _make_filter("start_date", "between", [dates[0], dates[1]], domain)
        if fc:
            filters.append(fc)

    # ── 4. Project name extraction ───────────────────────────────────────
    project_match = _PROJECT_NAME_RE.search(question)
    if project_match:
        fc = _make_filter("project_name", "eq", [project_match.group(1).strip()], domain)
        if fc:
            filters.append(fc)

    # ── 5. Client name extraction ────────────────────────────────────────
    client_match = _CLIENT_NAME_RE.search(question)
    if client_match:
        fc = _make_filter("client_name", "eq", [client_match.group(1).strip()], domain)
        if fc:
            filters.append(fc)

    # ── 6. Resource name extraction ──────────────────────────────────────
    # Only if no project/client match claimed the name slot
    if not project_match and not client_match:
        name_match = _NAME_RE.search(question)
        if name_match:
            fc = _make_filter("resource_name", "eq", [name_match.group(1)], domain)
            if fc:
                filters.append(fc)

    # ── 7. Numeric threshold patterns ────────────────────────────────────
    # Hours > N
    hours_gt = _HOURS_GT_RE.search(question)
    if hours_gt:
        fc = _make_filter("min_hours", "gt", [hours_gt.group(1)], domain)
        if fc:
            filters.append(fc)

    # Hours < N
    hours_lt = _HOURS_LT_RE.search(question)
    if hours_lt and not hours_gt:  # mutually exclusive: gt takes priority
        fc = _make_filter("min_hours", "lt", [hours_lt.group(1)], domain)
        if fc:
            filters.append(fc)

    # Min allocation %
    alloc_match = _ALLOCATION_RE.search(question)
    if alloc_match:
        fc = _make_filter("min_allocation", "gt", [alloc_match.group(1)], domain)
        if fc:
            filters.append(fc)

    # Min budget
    budget_match = _BUDGET_RE.search(question)
    if budget_match:
        fc = _make_filter("min_budget", "gt", [budget_match.group(1)], domain)
        if fc:
            filters.append(fc)

    # Min experience
    exp_match = _EXPERIENCE_RE.search(question)
    if exp_match:
        fc = _make_filter("min_experience", "gt", [exp_match.group(1)], domain)
        if fc:
            filters.append(fc)

    # Days overdue
    overdue_match = _DAYS_OVERDUE_RE.search(question)
    if overdue_match:
        days = overdue_match.group(1) or overdue_match.group(2)
        if days:
            fc = _make_filter("days_overdue", "gt", [days], domain)
            if fc:
                filters.append(fc)

    # ── 8. Designation extraction ────────────────────────────────────────
    desig_match = _DESIGNATION_RE.search(question)
    if desig_match:
        fc = _make_filter("designation", "eq", [desig_match.group(1).strip()], domain)
        if fc:
            filters.append(fc)

    # ── 9. Billable extraction ────────────────────────────────────────────
    billable_match = _BILLABLE_RE.search(question)
    if billable_match:
        val = "0" if "non" in billable_match.group(1).lower() else "1"
        fc = _make_filter("billable", "eq", [val], domain)
        if fc:
            filters.append(fc)

    # ── 10. Status extraction ────────────────────────────────────────────
    # Extract status values like "active", "inactive", "pending", etc.
    # Map to canonical "status" field which resolves to StatusName column
    status_match = _STATUS_RE.search(question)
    if status_match:
        status_val = status_match.group(1)
        # Normalize via STATUS_ALIASES — keeps canonical casing aligned with DOMAIN_STATUS_IDS
        canonical = STATUS_ALIASES.get(status_val.lower(), status_val.capitalize())
        fc = _make_filter("status", "eq", [canonical], domain)
        if fc:
            filters.append(fc)

    # ── 11. LLM fallback stub ────────────────────────────────────────────
    if not filters:
        logger.debug(
            "filter_extractor: no regex matches for domain='%s', intent='%s'. "
            "LLM extraction deferred to Plan 04.",
            domain,
            intent,
        )

    # ── Log extracted filters ─────────────────────────────────────────────
    filter_summary = (
        ", ".join(f"{f.field}={f.op}:{f.values}" for f in filters) if filters else "none"
    )
    logger.info(
        "filter_extractor: domain=%s intent=%s extracted_filters=[%s]",
        domain,
        intent,
        filter_summary,
    )

    return {"filters": filters}
