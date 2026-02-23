from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.models import AuditEvent, EventIngest, RuntimeEvent, RuntimeToolInvocation
from apps.runtime_orchestrator.app.main import app


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_orchestrator.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def _allow_policy_response(url: str, *args: Any, **kwargs: Any):
    del url, args, kwargs

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "allow": True,
                "outcome": "allow",
                "reasons": [],
                "required_approvals": [],
                "decision_artifact_id": "artifact:test:allow",
            }

    return _Resp()


def _deny_policy_response(url: str, *args: Any, **kwargs: Any):
    del url, args, kwargs

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "allow": False,
                "outcome": "deny",
                "reasons": ["risk_score_too_high_for_auto_execution"],
                "required_approvals": [],
                "decision_artifact_id": "artifact:test:deny",
            }

    return _Resp()


def test_orchestrator_run_create_allow_path_records_gate_decision(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    os.environ["RUNTIME_POLICY_FAILURE_MODE"] = "pause"
    monkeypatch.setattr("apps.runtime_orchestrator.app.main.httpx.post", _allow_policy_response)
    client = TestClient(app)

    create = client.post(
        "/v1/orchestrator/runs",
        headers={"x-service-token": "svc-token"},
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "metadata": {"source": "test"},
            "context": {
                "correlation_id": "corr-1",
                "actor_id": "user-1",
                "tenant_id": "tenant-a",
                "actor_name": "User One",
            },
        },
    )
    assert create.status_code == 200
    run_id = create.json()["run_id"]
    assert create.json()["status"] == "running"

    run_resp = client.get(
        f"/v1/orchestrator/runs/{run_id}",
        headers={"x-service-token": "svc-token"},
        params={"tenant_id": "tenant-a"},
    )
    assert run_resp.status_code == 200
    run_payload = run_resp.json()
    assert run_payload["status"] == "running"
    execution_step = next(
        step for step in run_payload["steps"] if step["step_key"] == "reasoning_plan"
    )
    assert execution_step["gate_status"] == "allowed"
    assert execution_step["status"] == "executing"

    timeline = client.get(
        f"/v1/orchestrator/runs/{run_id}/timeline",
        headers={"x-service-token": "svc-token"},
        params={"tenant_id": "tenant-a"},
    )
    assert timeline.status_code == 200
    event_types = [event["event_type"] for event in timeline.json()["events"]]
    assert "run.started" in event_types
    assert "plan.step.proposed" in event_types
    assert "policy.decision.recorded" in event_types

    with session_scope() as session:
        policy_audits = (
            session.query(AuditEvent)
            .filter(AuditEvent.event_type == "policy", AuditEvent.tenant_id == "tenant-a")
            .all()
        )
        assert len(policy_audits) == 1
        assert policy_audits[0].outcome == "allow"
        mirrored_events = (
            session.query(EventIngest)
            .filter(
                EventIngest.source == "runtime-orchestrator",
                EventIngest.tenant_id == "tenant-a",
            )
            .all()
        )
        mirrored_types = {item.event_type for item in mirrored_events}
        assert "run.started" in mirrored_types
        assert "plan.step.proposed" in mirrored_types
        assert "policy.decision.recorded" in mirrored_types


def test_orchestrator_run_create_deny_path_blocks_step(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    monkeypatch.setattr("apps.runtime_orchestrator.app.main.httpx.post", _deny_policy_response)
    client = TestClient(app)

    create = client.post(
        "/v1/orchestrator/runs",
        headers={"x-service-token": "svc-token"},
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "metadata": {"risk_score": 0.8},
            "context": {
                "correlation_id": "corr-2",
                "actor_id": "user-2",
                "tenant_id": "tenant-a",
                "actor_name": "User Two",
            },
        },
    )
    assert create.status_code == 200
    assert create.json()["status"] == "failed"

    run_id = create.json()["run_id"]
    run_resp = client.get(
        f"/v1/orchestrator/runs/{run_id}",
        headers={"x-service-token": "svc-token"},
        params={"tenant_id": "tenant-a"},
    )
    assert run_resp.status_code == 200
    run_payload = run_resp.json()
    assert run_payload["status"] == "failed"
    execution_step = next(
        step for step in run_payload["steps"] if step["step_key"] == "reasoning_plan"
    )
    assert execution_step["gate_status"] == "denied"
    assert execution_step["status"] == "blocked"


def test_orchestrator_policy_outage_defaults_to_pause(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    os.environ["RUNTIME_POLICY_FAILURE_MODE"] = "pause"

    def _raise_http_error(url: str, *args: Any, **kwargs: Any):
        del args, kwargs
        raise httpx.ConnectError("network down", request=httpx.Request("POST", url))

    monkeypatch.setattr("apps.runtime_orchestrator.app.main.httpx.post", _raise_http_error)
    client = TestClient(app)

    create = client.post(
        "/v1/orchestrator/runs",
        headers={"x-service-token": "svc-token"},
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "metadata": {"source": "test"},
            "context": {
                "correlation_id": "corr-3",
                "actor_id": "user-3",
                "tenant_id": "tenant-a",
            },
        },
    )
    assert create.status_code == 200
    assert create.json()["status"] == "paused"


def test_orchestrator_policy_outage_can_deny_by_config(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    os.environ["RUNTIME_POLICY_FAILURE_MODE"] = "deny"

    def _raise_http_error(url: str, *args: Any, **kwargs: Any):
        del args, kwargs
        raise httpx.ConnectError("network down", request=httpx.Request("POST", url))

    monkeypatch.setattr("apps.runtime_orchestrator.app.main.httpx.post", _raise_http_error)
    client = TestClient(app)

    create = client.post(
        "/v1/orchestrator/runs",
        headers={"x-service-token": "svc-token"},
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "metadata": {"source": "test"},
            "context": {
                "correlation_id": "corr-4",
                "actor_id": "user-4",
                "tenant_id": "tenant-a",
            },
        },
    )
    assert create.status_code == 200
    assert create.json()["status"] == "failed"


def test_orchestrator_execution_broker_success(monkeypatch, tmp_path: Path) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"

    def _fake_post(url: str, *args: Any, **kwargs: Any):
        del args, kwargs

        class _Resp:
            status_code = 200
            headers = {"content-type": "application/json"}

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                if "step-evaluate" in url:
                    return {
                        "allow": True,
                        "outcome": "allow",
                        "reasons": [],
                        "required_approvals": [],
                        "decision_artifact_id": "artifact:test:allow",
                    }
                return {"status": "submitted", "job_id": "job-123"}

        return _Resp()

    monkeypatch.setattr("apps.runtime_orchestrator.app.main.httpx.post", _fake_post)
    client = TestClient(app)

    create = client.post(
        "/v1/orchestrator/runs",
        headers={"x-service-token": "svc-token"},
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "metadata": {
                "execution": {
                    "plugin": "airflow",
                    "action": "workflow.trigger",
                    "params": {"workflow_id": "wf-1"},
                }
            },
            "context": {
                "correlation_id": "corr-e1",
                "actor_id": "user-e1",
                "tenant_id": "tenant-a",
            },
        },
    )
    assert create.status_code == 200
    assert create.json()["status"] == "running"

    run_id = create.json()["run_id"]
    timeline = client.get(
        f"/v1/orchestrator/runs/{run_id}/timeline",
        headers={"x-service-token": "svc-token"},
        params={"tenant_id": "tenant-a"},
    )
    assert timeline.status_code == 200
    event_types = [event["event_type"] for event in timeline.json()["events"]]
    assert "tool.call.started" in event_types
    assert "tool.call.completed" in event_types
    assert "run.succeeded" not in event_types

    with session_scope() as session:
        invocations = session.query(RuntimeToolInvocation).all()
        assert len(invocations) == 1
        assert invocations[0].normalized_outcome == "success"
        assert invocations[0].status == "completed"


def test_orchestrator_execution_broker_retries_transient_then_succeeds(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    os.environ["RUNTIME_TOOL_MAX_RETRIES"] = "2"
    plugin_attempt = {"count": 0}

    def _fake_post(url: str, *args: Any, **kwargs: Any):
        del args, kwargs

        class _Resp:
            headers = {"content-type": "application/json"}

            def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
                self.status_code = status_code
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return self._payload

            @property
            def text(self) -> str:
                return str(self._payload)

        if "step-evaluate" in url:
            return _Resp(
                200,
                {
                    "allow": True,
                    "outcome": "allow",
                    "reasons": [],
                    "required_approvals": [],
                    "decision_artifact_id": "artifact:test:allow",
                },
            )
        plugin_attempt["count"] += 1
        if plugin_attempt["count"] == 1:
            return _Resp(503, {"detail": "temporarily unavailable"})
        return _Resp(200, {"status": "submitted", "job_id": "job-456"})

    monkeypatch.setattr("apps.runtime_orchestrator.app.main.httpx.post", _fake_post)
    client = TestClient(app)

    create = client.post(
        "/v1/orchestrator/runs",
        headers={"x-service-token": "svc-token"},
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "metadata": {
                "execution": {
                    "plugin": "airflow",
                    "action": "workflow.trigger",
                    "params": {"workflow_id": "wf-2"},
                }
            },
            "context": {
                "correlation_id": "corr-e2",
                "actor_id": "user-e2",
                "tenant_id": "tenant-a",
            },
        },
    )
    assert create.status_code == 200
    assert create.json()["status"] == "running"

    run_id = create.json()["run_id"]
    timeline = client.get(
        f"/v1/orchestrator/runs/{run_id}/timeline",
        headers={"x-service-token": "svc-token"},
        params={"tenant_id": "tenant-a"},
    )
    event_types = [event["event_type"] for event in timeline.json()["events"]]
    assert "tool.call.retrying" in event_types
    with session_scope() as session:
        invocations = (
            session.query(RuntimeToolInvocation)
            .order_by(RuntimeToolInvocation.created_at.asc())
            .all()
        )
        assert len(invocations) == 2
        assert invocations[0].normalized_outcome == "transient"
        assert invocations[1].normalized_outcome == "success"


def test_orchestrator_execution_broker_policy_denied_is_terminal(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    os.environ["RUNTIME_TOOL_MAX_RETRIES"] = "2"

    def _fake_post(url: str, *args: Any, **kwargs: Any):
        del args, kwargs

        class _Resp:
            headers = {"content-type": "application/json"}

            def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
                self.status_code = status_code
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return self._payload

            @property
            def text(self) -> str:
                return str(self._payload)

        if "step-evaluate" in url:
            return _Resp(
                200,
                {
                    "allow": True,
                    "outcome": "allow",
                    "reasons": [],
                    "required_approvals": [],
                    "decision_artifact_id": "artifact:test:allow",
                },
            )
        return _Resp(403, {"deny_reasons": ["blocked"], "required_approvals": []})

    monkeypatch.setattr("apps.runtime_orchestrator.app.main.httpx.post", _fake_post)
    client = TestClient(app)

    create = client.post(
        "/v1/orchestrator/runs",
        headers={"x-service-token": "svc-token"},
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "metadata": {
                "execution": {
                    "plugin": "airflow",
                    "action": "workflow.trigger",
                    "params": {"workflow_id": "wf-3"},
                }
            },
            "context": {
                "correlation_id": "corr-e3",
                "actor_id": "user-e3",
                "tenant_id": "tenant-a",
            },
        },
    )
    assert create.status_code == 200
    assert create.json()["status"] == "failed"

    run_id = create.json()["run_id"]
    timeline = client.get(
        f"/v1/orchestrator/runs/{run_id}/timeline",
        headers={"x-service-token": "svc-token"},
        params={"tenant_id": "tenant-a"},
    )
    event_types = [event["event_type"] for event in timeline.json()["events"]]
    assert "tool.call.failed" in event_types
    assert "tool.call.retrying" not in event_types


def test_orchestrator_timeline_normalizes_malformed_event_envelope(
    monkeypatch, tmp_path: Path
) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    monkeypatch.setattr("apps.runtime_orchestrator.app.main.httpx.post", _allow_policy_response)
    client = TestClient(app)

    create = client.post(
        "/v1/orchestrator/runs",
        headers={"x-service-token": "svc-token"},
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "metadata": {"source": "test"},
            "context": {
                "correlation_id": "corr-malformed",
                "actor_id": "user-malformed",
                "tenant_id": "tenant-a",
            },
        },
    )
    assert create.status_code == 200
    run_id = create.json()["run_id"]
    run_uuid = uuid.UUID(run_id)

    with session_scope() as session:
        event = session.query(RuntimeEvent).filter(RuntimeEvent.run_id == run_uuid).first()
        assert event is not None
        event.envelope = {"event_type": event.event_type}
        session.flush()

    timeline = client.get(
        f"/v1/orchestrator/runs/{run_id}/timeline",
        headers={"x-service-token": "svc-token"},
        params={"tenant_id": "tenant-a"},
    )
    assert timeline.status_code == 200
    first = timeline.json()["events"][0]
    assert first["event_id"]
    assert first["timestamp"]
    assert first["agent_id"] == "unknown"
    assert first["payload"] == {}


def test_orchestrator_requires_service_token(tmp_path: Path) -> None:
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    client = TestClient(app)

    response = client.post(
        "/v1/orchestrator/runs",
        json={
            "intent": "Trigger deploy",
            "environment": "dev",
            "context": {
                "correlation_id": "corr-1",
                "actor_id": "user-1",
                "tenant_id": "tenant-a",
            },
        },
    )
    assert response.status_code == 401
