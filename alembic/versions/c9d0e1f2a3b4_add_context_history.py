"""add_context_history

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-10 02:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str = "b8c9d0e1f2a3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # sa.Enum with a named type creates the PostgreSQL ENUM automatically as part of
    # CREATE TABLE — no separate op.execute("CREATE TYPE ...") needed here.
    op.create_table(
        "context_history",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.Text, nullable=False),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("value", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("written_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "operation",
            sa.Enum("created", "updated", "deleted", "rollback",
                    name="context_operation_enum"),
            nullable=False,
        ),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "namespace", "key", "version",
            name="uq_context_history_version",
        ),
    )
    op.create_index(
        "ix_context_history_tenant_ns_key",
        "context_history",
        ["tenant_id", "namespace", "key"],
    )


def downgrade() -> None:
    op.drop_index("ix_context_history_tenant_ns_key", table_name="context_history")
    op.drop_table("context_history")
    op.execute("DROP TYPE context_operation_enum")
