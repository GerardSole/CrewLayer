"""add_merged_from

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-09 22:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memories
        ADD COLUMN IF NOT EXISTS merged_from UUID[] NOT NULL DEFAULT '{}'
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS merged_from")
