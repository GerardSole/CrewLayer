"""add_sessions_table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-09 20:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Use raw SQL to avoid SQLAlchemy's Enum DDL auto-creation conflicting
    # with the type that may already exist from a partial prior run.
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE session_status AS ENUM ('active', 'closed', 'archived');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id          UUID PRIMARY KEY,
            tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            agent_id    UUID NOT NULL REFERENCES agents(id)  ON DELETE CASCADE,
            status      session_status NOT NULL DEFAULT 'active',
            summary     TEXT,
            message_count INTEGER NOT NULL DEFAULT 0,
            started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            closed_at   TIMESTAMPTZ,
            metadata    JSONB NOT NULL DEFAULT '{}'
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_tenant_id ON sessions (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sessions_agent_id  ON sessions (agent_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TYPE IF EXISTS session_status")
