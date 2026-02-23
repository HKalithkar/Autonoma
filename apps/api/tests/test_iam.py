from __future__ import annotations

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
    os.environ["OIDC_ISSUER"] = "https://issuer.example/realms/autonoma"
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
    db_path = tmp_path / "test_iam.db"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    os.environ["DB_AUTO_CREATE"] = "true"
    os.environ["DB_SEED"] = "false"
    reset_db_cache()
    init_db()


def _make_token(secret: bytes, role: str = "admin") -> str:
    return jwt.encode(
        {
            "sub": "admin-1",
            "aud": "autonoma-api",
            "iss": "https://issuer.example/realms/autonoma",
            "realm_access": {"roles": [role]},
        },
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )


def test_iam_status_not_configured(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    os.environ["IAM_PROVIDER"] = ""
    token = _make_token(secret)
    client = TestClient(create_app())
    response = client.get("/v1/iam/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is False


def test_iam_list_users_requires_config(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    os.environ["IAM_PROVIDER"] = ""
    token = _make_token(secret)
    client = TestClient(create_app())
    response = client.get("/v1/iam/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 501


def test_iam_list_users_with_keycloak(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    os.environ["IAM_PROVIDER"] = "keycloak"
    os.environ["IAM_ADMIN_URL"] = "http://keycloak:8080"
    os.environ["IAM_TOKEN_URL"] = "http://keycloak:8080/realms/autonoma/protocol/openid-connect/token"
    os.environ["IAM_CLIENT_ID"] = "admin-cli"
    os.environ["IAM_CLIENT_SECRET"] = "secret"
    os.environ["IAM_REALM"] = "autonoma"

    class _FakeResponse:
        def __init__(self, payload: dict | list) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    def fake_post(url, *args, **kwargs):
        assert "token" in url
        return _FakeResponse({"access_token": "token"})

    def fake_get(url, *args, **kwargs):
        if url.endswith("/users"):
            return _FakeResponse(
                [
                    {
                        "id": "user-1",
                        "username": "demo",
                        "email": "demo@example.com",
                        "enabled": True,
                    }
                ]
            )
        return _FakeResponse([])

    monkeypatch.setattr("apps.api.app.routes.iam.httpx.post", fake_post)
    monkeypatch.setattr("apps.api.app.routes.iam.httpx.get", fake_get)

    token = _make_token(secret)
    client = TestClient(create_app())
    response = client.get("/v1/iam/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["username"] == "demo"


def test_iam_list_user_roles(monkeypatch, tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    os.environ["IAM_PROVIDER"] = "keycloak"
    os.environ["IAM_ADMIN_URL"] = "http://keycloak:8080"
    os.environ["IAM_TOKEN_URL"] = "http://keycloak:8080/realms/autonoma/protocol/openid-connect/token"
    os.environ["IAM_CLIENT_ID"] = "admin-cli"
    os.environ["IAM_CLIENT_SECRET"] = "secret"
    os.environ["IAM_REALM"] = "autonoma"

    class _FakeResponse:
        def __init__(self, payload: dict | list) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    def fake_post(url, *args, **kwargs):
        assert "token" in url
        return _FakeResponse({"access_token": "token"})

    def fake_get(url, *args, **kwargs):
        if url.endswith("/role-mappings/realm"):
            return _FakeResponse([{"id": "role-1", "name": "admin", "description": "Admin"}])
        return _FakeResponse([])

    monkeypatch.setattr("apps.api.app.routes.iam.httpx.post", fake_post)
    monkeypatch.setattr("apps.api.app.routes.iam.httpx.get", fake_get)

    token = _make_token(secret)
    client = TestClient(create_app())
    response = client.get(
        "/v1/iam/users/admin-1/roles", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["name"] == "admin"
