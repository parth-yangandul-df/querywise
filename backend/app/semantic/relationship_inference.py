"""Inferred relationship rules for SQL Server schemas with sparse enforced FKs.

When a SQL Server database does not have enforced foreign-key constraints
(or they are not captured by introspection), the LLM has no join guidance and
will guess — often incorrectly.  This module provides a curated set of
*inferred* join rules derived from column-name conventions.

These rules are:
  - Applied at query time (not stored as CachedRelationship rows)
  - Distinguished from declared FKs in the assembled prompt
  - Used by context_builder to pull in referenced tables even when they are
    not selected by the embedding / keyword retrieval stages

Confirmed join rules for the PRMS SQL Server schema
(validated by the project team):
  Client.StatusId          -> Status.StatusId       (ReferenceId=1)
  Project.ProjectStatusId  -> Status.StatusId       (ReferenceId=2)
  Project.ClientId         -> Client.ClientId
  Resource.ReportingTo     -> Resource.ResourceId   (self-join)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class InferredRelationship:
    """A join rule inferred from column-naming conventions rather than FK metadata."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    # Optional: the target table must satisfy this extra WHERE filter in join context.
    # E.g. for Status lookups the filter would be "ReferenceId = 1".
    filter_hint: str | None = None
    # Human-readable note injected into the LLM prompt
    note: str | None = None


# ---------------------------------------------------------------------------
# Curated inferred join rules — expand as more are confirmed
# ---------------------------------------------------------------------------
_INFERRED_RULES: list[InferredRelationship] = [
    InferredRelationship(
        source_table="Client",
        source_column="StatusId",
        target_table="Status",
        target_column="StatusId",
        filter_hint="Status.ReferenceId = 1",
        note=(
            "Client status label: JOIN Status ON Client.StatusId = Status.StatusId"
            " AND Status.ReferenceId = 1"
        ),
    ),
    InferredRelationship(
        source_table="Project",
        source_column="ProjectStatusId",
        target_table="Status",
        target_column="StatusId",
        filter_hint="Status.ReferenceId = 2",
        note=(
            "Project status label: JOIN Status ON Project.ProjectStatusId = Status.StatusId"
            " AND Status.ReferenceId = 2"
        ),
    ),
    InferredRelationship(
        source_table="Project",
        source_column="ClientId",
        target_table="Client",
        target_column="ClientId",
        note="Project belongs to Client: JOIN Client ON Project.ClientId = Client.ClientId",
    ),
    InferredRelationship(
        source_table="Resource",
        source_column="ReportingTo",
        target_table="Resource",
        target_column="ResourceId",
        note=(
            "Reporting hierarchy self-join: JOIN Resource AS Manager "
            "ON Resource.ReportingTo = Manager.ResourceId"
        ),
    ),
    InferredRelationship(
        source_table="ProjectResource",
        source_column="ResourceId",
        target_table="Resource",
        target_column="ResourceId",
        note=(
            "Allocation to resource: JOIN Resource"
            " ON ProjectResource.ResourceId = Resource.ResourceId"
        ),
    ),
    InferredRelationship(
        source_table="ProjectResource",
        source_column="ProjectId",
        target_table="Project",
        target_column="ProjectId",
        note="Allocation to project: JOIN Project ON ProjectResource.ProjectId = Project.ProjectId",
    ),
]


def _question_words(question: str) -> set[str]:
    """Extract lowercase words of length >= 3 from the question."""
    return {w.lower() for w in re.split(r"[^a-zA-Z]", question) if len(w) >= 3}


def _rule_words(rule: InferredRelationship) -> set[str]:
    """Extract candidate words from a rule's fields for relevance matching.

    Splits CamelCase identifiers so e.g. 'ProjectStatusId' yields
    {'project', 'status', 'statusid', 'projectstatusid'}.
    """
    words: set[str] = set()
    fields = [
        rule.source_column,
        rule.target_table,
        rule.filter_hint or "",
        rule.note or "",
    ]
    for field in fields:
        # Include the raw lowercased token
        words.add(field.lower())
        # Split on non-alphanumeric boundaries
        for part in re.split(r"[^a-zA-Z]", field):
            if len(part) >= 3:
                words.add(part.lower())
        # Split CamelCase: 'ProjectStatusId' → ['Project', 'Status', 'Id']
        camel_parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", field).split()
        for part in camel_parts:
            if len(part) >= 3:
                words.add(part.lower())
    return words


def get_inferred_relationships(
    selected_table_names: list[str],
    question: str = "",
) -> list[InferredRelationship]:
    """Return inferred join rules relevant to the currently selected tables.

    A rule is included when:
    1. The *source* table is in the selected set, AND
    2. Either no question is provided, OR the rule has keyword overlap with the question.

    Keyword filtering prevents irrelevant rules from forcing unneeded lookup
    tables (e.g. Status, Client) into context for unrelated queries.

    Args:
        selected_table_names: Table names (case-insensitive) currently in context.
        question: The user's original question for keyword relevance filtering.

    Returns:
        Filtered list of InferredRelationship objects.
    """
    selected_lower = {n.lower() for n in selected_table_names}
    q_words = _question_words(question) if question else set()

    applicable: list[InferredRelationship] = []
    for rule in _INFERRED_RULES:
        if rule.source_table.lower() not in selected_lower:
            continue
        # If we have question keywords, require overlap with the rule's vocabulary
        if q_words:
            rule_vocab = _rule_words(rule)
            if not (q_words & rule_vocab):
                logger.debug(
                    "relationship_inference: skipping rule %s.%s -> %s (no keyword overlap)",
                    rule.source_table,
                    rule.source_column,
                    rule.target_table,
                )
                continue
        applicable.append(rule)

    if applicable:
        logger.info(
            "relationship_inference: %d inferred rules for tables %s: %s",
            len(applicable),
            selected_table_names,
            [
                (r.source_table, r.source_column, r.target_table, r.target_column)
                for r in applicable
            ],
        )
    return applicable


def get_referenced_tables(
    selected_table_names: list[str],
    question: str = "",
) -> list[str]:
    """Return table names referenced by inferred rules but not yet in the selected set.

    Uses the same keyword filtering as get_inferred_relationships to avoid
    force-including lookup tables that are not relevant to the question.

    Use this to force-include lookup tables (e.g. Status) that the retrieval
    stage might have missed.
    """
    selected_lower = {n.lower() for n in selected_table_names}
    # Reuse get_inferred_relationships to respect keyword filtering
    applicable = get_inferred_relationships(selected_table_names, question=question)

    missing: list[str] = []
    seen: set[str] = set()
    for rule in applicable:
        target_lower = rule.target_table.lower()
        # Skip self-joins (source == target)
        if (
            target_lower != rule.source_table.lower()
            and target_lower not in selected_lower
            and target_lower not in seen
        ):
            missing.append(rule.target_table)
            seen.add(target_lower)
    return missing
