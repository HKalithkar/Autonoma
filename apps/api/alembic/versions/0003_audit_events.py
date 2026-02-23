"""Add audit events table.

Revision ID: 0003_audit_events
Revises: 0002_approvals_and_run_params
Create Date: 2026-01-09 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_audit_events"
down_revision = "0002_approvals_and_run_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "correlation_id", sa.String(length=200), nullable=False, server_default="unknown"
        ),
        sa.Column("actor_id", sa.String(length=200), nullable=False, server_default="unknown"),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
