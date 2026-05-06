"""Add users table, alter query_executions.user_id to UUID FK, seed dev users

Revision ID: 006
Revises: 005
Create Date: 2026-03-30

Creates the users table for RBAC (3 global roles: admin, manager, user).
Alters query_executions.user_id from VARCHAR(255) to UUID FK → users.id.
Seeds 3 development users (admin, manager, user) directly in the migration.

Passwords (bcrypt-hashed, cost=12):
  admin@querywise.dev   → admin123
  manager@querywise.dev → manager123
  user@querywise.dev    → user123
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Pre-computed bcrypt hashes (cost=12) for dev seed users.
# Generated with: bcrypt.hashpw(b"<password>", bcrypt.gensalt(rounds=12))
# These are static so the migration is reproducible without runtime dependencies.
_ADMIN_HASH = "$2b$12$5yVgOEjS11KXVxySeXuLr.Hk8d1tk0fETbCVEsuHZ1ssUO.5MPDtS"
_MANAGER_HASH = "$2b$12$zTbXxBoYm/1TVgPOSPNasOIGAP4E.9TQUx5l84Gtkz9bHS5Zw46US"
_USER_HASH = "$2b$12$oR4bLXrETMk4kNCV33VnwuuOkKrEpalIBgQxn3qk5O0C8AQq/WlsG"

# Fixed UUIDs for dev seed users (stable across migrations/resets)
_ADMIN_ID = "00000000-0000-0000-0000-000000000001"
_MANAGER_ID = "00000000-0000-0000-0000-000000000002"
_USER_ID = "00000000-0000-0000-0000-000000000003"


def upgrade() -> None:
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("resource_id", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Seed dev users only in explicitly-named development environments.
    # Uses os.environ directly since Alembic runs outside FastAPI app context
    # and cannot access settings (which requires DB connectivity at import time).
    if os.environ.get("ENVIRONMENT", "development") == "development":
        # UUIDs are literals cast inline to avoid asyncpg
        #    inferring VARCHAR for named bind parameters on UUID columns.
        op.execute(
            sa.text(
                f"""
                INSERT INTO users (id, email, hashed_password, role, resource_id, is_active)
                VALUES
                    ('{_ADMIN_ID}'::uuid,   'admin@querywise.dev',   :admin_hash,   'admin',   NULL, true),
                    ('{_MANAGER_ID}'::uuid, 'manager@querywise.dev', :manager_hash, 'manager', NULL, true),
                    ('{_USER_ID}'::uuid,    'user@querywise.dev',    :user_hash,    'user',    39,   true)
                ON CONFLICT (email) DO NOTHING
                """
            ).bindparams(
                admin_hash=_ADMIN_HASH,
                manager_hash=_MANAGER_HASH,
                user_hash=_USER_HASH,
            )
        )

    # 3. Alter query_executions.user_id: VARCHAR(255) → UUID FK → users.id
    #    Existing rows have NULL, so USING NULL is safe.
    op.execute(
        sa.text(
            """
            ALTER TABLE query_executions
                ALTER COLUMN user_id TYPE UUID USING NULL,
                ADD CONSTRAINT fk_qe_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE SET NULL
            """
        )
    )


def downgrade() -> None:
    # Reverse FK constraint and column type change
    op.execute(
        sa.text(
            """
            ALTER TABLE query_executions
                DROP CONSTRAINT IF EXISTS fk_qe_user,
                ALTER COLUMN user_id TYPE VARCHAR(255) USING NULL
            """
        )
    )

    op.drop_index("ix_users_email", "users")
    op.drop_table("users")
