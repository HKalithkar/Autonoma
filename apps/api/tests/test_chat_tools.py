from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from apps.api.app.auth import AuthContext
from apps.api.app.chat_tools import ToolExecutor
from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.models import (
    Approval,
    AuditEvent,
    EventIngest,
    Plugin,
    Workflow,
    WorkflowRun,
)


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_chat_tools.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def _auth_context(permissions: list[str]) -> AuthContext:
    return AuthContext(
        actor_id="user-1",
        tenant_id="default",
        roles=["operator"],
        permissions=permissions,
        username="user-1",
    )


def test_normalize_list(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    with session_scope() as session:
        executor = ToolExecutor(session, _auth_context(["workflow:read"]))
        assert executor._normalize_list(None) == []
        assert executor._normalize_list("a, b") == ["a", "b"]
        assert executor._normalize_list(["a", " ", "b"]) == ["a", "b"]


def test_ensure_permission_denied(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    with session_scope() as session:
        executor = ToolExecutor(session, _auth_context([]))
        with pytest.raises(HTTPException) as exc:
            executor.workflow_list({})
        assert exc.value.status_code == 403


def test_workflow_run_requires_approval(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)

    recorded: dict[str, Any] = {}

    def fake_policy(*args: Any, **kwargs: Any):
        from apps.api.app.policy import PolicyDecision

        recorded["environment"] = kwargs.get("parameters", {}).get("environment")
        return PolicyDecision(
            allow=False, deny_reasons=["high_risk"], required_approvals=["approver"]
        )

    monkeypatch.setattr("apps.api.app.chat_tools.evaluate_policy", fake_policy)

    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_ref=None,
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-health",
            description="Daily job",
            plugin_id=plugin.id,
            action="trigger_dag",
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

        executor = ToolExecutor(session, _auth_context(["workflow:run"]))
        result = executor.workflow_run(
            {"workflow_id": str(workflow.id), "environment": "production"}
        )
        assert result["status"] == "pending_approval"
        assert "approval_id" in result
        assert recorded["environment"] == "prod"
        run = session.query(WorkflowRun).first()
        assert run is not None
        assert run.status == "pending_approval"
        assert run.environment == "prod"


def test_workflow_run_emits_created_audit(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)

    def fake_policy(*args: Any, **kwargs: Any):
        from apps.api.app.policy import PolicyDecision

        del args, kwargs
        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_launch(*args: Any, **kwargs: Any):
        del args, kwargs
        return {"run_id": "33333333-3333-3333-3333-333333333333", "status": "running"}

    monkeypatch.setattr("apps.api.app.chat_tools.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.chat_tools.launch_v1_run", fake_launch)

    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_ref=None,
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-health",
            description="Daily job",
            plugin_id=plugin.id,
            action="trigger_dag",
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

        executor = ToolExecutor(session, _auth_context(["workflow:run"]))
        result = executor.workflow_run({"workflow_id": str(workflow.id), "environment": "dev"})
        assert result["status"] == "running"

        audit = (
            session.query(AuditEvent)
            .filter(AuditEvent.event_type == "workflow.run.created")
            .one()
        )
        assert audit.outcome == "allow"
        assert audit.details["workflow_id"] == str(workflow.id)
        assert audit.details["workflow_run_id"] == "33333333-3333-3333-3333-333333333333"
        assert audit.details["adapter"] == "v1_runtime"
        mirrored = (
            session.query(EventIngest)
            .filter(EventIngest.event_type == "workflow.run.created")
            .one()
        )
        assert mirrored.source == "api"


def test_workflow_list_includes_input_schema(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_ref=None,
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        schema = {
            "type": "object",
            "required": ["server_name"],
            "properties": {"server_name": {"type": "string"}},
        }
        workflow = Workflow(
            name="reboot-server",
            description="Reboot server",
            plugin_id=plugin.id,
            action="trigger_dag",
            input_schema=schema,
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

        executor = ToolExecutor(session, _auth_context(["workflow:read"]))
        result = executor.workflow_list({})
        assert result[0]["input_schema"] == schema


def test_workflow_get_includes_required_fields(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_ref=None,
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        schema = {
            "type": "object",
            "required": ["server_name"],
            "properties": {
                "server_name": {"type": "string"},
                "reason": {"type": "string"},
            },
        }
        workflow = Workflow(
            name="reboot-server",
            description="Reboot server",
            plugin_id=plugin.id,
            action="trigger_dag",
            input_schema=schema,
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

        executor = ToolExecutor(session, _auth_context(["workflow:read"]))
        result = executor.workflow_get({"workflow_id": str(workflow.id)})
        assert result["required_fields"] == ["server_name"]
        assert result["optional_fields"] == ["reason"]

        by_name = executor.workflow_get({"workflow_name": "reboot-server"})
        assert by_name["id"] == str(workflow.id)
        by_fuzzy_name = executor.workflow_get({"workflow_name": "eboot-server"})
        assert by_fuzzy_name["id"] == str(workflow.id)


def test_approval_decision_updates_run(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)

    def fake_launch(*args: Any, **kwargs: Any):
        return {"run_id": "22222222-2222-2222-2222-222222222222", "status": "running"}

    monkeypatch.setattr("apps.api.app.chat_tools.launch_v1_run", fake_launch)

    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_ref=None,
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-health",
            description="Daily job",
            plugin_id=plugin.id,
            action="trigger_dag",
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()
        run = WorkflowRun(
            workflow_id=workflow.id,
            status="pending_approval",
            params={},
            environment="prod",
            requested_by="user-1",
            tenant_id="default",
        )
        session.add(run)
        session.flush()
        approval = Approval(
            workflow_run_id=run.id,
            workflow_id=workflow.id,
            target_type="workflow",
            requested_by="user-1",
            required_role="approver",
            risk_level="high",
            status="pending",
            correlation_id="corr-1",
            tenant_id="default",
        )
        session.add(approval)
        session.flush()

        executor = ToolExecutor(session, _auth_context(["approval:write"]))
        result = executor.approval_decision(
            {"approval_id": str(approval.id), "decision": "approve"}
        )
        assert result["status"] == "approved"
        assert result["run_status"] == "running"
        assert result["workflow_name"] == "daily-health"
        assert result["job_id"] is None


def test_agent_plan_handles_unavailable_runtime(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)

    def fake_launch(*args: Any, **kwargs: Any):
        raise HTTPException(status_code=502, detail="Runtime orchestrator unavailable")

    monkeypatch.setattr("apps.api.app.chat_tools.launch_v1_run", fake_launch)

    with session_scope() as session:
        executor = ToolExecutor(session, _auth_context(["agent:run"]))
        with pytest.raises(HTTPException) as exc:
            executor.agent_plan({"goal": "check status"})
        assert exc.value.status_code == 502


def test_audit_and_event_filters(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.add(
            AuditEvent(
                event_type="authn",
                outcome="allow",
                source="api",
                details={"description": "Authentication allow"},
                actor_id="user-1",
                tenant_id="default",
            )
        )
        session.add(
            EventIngest(
                event_type="alert",
                severity="high",
                summary="Test alert",
                source="monitoring",
                details={},
                environment="prod",
                status="received",
                received_at=now - timedelta(minutes=10),
                tenant_id="default",
            )
        )
        session.add(
            EventIngest(
                event_type="alert",
                severity="low",
                summary="Recent alert",
                source="monitoring",
                details={},
                environment="prod",
                status="received",
                received_at=now,
                tenant_id="default",
            )
        )
        session.flush()

        executor = ToolExecutor(session, _auth_context(["audit:read"]))
        audits = executor.audit_list({"event_type": "authn", "source": "api"})
        assert len(audits) == 1

        events = executor.events_list({"since": (now - timedelta(minutes=5)).isoformat()})
        assert len(events) == 1
        assert events[0]["summary"] == "Recent alert"
