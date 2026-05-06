"""Configurable embedding dimension

Revision ID: 002
Revises: 001
Create Date: 2026-02-21

Supports switching between OpenAI (1536-dim) and Ollama (768-dim) embeddings.
Alters all vector columns to the target dimension and nulls out existing
embeddings so they regenerate with the new provider on next use.
"""

import os
from collections.abc import Sequence

from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Read target dimension from env; default stays at 1536 (OpenAI) for backwards compat
NEW_DIM = int(os.environ.get("EMBEDDING_DIMENSION", "1536"))
OLD_DIM = 1536

# All (table, column) pairs that store embeddings
EMBEDDING_COLUMNS = [
    ("cached_tables", "description_embedding"),
    ("cached_columns", "description_embedding"),
    ("glossary_terms", "term_embedding"),
    ("metric_definitions", "metric_embedding"),
    ("sample_queries", "question_embedding"),
]


def upgrade() -> None:
    for table, column in EMBEDDING_COLUMNS:
        # Null out existing embeddings — they're incompatible with the new dimension
        op.execute(f"UPDATE {table} SET {column} = NULL WHERE {column} IS NOT NULL")
        # Alter column type to the new vector dimension
        op.alter_column(
            table,
            column,
            type_=Vector(NEW_DIM),
            postgresql_using=f"{column}::vector({NEW_DIM})",
        )


def downgrade() -> None:
    for table, column in EMBEDDING_COLUMNS:
        op.execute(f"UPDATE {table} SET {column} = NULL WHERE {column} IS NOT NULL")
        op.alter_column(
            table,
            column,
            type_=Vector(OLD_DIM),
            postgresql_using=f"{column}::vector({OLD_DIM})",
        )
