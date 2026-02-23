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


def _make_token(secret: bytes, claims: dict[str, object], kid: str = "test-key") -> str:
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
    db_path = tmp_path / "test_runs_v1.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def test_v1_runs_endpoints_stub_flow(monkeypatch, tmp_path: Path) -> None:
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
    )
    def fake_post(url: str, *args: Any, **kwargs: Any):
        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {
                    "run_id": "run-123",
                    "status": "running",
                    "summary": "Run accepted and dispatched to orchestrator workers.",
                    "correlation_id": "corr-1",
                    "actor_id": "operator-1",
                    "tenant_id": "default",
                }

        return _Resp()

    def fake_get(url: str, *args: Any, **kwargs: Any):
        params = kwargs.get("params") or {}

        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                if url.endswith("/timeline"):
                    all_events = [
                        {
                            "event_id": "evt-2",
                            "event_type": "plan.step.proposed",
                            "schema_version": "v1",
                            "run_id": "run-123",
                            "timestamp": "2026-02-01T12:00:01Z",
                            "correlation_id": "corr-1",
                            "actor_id": "operator-1",
                            "tenant_id": "default",
                            "agent_id": "reasoning_worker",
                            "payload": {"message": "plan"},
                            "visibility_level": "tenant",
                            "redaction": "none",
                        },
                        {
                            "event_id": "evt-1",
                            "event_type": "run.started",
                            "schema_version": "v1",
                            "run_id": "run-123",
                            "timestamp": "2026-02-01T12:00:00Z",
                            "correlation_id": "corr-1",
                            "actor_id": "operator-1",
                            "tenant_id": "default",
                            "agent_id": "orchestrator_worker",
                            "payload": {"message": "ok"},
                            "visibility_level": "tenant",
                            "redaction": "none",
                        },
                    ]
                    after_event_id = params.get("after_event_id")
                    if after_event_id == "evt-1":
                        all_events = [all_events[0]]
                    return {
                        "run_id": "run-123",
                        "events": all_events,
                    }
                return {
                    "run_id": "run-123",
                    "status": "running",
                    "intent": "Trigger workflow",
                    "environment": "dev",
                    "created_at": "2026-02-01T12:00:00Z",
                    "updated_at": "2026-02-01T12:00:00Z",
                    "correlation_id": "corr-1",
                    "actor_id": "operator-1",
                    "tenant_id": "default",
                    "steps": [],
                }

        return _Resp()

    monkeypatch.setattr("apps.api.app.routes.runs_v1.httpx.post", fake_post)
    monkeypatch.setattr("apps.api.app.routes.runs_v1.httpx.get", fake_get)

    os.environ["SERVICE_TOKEN"] = "svc-token"
    client = TestClient(create_app())

    create_resp = client.post(
        "/v1/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"intent": "Trigger workflow", "environment": "dev"},
    )
    assert create_resp.status_code == 202
    run_id = create_resp.json()["run_id"]

    get_resp = client.get(f"/v1/runs/{run_id}", headers={"Authorization": f"Bearer {token}"})
    assert get_resp.status_code == 200
    assert get_resp.json()["run_id"] == run_id

    timeline_resp = client.get(
        f"/v1/runs/{run_id}/timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert timeline_resp.status_code == 200
    timeline_payload = timeline_resp.json()
    assert timeline_payload["run_id"] == run_id
    assert timeline_payload["events"]
    assert timeline_payload["events"][0]["event_id"] == "evt-1"
    assert timeline_payload["next_event_id"] == "evt-2"

    stream_resp = client.get(
        f"/v1/runs/{run_id}/stream?last_event_id=evt-1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert stream_resp.status_code == 200
    assert "text/event-stream" in stream_resp.headers.get("content-type", "")
    assert "id: evt-2" in stream_resp.text
    assert "event: plan.step.proposed" in stream_resp.text


def test_v1_stream_supports_last_event_id_header(monkeypatch, tmp_path: Path) -> None:
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
    )

    def fake_get(url: str, *args: Any, **kwargs: Any):
        params = kwargs.get("params") or {}

        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                if url.endswith("/timeline"):
                    after_event_id = params.get("after_event_id")
                    events = [
                        {
                            "event_id": "evt-1",
                            "event_type": "run.started",
                            "schema_version": "v1",
                            "run_id": "run-123",
                            "timestamp": "2026-02-01T12:00:00Z",
                            "correlation_id": "corr-1",
                            "actor_id": "operator-1",
                            "tenant_id": "default",
                            "agent_id": "orchestrator_worker",
                            "payload": {"message": "ok"},
                            "visibility_level": "tenant",
                            "redaction": "none",
                        },
                        {
                            "event_id": "evt-2",
                            "event_type": "plan.step.proposed",
                            "schema_version": "v1",
                            "run_id": "run-123",
                            "timestamp": "2026-02-01T12:00:01Z",
                            "correlation_id": "corr-1",
                            "actor_id": "operator-1",
                            "tenant_id": "default",
                            "agent_id": "reasoning_worker",
                            "payload": {"message": "plan"},
                            "visibility_level": "tenant",
                            "redaction": "none",
                        },
                    ]
                    if after_event_id == "evt-1":
                        events = [events[1]]
                    return {"run_id": "run-123", "events": events}
                return {
                    "run_id": "run-123",
                    "status": "running",
                    "intent": "Trigger workflow",
                    "environment": "dev",
                    "created_at": "2026-02-01T12:00:00Z",
                    "updated_at": "2026-02-01T12:00:00Z",
                    "correlation_id": "corr-1",
                    "actor_id": "operator-1",
                    "tenant_id": "default",
                    "steps": [],
                }

        return _Resp()

    def fake_post(url: str, *args: Any, **kwargs: Any):
        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {
                    "run_id": "run-123",
                    "status": "running",
                    "summary": "ok",
                    "correlation_id": "corr-1",
                    "actor_id": "operator-1",
                    "tenant_id": "default",
                }

        return _Resp()

    monkeypatch.setattr("apps.api.app.routes.runs_v1.httpx.get", fake_get)
    monkeypatch.setattr("apps.api.app.routes.runs_v1.httpx.post", fake_post)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    client = TestClient(create_app())

    response = client.get(
        "/v1/runs/run-123/stream",
        headers={"Authorization": f"Bearer {token}", "Last-Event-ID": "evt-1"},
    )
    assert response.status_code == 200
    assert "id: evt-2" in response.text


def test_v1_run_approval_requires_permission(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    operator_token = _make_token(
        secret,
        {
            "sub": "operator-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["operator"]},
        },
    )
    approver_token = _make_token(
        secret,
        {
            "sub": "approver-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["approver"]},
        },
    )
    admin_token = _make_token(
        secret,
        {
            "sub": "admin-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["admin"]},
        },
    )
    client = TestClient(create_app())
    run_id = "run-123"

    denied_resp = client.post(
        f"/v1/runs/{run_id}/approve",
        headers={"Authorization": f"Bearer {operator_token}"},
        json={"reason": "ok"},
    )
    assert denied_resp.status_code == 403

    allowed_resp = client.post(
        f"/v1/runs/{run_id}/approve",
        headers={"Authorization": f"Bearer {approver_token}"},
        json={"reason": "approved"},
    )
    assert allowed_resp.status_code == 200
    assert allowed_resp.json()["decision"] == "approved"

    reject_resp = client.post(
        f"/v1/runs/{run_id}/reject",
        headers={"Authorization": f"Bearer {approver_token}"},
        json={"reason": "rejected"},
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["decision"] == "rejected"

    audit_resp = client.get("/v1/audit", headers={"Authorization": f"Bearer {admin_token}"})
    assert audit_resp.status_code == 200
    audit_payload = audit_resp.json()
    assert any(
        item["event_type"] == "approval.decision"
        and item["details"].get("decision") == "approve"
        and item["details"].get("workflow_run_id") == run_id
        for item in audit_payload
    )
    assert any(
        item["event_type"] == "approval.decision"
        and item["details"].get("decision") == "reject"
        and item["details"].get("workflow_run_id") == run_id
        for item in audit_payload
    )


def test_v1_internal_step_policy_endpoint_requires_service_token(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    client = TestClient(create_app())
    payload = {
        "run_id": "run-1",
        "step_id": "step-1",
        "action": "plugin.invoke",
        "risk_score": 0.1,
        "correlation_id": "corr-1",
        "actor_id": "svc-orchestrator",
        "tenant_id": "tenant-a",
    }

    unauthorized = client.post("/v1/internal/policy/step-evaluate", json=payload)
    assert unauthorized.status_code == 401

    authorized = client.post(
        "/v1/internal/policy/step-evaluate",
        headers={"x-service-token": "svc-token"},
        json=payload,
    )
    assert authorized.status_code == 200
    assert authorized.json()["outcome"] == "allow"


def test_v1_internal_step_policy_endpoint_rejects_invalid_tenant_scope(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "svc-token"
    client = TestClient(create_app())

    response = client.post(
        "/v1/internal/policy/step-evaluate",
        headers={"x-service-token": "svc-token"},
        json={
            "run_id": "run-1",
            "step_id": "step-1",
            "action": "plugin.invoke",
            "risk_score": 0.1,
            "correlation_id": "corr-1",
            "actor_id": "svc-orchestrator",
            "tenant_id": "   ",
        },
    )
    assert response.status_code == 400


def test_v1_contract_file_contains_required_paths() -> None:
    contract_path = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "contracts"
        / "openapi-v1-runs.yaml"
    )
    text = contract_path.read_text(encoding="utf-8")
    for required_path in [
        "/v1/runs:",
        "/v1/runs/{run_id}:",
        "/v1/runs/{run_id}/timeline:",
        "/v1/runs/{run_id}/stream:",
        "/v1/runs/{run_id}/approve:",
        "/v1/runs/{run_id}/reject:",
        "/v1/internal/policy/step-evaluate:",
    ]:
        assert required_path in text
