"""add agent runs and configs

Revision ID: 0006_agent_runs_and_configs
Revises: 0005_run_environment
Create Date: 2026-01-10 05:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_agent_runs_and_configs"
down_revision = "0005_run_environment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("environment", sa.String(length=50), nullable=False, server_default="dev"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="planned"),
        sa.Column("plan", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("requested_by", sa.String(length=200), nullable=False, server_default="unknown"),
        sa.Column(
            "correlation_id", sa.String(length=200), nullable=False, server_default="unknown"
        ),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_agent_runs_tenant_created", "agent_runs", ["tenant_id", "created_at"])

    op.create_table(
        "agent_configs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("agent_type", sa.String(length=100), nullable=False, unique=True),
        sa.Column("api_url", sa.String(length=500), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("api_key_ref", sa.String(length=200), nullable=True),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_configs")
    op.drop_index("ix_agent_runs_tenant_created", table_name="agent_runs")
    op.drop_table("agent_runs")
