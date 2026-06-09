"""add_audit_log

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-10 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            tenant_id   UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            api_key_id  UUID,
            actor_key_name VARCHAR(255) NOT NULL,
            method      VARCHAR(10)  NOT NULL,
            path        TEXT         NOT NULL,
            resource_type VARCHAR(100),
            resource_id   VARCHAR(255),
            ip_address  VARCHAR(50),
            status_code INTEGER      NOT NULL,
            timestamp   TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_tenant_id  ON audit_log (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_timestamp   ON audit_log (timestamp)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
