"""add_memory_status

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-10 01:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str = "a7b8c9d0e1f2"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE memory_status_enum AS ENUM ('active', 'archived')")
    op.add_column(
        "memories",
        sa.Column(
            "status",
            sa.Enum("active", "archived", name="memory_status_enum"),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_index("ix_memories_status", "memories", ["status"])


def downgrade() -> None:
    op.drop_index("ix_memories_status", table_name="memories")
    op.drop_column("memories", "status")
    op.execute("DROP TYPE memory_status_enum")
