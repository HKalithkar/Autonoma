"""gitops metadata on workflow runs and plugin invocations

Revision ID: 0008_gitops_metadata
Revises: 0007_agent_eval
Create Date: 2026-01-10 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_gitops_metadata"
down_revision = "0007_agent_eval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs") as batch_op:
        batch_op.add_column(
            sa.Column("gitops", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
    with op.batch_alter_table("plugin_invocations") as batch_op:
        batch_op.add_column(sa.Column("webhook_status", sa.String(length=50), nullable=True))
        batch_op.add_column(
            sa.Column("webhook_received_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("plugin_invocations") as batch_op:
        batch_op.drop_column("webhook_received_at")
        batch_op.drop_column("webhook_status")
    with op.batch_alter_table("workflow_runs") as batch_op:
        batch_op.drop_column("gitops")
