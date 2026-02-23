"""Add approvals and workflow run params.

Revision ID: 0002_approvals_and_run_params
Revises: 0001_init
Create Date: 2026-01-09 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_approvals_and_run_params"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs") as batch_op:
        batch_op.add_column(
            sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column(
            "required_role", sa.String(length=100), nullable=False, server_default="approver"
        ),
        sa.Column("risk_level", sa.String(length=50), nullable=False, server_default="medium"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("plan_summary", sa.Text(), nullable=True),
        sa.Column("artifacts", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "correlation_id", sa.String(length=200), nullable=False, server_default="unknown"
        ),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"]),
    )


def downgrade() -> None:
    op.drop_table("approvals")
    with op.batch_alter_table("workflow_runs") as batch_op:
        batch_op.drop_column("params")
