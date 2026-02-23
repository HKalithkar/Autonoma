from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plugins",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("endpoint", sa.String(length=500), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.Column("allowed_roles", sa.JSON(), nullable=False),
        sa.Column("auth_ref", sa.String(length=200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
    )
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("plugin_id", sa.Uuid, nullable=False),
        sa.Column("action", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("workflow_id", sa.Uuid, nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("job_id", sa.String(length=200)),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"]),
    )
    op.create_table(
        "plugin_invocations",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("plugin_id", sa.Uuid, nullable=False),
        sa.Column("action", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugins.id"]),
    )
    op.create_index("ix_plugin_invocations_plugin_id", "plugin_invocations", ["plugin_id"])
    op.create_index(
        "ix_workflow_runs_status_created_at",
        "workflow_runs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_status_created_at", table_name="workflow_runs")
    op.drop_index("ix_plugin_invocations_plugin_id", table_name="plugin_invocations")
    op.drop_table("plugin_invocations")
    op.drop_table("workflow_runs")
    op.drop_table("workflows")
    op.drop_table("plugins")
