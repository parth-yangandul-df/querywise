"""semantic_resolver — bridge between the semantic layer and the QueryPlan compiler.

Provides three capabilities:
1. resolve_glossary_hints()  — loads glossary terms from DB and returns available field names
   for the current domain, used to disambiguate ambiguous filter extractions.
2. load_value_map()          — loads dictionary entries from DB and returns a nested dict
   {field_name: {user_value: db_value}} for normalizing user-friendly values to DB values.
3. normalize_value()         — maps a single user value to its DB equivalent via value_map.
4. normalize_values_batch()  — applies normalize_value to all text fields in a FilterClause list.

All functions degrade gracefully: DB unavailability returns empty results, never raises.

Module-level cache:
    _value_map_cache — populated by load_value_map() on first call or startup.
    Subsequent calls via get_cached_value_map() return the cached dict without DB hits.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.graph.nodes.field_registry import FIELD_REGISTRY, FIELD_REGISTRY_BY_DOMAIN
from app.llm.graph.query_plan import FilterClause

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level value_map cache — populated at startup, reused per-query
# ---------------------------------------------------------------------------

_value_map_cache: dict[str, dict[str, str]] = {}


def get_cached_value_map() -> dict[str, dict[str, str]]:
    """Return the in-memory value_map cache.

    Returns the dict populated by load_value_map() at startup.
    If not yet populated, returns an empty dict (graceful degradation).
    """
    return _value_map_cache


# ---------------------------------------------------------------------------
# resolve_glossary_hints
# ---------------------------------------------------------------------------


async def resolve_glossary_hints(
    db: AsyncSession,
    connection_id: str,
    domain: str,
) -> list[str]:
    """Return available field names from glossary terms for the given domain.

    Queries the DB for glossary terms associated with connection_id. For each term,
    extracts field names from related_columns, validates them against the FieldRegistry
    for the current domain, and returns a deduplicated list of valid field names.

    Args:
        db: The async SQLAlchemy session.
        connection_id: The connection UUID string (or any hashable key).
        domain: The current query domain (e.g. "resource", "project").

    Returns:
        List of valid field names relevant to the domain. Empty on any error.
    """
    try:
        from app.db.models.glossary import GlossaryTerm

        result = await db.execute(
            select(GlossaryTerm).where(GlossaryTerm.connection_id == connection_id)
        )
        terms = result.scalars().all()

        domain_fields = FIELD_REGISTRY_BY_DOMAIN.get(domain, {})
        hints: list[str] = []
        seen: set[str] = set()

        for term in terms:
            related_cols: list[str] = term.related_columns or []
            for col in related_cols:
                col_lower = col.lower()
                # Check if this column name is a valid field in the domain
                if col_lower in domain_fields and col_lower not in seen:
                    hints.append(col_lower)
                    seen.add(col_lower)
                # Also check against field aliases
                for field_name, fc in domain_fields.items():
                    if col_lower == field_name.lower() and field_name not in seen:
                        hints.append(field_name)
                        seen.add(field_name)

        logger.debug(
            "semantic_resolver: resolved %d glossary hints for domain='%s' connection='%s'",
            len(hints),
            domain,
            connection_id,
        )
        return hints

    except Exception:
        logger.warning(
            "semantic_resolver: glossary hint resolution failed for domain='%s' — degrading to empty",
            domain,
            exc_info=True,
        )
        return []


# ---------------------------------------------------------------------------
# load_value_map
# ---------------------------------------------------------------------------


async def load_value_map(db: AsyncSession) -> dict[str, dict[str, str]]:
    """Load dictionary entries from DB into a field-keyed value map.

    Returns a nested dict: {column_name_lower: {raw_value_lower: display_value}}.

    The returned dict can be used by normalize_value() for O(1) lookups.
    Also populates the module-level _value_map_cache for future calls via
    get_cached_value_map().

    Args:
        db: The async SQLAlchemy session.

    Returns:
        Nested dict. Empty dict on any DB error (graceful degradation).
    """
    global _value_map_cache

    try:
        from sqlalchemy.orm import joinedload

        from app.db.models.dictionary import DictionaryEntry

        result = await db.execute(
            select(DictionaryEntry).options(joinedload(DictionaryEntry.column))
        )
        entries = result.scalars().all()

        value_map: dict[str, dict[str, str]] = {}

        for entry in entries:
            col = entry.column
            if col is None:
                continue

            # Map by column_name (lowercased for lookup)
            col_name_lower = col.column_name.lower() if col.column_name else ""
            if not col_name_lower:
                continue

            if col_name_lower not in value_map:
                value_map[col_name_lower] = {}

            # Store raw_value → display_value (raw lowercased for case-insensitive lookup)
            raw_lower = entry.raw_value.lower() if entry.raw_value else ""
            value_map[col_name_lower][raw_lower] = entry.display_value

        logger.info(
            "semantic_resolver: loaded value_map with %d field(s) from dictionary entries",
            len(value_map),
        )

        # Populate module-level cache
        _value_map_cache = value_map
        return value_map

    except Exception:
        logger.warning(
            "semantic_resolver: value_map loading failed — degrading to empty map",
            exc_info=True,
        )
        return {}


# ---------------------------------------------------------------------------
# normalize_value
# ---------------------------------------------------------------------------


def normalize_value(
    value: str,
    field: str,
    value_map: dict[str, dict[str, str]],
) -> str:
    """Map a single user value to its DB equivalent via value_map.

    Looks up value_map[field][value.lower()]. If found, returns the DB value.
    If not found (field not in map, or value not in field's map), returns
    the original value unchanged.

    Case-insensitive on the input value — the lookup uses value.lower().

    Args:
        value: The user-provided filter value.
        field: The canonical field name (e.g. "designation", "status").
        value_map: Nested dict from load_value_map().

    Returns:
        The normalized DB value, or original value if no mapping found.
    """
    field_map = value_map.get(field.lower(), {})
    if not field_map:
        return value

    lookup_key = value.lower() if value else ""
    mapped = field_map.get(lookup_key)
    if mapped is not None:
        return mapped

    return value


# ---------------------------------------------------------------------------
# normalize_values_batch
# ---------------------------------------------------------------------------


def normalize_values_batch(
    filters: list[FilterClause],
    value_map: dict[str, dict[str, str]],
) -> list[FilterClause]:
    """Apply value_map normalization to all text-type FilterClause values.

    Non-text fields (date, numeric, boolean) are passed through unchanged —
    normalization only makes sense for human-readable text values.

    Args:
        filters: List of FilterClause objects to normalize.
        value_map: Nested dict from load_value_map().

    Returns:
        New list of FilterClause objects with normalized text values.
        Non-text fields are returned as-is (new FilterClause objects with same values).
    """
    if not value_map:
        return list(filters)

    result: list[FilterClause] = []

    for fc in filters:
        field_config = FIELD_REGISTRY.get(fc.field)

        # Only normalize text fields — numeric/date/boolean pass through
        if field_config is None or field_config.sql_type != "text":
            result.append(fc)
            continue

        normalized_values = [normalize_value(v, fc.field, value_map) for v in fc.values]

        if normalized_values != fc.values:
            logger.debug(
                "semantic_resolver: normalized field='%s' values %s → %s",
                fc.field,
                fc.values,
                normalized_values,
            )

        result.append(
            FilterClause(
                field=fc.field,
                op=fc.op,
                values=normalized_values,
            )
        )

    return result
