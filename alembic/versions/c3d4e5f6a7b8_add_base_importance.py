"""add_base_importance

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-09 21:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add base_importance with a default so existing rows get 0.5
    op.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS base_importance FLOAT NOT NULL DEFAULT 0.5
    """)
    # Backfill: existing memories keep their current importance as the base
    op.execute("UPDATE memories SET base_importance = importance")


def downgrade() -> None:
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS base_importance")
