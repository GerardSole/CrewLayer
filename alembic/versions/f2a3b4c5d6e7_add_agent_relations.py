"""add agent relations

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-10
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supervisor_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subordinate_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "relation_type",
            sa.Enum("supervisor", "collaborator", "delegate", name="agent_relation_type_enum"),
            nullable=False,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "supervisor_id", "subordinate_id", name="uq_agent_relation"),
    )
    op.create_index("ix_agent_relations_supervisor", "agent_relations", ["tenant_id", "supervisor_id"])
    op.create_index("ix_agent_relations_subordinate", "agent_relations", ["tenant_id", "subordinate_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_relations_subordinate", table_name="agent_relations")
    op.drop_index("ix_agent_relations_supervisor", table_name="agent_relations")
    op.drop_table("agent_relations")
    op.execute("DROP TYPE IF EXISTS agent_relation_type_enum")
