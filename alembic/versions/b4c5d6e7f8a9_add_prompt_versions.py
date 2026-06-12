"""add prompt versions

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_prompt_versions_tenant_id", "prompt_versions", ["tenant_id"])
    op.create_index("ix_prompt_versions_agent_id", "prompt_versions", ["agent_id"])
    op.create_index(
        "ix_prompt_versions_agent_version", "prompt_versions", ["agent_id", "version"]
    )
    op.create_index(
        "ix_prompt_versions_tenant_agent", "prompt_versions", ["tenant_id", "agent_id"]
    )

    op.create_table(
        "prompt_test_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "prompt_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_prompt_test_results_version_id",
        "prompt_test_results",
        ["prompt_version_id"],
    )

    op.add_column(
        "actions",
        sa.Column(
            "prompt_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("actions", "prompt_version_id")
    op.drop_table("prompt_test_results")
    op.drop_index("ix_prompt_versions_tenant_agent", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_agent_version", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_agent_id", table_name="prompt_versions")
    op.drop_index("ix_prompt_versions_tenant_id", table_name="prompt_versions")
    op.drop_table("prompt_versions")
