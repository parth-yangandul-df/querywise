"""Persist turn_context on query_executions

Revision ID: 010
Revises: 009
Create Date: 2026-04-23

Adds a JSONB turn_context column to query_executions so chat sessions can
restore the exact structured prior-turn state needed for follow-up,
refinement, and topic-switch handling after reload.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | Sequence[str] | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "query_executions",
        sa.Column("turn_context", JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("query_executions", "turn_context")
