"""add_agent_status

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-10 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE agent_status_enum AS ENUM ('idle', 'working', 'error')")
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN status          agent_status_enum NOT NULL DEFAULT 'idle',
            ADD COLUMN status_updated_at TIMESTAMPTZ       NOT NULL DEFAULT now(),
            ADD COLUMN current_session_id UUID
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE agents
            DROP COLUMN IF EXISTS current_session_id,
            DROP COLUMN IF EXISTS status_updated_at,
            DROP COLUMN IF EXISTS status
    """)
    op.execute("DROP TYPE IF EXISTS agent_status_enum")
