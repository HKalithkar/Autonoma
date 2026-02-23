from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode

from apps.api.app import auth as auth_module
from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.main import create_app
from apps.api.app.models import (
    Approval,
    ChatMessage,
    ChatSession,
    EventIngest,
    Plugin,
    Workflow,
    WorkflowRun,
)
from apps.api.app.policy import PolicyDecision


def _configure_oidc(secret: bytes) -> None:
    jwks = {
        "keys": [
            {
                "kty": "oct",
                "k": base64url_encode(secret).decode("utf-8"),
                "kid": "test-key",
                "alg": "HS256",
            }
        ]
    }
    os.environ["OIDC_ISSUER"] = "https://issuer.example"
    os.environ["OIDC_AUTH_URL"] = "https://issuer.example/auth"
    os.environ["OIDC_TOKEN_URL"] = "https://issuer.example/token"
    os.environ["OIDC_JWKS_URL"] = "https://issuer.example/jwks"
    os.environ["OIDC_REDIRECT_URI"] = "https://api.example/v1/auth/callback"
    os.environ["OIDC_CLIENT_ID"] = "autonoma-api"
    os.environ["OIDC_AUDIENCE"] = "autonoma-api"
    os.environ["OIDC_ALLOWED_ALGS"] = "HS256"
    os.environ["OIDC_JWKS_JSON"] = json.dumps(jwks)
    auth_module.get_settings.cache_clear()
    auth_module._load_static_jwks.cache_clear()
    auth_module.fetch_jwks.cache_clear()


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_chat.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def _make_token(secret: bytes, roles: list[str] | None = None) -> str:
    return jwt.encode(
        {
            "sub": "user-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": roles or ["operator"]},
        },
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )


def test_chat_creates_session_and_executes_tool(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-health",
            plugin_id=plugin.id,
            action="trigger_dag",
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Here are workflows.",
                "tool_calls": [{"action": "workflow.list", "params": {}}],
            }

    def fake_post(*args, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "List workflows"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_results"]
    assert payload["tool_results"][0]["action"] == "workflow.list"
    assert payload["tool_results"][0]["status"] == "ok"

    with session_scope() as session:
        session_rows = session.query(ChatSession).all()
        message_rows = session.query(ChatMessage).all()
        event_rows = session.query(EventIngest).all()
        assert len(session_rows) == 1
        assert len(message_rows) >= 2
        assert event_rows
        chat_events = [event for event in event_rows if event.event_type == "chat.run"]
        assert chat_events
        assert any(
            event.details.get("session_id") == payload["session_id"] for event in chat_events
        )


def test_chat_delegates_plan_to_v1_runtime(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Planning now.",
                "tool_calls": [
                    {
                        "action": "agent.plan",
                        "params": {"goal": "Scale cache", "environment": "dev"},
                    }
                ],
            }

    class _RunResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "run_id": "run-v1-999",
                "status": "running",
                "summary": "Run accepted and dispatched to orchestrator workers.",
                "correlation_id": "corr-1",
                "actor_id": "user-1",
                "tenant_id": "default",
            }

    def _fake_post(url: str, *args, **kwargs):
        if url.endswith("/v1/chat/respond"):
            return _ChatResponse()
        if url.endswith("/v1/orchestrator/runs"):
            assert kwargs["headers"]["x-service-token"] == "svc-token"
            return _RunResponse()
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setenv("SERVICE_TOKEN", "svc-token")
    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", _fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Plan a cache scale"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_results"][0]["action"] == "agent.plan"
    assert payload["tool_results"][0]["result"]["run_id"] == "run-v1-999"
    assert payload["tool_results"][0]["result"]["plan_id"] == "v1-run-run-v1-999"


def test_chat_allows_workflow_get_without_run_intent(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    with session_scope() as session:
        plugin = Plugin(
            name="jenkins",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_job": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="jenkins-dummy-backup",
            plugin_id=plugin.id,
            action="trigger_job:dummy-backup",
            input_schema={
                "type": "object",
                "required": ["backup_bucket"],
                "properties": {"backup_bucket": {"type": "string"}},
            },
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Fetching details.",
                "tool_calls": [
                    {"action": "workflow.get", "params": {"workflow_name": "jenkins-dummy-backup"}}
                ],
            }

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "show details for jenkins-dummy-backup"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_results"][0]["action"] == "workflow.get"
    assert payload["tool_results"][0]["status"] == "ok"
    assert payload["tool_results"][0]["result"]["name"] == "jenkins-dummy-backup"


def test_chat_workflow_get_not_found_returns_user_friendly_message(
    monkeypatch, tmp_path: Path
) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Retrieving details for workflow 'enkins-dummy-backup'.",
                "tool_calls": [
                    {"action": "workflow.get", "params": {"workflow_name": "enkins-dummy-backup"}}
                ],
            }

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "show details for workflow enkins-dummy-backup"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_results"][0]["action"] == "workflow.get"
    assert payload["tool_results"][0]["status"] == "error"
    assert "does not exist" in payload["response"]


def test_chat_agent_runtime_timeout_returns_error_code(
    monkeypatch, tmp_path: Path
) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    def _fake_post(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", _fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "List workflows"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["response"].startswith("Chat unavailable")
    assert payload["error_code"] == "CHAT_AGENT_RUNTIME_TIMEOUT"


def test_chat_approvals_include_run_details(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret, roles=["approver"])

    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-health",
            plugin_id=plugin.id,
            action="trigger_dag",
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()
        run = WorkflowRun(
            workflow_id=workflow.id,
            status="submitted",
            params={},
            environment="prod",
            requested_by="operator-1",
            tenant_id="default",
        )
        session.add(run)
        session.flush()
        approval = Approval(
            workflow_run_id=run.id,
            workflow_id=workflow.id,
            target_type="workflow",
            requested_by="operator-1",
            required_role="approver",
            risk_level="high",
            status="pending",
            tenant_id="default",
        )
        session.add(approval)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Listing approvals.",
                "tool_calls": [{"action": "approvals.list", "params": {"status": "pending"}}],
            }

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Pending approvals?"},
    )
    assert response.status_code == 200
    payload = response.json()
    result = payload["tool_results"][0]["result"][0]
    assert result["workflow_name"] == "daily-health"
    assert result["environment"] == "prod"


def test_chat_runs_workflow_when_intent_and_params_present(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    with session_scope() as session:
        plugin = Plugin(
            name="jenkins",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_job": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-build",
            plugin_id=plugin.id,
            action="trigger_job",
            input_schema={
                "type": "object",
                "required": ["branch"],
                "properties": {"branch": {"type": "string"}},
            },
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"response": "Okay.", "tool_calls": []}

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    def fake_policy(*args, **kwargs):
        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_launch(*args, **kwargs):
        return {
            "run_id": "11111111-1111-1111-1111-111111111111",
            "status": "running",
            "summary": "Run accepted and dispatched to orchestrator workers.",
        }

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)
    monkeypatch.setattr("apps.api.app.chat_tools.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.chat_tools.launch_v1_run", fake_launch)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": 'run workflow daily-build with {"branch":"main"} in prod'},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_results"]
    assert payload["tool_results"][-1]["action"] == "workflow.run"
    assert payload["tool_results"][-1]["status"] == "ok"


def test_chat_requires_confirmation_on_workflow_name_mismatch(
    monkeypatch, tmp_path: Path
) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    with session_scope() as session:
        plugin = Plugin(
            name="jenkins",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_job": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-build",
            plugin_id=plugin.id,
            action="trigger_job",
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Running.",
                "tool_calls": [
                    {
                        "action": "workflow.run",
                        "params": {
                            "workflow_name": "daily-build-prod",
                            "params": {"branch": "main"},
                        },
                    }
                ],
            }

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": 'run workflow daily-build with {"branch":"main"}'},
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(item["status"] == "error" for item in payload["tool_results"])
    assert "Workflow name mismatch" in payload["response"]


def test_chat_parses_unquoted_as_params_and_runs(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    with session_scope() as session:
        plugin = Plugin(
            name="jenkins",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_job": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="jenkins-dummy-backup",
            plugin_id=plugin.id,
            action="trigger_job",
            input_schema={
                "type": "object",
                "required": ["backup_bucket"],
                "properties": {"backup_bucket": {"type": "string"}},
            },
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"response": "Okay.", "tool_calls": []}

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    def fake_policy(*args, **kwargs):
        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_launch(*args, **kwargs):
        return {
            "run_id": "22222222-2222-2222-2222-222222222222",
            "status": "running",
            "summary": "Run accepted and dispatched to orchestrator workers.",
        }

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)
    monkeypatch.setattr("apps.api.app.chat_tools.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.chat_tools.launch_v1_run", fake_launch)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "trigger workflow jenkins-dummy-backup with backup_bucket as dummy"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_results"]
    assert payload["tool_results"][-1]["action"] == "workflow.run"
    assert payload["tool_results"][-1]["status"] == "ok"


def test_chat_parses_quoted_params_with_spaces(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    with session_scope() as session:
        plugin = Plugin(
            name="jenkins",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_job": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="jenkins-dummy-backup",
            plugin_id=plugin.id,
            action="trigger_job",
            input_schema={
                "type": "object",
                "required": ["backup_bucket"],
                "properties": {"backup_bucket": {"type": "string"}},
            },
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"response": "Okay.", "tool_calls": []}

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    def fake_policy(*args, **kwargs):
        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_launch(*args, **kwargs):
        return {
            "run_id": "33333333-3333-3333-3333-333333333333",
            "status": "running",
            "summary": "Run accepted and dispatched to orchestrator workers.",
        }

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)
    monkeypatch.setattr("apps.api.app.chat_tools.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.chat_tools.launch_v1_run", fake_launch)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": 'trigger workflow jenkins-dummy-backup with backup_bucket: "primary bucket"'
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_results"]
    assert payload["tool_results"][-1]["action"] == "workflow.run"
    assert payload["tool_results"][-1]["status"] == "ok"


def test_chat_parses_unquoted_params_with_spaces(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    with session_scope() as session:
        plugin = Plugin(
            name="jenkins",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_job": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="jenkins-dummy-backup",
            plugin_id=plugin.id,
            action="trigger_job",
            input_schema={
                "type": "object",
                "required": ["backup_bucket"],
                "properties": {"backup_bucket": {"type": "string"}},
            },
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"response": "Okay.", "tool_calls": []}

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    def fake_policy(*args, **kwargs):
        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_launch(*args, **kwargs):
        return {
            "run_id": "44444444-4444-4444-4444-444444444444",
            "status": "running",
            "summary": "Run accepted and dispatched to orchestrator workers.",
        }

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)
    monkeypatch.setattr("apps.api.app.chat_tools.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.chat_tools.launch_v1_run", fake_launch)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "message": "trigger workflow jenkins-dummy-backup with backup_bucket: primary bucket"
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_results"]
    assert payload["tool_results"][-1]["action"] == "workflow.run"
    assert payload["tool_results"][-1]["status"] == "ok"

def test_chat_approval_get_returns_details(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret, roles=["approver"])

    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-health",
            plugin_id=plugin.id,
            action="trigger_dag",
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()
        run = WorkflowRun(
            workflow_id=workflow.id,
            status="submitted",
            params={},
            environment="prod",
            requested_by="operator-1",
            tenant_id="default",
        )
        session.add(run)
        session.flush()
        approval = Approval(
            workflow_run_id=run.id,
            workflow_id=workflow.id,
            target_type="workflow",
            requested_by="operator-1",
            required_role="approver",
            risk_level="high",
            status="pending",
            tenant_id="default",
        )
        session.add(approval)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Approval details.",
                "tool_calls": [
                    {"action": "approval.get", "params": {"approval_id": str(approval.id)}}
                ],
            }

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Approval details"},
    )
    assert response.status_code == 200
    payload = response.json()
    result = payload["tool_results"][0]["result"]
    assert result["workflow_name"] == "daily-health"
    assert result["environment"] == "prod"


def test_chat_approval_decision_adds_summary(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret, roles=["approver"])

    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-health",
            plugin_id=plugin.id,
            action="trigger_dag",
            created_by="system",
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

    def fake_launch(*args, **kwargs):
        return {
            "run_id": "55555555-5555-5555-5555-555555555555",
            "status": "running",
            "summary": "Run accepted and dispatched to orchestrator workers.",
        }

    monkeypatch.setattr("apps.api.app.chat_tools.launch_v1_run", fake_launch)

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Approved.",
                "tool_calls": [
                    {
                        "action": "approval.decision",
                        "params": {
                            "approval_id": str(approval.id),
                            "decision": "approve",
                        },
                    }
                ],
            }

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Approve the request"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "Approval" in payload["response"]


def test_chat_run_get_returns_details(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret, roles=["admin"])

    with session_scope() as session:
        plugin = Plugin(
            name="airflow",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_dag": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="daily-health",
            plugin_id=plugin.id,
            action="trigger_dag",
            created_by="system",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()
        run = WorkflowRun(
            workflow_id=workflow.id,
            status="submitted",
            params={"dag_id": "infra-refresh"},
            environment="dev",
            requested_by="operator-1",
            tenant_id="default",
        )
        session.add(run)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Run details.",
                "tool_calls": [{"action": "run.get", "params": {"run_id": str(run.id)}}],
            }

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Run details"},
    )
    assert response.status_code == 200
    payload = response.json()
    result = payload["tool_results"][0]["result"]
    assert result["workflow_name"] == "daily-health"
    assert result["environment"] == "dev"


def test_chat_plugin_get_returns_details(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret, roles=["admin"])

    with session_scope() as session:
        plugin = Plugin(
            name="vault-resolver",
            version="v1",
            plugin_type="secret",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"resolve": {}},
            allowed_roles={},
            auth_type="none",
            auth_config={},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()

    class _ChatResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "response": "Plugin details.",
                "tool_calls": [
                    {"action": "plugin.get", "params": {"name": "vault-resolver"}}
                ],
            }

    def fake_post(*args, **kwargs):
        return _ChatResponse()

    monkeypatch.setattr("apps.api.app.routes.chat.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "show me details of vault-resolver"},
    )
    assert response.status_code == 200
    payload = response.json()
    result = payload["tool_results"][0]["result"]
    assert result["name"] == "vault-resolver"
    assert result["plugin_type"] == "secret"
