from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode

from apps.api.app import auth as auth_module
from apps.api.app.db import init_db, reset_db_cache
from apps.api.app.main import create_app


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


def _make_token(secret: bytes, roles: list[str], sub: str) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": roles},
        },
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_approvals.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()


def test_approval_flow(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    admin_token = _make_token(secret, ["admin"], "requester-1")
    approver_token = _make_token(secret, ["approver"], "approver-1")

    def fake_policy(*args: Any, **kwargs: Any):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(
            allow=False,
            deny_reasons=["requires_approval"],
            required_approvals=["human_approval"],
        )

    def fake_launch(**kwargs: Any) -> dict[str, str]:
        assert kwargs["metadata"]["approval_id"]
        return {"run_id": "55555555-5555-5555-5555-555555555555", "status": "submitted"}

    monkeypatch.setattr("apps.api.app.routes.workflows.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.routes.approvals.launch_v1_run", fake_launch)

    client = TestClient(create_app())
    plugin_resp = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "airflow",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"trigger_dag": {}},
        },
    )
    plugin_id = plugin_resp.json()["id"]
    workflow_resp = client.post(
        "/v1/workflows",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "prod-run", "plugin_id": plugin_id, "action": "trigger_dag"},
    )
    workflow_id = workflow_resp.json()["id"]

    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"params": {"env": "prod"}, "environment": "prod"},
    )
    assert run_resp.status_code == 202
    approval_id = run_resp.json()["approval_id"]

    approvals_resp = client.get(
        "/v1/approvals",
        headers={"Authorization": f"Bearer {approver_token}"},
    )
    assert approvals_resp.status_code == 200
    assert approvals_resp.json()[0]["id"] == approval_id

    decision_resp = client.post(
        f"/v1/approvals/{approval_id}/decision",
        headers={"Authorization": f"Bearer {approver_token}"},
        json={"decision": "approve"},
    )
    assert decision_resp.status_code == 200
    assert decision_resp.json()["run_status"] == "submitted"


def test_approval_self_approval_denied(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    admin_token = _make_token(secret, ["admin"], "requester-1")

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
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "airflow",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"trigger_dag": {}},
        },
    )
    plugin_id = plugin_resp.json()["id"]
    workflow_resp = client.post(
        "/v1/workflows",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "prod-run-self", "plugin_id": plugin_id, "action": "trigger_dag"},
    )
    workflow_id = workflow_resp.json()["id"]

    run_resp = client.post(
        f"/v1/workflows/{workflow_id}/runs",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"params": {"env": "prod"}, "environment": "prod"},
    )
    approval_id = run_resp.json()["approval_id"]

    decision_resp = client.post(
        f"/v1/approvals/{approval_id}/decision",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"decision": "approve"},
    )
    assert decision_resp.status_code == 403


def test_approval_invalid_uuid(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_db(tmp_path)
    _configure_oidc(secret)
    init_db()
    approver_token = _make_token(secret, ["approver"], "approver-1")

    client = TestClient(create_app())
    decision_resp = client.post(
        "/v1/approvals/not-a-uuid/decision",
        headers={"Authorization": f"Bearer {approver_token}"},
        json={"decision": "approve"},
    )
    assert decision_resp.status_code == 400
    assert decision_resp.json()["detail"] == "Invalid approval id"
