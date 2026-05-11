"""Assembles the LLM prompt from selected semantic context."""

from app.semantic.glossary_resolver import (
    ResolvedDictionary,
    ResolvedGlossary,
    ResolvedKnowledge,
    ResolvedMetric,
    ResolvedSampleQuery,
)
from app.semantic.relationship_inference import InferredRelationship
from app.semantic.schema_linker import LinkedTable


# Audit columns that appear on almost every table but are rarely used in queries.
# Excluding them reduces noise without losing business-relevant context.
_AUDIT_COLUMNS = {"CreateBy", "CreateDate", "UpdateBy", "UpdateDate"}

# Tables with more than this many columns switch to compact single-line format.
_COMPACT_THRESHOLD = 15


def assemble_prompt(
    tables: list[LinkedTable],
    glossary: list[ResolvedGlossary],
    metrics: list[ResolvedMetric],
    knowledge: list[ResolvedKnowledge],
    dictionaries: list[ResolvedDictionary],
    sample_queries: list[ResolvedSampleQuery],
    relationships: list[dict],
    inferred_relationships: list[InferredRelationship] | None = None,
    dialect: str = "postgresql",
) -> str:
    """Format all selected context into a structured prompt section for the LLM."""
    sections: list[str] = []

    # Schema section
    if tables:
        schema_lines = ["=== DATABASE SCHEMA ==="]
        for lt in tables:
            table = lt.table
            # Filter out audit columns (pure metadata, never queried)
            relevant_cols = [c for c in lt.columns if c.column_name not in _AUDIT_COLUMNS]

            schema_lines.append(f"\nTable: {table.schema_name}.{table.table_name}")
            if table.comment:
                schema_lines.append(f"  Description: {table.comment}")
            if table.row_count_estimate:
                schema_lines.append(f"  Approximate rows: {table.row_count_estimate:,}")

            if len(relevant_cols) > _COMPACT_THRESHOLD:
                # Compact format: single line per table for very wide tables
                col_parts = []
                for col in relevant_cols:
                    suffix = ""
                    if col.is_primary_key:
                        suffix = " PK"
                    elif not col.is_nullable:
                        suffix = " NOT NULL"
                    col_parts.append(f"{col.column_name}({col.data_type}{suffix})")
                schema_lines.append("  Columns: " + ", ".join(col_parts))
            else:
                for col in relevant_cols:
                    parts = [f"  - {col.column_name} ({col.data_type}"]
                    if col.is_primary_key:
                        parts.append(", PK")
                    if not col.is_nullable:
                        parts.append(", NOT NULL")
                    parts.append(")")
                    if col.comment:
                        parts.append(f" -- {col.comment}")
                    schema_lines.append("".join(parts))

        sections.append("\n".join(schema_lines))

    # Declared FK relationships section — deduplicate and skip ones that are
    # already covered by inferred relationships (avoids redundant join guidance).
    if relationships:
        # Build set of inferred relationship signatures for deduplication
        inferred_sigs: set[str] = set()
        if inferred_relationships:
            for ir in inferred_relationships:
                inferred_sigs.add(
                    f"{ir.source_table}.{ir.source_column}->{ir.target_table}.{ir.target_column}"
                )

        unique_rels: list[dict] = []
        seen_sigs: set[str] = set()
        for rel in relationships:
            sig = f"{rel['source_table']}.{rel['source_column']}->{rel['target_table']}.{rel['target_column']}"
            # Skip if exact relationship already listed in inferred section
            if sig in inferred_sigs or sig in seen_sigs:
                continue
            seen_sigs.add(sig)
            unique_rels.append(rel)

        if unique_rels:
            rel_lines = ["\n=== RELATIONSHIPS (declared foreign keys) ==="]
            for rel in unique_rels:
                rel_lines.append(
                    f"  {rel['source_table']}.{rel['source_column']} -> "
                    f"{rel['target_table']}.{rel['target_column']}"
                )
            sections.append("\n".join(rel_lines))

    # Inferred relationships section — curated join rules for schemas with sparse FKs
    if inferred_relationships:
        infer_lines = [
            "\n=== INFERRED RELATIONSHIPS"
            " (use these joins — not declared as FK but confirmed correct) ==="
        ]
        infer_lines.append(
            "These join paths are confirmed business rules. "
            "Always prefer these over guessing an alternative join."
        )
        for rel in inferred_relationships:
            line = (
                f"  {rel.source_table}.{rel.source_column} -> "
                f"{rel.target_table}.{rel.target_column}"
            )
            if rel.filter_hint:
                line += f"  [filter: {rel.filter_hint}]"
            infer_lines.append(line)
            if rel.note:
                infer_lines.append(f"    NOTE: {rel.note}")
        sections.append("\n".join(infer_lines))

    # Business glossary section
    if glossary:
        glossary_lines = ["\n=== BUSINESS GLOSSARY ==="]
        glossary_lines.append("Use these definitions when the user refers to these terms:")
        for g in glossary:
            glossary_lines.append(f'  - "{g.term}": {g.definition}')
            glossary_lines.append(f"    SQL: {g.sql_expression}")
            if g.related_tables:
                glossary_lines.append(f"    Tables: {', '.join(g.related_tables)}")
        sections.append("\n".join(glossary_lines))

    # Metrics section
    if metrics:
        metric_lines = ["\n=== METRIC DEFINITIONS ==="]
        for m in metrics:
            metric_lines.append(f'  - "{m.display_name}" ({m.metric_name})')
            metric_lines.append(f"    SQL: {m.sql_expression}")
            if m.dimensions:
                metric_lines.append(f"    Suggested dimensions: {', '.join(m.dimensions)}")
        sections.append("\n".join(metric_lines))

    # Business knowledge section
    if knowledge:
        knowledge_lines = ["\n=== BUSINESS KNOWLEDGE ==="]
        knowledge_lines.append("Relevant documentation excerpts:")
        for k in knowledge:
            source = k.title
            if k.source_url:
                source += f" ({k.source_url})"
            knowledge_lines.append(f'  [Source: "{source}"]')
            text = k.content[:1500] + "..." if len(k.content) > 1500 else k.content
            knowledge_lines.append(f"  {text}")
            knowledge_lines.append("")
        sections.append("\n".join(knowledge_lines))

    # Data dictionary section — consolidate duplicate column names into one entry
    if dictionaries:
        dict_lines = ["\n=== DATA DICTIONARY ==="]
        dict_lines.append("Column value mappings (use these to interpret or filter values):")

        # Merge entries with identical column names (e.g. IsActive on multiple tables)
        merged: dict[str, tuple[dict, list[str]]] = {}  # col_name -> (mappings, tables)
        for d in dictionaries:
            key = d.column_name
            if key in merged:
                existing_mappings, existing_tables = merged[key]
                # If mappings are identical, just add the table name
                if existing_mappings == d.mappings:
                    existing_tables.append(d.table_name)
                else:
                    # Different mappings for same column name — disambiguate with table prefix
                    dict_lines.append(
                        f"  - {d.table_name}.{d.column_name}: "
                        + ", ".join(f"{k}={v}" for k, v in d.mappings.items())
                    )
            else:
                merged[key] = (d.mappings, [d.table_name])

        for col_name, (mappings, tables_list) in merged.items():
            mappings_str = ", ".join(f"{k}={v}" for k, v in mappings.items())
            if len(tables_list) > 1:
                dict_lines.append(f"  - {col_name} (on {', '.join(tables_list)}): {mappings_str}")
            else:
                dict_lines.append(f"  - {col_name}: {mappings_str}")
        sections.append("\n".join(dict_lines))

    # Sample queries section (few-shot examples)
    if sample_queries:
        sample_lines = ["\n=== EXAMPLE QUERIES ==="]
        sample_lines.append("Here are some validated query examples for reference:")
        for sq in sample_queries:
            sample_lines.append(f"  Q: {sq.natural_language}")
            sample_lines.append(f"  SQL: {sq.sql_query}")
            sample_lines.append("")
        sections.append("\n".join(sample_lines))

    # Constraints section
    constraint_lines = ["\n=== CONSTRAINTS ==="]
    constraint_lines.append(f"- SQL dialect: {dialect}")
    constraint_lines.append("- Read-only: generate only SELECT statements")
    constraint_lines.append("- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE")
    constraint_lines.append("- Use explicit column names, not SELECT *")
    constraint_lines.append(
        "- COLUMN NAMES: copy every column name verbatim from the DATABASE SCHEMA above. "
        "Never shorten, guess, or invent column names. "
        "E.g. write BusinessUnitName not Name, ClientName not Name, ResourceName not Name."
    )

    if dialect == "sqlserver":
        constraint_lines.append(
            "- Use SELECT TOP N to limit rows, NOT LIMIT (T-SQL has no LIMIT clause)"
        )
        constraint_lines.append(
            "- Quote identifiers with [square brackets], e.g. [column_name], [table_name]"
        )
        constraint_lines.append("- Use GETDATE() for current timestamp, not NOW()")
        constraint_lines.append("- Use LEN() for string length, not LENGTH()")
        constraint_lines.append("- Use ISNULL(expr, default) or COALESCE() for null handling")
        constraint_lines.append("- Use + for string concatenation, not ||")
        constraint_lines.append("- Do NOT use RETURNING clause (PostgreSQL-only)")
        constraint_lines.append(
            "- Do NOT use EXTRACT() — use YEAR(), MONTH(), DAY() functions instead"
        )
        constraint_lines.append(
            "- Default row limit: SELECT TOP 1000 unless user specifies otherwise"
        )
        if inferred_relationships:
            constraint_lines.append(
                "- JOIN RULES: Always use the join paths listed in INFERRED RELATIONSHIPS above. "
                "Never invent an alternative join path when one is provided."
            )
    else:
        constraint_lines.append("- Limit results to 1000 rows unless user specifies otherwise")

    sections.append("\n".join(constraint_lines))

    return "\n".join(sections)
