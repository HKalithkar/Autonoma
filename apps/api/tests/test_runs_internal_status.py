from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode

from apps.api.app import auth as auth_module
from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.main import create_app
from apps.api.app.models import Plugin, RuntimeRun, Workflow, WorkflowRun


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
    db_path = tmp_path / "test_runs_internal_status.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()


def test_internal_workflow_status_callback_updates_run_and_runtime(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    os.environ["RUNTIME_V1_RUN_STATUS_SYNC_ENABLED"] = "false"
    init_db()
    token = _make_token(secret, ["admin"])

    run_id = uuid.UUID("66666666-6666-6666-6666-666666666666")
    with session_scope() as session:
        plugin = Plugin(
            name="n8n",
            version="v1",
            plugin_type="workflow",
            endpoint="http://plugin-gateway:8002/invoke",
            actions={"trigger_workflow": {}},
            allowed_roles={},
            auth_type="none",
            auth_ref=None,
            auth_config={"invoke_url": "http://workflow-adapter:9004/invoke"},
            tenant_id="default",
        )
        session.add(plugin)
        session.flush()
        workflow = Workflow(
            name="n8n-status-sync-workflow",
            description="Sync test",
            plugin_id=plugin.id,
            action="trigger_workflow:autonoma-health-check",
            created_by="user-1",
            tenant_id="default",
        )
        session.add(workflow)
        session.flush()
        session.add(
            WorkflowRun(
                id=run_id,
                workflow_id=workflow.id,
                status="running",
                requested_by="user-1",
                requested_by_name="user-1",
                tenant_id="default",
                params={"service_name": "payments"},
                environment="dev",
                gitops={"adapter": "v1_runtime", "runtime_run_id": str(run_id)},
            )
        )
        session.add(
            RuntimeRun(
                id=run_id,
                intent="run workflow",
                status="running",
                environment="dev",
                requester_actor_id="user-1",
                requester_actor_name="user-1",
                run_metadata={},
                correlation_id=str(run_id),
                tenant_id="default",
            )
        )
        session.flush()

    client = TestClient(create_app())
    callback_resp = client.post(
        "/v1/runs/internal/status",
        headers={"x-service-token": "svc-token"},
        json={
            "run_id": str(run_id),
            "status": "succeeded",
            "job_id": "n8n-job-1",
            "plugin": "n8n",
            "tenant_id": "default",
            "details": {"source": "test"},
        },
    )
    assert callback_resp.status_code == 200

    runs_resp = client.get("/v1/runs", headers={"Authorization": f"Bearer {token}"})
    assert runs_resp.status_code == 200
    matching = [item for item in runs_resp.json() if item["id"] == str(run_id)]
    assert matching
    assert matching[0]["status"] == "succeeded"
    assert matching[0]["job_id"] == "n8n-job-1"

    audit_resp = client.get("/v1/audit", headers={"Authorization": f"Bearer {token}"})
    assert audit_resp.status_code == 200
    assert any(event["event_type"] == "workflow.run.completed" for event in audit_resp.json())
