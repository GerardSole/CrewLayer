"""add episodic memory

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "episodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "completed", "archived", name="episode_status_enum"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_episodes_tenant_id", "episodes", ["tenant_id"])
    op.create_index("ix_episodes_agent_id", "episodes", ["agent_id"])

    op.add_column(
        "sessions",
        sa.Column(
            "episode_id",
            UUID(as_uuid=True),
            sa.ForeignKey("episodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "episode_memories",
        sa.Column("episode_id", UUID(as_uuid=True), sa.ForeignKey("episodes.id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("memory_id", UUID(as_uuid=True), sa.ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("episode_id", "memory_id", name="uq_episode_memory"),
    )


def downgrade() -> None:
    op.drop_table("episode_memories")
    op.drop_column("sessions", "episode_id")
    op.drop_table("episodes")
    op.execute("DROP TYPE episode_status_enum")
