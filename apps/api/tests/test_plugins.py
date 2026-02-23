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
    db_path = tmp_path / "test_plugins.db"
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


def test_register_and_filter_plugins(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    client = TestClient(create_app())
    response = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "vault-resolver",
            "version": "v1",
            "plugin_type": "secret",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"resolve": {}},
            "auth_type": "bearer",
            "auth_ref": "secretkeyref:plugin:vault-resolver:kv/autonoma#token",
            "auth_config": {"audience": "vault"},
        },
    )
    assert response.status_code == 201

    list_response = client.get(
        "/v1/plugins?plugin_type=secret",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["plugin_type"] == "secret"
    assert payload[0]["auth_type"] == "bearer"
    assert payload[0]["auth_ref"] == "secretkeyref:plugin:vault-resolver:kv/autonoma#token"

    name_response = client.get(
        "/v1/plugins?name=vault-resolver",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert name_response.status_code == 200
    assert name_response.json()[0]["name"] == "vault-resolver"


def test_update_plugin(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)

    client = TestClient(create_app())
    create_response = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "airflow",
            "version": "v1",
            "plugin_type": "workflow",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"trigger": {}},
            "auth_type": "none",
        },
    )
    assert create_response.status_code == 201
    plugin_id = create_response.json()["id"]

    update_response = client.put(
        f"/v1/plugins/{plugin_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "airflow-updated",
            "version": "v2",
            "plugin_type": "workflow",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"trigger": {}, "status": {}},
            "auth_type": "none",
        },
    )
    assert update_response.status_code == 200

    list_response = client.get(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload[0]["name"] == "airflow-updated"
    assert payload[0]["version"] == "v2"


def test_delete_plugin_rejects_when_in_use(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)
    client = TestClient(create_app())

    plugin_response = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "airflow",
            "version": "v1",
            "plugin_type": "workflow",
            "endpoint": "http://plugin-gateway:8002/invoke",
            "actions": {"trigger": {}},
            "auth_type": "none",
        },
    )
    plugin_id = plugin_response.json()["id"]

    workflow_response = client.post(
        "/v1/workflows",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "daily",
            "description": "test",
            "plugin_id": plugin_id,
            "action": "trigger",
        },
    )
    assert workflow_response.status_code == 201

    delete_response = client.delete(
        f"/v1/plugins/{plugin_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert delete_response.status_code == 409


def test_internal_plugin_resolve(tmp_path: Path) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    _configure_db(tmp_path)
    token = _make_token(secret)
    os.environ["SERVICE_TOKEN"] = "service-token"

    client = TestClient(create_app())
    create_response = client.post(
        "/v1/plugins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "mcp-test",
            "version": "v1",
            "plugin_type": "mcp",
            "endpoint": "http://mcp:9000",
            "actions": {"tools/list": {}, "tools/call": {}},
            "auth_type": "none",
        },
    )
    assert create_response.status_code == 201

    resolve_response = client.get(
        "/v1/plugins/internal/resolve?name=mcp-test&plugin_type=mcp",
        headers={"x-service-token": "service-token"},
    )
    assert resolve_response.status_code == 200
    payload = resolve_response.json()
    assert payload["name"] == "mcp-test"
    assert payload["plugin_type"] == "mcp"
