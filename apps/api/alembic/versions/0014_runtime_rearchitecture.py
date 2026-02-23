"""Add runtime run-centric persistence tables.

Revision ID: 0014_runtime_rearchitecture
Revises: 0013_actor_display_names
Create Date: 2026-02-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_runtime_rearchitecture"
down_revision = "0013_actor_display_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="accepted"),
        sa.Column("environment", sa.String(length=50), nullable=False, server_default="dev"),
        sa.Column(
            "requester_actor_id",
            sa.String(length=200),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("requester_actor_name", sa.String(length=200), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "correlation_id",
            sa.String(length=200),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_runs_status", "runtime_runs", ["status"])
    op.create_index("ix_runtime_runs_correlation_id", "runtime_runs", ["correlation_id"])
    op.create_index("ix_runtime_runs_tenant_created", "runtime_runs", ["tenant_id", "created_at"])

    op.create_table(
        "runtime_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("assigned_agent", sa.String(length=200), nullable=False),
        sa.Column("gate_status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column(
            "approval_status",
            sa.String(length=50),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "correlation_id",
            sa.String(length=200),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runtime_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_steps_run_id", "runtime_steps", ["run_id"])
    op.create_index("ix_runtime_steps_status", "runtime_steps", ["status"])
    op.create_index("ix_runtime_steps_correlation_id", "runtime_steps", ["correlation_id"])
    op.create_index("ix_runtime_steps_tenant_created", "runtime_steps", ["tenant_id", "created_at"])

    op.create_table(
        "runtime_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False, server_default="v1"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column(
            "correlation_id",
            sa.String(length=200),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("actor_id", sa.String(length=200), nullable=False, server_default="unknown"),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column(
            "visibility_level",
            sa.String(length=50),
            nullable=False,
            server_default="tenant",
        ),
        sa.Column("redaction", sa.String(length=50), nullable=False, server_default="none"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runtime_runs.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["runtime_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_runtime_events_event_id"),
    )
    op.create_index("ix_runtime_events_run_id", "runtime_events", ["run_id"])
    op.create_index("ix_runtime_events_correlation_id", "runtime_events", ["correlation_id"])
    op.create_index(
        "ix_runtime_events_tenant_created",
        "runtime_events",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "runtime_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column(
            "required_role",
            sa.String(length=100),
            nullable=False,
            server_default="approver",
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=200), nullable=False, server_default="unknown"),
        sa.Column("decided_by", sa.String(length=200), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "correlation_id",
            sa.String(length=200),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runtime_runs.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["runtime_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_runtime_approvals_run_id", "runtime_approvals", ["run_id"])
    op.create_index("ix_runtime_approvals_status", "runtime_approvals", ["status"])
    op.create_index("ix_runtime_approvals_correlation_id", "runtime_approvals", ["correlation_id"])
    op.create_index(
        "ix_runtime_approvals_tenant_created",
        "runtime_approvals",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "runtime_tool_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="started"),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("normalized_outcome", sa.String(length=100), nullable=True),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column(
            "correlation_id",
            sa.String(length=200),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("actor_id", sa.String(length=200), nullable=False, server_default="unknown"),
        sa.Column("tenant_id", sa.String(length=200), nullable=False, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runtime_runs.id"]),
        sa.ForeignKeyConstraint(["step_id"], ["runtime_steps.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_runtime_tool_invocations_tenant_idempotency",
        ),
    )
    op.create_index("ix_runtime_tool_invocations_run_id", "runtime_tool_invocations", ["run_id"])
    op.create_index("ix_runtime_tool_invocations_status", "runtime_tool_invocations", ["status"])
    op.create_index(
        "ix_runtime_tool_invocations_correlation_id",
        "runtime_tool_invocations",
        ["correlation_id"],
    )
    op.create_index(
        "ix_runtime_tool_invocations_tenant_created",
        "runtime_tool_invocations",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_tool_invocations_tenant_created",
        table_name="runtime_tool_invocations",
    )
    op.drop_index(
        "ix_runtime_tool_invocations_correlation_id",
        table_name="runtime_tool_invocations",
    )
    op.drop_index("ix_runtime_tool_invocations_status", table_name="runtime_tool_invocations")
    op.drop_index("ix_runtime_tool_invocations_run_id", table_name="runtime_tool_invocations")
    op.drop_table("runtime_tool_invocations")

    op.drop_index("ix_runtime_approvals_tenant_created", table_name="runtime_approvals")
    op.drop_index("ix_runtime_approvals_correlation_id", table_name="runtime_approvals")
    op.drop_index("ix_runtime_approvals_status", table_name="runtime_approvals")
    op.drop_index("ix_runtime_approvals_run_id", table_name="runtime_approvals")
    op.drop_table("runtime_approvals")

    op.drop_index("ix_runtime_events_tenant_created", table_name="runtime_events")
    op.drop_index("ix_runtime_events_correlation_id", table_name="runtime_events")
    op.drop_index("ix_runtime_events_run_id", table_name="runtime_events")
    op.drop_table("runtime_events")

    op.drop_index("ix_runtime_steps_tenant_created", table_name="runtime_steps")
    op.drop_index("ix_runtime_steps_correlation_id", table_name="runtime_steps")
    op.drop_index("ix_runtime_steps_status", table_name="runtime_steps")
    op.drop_index("ix_runtime_steps_run_id", table_name="runtime_steps")
    op.drop_table("runtime_steps")

    op.drop_index("ix_runtime_runs_tenant_created", table_name="runtime_runs")
    op.drop_index("ix_runtime_runs_correlation_id", table_name="runtime_runs")
    op.drop_index("ix_runtime_runs_status", table_name="runtime_runs")
    op.drop_table("runtime_runs")
