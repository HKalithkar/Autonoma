"""event ingestion history

Revision ID: 0009_event_ingest
Revises: 0008_gitops_metadata
Create Date: 2026-01-10 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_event_ingest"
down_revision = "0008_gitops_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_ingests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("environment", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="received"),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("approval_id", sa.Uuid(), nullable=True),
        sa.Column("actions", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("correlation_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=200), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("event_ingests")
