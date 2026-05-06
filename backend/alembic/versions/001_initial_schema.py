"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # database_connections
    op.create_table(
        "database_connections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("connector_type", sa.String(50), nullable=False),
        sa.Column("connection_string_encrypted", sa.Text, nullable=False),
        sa.Column("default_schema", sa.String(255), server_default="public"),
        sa.Column("read_only", sa.Boolean, server_default=sa.text("true")),
        sa.Column("max_query_timeout_seconds", sa.Integer, server_default=sa.text("30")),
        sa.Column("max_rows", sa.Integer, server_default=sa.text("1000")),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("last_introspected_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # cached_tables
    op.create_table(
        "cached_tables",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("database_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schema_name", sa.String(255), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("table_type", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("row_count_estimate", sa.Integer),
        sa.Column("description_embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # cached_columns
    op.create_table(
        "cached_columns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "table_id",
            UUID(as_uuid=True),
            sa.ForeignKey("cached_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("column_name", sa.String(255), nullable=False),
        sa.Column("data_type", sa.String(100), nullable=False),
        sa.Column("is_nullable", sa.Boolean, server_default=sa.text("true")),
        sa.Column("is_primary_key", sa.Boolean, server_default=sa.text("false")),
        sa.Column("default_value", sa.Text),
        sa.Column("comment", sa.Text),
        sa.Column("ordinal_position", sa.Integer, nullable=False),
        sa.Column("description_embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # cached_relationships
    op.create_table(
        "cached_relationships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("database_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("constraint_name", sa.String(255)),
        sa.Column(
            "source_table_id",
            UUID(as_uuid=True),
            sa.ForeignKey("cached_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_column", sa.String(255), nullable=False),
        sa.Column(
            "target_table_id",
            UUID(as_uuid=True),
            sa.ForeignKey("cached_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_column", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # glossary_terms
    op.create_table(
        "glossary_terms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("database_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("term", sa.String(255), nullable=False),
        sa.Column("definition", sa.Text, nullable=False),
        sa.Column("sql_expression", sa.Text, nullable=False),
        sa.Column("related_tables", ARRAY(sa.Text)),
        sa.Column("related_columns", ARRAY(sa.Text)),
        sa.Column("examples", JSONB),
        sa.Column("term_embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # metric_definitions
    op.create_table(
        "metric_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("database_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("sql_expression", sa.Text, nullable=False),
        sa.Column("aggregation_type", sa.String(50)),
        sa.Column("related_tables", ARRAY(sa.Text)),
        sa.Column("dimensions", ARRAY(sa.Text)),
        sa.Column("filters", JSONB),
        sa.Column("metric_embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # sample_queries
    op.create_table(
        "sample_queries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("database_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("natural_language", sa.Text, nullable=False),
        sa.Column("sql_query", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("tags", ARRAY(sa.Text)),
        sa.Column("is_validated", sa.Boolean, server_default=sa.text("false")),
        sa.Column("question_embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_by", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # query_executions
    op.create_table(
        "query_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connection_id",
            UUID(as_uuid=True),
            sa.ForeignKey("database_connections.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255)),
        sa.Column("natural_language", sa.Text, nullable=False),
        sa.Column("generated_sql", sa.Text),
        sa.Column("final_sql", sa.Text),
        sa.Column("execution_status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("row_count", sa.Integer),
        sa.Column("execution_time_ms", sa.Float),
        sa.Column("llm_provider", sa.String(50)),
        sa.Column("llm_model", sa.String(100)),
        sa.Column("llm_input_tokens", sa.Integer),
        sa.Column("llm_output_tokens", sa.Integer),
        sa.Column("retry_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("result_summary", sa.Text),
        sa.Column("is_favorite", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # dictionary_entries
    op.create_table(
        "dictionary_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "column_id",
            UUID(as_uuid=True),
            sa.ForeignKey("cached_columns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_value", sa.String(255), nullable=False),
        sa.Column("display_value", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("sort_order", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("dictionary_entries")
    op.drop_table("query_executions")
    op.drop_table("sample_queries")
    op.drop_table("metric_definitions")
    op.drop_table("glossary_terms")
    op.drop_table("cached_relationships")
    op.drop_table("cached_columns")
    op.drop_table("cached_tables")
    op.drop_table("database_connections")
    op.execute("DROP EXTENSION IF EXISTS vector")
