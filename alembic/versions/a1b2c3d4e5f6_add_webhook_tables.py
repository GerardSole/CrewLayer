"""add_webhook_tables

Revision ID: a1b2c3d4e5f6
Revises: 7a34c12ceaec
Create Date: 2026-06-09 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '7a34c12ceaec'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'webhook_endpoints',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('events', sa.ARRAY(sa.String), nullable=False, server_default='{}'),
        sa.Column('secret', sa.String(255), nullable=False),
        sa.Column('active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
    )

    op.create_table(
        'webhook_deliveries',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('webhook_id', sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('webhook_endpoints.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('event', sa.Text, nullable=False),
        sa.Column('payload', sa.dialects.postgresql.JSONB, nullable=False, server_default='{}'),
        sa.Column('status', sa.Enum('pending', 'success', 'failed', name='delivery_status'),
                  nullable=False),
        sa.Column('attempts', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_attempt_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('response_status', sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_table('webhook_deliveries')
    op.drop_table('webhook_endpoints')
    op.execute("DROP TYPE IF EXISTS delivery_status")
