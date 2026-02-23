import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode

from apps.api.app import auth as auth_module
from apps.api.app.db import init_db, reset_db_cache, session_scope
from apps.api.app.main import create_app
from apps.api.app.models import EventIngest, RuntimeEvent, RuntimeRun


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
    db_path = tmp_path / "test_event.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def _make_token(secret: bytes) -> str:
    return jwt.encode(
        {
            "sub": "admin-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["admin"]},
        },
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )


def test_event_webhook_creates_agent_run(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    os.environ["SERVICE_TOKEN"] = "token"
    token = _make_token(secret)

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "plan_id": "plan-1",
                "status": "planned",
                "plan": [{"step_id": "analyze"}],
                "tool_calls": [],
                "memory_refs": [{"ref_type": "vector"}],
                "traces": [],
            }

    def fake_post(*args, **kwargs):
        return _FakeResponse()

    monkeypatch.setattr("apps.api.app.routes.events.httpx.post", fake_post)

    def fake_policy(*args, **kwargs):
        from apps.api.app.policy import PolicyDecision

        return PolicyDecision(allow=True, deny_reasons=[], required_approvals=[])

    monkeypatch.setattr("apps.api.app.routes.events.evaluate_policy", fake_policy)

    client = TestClient(create_app())
    response = client.post(
        "/v1/events/webhook",
        headers={"x-service-token": "token"},
        json={
            "event_type": "alert",
            "severity": "high",
            "summary": "CPU spike",
            "source": "monitoring",
            "details": {"host": "node-1"},
            "environment": "prod",
            "correlation_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 200

    list_response = client.get(
        "/v1/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200
    data = list_response.json()
    assert data
    alert_events = [event for event in data if event["event_type"] == "alert"]
    assert alert_events
    alert = alert_events[0]
    assert alert["actions"]["evaluation"]["verdict"] == "require_approval"
    assert any(step["step"] == "agent_plan" for step in alert["actions"]["trail"])
    assert any(step["step"] == "approval_requested" for step in alert["actions"]["trail"])


def test_event_stream_once_returns_events(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    with session_scope() as session:
        event = EventIngest(
            event_type="chat.run",
            severity="info",
            summary="chat event",
            source="chat",
            details={},
            environment="dev",
            status="completed",
            actions={},
            correlation_id="corr-1",
            tenant_id="default",
        )
        session.add(event)
        session.flush()

    client = TestClient(create_app())
    response = client.get(
        "/v1/events/stream?once=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "chat.run" in response.text


def test_events_list_includes_runtime_events_without_ingest(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    run_id = uuid.uuid4()
    with session_scope() as session:
        run = RuntimeRun(
            id=run_id,
            intent="runtime-test",
            status="running",
            environment="dev",
            requester_actor_id="demo_admin",
            tenant_id="default",
            correlation_id="corr-runtime-1",
            run_metadata={},
        )
        session.add(run)
        event = RuntimeEvent(
            run_id=run_id,
            event_id="evt-runtime-1",
            event_type="run.started",
            schema_version="v1",
            occurred_at=datetime.now(timezone.utc),
            envelope={
                "event_type": "run.started",
                "payload": {"message": "Workflow run started."},
            },
            correlation_id="corr-runtime-1",
            actor_id="demo_admin",
            tenant_id="default",
            visibility_level="tenant",
            redaction="none",
        )
        session.add(event)
        session.flush()

    client = TestClient(create_app())
    response = client.get("/v1/events", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    runtime_events = [item for item in payload if item["source"] == "runtime-orchestrator"]
    assert runtime_events
    assert any(item["event_type"] == "run.started" for item in runtime_events)


def test_event_stream_once_includes_runtime_events_without_ingest(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    run_id = uuid.uuid4()
    with session_scope() as session:
        run = RuntimeRun(
            id=run_id,
            intent="runtime-stream-test",
            status="running",
            environment="dev",
            requester_actor_id="demo_admin",
            tenant_id="default",
            correlation_id="corr-runtime-stream-1",
            run_metadata={},
        )
        session.add(run)
        event = RuntimeEvent(
            run_id=run_id,
            event_id="evt-runtime-stream-1",
            event_type="plan.step.proposed",
            schema_version="v1",
            occurred_at=datetime.now(timezone.utc),
            envelope={
                "event_type": "plan.step.proposed",
                "payload": {"step_key": "step-1"},
            },
            correlation_id="corr-runtime-stream-1",
            actor_id="demo_admin",
            tenant_id="default",
            visibility_level="tenant",
            redaction="none",
        )
        session.add(event)
        session.flush()

    client = TestClient(create_app())
    response = client.get(
        "/v1/events/stream?once=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "plan.step.proposed" in response.text
