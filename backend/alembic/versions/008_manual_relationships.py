"""Add is_manual flag to cached_relationships

Revision ID: 008
Revises: 007
Create Date: 2026-04-22

Adds is_manual boolean column to cached_relationships so that explicitly seeded
(or user-declared) relationships survive schema re-introspection. Introspection
now only deletes rows where is_manual = FALSE.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | Sequence[str] | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cached_relationships",
        sa.Column("is_manual", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("cached_relationships", "is_manual")
