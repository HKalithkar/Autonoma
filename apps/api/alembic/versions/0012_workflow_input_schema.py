"""Add input schema to workflows.

Revision ID: 0012_workflow_input_schema
Revises: 0011_chat_history
Create Date: 2025-01-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_workflow_input_schema"
down_revision = "0011_chat_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.add_column(sa.Column("input_schema", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.drop_column("input_schema")
