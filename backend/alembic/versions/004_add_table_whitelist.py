"""Add allowed_table_names to database_connections

Revision ID: 004
Revises: 003
Create Date: 2026-03-23

Adds allowed_table_names JSON column to database_connections.
Used by SQL Server connections to whitelist specific dbo tables
that should be included during schema introspection.
Null means no whitelist (all tables, subject to auto-exclusion rules).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "database_connections",
        sa.Column(
            "allowed_table_names",
            JSONB,
            nullable=True,
            comment="Whitelist of exact 'schema.table' names to include during introspection. "
            "Null or empty list means no whitelist filter. SQL Server only.",
        ),
    )


def downgrade() -> None:
    op.drop_column("database_connections", "allowed_table_names")
