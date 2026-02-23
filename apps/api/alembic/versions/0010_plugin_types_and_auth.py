"""Add plugin type and auth metadata.

Revision ID: 0010_plugin_types_and_auth
Revises: 0009_event_ingest
Create Date: 2026-01-10 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_plugin_types_and_auth"
down_revision = "0009_event_ingest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plugins") as batch_op:
        batch_op.add_column(
            sa.Column(
                "plugin_type",
                sa.String(length=50),
                nullable=False,
                server_default="workflow",
            )
        )
        batch_op.add_column(
            sa.Column(
                "auth_type",
                sa.String(length=50),
                nullable=False,
                server_default="none",
            )
        )
        batch_op.add_column(
            sa.Column(
                "auth_config",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'::json"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("plugins") as batch_op:
        batch_op.drop_column("auth_config")
        batch_op.drop_column("auth_type")
        batch_op.drop_column("plugin_type")
