"""add evaluation tables

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-06-12 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> None:
    vals = ", ".join(f"'{v}'" for v in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({vals}); "
        f"EXCEPTION WHEN duplicate_object THEN null; END $$"
    )


def upgrade() -> None:
    _enum("rating_thumbs_enum", "up", "down")
    _enum("evaluator_enum", "human", "auto")
    _enum(
        "anomaly_type_enum",
        "response_too_long", "tool_overuse", "high_latency", "error_spike", "low_score_streak",
    )
    _enum("anomaly_severity_enum", "low", "medium", "high")
    _enum("ab_test_status_enum", "active", "completed", "stopped")
    _enum("ab_test_winner_enum", "a", "b", "inconclusive")
    _enum("ab_test_variant_enum", "a", "b")

    op.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            action_id UUID NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
            session_id UUID,
            prompt_version_id UUID REFERENCES prompt_versions(id) ON DELETE SET NULL,
            rating_thumbs rating_thumbs_enum,
            rating_score FLOAT,
            evaluator evaluator_enum NOT NULL DEFAULT 'human',
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by UUID
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_evaluations_tenant_agent ON evaluations (tenant_id, agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_evaluations_action_id ON evaluations (action_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_evaluations_tenant_id ON evaluations (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_evaluations_agent_id ON evaluations (agent_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS anomalies (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            action_id UUID NOT NULL REFERENCES actions(id) ON DELETE CASCADE,
            anomaly_type anomaly_type_enum NOT NULL,
            severity anomaly_severity_enum NOT NULL,
            details JSONB NOT NULL DEFAULT '{}',
            resolved BOOLEAN NOT NULL DEFAULT false,
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_anomalies_tenant_agent ON anomalies (tenant_id, agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_anomalies_tenant_id ON anomalies (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_anomalies_agent_id ON anomalies (agent_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ab_tests (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            status ab_test_status_enum NOT NULL DEFAULT 'active',
            variant_a_prompt_version_id UUID NOT NULL REFERENCES prompt_versions(id) ON DELETE RESTRICT,
            variant_b_prompt_version_id UUID NOT NULL REFERENCES prompt_versions(id) ON DELETE RESTRICT,
            traffic_split FLOAT NOT NULL DEFAULT 0.5,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            winner ab_test_winner_enum
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ab_tests_tenant_agent ON ab_tests (tenant_id, agent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ab_tests_tenant_id ON ab_tests (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ab_tests_agent_id ON ab_tests (agent_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ab_test_assignments (
            id UUID PRIMARY KEY,
            ab_test_id UUID NOT NULL REFERENCES ab_tests(id) ON DELETE CASCADE,
            session_id UUID NOT NULL,
            variant ab_test_variant_enum NOT NULL,
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ab_test_session UNIQUE (ab_test_id, session_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ab_test_assignments_test_id ON ab_test_assignments (ab_test_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ab_test_assignments")
    op.execute("DROP TABLE IF EXISTS ab_tests")
    op.execute("DROP TABLE IF EXISTS anomalies")
    op.execute("DROP TABLE IF EXISTS evaluations")

    op.execute("DROP TYPE IF EXISTS ab_test_variant_enum")
    op.execute("DROP TYPE IF EXISTS ab_test_winner_enum")
    op.execute("DROP TYPE IF EXISTS ab_test_status_enum")
    op.execute("DROP TYPE IF EXISTS anomaly_severity_enum")
    op.execute("DROP TYPE IF EXISTS anomaly_type_enum")
    op.execute("DROP TYPE IF EXISTS evaluator_enum")
    op.execute("DROP TYPE IF EXISTS rating_thumbs_enum")
