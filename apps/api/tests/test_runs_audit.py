from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode

from apps.api.app import auth as auth_module
from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.main import create_app
from apps.api.app.models import Plugin, Workflow, WorkflowRun


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


def _make_token(secret: bytes, roles: list[str]) -> str:
    return jwt.encode(
        {
            "sub": "user-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": roles},
        },
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_runs.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()


def test_runs_and_audit_feed(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

    def fake_policy(*args: Any, **kwargs: Any):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_post(*args: Any, **kwargs: Any):
        del args, kwargs
        return {"run_id": "44444444-4444-4444-4444-444444444444", "status": "running"}

    monkeypatch.setattr("apps.api.app.routes.workflows.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.routes.workflows.launch_v1_run", fake_post)

    client = TestClient(create_app())
    plugin_resp = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "airflow",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"trigger_dag": {}},
        },
    )
    plugin_id = plugin_resp.json()["id"]
    workflow_resp = client.post(
        "/v1/workflows",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "audit-run", "plugin_id": plugin_id, "action": "trigger_dag"},
    )
    workflow_id = workflow_resp.json()["id"]

    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "params": {"dag_id": "audit", "api_key": "super-secret"},
            "environment": "dev",
        },
    )
    assert run_resp.status_code == 202

    runs_resp = client.get(
        "/v1/runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert runs_resp.status_code == 200
    runs = runs_resp.json()
    matching = [run for run in runs if run["workflow_name"] == "audit-run"]
    assert matching
    params = matching[0]["params"]
    assert params["dag_id"] == "audit"
    assert params["api_key"] == "REDACTED"

    events_resp = client.get(
        "/v1/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert events_resp.status_code == 200
    events_payload = events_resp.json()
    assert any(event["event_type"] == "workflow.register" for event in events_payload)

    audit_resp = client.get(
        "/v1/audit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert audit_resp.status_code == 200
    events = audit_resp.json()
    assert len(events) >= 1
    assert "source" in events[0]

    delete_resp = client.delete(
        f"/v1/workflows/{workflow_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_resp.status_code == 200


def test_audit_ingest(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

    client = TestClient(create_app())
    ingest_resp = client.post(
        "/v1/audit/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json=[
            {
                "event_type": "plugin.invoke",
                "outcome": "allow",
                "details": {"job_id": "job-123"},
                "correlation_id": "corr-1",
                "actor_id": "service-plugin",
                "tenant_id": "default",
                "source": "plugin-gateway",
            }
        ],
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["count"] == 1

    filter_resp = client.get(
        "/v1/audit?source=PLUGIN&event_type=invoke&outcome=ALLOW",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert filter_resp.status_code == 200
    events = filter_resp.json()
    assert any(event["event_type"] == "plugin.invoke" for event in events)


def test_runs_status_sync_emits_terminal_audit(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])
    os.environ["RUNTIME_V1_RUN_STATUS_SYNC_ENABLED"] = "true"

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
            auth_config={"invoke_url": "http://workflow-adapter:9004/invoke"},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="status-sync-workflow",
            description="Sync test",
            plugin_id=plugin.id,
            action="trigger_dag:dummy",
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()
        run = WorkflowRun(
            id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
            workflow_id=workflow.id,
            status="running",
            requested_by="user-1",
            requested_by_name="user-1",
            tenant_id="default",
            params={"dag_id": "sync"},
            environment="dev",
            gitops={
                "adapter": "v1_runtime",
                "runtime_run_id": "55555555-5555-5555-5555-555555555555",
            },
        )
        session.add(run)
        session.flush()

    def fake_get(*args: Any, **kwargs: Any):
        del args, kwargs

        class _Resp:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return {"status": "succeeded"}

        return _Resp()

    monkeypatch.setattr("apps.api.app.routes.runs.httpx.get", fake_get)

    client = TestClient(create_app())
    runs_resp = client.get("/v1/runs", headers={"Authorization": f"Bearer {token}"})
    assert runs_resp.status_code == 200
    assert any(item["status"] == "succeeded" for item in runs_resp.json())

    audit_resp = client.get("/v1/audit", headers={"Authorization": f"Bearer {token}"})
    assert audit_resp.status_code == 200
    assert any(event["event_type"] == "workflow.run.completed" for event in audit_resp.json())

    events_resp = client.get("/v1/events", headers={"Authorization": f"Bearer {token}"})
    assert events_resp.status_code == 200
    assert any(event["event_type"] == "workflow.run.completed" for event in events_resp.json())
