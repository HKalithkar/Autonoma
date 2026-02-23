from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode

from apps.api.app import auth as auth_module
from apps.api.app.db import init_db, reset_db_cache
from apps.api.app.main import create_app
from apps.api.app.models import RuntimeEvent, RuntimeRun


def _make_token(secret: bytes, claims: dict[str, object], kid: str) -> str:
    return jwt.encode(claims, secret, algorithm="HS256", headers={"kid": kid})


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
    db_path = tmp_path / "test_agent.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def _mock_v1_launch(monkeypatch) -> None:
    def fake_policy(*args, **kwargs):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_launch(*args, **kwargs):
        return {
            "run_id": "11111111-1111-1111-1111-111111111111",
            "status": "running",
            "summary": "Run accepted and dispatched to orchestrator workers.",
            "correlation_id": "corr-1",
            "actor_id": "operator-1",
            "tenant_id": "default",
        }

    monkeypatch.setattr("apps.api.app.routes.agent.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.routes.agent.launch_v1_run", fake_launch)


def test_agent_run_creates_plan(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(
        secret,
        {
            "sub": "operator-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["operator"]},
        },
        "test-key",
    )

    _mock_v1_launch(monkeypatch)

    client = TestClient(create_app())
    response = client.post(
        "/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"goal": "Trigger workflow", "environment": "dev", "tools": []},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "planned"
    assert "run_id" in body


def test_agent_run_uses_v1_in_prod(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(
        secret,
        {
            "sub": "operator-2",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["operator"]},
        },
        "test-key",
    )
    _mock_v1_launch(monkeypatch)

    client = TestClient(create_app())
    response = client.post(
        "/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "goal": "Refresh caches safely",
            "environment": "prod",
            "tools": ["plugin_gateway.invoke"],
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "planned"
    assert payload["adapter"] == "v1"


def test_agent_run_denied_when_policy_denies(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(
        secret,
        {
            "sub": "operator-3",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["operator"]},
        },
        "test-key",
    )
    def deny_policy(*args, **kwargs):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(allow=False, deny_reasons=["policy_deny"], required_approvals=[])

    monkeypatch.setattr("apps.api.app.routes.agent.evaluate_policy", deny_policy)

    client = TestClient(create_app())
    response = client.post(
        "/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "goal": "Delete production clusters",
            "environment": "prod",
            "tools": ["plugin_gateway.invoke"],
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["deny_reasons"] == ["policy_deny"]


def test_agent_run_can_route_to_v1_adapter(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(
        secret,
        {
            "sub": "operator-5",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["operator"]},
        },
        "test-key",
    )
    def fake_policy(*args, **kwargs):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    def fake_launch(*args, **kwargs):
        return {
            "run_id": "run-v1-123",
            "status": "running",
            "summary": "Run accepted and dispatched to orchestrator workers.",
            "correlation_id": "corr-1",
            "actor_id": "operator-5",
            "tenant_id": "default",
        }

    monkeypatch.setattr("apps.api.app.routes.agent.evaluate_policy", fake_policy)
    monkeypatch.setattr("apps.api.app.routes.agent.launch_v1_run", fake_launch)

    client = TestClient(create_app())
    response = client.post(
        "/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"goal": "Trigger workflow", "environment": "dev", "tools": []},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["run_id"] == "run-v1-123"
    assert body["adapter"] == "v1"


def test_agent_runs_list_includes_evaluation(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(
        secret,
        {
            "sub": "operator-4",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["operator"]},
        },
        "test-key",
    )
    _mock_v1_launch(monkeypatch)

    client = TestClient(create_app())
    create_resp = client.post(
        "/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"goal": "Trigger workflow", "environment": "dev", "tools": []},
    )
    assert create_resp.status_code == 201

    list_resp = client.get("/v1/agent/runs", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert isinstance(runs, list)
    assert len(runs) == 1
    assert runs[0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert runs[0]["status"] == "running"
    assert runs[0]["runtime"]["run_id"] == "11111111-1111-1111-1111-111111111111"


def test_agent_runs_list_uses_runtime_status_and_events(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(
        secret,
        {
            "sub": "operator-6",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["operator"]},
        },
        "test-key",
    )
    _mock_v1_launch(monkeypatch)

    client = TestClient(create_app())
    create_resp = client.post(
        "/v1/agent/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"goal": "Trigger workflow", "environment": "dev", "tools": []},
    )
    assert create_resp.status_code == 201

    from apps.api.app.db import session_scope

    with session_scope() as session:
        run_id = UUID("11111111-1111-1111-1111-111111111111")
        run = RuntimeRun(
            id=run_id,
            intent="Trigger workflow",
            status="succeeded",
            environment="dev",
            requester_actor_id="operator-6",
            requester_actor_name=None,
            run_metadata={},
            correlation_id="corr-1",
            tenant_id="default",
        )
        session.add(run)
        session.flush()
        run.status = "succeeded"
        session.add(
            RuntimeEvent(
                run_id=run.id,
                step_id=None,
                event_id="evt-123",
                event_type="run.succeeded",
                schema_version="v1",
                occurred_at=run.updated_at,
                envelope={"payload": {"message": "done"}, "agent_id": "orchestrator_worker"},
                correlation_id=run.correlation_id,
                actor_id=run.requester_actor_id,
                tenant_id=run.tenant_id,
                visibility_level="tenant",
                redaction="none",
            )
        )
        session.flush()

    list_resp = client.get("/v1/agent/runs", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200
    runs = list_resp.json()
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["runtime"]["status"] == "succeeded"
    assert runs[0]["runtime"]["last_event_type"] == "run.succeeded"


def test_agent_config_requires_admin(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(
        secret,
        {
            "sub": "viewer-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["viewer"]},
        },
        "test-key",
    )
    client = TestClient(create_app())
    response = client.get("/v1/agent/configs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_agent_config_rejects_invalid_api_key_ref(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(
        secret,
        {
            "sub": "admin-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["admin"]},
        },
        "test-key",
    )
    client = TestClient(create_app())
    response = client.put(
        "/v1/agent/configs/orchestrator",
        headers={"Authorization": f"Bearer {token}"},
        json={"api_url": "http://llm", "model": "model-1", "api_key_ref": "vault:bad"},
    )
    assert response.status_code == 400
