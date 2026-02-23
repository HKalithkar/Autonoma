from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode

from apps.api.app import auth as auth_module
from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.main import create_app
from apps.api.app.models import WorkflowRun


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
    db_path = tmp_path / "test_workflows.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()


def test_register_and_trigger_workflow(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

    def fake_policy(*args: Any, **kwargs: Any):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_launch(**kwargs: Any) -> dict[str, str]:
        assert kwargs["metadata"]["execution"]["plugin"] == "airflow"
        assert kwargs["metadata"]["execution"]["action"] == "trigger_dag"
        return {"run_id": "11111111-1111-1111-1111-111111111111", "status": "running"}

    monkeypatch.setattr("apps.api.app.routes.workflows.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.routes.workflows.launch_v1_run", fake_launch)

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
    assert plugin_resp.status_code == 201
    plugin_id = plugin_resp.json()["id"]
    secret_plugin_resp = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "vault-resolver",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"resolve": {}},
            "plugin_type": "secret",
            "auth_type": "bearer",
            "auth_ref": "secretkeyref:plugin:vault-resolver:token",
            "auth_config": {"header": "X-Vault-Token"},
        },
    )
    assert secret_plugin_resp.status_code == 201

    workflow_resp = client.post(
        "/v1/workflows",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "daily-health", "plugin_id": plugin_id, "action": "trigger_dag"},
    )
    assert workflow_resp.status_code == 201
    workflow_id = workflow_resp.json()["id"]

    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"params": {"dag_id": "health"}, "environment": "dev"},
    )
    assert run_resp.status_code == 202
    payload = run_resp.json()
    assert payload["run_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["status"] == "running"
    assert payload["adapter"] == "v1_runtime"


def test_workflow_run_denied_by_policy(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

    def fake_policy(*args: Any, **kwargs: Any):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(
            allow=False,
            deny_reasons=["requires_approval"],
            required_approvals=["human_approval"],
        )

    monkeypatch.setattr("apps.api.app.routes.workflows.evaluate_policy", fake_policy)
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
    secret_plugin_resp = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "vault-resolver",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"resolve": {}},
            "plugin_type": "secret",
            "auth_type": "bearer",
            "auth_ref": "secretkeyref:plugin:vault-resolver:token",
            "auth_config": {"header": "X-Vault-Token"},
        },
    )
    assert secret_plugin_resp.status_code == 201
    workflow_resp = client.post(
        "/v1/workflows",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "daily-health-denied", "plugin_id": plugin_id, "action": "trigger_dag"},
    )
    workflow_id = workflow_resp.json()["id"]
    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"params": {"env": "prod"}, "environment": "prod"},
    )
    assert run_resp.status_code == 202
    payload = run_resp.json()
    assert payload["status"] == "pending_approval"
    assert payload["approval_id"]
    assert payload["required_approvals"] == ["human_approval"]


def test_workflow_run_resolves_secret_refs(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])
    os.environ["PLUGIN_GATEWAY_TOKEN"] = "token"
    os.environ["PLUGIN_GATEWAY_URL"] = "http://plugin-gateway:8002/invoke"

    def fake_policy(*args: Any, **kwargs: Any):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_resolve(
        session,
        params: dict[str, Any],
        *,
        context: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del session, context
        assert params["api_key"] == "secretkeyref:plugin:vault-resolver:kv/autonoma#airflow"
        return (
            {"api_key": "resolved-secret", "dag_id": "health"},
            {"api_key": "[REDACTED]", "dag_id": "health"},
        )

    def fake_launch(**kwargs: Any) -> dict[str, str]:
        execution = kwargs["metadata"]["execution"]
        assert execution["params"]["api_key"] == "resolved-secret"
        assert execution["params"]["dag_id"] == "health"
        return {"run_id": "33333333-3333-3333-3333-333333333333", "status": "running"}

    monkeypatch.setattr("apps.api.app.routes.workflows.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.routes.workflows.resolve_secret_refs", fake_resolve)
    monkeypatch.setattr("apps.api.app.routes.workflows.launch_v1_run", fake_launch)

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
    secret_plugin_resp = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "vault-resolver",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"resolve": {}},
            "plugin_type": "secret",
            "auth_type": "bearer",
            "auth_ref": "secretkeyref:plugin:vault-resolver:token",
            "auth_config": {"header": "X-Vault-Token"},
        },
    )
    assert secret_plugin_resp.status_code == 201
    workflow_resp = client.post(
        "/v1/workflows",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "secreted", "plugin_id": plugin_id, "action": "trigger_dag"},
    )
    workflow_id = workflow_resp.json()["id"]

    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "params": {
                "api_key": "secretkeyref:plugin:vault-resolver:kv/autonoma#airflow",
                "dag_id": "health",
            },
            "environment": "dev",
        },
    )
    assert run_resp.status_code == 202
    assert run_resp.json()["run_id"] == "33333333-3333-3333-3333-333333333333"

    with session_scope() as session:
        run = (
            session.query(WorkflowRun)
            .order_by(WorkflowRun.created_at.desc())
            .first()
        )
        assert run
        assert run.params["api_key"] == "[REDACTED]"
        assert run.params["dag_id"] == "health"


def test_workflow_run_invalid_uuid(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

    client = TestClient(create_app())
    run_resp = client.post(
        "/v1/workflows/not-a-uuid/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"params": {"env": "dev"}, "environment": "dev"},
    )
    assert run_resp.status_code == 400
    assert run_resp.json()["detail"] == "Invalid workflow id"


def test_workflow_run_missing_environment(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

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
        json={"name": "missing-env", "plugin_id": plugin_id, "action": "trigger_dag"},
    )
    workflow_id = workflow_resp.json()["id"]

    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"params": {"env": "dev"}},
    )
    assert run_resp.status_code == 400
    assert run_resp.json()["detail"] == "Missing environment"


def test_workflow_run_invalid_environment(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

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
        json={"name": "invalid-env", "plugin_id": plugin_id, "action": "trigger_dag"},
    )
    workflow_id = workflow_resp.json()["id"]

    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"params": {"env": "dev"}, "environment": "qa"},
    )
    assert run_resp.status_code == 400
    assert run_resp.json()["detail"] == "Invalid environment"


def test_register_workflow_invalid_plugin_id(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

    client = TestClient(create_app())
    workflow_resp = client.post(
        "/v1/workflows",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "daily-health", "plugin_id": "not-a-uuid", "action": "trigger_dag"},
    )
    assert workflow_resp.status_code == 400
    assert workflow_resp.json()["detail"] == "Invalid plugin id"


def test_workflow_run_requires_schema_fields(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    token = _make_token(secret, ["admin"])

    def fake_policy(*args: Any, **kwargs: Any):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    monkeypatch.setattr("apps.api.app.routes.workflows.evaluate_policy", fake_policy)

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
        json={
            "name": "reboot-server",
            "plugin_id": plugin_id,
            "action": "trigger_dag",
            "input_schema": {
                "type": "object",
                "required": ["server_name"],
                "properties": {"server_name": {"type": "string"}},
            },
        },
    )
    workflow_id = workflow_resp.json()["id"]
    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"params": {"reason": "patching"}, "environment": "dev"},
    )
    assert run_resp.status_code == 400
