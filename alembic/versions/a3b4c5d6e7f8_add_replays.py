"""add replays

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replays",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "completed", "failed", name="replay_status_enum"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("from_timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("to_timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("speed", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("action_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_replays_tenant_id", "replays", ["tenant_id"])
    op.create_index("ix_replays_agent_id", "replays", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_replays_agent_id", table_name="replays")
    op.drop_index("ix_replays_tenant_id", table_name="replays")
    op.drop_table("replays")
    op.execute("DROP TYPE replay_status_enum")
