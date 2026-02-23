"""Add requested_by_name/decided_by_name fields.

Revision ID: 0013_actor_display_names
Revises: 0012_workflow_input_schema
Create Date: 2026-02-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_actor_display_names"
down_revision = "0012_workflow_input_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("requested_by_name", sa.String(length=200)))
    op.add_column("agent_runs", sa.Column("requested_by_name", sa.String(length=200)))
    op.add_column("approvals", sa.Column("requested_by_name", sa.String(length=200)))
    op.add_column("approvals", sa.Column("decided_by_name", sa.String(length=200)))


def downgrade() -> None:
    op.drop_column("approvals", "decided_by_name")
    op.drop_column("approvals", "requested_by_name")
    op.drop_column("agent_runs", "requested_by_name")
    op.drop_column("workflow_runs", "requested_by_name")
