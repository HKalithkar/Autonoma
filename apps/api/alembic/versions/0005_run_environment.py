"""Add environment to workflow runs.

Revision ID: 0005_run_environment
Revises: 0004_audit_source
Create Date: 2026-01-09 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_run_environment"
down_revision = "0004_audit_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_runs") as batch_op:
        batch_op.add_column(
            sa.Column("environment", sa.String(length=50), nullable=False, server_default="dev")
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_runs") as batch_op:
        batch_op.drop_column("environment")
