import json
import os
from pathlib import Path

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


def _configure_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test_memory.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def test_memory_search_proxies(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = jwt.encode(
        {
            "sub": "operator-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["admin"]},
        },
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )

    monkeypatch.setenv("SERVICE_TOKEN", "svc-token")
    captured: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"results": []}

    def fake_post(*args, **kwargs):
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse()

    monkeypatch.setattr("apps.api.app.routes.memory.httpx.post", fake_post)

    client = TestClient(create_app())
    response = client.post(
        "/v1/memory/search",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "test"},
    )
    assert response.status_code == 200
    assert captured["headers"] == {"x-service-token": "svc-token"}

    events_resp = client.get(
        "/v1/events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert any(event["event_type"] == "memory.search" for event in events)
