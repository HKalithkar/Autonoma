"""Add source field to audit events.

Revision ID: 0004_audit_source
Revises: 0003_audit_events
Create Date: 2026-01-09 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_audit_source"
down_revision = "0003_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(length=100), nullable=False, server_default="api")
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_column("source")
