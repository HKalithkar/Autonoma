from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, cast

import httpx
from fastapi import HTTPException, Request, status
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode

from libs.common.context import get_request_context, set_request_context

from .audit import audit_event

CookieSameSite = Literal["lax", "strict", "none"]


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    audience: str
    auth_url: str
    token_url: str
    jwks_url: str
    client_id: str
    client_secret: str | None
    redirect_uri: str
    scopes: str
    allowed_algs: list[str]
    cookie_secure: bool
    cookie_samesite: CookieSameSite
    auth_url_docker: str | None
    ui_base_url: str | None


@dataclass(frozen=True)
class AuthContext:
    actor_id: str
    tenant_id: str
    roles: list[str]
    permissions: list[str]
    username: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> OIDCSettings:
    issuer = os.getenv("OIDC_ISSUER", "").strip()
    auth_url = os.getenv("OIDC_AUTH_URL", "").strip()
    token_url = os.getenv("OIDC_TOKEN_URL", "").strip()
    jwks_url = os.getenv("OIDC_JWKS_URL", "").strip()
    client_id = os.getenv("OIDC_CLIENT_ID", "").strip()
    redirect_uri = os.getenv("OIDC_REDIRECT_URI", "").strip()
    audience = os.getenv("OIDC_AUDIENCE", client_id).strip()
    scopes = os.getenv("OIDC_SCOPES", "openid profile email").strip()
    allowed_algs = os.getenv("OIDC_ALLOWED_ALGS", "RS256").split(",")
    allowed_algs = [alg.strip() for alg in allowed_algs if alg.strip()]
    cookie_secure = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
    cookie_samesite = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    client_secret = os.getenv("OIDC_CLIENT_SECRET")
    auth_url_docker = os.getenv("OIDC_AUTH_URL_DOCKER", "").strip() or None
    ui_base_url = os.getenv("UI_BASE_URL", "").strip() or None

    if (
        not issuer
        or not auth_url
        or not token_url
        or not jwks_url
        or not client_id
        or not redirect_uri
    ):
        raise RuntimeError("OIDC configuration is incomplete")

    if cookie_samesite not in {"lax", "strict", "none"}:
        raise RuntimeError("AUTH_COOKIE_SAMESITE must be lax, strict, or none")
    if cookie_samesite == "none" and not cookie_secure:
        raise RuntimeError("AUTH_COOKIE_SECURE must be true when AUTH_COOKIE_SAMESITE=none")

    return OIDCSettings(
        issuer=issuer,
        audience=audience,
        auth_url=auth_url,
        token_url=token_url,
        jwks_url=jwks_url,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
        allowed_algs=allowed_algs,
        cookie_secure=cookie_secure,
        cookie_samesite=cast(CookieSameSite, cookie_samesite),
        auth_url_docker=auth_url_docker,
        ui_base_url=ui_base_url,
    )


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(48)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")


@lru_cache(maxsize=1)
def _load_static_jwks() -> dict[str, Any] | None:
    raw = os.getenv("OIDC_JWKS_JSON")
    if not raw:
        return None
    return json.loads(raw)


@lru_cache(maxsize=1)
def fetch_jwks(jwks_url: str) -> dict[str, Any]:
    static = _load_static_jwks()
    if static:
        return static
    response = httpx.get(jwks_url, timeout=5.0)
    response.raise_for_status()
    return response.json()


def _select_jwk(jwks: dict[str, Any], kid: str | None) -> dict[str, Any]:
    keys = jwks.get("keys", [])
    if not keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing JWKS keys")
    if kid:
        for key in keys:
            if key.get("kid") == kid:
                return key
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown key id")
    if len(keys) == 1:
        return keys[0]
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing key id")


def _materialize_key(jwk_data: dict[str, Any]) -> bytes:
    if jwk_data.get("kty") == "oct":
        encoded = jwk_data.get("k", "")
        return base64url_decode(encoded.encode("utf-8"))
    key = jwk.construct(jwk_data)
    return key.to_pem()


def validate_jwt(token: str, settings: OIDCSettings) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc
    alg = header.get("alg")
    if alg not in settings.allowed_algs:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported token algorithm",
        )

    jwks = fetch_jwks(settings.jwks_url)
    key_data = _select_jwk(jwks, header.get("kid"))
    key = _materialize_key(key_data)
    try:
        return jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


def get_token_from_request(request: Request) -> str | None:
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return request.cookies.get("autonoma_access_token")


def build_auth_url(settings: OIDCSettings, state: str, verifier: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": settings.scopes,
        "state": state,
        "code_challenge": code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    query = httpx.QueryParams(params)
    return f"{settings.auth_url}?{query}"


def build_auth_url_for_host(
    settings: OIDCSettings,
    state: str,
    verifier: str,
    host: str | None,
) -> str:
    if host and settings.auth_url_docker and host.startswith("web"):
        params = {
            "response_type": "code",
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "scope": settings.scopes,
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        query = httpx.QueryParams(params)
        return f"{settings.auth_url_docker}?{query}"
    return build_auth_url(settings, state, verifier)


def exchange_code(settings: OIDCSettings, code: str, verifier: str) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "client_id": settings.client_id,
        "code_verifier": verifier,
    }
    if settings.client_secret:
        data["client_secret"] = settings.client_secret
    response = httpx.post(settings.token_url, data=data, timeout=5.0)
    response.raise_for_status()
    return response.json()


def exchange_refresh(settings: OIDCSettings, refresh_token: str) -> dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings.client_id,
    }
    if settings.client_secret:
        data["client_secret"] = settings.client_secret
    response = httpx.post(settings.token_url, data=data, timeout=5.0)
    response.raise_for_status()
    return response.json()


def revoke_token(settings: OIDCSettings, token: str) -> None:
    revoke_url = os.getenv("OIDC_REVOCATION_URL", "").strip()
    if not revoke_url:
        return
    data = {
        "token": token,
        "client_id": settings.client_id,
    }
    if settings.client_secret:
        data["client_secret"] = settings.client_secret
    response = httpx.post(revoke_url, data=data, timeout=5.0)
    response.raise_for_status()


def extract_roles(claims: dict[str, Any]) -> list[str]:
    realm_access = claims.get("realm_access", {})
    roles = realm_access.get("roles", [])
    if "roles" in claims:
        roles = list(set(roles) | set(claims.get("roles", [])))
    return [str(role) for role in roles]


def extract_tenant_id(claims: dict[str, Any], request: Request) -> str:
    return str(claims.get("tenant_id") or request.headers.get("x-tenant-id") or "default")


def audit_authn_failure(reason: str) -> None:
    audit_event("authn", "deny", {"reason": reason})


def audit_authz_decision(permission: str, outcome: str) -> None:
    audit_event("authz", outcome, {"permission": permission})


def ensure_token(request: Request) -> dict[str, Any]:
    service_token = request.headers.get("x-service-token")
    if service_token:
        expected = os.getenv("SERVICE_TOKEN")
        if expected and secrets.compare_digest(service_token, expected):
            return {
                "sub": "service:agent-runtime",
                "roles": ["service_audit"],
                "tenant_id": "default",
            }
    settings = get_settings()
    token = get_token_from_request(request)
    if not token:
        audit_authn_failure("missing_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        claims = validate_jwt(token, settings)
    except HTTPException:
        audit_authn_failure("invalid_token")
        raise
    return claims


def update_request_context(request: Request, claims: dict[str, Any]) -> None:
    tenant_id = extract_tenant_id(claims, request)
    actor_id = str(claims.get("sub") or claims.get("preferred_username") or "unknown")
    correlation_id = request.headers.get("x-correlation-id") or get_request_context().correlation_id
    set_request_context(correlation_id=correlation_id, actor_id=actor_id, tenant_id=tenant_id)
