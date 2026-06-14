"""add criteria_scores to evaluations

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS criteria_scores JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE evaluations DROP COLUMN IF EXISTS criteria_scores")
