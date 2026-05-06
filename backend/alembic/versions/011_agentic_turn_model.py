"""Add agentic multi-turn fields to query_executions

Revision ID: 011
Revises: 010
Create Date: 2026-04-30

Adds turn_type, clarification_reason, result_columns, and result_preview_rows
to query_executions to support the fully agentic multi-turn chat pipeline.
Existing rows default to turn_type='query'.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "011"
down_revision: str | Sequence[str] | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "query_executions",
        sa.Column("turn_type", sa.String(20), nullable=False, server_default="query"),
    )
    op.add_column(
        "query_executions",
        sa.Column("clarification_reason", sa.String(40), nullable=True),
    )
    op.add_column(
        "query_executions",
        sa.Column("result_columns", JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "query_executions",
        sa.Column("result_preview_rows", JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_query_executions_turn_type", "query_executions", ["turn_type"])


def downgrade() -> None:
    op.drop_index("ix_query_executions_turn_type", "query_executions")
    op.drop_column("query_executions", "result_preview_rows")
    op.drop_column("query_executions", "result_columns")
    op.drop_column("query_executions", "clarification_reason")
    op.drop_column("query_executions", "turn_type")
