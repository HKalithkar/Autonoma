from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode

from apps.api.app import auth as auth_module
from apps.api.app import policy as policy_module
from apps.api.app.main import create_app
from apps.api.app.routes import auth as auth_routes


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
    os.environ.pop("OIDC_AUTH_URL_DOCKER", None)
    auth_module.get_settings.cache_clear()
    auth_module._load_static_jwks.cache_clear()
    auth_module.fetch_jwks.cache_clear()


def test_service_token_allows_audit_write(monkeypatch) -> None:
    os.environ["SERVICE_TOKEN"] = "svc-token"
    client = TestClient(create_app())
    response = client.post(
        "/v1/audit/ingest",
        headers={"x-service-token": "svc-token"},
        json=[
            {
                "event_type": "llm.call",
                "outcome": "allow",
                "details": {"model": "demo"},
                "correlation_id": "c1",
                "actor_id": "service",
                "tenant_id": "default",
                "source": "agent-runtime",
            }
        ],
    )
    assert response.status_code == 200


def test_auth_me_requires_token() -> None:
    _configure_oidc(b"test-secret")
    client = TestClient(create_app())
    response = client.get("/v1/auth/me")
    assert response.status_code == 401


def test_auth_me_allows_valid_token() -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    token = _make_token(
        secret,
        {
            "sub": "user-1",
            "preferred_username": "demo_admin",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["viewer"]},
        },
        "test-key",
    )
    client = TestClient(create_app())
    response = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["actor_id"] == "user-1"
    assert payload["username"] == "demo_admin"
    assert "auth:me" in payload["permissions"]


def test_admin_endpoint_requires_admin_role() -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    token = _make_token(
        secret,
        {
            "sub": "user-2",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["viewer"]},
        },
        "test-key",
    )
    client = TestClient(create_app())
    response = client.get("/v1/admin/permissions", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_policy_endpoint_requires_policy_permission() -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    token = _make_token(
        secret,
        {
            "sub": "user-3",
            "aud": "autonoma-api",
            "iss": "https://issuer.example",
            "realm_access": {"roles": ["viewer"]},
        },
        "test-key",
    )
    client = TestClient(create_app())
    response = client.post(
        "/v1/policy/check",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "auth:me"},
    )
    assert response.status_code == 403


def test_policy_check_allows_admin_with_mocked_policy(monkeypatch) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
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

    def fake_evaluate(action, resource, parameters):
        return policy_module.PolicyDecision(
            allow=True,
            deny_reasons=[],
            required_approvals=[],
        )

    monkeypatch.setattr("apps.api.app.routes.policy.evaluate_policy", fake_evaluate)
    client = TestClient(create_app())
    response = client.post(
        "/v1/policy/check",
        headers={"Authorization": f"Bearer {token}"},
        json={"action": "auth:me"},
    )
    assert response.status_code == 200
    assert response.json()["allow"] is True


def test_login_uses_docker_auth_url_for_web_host() -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    os.environ["OIDC_AUTH_URL_DOCKER"] = (
        "http://keycloak:8080/realms/autonoma/protocol/openid-connect/auth"
    )
    auth_module.get_settings.cache_clear()

    client = TestClient(create_app())
    response = client.get("/v1/auth/login", headers={"host": "web:3000"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith(
        "http://keycloak:8080/realms/autonoma/protocol/openid-connect/auth"
    )


def test_callback_redirects_to_ui_base_url(monkeypatch) -> None:
    secret = b"test-secret"
    _configure_oidc(secret)
    os.environ["UI_BASE_URL"] = "http://localhost:3000"
    auth_module.get_settings.cache_clear()

    def fake_exchange(settings, code, verifier):
        return {"access_token": "token-1", "expires_in": 3600}

    monkeypatch.setattr(auth_routes, "exchange_code", fake_exchange)

    client = TestClient(create_app())
    response = client.get(
        "/v1/auth/callback?code=abc&state=state-1",
        cookies={"oidc_state": "state-1", "oidc_code_verifier": "verifier-1"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/"


def test_refresh_requires_csrf(monkeypatch) -> None:
    _configure_oidc(b"test-secret")

    def fake_refresh(*args, **kwargs):
        return {"access_token": "new-token", "expires_in": 3600}

    monkeypatch.setattr(auth_routes, "exchange_refresh", fake_refresh)

    client = TestClient(create_app())
    client.cookies.set("autonoma_refresh_token", "refresh-1")
    response = client.post("/v1/auth/refresh")
    assert response.status_code == 403


def test_refresh_sets_access_cookie(monkeypatch) -> None:
    _configure_oidc(b"test-secret")

    def fake_refresh(*args, **kwargs):
        return {
            "access_token": "new-token",
            "expires_in": 3600,
            "refresh_token": "refresh-2",
            "refresh_expires_in": 7200,
        }

    monkeypatch.setattr(auth_routes, "exchange_refresh", fake_refresh)

    client = TestClient(create_app())
    client.cookies.set("autonoma_refresh_token", "refresh-1")
    client.cookies.set("autonoma_csrf", "csrf-1")
    response = client.post("/v1/auth/refresh", headers={"x-csrf-token": "csrf-1"})
    assert response.status_code == 204
    cookies = response.headers.get("set-cookie", "")
    assert "autonoma_access_token" in cookies
