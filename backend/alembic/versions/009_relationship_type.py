"""Add relationship_type column to cached_relationships

Revision ID: 009
Revises: 008
Create Date: 2026-04-23

Adds relationship_type (explicit_fk | bridge | hierarchical | implicit_join)
to cached_relationships so manually declared relationships can express their
semantic meaning to the LLM context builder.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | Sequence[str] | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cached_relationships",
        sa.Column("relationship_type", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cached_relationships", "relationship_type")
