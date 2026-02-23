"""agent evaluations and approval targets

Revision ID: 0007_agent_eval
Revises: 0006_agent_runs_and_configs
Create Date: 2026-01-10 06:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_agent_eval"
down_revision = "0006_agent_runs_and_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("verdict", sa.String(length=50), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "correlation_id", sa.String(length=200), nullable=False, server_default="unknown"
        ),
        sa.Column("actor_id", sa.String(length=200), nullable=False, server_default="unknown"),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"]),
    )
    op.create_index(
        "ix_agent_evaluations_run_created",
        "agent_evaluations",
        ["agent_run_id", "created_at"],
    )

    op.add_column("approvals", sa.Column("agent_run_id", sa.Uuid(), nullable=True))
    op.add_column(
        "approvals",
        sa.Column("target_type", sa.String(length=50), nullable=False, server_default="workflow"),
    )
    op.alter_column("approvals", "workflow_run_id", nullable=True)
    op.alter_column("approvals", "workflow_id", nullable=True)
    op.create_foreign_key(
        "fk_approvals_agent_run_id",
        "approvals",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
    )
    op.execute("UPDATE approvals SET target_type = 'workflow' WHERE target_type IS NULL")


def downgrade() -> None:
    op.drop_constraint("fk_approvals_agent_run_id", "approvals", type_="foreignkey")
    op.drop_column("approvals", "target_type")
    op.drop_column("approvals", "agent_run_id")
    op.alter_column("approvals", "workflow_id", nullable=False)
    op.alter_column("approvals", "workflow_run_id", nullable=False)
    op.drop_index("ix_agent_evaluations_run_created", table_name="agent_evaluations")
    op.drop_table("agent_evaluations")
