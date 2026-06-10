"""add agent tags

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "tags",
            ARRAY(sa.String),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index(
        "ix_agents_tags",
        "agents",
        ["tags"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_agents_tags", table_name="agents")
    op.drop_column("agents", "tags")
