from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Plugin(Base):
    __tablename__ = "plugins"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    plugin_type: Mapped[str] = mapped_column(String(50), nullable=False, default="workflow")
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    actions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    allowed_roles: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False, default="none")
    auth_ref: Mapped[str | None] = mapped_column(String(200))
    auth_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")

    workflows: Mapped[list["Workflow"]] = relationship(back_populates="plugin")


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    plugin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plugins.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_by: Mapped[str] = mapped_column(String(200), default="system")
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")

    plugin: Mapped[Plugin] = relationship(back_populates="workflows")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="submitted")
    job_id: Mapped[str | None] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    environment: Mapped[str] = mapped_column(String(50), nullable=False, default="dev")
    gitops: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    requested_by: Mapped[str] = mapped_column(String(200), default="unknown")
    requested_by_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(String(50), nullable=False, default="dev")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned")
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    requested_by: Mapped[str] = mapped_column(String(200), default="unknown")
    requested_by_name: Mapped[str | None] = mapped_column(String(200))
    correlation_id: Mapped[str] = mapped_column(String(200), default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentEvaluation(Base):
    __tablename__ = "agent_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    verdict: Mapped[str] = mapped_column(String(50), nullable=False)
    reasons: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(200), default="unknown")
    actor_id: Mapped[str] = mapped_column(String(200), default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PluginInvocation(Base):
    __tablename__ = "plugin_invocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    plugin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plugins.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="submitted")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    webhook_status: Mapped[str | None] = mapped_column(String(50))
    webhook_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str] = mapped_column(String(200), default="unknown")
    actor_id: Mapped[str] = mapped_column(String(200), default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_runs.id"),
        nullable=True,
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflows.id"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id"))
    target_type: Mapped[str] = mapped_column(String(50), nullable=False, default="workflow")
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    requested_by_name: Mapped[str | None] = mapped_column(String(200))
    required_role: Mapped[str] = mapped_column(String(100), nullable=False, default="approver")
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False, default="medium")
    rationale: Mapped[str | None] = mapped_column(Text)
    plan_summary: Mapped[str | None] = mapped_column(Text)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    decision_comment: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_by_name: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str] = mapped_column(String(200), default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New chat")
    actor_id: Mapped[str] = mapped_column(String(200), default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tool_results: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_type: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    api_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_ref: Mapped[str | None] = mapped_column(String(200))
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="api")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(200), default="unknown")
    actor_id: Mapped[str] = mapped_column(String(200), default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class EventIngest(Base):
    __tablename__ = "event_ingests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    environment: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="received")
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(200), default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), default="default")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RuntimeRun(Base):
    __tablename__ = "runtime_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="accepted")
    environment: Mapped[str] = mapped_column(String(50), nullable=False, default="dev")
    requester_actor_id: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    requester_actor_name: Mapped[str | None] = mapped_column(String(200))
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
    )
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RuntimeStep(Base):
    __tablename__ = "runtime_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime_runs.id"), nullable=False)
    step_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    assigned_agent: Mapped[str] = mapped_column(String(200), nullable=False)
    gate_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    approval_status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_required")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RuntimeEvent(Base):
    __tablename__ = "runtime_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime_runs.id"), nullable=False)
    step_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runtime_steps.id"))
    event_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, default="default")
    visibility_level: Mapped[str] = mapped_column(String(50), nullable=False, default="tenant")
    redaction: Mapped[str] = mapped_column(String(50), nullable=False, default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RuntimeApproval(Base):
    __tablename__ = "runtime_approvals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime_runs.id"), nullable=False)
    step_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runtime_steps.id"))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    required_role: Mapped[str] = mapped_column(String(100), nullable=False, default="approver")
    rationale: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RuntimeToolInvocation(Base):
    __tablename__ = "runtime_tool_invocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime_runs.id"), nullable=False)
    step_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runtime_steps.id"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="started")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    normalized_outcome: Mapped[str | None] = mapped_column(String(100))
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False, default="unknown")
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
